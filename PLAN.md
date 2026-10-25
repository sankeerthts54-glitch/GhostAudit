# Ghost Data Still Exists — Project PLAN.md

> **Hackathon:** HackerRank Orchestrate October 2026  
> **Submission deadline:** October 26, 2026 — 6:00 AM IST  
> **Submit at:** https://www.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists  
> **Repo root:** `C:\Orchestrate\hackerrank-orchestrate-october26\`

---

## How To Use This File (Elephant-Goldfish Protocol)

Each new thread/agent starts fresh with **no prior context**. Every agent must:

1. Read **this entire file** before taking any action.
2. Read `AGENTS.md` (repo root) and follow all logging rules.
3. Append the required `SESSION START` entry to `log.txt`.
4. Execute only the phase tasks listed in their thread briefing.
5. Mark tasks `[x]` when done and update `STATUS` notes.
6. Never touch files outside their phase scope without explicit instruction.

---

## Architecture Overview

```
dataset/                        ← READ-ONLY input (never modify)
  deletion_requests.csv         ← 518 cases to process
  deletion_rules.csv            ← Policy: DELETE / REDACT / ANONYMIZE / RETAIN
  user_identities.csv           ← Current identity snapshot
  user_audit_log.csv            ← Historical identity changes
  system_activity.csv           ← Operational events stream
  evidence_files.csv            ← Manifest: file_id → path + capture time
  evidence/                     ← PDFs, images, logs, JSON, SQL files
  sample_deletion_requests.csv  ← 32 labelled examples
  sample_output.csv             ← Ground truth for samples
  output.csv                    ← Blank submission template

code/                           ← ALL solution code lives here
  main.py                       ← Entry point: python code/main.py
  agent/
    pipeline.py                 ← Orchestration: per-case agent loop
    identity_resolver.py        ← Identity resolution (current + historical)
    evidence_loader.py          ← Load & index evidence files
    deletion_checker.py         ← Apply deletion_rules.csv, classify records
    step_builder.py             ← Build ordered steps_json arrays
    llm_client.py               ← LLM calls (Gemini API) with retry/backoff
  prompts/
    system_prompt.txt           ← Master system prompt for the audit agent
    identity_prompt.txt         ← Identity resolution sub-prompt
    audit_prompt.txt            ← Core audit/classification prompt
    remediation_prompt.txt      ← Remediation step generation prompt
  utils/
    csv_io.py                   ← Read/write CSV safely
    json_utils.py               ← JSON serialisation helpers
    logger.py                   ← Append-only log.txt writer (AGENTS.md §5)
    time_utils.py               ← audit_at filtering helpers
  evaluation/
    evaluate.py                 ← Evaluate against sample_output.csv
    evaluation_report.md        ← Required deliverable (filled after runs)
    usage_report.md             ← Token/cost tracking (filled after runs)
    custom_cases.py             ← 3+ custom eval cases
  config.py                     ← Env-var secrets, model config
  requirements.txt              ← Python deps

