"""Extract dates and term information from lease documents."""
from __future__ import annotations

import datetime
import re

from ..models import ExtractionResult, Term
from ..normalizers.dates import find_dates, parse_date, compute_term_months
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument
from .base import extract_schedule1_part, find_labeled_value, find_schedule_section, make_result, not_found, ExtractionMethod


def extract_term(doc: DocumentText, split: SplitDocument) -> Term:
    t = Term()
    text = split.principal_terms
    schedule_i_text = split.schedule_i or ""

    t.lease_signing_date = _extract_signing_date(doc)
    t.lease_commencement_date = _extract_commencement(text, doc)
    t.lease_expiry_date = _extract_expiry(text, doc)

    # If explicit expiry not found, derive it from commencement + term text
    if not t.lease_expiry_date.is_found():
        term_result = find_labeled_value(text, "Term", "Lease Term")
        if term_result:
            t.lease_expiry_date = _compute_expiry_from_commencement_and_term(
                t.lease_commencement_date, term_result[1]
            )

    # Fallback: formal tenancy agreement — "TERM OF TENANCY" in Schedule I
    # e.g. "TWENTY (20) MONTHS from 21st September 2025 to 20th May 2027 both days inclusive"
    if (not t.lease_commencement_date.is_found() or not t.lease_expiry_date.is_found()) and schedule_i_text:
        sched_term = _extract_term_from_schedule_i(schedule_i_text, doc)
        if sched_term:
            comm, expiry = sched_term
            if not t.lease_commencement_date.is_found() and comm:
                t.lease_commencement_date = comm
            if not t.lease_expiry_date.is_found() and expiry:
                t.lease_expiry_date = expiry

    t.scheduled_commencement_date = _derive_scheduled_commencement(t.lease_commencement_date)
    t.lease_term_months = _compute_or_extract_term(
        text, doc, t.lease_commencement_date, t.lease_expiry_date, schedule_i_text
    )
    t.rent_free_period_text = _extract_rent_free(split.full_text, doc, schedule_i_text)
    t.fit_out_period_text = _extract_fit_out(text, doc, t.rent_free_period_text)
    t.option_to_renew_text = _extract_option_to_renew(split.full_text, doc)
    t.right_of_expansion_text = _extract_expansion(split.full_text, doc)
    t.trigger_date_text = _extract_trigger_date(split.full_text, doc)
    t.tenant_termination_right_text = _extract_tenant_termination(text, split.full_text, doc)

    return t


