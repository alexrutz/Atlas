"""
Diagnostic logger for LLM calls.

Writes the full input (prompts) and output (responses) of every LLM call
to a dedicated log file: /app/logs/llm_diagnostic.log

This file is tailed by the atlas-llm-diagnostic Docker container, so you
can watch LLM interactions in real-time:
    docker compose logs -f llm-diagnostic

Uses ANSI colors for readability:
  - Cyan: enrichment calls
  - Yellow: RAG/chat calls
  - Green: LLM output
  - Red: errors
"""

import logging
from datetime import datetime, timezone

_diag_logger = logging.getLogger("atlas.llm_diagnostic")

# ANSI colors for terminal output via Docker logs
CYAN = "\033[96m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"


def log_llm_call(
    label: str,
    *,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    enable_thinking: bool | None = None,
    output: str | None = None,
    thinking: str | None = None,
    error: str | None = None,
    is_stream_start: bool = False,
) -> None:
    """
    Log an LLM call with colored output.

    This single function replaces the previous 5 separate log functions.
    The `label` determines the header and color:
      - Labels containing "ENRICHMENT" use cyan
      - Everything else uses yellow

    Examples:
        log_llm_call("ENRICHMENT LLM", system_prompt=..., user_prompt=..., output=...)
        log_llm_call("FINAL RAG LLM", system_prompt=..., user_prompt=..., is_stream_start=True)
        log_llm_call("FINAL RAG LLM (stream complete)", output=..., thinking=...)
        log_llm_call("FREE CHAT LLM", system_prompt=..., user_prompt=..., is_stream_start=True)
        log_llm_call("FREE CHAT LLM (stream complete)", output=..., thinking=...)
    """
    color = CYAN if "ENRICHMENT" in label else YELLOW

    # Header
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    parts = [f"{color}{BOLD}{'=' * 80}\n[{ts}] {label}\n{'=' * 80}{RESET}"]

    # Prompts (if provided)
    if system_prompt is not None:
        parts.append(f"{color}{BOLD}SYSTEM PROMPT:{RESET}")
        parts.append(f"{color}{system_prompt}{RESET}")
    if user_prompt is not None:
        parts.append(f"{color}{BOLD}USER PROMPT:{RESET}")
        parts.append(f"{color}{user_prompt}{RESET}")
    if enable_thinking is not None:
        parts.append(f"{color}{DIM}enable_thinking={enable_thinking}{RESET}")

    # Output section
    if is_stream_start:
        parts.append(f"{color}{DIM}(streaming started...){RESET}")
    elif error:
        parts.append(f"{RED}{BOLD}ERROR:{RESET} {RED}{error}{RESET}")
    else:
        if thinking:
            parts.append(f"{color}{BOLD}THINKING:{RESET}")
            parts.append(f"{DIM}{thinking}{RESET}")
        if output is not None:
            parts.append(f"{GREEN}{BOLD}OUTPUT:{RESET}")
            parts.append(f"{GREEN}{output}{RESET}")

    parts.append(f"{color}{DIM}{'─' * 80}{RESET}")

    _diag_logger.info("\n".join(parts))


def setup_diagnostic_logging(log_path: str = "/app/logs/llm_diagnostic.log") -> None:
    """Set up the diagnostic logger to write to a dedicated file only.

    The sidecar container (llm-diagnostic) tails this file.  We intentionally
    do NOT add a stderr handler here so that the same diagnostic output does
    not appear in *both* ``docker compose logs backend`` and
    ``docker compose logs llm-diagnostic``.
    """
    import os
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    diag = logging.getLogger("atlas.llm_diagnostic")
    diag.setLevel(logging.DEBUG)
    diag.propagate = False

    # Only write to the file — the sidecar container tails it
    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(message)s"))
    diag.addHandler(fh)
