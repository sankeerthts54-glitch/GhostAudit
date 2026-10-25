"""Custom evaluation test cases for Ghost Data Still Exists challenge.

Defines at least three distinct hand-crafted test cases covering:
1. Ambiguous non-deletion request (DSAR / Article 15 access export) -> NOT_APPLICABLE
2. Account tombstone with leaked PII hash in audit logs -> INCOMPLETE
3. Active synchronization data flow risk overwriting purged records -> INCOMPLETE
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

# 1. Custom Deletion Request Inputs
CUSTOM_CASES_INPUT: List[Dict[str, str]] = [
    {
        "case_id": "case_custom_01",
        "email": "sarah.connor@cyberdyne.org",
        "requested_at": "2026-08-10T14:00:00Z",
        "reported_status": "COMPLETE",
        "reported_at": "2026-08-12T10:00:00Z",
        "audit_at": "2026-08-15T12:00:00Z",
        "request_text": (
            "Under GDPR Article 15 (Right of Access), please send me an electronic export "
            "of all my profile details, transaction records, and activity logs. I do not want "
            "my account deleted at this time."
        ),
    },
    {
        "case_id": "case_custom_02",
        "email": "marcus.vance@solarenergy.net",
        "requested_at": "2026-09-01T08:30:00Z",
        "reported_status": "COMPLETE",
        "reported_at": "2026-09-03T16:00:00Z",
        "audit_at": "2026-09-05T09:00:00Z",
        "request_text": "Please delete all my personal information and close my account permanently.",
    },
    {
        "case_id": "case_custom_03",
        "email": "elena.rostova@hyperion.io",
        "requested_at": "2026-09-12T11:15:00Z",
        "reported_status": "COMPLETE",
        "reported_at": "2026-09-14T17:30:00Z",
        "audit_at": "2026-09-16T18:00:00Z",
        "request_text": "I request the full erasure of my user records and all connected customer data.",
    },
]

# 2. Expected Outputs for Custom Cases
CUSTOM_CASES_EXPECTED: List[Dict[str, Any]] = [
    {
        "case_id": "case_custom_01",
        "deletion_status": "NOT_APPLICABLE",
        "steps_json": "[]",
    },
    {
        "case_id": "case_custom_02",
        "deletion_status": "INCOMPLETE",
        "steps_json": json.dumps([
            {
                "step_no": 1,
                "phase": "FINDING",
                "system_id": "identity_service",
                "resource_id": "tombstone_9912",
                "operation": "REPORT_EXPOSED_PII",
                "state": "PRESENT",
                "evidence_id": "evidence_custom_02",
            },
            {
                "step_no": 2,
                "phase": "REMEDIATION",
                "system_id": "identity_service",
                "resource_id": "tombstone_9912",
                "operation": "REDACT_RECORD",
                "state": "REDACTED",
                "evidence_id": "",
            },
            {
                "step_no": 3,
                "phase": "VERIFICATION",
                "system_id": "account_service",
                "resource_id": "account_custom_02",
                "operation": "VERIFY_RECORD_ABSENT",
                "state": "ABSENT",
                "evidence_id": "",
            },
            {
                "step_no": 4,
                "phase": "VERIFICATION",
                "system_id": "identity_service",
                "resource_id": "tombstone_9912",
                "operation": "VERIFY_RECORD_REDACTED",
                "state": "REDACTED",
                "evidence_id": "",
            },
        ]),
    },
    {
        "case_id": "case_custom_03",
        "deletion_status": "INCOMPLETE",
        "steps_json": json.dumps([
            {
                "step_no": 1,
                "phase": "FINDING",
                "system_id": "integration_service",
                "resource_id": "data_flow_kafka_sync",
                "operation": "REPORT_ACTIVE_DATA_FLOW",
                "state": "ACTIVE",
                "evidence_id": "evidence_custom_03",
            },
            {
                "step_no": 2,
                "phase": "REMEDIATION",
                "system_id": "integration_service",
                "resource_id": "data_flow_kafka_sync",
                "operation": "DISABLE_DATA_FLOW",
                "state": "DISABLED",
                "evidence_id": "",
            },
            {
                "step_no": 3,
                "phase": "VERIFICATION",
                "system_id": "account_service",
                "resource_id": "account_custom_03",
                "operation": "VERIFY_RECORD_ABSENT",
                "state": "ABSENT",
                "evidence_id": "",
            },
            {
                "step_no": 4,
                "phase": "VERIFICATION",
                "system_id": "integration_service",
                "resource_id": "data_flow_kafka_sync",
                "operation": "VERIFY_DATA_FLOW_DISABLED",
                "state": "DISABLED",
                "evidence_id": "",
            },
        ]),
    },
]


def get_custom_cases() -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    """Returns (inputs, expected_outputs) for custom evaluation test cases."""
    return CUSTOM_CASES_INPUT, CUSTOM_CASES_EXPECTED


if __name__ == "__main__":
    print("Custom Evaluation Cases:")
    for inp, exp in zip(CUSTOM_CASES_INPUT, CUSTOM_CASES_EXPECTED):
        print(f"\n[{inp['case_id']}] Status: {exp['deletion_status']}")
        print(f"Request: {inp['request_text'][:80]}...")
        steps = json.loads(exp["steps_json"])
        print(f"Steps count: {len(steps)}")
        for s in steps:
            print(f"  - Step {s['step_no']}: {s['phase']} | {s['system_id']} | {s['operation']} | {s['state']}")
