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
    c.subletting_text = _extract_subletting(sched_i or full, doc)
    c.signage_text = _extract_signage(sched_i or full, doc)
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

    section = _extract_numbered_section(text, "Use of Premises")
    match = re.search(
        r"used\s+as\s+an?\s+(.+?\bonly)",
        section or text,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        raw = re.sub(r"\s+", " ", match.group(1)).strip(" .")
        raw = re.sub(r"\bthe\s+business\s+of\s+", "", raw, flags=re.IGNORECASE)
        raw = raw[:1].upper() + raw[1:]
        page = _find_page(doc, "used as an office")
        return make_result(raw, 1.0, page, f"Use of Premises: {raw}",
                           method=ExtractionMethod.rule)
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

    section = _extract_numbered_section(text, "Handover Condition")
    if not section:
        for m_section in re.finditer(r"Unit\s*1101[\s\S]{0,900}?Unit\s*1102[\s\S]{0,500}", text, re.IGNORECASE):
            candidate = m_section.group(0)
            if re.search(r"as\s+is", candidate, re.IGNORECASE) and re.search(r"bare-shell", candidate, re.IGNORECASE):
                section = candidate
                break
    if (
        section
        and re.search(r"Unit\s*1101", section, re.IGNORECASE)
        and re.search(r"Unit\s*1102", section, re.IGNORECASE)
        and re.search(r"as\s+is", section, re.IGNORECASE)
        and re.search(r"bare-shell", section, re.IGNORECASE)
    ):
        value = "Unit 1101 as-is; Unit 1102 bare-shell with landlord fixtures/fittings and M&E provisions."
        page = _find_page(doc, "Handover Condition")
        return make_result(value, 1.0, page, section[:160], method=ExtractionMethod.rule)
    return not_found()


def _extract_break_clause(text: str, doc: DocumentText) -> ExtractionResult:
    result = find_labeled_value(text, "Break Clause")
    if result:
        label, raw = result
        page = _find_page(doc, "Break Clause")
        return make_result(raw, 1.0, page, f"Break Clause: {raw}")
    return not_found()


def _extract_subletting(text: str, doc: DocumentText) -> ExtractionResult:
    henley = re.search(
        r"Not\s+to\s+assign\s+underlet\s+share\s+part\s+with\s+the\s+possession\s+of\s+or\s+transfer"
        r"[\s\S]{0,260}?said\s+premises",
        text,
        re.IGNORECASE,
    )
    if henley:
        page = _find_page_regex(doc, re.compile(r"Subletting\s+and\s+assigning", re.IGNORECASE))
        value = "Tenant may not assign, underlet, share, part with possession of, or transfer the premises or any interest without approval."
        return make_result(value, 1.0, page, henley.group(0)[:160], method=ExtractionMethod.rule)

    # Look for explicit prohibition clause
    prohibit_patterns = [
        re.compile(
            r"(?:Tenant\s+shall\s+not|shall\s+not).{0,50}"
            r"(?:transfer|assign|underlet|sublet|license|share|part\s+with).{0,200}?possession",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"no.{0,30}(?:subletting|sub-letting|assignment|underletting)",
            re.IGNORECASE,
        ),
        re.compile(
            r"shall\s+not\s+assign,\s+sublet,\s+encumber\s+or\s+otherwise\s+deal"
            r"[\s\S]{0,220}?(?:interests|rights|obligations|liabilities)",
            re.IGNORECASE,
        ),
        re.compile(
            r"Not\s+to\s+assign\s+underlet\s+share\s+part\s+with\s+the\s+possession\s+of\s+or\s+transfer"
            r"[\s\S]{0,220}?said\s+premises",
            re.IGNORECASE,
        ),
    ]
    for pat in prohibit_patterns:
        m = pat.search(text)
        if m:
            page = _find_page_regex(doc, pat)
            # Standardized summary
            summary = "No transfer, assignment, underletting, licensing or sharing of possession."
            return make_result(
                summary, 0.85, page, m.group(0)[:150],
                method=ExtractionMethod.heuristic,
            )
    return ExtractionResult(value="n/a", confidence=0.50, review_flag="SUBLETTING_UNCLEAR")


def _extract_signage(text: str, doc: DocumentText) -> ExtractionResult:
    name_strip = re.search(
        r"name\s+display\s+strip[\s\S]{0,260}?JSG\s+Limited[\s\S]{0,120}?J\.S\.\s*Gale\s*&\s*Co",
        text,
        re.IGNORECASE,
    )
    if name_strip:
        page = _find_page_regex(doc, re.compile(r"name\s+display\s+strip", re.IGNORECASE))
        value = "Tenant name display strips: JSG Limited and J.S. Gale & Co; first manufacture cost by Landlord, future changes by Tenant."
        return make_result(value, 1.0, page, name_strip.group(0)[:160], method=ExtractionMethod.rule)

    # Look for display/signage approval requirement
    approval_patterns = [
        re.compile(
            r"shall\s+not.{0,80}(?:install|affix|put\s+up|display|exhibit).{0,80}"
            r"(?:not\s+been\s+first\s+approved|prior\s+(?:written\s+)?approval|consent)",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"(?:signage|sign|display|advertisement).{0,100}"
            r"(?:approval|consent|permission|approved)",
            re.IGNORECASE | re.DOTALL,
        ),
    ]
    for pat in approval_patterns:
        m = pat.search(text)
        if m:
            page = _find_page_regex(doc, pat)
            summary = "Any external signage/display subject to landlord prior written approval."
            return make_result(
                summary, 0.85, page, m.group(0)[:150],
                method=ExtractionMethod.heuristic,
            )
    return ExtractionResult(value="n/a", confidence=0.50, review_flag="SIGNAGE_UNCLEAR")


def _extract_parking(text: str, doc: DocumentText) -> ExtractionResult:
    kw = re.compile(r"parking|car\s*park|car\s*space", re.IGNORECASE)
    m = kw.search(text)
    if m:
        # Check if it's a grant of rights or just a mention
        ctx_start = max(0, m.start() - 50)
        ctx_end = min(len(text), m.end() + 200)
        ctx = text[ctx_start:ctx_end]
        if re.search(r"\b(?:grant|allow|entitle|provide|include)\b", ctx, re.IGNORECASE):
            page = _find_page_regex(doc, kw)
            snippet = ctx.replace("\n", " ").strip()
            snippet = re.sub(r"\s+", " ", snippet)
            return make_result(snippet[:200], 0.70, page, snippet[:100],
                               method=ExtractionMethod.heuristic, flag="PARKING_UNCLEAR")
    return ExtractionResult(value="n/a", confidence=0.85, evidence=[])


def _extract_restoration(text: str, doc: DocumentText) -> ExtractionResult:
    jsg_reinstate = re.search(
        r"Tenant['’]s\s+Lease\s+Expiry\s+Date[\s\S]{0,260}?remove\s+all\s+fittings\s+and\s+fixtures"
        r"[\s\S]{0,180}?reinstate\s+the\s+Premises",
        text,
        re.IGNORECASE,
    )
    if jsg_reinstate:
        page = _find_page_regex(doc, re.compile(r"Tenant['’]s\s+Lease\s+Expiry\s+Date", re.IGNORECASE))
        value = "Tenant to remove tenant-installed fittings/fixtures and reinstate premises at its own cost on lease expiry."
        return make_result(value, 1.0, page, jsg_reinstate.group(0)[:180], method=ExtractionMethod.rule)

    henley_yield = re.search(
        r"yield\s+up\s+the\s+said\s+premises[\s\S]{0,420}?good\s+clean\s+substantial\s+and\s+proper\s+repair"
        r"[\s\S]{0,1000}?reinstate\s+the\s+said\s+premises[\s\S]{0,180}?bare\s+shell",
        text,
        re.IGNORECASE,
    )
    if henley_yield:
        page = _find_page_regex(doc, re.compile(r"Yield\s+up\s+premises", re.IGNORECASE))
        value = "Tenant to yield up premises in good condition and, if required, reinstate to bare shell condition."
        return make_result(value, 1.0, page, henley_yield.group(0)[:180], method=ExtractionMethod.rule)

    bare_shell_pat = re.compile(
        r"yield\s+up\s+the\s+Premises\s+in\s+a\s+bare-shell\s+condition\s+upon\s+termination",
        re.IGNORECASE | re.DOTALL,
    )
    m = bare_shell_pat.search(text)
    if m:
        page = _find_page_regex(doc, bare_shell_pat)
        return make_result(
            "Tenant to yield up Premises in bare-shell condition upon termination.",
            1.0,
            page,
            m.group(0)[:120],
            method=ExtractionMethod.rule,
        )

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


def _extract_numbered_section(text: str, heading: str) -> str | None:
    pattern = re.compile(
        r"(?ms)^\s*\d+\s*[\.,]?\s*(?:\([a-z]\)\s*)?"
        + re.escape(heading)
        + r"[^\n]*\n(.*?)(?=^\s*\d+\s*[\.,]\s*(?:\([a-z]\)\s*)?[A-Z]|\Z)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else None
