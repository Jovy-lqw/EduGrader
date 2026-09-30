from io import BytesIO
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from backend.app.services.pdf_processing import PdfProcessor, _sanitize_text
from backend.app.services.rubric_files import RubricFileError, RubricFileParser


class RubricFileParserTests(IsolatedAsyncioTestCase):
    async def test_parses_utf8_text(self) -> None:
        parsed = await RubricFileParser().parse(
            "评分细则.txt",
            "内容质量 60 分\n格式规范 40 分".encode(),
            max_file_bytes=1024,
            max_characters=100,
        )

        self.assertEqual(parsed.file_type, "txt")
        self.assertEqual(parsed.text, "内容质量 60 分\n格式规范 40 分")

    async def test_parses_docx_paragraphs(self) -> None:
        document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>内容质量 60 分</w:t></w:r></w:p>
    <w:p><w:r><w:t>格式规范 40 分</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", document)

        parsed = await RubricFileParser().parse(
            "评分细则.docx",
            buffer.getvalue(),
            max_file_bytes=4096,
            max_characters=100,
        )

        self.assertEqual(parsed.file_type, "docx")
        self.assertEqual(parsed.text, "内容质量 60 分\n格式规范 40 分")

    async def test_pdf_uses_existing_extractor(self) -> None:
        with patch(
            "backend.app.services.pdf_processing.PdfProcessor._extract_text",
            return_value=("评分标准", False),
        ) as extract_text:
            parsed = await RubricFileParser().parse(
                "评分细则.pdf",
                b"%PDF-test",
                max_file_bytes=1024,
                max_characters=100,
            )

        self.assertEqual(parsed.text, "评分标准")
        extract_text.assert_called_once()

    async def test_rejects_unsupported_file(self) -> None:
        with self.assertRaisesRegex(RubricFileError, "仅支持"):
            await RubricFileParser().parse(
                "评分细则.doc",
                b"legacy",
                max_file_bytes=1024,
                max_characters=100,
            )

    async def test_rejects_text_over_character_limit(self) -> None:
        with self.assertRaisesRegex(RubricFileError, "模型上下文"):
            await RubricFileParser().parse(
                "评分细则.md",
                b"123456",
                max_file_bytes=1024,
                max_characters=5,
            )

    async def test_student_document_processor_accepts_docx(self) -> None:
        document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>实验分析与结论</w:t></w:r></w:p></w:body>
</w:document>
"""
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", document)

        class Adapter:
            def __init__(self) -> None:
                self.downloaded_urls = []

            async def download_file(self, url):
                self.downloaded_urls.append(url)
                return buffer.getvalue(), "application/octet-stream"

        adapter = Adapter()
        config = SimpleNamespace(
            max_pdf_megabytes=1,
            max_model_characters=1000,
            keep_downloaded_pdfs=False,
        )
        with patch(
            "backend.app.services.pdf_processing.runtime_config_store.load",
            return_value=config,
        ):
            parsed = await PdfProcessor().collect_and_parse(
                adapter,
                job_id="job",
                student_id="student",
                files=[
                    {
                        "name": "实验源码.zip",
                        "url": "mock://source",
                        "suffix": "zip",
                    },
                    {
                        "name": "实验报告.docx",
                        "url": "mock://report",
                        "suffix": "docx",
                    }
                ],
            )

        self.assertIn("实验分析与结论", parsed.text)
        self.assertEqual(parsed.selected_files[0]["document_type"], "docx")
        self.assertEqual(parsed.ignored_files[0]["name"], "实验源码.zip")
        self.assertEqual(adapter.downloaded_urls, ["mock://report"])

    async def test_student_document_processor_reads_report_inside_zip(self) -> None:
        document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>压缩包内实验报告</w:t></w:r></w:p></w:body>
</w:document>
"""
        docx_buffer = BytesIO()
        with ZipFile(docx_buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", document)
        zip_buffer = BytesIO()
        with ZipFile(zip_buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("报告/阶段二报告.docx", docx_buffer.getvalue())
            archive.writestr("阶段二报告-副本.docx", docx_buffer.getvalue())
            archive.writestr("src/main.c", "int main(void) { return 0; }")

        class Adapter:
            async def download_file(self, _url):
                return zip_buffer.getvalue(), "application/zip"

        config = SimpleNamespace(
            max_pdf_megabytes=1,
            max_model_characters=1000,
            keep_downloaded_pdfs=False,
        )
        with patch(
            "backend.app.services.pdf_processing.runtime_config_store.load",
            return_value=config,
        ):
            parsed = await PdfProcessor().collect_and_parse(
                Adapter(),
                job_id="zip-job",
                student_id="zip-student",
                files=[
                    {
                        "id": "archive",
                        "name": "提交材料.zip",
                        "url": "mock://archive",
                        "suffix": "zip",
                    }
                ],
            )

        self.assertIn("压缩包内实验报告", parsed.text)
        self.assertEqual(len(parsed.selected_files), 1)
        self.assertEqual(parsed.selected_files[0]["archive_entry"], "报告/阶段二报告.docx")
        self.assertNotIn("_body", parsed.selected_files[0])
        self.assertEqual(parsed.ignored_files[0]["ignored_reason"], "压缩包内重复报告")

    async def test_student_document_processor_compacts_long_text(self) -> None:
        long_text = "开头" + "A" * 1200 + "中段" + "B" * 1200 + "结尾"
        document = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{long_text}</w:t></w:r></w:p></w:body>
</w:document>
"""
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", document)

        class Adapter:
            async def download_file(self, _url):
                return buffer.getvalue(), "application/octet-stream"

        config = SimpleNamespace(
            max_pdf_megabytes=1,
            max_model_characters=600,
            keep_downloaded_pdfs=False,
        )
        with patch(
            "backend.app.services.pdf_processing.runtime_config_store.load",
            return_value=config,
        ):
            parsed = await PdfProcessor().collect_and_parse(
                Adapter(),
                job_id="long-job",
                student_id="long-student",
                files=[
                    {
                        "name": "长报告.docx",
                        "url": "mock://long-report",
                        "suffix": "docx",
                    }
                ],
            )

        self.assertTrue(parsed.was_truncated)
        self.assertGreater(parsed.original_characters, 600)
        self.assertLessEqual(len(parsed.text), 600)
        self.assertIn("此处省略部分原文", parsed.text)

    def test_sanitizes_invalid_unicode_surrogates(self) -> None:
        self.assertEqual(_sanitize_text("正常\ud800文本"), "正常?文本")
