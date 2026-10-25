"""Configuration and environment variables for the audit agent."""

from __future__ import annotations

import os
from pathlib import Path

# Try loading .env if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Paths
CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset"
EVIDENCE_DIR = DATASET_DIR / "evidence"
OUTPUT_CSV = REPO_ROOT / "output.csv"
LOG_FILE = REPO_ROOT / "log.txt"
PROMPTS_DIR = CODE_DIR / "prompts"
EVALUATION_DIR = CODE_DIR / "evaluation"

# Challenge constants
ALLOWED_STATUSES = ["COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"]
EXPECTED_ROWS_COUNT = 518

# Model / API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODEL_NAME = os.getenv("FALLBACK_MODEL", "gemini-3.8-flash")

# LLM execution settings
TEMPERATURE = 0.0
MAX_OUTPUT_TOKENS = 8192
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0
BACKOFF_FACTOR = 2.0

# Logging info
TOOL_NAME = "Google Antigravity"
RUNTIME_MODEL_NAME = "gemini-3.8-flash"