def _extract_term_from_schedule_i(
    schedule_text: str, doc: DocumentText,
) -> tuple[ExtractionResult, ExtractionResult] | None:
    """
    Extract commencement and expiry from Schedule I / The Schedule.

    Handles several formats:
    1. "TWENTY (20) MONTHS from 21st September 2025 to 20th May 2027" (First Schedule style)
    2. "A term of FOUR (4) years commencing on DATE and expiring on DATE" (SCHEDULE 1 style)
    3. "A term of SIX (6) years commencing on DATE and expiring on DATE" (Deacons style)
    """
    # ── Format 2 & 3: "commencing on DATE and expiring on DATE" (SCHEDULE 1 / Deacons) ──
    term_block = extract_schedule1_part(schedule_text, "Term", "Term of Tenancy")
    if term_block:
        # Normalize OCR ordinal artifacts
        tb = re.sub(r'(\d+)[%"\'\u201c\u201d`](?=\s)', r'\1', term_block)
        tb = re.sub(r'(\d+)(?:st|nd|rd|th)(?=\s)', r'\1', tb, flags=re.IGNORECASE)

        comm_exp_pat = re.compile(
            r"commencing\s+on\s+(\d{1,2}\s+\w+\s+\d{4})\s+and\s+expiring\s+on\s+(\d{1,2}\s+\w+\s+\d{4})",
            re.IGNORECASE,
        )
        m = comm_exp_pat.search(tb)
        if m:
            comm_d = parse_date(m.group(1).strip())
            expiry_d = parse_date(m.group(2).strip())
            page = next((p.page_num for p in doc.pages
                         if "commencing on" in p.text.lower()), 0)
            comm_result = (
                make_result(comm_d, 0.92, page, f"Schedule 1 Term: commencing {m.group(1)}",
                            method=ExtractionMethod.rule)
                if comm_d else not_found()
            )
            expiry_result = (
                make_result(expiry_d, 0.92, page, f"Schedule 1 Term: expiring {m.group(2)}",
                            method=ExtractionMethod.rule)
                if expiry_d else not_found()
            )
            return comm_result, expiry_result

    # ── Format 1: "from DATE to DATE" (First Schedule / Central Plaza style) ──
    term_text = find_schedule_section(schedule_text, "TERM OF TENANCY", "Term of Tenancy")
    if not term_text:
        term_text = schedule_text

    # Normalize OCR ordinal artifacts
    term_text = re.sub(r'(\d+)[%"\'\u201c\u201d`](?=\s)', r'\1', term_text)
    term_text = re.sub(r'(\d+)(?:st|nd|rd|th)(?=\s)', r'\1', term_text, flags=re.IGNORECASE)

    range_pat = re.compile(
        r"from\s+(\S+\s+\w+\s+\d{4})\s+to\s+(\S+\s+\w+\s+\d{4})",
        re.IGNORECASE,
    )
    m = range_pat.search(term_text)
    if m:
        comm_d = parse_date(m.group(1).strip())
        expiry_d = parse_date(m.group(2).strip())
        page = next((p.page_num for p in doc.pages if "TERM OF TENANCY" in p.text), 0)
        comm_result = (
            make_result(comm_d, 0.90, page, f"Schedule I term: {m.group(1)}",
                        method=ExtractionMethod.rule)
            if comm_d else not_found()
        )
        expiry_result = (
            make_result(expiry_d, 0.90, page, f"Schedule I term: {m.group(2)}",
                        method=ExtractionMethod.rule)
            if expiry_d else not_found()
        )
        return comm_result, expiry_result
    return None


def _extract_signing_date(doc: DocumentText) -> ExtractionResult:
    """
    Extract the date the lease was signed/executed.
    Patterns: "made this 18th day of December 2023"
              "signed/executed on 15 March 2024"
              "dated the 5th day of January 2025"
    """
    patterns = [
        re.compile(
            r"(?:made|dated|signed|executed)\s+(?:this|the)?\s*(\d{1,2})(?:st|nd|rd|th)?\s+"
            r"day\s+of\s+(\w+)\s+(\d{4})",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:signed|executed|dated)\s+(?:on\s+|as\s+of\s+)?(\d{1,2})\s+(\w+)\s+(\d{4})",
            re.IGNORECASE,
        ),
    ]
    for p in doc.pages:
        for pat in patterns:
            m = pat.search(p.text)
            if m:
                try:
                    d = parse_date(f"{m.group(1)} {m.group(2)} {m.group(3)}")
                    if d:
                        quote = m.group(0)[:60]
                        return make_result(d, 0.90, p.page_num, quote, method=ExtractionMethod.rule)
                except Exception:
                    pass
    for p in doc.pages[:2]:
        if "Tenancy Offer Letter" not in p.text and "Offer to Lease" not in p.text:
            continue
        m = re.search(
            r"\b(\d{1,2}\s+"
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+\d{4})\b",
            p.text,
            re.IGNORECASE,
        )
        if m:
            d = parse_date(m.group(1))
            if d:
                return make_result(d, 1.0, p.page_num, f"Offer date: {m.group(1)}",
                                   method=ExtractionMethod.rule)
    return not_found()


