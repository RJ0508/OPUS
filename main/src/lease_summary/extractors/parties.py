"""Extract party information: landlord, tenant, solicitor."""
from __future__ import annotations

import re

from ..models import ExtractionResult, Parties
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument
from .base import (
    extract_schedule1_part,
    find_labeled_value,
    find_schedule_section,
    make_result,
    not_found,
    ExtractionMethod,
)


_BAD_GENERIC_PARTY_FRAGMENTS = (
    "offer to lease",
    "dear sirs",
    "hereby offer",
    "premises described",
    "subject to the following",
    "terms and conditions",
)


def extract_parties(doc: DocumentText, split: SplitDocument) -> Parties:
    p = Parties()
    text = split.principal_terms
    # Schedule I contains party info in formal tenancy agreements (e.g. Part IA/IB format)
    schedule_text = split.schedule_i or ""
    pages = split.principal_terms_pages

    p.landlord_name = _extract_landlord_name(text, doc, pages[0], schedule_text)
    p.landlord_registered_address = _extract_landlord_address(text, doc, pages[0], schedule_text)
    p.landlord_agent = _extract_landlord_agent(doc, pages[0], schedule_text)
    p.landlord_solicitor = _extract_landlord_solicitor(text, doc)
    p.tenant_name = _extract_tenant_name(text, doc, pages[0], schedule_text)
    p.tenant_registered_address = _extract_tenant_address(text, doc, pages[0], schedule_text)

    return p


