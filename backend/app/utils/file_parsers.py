"""Document parsing via docling-serve hybrid chunking endpoint.

All document processing is delegated to docling-serve using:
  POST /v1/chunk/hybrid/file/async

This module submits the job, polls until completion, and normalizes returned
chunks into Atlas' internal ChunkData structure.
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ParsedSection:
    """A section from a parsed document."""

    header: str | None
    content: str
    page_number: int | None = None
    label: str | None = None


@dataclass
class ChunkData:
    """A single chunk with metadata."""

    text: str
    section_header: str | None = None
    page_number: int | None = None
    contextualized_text: str | None = None
    token_count: int | None = None
    labels: list[str] = field(default_factory=list)


@dataclass
class DocumentStats:
    """Statistics about the parsed document."""

    num_pages: int | None = None
    num_tables: int = 0
    num_figures: int = 0
    num_headings: int = 0
    num_text_elements: int = 0
    num_list_items: int = 0
    num_code_blocks: int = 0


@dataclass
class ParsedDocument:
    """Result of document parsing."""

    text: str
    sections: list[ParsedSection] = field(default_factory=list)
    page_count: int | None = None
    metadata: dict = field(default_factory=dict)
    chunks: list[ChunkData] = field(default_factory=list)
    stats: DocumentStats = field(default_factory=DocumentStats)


SUPPORTED_FORMATS = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".html",
    ".xml",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
}

_MAX_RETRIES = 2
_RETRY_DELAY = 3.0
_POLL_INTERVAL = 1.5
_POLL_TIMEOUT_S = 600.0


def parse_document(file_path: str, file_type: str) -> ParsedDocument:
    """Parse and chunk a document through docling-serve hybrid chunking."""
    from app.core.config import settings

    ext = file_type.lower()
    if ext not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported file format: {file_type}")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    started = time.perf_counter()
    with open(path, "rb") as f:
        file_bytes = f.read()

    task_id = _submit_hybrid_chunk_job(path, file_bytes, settings)
    result = _poll_hybrid_chunk_result(task_id, settings)

    chunks = _extract_chunks(result)
    if not chunks:
        raise RuntimeError("docling-serve returned no chunks")

    combined_text = "\n\n".join(c.text for c in chunks)
    stats = _extract_stats(result)
    total_time_s = round(time.perf_counter() - started, 2)

    logger.info(
        "docling-hybrid: %s → %s chunks (%ss)",
        path.name,
        len(chunks),
        total_time_s,
    )

    return ParsedDocument(
        text=combined_text,
        metadata={
            "parser": "docling-hybrid-async",
            "filename": path.name,
            "file_type": ext,
            "file_size_bytes": len(file_bytes),
            "task_id": task_id,
            "total_time_s": total_time_s,
        },
        chunks=chunks,
        page_count=stats.num_pages,
        stats=stats,
    )


def _submit_hybrid_chunk_job(path: Path, file_bytes: bytes, settings) -> str:
    url = f"{settings.docling_base_url}/v1/chunk/hybrid/file/async"
    form_data = {
        "do_ocr": str(settings.docling_do_ocr).lower(),
        "do_table_structure": str(settings.docling_do_table_structure).lower(),
        "table_mode": settings.docling_table_mode,
        "do_code_enrichment": str(settings.docling_do_code_enrichment).lower(),
        "images_scale": str(settings.docling_images_scale),
        "max_tokens": str(settings.docling_max_tokens),
        "merge_peers": str(settings.docling_merge_peers).lower(),
        "tokenizer": settings.docling_tokenizer,
    }
    if settings.docling_ocr_lang:
        form_data["ocr_lang"] = settings.docling_ocr_lang

    files = {"files": (path.name, file_bytes, "application/octet-stream")}

    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = httpx.post(
                url,
                data=form_data,
                files=files,
                timeout=httpx.Timeout(connect=30.0, read=120.0, write=60.0, pool=30.0),
            )
            if response.status_code == 200:
                body = response.json()
                task_id = body.get("task_id") or body.get("id") or body.get("job_id")
                if not task_id:
                    raise RuntimeError(f"No task id in response: {body}")
                return str(task_id)

            last_error = RuntimeError(
                f"docling-serve error ({response.status_code}): {response.text}"
            )
            if response.status_code < 500:
                raise last_error
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning("docling-serve timeout submitting chunk job (attempt %s): %s", attempt + 1, e)
        except RuntimeError:
            raise
        except Exception as e:
            last_error = e
            logger.warning("docling-serve submit error (attempt %s): %s", attempt + 1, e)

        if attempt < _MAX_RETRIES:
            time.sleep(_RETRY_DELAY)

    raise RuntimeError(
        f"docling-serve failed to submit chunk job after {_MAX_RETRIES + 1} attempts: {last_error}"
    )


def _poll_hybrid_chunk_result(task_id: str, settings) -> dict[str, Any]:
    deadline = time.monotonic() + _POLL_TIMEOUT_S
    base = settings.docling_base_url.rstrip("/")

    candidate_urls = [
        f"{base}/v1/tasks/{task_id}",
        f"{base}/v1/task/{task_id}",
        f"{base}/v1/jobs/{task_id}",
        f"{base}/v1/result/{task_id}",
    ]

    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)) as client:
        while time.monotonic() < deadline:
            last_non_404: httpx.Response | None = None
            for url in candidate_urls:
                resp = client.get(url)
                if resp.status_code == 404:
                    continue
                last_non_404 = resp
                break

            if last_non_404 is None:
                time.sleep(_POLL_INTERVAL)
                continue

            if last_non_404.status_code >= 400:
                raise RuntimeError(
                    f"docling-serve poll failed ({last_non_404.status_code}): {last_non_404.text}"
                )

            body = last_non_404.json()
            status = str(body.get("status") or body.get("state") or "").lower()

            if status in {"succeeded", "success", "completed", "done", "finished"}:
                return body.get("result") or body

            if status in {"failed", "error", "cancelled", "canceled"}:
                details = body.get("error") or body.get("message") or body
                raise RuntimeError(f"docling-serve async job failed: {details}")

            if any(k in body for k in ("chunks", "hybrid_chunks", "chunk_results")):
                return body

            time.sleep(_POLL_INTERVAL)

    raise TimeoutError(f"Timeout waiting for docling-serve async chunk job {task_id}")


def _extract_chunks(result: dict[str, Any]) -> list[ChunkData]:
    raw_chunks = (
        result.get("chunks")
        or result.get("hybrid_chunks")
        or result.get("chunk_results")
        or result.get("data", {}).get("chunks")
        or []
    )

    chunks: list[ChunkData] = []
    for item in raw_chunks:
        text = (
            item.get("text")
            or item.get("content")
            or item.get("chunk")
            or item.get("body")
            or ""
        )
        if not text:
            continue

        headings = item.get("headings") or item.get("section_path") or []
        section_header = item.get("section_header")
        if not section_header and isinstance(headings, list) and headings:
            section_header = " > ".join(str(h) for h in headings)

        chunks.append(
            ChunkData(
                text=text,
                section_header=section_header,
                page_number=item.get("page_no") or item.get("page_number"),
                contextualized_text=item.get("contextualized_text") or item.get("contextualized"),
                token_count=item.get("token_count"),
                labels=item.get("labels") or [],
            )
        )

    return chunks


def _extract_stats(result: dict[str, Any]) -> DocumentStats:
    stats_data = result.get("stats") or result.get("metadata", {}).get("stats") or {}
    return DocumentStats(
        num_pages=stats_data.get("num_pages") or stats_data.get("pages"),
        num_tables=stats_data.get("num_tables", 0),
        num_figures=stats_data.get("num_figures", 0),
        num_headings=stats_data.get("num_headings", 0),
        num_text_elements=stats_data.get("num_text_elements", 0),
        num_list_items=stats_data.get("num_list_items", 0),
        num_code_blocks=stats_data.get("num_code_blocks", 0),
    )
