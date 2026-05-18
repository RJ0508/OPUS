"""Extract premises information: address, building, area."""
from __future__ import annotations

import re

from ..models import ExtractionResult, Premises
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument
from .base import extract_schedule1_part, find_labeled_value, find_schedule_section, make_result, not_found, ExtractionMethod


_BAD_PREMISES_FRAGMENTS = (
    "dear sirs",
    "hereby offer",
    "premises described",
    "subject to the following",
    "terms and conditions",
)


def extract_premises(doc: DocumentText, split: SplitDocument) -> Premises:
    p = Premises()
    text = split.principal_terms
    schedule_text = split.schedule_i or ""

    p.full_address = _extract_full_address(text, doc, schedule_text)
    p.building_name = _extract_building(text, doc, p.full_address.value, schedule_text)
    p.floor_suite = _extract_floor_suite(text, doc, p.full_address.value, schedule_text)
    p.rentable_area_sqft = _extract_area(text, split.full_text, doc)
    p.area_comment = _extract_area_comment(text, doc, p.rentable_area_sqft)

    return p


def _extract_full_address(text: str, doc: DocumentText, schedule_text: str = "") -> ExtractionResult:
    # ── Highest priority: SCHEDULE 1 / The Schedule (when populated) ──────────────
    if schedule_text:
        raw = extract_schedule1_part(schedule_text, "Premises", "The Premises")
        if raw:
            cleaned = _normalize_schedule1_premises(raw)
            if len(cleaned) > 10:
                page = next(
                    (p.page_num for p in doc.pages
                     if "Premises" in p.text and ("Floor" in p.text or "Level" in p.text or "Unit" in p.text)),
                    0,
                )
                return make_result(cleaned, 0.90, page, f"Schedule 1 Premises: {cleaned[:80]}",
                                   method=ExtractionMethod.rule)

    # Try labeled fields (ordered from most to least specific)
    result = find_labeled_value(
        text,
        "Premises and Address",
        "Address of Premises",
        "Premises",
    )
    if result:
        label, value = result
        # Remove floor plan / annotation notes that often trail the address
        value = re.sub(r"\s*\.?\s*As shown.*", "", value, flags=re.DOTALL | re.IGNORECASE).strip()
        value = re.sub(r"\s*Please\s+note\s+that.*", "", value, flags=re.DOTALL | re.IGNORECASE).strip()
        value = re.sub(r"\s*\(the\s+[\"'\u201c]?Premises[\"'\u201d]?\).*", "", value,
                       flags=re.DOTALL | re.IGNORECASE).strip()
        # Deduplicate "NN/F NN, Floor NN, ..." → keep only "NN/F NN, ..."
        value = re.sub(r",\s*Floor\s+\d{1,2}\b", "", value, flags=re.IGNORECASE).strip()
        if _looks_like_labeled_premises_address(value):
            page = 0
            for p in doc.pages:
                if value[:15] in p.text or (
                    "Premises" in p.text and ("Floor" in p.text or "/" in p.text)
                ):
                    page = p.page_num
                    break
            return make_result(value, 1.0, page, f"Premises: {value[:80]}")

    # Fallback: search Schedule I for "THE PREMISES" section (formal tenancy agreements, no colon)
    if schedule_text:
        value = find_schedule_section(schedule_text, "THE PREMISES")
        if value:
            # Collapse internal newlines first
            value = re.sub(r"\s*\n\s*", " ", value).strip()
            # Remove "(herein referred to as ...)" annotation in-place
            value = re.sub(r'\s*\(herein\s+referred\s+to[^)]*\)', '', value,
                           flags=re.IGNORECASE).strip()
            value = re.sub(r'\s*As shown (?:coloured|highlighted).*', '', value,
                           flags=re.DOTALL | re.IGNORECASE).strip()
            # Stop at the land registry "erected on..." clause
            value = re.sub(r'\s+erected\s+on\s+.*$', '', value,
                           flags=re.DOTALL | re.IGNORECASE).strip()
            # Normalize legal description: "ALL THAT OFFICE UNIT NO.X on the ORDINAL FLOOR
            # of the building known as NAME at No.N STREET, DISTRICT, CITY"
            # → "Suite/Unit X, N/F, Name, N Street, District, City"
            value = _normalize_legal_address(value)
            if len(value) > 10:
                page = next((p.page_num for p in doc.pages if "THE PREMISES" in p.text), 0)
                return make_result(value, 0.90, page, f"Schedule I Premises: {value[:80]}",
                                   method=ExtractionMethod.rule)

    # Fallback: find "Floor X, Building, Street, City" address pattern
    addr_pattern = re.compile(
        r"(\d{1,2}[/F]\s+\d{2,},?\s+Floor\s+\d{1,2}[^,]*,[^,]+,[^,]+,[^,]+Hong Kong)",
        re.IGNORECASE,
    )
    for p in doc.pages[:6]:
        m = addr_pattern.search(p.text)
        if m:
            return make_result(m.group(1).strip(), 0.85, p.page_num, m.group(1)[:80])

    return not_found("PREMISES_NOT_FOUND")