def _extract_landlord_name(text: str, doc: DocumentText, page: int,
                           schedule_text: str = "") -> ExtractionResult:
    # ── Highest priority: SCHEDULE 1 / The Schedule (when populated) ──────────────
    # These appear before the generic label scan to avoid false matches on
    # "Landlord" appearing in the body of formal full-lease documents.
    if schedule_text:
        landlord_block = extract_schedule1_part(schedule_text, "Landlord", "The Landlord")
        if landlord_block:
            value = re.split(r'\s+whose\s+(?:registered\s+office|correspondence\s+address)',
                             landlord_block, flags=re.IGNORECASE)[0]
            value = re.sub(r'\s*\n\s*', ' ', value).strip()
            value = re.sub(r"\s+[\u4e00-\u9fff\uff00-\uffef（）【】「」『』]+.*$", "", value).strip()
            value = re.sub(r'\s*\(\d+\)\s*$', '', value).strip()
            if len(value) > 5:
                value = _normalize_company_name(value)
                page = next((p.page_num for p in doc.pages if value[:10] in p.text), page)
                return make_result(value, 0.90, page, f"Schedule 1 Landlord: {value[:60]}",
                                   method=ExtractionMethod.rule)

    # "Name of Landlord" is specific enough to use even in formal full-lease docs
    result = find_labeled_value(text, "Name of Landlord")
    if result:
        label, value = result
        value = re.sub(r"\s+[\u4e00-\u9fff\uff00-\uffef（）【】「」『』]+.*$", "", value).strip()
        if len(value) > 5 and not re.match(r'^[-/\s.]+$', value):
            value = _normalize_company_name(value)
            for p in doc.pages:
                if "Name of Landlord" in p.text or (value and value[:10] in p.text):
                    page = p.page_num
                    break
            return make_result(value, 1.0, page, f"Name of Landlord: {value}")

    # Generic "Landlord" / "Lessor" labels only for offer-to-lease docs (no formal schedule)
    if not schedule_text:
        result = find_labeled_value(text, "Landlord", "Lessor")
        if result:
            label, value = result
            value = re.sub(r"\s+[\u4e00-\u9fff\uff00-\uffef（）【】「」『』]+.*$", "", value).strip()
            if _looks_like_generic_party_name(value):
                value = _normalize_company_name(value)
                for p in doc.pages:
                    if value and value[:10] in p.text:
                        page = p.page_num
                        break
                return make_result(value, 1.0, page, f"Landlord: {value}")

    # Prose pattern: "signed between LANDLORD and TENANT"
    prose_pat = re.compile(
        r"signed\s+between\s+(.+?)\s+and\s+(?=[A-Z])",
        re.IGNORECASE | re.DOTALL,
    )
    for p in doc.pages[:5]:
        m = prose_pat.search(p.text)
        if m:
            value = m.group(1).strip().rstrip(",")
            value = re.sub(r"\s+[\u4e00-\u9fff\uff00-\uffef（）【】「」『』]+.*$", "", value).strip()
            if len(value) > 5:
                value = _normalize_company_name(value)
                return make_result(value, 0.85, p.page_num, f"Signed between: {value}",
                                   method=ExtractionMethod.rule)

    # Preamble "BETWEEN" clause: "COMPANY NAME…("Landlord")" (Hang Seng / Deacons style)
    # Note: docx uses ASCII " while scanned docs may use smart quotes — include all variants
    between_pat = re.compile(
        r"BETWEEN\s*:?-?\s*\n\s*([A-Z][A-Z\s,&.()\-]+(?:LIMITED|LTD\.?|COMPANY|CORPORATION))"
        r"(?:[\s\S]{0,600}?)\([\"'\u201c]Landlord[\"'\u201d\)]",
        re.IGNORECASE,
    )
    m_between = between_pat.search(text)
    if m_between:
        value = m_between.group(1).strip()
        value = re.sub(r"\s+[\u4e00-\u9fff\uff00-\uffef（）【】「」『』]+.*$", "", value).strip()
        if len(value) > 5:
            value = _normalize_company_name(value)
            page = next((p.page_num for p in doc.pages if value[:10] in p.text), page)
            return make_result(value, 0.85, page, f"Preamble Landlord: {value[:60]}",
                               method=ExtractionMethod.rule)

    # Formal tenancy agreement: "THE LANDLORD" section in First Schedule (no colon separator)
    if schedule_text:
        value = _extract_schedule_party_block(
            schedule_text,
            start_pattern=r"PART\s+IA\s+THE\s+LANDLORD\.?",
            end_pattern=r"PART\s+IB\s+THE\s+TENANT|PART\s+II\s+THE\s+PREMISES",
        ) or find_schedule_section(schedule_text, "THE LANDLORD")
        if value:
            # "CENTRAL PLAZA MANAGEMENT COMPANY LIMITED... agent for the Landlords X and Y."
            # Prefer the managing agent (first-named entity) over the beneficial owners
            agent_m = re.search(
                r"agent\s+for\s+the\s+landlords?",
                value, re.IGNORECASE,
            )
            if agent_m:
                # Use everything before "agent for" as the primary landlord (managing company)
                value = value[:agent_m.start()].strip()
                # Trim registered office / address that follows the company name
                value = re.split(r"\s+(?:whose\s+registered|of\s+which\s+the|having\s+its)",
                                 value, flags=re.IGNORECASE)[0]
                value = value.strip().rstrip(",").rstrip(".")
                value = re.sub(r"\s+(?:as|being|acting)\s*$", "", value, flags=re.IGNORECASE).strip()
            else:
                value = re.split(r"\s+(?:whose\s+registered|of\s+the\s+one\s+part)", value)[0].strip()
            # Collapse line breaks within company names
            value = re.sub(r'\s*\n\s*', ' ', value).strip()
            # Remove OCR-garbled parentheticals (contain symbols like {, @, #)
            value = re.sub(r'\s*\([^)]*[{@#%&^|]+[^)]*\)', '', value).strip()
            value = re.sub(r"\s*\([^)]{0,40}\)\s*$", "", value).strip()
            value = re.sub(r"\s+[\u4e00-\u9fff\uff00-\uffef（）【】「」『』\{\[\]]+.*$", "", value).strip()
            if len(value) > 5:
                value = _normalize_company_name(value)
                page = next((p.page_num for p in doc.pages if "THE LANDLORD" in p.text), page)
                return make_result(value, 0.85, page, f"Schedule Part IA: {value[:60]}",
                                   method=ExtractionMethod.rule)

    value = _extract_numbered_schedule_party_name(text, "FIRST", "Landlord", "SECOND")
    if value:
        page = next((p.page_num for p in doc.pages if "THE FIRST SCHEDULE" in p.text), page)
        return make_result(value, 0.90, page, f"First Schedule Landlord: {value[:60]}",
                           method=ExtractionMethod.rule)
    return not_found()