output.csv                      ← Final predictions (repo root, 518 rows)
log.txt                         ← AGENTS.md-required session log (repo root)
README.md                       ← Update with setup & run instructions
```

---

## Key Constraints (read before every phase)

- **Output schema:** `case_id,deletion_status,steps_json` — exactly 518 rows, sorted by `case_id`.
- **Statuses:** `COMPLETE` | `INCOMPLETE` | `NOT_APPLICABLE`
- **NOT_APPLICABLE** → `steps_json = []` — when `request_text` does NOT authorize deletion.
- **Steps ordering:** FINDING → REMEDIATION → VERIFICATION (within each phase: by operation table order, then `system_id` asc, then `resource_id` asc).
- **Evidence IDs:** Findings/verifications for COMPLETE cite `file_id`/`activity_id`/`audit_id`. Remediation steps & post-remediation verifications for INCOMPLETE use `evidence_id = ""`.
- **Time cutoff:** Only use evidence captured at or before `audit_at`.
- **No hardcoded labels.** No golden answer shortcuts.
- **Secrets from env vars only** — never commit `.env` or API keys.

---

## Phase 0 — Repository Bootstrap & Logging Setup
**Thread instruction:** "Read PLAN.md. Execute Phase 0."

### Goals
- Create the `code/` folder scaffold with all empty stubs.
- Implement `utils/logger.py` fully (AGENTS.md §5 compliant).
- Implement `utils/csv_io.py` (safe read/write, UTF-8).
- Implement `utils/time_utils.py` (audit_at comparison helpers).
- Implement `utils/json_utils.py` (steps_json serializer, ensure correct field order).
- Implement `config.py` (read API keys from env: `GEMINI_API_KEY`).
- Create `requirements.txt` with: `google-genai`, `python-dotenv`, `pandas`, `tqdm`.
- Create `.env.example` (no real values, template only).
- Write initial `log.txt` SESSION START entry (AGENTS.md §5.1).
- Update `README.md` with setup instructions.

### Tasks
- [x] Create `code/` directory structure (all subdirs)
- [x] `code/utils/logger.py` — append-only log.txt writer, §5.1 + §5.2 format
- [x] `code/utils/csv_io.py` — read_csv, write_csv wrappers
- [x] `code/utils/time_utils.py` — parse ISO timestamps, compare with audit_at
- [x] `code/utils/json_utils.py` — serialize steps_json, escape for CSV
- [x] `code/config.py` — load .env, expose GEMINI_API_KEY, MODEL_NAME, DATASET_DIR, REPO_ROOT
- [x] `requirements.txt`
- [x] `.env.example`
- [x] `README.md` — setup + run instructions
- [x] `log.txt` — SESSION START entry

### STATUS: [x] Completed

---

## Phase 1 — Data Loading & Identity Resolution
**Thread instruction:** "Read PLAN.md. Execute Phase 1. Phase 0 must be complete first."

### Goals
- Load all CSV datasets into memory-efficient structures.
- Build the identity resolver: given a case email, find the `user_id` and ALL historical emails/phones/hashes from `user_audit_log.csv` + `user_identities.csv`.
- Build evidence loader: parse `evidence_files.csv`, map `file_id` → file path, filter by capture time ≤ audit_at.
- Parse `deletion_rules.csv` into a rule lookup dict keyed by `data_category`.
- Parse `system_activity.csv` with time-aware filtering.

### Key logic
```
identity_resolver(email, audit_at):
  1. Normalize email (lowercase, strip whitespace)
  2. Find user_id from user_identities.csv (current email match)
     OR from user_audit_log.csv (historical email match)
  3. Return: { user_id, current_email, all_historical_emails, phone, email_hash, name }
```

### Tasks
- [x] `code/agent/identity_resolver.py`
  - normalize_email()
  - resolve_identity(email, audit_at) → IdentityProfile dataclass
  - get_all_identifiers(profile) → set of all emails/hashes/phones
- [x] `code/agent/evidence_loader.py`
  - load_evidence_manifest(audit_at) → dict[file_id, EvidenceFile]
  - load_file_content(file_id) → str | bytes
  - index_sql_file(path) → sqlite3 connection (in-memory)
  - parse_json_evidence(path) → dict
  - parse_log_evidence(path) → list[str]
- [x] `code/agent/deletion_checker.py`
  - load_deletion_rules() → dict[data_category, Rule]
  - load_system_activity(user_identifiers, audit_at) → list[ActivityEvent]
  - classify_activity_event(event, rules) → classification

### STATUS: [x] Completed

---

## Phase 2 — LLM Client & Prompt Engineering
**Thread instruction:** "Read PLAN.md. Execute Phase 2. Phase 0 must be complete first."

### Goals
- Implement `llm_client.py` using `google-genai` SDK (Gemini 2.0/2.5 Flash).
- Design all prompts for: deletion authorization check, identity confirmation, system-by-system audit, step generation.
- Implement structured output (JSON mode) so steps_json is returned in correct schema.
- Implement retry with exponential backoff for quota/rate limits.
- Track token usage per call for `usage_report.md`.

### Model Strategy
- **Model:** `gemini-2.5-flash` (best cost/quality ratio for 518 cases)
- **Fallback:** `gemini-2.0-flash` for retries
- **Structured output:** Use JSON schema enforcement via `response_schema` parameter
- **Context budget:** Keep per-case context under 50K tokens

### Prompt Architecture
```
1. AUTHORIZATION CHECK (fast, cheap):
   Input: request_text
   Output: { "authorizes_deletion": bool, "reason": str }

2. IDENTITY AUDIT (per case):
   Input: user profile + all_identifiers + deletion_rules
   Output: { "records_found": [...], "risks": [...] }

3. STEP GENERATION (per case):
   Input: audit findings + deletion_rules + sample format
   Output: { "deletion_status": "...", "steps": [...] }
