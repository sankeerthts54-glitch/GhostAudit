"""Step sequence builder adhering to challenge ordering rules.

Implements sorting and canonical structure for steps_json according to
problem_statement.md:
  1. FINDING phase:
     REPORT_REMAINING_RECORD -> REPORT_EXPOSED_PII -> REPORT_ACTIVE_DATA_FLOW -> REPORT_RESTORE_RISK
  2. REMEDIATION phase:
     DISABLE_DATA_FLOW -> BLOCK_RESTORE -> DELETE_RECORD -> REDACT_RECORD -> ANONYMIZE_RECORD
  3. VERIFICATION phase:
     VERIFY_RECORD_ABSENT -> VERIFY_RECORD_PRESENT -> VERIFY_RECORD_REDACTED ->
     VERIFY_RECORD_ANONYMIZED -> VERIFY_DATA_FLOW_DISABLED -> VERIFY_RESTORE_BLOCKED

Within each phase and operation, steps are sorted by system_id asc, then resource_id asc.
Step numbering starts at 1 and increases consecutively.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Union

from code.utils.json_utils import (
    ALLOWED_OPERATIONS_AND_STATES,
    ALLOWED_PHASES,
    CANONICAL_FIELD_ORDER,
    canonicalize_step,
    serialize_steps,
)

# Canonical phase order
PHASE_ORDER: Dict[str, int] = {
    "FINDING": 1,
    "REMEDIATION": 2,
    "VERIFICATION": 3,
}

# Canonical operation order within each phase
OPERATION_ORDER: Dict[str, int] = {
    # Phase 1: FINDING
    "REPORT_REMAINING_RECORD": 1,
    "REPORT_EXPOSED_PII": 2,
    "REPORT_ACTIVE_DATA_FLOW": 3,
    "REPORT_RESTORE_RISK": 4,

    # Phase 2: REMEDIATION
    "DISABLE_DATA_FLOW": 1,
    "BLOCK_RESTORE": 2,
    "DELETE_RECORD": 3,
    "REDACT_RECORD": 4,
    "ANONYMIZE_RECORD": 5,

    # Phase 3: VERIFICATION
    "VERIFY_RECORD_ABSENT": 1,
    "VERIFY_RECORD_PRESENT": 2,
    "VERIFY_RECORD_REDACTED": 3,
    "VERIFY_RECORD_ANONYMIZED": 4,
    "VERIFY_DATA_FLOW_DISABLED": 5,
    "VERIFY_RESTORE_BLOCKED": 6,
}


@dataclass
class Step:
    """Represents a single audit, remediation, or verification step."""

    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str = ""
    step_no: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert Step to canonical dictionary."""
        return {
            "step_no": self.step_no,
            "phase": self.phase,
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "operation": self.operation,
            "state": self.state,
            "evidence_id": self.evidence_id,
        }


def step_sort_key(step: Union[Step, Dict[str, Any]]) -> tuple:
    """Return sorting tuple: (phase_order, op_order, system_id, resource_id)."""
    if isinstance(step, Step):
        phase = step.phase
        op = step.operation
        sys_id = step.system_id
        res_id = step.resource_id
    else:
        phase = str(step.get("phase", ""))
        op = str(step.get("operation", ""))
        sys_id = str(step.get("system_id", ""))
        res_id = str(step.get("resource_id", ""))

    p_order = PHASE_ORDER.get(phase, 99)
    op_order = OPERATION_ORDER.get(op, 99)
    return (p_order, op_order, sys_id, res_id)


