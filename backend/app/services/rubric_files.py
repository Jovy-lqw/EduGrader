from __future__ import annotations

import asyncio
import re
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree


class RubricFileError(RuntimeError):
    pass


@dataclass
class ParsedRubricFile:
    filename: str
    file_type: str
    text: str


class RubricFileParser:
    _supported_suffixes = {".pdf", ".docx", ".txt", ".md"}

    async def parse(
        self,
        filename: str,
        body: bytes,
        *,
        max_file_bytes: int,
        max_characters: int,
    ) -> ParsedRubricFile:
        safe_name = Path(filename).name
        suffix = Path(safe_name).suffix.lower()
        if suffix not in self._supported_suffixes:
            raise RubricFileError("仅支持 PDF、DOCX、TXT 和 MD 文件")
        if not body:
            raise RubricFileError("上传文件为空")
        if len(body) > max_file_bytes:
            raise RubricFileError("评分细则文件超过大小限制")

        if suffix == ".pdf":
            text = await asyncio.to_thread(self._extract_pdf, body)
        elif suffix == ".docx":
            text = await asyncio.to_thread(
                extract_docx_text,
                body,
                max_file_bytes,
            )
        else:
            text = self._decode_text(body)

        text = re.sub(r"\r\n?", "\n", text).strip()
        if not text:
            raise RubricFileError("文件中未提取到有效文本")
        if len(text) > max_characters:
            raise RubricFileError("评分细则文本超过模型上下文限制")
        return ParsedRubricFile(
            filename=safe_name,
            file_type=suffix.lstrip("."),
            text=text,
        )

    @staticmethod
    def _extract_pdf(body: bytes) -> str:
        from .pdf_processing import PdfProcessingError, PdfProcessor

        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                handle.write(body)
                path = Path(handle.name)
            text, _used_ocr = PdfProcessor()._extract_text(path)
            return text
        except PdfProcessingError as exc:
            raise RubricFileError(str(exc)) from exc
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    @staticmethod
    def _decode_text(body: bytes) -> str:
        if body.startswith((b"\xff\xfe", b"\xfe\xff")):
            try:
                return body.decode("utf-16")
            except UnicodeDecodeError as exc:
                raise RubricFileError("文本文件编码无法识别") from exc

        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return body.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise RubricFileError("文本文件编码无法识别")


def extract_docx_text(body: bytes, max_xml_bytes: int) -> str:
    try:
        with zipfile.ZipFile(BytesIO(body)) as archive:
            document = archive.getinfo("word/document.xml")
            if document.file_size > max_xml_bytes:
                raise RubricFileError("DOCX 解压后内容超过大小限制")
            xml = archive.read(document)
    except RubricFileError:
        raise
    except (KeyError, zipfile.BadZipFile, OSError) as exc:
        raise RubricFileError("DOCX 文件已损坏或格式不受支持") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise RubricFileError("DOCX 文档内容无法解析") from exc

    word_namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraph_tag = f"{{{word_namespace}}}p"
    text_tag = f"{{{word_namespace}}}t"
    tab_tag = f"{{{word_namespace}}}tab"
    break_tags = {
        f"{{{word_namespace}}}br",
        f"{{{word_namespace}}}cr",
    }
    paragraphs: list[str] = []
    for paragraph in root.iter(paragraph_tag):
        fragments: list[str] = []
        for node in paragraph.iter():
            if node.tag == text_tag and node.text:
                fragments.append(node.text)
            elif node.tag == tab_tag:
                fragments.append("\t")
            elif node.tag in break_tags:
                fragments.append("\n")
        value = "".join(fragments).strip()
        if value:
            paragraphs.append(value)
    return "\n".join(paragraphs)


rubric_file_parser = RubricFileParser()
