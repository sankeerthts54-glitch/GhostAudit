"""Deletion policy checker and system activity evaluator for Ghost Data Still Exists.

Loads deletion_rules.csv, filters system_activity.csv by user identifiers and audit_at,
and classifies events against retention/deletion policies.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from code.config import DATASET_DIR
from code.utils.time_utils import is_at_or_before


@dataclass
class Rule:
    """Representation of a policy rule from deletion_rules.csv."""

    rule_id: str
    data_category: str
    condition: str
    required_action: str  # DELETE | REDACT | ANONYMIZE | RETAIN

    @property
    def is_delete(self) -> bool:
        return self.required_action.upper() == "DELETE"

    @property
    def is_redact(self) -> bool:
        return self.required_action.upper() == "REDACT"

    @property
    def is_anonymize(self) -> bool:
        return self.required_action.upper() == "ANONYMIZE"

    @property
    def is_retain(self) -> bool:
        return self.required_action.upper() == "RETAIN"


@dataclass
class ActivityEvent:
    """Representation of an operational event from system_activity.csv."""

    activity_id: str
    event_time: str
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str  # SUCCESS | FAILED | PARTIAL
    details: str

    @property
    def is_success(self) -> bool:
        return self.reported_result.upper() == "SUCCESS"

    @property
    def is_failed(self) -> bool:
        return self.reported_result.upper() == "FAILED"

    @property
    def is_partial(self) -> bool:
        return self.reported_result.upper() == "PARTIAL"

    @property
    def is_data_flow(self) -> bool:
        return self.event_type.upper() in [
            "SYNC_RECORD",
            "CHECK_DATA_FLOW",
            "DISABLE_DATA_FLOW",
        ]

    @property
    def is_restore_risk(self) -> bool:
        return self.event_type.upper() in [
            "RESTORE_BACKUP",
            "CHECK_RESTORE_ACCESS",
            "BLOCK_RESTORE",
        ]


def load_deletion_rules(
    dataset_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Rule]:
    """Load deletion rules from deletion_rules.csv indexed by data_category."""
    base_dir = Path(dataset_dir) if dataset_dir else DATASET_DIR
    rules_path = base_dir / "deletion_rules.csv"
    if not rules_path.is_file():
        raise FileNotFoundError(f"deletion_rules.csv not found at {rules_path}")

    rules_by_category: Dict[str, Rule] = {}
    with open(rules_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cat = row.get("data_category", "").strip()
            if not cat:
                continue
            rule = Rule(
                rule_id=row.get("rule_id", "").strip(),
                data_category=cat,
                condition=row.get("condition", "").strip(),
                required_action=row.get("required_action", "").strip().upper(),
            )
            rules_by_category[cat] = rule

    return rules_by_category


def load_system_activity(
    user_identifiers: Optional[Set[str]] = None,
    audit_at: Optional[str] = None,
    dataset_dir: Optional[Union[str, Path]] = None,
) -> List[ActivityEvent]:
    """Load system_activity.csv events, filtered by audit_at and user identifiers."""
    base_dir = Path(dataset_dir) if dataset_dir else DATASET_DIR
    activity_path = base_dir / "system_activity.csv"
    if not activity_path.is_file():
        raise FileNotFoundError(f"system_activity.csv not found at {activity_path}")

    # Prepare normalized filter terms
    search_terms: Set[str] = set()
    if user_identifiers:
        for ident in user_identifiers:
            clean = str(ident).strip().lower()
            if clean:
                search_terms.add(clean)

    events: List[ActivityEvent] = []
    with open(activity_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            event_time = row.get("event_time", "").strip()
            if audit_at and not is_at_or_before(event_time, audit_at):
                continue

            act_id = row.get("activity_id", "").strip()
            etype = row.get("event_type", "").strip()
            source = row.get("source_system", "").strip()
            target = row.get("target_system", "").strip()
            res_id = row.get("resource_id", "").strip()
            result = row.get("reported_result", "").strip()
            details = row.get("details", "").strip()

            # If user_identifiers specified, check match against resource_id or details
            if search_terms:
                res_lower = res_id.lower()
                details_lower = details.lower()
                matched = any(
                    term in res_lower or term in details_lower
                    for term in search_terms
                )
                if not matched:
                    continue

            events.append(
                ActivityEvent(
                    activity_id=act_id,
                    event_time=event_time,
                    event_type=etype,
                    source_system=source,
                    target_system=target,
                    resource_id=res_id,
                    reported_result=result,
                    details=details,
                )
            )

    return events


def classify_activity_event(
    event: ActivityEvent,
    rules: Dict[str, Rule],
) -> Dict[str, Any]:
    """Classify an activity event against deletion rules.
    
    Identifies if an event signals:
    - active data flow recreation
    - unblocked restore risk
    - failed or partial deletion
    - successful deletion or retention
    """
    etype = event.event_type.upper()
    result = event.reported_result.upper()

    classification: Dict[str, Any] = {
        "activity_id": event.activity_id,
        "event_time": event.event_time,
        "system_id": event.target_system or event.source_system,
        "resource_id": event.resource_id,
        "event_type": etype,
        "reported_result": result,
        "is_complete": False,
        "finding_type": None,
        "remediation_op": None,
        "verification_op": None,
        "risk_description": "",
    }

    # 1. Active data flow recreation (SYNC_RECORD or active replication)
    if etype == "SYNC_RECORD":
        if result == "SUCCESS":
            classification["finding_type"] = "REPORT_ACTIVE_DATA_FLOW"
            classification["remediation_op"] = "DISABLE_DATA_FLOW"
            classification["verification_op"] = "VERIFY_DATA_FLOW_DISABLED"
            classification["risk_description"] = (
                f"Active sync flow {event.source_system} -> {event.target_system} "
                f"recreated or synchronized {event.resource_id}."
            )
        return classification

    # 2. Check data flow / flow status
    if etype == "CHECK_DATA_FLOW":
        if result != "SUCCESS" or "active" in event.details.lower():
            classification["finding_type"] = "REPORT_ACTIVE_DATA_FLOW"
            classification["remediation_op"] = "DISABLE_DATA_FLOW"
            classification["verification_op"] = "VERIFY_DATA_FLOW_DISABLED"
            classification["risk_description"] = "Data flow is active or unverified."
        else:
            classification["is_complete"] = True
            classification["verification_op"] = "VERIFY_DATA_FLOW_DISABLED"
        return classification

    # 3. Restore risk / backup restore
    if etype in ["RESTORE_BACKUP", "CHECK_RESTORE_ACCESS"]:
        if result == "SUCCESS" or "accessible" in event.details.lower():
            classification["finding_type"] = "REPORT_RESTORE_RISK"
            classification["remediation_op"] = "BLOCK_RESTORE"
            classification["verification_op"] = "VERIFY_RESTORE_BLOCKED"
            classification["risk_description"] = "Restore access is unblocked; data can be restored."
        return classification

    if etype == "BLOCK_RESTORE":
        if result == "SUCCESS":
            classification["is_complete"] = True
            classification["verification_op"] = "VERIFY_RESTORE_BLOCKED"
        else:
            classification["finding_type"] = "REPORT_RESTORE_RISK"
            classification["remediation_op"] = "BLOCK_RESTORE"
            classification["verification_op"] = "VERIFY_RESTORE_BLOCKED"
        return classification

    if etype == "DISABLE_DATA_FLOW":
        if result == "SUCCESS":
            classification["is_complete"] = True
            classification["verification_op"] = "VERIFY_DATA_FLOW_DISABLED"
        else:
            classification["finding_type"] = "REPORT_ACTIVE_DATA_FLOW"
            classification["remediation_op"] = "DISABLE_DATA_FLOW"
            classification["verification_op"] = "VERIFY_DATA_FLOW_DISABLED"
        return classification

    # 4. Deletion operations
    if etype == "DELETE_RECORD":
        if result != "SUCCESS":
            classification["finding_type"] = "REPORT_REMAINING_RECORD"
            classification["remediation_op"] = "DELETE_RECORD"
            classification["verification_op"] = "VERIFY_RECORD_ABSENT"
            classification["risk_description"] = f"Deletion failed or was partial ({result})."
        else:
            classification["is_complete"] = True
            classification["verification_op"] = "VERIFY_RECORD_ABSENT"
        return classification

    # 5. Redaction operations
    if etype == "REDACT_RECORD":
        if result != "SUCCESS":
            classification["finding_type"] = "REPORT_EXPOSED_PII"
            classification["remediation_op"] = "REDACT_RECORD"
            classification["verification_op"] = "VERIFY_RECORD_REDACTED"
            classification["risk_description"] = f"Redaction failed or was partial ({result})."
        else:
            classification["is_complete"] = True
            classification["verification_op"] = "VERIFY_RECORD_REDACTED"
        return classification

    # 6. Anonymization operations
    if etype == "ANONYMIZE_RECORD":
        if result != "SUCCESS":
            classification["finding_type"] = "REPORT_EXPOSED_PII"
            classification["remediation_op"] = "ANONYMIZE_RECORD"
            classification["verification_op"] = "VERIFY_RECORD_ANONYMIZED"
            classification["risk_description"] = f"Anonymization failed or was partial ({result})."
        else:
            classification["is_complete"] = True
            classification["verification_op"] = "VERIFY_RECORD_ANONYMIZED"
        return classification

    # 7. Retention operations
    if etype == "RETAIN_RECORD":
        classification["is_complete"] = True
        classification["verification_op"] = "VERIFY_RECORD_PRESENT"
        return classification

    # Default fallback
    classification["is_complete"] = (result == "SUCCESS")
    return classification


class DeletionChecker:
    """Manages rules and evaluates events against deletion policies."""

    def __init__(self, dataset_dir: Optional[Union[str, Path]] = None) -> None:
        self.dataset_dir = Path(dataset_dir) if dataset_dir else DATASET_DIR
        self.rules = load_deletion_rules(self.dataset_dir)
        self._all_activity: Optional[List[ActivityEvent]] = None

    def get_user_activity(
        self,
        user_identifiers: Set[str],
        audit_at: Optional[str] = None,
    ) -> List[ActivityEvent]:
        """Fetch all system activity events relevant to a user up to audit_at."""
        return load_system_activity(
            user_identifiers=user_identifiers,
            audit_at=audit_at,
            dataset_dir=self.dataset_dir,
        )

    def classify(self, event: ActivityEvent) -> Dict[str, Any]:
        """Classify event using loaded rules."""
        return classify_activity_event(event, self.rules)