```

### Tasks
- [x] `code/agent/llm_client.py`
  - GeminiClient class with retry/backoff
  - call_structured(prompt, schema) → dict
  - track_usage(input_tokens, output_tokens, model)
  - get_usage_summary() → UsageSummary
- [x] `code/prompts/system_prompt.txt` — master system context
- [x] `code/prompts/identity_prompt.txt`
- [x] `code/prompts/audit_prompt.txt`
- [x] `code/prompts/remediation_prompt.txt`

### STATUS: [x] Completed

---

## Phase 3 — Core Agent Pipeline (Per-Case Logic)
**Thread instruction:** "Read PLAN.md. Execute Phase 3. Phases 0, 1, 2 must be complete."

### Goals
- Implement `pipeline.py`: the main per-case processing loop.
- Implement `step_builder.py`: construct and sort step arrays by the rules.
- Wire all components together.
- Handle edge cases: no user found, evidence after audit_at, tombstones, duplicate records.

### Per-Case Flow
```
process_case(row):
  1. Parse case_id, email, requested_at, audit_at, request_text
  2. AUTHORIZATION CHECK → if NOT deletion: return NOT_APPLICABLE, []
  3. identity_resolver(email, audit_at) → profile
  4. Load evidence files captured ≤ audit_at
  5. Load system_activity for this user ≤ audit_at
  6. Build context: profile + rules + activity + evidence summary
  7. LLM AUDIT CALL → findings (records present, PII exposed, active flows, restore risks)
  8. Determine deletion_status:
     - COMPLETE if no findings
     - INCOMPLETE if any findings
  9. step_builder.build_steps(findings, status, rules)
  10. Return { case_id, deletion_status, steps_json }
```

### Step Builder Rules
```
FINDING phase order: REPORT_REMAINING_RECORD → REPORT_EXPOSED_PII → REPORT_ACTIVE_DATA_FLOW → REPORT_RESTORE_RISK
  Within same op: sort by system_id asc, then resource_id asc

REMEDIATION phase order: DISABLE_DATA_FLOW → BLOCK_RESTORE → DELETE_RECORD → REDACT_RECORD → ANONYMIZE_RECORD
  NOTE: data flows disabled and restores blocked BEFORE modifying records

