"""JSON utilities for steps_json serialization and validation."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


ALLOWED_PHASES = {"FINDING", "REMEDIATION", "VERIFICATION"}

ALLOWED_OPERATIONS_AND_STATES = {
    # Findings
    "REPORT_REMAINING_RECORD": "PRESENT",
    "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
    "REPORT_RESTORE_RISK": "ACTIVE",
    # Remediation
    "DISABLE_DATA_FLOW": "DISABLED",
    "BLOCK_RESTORE": "BLOCKED",
    "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED",
    "ANONYMIZE_RECORD": "ANONYMIZED",
    # Verification
    "VERIFY_RECORD_ABSENT": "ABSENT",
    "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}

CANONICAL_FIELD_ORDER = [
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
]


def canonicalize_step(step: Dict[str, Any], step_no: Optional[int] = None) -> Dict[str, Any]:
    """Order step dictionary fields canonically and assign step_no if provided."""
    canonical = {}
    current_step_no = step_no if step_no is not None else step.get("step_no", 1)
    canonical["step_no"] = int(current_step_no)

    for field in CANONICAL_FIELD_ORDER:
        if field == "step_no":
            continue
        canonical[field] = str(step.get(field, ""))

    return canonical


def validate_step(step: Dict[str, Any]) -> List[str]:
    """Validate a step dictionary against challenge schema and rules."""
    errors = []
    for field in CANONICAL_FIELD_ORDER:
        if field not in step:
            errors.append(f"Missing required field: {field}")

    phase = step.get("phase")
    if phase not in ALLOWED_PHASES:
        errors.append(f"Invalid phase '{phase}'. Must be one of {ALLOWED_PHASES}")

    op = step.get("operation")
    if op not in ALLOWED_OPERATIONS_AND_STATES:
        errors.append(f"Invalid operation '{op}'.")
    else:
        expected_state = ALLOWED_OPERATIONS_AND_STATES[op]
        actual_state = step.get("state")
        if actual_state != expected_state:
            errors.append(
                f"State mismatch for operation '{op}': expected '{expected_state}', got '{actual_state}'"
            )

    return errors


def serialize_steps(steps: List[Dict[str, Any]]) -> str:
    """Serialize list of steps into compact JSON string for CSV output."""
    if not steps:
        return "[]"

    formatted_steps = []
    for i, step in enumerate(steps, start=1):
        formatted_steps.append(canonicalize_step(step, step_no=i))

    return json.dumps(formatted_steps, separators=(",", ":"))


def parse_steps(steps_json_str: str) -> List[Dict[str, Any]]:
    """Parse steps_json string into a list of step dicts."""
    if not steps_json_str or steps_json_str.strip() in ("", "[]"):
        return []
    try:
        data = json.loads(steps_json_str)
        if isinstance(data, list):
            return data
        return []
    except json.JSONDecodeError:
        return []
