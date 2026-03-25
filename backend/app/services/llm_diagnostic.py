"""
Diagnostic logger for LLM calls.

Writes full input/output of enrichment and RAG LLM calls to a dedicated
log file that is tailed by the atlas-llm-diagnostic sidecar container.
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


def _separator(color: str, label: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    return f"{color}{BOLD}{'=' * 80}\n[{ts}] {label}\n{'=' * 80}{RESET}"


def log_enrichment_call(
    system_prompt: str,
    user_prompt: str,
    output: str,
    error: str | None = None,
) -> None:
    """Log the full enrichment LLM call input and output."""
    parts = [
        _separator(CYAN, "ENRICHMENT LLM"),
        f"{CYAN}{BOLD}SYSTEM PROMPT:{RESET}",
        f"{CYAN}{system_prompt}{RESET}",
        f"{CYAN}{BOLD}USER PROMPT:{RESET}",
        f"{CYAN}{user_prompt}{RESET}",
    ]
    if error:
        parts.append(f"{RED}{BOLD}ERROR:{RESET} {RED}{error}{RESET}")
    else:
        parts.append(f"{GREEN}{BOLD}OUTPUT:{RESET}")
        parts.append(f"{GREEN}{output}{RESET}")
    parts.append(f"{CYAN}{DIM}{'─' * 80}{RESET}")

    msg = "\n".join(parts)
    _diag_logger.info(msg)


def log_rag_call(
    system_prompt: str,
    user_prompt: str,
    enable_thinking: bool,
    output: str | None = None,
    thinking: str | None = None,
    is_stream_start: bool = False,
    error: str | None = None,
) -> None:
    """Log the full RAG/final LLM call input and output."""
    parts = [
        _separator(YELLOW, "FINAL RAG LLM"),
        f"{YELLOW}{BOLD}SYSTEM PROMPT:{RESET}",
        f"{YELLOW}{system_prompt}{RESET}",
        f"{YELLOW}{BOLD}USER PROMPT:{RESET}",
        f"{YELLOW}{user_prompt}{RESET}",
        f"{YELLOW}{DIM}enable_thinking={enable_thinking}{RESET}",
    ]
    if is_stream_start:
        parts.append(f"{YELLOW}{DIM}(streaming started...){RESET}")
    elif error:
        parts.append(f"{RED}{BOLD}ERROR:{RESET} {RED}{error}{RESET}")
    else:
        if thinking:
            parts.append(f"{YELLOW}{BOLD}THINKING:{RESET}")
            parts.append(f"{DIM}{thinking}{RESET}")
        if output is not None:
            parts.append(f"{GREEN}{BOLD}OUTPUT:{RESET}")
            parts.append(f"{GREEN}{output}{RESET}")
    parts.append(f"{YELLOW}{DIM}{'─' * 80}{RESET}")

    msg = "\n".join(parts)
    _diag_logger.info(msg)


def log_rag_stream_complete(
    output: str,
    thinking: str | None = None,
) -> None:
    """Log final output after a streaming RAG call completes."""
    parts = [
        _separator(YELLOW, "FINAL RAG LLM (stream complete)"),
    ]
    if thinking:
        parts.append(f"{YELLOW}{BOLD}THINKING:{RESET}")
        parts.append(f"{DIM}{thinking}{RESET}")
    parts.append(f"{GREEN}{BOLD}OUTPUT:{RESET}")
    parts.append(f"{GREEN}{output}{RESET}")
    parts.append(f"{YELLOW}{DIM}{'─' * 80}{RESET}")

    msg = "\n".join(parts)
    _diag_logger.info(msg)


def log_free_chat_call(
    system_prompt: str,
    user_prompt: str,
    enable_thinking: bool,
    is_stream_start: bool = False,
) -> None:
    """Log a free chat LLM call start."""
    parts = [
        _separator(YELLOW, "FREE CHAT LLM"),
        f"{YELLOW}{BOLD}SYSTEM PROMPT:{RESET}",
        f"{YELLOW}{system_prompt}{RESET}",
        f"{YELLOW}{BOLD}USER PROMPT:{RESET}",
        f"{YELLOW}{user_prompt}{RESET}",
        f"{YELLOW}{DIM}enable_thinking={enable_thinking}{RESET}",
    ]
    if is_stream_start:
        parts.append(f"{YELLOW}{DIM}(streaming started...){RESET}")
    parts.append(f"{YELLOW}{DIM}{'─' * 80}{RESET}")

    msg = "\n".join(parts)
    _diag_logger.info(msg)


def log_free_chat_stream_complete(
    output: str,
    thinking: str | None = None,
) -> None:
    """Log final output after a free chat streaming call completes."""
    parts = [
        _separator(YELLOW, "FREE CHAT LLM (stream complete)"),
    ]
    if thinking:
        parts.append(f"{YELLOW}{BOLD}THINKING:{RESET}")
        parts.append(f"{DIM}{thinking}{RESET}")
    parts.append(f"{GREEN}{BOLD}OUTPUT:{RESET}")
    parts.append(f"{GREEN}{output}{RESET}")
    parts.append(f"{YELLOW}{DIM}{'─' * 80}{RESET}")

    msg = "\n".join(parts)
    _diag_logger.info(msg)


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