VERIFICATION phase order: VERIFY_RECORD_ABSENT → VERIFY_RECORD_PRESENT → VERIFY_RECORD_REDACTED → VERIFY_RECORD_ANONYMIZED → VERIFY_DATA_FLOW_DISABLED → VERIFY_RESTORE_BLOCKED
```

### Tasks
- [x] `code/agent/pipeline.py`
  - DeletionAuditPipeline class
  - process_case(row) → CaseResult
  - process_all(cases_df) → list[CaseResult]
- [x] `code/agent/step_builder.py`
  - build_steps(findings, status, rules, identifiers) → list[Step]
  - sort_steps(steps) → list[Step] (phase + op + system_id + resource_id)
  - validate_steps(steps) → errors list
- [x] `code/main.py`
  - Argument parsing (--dataset-dir, --output, --cases)
  - Load all data
  - Run pipeline with tqdm progress bar
  - Write output.csv
  - Write usage summary to evaluation/usage_report.md

### STATUS: [x] Completed

---

## Phase 4 — Evaluation & Sample Validation
**Thread instruction:** "Read PLAN.md. Execute Phase 4. Phases 0-3 must be complete."

### Goals
- Implement `evaluation/evaluate.py` to score against `sample_output.csv`.
- Run the agent on all 32 sample cases.
- Compare status accuracy, step accuracy, sequence accuracy, field accuracy.
- Create 3+ custom evaluation cases to demonstrate understanding.
- Write `evaluation/evaluation_report.md` (required deliverable).
- Iterate on prompts/logic based on sample failures.

### Scoring Dimensions
1. **Status accuracy:** % of cases with correct `deletion_status`
2. **Step presence:** % of expected steps that appear
3. **Step ordering:** Are phases and within-phase orderings correct?
4. **Evidence citation:** Do COMPLETE findings cite valid evidence IDs?
5. **Field accuracy:** Correct `system_id`, `resource_id`, `operation`, `state`

### Tasks
- [x] `code/evaluation/evaluate.py`
  - load_sample_output()
  - compare_case(predicted, expected) → CaseScore
  - score_all(predictions, ground_truth) → EvalReport
  - print_report(report)
- [x] Run samples: `python code/main.py --cases dataset/sample_deletion_requests.csv`
- [x] Analyze failures: identify patterns in wrong status/wrong steps
- [x] `evaluation/custom_cases.py` — 3 hand-crafted cases with expected outputs
- [x] `evaluation/evaluation_report.md` — fill with actual metrics, failures, improvements
- [x] Prompt iteration based on failures

### STATUS: [x] Completed

---

## Phase 5 — Full Dataset Run & Submission Prep
**Thread instruction:** "Read PLAN.md. Execute Phase 5. Phases 0-4 must be complete."

### Goals
- Run the agent on all 518 `deletion_requests.csv` cases.
- Produce the final `output.csv` at repo root with exactly 518 rows sorted by `case_id`.
- Fill `evaluation/usage_report.md` with real token/cost data from the run.
- Package `code.zip` (excluding dataset/, venvs, node_modules, secrets).
- Prepare submission artifacts checklist.

### Pre-run Validation Checklist
- [x] output.csv has header `case_id,deletion_status,steps_json`
- [x] Exactly 518 data rows
- [x] All case_ids present and sorted
- [x] All deletion_status values are valid enum values
- [x] steps_json is valid JSON for every row
- [x] NOT_APPLICABLE cases have `steps_json = []`
- [x] step_no is consecutive from 1 in every steps array
- [x] No API keys or secrets in any file

### Tasks
- [x] Run: `python code/main.py` → output.csv at repo root
- [x] Validate output.csv (row count, sort, JSON validity)
- [x] Fill `evaluation/usage_report.md` from llm_client usage tracker
- [x] Update `evaluation/evaluation_report.md` with full-run observations
- [x] Create `code.zip`:
  ```powershell
  # From repo root:
  Compress-Archive -Path code,evaluation,README.md,PLAN.md -DestinationPath code.zip -Force
  ```
  > Do NOT include: dataset/, .env, venv/, __pycache__, node_modules, *.pyc
- [x] Prepare `agent-trace.zip` (see agent_trace_instructions.md)
- [ ] Final submissions at: https://www.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists

### Submission Artifacts
| Item | File | Ready? |
|------|------|--------|
| Code | `code.zip` | [x] |
| Predictions | `output.csv` (repo root) | [x] |
| Chat Transcript | `log.txt` (repo root) | [x] |
| Agent Trace | `agent-trace.zip` | [x] |

### STATUS: [x] Completed (pending final manual submission)

---

## Gemini API Setup

The solution uses the **Google Gemini API** via the `google-genai` Python SDK.

```bash
# Required environment variable:
GEMINI_API_KEY=your_key_here

# Recommended model:
GEMINI_MODEL=gemini-2.5-flash-preview-05-20
# Fallback:
GEMINI_MODEL_FALLBACK=gemini-2.0-flash
```

Get your key at: https://aistudio.google.com/apikey

---

## Quick Run Commands

```powershell
# Setup (from repo root)
cd C:\Orchestrate\hackerrank-orchestrate-october26
python -m venv venv
.\venv\Scripts\Activate
pip install -r code\requirements.txt
copy .env.example .env  # Then add your GEMINI_API_KEY

# Run on sample cases (validate first)
python code\main.py --cases dataset\sample_deletion_requests.csv --output sample_run_output.csv

# Evaluate against ground truth
python code\evaluation\evaluate.py --predicted sample_run_output.csv --expected dataset\sample_output.csv

# Full run (518 cases)
python code\main.py

# Validate output
python code\evaluation\validate_output.py
```

---

## Phase Completion Tracker

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Bootstrap & Logging Setup | [x] Completed |
| 1 | Data Loading & Identity Resolution | [x] Completed |
| 2 | LLM Client & Prompt Engineering | [x] Completed |
| 3 | Core Agent Pipeline | [x] Completed |
| 4 | Evaluation & Sample Validation | [x] Completed |
| 5 | Full Dataset Run & Submission | [x] Completed |

---

## Critical Rules — Never Violate

1. **Never use organizer-only files** (outside `dataset/`) for predictions.
2. **Never hardcode expected answers** from `sample_output.csv` — agent must reason.
3. **Never use evidence captured after `audit_at`** for a given case.
4. **Always read from `dataset/` directory** — never modify it.
5. **Write `output.csv` to repo root**, not inside `dataset/` or `code/`.
6. **`log.txt` is append-only** — never rewrite old entries.
7. **Keep API keys in `.env`** — never commit them.
8. **Exactly 518 rows** in `output.csv`, sorted by `case_id`.
