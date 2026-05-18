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
    t.rent_free_period_text = _extract_rent_free(text, doc, schedule_i_text)
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

    # Fallback: signature/execution block heuristics.
    # Only attempt when there's an execution cue; then extract the first date
    # appearing near that cue. This avoids accidentally picking up commencement/expiry dates.
    from ..normalizers.dates import find_dates

    execution_cue = re.compile(
        r"\b(in\s+witness\s+whereof|executed|execution|signed\s+sealed|common\s+seal|sealed)\b",
        re.IGNORECASE,
    )
    dated_cue = re.compile(r"\bdated\b", re.IGNORECASE)
    # Search the last pages first (signature blocks tend to be near the end)
    pages = list(doc.pages)
    scan_pages = list(reversed(pages[-10:])) + pages[:3]
    for p in scan_pages:
        t = p.text
        cue_m = execution_cue.search(t)
        if not cue_m:
            continue
        window = t[cue_m.start(): cue_m.start() + 600]
        dates = find_dates(window)
        if dates:
            d, raw = dates[0]
            quote = window[:200].replace("\n", " ").strip()
            return make_result(d, 0.75, p.page_num, f"{cue_m.group(0)} … {raw}",
                               method=ExtractionMethod.heuristic,
                               flag="SIGNING_DATE_HEURISTIC")

    # Secondary fallback: "dated" often appears in the opening definition line
    # ("this Lease is made/dated ..."). Restrict to early pages.
    for p in pages[:5]:
        t = p.text
        m = dated_cue.search(t)
        if not m:
            continue
        window = t[m.start(): m.start() + 300]
        dates = find_dates(window)
        if dates:
            d, raw = dates[0]
            return make_result(
                d,
                0.70,
                p.page_num,
                f"dated … {raw}",
                method=ExtractionMethod.heuristic,
                flag="SIGNING_DATE_HEURISTIC",
            )
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
    labeled = find_labeled_value(full_text, "Option to Renew", "Renewal Option")
    if labeled:
        label, raw = labeled
        page = _find_page(doc, label)
        if _is_na(raw):
            return make_result("n/a", 1.0, page, f"{label}: {raw}", method=ExtractionMethod.regex)
        if not _looks_like_negated_option(raw):
            return make_result(_clean_clause_text(raw), 0.85, page, f"{label}: {raw[:100]}")

    return ExtractionResult(value="n/a", confidence=1.0, evidence=[])


def _extract_expansion(full_text: str, doc: DocumentText) -> ExtractionResult:
    labeled = find_labeled_value(full_text, "Right of Expansion")
    if labeled:
        label, raw = labeled
        page = _find_page(doc, label)
        if _is_na(raw):
            return make_result("n/a", 1.0, page, f"{label}: {raw}", method=ExtractionMethod.regex)
        if not _looks_like_negated_option(raw):
            return make_result(_clean_clause_text(raw), 0.85, page, f"{label}: {raw[:100]}")

    return ExtractionResult(value="n/a", confidence=1.0, evidence=[])


def _extract_trigger_date(full_text: str, doc: DocumentText) -> ExtractionResult:
    labeled = find_labeled_value(full_text, "Trigger Date")
    if labeled:
        label, raw = labeled
        page = _find_page(doc, label)
        if _is_na(raw):
            return make_result("n/a", 1.0, page, f"{label}: {raw}", method=ExtractionMethod.regex)
        return make_result(_clean_clause_text(raw), 0.85, page, f"{label}: {raw[:100]}")
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


def _is_na(text: str) -> bool:
    return bool(re.match(r"^\s*n[./]?\s*a\s*$", str(text or ""), re.IGNORECASE))


def _clean_clause_text(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit].rstrip()


def _looks_like_negated_option(text: str) -> bool:
    lowered = re.sub(r"\s+", " ", str(text or "").lower())
    if re.search(r"\b(?:no|not|without)\s+(?:an?\s+)?(?:option|right)", lowered):
        return True
    if "extinguish and determine" in lowered:
        return True
    if "whether the same shall have been exercised" in lowered:
        return True
    if re.search(r"\b(?:notice|termination|terminate|determination)\b.{0,120}\boption\b", lowered):
        return True
    return False


def _extract_clause_snippet(text: str, pattern: re.Pattern, chars: int = 200) -> str:
    m = pattern.search(text)
    if not m:
        return ""
    start = max(0, m.start() - 20)
    end = min(len(text), m.end() + chars)
    snippet = text[start:end].replace("\n", " ").strip()
    return re.sub(r"\s+", " ", snippet)