def _extract_landlord_address(
    text: str,
    doc: DocumentText,
    page: int,
    schedule_text: str = "",
) -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Registered office/principal place of business in Hong Kong of the Landlord",
        "Registered office/principal place of business",
        address_mode=True,
    )
    if result:
        label, value = result
        value = _trim_party_capture(value)
        # Find page
        for p in doc.pages:
            if "Landlord" in p.text and ("Registered" in p.text or "principal place" in p.text):
                page = p.page_num
                break
        return make_result(value, 0.85, page, f"Landlord address: {value[:60]}")

    # Preamble prose: "COMPANY… whose correspondence/registered address is ADDRESS ("Landlord")"
    # Hang Seng style: "YAN NIN DEVELOPMENT COMPANY LIMITED… whose correspondence address is 9/F… ("Landlord")"
    # Non-greedy to find the FIRST "whose…" after BETWEEN (landlord's, not tenant's).
    # [^)]* handles "(hereinafter called "Landlord")" vs bare ("Landlord").
    # [\"'\u201d]\s*\) requires closing-quote then ")" so "Tenant's" apostrophe is not a false match.
    landlord_addr_pat = re.compile(
        r"BETWEEN\s*:?-?\s*\n"
        r"(?:[\s\S]+?)"
        r"whose\s+(?:registered\s+office|correspondence\s+address)\s+is\s+(?:situated?\s+)?(?:at\s+)?"
        r"((?:(?!\([^)]*[\"'\u201c](?:Tenant|Landlord)[\"'\u201d]\s*\)).)+)"
        r"(?=\s*\([^)]*[\"'\u201c]Landlord[\"'\u201d]\s*\))",
        re.IGNORECASE | re.DOTALL,
    )
    m_la = landlord_addr_pat.search(text)
    if m_la:
        raw_addr = re.sub(r'\s*\n\s*', ' ', m_la.group(1)).strip()
        value = _normalize_address(raw_addr)
        if len(value) > 10:
            page = next((p.page_num for p in doc.pages if "Landlord" in p.text and
                         ("address" in p.text.lower() or "registered" in p.text.lower())), page)
            return make_result(value, 0.85, page, f"Preamble landlord address: {value[:60]}",
                               method=ExtractionMethod.rule)

    if schedule_text:
        landlord_block = extract_schedule1_part(schedule_text, "Landlord", "The Landlord")
        if landlord_block:
            collapsed = _collapse_schedule_text(landlord_block)
            addr_m = re.search(
                r"whose\s+(?:registered\s+office|correspondence\s+address)\s+is\s+"
                r"(?:situate|situated)\s+at\s+(.+?)(?=\([\"'\u201c]|\.\s*$|\Z)",
                collapsed, re.IGNORECASE,
            )
            if addr_m:
                value = _normalize_address(addr_m.group(1))
                page = next((p.page_num for p in doc.pages if value[:10] in p.text), page)
                return make_result(value, 0.90, page, f"Schedule 1 landlord address: {value[:60]}",
                                   method=ExtractionMethod.rule)

        block = _extract_schedule_party_block(
            schedule_text,
            start_pattern=r"PART\s+IA\s+THE\s+LANDLORD\.?",
            end_pattern=r"PART\s+IB\s+THE\s+TENANT|PART\s+II\s+THE\s+PREMISES",
        ) or find_schedule_section(schedule_text, "THE LANDLORD")
        if block:
            match = re.search(
                r"whose\s+registered\s+office\s+is\s+situate\s+at\s+(.+?)(?=\s+agent\s+for\s+the\s+landlords?\b|\.?$)",
                _collapse_schedule_text(block),
                re.IGNORECASE,
            )
            if match:
                value = _normalize_address(match.group(1))
                page = next((p.page_num for p in doc.pages if "THE LANDLORD" in p.text), page)
                return make_result(
                    value,
                    0.85,
                    page,
                    f"Schedule landlord address: {value[:60]}",
                    method=ExtractionMethod.rule,
                )

    value = _extract_numbered_schedule_party_address(text, "FIRST", "Landlord", "SECOND")
    if value:
        page = next((p.page_num for p in doc.pages if "THE FIRST SCHEDULE" in p.text), page)
        return make_result(value, 0.90, page, f"First Schedule landlord address: {value[:60]}",
                           method=ExtractionMethod.rule)
    return not_found()


