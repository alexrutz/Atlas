"""
Document parsers with Docling as primary pipeline and legacy fallback.

Docling pipeline: ML-powered parsing with layout analysis, table structure
recognition, and structural document representation (DoclingDocument).

Legacy pipeline: pypdf, python-docx, openpyxl, python-pptx, beautifulsoup4.
Activated when docling is disabled or as automatic fallback on error.

Supported formats: PDF, DOCX, XLSX, PPTX, TXT, MD, CSV, HTML, XML, JSON
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ParsedSection:
    """A section from a parsed document."""
    header: str | None
    content: str
    page_number: int | None = None


@dataclass
class ParsedDocument:
    """Result of document parsing."""
    text: str                                  # Full extracted text
    sections: list[ParsedSection] = field(default_factory=list)
    page_count: int | None = None
    metadata: dict = field(default_factory=dict)
    # Docling-specific: the raw DoclingDocument for downstream chunking
    docling_document: object | None = None


# =============================================================================
# Unified entry point
# =============================================================================

def parse_document(file_path: str, file_type: str) -> ParsedDocument:
    """
    Parse a document, using Docling if enabled, with legacy fallback.

    Args:
        file_path: Path to the file
        file_type: File extension (e.g. '.pdf', '.docx')

    Returns:
        ParsedDocument with extracted text, sections, and optionally
        the raw DoclingDocument for structure-aware chunking.
    """
    from app.core.config import settings

    if settings.docling.enabled:
        try:
            return _parse_with_docling(file_path, file_type)
        except Exception as e:
            logger.warning(f"Docling parsing failed, falling back to legacy: {e}")

    return _parse_with_legacy(file_path, file_type)


# =============================================================================
# Docling pipeline
# =============================================================================

def _parse_with_docling(file_path: str, file_type: str) -> ParsedDocument:
    """Parse a document using Docling's ML-powered pipeline."""
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.base_models import InputFormat
    from app.core.config import settings

    cfg = settings.docling

    # Configure pipeline options for PDFs
    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.do_ocr = cfg.do_ocr
    pipeline_opts.do_table_structure = cfg.do_table_structure
    if cfg.table_mode == "accurate":
        pipeline_opts.table_structure_options.mode = TableFormerMode.ACCURATE
    else:
        pipeline_opts.table_structure_options.mode = TableFormerMode.FAST

    # Set accelerator device
    if cfg.accelerator_device != "auto":
        pipeline_opts.accelerator_options.device = cfg.accelerator_device

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts),
        }
    )

    logger.info(f"Docling: parsing {file_path} (type={file_type})")
    result = converter.convert(file_path)
    doc = result.document

    # Export markdown for full text
    md_text = doc.export_to_markdown()

    # Build sections from the document tree
    sections = _docling_doc_to_sections(doc)

    # Determine page count from provenance
    page_count = _get_docling_page_count(doc)

    logger.info(
        f"Docling: parsed {file_path} → {len(sections)} sections, "
        f"{len(md_text)} chars, {page_count or '?'} pages"
    )

    return ParsedDocument(
        text=md_text,
        sections=sections,
        page_count=page_count,
        metadata={"parser": "docling"},
        docling_document=doc,
    )


def _docling_doc_to_sections(doc) -> list[ParsedSection]:
    """Extract sections from a DoclingDocument's body tree."""
    sections = []

    try:
        for item, _level in doc.iterate_items():
            text = ""
            header = None
            page_number = None

            # Get text content
            if hasattr(item, "text"):
                text = item.text or ""
            elif hasattr(item, "export_to_markdown"):
                text = item.export_to_markdown()

            if not text.strip():
                continue

            # Determine if this is a heading
            item_type = getattr(item, "label", None) or type(item).__name__
            if "heading" in str(item_type).lower():
                header = text.strip()
                continue  # Headings are context, not standalone sections

            # Get page number from provenance
            prov = getattr(item, "prov", None)
            if prov and len(prov) > 0:
                page_number = getattr(prov[0], "page_no", None)

            # Get parent heading context
            parent_headers = _get_parent_headings(doc, item)
            if parent_headers:
                header = " > ".join(parent_headers)

            sections.append(ParsedSection(
                header=header,
                content=text.strip(),
                page_number=page_number,
            ))
    except Exception as e:
        logger.warning(f"Error extracting sections from DoclingDocument: {e}")
        # Fallback: single section from markdown
        md = doc.export_to_markdown()
        if md.strip():
            sections.append(ParsedSection(header=None, content=md.strip()))

    return sections


def _get_parent_headings(doc, item) -> list[str]:
    """Walk up the document tree to collect parent heading texts."""
    headings = []
    try:
        # Navigate parent references to collect heading context
        current = item
        for _ in range(10):  # max depth guard
            parent = getattr(current, "parent", None)
            if parent is None:
                break
            parent_label = getattr(parent, "label", None) or ""
            if "heading" in str(parent_label).lower():
                parent_text = getattr(parent, "text", "") or ""
                if parent_text.strip():
                    headings.insert(0, parent_text.strip())
            current = parent
    except Exception:
        pass
    return headings


def _get_docling_page_count(doc) -> int | None:
    """Get page count from DoclingDocument provenance."""
    try:
        max_page = 0
        for item, _level in doc.iterate_items():
            prov = getattr(item, "prov", None)
            if prov:
                for p in prov:
                    page_no = getattr(p, "page_no", 0) or 0
                    if page_no > max_page:
                        max_page = page_no
        return max_page if max_page > 0 else None
    except Exception:
        return None


# =============================================================================
# Legacy pipeline (backup)
# =============================================================================

def _parse_with_legacy(file_path: str, file_type: str) -> ParsedDocument:
    """Parse using legacy parsers (pre-docling)."""
    from app.utils.file_parsers_legacy import parse_document as legacy_parse
    return legacy_parse(file_path, file_type)
