from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

from ..config import settings
from ..runtime_config import runtime_config_store
from .adapters import PlatformAdapter
from .rubric_files import RubricFileError, extract_docx_text


class PdfProcessingError(RuntimeError):
    pass


@dataclass
class ParsedDocuments:
    text: str
    selected_files: list[dict[str, Any]]
    ignored_files: list[dict[str, Any]]
    content_hash: str
    original_characters: int
    was_truncated: bool


class PdfProcessor:
    async def collect_and_parse(
        self,
        adapter: PlatformAdapter,
        *,
        job_id: str,
        student_id: str,
        files: list[dict[str, Any]],
        download_file: Optional[
            Callable[[str], Awaitable[tuple[bytes, str]]]
        ] = None,
    ) -> ParsedDocuments:
        config = runtime_config_store.load()
        downloader = download_file or adapter.download_file
        candidates: list[dict[str, Any]] = []
        zip_candidates: list[dict[str, Any]] = []
        ignored: list[dict[str, Any]] = []
        for file in files:
            if self._supported_document_suffix(file):
                candidates.append(file)
            elif self._file_suffix(file) == ".zip":
                zip_candidates.append(file)
            else:
                ignored.append({**file, "ignored_reason": "非 PDF/DOCX 附件"})
        if candidates:
            ignored.extend(
                {**file, "ignored_reason": "已有独立报告，未检查压缩包"}
                for file in zip_candidates
            )
        elif zip_candidates:
            candidates, zip_ignored = await self._documents_from_zips(
                downloader,
                zip_candidates,
                config.max_pdf_megabytes * 1024 * 1024,
            )
            ignored.extend(zip_ignored)
        if not candidates:
            available = sorted(
                {
                    Path(str(file.get("name") or "")).suffix.lower().lstrip(".")
                    for file in files
                    if Path(str(file.get("name") or "")).suffix
                }
            )
            detail = f"（现有附件：{', '.join(available).upper()}）" if available else ""
            raise PdfProcessingError(f"未找到 PDF 或 DOCX 报告{detail}")

        target_dir = settings.download_dir / job_id / _safe_segment(student_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        parsed_parts: list[str] = []
        selected: list[dict[str, Any]] = []
        digester = hashlib.sha256()
        try:
            for index, file in enumerate(candidates, start=1):
                embedded_body = file.get("_body")
                if isinstance(embedded_body, bytes):
                    body = embedded_body
                    response_content_type = str(file.get("content_type") or "")
                else:
                    body, response_content_type = await downloader(
                        str(file.get("url") or "")
                    )
                if len(body) > config.max_pdf_megabytes * 1024 * 1024:
                    raise PdfProcessingError(
                        f"附件 {file.get('name') or index} 超过大小限制"
                    )
                suffix = self._supported_document_suffix(file)

                filename = _safe_filename(
                    str(file.get("name") or f"report-{index}{suffix}")
                )
                path = target_dir / f"{index:02d}-{filename}"
                path.write_bytes(body)
                digest = hashlib.sha256(body).hexdigest()
                if suffix == ".pdf":
                    declared_type = str(file.get("content_type") or "").lower()
                    type_is_pdf = (
                        "application/pdf" in response_content_type.lower()
                        or "application/pdf" in declared_type
                        or body.startswith(b"%PDF-")
                    )
                    if not type_is_pdf:
                        ignored.append(
                            {
                                **file,
                                "ignored_reason": "扩展名为 PDF，但内容不是 PDF",
                            }
                        )
                        continue
                    text, used_ocr = await asyncio.to_thread(
                        self._extract_text,
                        path,
                    )
                else:
                    try:
                        text = await asyncio.to_thread(
                            extract_docx_text,
                            body,
                            config.max_pdf_megabytes * 1024 * 1024,
                        )
                    except RubricFileError as exc:
                        raise PdfProcessingError(str(exc)) from exc
                    used_ocr = False
                text = _sanitize_text(text)
                if not text.strip():
                    raise PdfProcessingError(f"文档 {filename} 无法提取有效文本")
                document_type = suffix.lstrip(".")
                parsed_parts.append(
                    f"\n\n===== {document_type.upper()} {index}: {filename} =====\n\n"
                    f"{text.strip()}"
                )
                selected.append(
                    {
                        **_public_file(file),
                        "name": filename,
                        "sha256": digest,
                        "used_ocr": used_ocr,
                        "characters": len(text),
                        "document_type": document_type,
                    }
                )
                digester.update(body)

            if not selected:
                raise PdfProcessingError("没有通过内容校验的 PDF 或 DOCX 报告")
            merged = "".join(parsed_parts).strip()
            original_characters = len(merged)
            merged, was_truncated = _compact_text(
                merged,
                config.max_model_characters,
            )
            return ParsedDocuments(
                text=merged,
                selected_files=selected,
                ignored_files=ignored,
                content_hash=digester.hexdigest(),
                original_characters=original_characters,
                was_truncated=was_truncated,
            )
        finally:
            if not config.keep_downloaded_pdfs:
                shutil.rmtree(target_dir, ignore_errors=True)

    def _extract_text(self, path: Path) -> tuple[str, bool]:
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise PdfProcessingError(f"PDF {path.name} 已加密，无法读取")
            pages = [
                (page.extract_text() or "").strip()
                for page in reader.pages
            ]
        except PdfProcessingError:
            raise
        except Exception as exc:
            raise PdfProcessingError(f"PDF {path.name} 已损坏或格式不受支持") from exc

        useful_chars = sum(len(re.sub(r"\s+", "", page)) for page in pages)
        if useful_chars >= max(120, len(pages) * 30):
            return self._join_pages(pages), False
        return self._ocr(path), True

    @staticmethod
    def _ocr(path: Path) -> str:
        try:
            import fitz
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise PdfProcessingError("扫描版 PDF 需要安装 OCR 依赖") from exc
        if shutil.which("tesseract") is None:
            raise PdfProcessingError(
                "检测到扫描版 PDF，但本机未安装 tesseract OCR"
            )
        document = fitz.open(path)
        pages: list[str] = []
        try:
            for page in document:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes(
                    "RGB",
                    (pixmap.width, pixmap.height),
                    pixmap.samples,
                )
                text = pytesseract.image_to_string(image, lang="chi_sim+eng")
                pages.append(text.strip())
        except Exception as exc:
            raise PdfProcessingError(f"PDF {path.name} OCR 失败") from exc
        finally:
            document.close()
        text = PdfProcessor._join_pages(pages)
        if len(re.sub(r"\s+", "", text)) < 30:
            raise PdfProcessingError(f"PDF {path.name} OCR 后仍无有效文本")
        return text

    @staticmethod
    def _join_pages(pages: list[str]) -> str:
        return "\n\n".join(
            f"--- 第 {index} 页 ---\n{text}"
            for index, text in enumerate(pages, start=1)
        )

    @staticmethod
    def _supported_document_suffix(file: dict[str, Any]) -> str:
        name = str(file.get("name") or "").lower()
        name_suffix = Path(name).suffix
        if name_suffix in {".pdf", ".docx"}:
            return name_suffix
        declared = f".{str(file.get('suffix') or '').lower().lstrip('.')}"
        return declared if declared in {".pdf", ".docx"} else ""

    @staticmethod
    def _file_suffix(file: dict[str, Any]) -> str:
        name_suffix = Path(str(file.get("name") or "")).suffix.lower()
        if name_suffix:
            return name_suffix
        suffix = str(file.get("suffix") or "").lower().lstrip(".")
        return f".{suffix}" if suffix else ""

    async def _documents_from_zips(
        self,
        download_file: Callable[[str], Awaitable[tuple[bytes, str]]],
        zip_files: list[dict[str, Any]],
        max_bytes: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        documents: list[dict[str, Any]] = []
        ignored: list[dict[str, Any]] = []
        total_document_bytes = 0
        seen_document_hashes: set[str] = set()
        for zip_file in zip_files:
            body, _ = await download_file(str(zip_file.get("url") or ""))
            if len(body) > max_bytes:
                ignored.append(
                    {**zip_file, "ignored_reason": "压缩包超过大小限制"}
                )
                continue
            try:
                with ZipFile(BytesIO(body)) as archive:
                    entries = [
                        entry
                        for entry in archive.infolist()
                        if not entry.is_dir()
                        and Path(entry.filename).suffix.lower() in {".pdf", ".docx"}
                    ]
                    for entry in entries:
                        if entry.file_size > max_bytes:
                            ignored.append(
                                {
                                    **zip_file,
                                    "name": f"{zip_file.get('name')}/{entry.filename}",
                                    "ignored_reason": "压缩包内报告超过大小限制",
                                }
                            )
                            continue
                        if total_document_bytes + entry.file_size > max_bytes:
                            raise PdfProcessingError("压缩包内报告总大小超过限制")
                        with archive.open(entry) as source:
                            document_body = source.read(max_bytes + 1)
                        if len(document_body) > max_bytes:
                            raise PdfProcessingError("压缩包内报告超过大小限制")
                        document_hash = hashlib.sha256(document_body).hexdigest()
                        if document_hash in seen_document_hashes:
                            ignored.append(
                                {
                                    **zip_file,
                                    "name": f"{zip_file.get('name')}/{entry.filename}",
                                    "ignored_reason": "压缩包内重复报告",
                                }
                            )
                            continue
                        seen_document_hashes.add(document_hash)
                        total_document_bytes += len(document_body)
                        suffix = Path(entry.filename).suffix.lower()
                        documents.append(
                            {
                                "id": f"{zip_file.get('id') or 'zip'}:{entry.filename}",
                                "name": f"{Path(str(zip_file.get('name') or '附件.zip')).stem}-{Path(entry.filename).name}",
                                "suffix": suffix.lstrip("."),
                                "content_type": (
                                    "application/pdf"
                                    if suffix == ".pdf"
                                    else (
                                        "application/vnd.openxmlformats-officedocument."
                                        "wordprocessingml.document"
                                    )
                                ),
                                "archive_name": zip_file.get("name"),
                                "archive_entry": entry.filename,
                                "_body": document_body,
                            }
                        )
                    if not entries:
                        ignored.append(
                            {
                                **zip_file,
                                "ignored_reason": "压缩包内未找到 PDF/DOCX 报告",
                            }
                        )
            except BadZipFile:
                ignored.append({**zip_file, "ignored_reason": "ZIP 文件已损坏"})
        return documents, ignored


def _safe_filename(value: str) -> str:
    value = Path(value).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return safe[:180] or "report.pdf"


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)[:100] or "unknown"


def _sanitize_text(value: str) -> str:
    return value.encode("utf-8", errors="replace").decode("utf-8")


def _public_file(file: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in file.items() if not key.startswith("_")}


def _compact_text(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    marker = (
        f"\n\n[此处省略部分原文，原文总计 {len(value)} 字，"
        "已按开头、中段、结尾保留代表性内容]\n\n"
    )
    available = limit - len(marker) * 2
    start_size = available * 2 // 5
    middle_size = available // 5
    end_size = available - start_size - middle_size
    middle_start = (len(value) - middle_size) // 2
    compacted = (
        value[:start_size]
        + marker
        + value[middle_start:middle_start + middle_size]
        + marker
        + value[-end_size:]
    )
    return compacted[:limit], True


pdf_processor = PdfProcessor()