def _extract_landlord_agent(doc: DocumentText, page: int, schedule_text: str = "") -> ExtractionResult:
    if not schedule_text:
        return not_found()
    block = _extract_schedule_party_block(
        schedule_text,
        start_pattern=r"PART\s+IA\s+THE\s+LANDLORD\.?",
        end_pattern=r"PART\s+IB\s+THE\s+TENANT|PART\s+II\s+THE\s+PREMISES",
    ) or find_schedule_section(schedule_text, "THE LANDLORD")
    if not block:
        return not_found()
    collapsed = _collapse_schedule_text(block)
    match = re.search(
        r"(agent\s+for\s+the\s+landlords?\s+.+?)(?=\.?$)",
        collapsed,
        re.IGNORECASE,
    )
    if not match:
        return not_found()
    value = re.sub(r"\s+", " ", match.group(1)).strip().rstrip(".")
    value = re.sub(r"\s*\([^)]*[{@#%\[\]/\\]+[^)]*\)", "", value).strip()
    page = next((p.page_num for p in doc.pages if "THE LANDLORD" in p.text), page)
    return make_result(value, 0.85, page, f"Schedule landlord agent: {value[:80]}",
                       method=ExtractionMethod.rule)


def _extract_landlord_solicitor(text: str, doc: DocumentText) -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Landlord's solicitors",
        "Landlord's Solicitors",
        "Solicitors",
    )
    if result:
        label, value = result
        # The captured value may include sub-labels like "Address :", "Contact Person :"
        # Keep only the firm name (text before the first sub-label)
        value = re.split(r"\s+(?:Address|Contact Person|Contact Tel|Tel)\s*:", value)[0].strip()
        page = 0
        for p in doc.pages:
            if "solicitor" in p.text.lower():
                page = p.page_num
                break
        return make_result(value, 1.0, page, f"Solicitor: {value[:60]}")
    return not_found()


