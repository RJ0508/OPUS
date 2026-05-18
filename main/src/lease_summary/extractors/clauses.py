"""Extract clause summary fields from lease documents."""
from __future__ import annotations

import re

from ..models import Clauses, ExtractionResult
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument
from .base import find_labeled_value, make_result, not_found, ExtractionMethod


def extract_clauses(doc: DocumentText, split: SplitDocument) -> Clauses:
    c = Clauses()
    principal = split.principal_terms
    full = split.full_text
    sched_i = split.schedule_i

    c.user_clause_text = _extract_user(principal, doc)
    c.handover_condition_text = _extract_handover(principal, doc)
    c.break_clause_text = _extract_break_clause(principal, doc)
    # Clause text can live in either the main body or schedules. For full leases
    # (e.g. Trade Desk), key clauses often appear outside Schedule I.
    clause_source = "\n".join(t for t in (full, sched_i) if t)
    c.subletting_text = _extract_subletting(clause_source, doc)
    c.signage_text = _extract_signage(clause_source, doc)
    c.parking_text = _extract_parking(full, doc)
    c.restoration_obligations_text = _extract_restoration(full, doc)

    return c


def _extract_user(text: str, doc: DocumentText) -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Usage of Premises by the Tenant",
        "Use of Premises",
        "User",
    )
    if result:
        label, raw = result
        # Clean up verbose legal caveats
        raw = raw.split("The Landlord gives no warranty")[0].strip()
        page = _find_page(doc, label.split()[0][:10])
        return make_result(raw, 1.0, page, f"User: {raw}")
    return not_found()


def _extract_handover(text: str, doc: DocumentText) -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Hand-Over Condition",
        "Handover Condition",
        "Hand Over Condition",
    )
    if result:
        label, raw = result
        page = _find_page(doc, "Handover") or _find_page(doc, "Hand-Over")
        return make_result(raw, 1.0, page, f"Handover: {raw[:100]}")
    return not_found()


def _extract_break_clause(text: str, doc: DocumentText) -> ExtractionResult:
    result = find_labeled_value(text, "Break Clause")
    if result:
        label, raw = result
        page = _find_page(doc, "Break Clause")
        return make_result(raw, 1.0, page, f"Break Clause: {raw}")
    return not_found()