def _normalize_legal_address(value: str) -> str:
    """
    Convert HK formal tenancy legal description to clean address string.
    Input:  "ALL THAT OFFICE UNIT NO.1702 on the SEVENTEENTH FLOOR of the building
             known as CENTRAL PLAZA at No.18 Harbour Road, Wanchai, Hong Kong"
    Output: "Suite 1702, 17/F, Central Plaza, 18 Harbour Road, Wanchai, Hong Kong"
    """
    m = re.match(
        r"(?:ALL\s+THAT\s+)?(?:OFFICE\s+)?(?:UNIT|SHOP|FLAT|ROOM)\s+(?:NO\.?)?\s*(\w+)"
        r"\s+on\s+the\s+(\w+(?:-\w+)?)\s+FLOOR\s+of\s+the\s+building\s+known\s+as\s+"
        r"([^,\n]+?)\s+at\s+No\.?\s*(\d+)\s+(.+)",
        value, re.IGNORECASE,
    )
    if not m:
        return value
    unit_id = m.group(1)
    floor_word = m.group(2).lower()
    building = m.group(3).strip().title()
    street_num = m.group(4)
    remainder = m.group(5).strip()
    floor_num = _ORDINALS_TO_INT.get(floor_word)
    if not floor_num:
        return value
    return f"Suite {unit_id}, {floor_num}/F, {building}, {street_num} {remainder}"


def _extract_building(text: str, doc: DocumentText, premises_value: str | None,
                      schedule_text: str = "") -> ExtractionResult:
    result = find_labeled_value(text, "Building Name", "Name of Building")
    if result:
        label, value = result
        clean_value = re.sub(r"\s+", " ", value).strip()
        if _looks_like_building_name(clean_value):
            page = 0
            for p in doc.pages:
                if "Building" in p.text and clean_value and clean_value[:8] in p.text:
                    page = p.page_num
                    break
            return make_result(clean_value, 1.0, page, f"Building: {clean_value}")

    # SCHEDULE 1 / The Schedule: Part I - The Building (Deacons style)
    if schedule_text:
        building_block = extract_schedule1_part(schedule_text, "The Building", "Building")
        if building_block:
            value = re.sub(r'\s*\n\s*', ' ', building_block).strip()
            # Keep only first sentence (name of the building, not legal lot description)
            value = re.split(r'\s+erected\s+on\b', value, flags=re.IGNORECASE)[0].strip()
            # Extract the building name (first part before comma/of)
            name_m = re.match(r"([A-Za-z\s]+(?:Tower|Plaza|Centre|Center|Building|House|Mansion))",
                               value, re.IGNORECASE)
            if name_m:
                clean_value = name_m.group(1).strip().title()
                if _looks_like_building_name(clean_value):
                    page = next((p.page_num for p in doc.pages
                                 if clean_value[:8] in p.text or clean_value[:8].lower() in p.text.lower()), 0)
                    return make_result(clean_value, 0.90, page, f"Schedule 1 Building: {clean_value}",
                                       method=ExtractionMethod.rule)

    # Fallback: extract building name from premises address
    if premises_value:
        building = _extract_building_from_address(premises_value)
        if building:
            return make_result(building, 0.85, 0, f"Building from premises: {building}",
                               method=ExtractionMethod.rule)
    return not_found()