def _extract_tenant_name(text: str, doc: DocumentText, page: int,
                         schedule_text: str = "") -> ExtractionResult:
    # ── Highest priority: SCHEDULE 1 / The Schedule ───────────────────────────────
    if schedule_text:
        tenant_block = extract_schedule1_part(schedule_text, "Tenant", "The Tenant")
        if tenant_block:
            value = re.split(r'\s+whose\s+(?:registered\s+office|correspondence\s+address)',
                             tenant_block, flags=re.IGNORECASE)[0]
            value = re.sub(r'\s*\n\s*', ' ', value).strip()
            value = re.sub(r"\s+[\u4e00-\u9fff\uff00-\uffef（）【】「」『』]+.*$", "", value).strip()
            value = re.sub(r'\s*\((?:BR|Company|Business\s+Registration)[^)]*\)\s*$', '', value).strip()
            if len(value) > 5:
                value = _normalize_company_name(value)
                page = next((p.page_num for p in doc.pages if value[:10] in p.text), page)
                return make_result(value, 0.90, page, f"Schedule 1 Tenant: {value[:60]}",
                                   method=ExtractionMethod.rule)

    # Specific labels (safe to use in any doc type)
    result = find_labeled_value(text, "Name of Tenant", "Tenant's Name", "Tenant Name")
    if result:
        label, value = result
        value = value.split("Certificate")[0].split("Business Registration")[0].strip()
        if len(value) > 5 and not re.match(r'^[-/\s.]+$', value):
            value = _normalize_company_name(value)
            for p in doc.pages:
                if "Name of Tenant" in p.text or (value and value[:10] in p.text):
                    page = p.page_num
                    break
            return make_result(value, 1.0, page, f"Name of Tenant: {value}")

    # Generic "Tenant" label only for offer-to-lease docs
    if not schedule_text:
        result = find_labeled_value(text, "Tenant")
        if result:
            label, value = result
            value = value.split("Certificate")[0].split("Business Registration")[0].strip()
            if _looks_like_generic_party_name(value):
                value = _normalize_company_name(value)
                for p in doc.pages:
                    if value and value[:10] in p.text:
                        page = p.page_num
                        break
                return make_result(value, 1.0, page, f"Tenant: {value}")

    # Preamble "("Tenant")" pattern (Hang Seng / Deacons style)
    # [^)]* handles "(hereinafter called "Landlord")" vs bare ("Landlord").
    # [\s\S]{0,150}? between marker and "AND (2)" handles "of the one part" filler.
    tenant_preamble_pat = re.compile(
        r"\([^)]*[\"'\u201c]Landlord[\"'\u201d]\s*\)"
        r"(?:[\s\S]{0,150}?)and\s+\(\d+\)\s*"
        r"([A-Z][A-Z\s,&.()\-]+(?:LIMITED|LTD\.?|COMPANY|CORPORATION))"
        r"(?:[\s\S]{0,600}?)\([^)]*[\"'\u201c]Tenant[\"'\u201d]\s*\)",
        re.IGNORECASE,
    )
    # Restrict to early pages — the BETWEEN preamble appears in pages 1–5;
    # searching all 48 pages risks matching a later "("Tenant")" occurrence.
    early_text = "\n".join(p.text for p in doc.pages[:6])
    m_tenant = tenant_preamble_pat.search(early_text)
    if m_tenant:
        value = m_tenant.group(1).strip()
        value = re.sub(r"\s+[\u4e00-\u9fff\uff00-\uffef（）【】「」『』]+.*$", "", value).strip()
        if len(value) > 5:
            value = _normalize_company_name(value)
            page = next((p.page_num for p in doc.pages if value[:10] in p.text), page)
            return make_result(value, 0.85, page, f"Preamble Tenant: {value[:60]}",
                               method=ExtractionMethod.rule)

    # Formal tenancy agreement: "THE TENANT" section in First Schedule (no colon separator)
    if schedule_text:
        value = _extract_schedule_party_block(
            schedule_text,
            start_pattern=r"PART\s+IB\s+THE\s+TENANT\.?",
            end_pattern=r"PART\s+II\s+THE\s+PREMISES",
        ) or find_schedule_section(schedule_text, "THE TENANT")
        if value:
            # "KLDISCOVERY ONTRACK (HK) LIMITED (BR No. 38703143) whose registered office..."
            value = re.split(r"\s+(?:whose\s+registered|of\s+the\s+other\s+part)", value)[0].strip()
            value = re.sub(r"\s*\((?:BR|Company|Business Registration)[^)]*\)\s*$", "", value).strip()
            if len(value) > 5:
                value = _normalize_company_name(value)
                page = next((p.page_num for p in doc.pages if "THE TENANT" in p.text), page)
                return make_result(value, 0.85, page, f"Schedule Part IB: {value[:60]}",
                                   method=ExtractionMethod.rule)

    value = _extract_numbered_schedule_party_name(text, "SECOND", "Tenant", "THIRD")
    if value:
        page = next((p.page_num for p in doc.pages if "THE SECOND SCHEDULE" in p.text), page)
        return make_result(value, 0.90, page, f"Second Schedule Tenant: {value[:60]}",
                           method=ExtractionMethod.rule)
    return not_found()