def _extract_subletting(text: str, doc: DocumentText) -> ExtractionResult:
    # Look for explicit prohibition clause
    prohibit_patterns = [
        re.compile(
            r"(?:Tenant\s+shall\s+not|shall\s+not).{0,50}"
            r"(?:transfer|assign|underlet|sublet|license|share|part\s+with).{0,200}?possession",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(r"\bNo\s*Alienation\b.{0,600}", re.IGNORECASE | re.DOTALL),
        re.compile(
            r"(?:not\s+to|shall\s+not).{0,120}?(?:assign|underlet|sublet|license)",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"no.{0,30}(?:subletting|sub-letting|assignment|underletting)",
            re.IGNORECASE,
        ),
    ]
    for pat in prohibit_patterns:
        m = pat.search(text)
        if m:
            page = _find_page_regex(doc, pat)
            # Use an excerpt of the actual clause text to avoid paraphrase drift.
            raw = re.sub(r"\s+", " ", m.group(0)).strip()
            # Require multiple alienation keywords to avoid weak/accidental matches.
            kws = ("assign", "transfer", "underlet", "sublet", "license", "possession")
            hits = sum(1 for k in kws if k in raw.lower())
            if hits < 2:
                continue
            summary = raw[:220]
            return make_result(
                summary, 0.85, page, m.group(0)[:150],
                method=ExtractionMethod.heuristic,
            )
    return ExtractionResult(value="n/a", confidence=0.50, review_flag="SUBLETTING_UNCLEAR")


def _extract_signage(text: str, doc: DocumentText) -> ExtractionResult:
    # Explicit "Signage" section with (a)/(b)/(c) bullets (Trade Desk style)
    section_pat = re.compile(r"\bSignage\b.{0,1600}", re.IGNORECASE | re.DOTALL)
    m = section_pat.search(text)
    if m:
        snippet = re.sub(r"\s+", " ", m.group(0)).strip()
        # Require strong signage-section signals (Trade Desk style) to avoid
        # treating generic "no signs without consent" as a full signage summary.
        if not any(token in snippet.lower() for token in ("logos", "directory", "elevator", "(a)", "(b)", "(c)")):
            return ExtractionResult(value="n/a", confidence=0.50, review_flag="SIGNAGE_UNCLEAR")
        snippet = snippet[:300]
        page = _find_page_regex(doc, re.compile(r"\bSignage\b", re.IGNORECASE))
        return make_result(snippet, 0.85, page, snippet[:150], method=ExtractionMethod.heuristic)

    # Offer-to-lease style: signage is commonly a consent/approval restriction,
    # not a dedicated "Signage" section.
    approval_patterns = [
        re.compile(
            r"(?:display|advertisement|signage|logo).{0,160}"
            r"(?:approval|consent|permission|prior\s+written)",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"not\s+without.{0,120}prior\s+(?:written\s+)?consent.{0,200}"
            r"(?:paint|exhibit|affix|display|signage|advertisement|logo)",
            re.IGNORECASE | re.DOTALL,
        ),
    ]
    for pat in approval_patterns:
        m = pat.search(text)
        if not m:
            continue
        summary = re.sub(r"\s+", " ", m.group(0)).strip()[:220]
        page = _find_page_regex(doc, pat)
        return make_result(summary, 0.85, page, m.group(0)[:150], method=ExtractionMethod.heuristic)

    return ExtractionResult(value="n/a", confidence=0.50, review_flag="SIGNAGE_UNCLEAR")


def _extract_parking(text: str, doc: DocumentText) -> ExtractionResult:
    # Prefer explicit section-style wording if present.
    section_pat = re.compile(r"\b(?:Car\s+Parking|Parking)\b.{0,1400}", re.IGNORECASE | re.DOTALL)
    kw = re.compile(r"parking|car\s*park|car\s*space", re.IGNORECASE)
    for m in kw.finditer(text):
        # Check if it's a grant of rights or just a mention
        ctx_start = max(0, m.start() - 80)
        ctx_end = min(len(text), m.end() + 500)
        ctx = text[ctx_start:ctx_end]
        if not re.search(r"\b(?:grant(?:ed)?|allow|entitle|provide|include)\b", ctx, re.IGNORECASE):
            continue
        # Prefer contexts that mention a number of spaces
        score = 1
        if re.search(r"\b\d+\s+car\s+parking\s+spaces?\b|\bcar\s+parking\s+spaces?\b", ctx, re.IGNORECASE):
            score = 2
        page = _find_page_regex(doc, kw)
        snippet = ctx.replace("\n", " ").strip()
        snippet = re.sub(r"\s+", " ", snippet)
        snippet = snippet[:300] if score == 2 else snippet[:200]
        return make_result(
            snippet,
            0.75 if score == 2 else 0.70,
            page,
            snippet[:120],
            method=ExtractionMethod.heuristic,
            flag="PARKING_UNCLEAR",
        )
    return ExtractionResult(value="n/a", confidence=0.85, evidence=[])


def _extract_restoration(text: str, doc: DocumentText) -> ExtractionResult:
    # Tier 1: explicit "as-is" / "original condition" clause
    asis_pat = re.compile(
        r"(?:yield\s+up|hand\s+over|deliver.{0,30}vacant\s+possession)"
        r".{0,150}?(?:as.is|original\s+condition|same\s+condition|good\s+order)",
        re.IGNORECASE | re.DOTALL,
    )
    m = asis_pat.search(text)
    if m:
        page = _find_page_regex(doc, asis_pat)
        return make_result(
            "Tenant to yield up in original/as-is condition.",
            0.85, page, m.group(0)[:100],
            method=ExtractionMethod.heuristic,
        )

    # Tier 2: reinstatement / remove fit-out obligation (tenant context only)
    # Exclude matches that are landlord obligations (fire/damage reinstatement or
    # "Landlord shall not be required to reinstate").
    reinstate_pat = re.compile(
        r"(?:reinstat(?!ement\s+deposit)|remove.{0,30}(?:partition|fixture|fitting|alteration)|"
        r"restore.{0,30}original)",
        re.IGNORECASE | re.DOTALL,
    )
    _landlord_ctx = re.compile(
        r"landlord.{0,80}not.{0,20}required\s+to\s+reinstat"
        r"|not\s+be\s+required\s+to\s+reinstat"
        r"|reinstat.{0,150}inhabitable"
        r"|inhabitable.{0,150}reinstat",
        re.IGNORECASE | re.DOTALL,
    )
    for m in reinstate_pat.finditer(text):
        ctx = text[max(0, m.start() - 250): m.end() + 250]
        if _landlord_ctx.search(ctx):
            continue  # landlord fire-damage context, not tenant obligation
        page = _find_page_regex(doc, reinstate_pat)
        return make_result(
            "Reinstatement of fit-out required at expiry.",
            0.75, page, m.group(0)[:100],
            method=ExtractionMethod.heuristic,
            flag="RESTORATION_UNCLEAR",
        )

    # Tier 3: fit-out deposit exists — implies some restoration obligation
    if re.search(r"Fit.out Deposit", text, re.IGNORECASE):
        return ExtractionResult(
            value="To be confirmed from Tenancy Agreement. Fit-out deposit held.",
            confidence=0.50,
            review_flag="RESTORATION_UNCLEAR",
        )

    return ExtractionResult(
        value="To be confirmed from Tenancy Agreement.",
        confidence=0.30,
        review_flag="RESTORATION_UNCLEAR",
    )


def _find_page(doc: DocumentText, snippet: str) -> int:
    for p in doc.pages:
        if snippet and snippet[:15].lower() in p.text.lower():
            return p.page_num
    return 0


def _find_page_regex(doc: DocumentText, pattern: re.Pattern) -> int:
    for p in doc.pages:
        if pattern.search(p.text):
            return p.page_num
    return 0
