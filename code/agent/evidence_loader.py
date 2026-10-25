"""Evidence loader and indexing module for Ghost Data Still Exists audit agent.

Loads evidence_files.csv, filters by capture time <= audit_at, and indexes/parses
SQL dumps (into in-memory SQLite), JSON snapshots, logs, and text evidence.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from code.config import DATASET_DIR
from code.utils.time_utils import is_at_or_before


@dataclass
class EvidenceFile:
    """Metadata and path information for a single evidence item."""

    file_id: str
    file_path: str
    origin: str
    captured_at: str
    absolute_path: Path

    @property
    def suffix(self) -> str:
        return self.absolute_path.suffix.lower()

    @property
    def is_sql(self) -> bool:
        return self.suffix == ".sql"

    @property
    def is_json(self) -> bool:
        return self.suffix == ".json"

    @property
    def is_log_or_text(self) -> bool:
        return self.suffix in [".log", ".txt"]

    @property
    def is_image(self) -> bool:
        return self.suffix in [".png", ".jpg", ".jpeg"]

    @property
    def is_pdf(self) -> bool:
        return self.suffix == ".pdf"


def load_evidence_manifest(
    audit_at: Optional[str] = None,
    dataset_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, EvidenceFile]:
    """Load evidence manifest from evidence_files.csv, filtered by captured_at <= audit_at."""
    base_dir = Path(dataset_dir) if dataset_dir else DATASET_DIR
    manifest_path = base_dir / "evidence_files.csv"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"evidence_files.csv not found at {manifest_path}")

    manifest: Dict[str, EvidenceFile] = {}
    with open(manifest_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fid = row.get("file_id", "").strip()
            if not fid:
                continue
            rel_path = row.get("file_path", "").strip()
            captured_at = row.get("captured_at", "").strip()
            origin = row.get("origin", "").strip()

            # Time cutoff: evidence captured after audit_at must never be used
            if audit_at and not is_at_or_before(captured_at, audit_at):
                continue

            abs_path = base_dir / rel_path
            manifest[fid] = EvidenceFile(
                file_id=fid,
                file_path=rel_path,
                origin=origin,
                captured_at=captured_at,
                absolute_path=abs_path,
            )

    return manifest


def load_file_content(
    file_id_or_path: Union[str, Path],
    dataset_dir: Optional[Union[str, Path]] = None,
) -> Union[str, bytes]:
    """Load content of an evidence file given its file_id or file path."""
    base_dir = Path(dataset_dir) if dataset_dir else DATASET_DIR
    path: Path
    if isinstance(file_id_or_path, Path):
        path = file_id_or_path
    elif str(file_id_or_path).startswith("evidence_"):
        # Look up in manifest
        manifest = load_evidence_manifest(dataset_dir=base_dir)
        ev_file = manifest.get(str(file_id_or_path))
        if not ev_file:
            raise FileNotFoundError(f"Unknown evidence_id: {file_id_or_path}")
        path = ev_file.absolute_path
    else:
        path = base_dir / file_id_or_path if not Path(file_id_or_path).is_absolute() else Path(file_id_or_path)

    if not path.is_file():
        raise FileNotFoundError(f"Evidence file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in [".sql", ".json", ".log", ".txt", ".csv"]:
        return path.read_text(encoding="utf-8", errors="ignore")
    return path.read_bytes()


def index_sql_file(path_or_sql_text: Union[str, Path]) -> sqlite3.Connection:
    """Execute SQLite SQL dump into an in-memory database and return connection."""
    if isinstance(path_or_sql_text, Path) or (isinstance(path_or_sql_text, str) and "\n" not in path_or_sql_text and Path(path_or_sql_text).is_file()):
        sql_text = Path(path_or_sql_text).read_text(encoding="utf-8", errors="ignore")
    else:
        sql_text = str(path_or_sql_text)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(sql_text)
    return conn


def parse_json_evidence(path_or_content: Union[str, Path]) -> Any:
    """Parse JSON evidence file or text into Python dict/list."""
    if isinstance(path_or_content, Path) or (isinstance(path_or_content, str) and not path_or_content.strip().startswith(("{", "[")) and Path(path_or_content).is_file()):
        content = Path(path_or_content).read_text(encoding="utf-8", errors="ignore")
    else:
        content = str(path_or_content)
    return json.loads(content)


def parse_log_evidence(path_or_content: Union[str, Path]) -> List[str]:
    """Parse log evidence file or text into non-empty stripped lines."""
    if isinstance(path_or_content, Path) or (isinstance(path_or_content, str) and "\n" not in path_or_content and Path(path_or_content).is_file()):
        content = Path(path_or_content).read_text(encoding="utf-8", errors="ignore")
    else:
        content = str(path_or_content)
    return [line.strip() for line in content.splitlines() if line.strip()]


class EvidenceLoader:
    """High-performance cached loader and searcher for all evidence files."""

    def __init__(self, dataset_dir: Optional[Union[str, Path]] = None) -> None:
        self.dataset_dir = Path(dataset_dir) if dataset_dir else DATASET_DIR
        self._all_manifest: Dict[str, EvidenceFile] = {}
        self._sql_connections: Dict[str, sqlite3.Connection] = {}
        self._json_cache: Dict[str, Any] = {}
        self._log_cache: Dict[str, List[str]] = {}
        self._raw_text_cache: Dict[str, str] = {}
        self._loaded: bool = False

    def load(self) -> None:
        """Load manifest."""
        if not self._loaded:
            self._all_manifest = load_evidence_manifest(dataset_dir=self.dataset_dir)
            self._loaded = True

    def get_manifest(self, audit_at: Optional[str] = None) -> Dict[str, EvidenceFile]:
        """Return evidence manifest valid at or before audit_at."""
        if not self._loaded:
            self.load()
        if not audit_at:
            return dict(self._all_manifest)
        return {
            fid: ev
            for fid, ev in self._all_manifest.items()
            if is_at_or_before(ev.captured_at, audit_at)
        }

    def get_sql_db(self, file_id: str) -> Optional[sqlite3.Connection]:
        """Get or initialize in-memory SQLite database for a SQL evidence file."""
        if not self._loaded:
            self.load()
        if file_id in self._sql_connections:
            return self._sql_connections[file_id]

        ev_file = self._all_manifest.get(file_id)
        if not ev_file or not ev_file.is_sql:
            return None

        conn = index_sql_file(ev_file.absolute_path)
        self._sql_connections[file_id] = conn
        return conn

    def get_json(self, file_id: str) -> Optional[Any]:
        """Get parsed JSON data for a JSON evidence file."""
        if not self._loaded:
            self.load()
        if file_id in self._json_cache:
            return self._json_cache[file_id]

        ev_file = self._all_manifest.get(file_id)
        if not ev_file or not ev_file.is_json:
            return None

        data = parse_json_evidence(ev_file.absolute_path)
        self._json_cache[file_id] = data
        return data

    def get_log_lines(self, file_id: str) -> Optional[List[str]]:
        """Get parsed log lines for a log/text evidence file."""
        if not self._loaded:
            self.load()
        if file_id in self._log_cache:
            return self._log_cache[file_id]

        ev_file = self._all_manifest.get(file_id)
        if not ev_file or not ev_file.is_log_or_text:
            return None

        lines = parse_log_evidence(ev_file.absolute_path)
        self._log_cache[file_id] = lines
        return lines

    def get_text_content(self, file_id: str) -> str:
        """Get raw text content for textual evidence files."""
        if not self._loaded:
            self.load()
        if file_id in self._raw_text_cache:
            return self._raw_text_cache[file_id]

        ev_file = self._all_manifest.get(file_id)
        if not ev_file or ev_file.is_image or ev_file.is_pdf:
            return ""

        text = str(load_file_content(ev_file.absolute_path, self.dataset_dir))
        self._raw_text_cache[file_id] = text
        return text

    def search_evidence(
        self,
        identifiers: Set[str],
        audit_at: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search all valid evidence files for occurrences of any identifier."""
        valid_files = self.get_manifest(audit_at=audit_at)
        matches: List[Dict[str, Any]] = []

        norm_identifiers = {i.lower() for i in identifiers if i}
        if not norm_identifiers:
            return matches

        for fid, ev in valid_files.items():
            if ev.is_sql:
                conn = self.get_sql_db(fid)
                if conn:
                    # Query tables
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [r[0] for r in cursor.fetchall()]
                    for table in tables:
                        cursor.execute(f"SELECT * FROM {table}")
                        rows = cursor.fetchall()
                        for row in rows:
                            row_dict = dict(row)
                            row_vals = [str(v).lower() for v in row_dict.values()]
                            matched = [
                                ident for ident in norm_identifiers
                                if any(ident in val for val in row_vals)
                            ]
                            if matched:
                                matches.append({
                                    "file_id": fid,
                                    "file_path": ev.file_path,
                                    "captured_at": ev.captured_at,
                                    "type": "sql",
                                    "table": table,
                                    "record": row_dict,
                                    "matched_identifiers": matched,
                                })
            elif ev.is_json:
                data = self.get_json(fid)
                data_str = json.dumps(data).lower()
                matched = [i for i in norm_identifiers if i in data_str]
                if matched:
                    matches.append({
                        "file_id": fid,
                        "file_path": ev.file_path,
                        "captured_at": ev.captured_at,
                        "type": "json",
                        "matched_identifiers": matched,
                    })
            elif ev.is_log_or_text:
                lines = self.get_log_lines(fid)
                if lines:
                    matched_lines = []
                    for line in lines:
                        line_lower = line.lower()
                        if any(i in line_lower for i in norm_identifiers):
                            matched_lines.append(line)
                    if matched_lines:
                        matches.append({
                            "file_id": fid,
                            "file_path": ev.file_path,
                            "captured_at": ev.captured_at,
                            "type": "log",
                            "lines": matched_lines[:10],
                            "total_matched_lines": len(matched_lines),
                        })

        return matches