def _extract_tenant_address(
    text: str,
    doc: DocumentText,
    page: int,
    schedule_text: str = "",
) -> ExtractionResult:
    # Look for registered office / principal place of business of Tenant
    result = find_labeled_value(
        text,
        "Registered office/principal place of business in Hong Kong/address of the Tenant",
        "Registered office/principal place of business in Hong Kong",
        address_mode=True,
    )
    if result:
        label, value = result
        value = _trim_party_capture(value)
        # Clean up sub-items that may be captured
        value = re.sub(r"\(v\).*", "", value, flags=re.DOTALL).strip()
        value = re.sub(r"\(iv\).*", "", value, flags=re.DOTALL).strip()
        for p in doc.pages:
            if "Tenant" in p.text and "Registered" in p.text:
                page = p.page_num
                break
        return make_result(value, 0.85, page, f"Tenant address: {value[:60]}")

    # Preamble prose: "COMPANY… whose registered office is situated at ADDRESS ("Tenant")"
    # [^)]* handles "(hereinafter called "Tenant")" vs bare ("Tenant").
    # [\"'\u201d]\s*\) requires closing-quote then ")" so "Tenant's" apostrophe is not a false match.
    tenant_addr_pat = re.compile(
        r"whose\s+(?:registered\s+office|correspondence\s+address)\s+is\s+(?:situated?\s+)?at\s+"
        r"((?:(?!\([^)]*[\"'\u201c](?:Tenant|Landlord)[\"'\u201d]\s*\)).)+)"
        r"(?=\s*\([^)]*[\"'\u201c]Tenant[\"'\u201d]\s*\))",
        re.IGNORECASE | re.DOTALL,
    )
    m_ta = tenant_addr_pat.search(text)
    if m_ta:
        raw_addr = re.sub(r'\s*\n\s*', ' ', m_ta.group(1)).strip()
        value = _normalize_address(raw_addr)
        if len(value) > 10:
            page = next((p.page_num for p in doc.pages if "Tenant" in p.text and "registered" in p.text.lower()), page)
            return make_result(value, 0.85, page, f"Preamble tenant address: {value[:60]}",
                               method=ExtractionMethod.rule)

    if schedule_text:
        tenant_block = extract_schedule1_part(schedule_text, "Tenant", "The Tenant")
        if tenant_block:
            collapsed = _collapse_schedule_text(tenant_block)
            addr_m = re.search(
                r"whose\s+(?:registered\s+office|correspondence\s+address)\s+is\s+"
                r"(?:situate|situated)\s+at\s+(.+?)(?=\([\"'\u201c]|\.\s*$|\Z)",
                collapsed, re.IGNORECASE,
            )
            if addr_m:
                value = _normalize_address(addr_m.group(1))
                page = next((p.page_num for p in doc.pages if value[:10] in p.text), page)
                return make_result(value, 0.90, page, f"Schedule 1 tenant address: {value[:60]}",
                                   method=ExtractionMethod.rule)

        block = _extract_schedule_party_block(
            schedule_text,
            start_pattern=r"PART\s+IB\s+THE\s+TENANT\.?",
            end_pattern=r"PART\s+II\s+THE\s+PREMISES",
        ) or find_schedule_section(schedule_text, "THE TENANT")
        if block:
            match = re.search(
                r"whose\s+registered\s+office\s+is\s+situate\s+at\s+(.+?)"
                r"(?=\.?\s+(?:PART\s+(?:II|2)\b|THE\s+PREMISES\b)|\.?$|\Z)",
                _collapse_schedule_text(block),
                re.IGNORECASE,
            )
            if match:
                value = _normalize_address(_trim_party_capture(match.group(1)))
                page = next((p.page_num for p in doc.pages if "THE TENANT" in p.text), page)
                return make_result(
                    value,
                    0.85,
                    page,
                    f"Schedule tenant address: {value[:60]}",
                    method=ExtractionMethod.rule,
                )

    value = _extract_numbered_schedule_party_address(text, "SECOND", "Tenant", "THIRD")
    if value:
        page = next((p.page_num for p in doc.pages if "THE SECOND SCHEDULE" in p.text), page)
        return make_result(value, 0.90, page, f"Second Schedule tenant address: {value[:60]}",
                           method=ExtractionMethod.rule)
    return not_found()