def _extract_building_from_address(address: str) -> str | None:
    parts = [part.strip() for part in address.split(",") if part.strip()]
    for part in parts:
        if _looks_like_building_name(part):
            return part
    m = re.search(r"\d{1,2}/F,\s*([^,]+),", address, re.IGNORECASE)
    if m and _looks_like_building_name(m.group(1).strip()):
        return m.group(1).strip()
    return None


def _looks_like_building_name(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    keywords = ("building", "plaza", "place", "centre", "center", "tower", "court", "house", "mansion")
    if not any(keyword in value.lower() for keyword in keywords):
        return False
    if any(token in value.lower() for token in ("security deposit", "advance deposit", "remaining deposit")):
        return False
    return True


def _looks_like_labeled_premises_address(value: str) -> bool:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= 10 or len(value) > 260:
        return False
    lower = value.lower()
    if any(fragment in lower for fragment in _BAD_PREMISES_FRAGMENTS):
        return False
    if lower.startswith("from ") and "(the \"tenant\")" in lower:
        return False
    return True


_ORDINALS_TO_INT = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "twenty-first": 21, "twenty-second": 22,
    "twenty-third": 23, "twenty-fourth": 24, "twenty-fifth": 25,
    "twenty-sixth": 26, "twenty-seventh": 27, "twenty-eighth": 28,
    "twenty-ninth": 29, "thirtieth": 30,
}


def _normalize_schedule1_premises(raw: str) -> str:
    """
    Clean up raw SCHEDULE 1 Premises block text into a readable address.
    Handles:
    - Trade Desk: "All the whole of the 22"4 and 23" Floors of the office tower
      of the building known as HYSAN PLACE (47124), 500 Hennessy Road…"
    - Hang Seng:  "Office Units on Levels L18, L19 and L20 of the Building…"
    """
    # Collapse newlines / extra whitespace
    value = re.sub(r'\s*\n\s*', ' ', raw).strip()

    # Normalize OCR-garbled ordinals:
    # "22"4" → "22"  (OCR reads "nd" as '"4' — the quote-digit suffix after digits)
    value = re.sub(r'(\d+)["\u201c\u201d]\d(?=\s|,|$)', r'\1', value)
    # "31%" or '23"' → "31" / "23"  (ordinal suffix as single punctuation char)
    value = re.sub(r'(\d+)[%"\'\u201c\u201d`](?=\s|,|$)', r'\1', value)
    # Strip residual ordinal words: "22nd", "23rd", etc.
    value = re.sub(r'(\d+)(?:st|nd|rd|th)(?=\s|,|$)', r'\1', value, flags=re.IGNORECASE)

    # Stop at land registry legal description
    value = re.sub(r'\s+erected\s+on\s+All\s+Those.*$', '', value, flags=re.DOTALL | re.IGNORECASE).strip()
    value = re.sub(r'\s+erected\s+on\s+.*$', '', value, flags=re.DOTALL | re.IGNORECASE).strip()
    value = re.sub(r'\s+shown\s+coloured\s+.*$', '', value, flags=re.DOTALL | re.IGNORECASE).strip()
    value = re.sub(r'\s+for\s+the\s+purpose\s+of\s+identification\s+only.*$', '', value,
                   flags=re.DOTALL | re.IGNORECASE).strip()

    # Remove parenthetical lot numbers e.g. "(47124)"
    value = re.sub(r'\s*\(\d{3,}\)', '', value).strip()

    # Pattern: "All the whole of the Nth and Mth Floors of the office tower of the building
    #           known as NAME, ADDRESS"
    # Use comma as required separator (so non-greedy building name doesn't stop too early)
    m = re.match(
        r"All\s+the\s+whole\s+of\s+the\s+(.+?)\s+of\s+the\s+(?:office\s+tower\s+of\s+the\s+)?building\s+"
        r"known\s+as\s+([A-Z][A-Z\s]+?)\s*,\s+(.+)",
        value, re.IGNORECASE,
    )
    if m:
        floors_raw = m.group(1).strip()          # "22nd and 23rd Floors"
        building = m.group(2).strip().title()    # "Hysan Place"
        address = m.group(3).strip()             # "500 Hennessy Road, Causeway Bay, Hong Kong"
        # Convert floor words to /F notation
        floor_label = _floors_raw_to_label(floors_raw)
        return f"{floor_label}, {building}, {address}"

    # Formal tenancy agreement style: "ALL THAT OFFICE UNIT NO.1702 on the SEVENTEENTH FLOOR…"
    legal = value
    legal = re.sub(r'\s*\(herein\s+referred\s+to[^)]*\)', '', legal, flags=re.IGNORECASE).strip()
    legal = re.sub(r'\s+erected\s+on\s+.*$', '', legal, flags=re.DOTALL | re.IGNORECASE).strip()
    legal = re.sub(r'\s+shown\s+coloured\s+.*$', '', legal, flags=re.DOTALL | re.IGNORECASE).strip()
    normalized_legal = _normalize_legal_address(legal)
    if normalized_legal != legal:
        return normalized_legal

    # Pattern: "Office Units on Levels L18, L19 and L20 of the Building…"
    m = re.match(
        r"(?:Office\s+)?Units?\s+on\s+Levels?\s+(.+?)\s+of\s+the\s+Building",
        value, re.IGNORECASE,
    )
    if m:
        levels = m.group(1).strip()  # "L18, L19 and L20"
        # Try to find building address from the schedule text (Part I - The Building)
        # This is handled downstream, return the levels as a shorthand address for now
        return f"{levels}, The Building"  # building name extracted separately

    return value


