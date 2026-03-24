"""
Docling API - Document parsing and chunking as a REST service.

Wraps the Docling ML pipeline (layout analysis, table structure recognition,
HybridChunker) behind a simple HTTP API so the main Atlas backend can stay
lightweight and free of heavy ML dependencies.
"""

import logging
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Docling API", version="1.0.0")

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class SectionResponse(BaseModel):
    header: str | None = None
    content: str
    page_number: int | None = None


class ChunkResponse(BaseModel):
    text: str
    section_header: str | None = None
    page_number: int | None = None
    contextualized_text: str | None = None


class ConvertResponse(BaseModel):
    text: str
    sections: list[SectionResponse] = []
    page_count: int | None = None
    metadata: dict = {}
    chunks: list[ChunkResponse] = []


# ---------------------------------------------------------------------------
# Docling pipeline (lazy-initialized)
# ---------------------------------------------------------------------------

_converter = None


def _get_converter():
    """Lazy-initialize the Docling DocumentConverter."""
    global _converter
    if _converter is not None:
        return _converter

    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.base_models import InputFormat

    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.do_ocr = os.environ.get("DOCLING_DO_OCR", "true").lower() == "true"
    pipeline_opts.do_table_structure = os.environ.get("DOCLING_DO_TABLE_STRUCTURE", "true").lower() == "true"

    table_mode = os.environ.get("DOCLING_TABLE_MODE", "fast")
    if table_mode == "accurate":
        pipeline_opts.table_structure_options.mode = TableFormerMode.ACCURATE
    else:
        pipeline_opts.table_structure_options.mode = TableFormerMode.FAST

    device = os.environ.get("DOCLING_ACCELERATOR_DEVICE", "auto")
    if device != "auto":
        pipeline_opts.accelerator_options.device = device

    _converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts),
        }
    )
    logger.info("Docling DocumentConverter initialized")
    return _converter


def _docling_doc_to_sections(doc) -> list[SectionResponse]:
    """Extract sections from a DoclingDocument."""
    sections = []
    try:
        for item, _level in doc.iterate_items():
            text = ""
            header = None
            page_number = None

            if hasattr(item, "text"):
                text = item.text or ""
            elif hasattr(item, "export_to_markdown"):
                text = item.export_to_markdown()

            if not text.strip():
                continue

            item_type = getattr(item, "label", None) or type(item).__name__
            if "heading" in str(item_type).lower():
                continue

            prov = getattr(item, "prov", None)
            if prov and len(prov) > 0:
                page_number = getattr(prov[0], "page_no", None)

            headings = _get_parent_headings(doc, item)
            if headings:
                header = " > ".join(headings)

            sections.append(SectionResponse(
                header=header,
                content=text.strip(),
                page_number=page_number,
            ))
    except Exception as e:
        logger.warning(f"Error extracting sections: {e}")
        md = doc.export_to_markdown()
        if md.strip():
            sections.append(SectionResponse(header=None, content=md.strip()))

    return sections


def _get_parent_headings(doc, item) -> list[str]:
    """Walk up the document tree to collect parent heading texts."""
    headings = []
    try:
        current = item
        for _ in range(10):
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


def _get_page_count(doc) -> int | None:
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


def _chunk_document(doc, max_tokens: int, merge_peers: bool, tokenizer: str) -> list[ChunkResponse]:
    """Chunk a DoclingDocument using HybridChunker."""
    from docling_core.transforms.chunker import HybridChunker

    chunker = HybridChunker(
        tokenizer=tokenizer,
        max_tokens=max_tokens,
        merge_peers=merge_peers,
    )

    chunks = []
    for chunk in chunker.chunk(doc):
        contextualized = chunker.contextualize(chunk)

        section_header = None
        page_number = None

        meta = getattr(chunk, "meta", None)
        if meta:
            headings = getattr(meta, "headings", None)
            if headings:
                section_header = " > ".join(headings)

            doc_items = getattr(meta, "doc_items", None)
            if doc_items:
                for item in doc_items:
                    prov = getattr(item, "prov", None)
                    if prov and len(prov) > 0:
                        page_no = getattr(prov[0], "page_no", None)
                        if page_no:
                            page_number = page_no
                            break

        chunk_text = getattr(chunk, "text", "") or str(chunk)

        chunks.append(ChunkResponse(
            text=chunk_text,
            section_header=section_header,
            page_number=page_number,
            contextualized_text=contextualized,
        ))

    return chunks


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/convert", response_model=ConvertResponse)
async def convert(
    file: UploadFile = File(...),
    max_tokens: int = Form(512),
    merge_peers: bool = Form(True),
    tokenizer: str = Form(""),
):
    """
    Parse and chunk a document using the Docling ML pipeline.

    Accepts any format supported by Docling (PDF, DOCX, XLSX, PPTX, HTML, etc.).
    Returns parsed text, sections, and ready-to-embed chunks.
    """
    if not tokenizer:
        tokenizer = os.environ.get("DOCLING_DEFAULT_TOKENIZER", "bert-base-uncased")

    suffix = Path(file.filename or "document").suffix.lower()
    content = await file.read()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        converter = _get_converter()
        logger.info(f"Converting: {file.filename} ({len(content)} bytes)")
        result = converter.convert(tmp_path)
        doc = result.document

        md_text = doc.export_to_markdown()
        sections = _docling_doc_to_sections(doc)
        page_count = _get_page_count(doc)
        chunks = _chunk_document(doc, max_tokens, merge_peers, tokenizer)

        logger.info(
            f"Converted {file.filename}: {len(sections)} sections, "
            f"{len(chunks)} chunks, {page_count or '?'} pages"
        )

        return ConvertResponse(
            text=md_text,
            sections=sections,
            page_count=page_count,
            metadata={"parser": "docling"},
            chunks=chunks,
        )
    except Exception as e:
        logger.error(f"Docling conversion failed for {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Document conversion failed: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