def _extract_schedule_party_block(schedule_text: str, start_pattern: str, end_pattern: str) -> str | None:
    match = re.search(
        start_pattern + r"\s*(.*?)(?=" + end_pattern + r"|\Z)",
        schedule_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _collapse_schedule_text(text: str) -> str:
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_numbered_schedule_party_name(
    text: str, schedule_word: str, label: str, next_schedule_word: str,
) -> str | None:
    block = _extract_numbered_schedule_block(text, schedule_word, next_schedule_word)
    if not block:
        return None
    m = re.search(label + r"\s*:\s*(.+)", block, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    value = re.split(
        r"\s+a\s+company\b|\s+whose\b|\s+having\b|\s+\(BRN\b",
        _collapse_schedule_text(m.group(1)),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    value = _normalize_company_name(value)
    return value if len(value) > 5 else None


def _extract_numbered_schedule_party_address(
    text: str, schedule_word: str, label: str, next_schedule_word: str,
) -> str | None:
    block = _extract_numbered_schedule_block(text, schedule_word, next_schedule_word)
    if not block or not re.search(label, block, re.IGNORECASE):
        return None
    collapsed = _collapse_schedule_text(block)
    m = re.search(
        r"(?:registered\s+office\s+is\s+situate\s+at|place\s+of\s+business\s+in\s+Hong\s+Kong\s+at)\s+(.+?)(?=\.\s*$)",
        collapsed,
        re.IGNORECASE,
    )
    if not m:
        return None
    return _normalize_address(m.group(1))


def _extract_numbered_schedule_block(
    text: str, schedule_word: str, next_schedule_word: str,
) -> str | None:
    m = re.search(
        rf"(?m)^\s*THE\s+{schedule_word}\s+SCHEDULE\s+(.*?)(?=^\s*THE\s+{next_schedule_word}\s+SCHEDULE\b|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    return m.group(1).strip() if m else None


def _normalize_address(value: str) -> str:
    value = _trim_party_capture(value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = value.replace("No.18", "18").replace("No.30", "30")
    value = re.sub(r"on\s+(\d+)[^A-Za-z0-9]{0,4}\s*Floor", r"\1/F", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+,", ",", value)
    return value


def _normalize_company_name(value: str) -> str:
    value = _trim_party_capture(value)
    value = re.sub(r"\s+", " ", value).strip(" ,.")
    value = re.sub(r",\s+(Limited|Ltd\.?)\b", r" \1", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+\.", ".", value)
    return value.strip()


def _trim_party_capture(value: str) -> str:
    """Stop party/address captures before the next schedule section."""
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = re.split(
        r"\bPART\s+(?:I{1,3}|IV|V|1|2|3)\b|\bTHE\s+PREMISES\b|\bTERM\s+OF\s+TENANCY\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return value.strip(" ,.")


def _looks_like_generic_party_name(value: str) -> bool:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= 5 or len(value) > 120:
        return False
    if re.match(r'^[-/\s.]+$', value):
        return False
    lower = value.lower()
    if any(fragment in lower for fragment in _BAD_GENERIC_PARTY_FRAGMENTS):
        return False
    return True
