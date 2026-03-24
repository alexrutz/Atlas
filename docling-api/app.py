"""
Docling API - Document parsing and chunking as a REST service.

Wraps the Docling ML pipeline behind an HTTP API:
- Layout analysis (DocLayNet model) for page element detection
- TableFormer for table structure recognition
- OCR (EasyOCR or Tesseract) for scanned documents
- Code enrichment for code block detection
- HybridChunker for token-aware, structure-preserving chunking
- Image/figure extraction from documents

The main Atlas backend calls this service via HTTP, keeping ML dependencies
isolated in this container.
"""

import logging
import os
import time
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Docling API", version="2.0.0")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class SectionResponse(BaseModel):
    header: str | None = None
    content: str
    page_number: int | None = None
    label: str | None = None


class ChunkResponse(BaseModel):
    text: str
    section_header: str | None = None
    page_number: int | None = None
    contextualized_text: str | None = None
    token_count: int | None = None
    labels: list[str] = []


class DocumentStats(BaseModel):
    """Statistics about the parsed document."""
    num_pages: int | None = None
    num_tables: int = 0
    num_figures: int = 0
    num_headings: int = 0
    num_text_elements: int = 0
    num_list_items: int = 0
    num_code_blocks: int = 0


class ConvertResponse(BaseModel):
    text: str
    sections: list[SectionResponse] = []
    page_count: int | None = None
    metadata: dict = {}
    chunks: list[ChunkResponse] = []
    stats: DocumentStats = DocumentStats()


class PipelineInfoResponse(BaseModel):
    """Current pipeline configuration."""
    ocr_enabled: bool
    ocr_backend: str
    table_structure: bool
    table_mode: str
    code_enrichment: bool
    accelerator_device: str
    supported_formats: list[str]


# ---------------------------------------------------------------------------
# Environment-based configuration
# ---------------------------------------------------------------------------

def _env_bool(key: str, default: bool = True) -> bool:
    return os.environ.get(key, str(default)).lower() in ("true", "1", "yes")


OCR_ENABLED = _env_bool("DOCLING_DO_OCR", True)
OCR_BACKEND = os.environ.get("DOCLING_OCR_BACKEND", "easyocr")  # easyocr or tesseract
TABLE_STRUCTURE = _env_bool("DOCLING_DO_TABLE_STRUCTURE", True)
TABLE_MODE = os.environ.get("DOCLING_TABLE_MODE", "fast")
CODE_ENRICHMENT = _env_bool("DOCLING_DO_CODE_ENRICHMENT", True)
ACCELERATOR_DEVICE = os.environ.get("DOCLING_ACCELERATOR_DEVICE", "auto")
IMAGES_SCALE = float(os.environ.get("DOCLING_IMAGES_SCALE", "2.0"))
GENERATE_PICTURES = _env_bool("DOCLING_GENERATE_PICTURES", False)
DEFAULT_TOKENIZER = os.environ.get("DOCLING_DEFAULT_TOKENIZER", "")
OCR_LANG = os.environ.get("DOCLING_OCR_LANG", "")  # comma-separated, e.g. "de,en"


# ---------------------------------------------------------------------------
# Docling pipeline (lazy-initialized, thread-safe via GIL for init)
# ---------------------------------------------------------------------------

_converter = None
_init_done = False


