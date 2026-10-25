"""CSV I/O utilities for robust reading and writing with UTF-8 support."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import pandas as pd


def read_csv_rows(filepath: Union[str, Path]) -> List[Dict[str, str]]:
    """Read a CSV file and return a list of dictionaries mapping header -> value."""
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")

    # Use utf-8-sig to handle optional BOM cleanly
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def read_csv_dataframe(filepath: Union[str, Path], **kwargs: Any) -> pd.DataFrame:
    """Read a CSV file into a pandas DataFrame."""
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")
    return pd.read_csv(path, encoding="utf-8-sig", **kwargs)


def write_csv_rows(
    filepath: Union[str, Path],
    rows: List[Dict[str, Any]],
    fieldnames: Optional[List[str]] = None,
) -> None:
    """Write a list of dictionaries to a CSV file safely in UTF-8."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not fieldnames and rows:
        fieldnames = list(rows[0].keys())

    if not fieldnames:
        fieldnames = []

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_csv_dataframe(
    filepath: Union[str, Path],
    df: pd.DataFrame,
    **kwargs: Any,
) -> None:
    """Write a pandas DataFrame to CSV safely in UTF-8."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n", **kwargs)
