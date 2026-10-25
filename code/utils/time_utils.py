"""Time and timestamp comparison utilities for audit cutoff enforcement."""

from __future__ import annotations

import datetime
from typing import Optional, Union


def parse_timestamp(ts: Union[str, datetime.datetime]) -> datetime.datetime:
    """Parse ISO-8601 string or return datetime object in UTC timezone."""
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=datetime.timezone.utc)
        return ts.astimezone(datetime.timezone.utc)

    if not isinstance(ts, str):
        raise ValueError(f"Expected str or datetime, got {type(ts)}")

    clean_ts = ts.strip()
    if not clean_ts:
        raise ValueError("Empty timestamp string")

    # Handle standard trailing 'Z'
    if clean_ts.endswith("Z"):
        clean_ts = clean_ts[:-1] + "+00:00"

    # Handle space separator instead of 'T'
    if " " in clean_ts and "T" not in clean_ts:
        clean_ts = clean_ts.replace(" ", "T")

    dt = datetime.datetime.fromisoformat(clean_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)

    return dt


def is_at_or_before(
    candidate_ts: Union[str, datetime.datetime, None],
    cutoff_ts: Union[str, datetime.datetime, None],
) -> bool:
    """Check if candidate_ts <= cutoff_ts.
    
    If candidate_ts is None or empty, returns False.
    If cutoff_ts is None or empty, returns True (no cutoff).
    """
    if candidate_ts is None or candidate_ts == "":
        return False
    if cutoff_ts is None or cutoff_ts == "":
        return True

    try:
        dt_cand = parse_timestamp(candidate_ts)
        dt_cutoff = parse_timestamp(cutoff_ts)
        return dt_cand <= dt_cutoff
    except Exception:
        return False


def format_iso(dt: Optional[datetime.datetime] = None) -> str:
    """Format datetime as ISO-8601 UTC string ending in 'Z'."""
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