def _get_converter():
    """Lazy-initialize the Docling DocumentConverter with full pipeline config."""
    global _converter, _init_done
    if _converter is not None:
        return _converter

    t0 = time.time()
    logger.info("Initializing Docling DocumentConverter...")

    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
        EasyOcrOptions,
        TesseractOcrOptions,
        AcceleratorOptions,
    )
    from docling.datamodel.base_models import InputFormat

    # --- PDF pipeline options ---
    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.do_ocr = OCR_ENABLED
    pipeline_opts.do_table_structure = TABLE_STRUCTURE
    pipeline_opts.images_scale = IMAGES_SCALE
    pipeline_opts.generate_picture_images = GENERATE_PICTURES

    # OCR backend
    if OCR_ENABLED:
        if OCR_BACKEND == "tesseract":
            ocr_opts = TesseractOcrOptions()
            if OCR_LANG:
                ocr_opts.lang = [l.strip() for l in OCR_LANG.split(",")]
            pipeline_opts.ocr_options = ocr_opts
            logger.info(f"OCR backend: Tesseract (lang={ocr_opts.lang})")
        else:
            ocr_opts = EasyOcrOptions()
            if OCR_LANG:
                ocr_opts.lang = [l.strip() for l in OCR_LANG.split(",")]
            pipeline_opts.ocr_options = ocr_opts
            logger.info(f"OCR backend: EasyOCR (lang={ocr_opts.lang})")

    # Code enrichment
    if CODE_ENRICHMENT:
        try:
            pipeline_opts.do_code_enrichment = True
            logger.info("Code enrichment: enabled")
        except AttributeError:
            logger.info("Code enrichment: not available in this Docling version")

    # Table structure mode
    if TABLE_STRUCTURE:
        if TABLE_MODE == "accurate":
            pipeline_opts.table_structure_options.mode = TableFormerMode.ACCURATE
        else:
            pipeline_opts.table_structure_options.mode = TableFormerMode.FAST
        logger.info(f"Table structure: {TABLE_MODE} mode")

    # Accelerator
    if ACCELERATOR_DEVICE != "auto":
        pipeline_opts.accelerator_options = AcceleratorOptions(device=ACCELERATOR_DEVICE)
        logger.info(f"Accelerator device: {ACCELERATOR_DEVICE}")

    # --- Build converter with format options ---
    format_options = {
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts),
    }

    _converter = DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.DOCX,
            InputFormat.PPTX,
            InputFormat.XLSX,
            InputFormat.HTML,
            InputFormat.XML,
            InputFormat.CSV,
            InputFormat.MD,
            InputFormat.ASCIIDOC,
            InputFormat.IMAGE,
        ],
        format_options=format_options,
    )

    elapsed = time.time() - t0
    _init_done = True
    logger.info(f"Docling DocumentConverter initialized in {elapsed:.1f}s")
    return _converter


# ---------------------------------------------------------------------------
# Document analysis helpers
# ---------------------------------------------------------------------------

def _analyze_document(doc) -> tuple[list[SectionResponse], DocumentStats]:
    """Extract sections and statistics from a DoclingDocument."""
    sections = []
    stats = DocumentStats()
    current_heading = None

    try:
        for item, _level in doc.iterate_items():
            text = ""
            page_number = None
            label_str = ""

            # Get element label
            label = getattr(item, "label", None)
            if label is not None:
                label_str = str(label).lower() if not isinstance(label, str) else label.lower()
                # For enum-style labels, extract the value name
                if hasattr(label, "value"):
                    label_str = str(label.value).lower()
                elif hasattr(label, "name"):
                    label_str = label.name.lower()

            # Get text content
            if hasattr(item, "text"):
                text = item.text or ""
            elif hasattr(item, "export_to_markdown"):
                text = item.export_to_markdown()

            if not text.strip():
                continue

            # Get page number from provenance
            prov = getattr(item, "prov", None)
            if prov and len(prov) > 0:
                page_number = getattr(prov[0], "page_no", None)

            # Track stats
            if "heading" in label_str or "title" in label_str:
                stats.num_headings += 1
                current_heading = text.strip()
                continue  # Headings are context, not standalone sections
            elif "table" in label_str:
                stats.num_tables += 1
            elif "figure" in label_str or "picture" in label_str:
                stats.num_figures += 1
            elif "list" in label_str:
                stats.num_list_items += 1
            elif "code" in label_str:
                stats.num_code_blocks += 1
            else:
                stats.num_text_elements += 1

            # Build section header from heading hierarchy
            header = current_heading
            parent_headings = _get_parent_headings(doc, item)
            if parent_headings:
                header = " > ".join(parent_headings)

            sections.append(SectionResponse(
                header=header,
                content=text.strip(),
                page_number=page_number,
                label=label_str if label_str else None,
            ))
    except Exception as e:
        logger.warning(f"Error extracting sections: {e}")
        md = doc.export_to_markdown()
        if md.strip():
            sections.append(SectionResponse(header=None, content=md.strip()))

    stats.num_pages = _get_page_count(doc)
    return sections, stats


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
            label_str = str(parent_label).lower()
            if "heading" in label_str or "title" in label_str:
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


