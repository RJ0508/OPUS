"""AI-assisted clause extraction using an OpenAI-compatible provider."""
from __future__ import annotations

from lease_summary.llm_config import build_openai_client, _safe_chat_create
from ..models import ExtractionResult, Evidence, ExtractionMethod
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument

# ── Config ──────────────────────────────────────────────────────────────────
_DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
_DEFAULT_MODEL = "kimi-k2.5"
_SYSTEM_PROMPT = (
    "You are a Hong Kong commercial lease analyst. "
    "Extract key facts from lease clauses in concise English. "
    "Respond in 1-2 sentences only. Do not add commentary."
)

# ── Clause extraction targets ────────────────────────────────────────────────
_CLAUSE_PROMPTS: dict[str, str] = {
    "subletting": (
        "Summarize the subletting/assignment rights: "
        "is it prohibited, or allowed with conditions? State who must give consent."
    ),
    "signage": (
        "Summarize the signage/display rights: "
        "what restrictions apply and whose approval is needed?"
    ),
    "restoration": (
        "Summarize the restoration/reinstatement obligation at lease expiry: "
        "must the tenant restore to original condition, remove fit-out, or hand over as-is?"
    ),
    "user": (
        "State the permitted use of the premises in one sentence."
    ),
    "tenant_termination": (
        "Does the tenant have any break clause or early termination right? "
        "If yes, state the conditions. If no, say 'No tenant break clause.'"
    ),
}


def ai_enhance_clauses(
    clauses_obj,
    doc: DocumentText,
    split: SplitDocument,
) -> None:
    """
    Enhance low-confidence clause fields in-place using the configured AI provider.
    Only overrides fields with confidence < 0.90.
    """
    client, settings = _get_client()
    if client is None or settings is None:
        return

    # Build context text: principal terms + schedule_i (up to ~8000 chars)
    context = (split.principal_terms + "\n\n" + (split.schedule_i or ""))[:8000]

    for field_name, prompt in _CLAUSE_PROMPTS.items():
        if field_name == "tenant_termination":
            continue  # handled separately via ai_enhance_term
        target = _get_field(clauses_obj, field_name)
        if target is None:
            continue
        # Skip if already determined with high confidence (including explicit N/A)
        if target.confidence >= 0.90 and target.value:
            continue

        result = _ask_ai(client, settings.model, context, prompt)
        if result:
            page = _find_page_for_clause(doc, field_name)
            _set_field(clauses_obj, field_name, ExtractionResult(
                value=result,
                confidence=0.80,
                evidence=[Evidence(
                    page=page,
                    quote=result[:200],
                    method=ExtractionMethod.heuristic,
                )],
                review_flag=None,
            ))


def ai_enhance_term(term_obj, doc: DocumentText, split: SplitDocument) -> None:
    """Enhance tenant_termination_right_text on the Term object."""
    client, settings = _get_client()
    if client is None or settings is None:
        return

    target = getattr(term_obj, "tenant_termination_right_text", None)
    if target is None:
        return
    # Skip if already determined (including explicit N/A — do not second-guess)
    if target.confidence >= 0.90 and target.value:
        return

    context = (split.principal_terms + "\n\n" + (split.schedule_i or ""))[:8000]
    result = _ask_ai(client, settings.model, context, _CLAUSE_PROMPTS["tenant_termination"])
    if result:
        page = _find_page_for_clause(doc, "tenant_termination")
        term_obj.tenant_termination_right_text = ExtractionResult(
            value=result,
            confidence=0.80,
            evidence=[Evidence(page=page, quote=result[:200], method=ExtractionMethod.heuristic)],
            review_flag=None,
        )


# ── Internal helpers ─────────────────────────────────────────────────────────

def _get_client():
    return build_openai_client(_DEFAULT_BASE_URL, _DEFAULT_MODEL)


def _ask_ai(client, model: str, context: str, question: str) -> str | None:
    try:
        resp = _safe_chat_create(
            client,
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Lease text:\n{context}\n\nQuestion: {question}"},
            ],
            max_tokens=150,
            temperature=1,
        )
        text = resp.choices[0].message.content.strip()
        return text if len(text) > 10 else None
    except Exception:
        return None


def _get_field(clauses_obj, field_name: str) -> ExtractionResult | None:
    mapping = {
        "subletting": "subletting_text",
        "signage": "signage_text",
        "restoration": "restoration_obligations_text",
        "user": "user_clause_text",
        "tenant_termination": None,  # lives on term, not clauses
    }
    attr = mapping.get(field_name)
    if attr:
        return getattr(clauses_obj, attr, None)
    return None


def _set_field(clauses_obj, field_name: str, value: ExtractionResult) -> None:
    mapping = {
        "subletting": "subletting_text",
        "signage": "signage_text",
        "restoration": "restoration_obligations_text",
        "user": "user_clause_text",
    }
    attr = mapping.get(field_name)
    if attr:
        setattr(clauses_obj, attr, value)


def _find_page_for_clause(doc: DocumentText, clause_name: str) -> int:
    keywords = {
        "subletting": ["sublet", "assignment", "underletting"],
        "signage": ["signage", "signboard", "advertisement"],
        "restoration": ["reinstate", "restore", "original condition", "yield up"],
        "user": ["permitted use", "usage", "User"],
        "tenant_termination": ["break clause", "termination"],
    }
    for kw in keywords.get(clause_name, []):
        for p in doc.pages:
            if kw.lower() in p.text.lower():
                return p.page_num
    return 0