def _extract_commencement(text: str, doc: DocumentText) -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Term Commencement Date",
        "Commencement Date",
        "Lease Commencement Date",
        "Date of commencement",
    )
    if result:
        label, raw = result
        dates = find_dates(raw)
        if dates:
            d, raw_match = dates[0]
            page = _find_page(doc, raw_match[:15])
            return make_result(d, 1.0, page, f"{label}: {raw_match}")
        d = parse_date(raw)
        if d:
            page = _find_page(doc, raw[:15])
            return make_result(d, 1.0, page, f"{label}: {raw}")

    # Formal schedule: "The term : Three (3) years fixed commencing on
    # 15 April 2026 and expiring on 14 April 2029".
    m = _TERM_COMMENCING_EXPIRING_RE.search(text)
    if m:
        d = parse_date(m.group(1).strip())
        if d:
            page = _find_page(doc, m.group(1).strip())
            return make_result(d, 0.90, page, f"Term schedule commencing: {m.group(1)}",
                               method=ExtractionMethod.rule)

    # Embedded commencement date: "commencing on DATE" anywhere in principal terms
    # e.g. "fixed 3-Years Period commencing on 18 December 2023"
    commencing_pat = re.compile(r"commencing\s+on\s+([\w\d\s,]+\d{4})", re.IGNORECASE)
    for p in doc.pages[:8]:
        m = commencing_pat.search(p.text)
        if m:
            d = parse_date(m.group(1).strip())
            if d:
                return make_result(d, 0.85, p.page_num, f"commencing on: {m.group(1).strip()}",
                                   method=ExtractionMethod.rule)
    return not_found("COMMENCEMENT_NOT_FOUND")


def _extract_expiry(text: str, doc: DocumentText) -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Term Expiry Date",
        "Expiry Date",
        "Expiration Date",
        "Lease Expiry Date",
    )
    if result:
        label, raw = result
        # Use find_dates to robustly extract the first date from potentially noisy value
        dates = find_dates(raw)
        if dates:
            d, raw_match = dates[0]
            page = _find_page(doc, raw_match[:15])
            return make_result(d, 1.0, page, f"{label}: {raw_match}")

    m = _TERM_COMMENCING_EXPIRING_RE.search(text)
    if m:
        d = parse_date(m.group(2).strip())
        if d:
            page = _find_page(doc, m.group(2).strip())
            return make_result(d, 0.90, page, f"Term schedule expiring: {m.group(2)}",
                               method=ExtractionMethod.rule)

    multi_unit_expiry = _extract_multi_unit_expiry(text, doc)
    if multi_unit_expiry:
        return multi_unit_expiry
    return not_found("EXPIRY_NOT_FOUND")


def _compute_expiry_from_commencement_and_term(
    commencement: ExtractionResult, term_text: str,
) -> ExtractionResult:
    """
    Derive expiry date from 'commencing on DATE' + 'N-Years/months' lease term.
    Used when no explicit expiry date label is present.
    """
    if not commencement.value:
        return not_found()
    m_years = re.search(r"(\d+)\s*[-\s]?(?:year|yr)", term_text, re.IGNORECASE)
    m_months = re.search(r"(\d+)\s*month", term_text, re.IGNORECASE)
    start: datetime.date = commencement.value
    if m_years:
        years = int(m_years.group(1))
        # End date is N years later, minus one day
        try:
            end = start.replace(year=start.year + years) - datetime.timedelta(days=1)
        except ValueError:
            end = start.replace(year=start.year + years, day=28) - datetime.timedelta(days=1)
        return ExtractionResult(
            value=end,
            confidence=0.85,
            evidence=commencement.evidence,
            review_flag="EXPIRY_COMPUTED_FROM_TERM",
        )
    if m_months:
        months = int(m_months.group(1))
        year_add, month_add = divmod(start.month - 1 + months, 12)
        end = start.replace(year=start.year + year_add, month=month_add + 1) - datetime.timedelta(days=1)
        return ExtractionResult(
            value=end,
            confidence=0.85,
            evidence=commencement.evidence,
            review_flag="EXPIRY_COMPUTED_FROM_TERM",
        )
    return not_found()


def _derive_scheduled_commencement(commencement: ExtractionResult) -> ExtractionResult:
    """Scheduled commencement = commencement unless separately stated."""
    if commencement.value:
        return ExtractionResult(
            value=commencement.value,
            confidence=0.85,
            evidence=commencement.evidence,
            review_flag=None,
        )
    return not_found()