def _chunk_document(
    doc,
    max_tokens: int,
    merge_peers: bool,
    tokenizer: str,
    include_labels: bool = True,
) -> list[ChunkResponse]:
    """Chunk a DoclingDocument using HybridChunker.

    HybridChunker produces token-aware, structure-preserving chunks:
    1. One chunk per document element (respects structural boundaries)
    2. Oversized elements split by token count
    3. Undersized adjacent peers merged (if merge_peers=True)
    4. Contextualize adds heading/caption prefixes for embedding
    """
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
        token_count = None
        labels = []

        meta = getattr(chunk, "meta", None)
        if meta:
            # Heading hierarchy
            headings = getattr(meta, "headings", None)
            if headings:
                section_header = " > ".join(headings)

            # Source element metadata
            doc_items = getattr(meta, "doc_items", None)
            if doc_items:
                for item in doc_items:
                    # Page number from first item with provenance
                    if page_number is None:
                        prov = getattr(item, "prov", None)
                        if prov and len(prov) > 0:
                            page_no = getattr(prov[0], "page_no", None)
                            if page_no:
                                page_number = page_no

                    # Collect element labels
                    if include_labels:
                        label = getattr(item, "label", None)
                        if label is not None:
                            label_str = str(label)
                            if hasattr(label, "value"):
                                label_str = str(label.value)
                            elif hasattr(label, "name"):
                                label_str = label.name
                            if label_str and label_str not in labels:
                                labels.append(label_str)

        chunk_text = getattr(chunk, "text", "") or str(chunk)

        # Estimate token count from the tokenizer
        try:
            from docling_core.transforms.chunker.tokenizer import HuggingFaceTokenizer
            tok = HuggingFaceTokenizer(tokenizer)
            token_count = tok.count_tokens(chunk_text)
        except Exception:
            # Rough estimate: ~4 chars per token
            token_count = len(chunk_text) // 4

        chunks.append(ChunkResponse(
            text=chunk_text,
            section_header=section_header,
            page_number=page_number,
            contextualized_text=contextualized,
            token_count=token_count,
            labels=labels,
        ))

    return chunks


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "models_loaded": _init_done,
    }


@app.get("/info", response_model=PipelineInfoResponse)
async def pipeline_info():
    """Return the current pipeline configuration."""
    return PipelineInfoResponse(
        ocr_enabled=OCR_ENABLED,
        ocr_backend=OCR_BACKEND,
        table_structure=TABLE_STRUCTURE,
        table_mode=TABLE_MODE,
        code_enrichment=CODE_ENRICHMENT,
        accelerator_device=ACCELERATOR_DEVICE,
        supported_formats=[
            "pdf", "docx", "pptx", "xlsx", "html", "xml",
            "csv", "md", "asciidoc", "image",
        ],
    )


@app.post("/convert", response_model=ConvertResponse)
async def convert(
    file: UploadFile = File(...),
    max_tokens: int = Form(512),
    merge_peers: bool = Form(True),
    tokenizer: str = Form(""),
):
    """
    Parse and chunk a document using the Docling ML pipeline.

    Accepts: PDF, DOCX, XLSX, PPTX, HTML, XML, CSV, MD, AsciiDoc, images.

    Returns:
    - **text**: Full document as Markdown
    - **sections**: Structural sections with headers, labels, and page numbers
    - **chunks**: Token-aware chunks ready for embedding (with contextualized text)
    - **stats**: Document statistics (tables, figures, headings, etc.)
    - **metadata**: Parser metadata
    """
    if not tokenizer:
        tokenizer = DEFAULT_TOKENIZER or "bert-base-uncased"

    suffix = Path(file.filename or "document").suffix.lower()
    content = await file.read()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        converter = _get_converter()
        t0 = time.time()
        logger.info(f"Converting: {file.filename} ({len(content)} bytes, type={suffix})")

        result = converter.convert(tmp_path)
        doc = result.document
        parse_time = time.time() - t0

        # Export full text as markdown
        md_text = doc.export_to_markdown()

        # Extract sections and statistics
        sections, stats = _analyze_document(doc)

        # Chunk with HybridChunker
        t1 = time.time()
        chunks = _chunk_document(doc, max_tokens, merge_peers, tokenizer)
        chunk_time = time.time() - t1

        # Build metadata
        metadata = {
            "parser": "docling",
            "filename": file.filename,
            "file_type": suffix,
            "file_size_bytes": len(content),
            "parse_time_s": round(parse_time, 2),
            "chunk_time_s": round(chunk_time, 2),
            "total_time_s": round(parse_time + chunk_time, 2),
            "tokenizer": tokenizer,
            "max_tokens": max_tokens,
        }

        logger.info(
            f"Converted {file.filename}: {stats.num_pages or '?'} pages, "
            f"{len(sections)} sections, {len(chunks)} chunks, "
            f"{stats.num_tables} tables, {stats.num_figures} figures "
            f"({parse_time:.1f}s parse + {chunk_time:.1f}s chunk)"
        )

        return ConvertResponse(
            text=md_text,
            sections=sections,
            page_count=stats.num_pages,
            metadata=metadata,
            chunks=chunks,
            stats=stats,
        )
    except Exception as e:
        logger.error(f"Docling conversion failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Document conversion failed: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.on_event("startup")
async def warmup():
    """Pre-load Docling models on startup to avoid cold-start latency."""
    if _env_bool("DOCLING_WARMUP", True):
        logger.info("Warming up Docling models...")
        try:
            _get_converter()
            logger.info("Warmup complete - models loaded")
        except Exception as e:
            logger.warning(f"Warmup failed (models will load on first request): {e}")