def _floors_raw_to_label(floors_raw: str) -> str:
    """
    Convert "22nd and 23rd Floors" or "22"4 and 23 Floors" (OCR) → "22/F & 23/F"
    """
    # Normalize OCR ordinal artifacts before extracting numbers
    # "22"4" → "22"  (quote + digit suffix)
    cleaned = re.sub(r'(\d+)["\u201c\u201d]\d', r'\1', floors_raw)
    # "31%" / '23"' → strip trailing punctuation ordinal
    cleaned = re.sub(r'(\d+)[%"\'\u201c\u201d`](?=\s|$)', r'\1', cleaned)
    # Strip ordinal words
    cleaned = re.sub(r'(\d+)(?:st|nd|rd|th)', r'\1', cleaned, flags=re.IGNORECASE)
    # Remove non-numeric words (and, Floors, the, etc.) — keep only digits
    nums = re.findall(r'\d+', cleaned)
    if nums:
        return " & ".join(f"{n}/F" for n in nums)
    return floors_raw


def _extract_floor_suite(
    text: str, doc: DocumentText, premises_value: str | None, schedule_text: str = ""
) -> ExtractionResult:
    """Extract floor + unit/room identifier from address or labeled field."""
    sources = [premises_value or ""] + [p.text for p in doc.pages[:5]]

    # Pattern A: "Unit/Room/Suite NNN, NN/F" (JS Gale style: "Room 1308, 13/F")
    pat_a = re.compile(
        r"(?:Unit|Room|Suite|Shop)\s+[\w\d-]+,\s+\d{1,2}/F", re.IGNORECASE
    )
    # Pattern B: "NN/F NN" without keyword (Tinygrad style: "15/F 02")
    pat_b = re.compile(r"(\d{1,2}/F\s+\d+[A-Z]?)", re.IGNORECASE)
    # Pattern C: "Unit/Room NNN ... NN/F" reversed order
    pat_c = re.compile(
        r"\d{1,2}/F[,\s]+(?:Unit|Room|Suite)\s+[\w\d-]+", re.IGNORECASE
    )

    for src in sources:
        for pat in (pat_a, pat_c):
            m = pat.search(src)
            if m:
                suite = re.sub(r"\s+", " ", m.group(0)).strip().rstrip(",")
                if len(suite) < 40:
                    page = next((pp.page_num for pp in doc.pages if suite[:10] in pp.text), 0)
                    return make_result(suite, 0.85, page, suite, method=ExtractionMethod.rule)
        m = pat_b.search(src)
        if m:
            suite = m.group(1).strip()
            if len(suite) < 20:
                page = next((pp.page_num for pp in doc.pages if suite[:6] in pp.text), 0)
                return make_result(suite, 0.80, page, suite, method=ExtractionMethod.rule)

    # Pattern D: "UNIT NO.NNNN on the <ORDINAL_WORD> FLOOR" (KLD style)
    for src in [premises_value or "", schedule_text] + [p.text for p in doc.pages[:5]]:
        m = re.search(
            r"(?:Office\s+)?Unit\s+(?:No\.?)?\s*([\w\d]+)\s+on\s+the\s+(\w+(?:-\w+)?)\s+Floor",
            src, re.IGNORECASE,
        )
        if m:
            unit_id = m.group(1)
            floor_word = m.group(2).lower()
            floor_num = _ORDINALS_TO_INT.get(floor_word)
            if floor_num:
                suite = f"Unit {unit_id}, {floor_num}/F"
                page = next((pp.page_num for pp in doc.pages if unit_id in pp.text), 0)
                return make_result(suite, 0.85, page, suite, method=ExtractionMethod.rule)

    # Pattern E: "Level NN Room NNN" / "Level NN Unit NNN" (used by some newer offices)
    for src in sources:
        m = re.search(
            r"Level\s+(\d{1,2})\s+(?:Room|Unit|Suite)\s+([\w\d-]+)", src, re.IGNORECASE
        )
        if m:
            level = m.group(1)
            unit_id = m.group(2)
            suite = f"Unit {unit_id}, {level}/F"
            page = next((pp.page_num for pp in doc.pages if unit_id in pp.text), 0)
            return make_result(suite, 0.80, page, m.group(0), method=ExtractionMethod.rule)

    # Pattern F: "Portion A of NN/F" / "Portion of the NN/F" (partial-floor leases)
    for src in sources:
        m = re.search(
            r"(Portion\s+[A-Z\d]+(?:\s+of(?:\s+the)?)?\s+\d{1,2}/F)",
            src, re.IGNORECASE,
        )
        if m:
            suite = re.sub(r"\s+", " ", m.group(1)).strip()
            page = next((pp.page_num for pp in doc.pages if suite[:8] in pp.text), 0)
            return make_result(suite, 0.80, page, suite, method=ExtractionMethod.rule)

    # Pattern F1: "Level L18, L19 and L20" (Hang Seng / Deacons style)
    for src in sources:
        m = re.search(r"Levels?\s+(L?\d+(?:(?:,\s*|\s+and\s+)L?\d+)*)", src, re.IGNORECASE)
        if m:
            levels = m.group(1).strip()
            # Normalize "L18, L19 and L20" → "L18/L19/L20"
            nums = re.findall(r'L?\d+', levels, re.IGNORECASE)
            suite = "/".join(nums)
            if suite:
                page = next((pp.page_num for pp in doc.pages if nums[0] in pp.text), 0)
                return make_result(suite, 0.85, page, f"Levels: {levels}", method=ExtractionMethod.rule)

    # Pattern F2: "NN/F & MM/F" or "NN/F, MM/F" (multi-floor whole-floor lease, Trade Desk style)
    for src in sources:
        m = re.search(r"(\d{1,2}/F(?:\s*[&,]\s*\d{1,2}/F)+)", src, re.IGNORECASE)
        if m:
            suite = re.sub(r"\s+", " ", m.group(1)).strip()
            if len(suite) < 30:
                page = next((pp.page_num for pp in doc.pages if suite[:4] in pp.text), 0)
                return make_result(suite, 0.85, page, suite, method=ExtractionMethod.rule)

    # Pattern G: "Whole of NN/F" / "Entire NN/F" (full-floor leases)
    for src in sources:
        m = re.search(
            r"(?:Whole\s+of|Entire)\s+(?:the\s+)?(\d{1,2}/F|\d{1,2}(?:st|nd|rd|th)\s+Floor)",
            src, re.IGNORECASE,
        )
        if m:
            raw = m.group(1)
            floor_m = re.match(r"(\d{1,2})", raw)
            suite = f"Whole of {floor_m.group(1)}/F" if floor_m else f"Whole of {raw}"
            page = next((pp.page_num for pp in doc.pages if raw in pp.text), 0)
            return make_result(suite, 0.80, page, m.group(0), method=ExtractionMethod.rule)

    # Pattern H: "NNth Floor" / "NNst Floor" plain form — low confidence
    for src in sources:
        m = re.search(
            r"(\d{1,2})(?:st|nd|rd|th)\s+Floor", src, re.IGNORECASE
        )
        if m:
            suite = f"{m.group(1)}/F"
            page = next((pp.page_num for pp in doc.pages if m.group(0)[:6] in pp.text), 0)
            return make_result(suite, 0.60, page, m.group(0), method=ExtractionMethod.rule)

    # Labeled field last resort
    result = find_labeled_value(text, "Unit No.", "Room No.", "Suite No.")
    if result:
        label, value = result
        value = value.strip()
        if 2 < len(value) < 30:
            page = next((p.page_num for p in doc.pages if value[:10] in p.text), 0)
            return make_result(value, 1.0, page, f"{label}: {value}", method=ExtractionMethod.regex)

    return not_found()