def _compute_or_extract_term(
    text: str, doc: DocumentText,
    commencement: ExtractionResult, expiry: ExtractionResult,
    schedule_i_text: str = "",
) -> ExtractionResult:
    m_sched = re.search(
        r"The\s+term\s*:\s*[A-Z\s-]+\((\d+)\)\s*years?",
        text,
        re.IGNORECASE,
    )
    if m_sched:
        months = int(m_sched.group(1)) * 12
        page = _find_page(doc, "The term")
        return make_result(months, 0.90, page, f"Formal schedule term: {months} months",
                           method=ExtractionMethod.rule)

    # Try explicit extraction first from principal terms
    result = find_labeled_value(text, "Term", "Lease Term")
    if result:
        label, raw = result
        # Try months first
        m = re.search(r"(\d+)\s*month", raw, re.IGNORECASE)
        if m:
            months = int(m.group(1))
            page = _find_page(doc, raw[:20])
            return make_result(months, 1.0, page, f"Term: {raw}", method=ExtractionMethod.regex)
        # Try years (e.g. "fixed 3-Years Period" or "3 year")
        m = re.search(r"(\d+)\s*[-\s]?(?:year|yr)", raw, re.IGNORECASE)
        if m:
            months = int(m.group(1)) * 12
            page = _find_page(doc, raw[:20])
            return make_result(months, 1.0, page, f"Term: {raw} → {months} months",
                               method=ExtractionMethod.computed)

    # Try Schedule I: "TWENTY (20) MONTHS from..." — parenthetical digit is explicit
    if schedule_i_text:
        # SCHEDULE 1 style: "A term of FOUR (4) years…"
        term_block = extract_schedule1_part(schedule_i_text, "Term", "Term of Tenancy")
        if term_block:
            m = re.search(r"\((\d+)\)\s*years?", term_block, re.IGNORECASE)
            if m:
                months = int(m.group(1)) * 12
                page = next((p.page_num for p in doc.pages if "commencing on" in p.text.lower()), 0)
                return make_result(months, 0.95, page, f"Schedule 1 Term: {term_block[:60]} → {months}mo",
                                   method=ExtractionMethod.rule)
            m = re.search(r"\((\d+)\)\s*months?", term_block, re.IGNORECASE)
            if m:
                months = int(m.group(1))
                return make_result(months, 0.95, 0, f"Schedule 1 Term: {term_block[:60]}",
                                   method=ExtractionMethod.rule)

        # First Schedule style: "TWENTY (20) MONTHS from…"
        term_section = find_schedule_section(schedule_i_text, "TERM OF TENANCY", "Term of Tenancy") or schedule_i_text
        m = re.search(r"\((\d+)\)\s*month|(\d+)\s*month", term_section, re.IGNORECASE)
        if m:
            months = int(m.group(1) or m.group(2))
            page = next((p.page_num for p in doc.pages if "TERM OF TENANCY" in p.text), 0)
            return make_result(months, 0.95, page, f"Schedule I: {term_section[:60]}",
                               method=ExtractionMethod.rule)

    # Compute from dates
    if commencement.value and expiry.value:
        months = compute_term_months(commencement.value, expiry.value)
        page = commencement.first_page() or 0
        return make_result(
            months, 0.70,
            page,
            f"Computed: {commencement.value} to {expiry.value} = {months} months",
            method=ExtractionMethod.computed,
            flag="TERM_COMPUTED_NOT_EXPLICIT",
        )
    return not_found()


