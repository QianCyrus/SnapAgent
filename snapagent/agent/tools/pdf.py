"""PDF reader tool using PyMuPDF."""

import base64
import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

from snapagent.agent.tools.base import Tool
from snapagent.agent.tools.filesystem import _resolve_path


class PdfReaderTool(Tool):
    """Tool to read and extract content from PDF files."""

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        max_pages: int = 100,
        extract_images: bool = False,
        image_output_dir: str | None = None,
    ):
        self._workspace = workspace
        self._allowed_dir = allowed_dir
        self._max_pages = max_pages
        self._extract_images = extract_images
        self._image_output_dir = image_output_dir

    @property
    def name(self) -> str:
        return "read_pdf"

    @property
    def description(self) -> str:
        return (
            "Extract text, tables, and metadata from a PDF file. "
            "Returns structured content with page numbers."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the PDF file",
                },
                "mode": {
                    "type": "string",
                    "enum": ["text", "tables", "metadata", "full"],
                    "description": "Extraction mode: text (default), tables, metadata, or full",
                },
                "pages": {
                    "type": "string",
                    "description": "Page range to extract, e.g. '1-5', '1,3,5', 'all' (default)",
                },
                "password": {
                    "type": "string",
                    "description": "Password for encrypted PDF (optional)",
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        mode: str = "text",
        pages: str = "all",
        password: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"
            if file_path.suffix.lower() != ".pdf":
                return f"Error: Not a PDF file: {path}"
        except PermissionError as e:
            return f"Error: {e}"

        try:
            import fitz
        except ImportError:
            return "Error: PyMuPDF not installed. Install with: pip install snapagent-ai[pdf]"

        try:
            doc = fitz.open(file_path)
            if doc.is_encrypted:
                if not password:
                    doc.close()
                    return "Error: PDF is encrypted. Provide password parameter."
                if not doc.authenticate(password):
                    doc.close()
                    return "Error: Invalid password for encrypted PDF."

            if mode == "metadata":
                result = self._extract_metadata(doc)
            elif mode == "tables":
                result = self._extract_tables(doc, pages)
            else:
                result = self._extract_text(doc, pages, mode == "full")

            doc.close()
            return result

        except Exception as e:
            logger.error("PDF extraction error: {}", e)
            return f"Error extracting PDF: {str(e)}"

    def _parse_page_range(self, pages: str, total: int) -> list[int]:
        if pages == "all":
            return list(range(total))

        page_nums = set()
        for part in pages.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                start, end = int(start) - 1, int(end)
                page_nums.update(range(max(0, start), min(total, end)))
            else:
                p = int(part) - 1
                if 0 <= p < total:
                    page_nums.add(p)

        return sorted(page_nums)[: self._max_pages]

    def _extract_text(self, doc, pages: str, include_images: bool) -> str:
        total_pages = len(doc)
        page_nums = self._parse_page_range(pages, total_pages)

        output = []
        output.append(f"PDF: {doc.name}")
        output.append(f"Total pages: {total_pages}")
        output.append(f"Extracting pages: {', '.join(str(p + 1) for p in page_nums)}")
        output.append("-" * 40)

        for page_num in page_nums:
            page = doc[page_num]
            output.append(f"\n[Page {page_num + 1}]\n")

            text = page.get_text("text")
            text = self._clean_text(text)
            if text.strip():
                output.append(text)

            if include_images and self._extract_images:
                images = self._extract_page_images(doc, page, page_num)
                if images:
                    output.append(f"\n[Images on page {page_num + 1}]")
                    output.extend(images)

        return "\n".join(output)

    def _extract_tables(self, doc, pages: str) -> str:
        total_pages = len(doc)
        page_nums = self._parse_page_range(pages, total_pages)

        output = []
        output.append(f"PDF: {doc.name}")
        output.append(f"Extracting tables from {len(page_nums)} pages")
        output.append("-" * 40)

        tables_found = 0
        for page_num in page_nums:
            page = doc[page_num]
            tables = page.find_tables()

            if tables.tables:
                for i, table in enumerate(tables.tables, 1):
                    tables_found += 1
                    output.append(f"\n[Table {tables_found} - Page {page_num + 1}]")

                    df = table.to_pandas()
                    output.append(df.to_string(index=False))
                    output.append("")

        if tables_found == 0:
            output.append("\nNo tables found in the specified pages.")

        return "\n".join(output)

    def _extract_metadata(self, doc) -> str:
        meta = doc.metadata

        output = []
        output.append(f"PDF Metadata: {doc.name}")
        output.append("-" * 40)

        fields = {
            "title": "Title",
            "author": "Author",
            "subject": "Subject",
            "keywords": "Keywords",
            "creator": "Creator",
            "producer": "Producer",
            "creationDate": "Created",
            "modDate": "Modified",
            "format": "Format",
            "encryption": "Encryption",
        }

        for key, label in fields.items():
            value = meta.get(key)
            if value:
                output.append(f"{label}: {value}")

        output.append(f"Pages: {len(doc)}")

        toc = doc.get_toc()
        if toc:
            output.append("\nTable of Contents:")
            for level, title, page in toc[:20]:
                indent = "  " * (level - 1)
                output.append(f"{indent}{title} (p.{page})")
            if len(toc) > 20:
                output.append(f"  ... and {len(toc) - 20} more entries")

        return "\n".join(output)

    def _extract_page_images(self, doc, page, page_num: int) -> list[str]:
        if not self._image_output_dir:
            return []

        output_dir = Path(self._image_output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        results = []
        image_list = page.get_images(full=True)

        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]

            img_filename = f"page{page_num + 1}_img{img_index + 1}.{image_ext}"
            img_path = output_dir / img_filename
            img_path.write_bytes(image_bytes)

            results.append(f"  Saved: {img_path}")

        return results

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
