"""Tests for PDF reader tool."""

import tempfile
from pathlib import Path

import pytest


def _has_pymupdf() -> bool:
    try:
        import fitz

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _has_pymupdf(), reason="PyMuPDF not installed")


@pytest.fixture
def sample_pdf() -> Path:
    """Create a simple PDF for testing."""
    import fitz

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Hello PDF World!")
        page.insert_text((50, 100), "This is page 1.")

        page2 = doc.new_page()
        page2.insert_text((50, 50), "Hello Page 2!")
        page2.insert_text((50, 100), "Another paragraph here.")

        doc.save(f.name)
        doc.close()
        return Path(f.name)


@pytest.fixture
def encrypted_pdf(sample_pdf: Path) -> Path:
    """Create an encrypted PDF for testing."""
    import fitz

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        doc = fitz.open(sample_pdf)
        doc.save(
            f.name, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner123", user_pw="user123"
        )
        doc.close()
        return Path(f.name)


class TestPdfReaderTool:
    def test_tool_properties(self) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        assert tool.name == "read_pdf"
        assert "PDF" in tool.description
        assert "path" in tool.parameters["properties"]
        assert "mode" in tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_read_text_default(self, sample_pdf: Path) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        result = await tool.execute(path=str(sample_pdf))

        assert "Hello PDF World" in result
        assert "Page 1" in result
        assert "Total pages: 2" in result

    @pytest.mark.asyncio
    async def test_read_specific_pages(self, sample_pdf: Path) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        result = await tool.execute(path=str(sample_pdf), pages="1")

        assert "Hello PDF World" in result
        assert "Page 2" not in result

    @pytest.mark.asyncio
    async def test_read_page_range(self, sample_pdf: Path) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        result = await tool.execute(path=str(sample_pdf), pages="1-2")

        assert "Page 1" in result
        assert "Page 2" in result

    @pytest.mark.asyncio
    async def test_read_metadata(self, sample_pdf: Path) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        result = await tool.execute(path=str(sample_pdf), mode="metadata")

        assert "PDF Metadata" in result
        assert "Pages: 2" in result

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        result = await tool.execute(path="/nonexistent/file.pdf")

        assert "Error" in result
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_not_a_pdf(self) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"This is not a PDF")
            f.flush()
            tool = PdfReaderTool()
            result = await tool.execute(path=f.name)

        assert "Error" in result
        assert "Not a PDF" in result

    @pytest.mark.asyncio
    async def test_encrypted_pdf_no_password(self, encrypted_pdf: Path) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        result = await tool.execute(path=str(encrypted_pdf))

        assert "Error" in result
        assert "encrypted" in result.lower()

    @pytest.mark.asyncio
    async def test_encrypted_pdf_with_password(self, encrypted_pdf: Path) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        result = await tool.execute(path=str(encrypted_pdf), password="user123")

        assert "Hello PDF World" in result or "Pages: 2" in result

    @pytest.mark.asyncio
    async def test_workspace_restriction(self, sample_pdf: Path) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        workspace = sample_pdf.parent
        tool = PdfReaderTool(workspace=workspace, allowed_dir=workspace)
        result = await tool.execute(path=sample_pdf.name)

        assert "Hello PDF World" in result or "Pages: 2" in result

    @pytest.mark.asyncio
    async def test_tables_mode_empty(self, sample_pdf: Path) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        result = await tool.execute(path=str(sample_pdf), mode="tables")

        assert "No tables found" in result

    def test_parse_page_range(self) -> None:
        from snapagent.agent.tools.pdf import PdfReaderTool

        tool = PdfReaderTool()
        assert tool._parse_page_range("all", 10) == list(range(10))
        assert tool._parse_page_range("1", 10) == [0]
        assert tool._parse_page_range("1-3", 10) == [0, 1, 2]
        assert tool._parse_page_range("1,3,5", 10) == [0, 2, 4]
        assert tool._parse_page_range("1-5,7,9", 10) == [0, 1, 2, 3, 4, 6, 8]

    def cleanup(self, sample_pdf: Path, encrypted_pdf: Path) -> None:
        if sample_pdf.exists():
            sample_pdf.unlink()
        if encrypted_pdf.exists():
            encrypted_pdf.unlink()