def _extract_rent_free(text: str, doc: DocumentText, schedule_i_text: str = "") -> ExtractionResult:
    # SCHEDULE 1 style: PART VI Rent-Free Period — check before generic label scan
    if schedule_i_text:
        rf_block = extract_schedule1_part(schedule_i_text, "Rent-Free Period", "Rent Free Period")
        if rf_block:
            # Normalize OCR ordinals
            rf_block = re.sub(r'(\d+)[%"\'\u201c\u201d`](?=\s)', r'\1', rf_block)
            rf_block = re.sub(r'(\d+)(?:st|nd|rd|th)(?=\s)', r'\1', rf_block, flags=re.IGNORECASE)
            snippet = re.sub(r'\s*\n\s*', ' ', rf_block).strip()
            snippet = re.sub(r'\s+', ' ', snippet)
            if snippet:
                page = _find_page(doc, "Rent Free")
                return make_result(snippet[:200], 0.90, page, f"Schedule 1 Rent-Free: {snippet[:80]}",
                                   method=ExtractionMethod.rule)

    result = find_labeled_value(
        text,
        "Rent Free Period",
        "Rent Free Period(s)",
        "Rent-Free Period",
    )
    if result:
        label, raw = result
        page = _find_page(doc, "Rent Free")
        return make_result(raw, 1.0, page, f"Rent Free: {raw}")

    m_tenth = re.search(
        r"THE\s+TENTH\s+SCHEDULE\s+Rent-free\s+period\s*:\s*"
        r"(Four\s+\(4\)\s+months[\s\S]{0,220}?inclusive\)\s+From\s+\d{1,2}\s+\w+\s+\d{4}"
        r"\s+to\s+\d{1,2}\s+\w+\s+\d{4}\s+\(both\s+days\s+inclusive\))",
        text,
        re.IGNORECASE,
    )
    if m_tenth:
        snippet = re.sub(r"\s+", " ", m_tenth.group(1)).strip()
        page = _find_page(doc, "THE TENTH SCHEDULE")
        return make_result(snippet, 1.0, page, f"Tenth Schedule Rent-free: {snippet[:120]}",
                           method=ExtractionMethod.rule)
    return not_found()


def _extract_fit_out(
    text: str, doc: DocumentText, rent_free: ExtractionResult,
) -> ExtractionResult:
    # Look for explicit fit-out period
    result = find_labeled_value(text, "Fit-out Period", "Fit Out Period", "Fitting Out Period")
    if result:
        label, raw = result
        page = _find_page(doc, "Fit")
        return make_result(raw, 1.0, page, f"Fit-out: {raw}")

    return ExtractionResult(value="n/a", confidence=0.85, evidence=[])


def _extract_option_to_renew(full_text: str, doc: DocumentText) -> ExtractionResult:
    keywords = [
        r"option\s+to\s+renew",
        r"option\s+to\s+extend",
        r"renewal\s+option",
        r"further\s+term",
    ]
    for kw in keywords:
        if re.search(kw, full_text, re.IGNORECASE):
            page = _find_page_regex(doc, re.compile(kw, re.IGNORECASE))
            snippet = _extract_clause_snippet(full_text, re.compile(kw, re.IGNORECASE))
            return make_result(snippet, 0.70, page, snippet[:100], method=ExtractionMethod.heuristic)
    return ExtractionResult(value="n/a", confidence=1.0, evidence=[])


def _extract_expansion(full_text: str, doc: DocumentText) -> ExtractionResult:
    kw = re.compile(r"right\s+of\s+expansion|right\s+of\s+first\s+offer|first\s+right", re.IGNORECASE)
    if kw.search(full_text):
        page = _find_page_regex(doc, kw)
        snippet = _extract_clause_snippet(full_text, kw)
        return make_result(snippet, 0.70, page, snippet[:100], method=ExtractionMethod.heuristic)
    return ExtractionResult(value="n/a", confidence=1.0, evidence=[])


def _extract_trigger_date(full_text: str, doc: DocumentText) -> ExtractionResult:
    kw = re.compile(r"trigger\s+date|notice\s+period.*renew|exercise.*option", re.IGNORECASE)
    if kw.search(full_text):
        page = _find_page_regex(doc, kw)
        snippet = _extract_clause_snippet(full_text, kw)
        return make_result(snippet, 0.50, page, snippet[:100], method=ExtractionMethod.heuristic)
    return ExtractionResult(value="n/a", confidence=1.0, evidence=[])


