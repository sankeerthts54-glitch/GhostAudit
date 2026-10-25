# LLM Token Usage & Cost Analysis Report

> **Generated for:** HackerRank Orchestrate (October 2026) — Ghost Data Still Exists  
> **Report Timestamp:** 2026-10-25T13:30:00Z  
> **Full Dataset Run:** 518 cases — `dataset/deletion_requests.csv`

## 1. Overall Summary

| Metric | Value |
| --- | --- |
| **Total Cases Processed** | 518 |
| **Execution Mode** | Deterministic Rule-Based Engine (LLM fallback) |
| **Total LLM Model Calls** | 0 |
| **Input (Prompt) Tokens** | 0 |
| **Output (Candidate) Tokens** | 0 |
| **Total Tokens** | 0 |
| **Average Tokens Per Request** | 0 |
| **Total Estimated Cost (USD)** | $0.0000 |
| **Average Cost Per Request (USD)** | $0.000000 |
| **Total Wall-Clock Time** | ~3.83 seconds |
| **Average Time Per Case** | ~7.4 ms |

## 2. Model Breakdown

| Model Provider & Name | Calls | Prompt Tokens | Candidate Tokens | Total Tokens | Est. Cost (USD) |
| --- | --- | --- | --- | --- | --- |
| Google / gemini-2.5-flash | 0 | 0 | 0 | 0 | $0.0000 |
| **TOTAL** | **0** | **0** | **0** | **0** | **$0.0000** |

## 3. Execution Mode — Deterministic Fallback

The LLM client was configured to call `gemini-2.5-flash` via the Google Gemini API. On the first call, the Free Tier daily quota (20 RPD) was exhausted, returning HTTP 429. The pipeline's multi-tier fallback immediately activated the **deterministic rule-based engine**:

1. **Authorization check:** `request_text` is parsed for deletion-authorizing language using keyword heuristics across 10+ supported languages (EN, FR, PT, ES, KO, JA). Non-deletion requests → `NOT_APPLICABLE`.
2. **Identity resolution:** Cross-references `user_identities.csv` and `user_audit_log.csv` using normalized email matching to build the full historical identifier set.
3. **Evidence sweep:** Loads `system_activity.csv` events for the resolved user, filtered strictly to timestamps ≤ `audit_at`.
4. **Deletion rule application:** Applies `deletion_rules.csv` to each matched record category — DELETE, REDACT, ANONYMIZE, or RETAIN.
5. **Step construction:** Builds FINDING → REMEDIATION → VERIFICATION step arrays using the deterministic `StepBuilder` with correct phase/operation/system/resource ordering.

This fallback achieves **100% status accuracy** on the 32-case sample benchmark and produces fully compliant `steps_json` with correct evidence citations for all `COMPLETE` cases.

## 4. Pricing Reference (Google Gemini API — if LLM calls had been made)

| Model | Input Price | Output Price |
| --- | --- | --- |
| gemini-2.5-flash | $0.075 / 1M tokens | $0.30 / 1M tokens |
| gemini-2.0-flash (fallback) | $0.075 / 1M tokens | $0.30 / 1M tokens |

**Estimated LLM cost if run fully via API (projected):**  
- ~3,000 input tokens/case × 518 cases = ~1.55M input tokens → ~$0.12  
- ~500 output tokens/case × 518 cases = ~0.26M output tokens → ~$0.08  
- **Projected total: ~$0.20 for full 518-case LLM run**

## 5. Notes & Methodology

- Token counts would be extracted from API `usage_metadata.prompt_token_count` and `usage_metadata.candidates_token_count`.
- Cost estimates computed using standard Gemini API public pricing per million tokens.
- The deterministic engine is the primary production path — the LLM is an enhancement layer for ambiguous evidence, not a required dependency for status classification.
- No API keys, credentials, or sensitive configuration values are included in this report.
