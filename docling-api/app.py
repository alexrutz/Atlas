"""
Docling API - Document parsing and chunking as a REST service.

Wraps the Docling ML pipeline behind an HTTP API:
- Layout analysis (DocLayNet model) for page element detection
- TableFormer for table structure recognition
- OCR (auto-selected: EasyOCR, Tesseract, or RapidOCR) for scanned documents
- Code enrichment for code block detection
- HybridChunker for token-aware, structure-preserving chunking with
  table header repetition for better RAG embedding quality
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
    flash_attention: bool
    ocr_batch_size: int
    layout_batch_size: int
    table_batch_size: int
    document_timeout: float | None
    supported_formats: list[str]


# ---------------------------------------------------------------------------
# Environment-based configuration
# ---------------------------------------------------------------------------

def _env_bool(key: str, default: bool = True) -> bool:
    return os.environ.get(key, str(default)).lower() in ("true", "1", "yes")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


# Pipeline configuration from environment
OCR_ENABLED = _env_bool("DOCLING_DO_OCR", True)
OCR_BACKEND = os.environ.get("DOCLING_OCR_BACKEND", "auto")  # auto, easyocr, tesseract
TABLE_STRUCTURE = _env_bool("DOCLING_DO_TABLE_STRUCTURE", True)
TABLE_MODE = os.environ.get("DOCLING_TABLE_MODE", "fast")
CODE_ENRICHMENT = _env_bool("DOCLING_DO_CODE_ENRICHMENT", True)
ACCELERATOR_DEVICE = os.environ.get("DOCLING_ACCELERATOR_DEVICE", "auto")
FLASH_ATTENTION = _env_bool("DOCLING_FLASH_ATTENTION", False)
IMAGES_SCALE = _env_float("DOCLING_IMAGES_SCALE", 2.0)
GENERATE_PICTURES = _env_bool("DOCLING_GENERATE_PICTURES", False)
DEFAULT_TOKENIZER = os.environ.get("DOCLING_DEFAULT_TOKENIZER", "")
OCR_LANG = os.environ.get("DOCLING_OCR_LANG", "")  # comma-separated, e.g. "de,en"

# Batch sizes for GPU throughput tuning
OCR_BATCH_SIZE = _env_int("DOCLING_OCR_BATCH_SIZE", 4)
LAYOUT_BATCH_SIZE = _env_int("DOCLING_LAYOUT_BATCH_SIZE", 4)
TABLE_BATCH_SIZE = _env_int("DOCLING_TABLE_BATCH_SIZE", 4)

# Timeout (seconds) per document to prevent runaway conversions
DOCUMENT_TIMEOUT = _env_float("DOCLING_DOCUMENT_TIMEOUT", 300.0)  # 5 minutes


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
        TableStructureOptions,
        AcceleratorOptions,
        AcceleratorDevice,
    )
    from docling.datamodel.base_models import InputFormat

    # --- Accelerator options ---
    accel_opts = AcceleratorOptions()
    if ACCELERATOR_DEVICE != "auto":
        accel_opts.device = ACCELERATOR_DEVICE
    if FLASH_ATTENTION:
        accel_opts.cuda_use_flash_attention2 = True
        logger.info("Flash Attention 2: enabled (requires Ampere+ GPU)")

    # --- PDF pipeline options ---
    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.accelerator_options = accel_opts
    pipeline_opts.do_ocr = OCR_ENABLED
    pipeline_opts.do_table_structure = TABLE_STRUCTURE
    pipeline_opts.images_scale = IMAGES_SCALE
    pipeline_opts.generate_picture_images = GENERATE_PICTURES

    # Document timeout
    if DOCUMENT_TIMEOUT > 0:
        pipeline_opts.document_timeout = DOCUMENT_TIMEOUT

    # GPU batch sizes for throughput
    pipeline_opts.ocr_batch_size = OCR_BATCH_SIZE
    pipeline_opts.layout_batch_size = LAYOUT_BATCH_SIZE
    pipeline_opts.table_batch_size = TABLE_BATCH_SIZE

    # OCR backend configuration
    if OCR_ENABLED:
        lang_list = [l.strip() for l in OCR_LANG.split(",") if l.strip()] if OCR_LANG else []
        _configure_ocr(pipeline_opts, lang_list)

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
            pipeline_opts.table_structure_options = TableStructureOptions(
                mode=TableFormerMode.ACCURATE
            )
        else:
            pipeline_opts.table_structure_options = TableStructureOptions(
                mode=TableFormerMode.FAST
            )
        logger.info(f"Table structure: {TABLE_MODE} mode")

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
    logger.info(
        f"Config: ocr={OCR_ENABLED} ({OCR_BACKEND}), tables={TABLE_STRUCTURE} ({TABLE_MODE}), "
        f"code={CODE_ENRICHMENT}, device={ACCELERATOR_DEVICE}, flash_attn={FLASH_ATTENTION}, "
        f"batch_sizes=ocr:{OCR_BATCH_SIZE}/layout:{LAYOUT_BATCH_SIZE}/table:{TABLE_BATCH_SIZE}, "
        f"timeout={DOCUMENT_TIMEOUT}s"
    )
    return _converter


def _configure_ocr(pipeline_opts, lang_list: list[str]):
    """Configure the OCR backend based on environment settings."""
    if OCR_BACKEND == "tesseract":
        from docling.datamodel.pipeline_options import TesseractCliOcrOptions
        ocr_opts = TesseractCliOcrOptions()
        if lang_list:
            ocr_opts.lang = lang_list
        pipeline_opts.ocr_options = ocr_opts
        logger.info(f"OCR backend: Tesseract CLI (lang={ocr_opts.lang})")

    elif OCR_BACKEND == "easyocr":
        from docling.datamodel.pipeline_options import EasyOcrOptions
        ocr_opts = EasyOcrOptions()
        if lang_list:
            ocr_opts.lang = lang_list
        pipeline_opts.ocr_options = ocr_opts
        logger.info(f"OCR backend: EasyOCR (lang={ocr_opts.lang})")

    else:
        # "auto" — let Docling pick the best available engine
        try:
            from docling.datamodel.pipeline_options import OcrAutoOptions
            ocr_opts = OcrAutoOptions()
            if lang_list:
                ocr_opts.lang = lang_list
            pipeline_opts.ocr_options = ocr_opts
            logger.info(f"OCR backend: auto-select (lang={ocr_opts.lang})")
        except ImportError:
            from docling.datamodel.pipeline_options import EasyOcrOptions
            ocr_opts = EasyOcrOptions()
            if lang_list:
                ocr_opts.lang = lang_list
            pipeline_opts.ocr_options = ocr_opts
            logger.info(f"OCR backend: EasyOCR fallback (lang={ocr_opts.lang})")


# ---------------------------------------------------------------------------
# Document analysis helpers
# ---------------------------------------------------------------------------

def _get_label_str(item) -> str:
    """Extract a normalized label string from a document item."""
    label = getattr(item, "label", None)
    if label is None:
        return ""
    if hasattr(label, "value"):
        return str(label.value).lower()
    if hasattr(label, "name"):
        return label.name.lower()
    return str(label).lower()


def _analyze_document(doc) -> tuple[list[SectionResponse], DocumentStats]:
    """Extract sections and statistics from a DoclingDocument."""
    sections = []
    stats = DocumentStats()
    current_heading = None

    try:
        for item, _level in doc.iterate_items():
            text = ""
            page_number = None

            label_str = _get_label_str(item)

            # Get text content
            if hasattr(item, "text"):
                text = item.text or ""
            elif hasattr(item, "export_to_markdown"):
                try:
                    text = item.export_to_markdown(doc)
                except TypeError:
                    text = item.export_to_markdown()

            if not text.strip():
                continue

            # Get page number from provenance
            prov = getattr(item, "prov", None)
            if prov and len(prov) > 0:
                page_number = getattr(prov[0], "page_no", None)

            # Track stats and decide on section headers
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
            parent_headings = _get_parent_headings(item)
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


def _get_parent_headings(item) -> list[str]:
    """Walk up the document tree to collect parent heading texts."""
    headings = []
    try:
        current = item
        for _ in range(10):
            parent = getattr(current, "parent", None)
            if parent is None:
                break
            label_str = _get_label_str(parent)
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


# ---------------------------------------------------------------------------
# Token counting helper
# ---------------------------------------------------------------------------

_tokenizer_cache: dict[str, object] = {}


def _count_tokens(text: str, tokenizer_name: str) -> int:
    """Count tokens using the specified tokenizer, with caching."""
    try:
        if tokenizer_name not in _tokenizer_cache:
            from docling_core.transforms.chunker.tokenizer.huggingface import (
                HuggingFaceTokenizer,
            )
            _tokenizer_cache[tokenizer_name] = HuggingFaceTokenizer(tokenizer_name)
        return _tokenizer_cache[tokenizer_name].count_tokens(text)
    except Exception:
        return len(text) // 4  # Rough estimate


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_document(
    doc,
    max_tokens: int,
    merge_peers: bool,
    tokenizer: str,
) -> list[ChunkResponse]:
    """Chunk a DoclingDocument using HybridChunker.

    HybridChunker produces token-aware, structure-preserving chunks:
    1. One chunk per document element (respects structural boundaries)
    2. Oversized elements split by token count
    3. Undersized adjacent peers merged (if merge_peers=True)
    4. Contextualize adds heading/caption prefixes for embedding
    5. Table headers repeated when tables span multiple chunks
    """
    from docling_core.transforms.chunker import HybridChunker

    chunker = HybridChunker(
        tokenizer=tokenizer,
        max_tokens=max_tokens,
        merge_peers=merge_peers,
        repeat_table_header=True,  # Repeat header row in split tables for RAG quality
    )

    chunks = []
    for chunk in chunker.chunk(doc):
        contextualized = chunker.contextualize(chunk)

        section_header = None
        page_number = None
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
                    label_str = _get_label_str(item)
                    if label_str and label_str not in labels:
                        labels.append(label_str)

        chunk_text = getattr(chunk, "text", "") or str(chunk)
        token_count = _count_tokens(chunk_text, tokenizer)

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
        flash_attention=FLASH_ATTENTION,
        ocr_batch_size=OCR_BATCH_SIZE,
        layout_batch_size=LAYOUT_BATCH_SIZE,
        table_batch_size=TABLE_BATCH_SIZE,
        document_timeout=DOCUMENT_TIMEOUT if DOCUMENT_TIMEOUT > 0 else None,
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

    Accepts: PDF, DOCX, XLSX, PPTX, HTML, CSV, MD, AsciiDoc, images.

    The pipeline:
    1. **Layout analysis** detects headings, tables, figures, lists, code blocks
    2. **Table structure** (TableFormer) recognizes rows, columns, cell spans
    3. **OCR** extracts text from scanned pages and images
    4. **Code enrichment** detects code blocks and programming languages
    5. **HybridChunker** splits into token-aware chunks with heading context
    6. **Table header repetition** ensures split tables retain column headers

    Returns:
    - **text**: Full document as Markdown
    - **sections**: Structural sections with headers, labels, and page numbers
    - **chunks**: Token-aware chunks ready for embedding (with contextualized text)
    - **stats**: Document statistics (tables, figures, headings, etc.)
    - **metadata**: Parser metadata including timings
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
            "ocr_backend": OCR_BACKEND,
            "table_mode": TABLE_MODE,
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