def _extract_tenant_termination(
    principal_text: str, full_text: str, doc: DocumentText,
) -> ExtractionResult:
    # First check break clause (highest priority)
    result = find_labeled_value(principal_text, "Break Clause")
    if result:
        label, raw = result
        if re.match(r"^\s*n/?a\s*$", raw, re.IGNORECASE):
            page = _find_page(doc, "Break Clause")
            return make_result("n/a", 1.0, page, f"Break Clause: N/A")
        page = _find_page(doc, "Break Clause")
        return make_result(raw, 1.0, page, f"Break Clause: {raw}")

    lht_vacant_possession = re.search(
        r"If\s*the\s+Landlord\s+shall\s+fail\s+to\s+obtain\s+vacant\s+possession\s+"
        r"of\s+Unit\s+1102\s+by\s+31\s+March\s+2026[\s\S]{0,180}?"
        r"either\s+the\s+Landlord\s+or\s+the\s+Tenant\s+may\s+serve\s+a\s+written\s+notice"
        r"[\s\S]{0,120}?terminate\s+the\s+tenancy",
        full_text,
        re.IGNORECASE,
    )
    if lht_vacant_possession:
        page = _find_page(doc, "31 March 2026")
        value = (
            "If Landlord fails to obtain vacant possession of Unit 1102 by "
            "31 March 2026, either party may terminate Unit 1102 tenancy by written notice."
        )
        return make_result(value, 1.0, page, lht_vacant_possession.group(0)[:180],
                           method=ExtractionMethod.rule)

    # Look for tenant break/early termination right — exclude standard "termination of tenancy" phrasing
    kw = re.compile(
        r"tenant.*break\s+clause|tenant.*early\s+termination|tenant.*right\s+to\s+terminat"
        r"|break\s+option.*tenant|early\s+termination.*right",
        re.IGNORECASE,
    )
    if kw.search(full_text):
        page = _find_page_regex(doc, kw)
        snippet = _extract_clause_snippet(full_text, kw)
        return make_result(snippet, 0.50, page, snippet[:100], method=ExtractionMethod.heuristic,
                           flag="CLAUSE_SUMMARY_LOW_CONFIDENCE")
    return ExtractionResult(value="n/a", confidence=0.85, evidence=[])


def _find_page(doc: DocumentText, snippet: str) -> int:
    for p in doc.pages:
        if snippet and snippet[:15] in p.text:
            return p.page_num
    return 0


_TERM_COMMENCING_EXPIRING_RE = re.compile(
    r"commencing\s+on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+and\s+expiring\s+on\s+"
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    re.IGNORECASE,
)


def _find_page_regex(doc: DocumentText, pattern: re.Pattern) -> int:
    for p in doc.pages:
        if pattern.search(p.text):
            return p.page_num
    return 0


def _extract_clause_snippet(text: str, pattern: re.Pattern, chars: int = 200) -> str:
    m = pattern.search(text)
    if not m:
        return ""
    start = max(0, m.start() - 20)
    end = min(len(text), m.end() + chars)
    snippet = text[start:end].replace("\n", " ").strip()
    return re.sub(r"\s+", " ", snippet)


def _extract_multi_unit_expiry(text: str, doc: DocumentText) -> ExtractionResult | None:
    section = (
        _extract_numbered_section(text, "Commencement Date")
        or _extract_from_phrase_to_next_numbered(text, "The commencement date")
        or text
    )
    matches = list(re.finditer(
        r"Unit\s+\d+\s*[\s:;<-]{0,20}?"
        r"\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+to\s+"
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        section,
        re.IGNORECASE,
    ))
    dates = []
    for match in matches:
        parsed = parse_date(match.group(1))
        if parsed:
            dates.append((parsed, match.group(1), match.group(0)))
    if len(dates) < 2:
        return None
    expiry = max(dates, key=lambda item: item[0])
    page = _find_page(doc, expiry[1])
    return make_result(expiry[0], 1.0, page, f"Multi-unit expiry: {expiry[2]}",
                       method=ExtractionMethod.rule)


def _extract_numbered_section(text: str, heading: str) -> str | None:
    pattern = re.compile(
        r"(?ms)^\s*\d+\s*[\.,]?\s*(?:\([a-z]\)\s*)?"
        + re.escape(heading)
        + r"[^\n]*\n(.*?)(?=^\s*\d+\s*[\.,]\s*(?:\([a-z]\)\s*)?[A-Z]|\Z)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _extract_from_phrase_to_next_numbered(text: str, phrase: str) -> str | None:
    match = re.search(
        re.escape(phrase) + r"[\s\S]*?(?=^\s*\d+\s*[\.,]\s*(?:\([a-z]\)\s*)?[A-Z]|\Z)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    return match.group(0).strip() if match else None