def sort_steps(steps: List[Union[Step, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Sort steps according to problem statement specifications and renumber consecutively."""
    if not steps:
        return []

    # Sort stably using step_sort_key
    sorted_raw = sorted(steps, key=step_sort_key)

    canonical_steps: List[Dict[str, Any]] = []
    for idx, s in enumerate(sorted_raw, start=1):
        if isinstance(s, Step):
            step_dict = s.to_dict()
        else:
            step_dict = dict(s)
        canonical_steps.append(canonicalize_step(step_dict, step_no=idx))

    return canonical_steps


def validate_steps(
    steps: List[Dict[str, Any]],
    deletion_status: str,
) -> List[str]:
    """Validate steps against status constraints and schema rules.
    
    Returns a list of error strings (empty if valid).
    """
    errors: List[str] = []

    if deletion_status == "NOT_APPLICABLE":
        if len(steps) != 0:
            errors.append(f"NOT_APPLICABLE cases must have empty steps_json, got {len(steps)} steps.")
        return errors

    if not steps:
        errors.append(f"Cases with status {deletion_status} must contain at least one step.")
        return errors

    for idx, step in enumerate(steps, start=1):
        # 1. Numbering
        actual_no = step.get("step_no")
        if actual_no != idx:
            errors.append(f"Step {idx}: invalid step_no {actual_no}, expected {idx}.")

        # 2. Phase
        phase = step.get("phase")
        if phase not in ALLOWED_PHASES:
            errors.append(f"Step {idx}: invalid phase '{phase}'.")

        if deletion_status == "COMPLETE" and phase != "VERIFICATION":
            errors.append(f"Step {idx}: COMPLETE case must only have VERIFICATION phase, got '{phase}'.")

        # 3. Operation & State
        op = step.get("operation")
        state = step.get("state")
        if op not in ALLOWED_OPERATIONS_AND_STATES:
            errors.append(f"Step {idx}: unknown operation '{op}'.")
        else:
            expected_state = ALLOWED_OPERATIONS_AND_STATES[op]
            if state != expected_state:
                errors.append(
                    f"Step {idx}: state mismatch for operation '{op}'. Expected '{expected_state}', got '{state}'."
                )

        # 4. Evidence ID rules
        evidence_id = str(step.get("evidence_id", ""))
        if deletion_status == "COMPLETE":
            if not evidence_id:
                errors.append(f"Step {idx}: COMPLETE verification step must cite a non-empty evidence_id.")
        elif deletion_status == "INCOMPLETE":
            if phase == "FINDING":
                if not evidence_id:
                    errors.append(f"Step {idx}: INCOMPLETE finding step must cite a non-empty evidence_id.")
            elif phase in ["REMEDIATION", "VERIFICATION"]:
                if evidence_id != "":
                    errors.append(
                        f"Step {idx}: INCOMPLETE {phase} step must have empty evidence_id (''), got '{evidence_id}'."
                    )

    return errors


def build_remediation_and_verification_for_finding(
    finding_op: str,
    system_id: str,
    resource_id: str,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Determine remediation action and corresponding post-remediation verification step for a finding."""
    if finding_op == "REPORT_ACTIVE_DATA_FLOW":
        rem = {
            "phase": "REMEDIATION",
            "system_id": system_id,
            "resource_id": resource_id,
            "operation": "DISABLE_DATA_FLOW",
            "state": "DISABLED",
            "evidence_id": "",
        }
        verif = {
            "phase": "VERIFICATION",
            "system_id": system_id,
            "resource_id": resource_id,
            "operation": "VERIFY_DATA_FLOW_DISABLED",
            "state": "DISABLED",
            "evidence_id": "",
        }
    elif finding_op == "REPORT_RESTORE_RISK":
        rem = {
            "phase": "REMEDIATION",
            "system_id": system_id,
            "resource_id": resource_id,
            "operation": "BLOCK_RESTORE",
            "state": "BLOCKED",
            "evidence_id": "",
        }
        verif = {
            "phase": "VERIFICATION",
            "system_id": system_id,
            "resource_id": resource_id,
            "operation": "VERIFY_RESTORE_BLOCKED",
            "state": "BLOCKED",
            "evidence_id": "",
        }
    elif finding_op == "REPORT_REMAINING_RECORD":
        rem = {
            "phase": "REMEDIATION",
            "system_id": system_id,
            "resource_id": resource_id,
            "operation": "DELETE_RECORD",
            "state": "ABSENT",
            "evidence_id": "",
        }
        verif = {
            "phase": "VERIFICATION",
            "system_id": system_id,
            "resource_id": resource_id,
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "",
        }
    elif finding_op == "REPORT_EXPOSED_PII":
        if system_id == "analytics_platform":
            rem = {
                "phase": "REMEDIATION",
                "system_id": system_id,
                "resource_id": resource_id,
                "operation": "ANONYMIZE_RECORD",
                "state": "ANONYMIZED",
                "evidence_id": "",
            }
            verif = {
                "phase": "VERIFICATION",
                "system_id": system_id,
                "resource_id": resource_id,
                "operation": "VERIFY_RECORD_ANONYMIZED",
                "state": "ANONYMIZED",
                "evidence_id": "",
            }
        else:
            # support_platform, identity_service tombstone, etc.
            rem = {
                "phase": "REMEDIATION",
                "system_id": system_id,
                "resource_id": resource_id,
                "operation": "REDACT_RECORD",
                "state": "REDACTED",
                "evidence_id": "",
            }
            verif = {
                "phase": "VERIFICATION",
                "system_id": system_id,
                "resource_id": resource_id,
                "operation": "VERIFY_RECORD_REDACTED",
                "state": "REDACTED",
                "evidence_id": "",
            }
    else:
        raise ValueError(f"Unsupported finding operation: {finding_op}")

    return rem, verif


def build_steps(
    findings: List[Dict[str, Any]],
    verifications: List[Dict[str, Any]],
    deletion_status: str,
) -> List[Dict[str, Any]]:
    """Build and sort the complete step list for a case."""
    if deletion_status == "NOT_APPLICABLE":
        return []

    all_steps: List[Dict[str, Any]] = []

    if deletion_status == "COMPLETE":
        # Only verification steps with evidence_id
        for v in verifications:
            step_item = dict(v)
            step_item["phase"] = "VERIFICATION"
            all_steps.append(step_item)
        return sort_steps(all_steps)

    # For INCOMPLETE status:
    # 1. Add FINDINGS (preserving evidence_id)
    # 2. Add REMEDIATIONS (evidence_id = "")
    # 3. Add VERIFICATIONS (evidence_id = "")
    seen_resources: set[tuple[str, str]] = set()

    for f in findings:
        f_dict = dict(f)
        f_dict["phase"] = "FINDING"
        all_steps.append(f_dict)

        rem, verif = build_remediation_and_verification_for_finding(
            finding_op=f_dict["operation"],
            system_id=f_dict["system_id"],
            resource_id=f_dict["resource_id"],
        )
        all_steps.append(rem)
        all_steps.append(verif)
        seen_resources.add((f_dict["system_id"], f_dict["resource_id"]))

    # Add existing verifications for other completed/retained resources (e.g. account_service 404, security_service)
    for v in verifications:
        key = (v["system_id"], v["resource_id"])
        if key not in seen_resources:
            v_dict = dict(v)
            v_dict["phase"] = "VERIFICATION"
            v_dict["evidence_id"] = ""  # For INCOMPLETE cases, verification evidence_id must be ""
            all_steps.append(v_dict)
            seen_resources.add(key)

    return sort_steps(all_steps)
