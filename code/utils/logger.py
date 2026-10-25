"""Append-only logger compliant with AGENTS.md §5.

Maintains the repository log.txt recording session starts and per-turn agent actions.
"""

from __future__ import annotations

import os
import re
import datetime
from pathlib import Path
from typing import Optional, List


def get_repo_root() -> Path:
    """Find the repo root containing AGENTS.md."""
    # From code/utils/logger.py -> parent.parent is repo root
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "AGENTS.md").is_file():
            return parent
    return Path.cwd()


def get_log_path() -> Path:
    """Return the absolute path to log.txt at repo root."""
    return get_repo_root() / "log.txt"


def get_iso_timestamp() -> str:
    """Return current timestamp in ISO-8601 with timezone."""
    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    return now.isoformat(timespec="seconds")


def redact_secrets(text: str) -> str:
    """Redact sensitive keys, tokens, credentials from text."""
    if not text:
        return ""
    # Gemini / API keys (e.g. AIza..., AI...)
    redacted = re.sub(r'AIza[0-9A-Za-z-_]{35}', '[REDACTED]', text)
    # Generic bearer tokens or api key assignments
    redacted = re.sub(r'(?i)(api[_-]?key|secret|token|password|bearer)\s*[:=]\s*["\']?[0-9a-zA-Z\-_.~+/=]{8,}["\']?',
                      r'\1=[REDACTED]', redacted)
    # Auth headers
    redacted = re.sub(r'(?i)(Authorization:\s*Bearer\s+)[0-9a-zA-Z\-_.~+/=]+', r'\1[REDACTED]', redacted)
    return redacted


def log_session_start(
    tool: str = "Google Antigravity",
    model: str = "gemini-3.8-flash",
    repo_root: Optional[Path] = None,
    branch: str = "main",
    worktree: str = "main",
    parent_agent: str = "none",
    language: str = "py",
    time_remaining: str = "not configured",
) -> None:
    """Append a SESSION START entry according to AGENTS.md §5.1."""
    root = repo_root or get_repo_root()
    log_file = root / "log.txt"
    ts = get_iso_timestamp()

    entry = (
        f"## [{ts}] SESSION START\n\n"
        f"tool={tool}\n"
        f"model={model}\n"
        f"Repo Root: {root}\n"
        f"Branch: {branch}\n"
        f"Worktree: {worktree}\n"
        f"Parent Agent: {parent_agent}\n"
        f"Language: {language}\n"
        f"Time Remaining: {time_remaining}\n\n"
    )

    with open(log_file, "a", encoding="utf-8", newline="\n") as f:
        f.write(entry)


def log_turn(
    title: str,
    user_prompt: str,
    response_summary: str,
    actions: List[str],
    tool: str = "Google Antigravity",
    model: str = "gemini-3.8-flash",
    branch: str = "main",
    worktree: str = "main",
    parent_agent: str = "none",
    repo_root: Optional[Path] = None,
) -> None:
    """Append a per-turn summary entry according to AGENTS.md §5.2."""
    root = repo_root or get_repo_root()
    log_file = root / "log.txt"
    ts = get_iso_timestamp()

    # Shorten title to max 80 characters
    safe_title = title.strip()[:80]
    safe_prompt = redact_secrets(user_prompt.strip())
    safe_summary = redact_secrets(response_summary.strip())

    actions_str = "\n".join(f"* {a}" for a in actions) if actions else "* None"

    entry = (
        f"## [{ts}] {safe_title}\n\n"
        f"User Prompt (verbatim, secrets redacted):\n"
        f"{safe_prompt}\n\n"
        f"Agent Response Summary:\n"
        f"{safe_summary}\n\n"
        f"Actions:\n"
        f"{actions_str}\n\n"
        f"Context:\n"
        f"tool={tool}\n"
        f"model={model}\n"
        f"branch={branch}\n"
        f"repo_root={root}\n"
        f"worktree={worktree}\n"
        f"parent_agent={parent_agent}\n\n"
    )

    with open(log_file, "a", encoding="utf-8", newline="\n") as f:
        f.write(entry)
