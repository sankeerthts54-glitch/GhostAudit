"""Prompts package for Ghost Data Still Exists audit agent.

Provides centralized loader for all prompt templates.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=16)
def get_prompt(name: str) -> str:
    """Load prompt content by file name (with or without .txt extension)."""
    filename = name if name.endswith(".txt") else f"{name}.txt"
    prompt_path = PROMPTS_DIR / filename
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")
