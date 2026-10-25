"""Identity resolution module for Ghost Data Still Exists audit agent.

Resolves current and historical user identities (emails, phones, hashes, names)
from user_identities.csv and user_audit_log.csv taking audit_at cutoff into account.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from code.config import DATASET_DIR
from code.utils.time_utils import is_at_or_before


def normalize_email(email: Optional[str]) -> str:
    """Normalize email address by stripping whitespace and converting to lowercase."""
    if not email:
        return ""
    return str(email).strip().lower()


def normalize_phone(phone: Optional[str]) -> str:
    """Clean phone number string while retaining canonical digits/format."""
    if not phone:
        return ""
    return str(phone).strip()


@dataclass
class IdentityProfile:
    """Represents a fully resolved user identity profile."""

    user_id: str
    name: str = ""
    current_email: str = ""
    current_phone: str = ""
    current_email_hash: str = ""
    updated_at: str = ""
    all_emails: Set[str] = field(default_factory=set)
    all_phones: Set[str] = field(default_factory=set)
    all_email_hashes: Set[str] = field(default_factory=set)
    historical_emails: List[Dict[str, Any]] = field(default_factory=list)
    historical_phones: List[Dict[str, Any]] = field(default_factory=list)
    historical_hashes: List[Dict[str, Any]] = field(default_factory=list)
    audit_records: List[Dict[str, Any]] = field(default_factory=list)

    def get_all_identifiers(self) -> Set[str]:
        """Return all unique direct identifiers (user_id, emails, phones, email_hashes)."""
        identifiers: Set[str] = set()
        if self.user_id:
            identifiers.add(self.user_id)
        for e in self.all_emails:
            if e:
                identifiers.add(e)
        for p in self.all_phones:
            if p:
                identifiers.add(p)
        for h in self.all_email_hashes:
            if h:
                identifiers.add(h)
        return identifiers

    def contains_identifier(self, text: str) -> bool:
        """Check if any user identifier is present in text."""
        if not text:
            return False
        text_lower = text.lower()
        if self.user_id and self.user_id.lower() in text_lower:
            return True
        for e in self.all_emails:
            if e and e.lower() in text_lower:
                return True
        for p in self.all_phones:
            if p and p in text:
                return True
        for h in self.all_email_hashes:
            if h and h.lower() in text_lower:
                return True
        return False


def get_all_identifiers(profile: IdentityProfile) -> Set[str]:
    """Convenience function to get all identifiers from an IdentityProfile."""
    return profile.get_all_identifiers()


class IdentityResolver:
    """Loads and caches user_identities.csv and user_audit_log.csv for fast resolution."""

    def __init__(self, dataset_dir: Optional[Union[str, Path]] = None) -> None:
        self.dataset_dir = Path(dataset_dir) if dataset_dir else DATASET_DIR
        self._identities_by_id: Dict[str, Dict[str, str]] = {}
        self._identities_by_email: Dict[str, str] = {}  # email -> user_id
        self._audit_logs_by_user: Dict[str, List[Dict[str, str]]] = {}
        self._audit_email_to_user: Dict[str, str] = {}  # historical email -> user_id
        self._loaded: bool = False

    def load(self) -> None:
        """Load identities and audit logs into memory indexes."""
        if self._loaded:
            return

        identities_path = self.dataset_dir / "user_identities.csv"
        if identities_path.is_file():
            with open(identities_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    uid = row.get("user_id", "").strip()
                    if not uid:
                        continue
                    self._identities_by_id[uid] = row
                    email = normalize_email(row.get("email", ""))
                    if email:
                        self._identities_by_email[email] = uid

        audit_path = self.dataset_dir / "user_audit_log.csv"
        if audit_path.is_file():
            with open(audit_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    uid = row.get("user_id", "").strip()
                    if not uid:
                        continue
                    if uid not in self._audit_logs_by_user:
                        self._audit_logs_by_user[uid] = []
                    self._audit_logs_by_user[uid].append(row)

                    field_name = row.get("field_name", "").strip().lower()
                    if field_name == "email":
                        old_val = normalize_email(row.get("old_value", ""))
                        new_val = normalize_email(row.get("new_value", ""))
                        if old_val:
                            self._audit_email_to_user[old_val] = uid
                        if new_val:
                            self._audit_email_to_user[new_val] = uid

        self._loaded = True

    def find_user_id(self, email: str) -> Optional[str]:
        """Find user_id given an email (checking current identities first, then audit logs)."""
        if not self._loaded:
            self.load()

        norm = normalize_email(email)
        if not norm:
            return None

        # Check current identities
        if norm in self._identities_by_email:
            return self._identities_by_email[norm]

        # Check audit log historical emails
        if norm in self._audit_email_to_user:
            return self._audit_email_to_user[norm]

        return None

    def resolve_identity(
        self,
        email: str,
        audit_at: Optional[str] = None,
    ) -> Optional[IdentityProfile]:
        """Resolve full identity profile for an email up to audit_at timestamp."""
        if not self._loaded:
            self.load()

        norm_email = normalize_email(email)
        user_id = self.find_user_id(norm_email)
        if not user_id:
            return None

        ident_row = self._identities_by_id.get(user_id, {})
        name = ident_row.get("name", "").strip()
        curr_email = ident_row.get("email", "").strip()
        curr_phone = ident_row.get("phone", "").strip()
        curr_hash = ident_row.get("email_hash", "").strip()
        updated_at = ident_row.get("updated_at", "").strip()

        all_emails: Set[str] = set()
        all_phones: Set[str] = set()
        all_hashes: Set[str] = set()

        if curr_email:
            all_emails.add(curr_email)
            all_emails.add(normalize_email(curr_email))
        if norm_email:
            all_emails.add(norm_email)
        if curr_phone:
            all_phones.add(normalize_phone(curr_phone))
        if curr_hash:
            all_hashes.add(curr_hash)

        historical_emails: List[Dict[str, Any]] = []
        historical_phones: List[Dict[str, Any]] = []
        historical_hashes: List[Dict[str, Any]] = []
        audit_records: List[Dict[str, Any]] = []

        user_audits = self._audit_logs_by_user.get(user_id, [])
        for a_row in user_audits:
            event_time = a_row.get("event_time", "")
            # Filter audit events by audit_at
            if audit_at and not is_at_or_before(event_time, audit_at):
                continue

            audit_records.append(a_row)
            fname = a_row.get("field_name", "").strip().lower()
            old_val = a_row.get("old_value", "").strip()
            new_val = a_row.get("new_value", "").strip()

            if fname == "email":
                if old_val:
                    all_emails.add(old_val)
                    all_emails.add(normalize_email(old_val))
                if new_val:
                    all_emails.add(new_val)
                    all_emails.add(normalize_email(new_val))
                historical_emails.append(a_row)
            elif fname == "phone":
                if old_val:
                    all_phones.add(normalize_phone(old_val))
                if new_val:
                    all_phones.add(normalize_phone(new_val))
                historical_phones.append(a_row)
            elif fname == "email_hash":
                if old_val:
                    all_hashes.add(old_val)
                if new_val:
                    all_hashes.add(new_val)
                historical_hashes.append(a_row)

        return IdentityProfile(
            user_id=user_id,
            name=name,
            current_email=curr_email,
            current_phone=curr_phone,
            current_email_hash=curr_hash,
            updated_at=updated_at,
            all_emails={e for e in all_emails if e},
            all_phones={p for p in all_phones if p},
            all_email_hashes={h for h in all_hashes if h},
            historical_emails=historical_emails,
            historical_phones=historical_phones,
            historical_hashes=historical_hashes,
            audit_records=audit_records,
        )


# Global default resolver singleton for easy module-level calls
_DEFAULT_RESOLVER: Optional[IdentityResolver] = None


def resolve_identity(
    email: str,
    audit_at: Optional[str] = None,
    dataset_dir: Optional[Union[str, Path]] = None,
) -> Optional[IdentityProfile]:
    """Module-level resolve_identity function conforming to PLAN.md Phase 1 interface."""
    global _DEFAULT_RESOLVER
    if dataset_dir:
        resolver = IdentityResolver(dataset_dir)
        return resolver.resolve_identity(email, audit_at)
    if _DEFAULT_RESOLVER is None:
        _DEFAULT_RESOLVER = IdentityResolver()
    return _DEFAULT_RESOLVER.resolve_identity(email, audit_at)