def _extract_area_comment(
    text: str, doc: DocumentText, area_result: ExtractionResult
) -> ExtractionResult:
    """Extract area qualifier (Gross/Net/Saleable/Rentable) or note."""
    # Look for qualifier adjacent to the area figure
    area_pattern = re.compile(
        r"([\d,]+)\s*(?:sq\.?\s*ft\.?|square\s+feet)[,\s]*\(?(Gross|Net|Saleable|Rentable|Lettable)\)?",
        re.IGNORECASE,
    )
    for p in doc.pages[:10]:
        m = area_pattern.search(p.text)
        if m:
            comment = m.group(2).capitalize()
            return make_result(comment, 0.90, p.page_num, f"Area type: {comment}",
                               method=ExtractionMethod.regex)
    # Check if area was not found — flag that it's from floor plan only
    if not area_result.is_found():
        return make_result("Not stated in document", 0.90, 0, "Area not in text",
                           method=ExtractionMethod.manual_default)
    return not_found()


def _extract_area(text: str, full_text: str, doc: DocumentText) -> ExtractionResult:
    # Tier 1: labeled fields in principal terms (most reliable)
    labeled_aliases = [
        "The Premises' Area",
        "Premises' Area",
        "Premises Area",
        "Rentable Area",
        "Lettable Area",
        "Saleable Area",
        "Net Area",
        "Floor Area",
        "Area",
    ]
    for alias in labeled_aliases:
        result = find_labeled_value(full_text, alias)
        if result:
            label, raw = result
            # Extract the first number — handles "Approximately 966 square feet (Gross)"
            m = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:sq\.?\s*ft\.?|square\s+feet|sqft)", raw, re.IGNORECASE)
            if not m:
                m = re.search(r"([\d,]+(?:\.\d+)?)", raw)
            if m:
                try:
                    area = float(m.group(1).replace(",", ""))
                    if 50 < area < 100_000:  # sanity: between 50 and 100,000 sqft
                        page = 0
                        for p in doc.pages:
                            if alias.split()[0][:8] in p.text:
                                page = p.page_num
                                break
                        return make_result(area, 1.0, page, f"{label}: {raw[:60]}",
                                           method=ExtractionMethod.regex)
                except ValueError:
                    pass

    # Tier 2: inline regex patterns in full text
    area_patterns = [
        r"(\d[\d,]+)\s*(?:sq\.?\s*ft\.?|square\s+feet)\s*\((?:gross|net|rentable|lettable)\)",
        r"(?:gross|net|rentable|lettable)\s+(\d[\d,]+)\s*(?:sq\.?\s*ft\.?|square\s+feet)",
        r"(\d[\d,]+)\s*(?:sq\.?\s*ft\.?|square\s+feet)\s+(?:net|rentable|gross|lettable)",
        r"(?:approximately\s+)?(\d[\d,]+)\s+(?:square\s+feet|sq\.?\s*ft\.?)",
    ]
    for pat in area_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            try:
                area = float(m.group(1).replace(",", ""))
                if 50 < area < 100_000:
                    page = 0
                    for p in doc.pages:
                        if m.group(0)[:20] in p.text:
                            page = p.page_num
                            break
                    return make_result(area, 0.85, page, m.group(0), method=ExtractionMethod.regex)
            except ValueError:
                pass

    return not_found("AREA_NOT_FOUND")
