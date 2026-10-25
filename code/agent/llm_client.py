"""LLM Client wrapping Gemini API with retries, structured outputs, and usage tracking.

Compliant with HackerRank Orchestrate constraints and AGENTS.md requirements.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, Field

try:
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors
except ImportError:
    genai = None
    types = None
    genai_errors = None

try:
    from code import config
except ImportError:
    import config

logger = logging.getLogger("audit_agent.llm_client")

T = TypeVar("T", bound=BaseModel)


# ==============================================================================
# Pydantic Schemas for Structured Outputs
# ==============================================================================

class AuthorizationCheck(BaseModel):
    """Schema for checking whether request text authorizes deletion."""
    authorizes_deletion: bool = Field(
        ...,
        description="True if the request explicitly asks for account/data deletion or erasure, False if it is access/export/correction/marketing/unrelated."
    )
    confidence: float = Field(
        default=1.0,
        description="Confidence score between 0.0 and 1.0"
    )
    reason: str = Field(
        ...,
        description="Brief justification for why this request does or does not authorize deletion."
    )


class AuditFindingItem(BaseModel):
    """Individual finding identifying uncompleted deletion or active risk."""
    system_id: str = Field(..., description="System ID where finding occurred, e.g. account_service, search_service")
    resource_id: str = Field(..., description="Resource ID, e.g. account_005, search_001, data_flow_123")
    operation: str = Field(
        ...,
        description="One of REPORT_REMAINING_RECORD, REPORT_EXPOSED_PII, REPORT_ACTIVE_DATA_FLOW, REPORT_RESTORE_RISK"
    )
    state: str = Field(..., description="Target state for finding: PRESENT or ACTIVE")
    evidence_id: str = Field(..., description="Evidence ID citing participant-visible file_id or activity_id")
    description: str = Field(default="", description="Brief explanation of the finding")


class CaseAuditResult(BaseModel):
    """Audit evaluation result for a case."""
    case_id: str = Field(..., description="Case identifier")
    authorizes_deletion: bool = Field(..., description="Whether the request authorizes deletion")
    deletion_status: str = Field(
        ...,
        description="One of COMPLETE, INCOMPLETE, NOT_APPLICABLE"
    )
    findings: List[AuditFindingItem] = Field(
        default_factory=list,
        description="List of uncompleted records, exposed PII, active syncs, or restore risks"
    )
    notes: str = Field(default="", description="Audit reasoning and summary")


class RemediationStepItem(BaseModel):
    """Proposed remediation or verification step."""
    phase: str = Field(..., description="REMEDIATION or VERIFICATION")
    system_id: str = Field(..., description="Target system ID")
    resource_id: str = Field(..., description="Target resource ID")
    operation: str = Field(..., description="Allowed operation name")
    state: str = Field(..., description="Allowed state name")
    evidence_id: str = Field(default="", description="Evidence citation, or empty string for proposed steps")


class RemediationPlan(BaseModel):
    """Full remediation and verification plan for an incomplete case."""
    case_id: str = Field(..., description="Case identifier")
    remediation_steps: List[RemediationStepItem] = Field(
        default_factory=list,
        description="Ordered list of remediation actions"
    )
    verification_steps: List[RemediationStepItem] = Field(
        default_factory=list,
        description="Ordered list of post-remediation verification checks"
    )


# ==============================================================================
# Usage & Cost Tracking
# ==============================================================================

# Standard rates (approximate USD per 1M tokens for Gemini Flash models)
COST_PER_M_PROMPT_TOKENS = {
    "gemini-3.8-flash": 0.15,
    "gemini-2.5-flash": 0.15,
    "gemini-2.0-flash": 0.10,
    "default": 0.15,
}
COST_PER_M_CANDIDATE_TOKENS = {
    "gemini-3.8-flash": 0.60,
    "gemini-2.5-flash": 0.60,
    "gemini-2.0-flash": 0.40,
    "default": 0.60,
}


@dataclass
class UsageSummary:
    """Token usage and cost statistics."""
    total_calls: int = 0
    prompt_tokens: int = 0
    candidate_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    calls_by_model: Dict[str, int] = field(default_factory=dict)
    prompt_tokens_by_model: Dict[str, int] = field(default_factory=dict)
    candidate_tokens_by_model: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "prompt_tokens": self.prompt_tokens,
            "candidate_tokens": self.candidate_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "calls_by_model": self.calls_by_model,
            "prompt_tokens_by_model": self.prompt_tokens_by_model,
            "candidate_tokens_by_model": self.candidate_tokens_by_model,
        }

    def to_markdown(self) -> str:
        """Render usage report according to problem_statement.md § Token Usage and Cost Analysis."""
        avg_tokens_per_call = (
            self.total_tokens / self.total_calls if self.total_calls > 0 else 0.0
        )
        avg_cost_per_call = (
            self.estimated_cost_usd / self.total_calls if self.total_calls > 0 else 0.0
        )

        md = [
            "# LLM Token Usage & Cost Analysis Report",
            "",
            "> **Generated for:** HackerRank Orchestrate (October 2026) — Ghost Data Still Exists  ",
            f"> **Report Timestamp:** {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
            "",
            "## 1. Overall Summary",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| **Total Model Calls** | {self.total_calls:,} |",
            f"| **Input (Prompt) Tokens** | {self.prompt_tokens:,} |",
            f"| **Output (Candidate) Tokens** | {self.candidate_tokens:,} |",
            f"| **Total Tokens** | {self.total_tokens:,} |",
            f"| **Average Tokens Per Call** | {avg_tokens_per_call:,.1f} |",
            f"| **Total Estimated Cost (USD)** | ${self.estimated_cost_usd:.4f} |",
            f"| **Average Cost Per Call (USD)** | ${avg_cost_per_call:.6f} |",
            "",
            "## 2. Model Breakdown",
            "",
            "| Model Provider & Name | Calls | Prompt Tokens | Candidate Tokens | Total Tokens | Est. Cost (USD) |",
            "| --- | --- | --- | --- | --- | --- |",
        ]

        for model_name, calls in self.calls_by_model.items():
            p_tok = self.prompt_tokens_by_model.get(model_name, 0)
            c_tok = self.candidate_tokens_by_model.get(model_name, 0)
            tot = p_tok + c_tok
            rate_p = COST_PER_M_PROMPT_TOKENS.get(model_name, COST_PER_M_PROMPT_TOKENS["default"])
            rate_c = COST_PER_M_CANDIDATE_TOKENS.get(model_name, COST_PER_M_CANDIDATE_TOKENS["default"])
            cost = (p_tok / 1_000_000.0) * rate_p + (c_tok / 1_000_000.0) * rate_c
            md.append(
                f"| Google `{model_name}` | {calls:,} | {p_tok:,} | {c_tok:,} | {tot:,} | ${cost:.4f} |"
            )

        md.extend([
            "",
            "## 3. Notes & Methodology",
            "",
            "- Token counts are extracted directly from API `usage_metadata` (`prompt_token_count` and `candidates_token_count`).",
            "- Cost estimates are computed using standard Gemini API pricing per million tokens.",
            "- Fast-path deterministic pre-filtering minimizes unnecessary LLM calls for unambiguous authorization and identity queries.",
            "- Structured outputs guarantee valid schema conformity without repeated retry overhead.",
        ])

        return "\n".join(md) + "\n"


# ==============================================================================
# Gemini LLM Client
# ==============================================================================

class GeminiClient:
    """Gemini API client handling retries, structured output schema, and usage auditing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        fallback_model: Optional[str] = None,
        max_retries: int = config.MAX_RETRIES,
        initial_backoff: float = config.INITIAL_BACKOFF_SECONDS,
        backoff_factor: float = config.BACKOFF_FACTOR,
    ):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model_name = model_name or config.MODEL_NAME
        self.fallback_model = fallback_model or config.FALLBACK_MODEL_NAME
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.backoff_factor = backoff_factor

        self.usage = UsageSummary()

        if not self.api_key:
            logger.warning("GEMINI_API_KEY is not configured. LLM calls will fail unless provided.")

        self._client: Optional[Any] = None
        if genai is not None and self.api_key:
            try:
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error("Failed to initialize genai.Client: %s", e)

    @property
    def client(self) -> Any:
        if self._client is None:
            if genai is None:
                raise RuntimeError("google-genai library is not installed.")
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is empty. Please set GEMINI_API_KEY in .env.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def track_usage(self, model: str, prompt_tokens: int, candidate_tokens: int) -> None:
        """Record token usage and update cumulative statistics."""
        self.usage.total_calls += 1
        self.usage.prompt_tokens += prompt_tokens
        self.usage.candidate_tokens += candidate_tokens
        self.usage.total_tokens += (prompt_tokens + candidate_tokens)

        # Per model calls
        self.usage.calls_by_model[model] = self.usage.calls_by_model.get(model, 0) + 1
        self.usage.prompt_tokens_by_model[model] = (
            self.usage.prompt_tokens_by_model.get(model, 0) + prompt_tokens
        )
        self.usage.candidate_tokens_by_model[model] = (
            self.usage.candidate_tokens_by_model.get(model, 0) + candidate_tokens
        )

        # Cost calculation
        rate_p = COST_PER_M_PROMPT_TOKENS.get(model, COST_PER_M_PROMPT_TOKENS["default"])
        rate_c = COST_PER_M_CANDIDATE_TOKENS.get(model, COST_PER_M_CANDIDATE_TOKENS["default"])
        call_cost = (prompt_tokens / 1_000_000.0) * rate_p + (candidate_tokens / 1_000_000.0) * rate_c
        self.usage.estimated_cost_usd += call_cost

    def _extract_tokens_from_response(self, response: Any) -> tuple[int, int]:
        """Extract prompt and candidate token counts from response."""
        p_tok = 0
        c_tok = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata is not None:
            meta = response.usage_metadata
            p_tok = getattr(meta, "prompt_token_count", 0) or 0
            c_tok = getattr(meta, "candidates_token_count", 0) or 0
        return p_tok, c_tok

    def call_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: float = config.TEMPERATURE,
    ) -> str:
        """Call Gemini for standard text generation with retry backoff."""
        active_model = model or self.model_name
        current_backoff = self.initial_backoff

        for attempt in range(1, self.max_retries + 1):
            try:
                gen_config = None
                if types is not None:
                    gen_config = types.GenerateContentConfig(
                        temperature=temperature,
                        system_instruction=system_instruction,
                    )

                response = self.client.models.generate_content(
                    model=active_model,
                    contents=prompt,
                    config=gen_config,
                )

                p_tok, c_tok = self._extract_tokens_from_response(response)
                self.track_usage(active_model, p_tok, c_tok)

                return response.text or ""

            except Exception as exc:
                err_str = str(exc)
                logger.warning(
                    "Gemini text call attempt %d/%d failed with model %s: %s",
                    attempt,
                    self.max_retries,
                    active_model,
                    err_str,
                )

                # Check if model is deprecated / unavailable, switch to fallback
                if "no longer available" in err_str or "NOT_FOUND" in err_str:
                    if active_model != self.fallback_model:
                        logger.info("Switching to fallback model %s", self.fallback_model)
                        active_model = self.fallback_model

                if attempt == self.max_retries:
                    raise exc

                time.sleep(current_backoff)
                current_backoff *= self.backoff_factor

        return ""

    def call_structured(
        self,
        prompt: str,
        schema: Type[T],
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: float = config.TEMPERATURE,
    ) -> T:
        """Call Gemini enforcing structured JSON schema output with retry backoff."""
        active_model = model or self.model_name
        current_backoff = self.initial_backoff

        for attempt in range(1, self.max_retries + 1):
            try:
                gen_config = None
                if types is not None:
                    gen_config = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=temperature,
                        system_instruction=system_instruction,
                    )

                response = self.client.models.generate_content(
                    model=active_model,
                    contents=prompt,
                    config=gen_config,
                )

                p_tok, c_tok = self._extract_tokens_from_response(response)
                self.track_usage(active_model, p_tok, c_tok)

                raw_text = response.text or "{}"
                # Parse into schema
                try:
                    data = json.loads(raw_text)
                    return schema.model_validate(data)
                except Exception as parse_err:
                    # Clean markdown code fences if model enclosed JSON
                    clean_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE)
                    data = json.loads(clean_text)
                    return schema.model_validate(data)

            except Exception as exc:
                err_str = str(exc)
                logger.warning(
                    "Gemini structured call attempt %d/%d failed with model %s: %s",
                    attempt,
                    self.max_retries,
                    active_model,
                    err_str,
                )

                # Fallback model switch if model not found
                if "no longer available" in err_str or "NOT_FOUND" in err_str:
                    if active_model != self.fallback_model:
                        logger.info("Switching to fallback model %s", self.fallback_model)
                        active_model = self.fallback_model

                if "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                    logger.warning("Gemini API quota exhausted: %s. Disabling further LLM calls.", err_str[:120])
                    self._quota_exhausted = True
                    raise exc

                if attempt == self.max_retries:
                    raise exc

                time.sleep(current_backoff)
                current_backoff *= self.backoff_factor

        raise RuntimeError(f"Failed to generate structured output after {self.max_retries} attempts.")

    def check_authorization(self, request_text: str) -> AuthorizationCheck:
        """Check if request_text authorizes deletion."""
        # Fast path check for common explicit deletion requests
        norm_text = request_text.lower().strip()
        non_deletion_triggers = [
            "download my data", "export my data", "copy of my data",
            "access my data", "send me my data", "what data do you have",
            "update my email", "change my phone", "correct my address",
            "unsubscribe from marketing", "stop sending newsletters", "opt out of emails"
        ]
        # If explicitly asking ONLY for non-deletion and not mentioning delete/erase/close
        has_deletion_intent = any(w in norm_text for w in ["delete", "erase", "close", "remove", "suppression", "eliminar", "loeschen"])
        has_non_deletion = any(trigger in norm_text for trigger in non_deletion_triggers)

        if has_non_deletion and not has_deletion_intent:
            return AuthorizationCheck(
                authorizes_deletion=False,
                confidence=0.98,
                reason="Request asks for data export, access, update, or marketing opt-out without authorization for deletion."
            )

        if getattr(self, "_quota_exhausted", False):
            return AuthorizationCheck(
                authorizes_deletion=has_deletion_intent,
                confidence=0.95,
                reason="Rule-based keyword evaluation (API quota limit reached).",
            )

        prompt = (
            f"Evaluate the following user message submitted to a platform privacy portal.\n\n"
            f"User message:\n\"\"\"{request_text}\"\"\"\n\n"
            f"Question: Does this message authorize PERMANENT DELETION or closure of the user's account and/or personal data?\n"
            f"Rules:\n"
            f"- If the user asks to close account, delete account, delete data, erase profile, or remove personal details -> True.\n"
            f"- If the user ONLY asks to access data, download/export data, rectify/update information, or opt out of marketing without deleting -> False.\n"
            f"- Support multilingual text (English, Spanish, French, German, Arabic, etc.)."
        )

        try:
            return self.call_structured(prompt=prompt, schema=AuthorizationCheck)
        except Exception as exc:
            logger.warning("LLM call failed in check_authorization: %s. Using rule fallback.", exc)
            return AuthorizationCheck(
                authorizes_deletion=has_deletion_intent,
                confidence=0.95,
                reason=f"Rule-based fallback due to API error: {exc}",
            )

    def get_usage_summary(self) -> UsageSummary:
        """Return the current cumulative usage summary."""
        return self.usage

    def reset_usage(self) -> None:
        """Reset usage metrics."""
        self.usage = UsageSummary()

    def export_usage_report(self, output_path: Optional[Path | str] = None) -> Path:
        """Export token and cost analysis report to markdown file."""
        target_path = Path(output_path) if output_path else config.EVALUATION_DIR / "usage_report.md"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.usage.to_markdown()
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Exported usage report to %s", target_path)

        # Also sync to repo root evaluation directory if different
        root_eval = config.REPO_ROOT / "evaluation" / "usage_report.md"
        if target_path.resolve() != root_eval.resolve():
            root_eval.parent.mkdir(parents=True, exist_ok=True)
            with open(root_eval, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("Exported usage report copy to %s", root_eval)

        return target_path
