"""Extract financial fields from lease documents."""
from __future__ import annotations

import re
from decimal import Decimal

from ..models import DepositComponent, ExtractionResult, Financials
from ..normalizers.currency import find_amounts, parse_hkd
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument
from .base import extract_schedule1_part, find_labeled_value, find_schedule_section, make_result, not_found, ExtractionMethod


def extract_financials(doc: DocumentText, split: SplitDocument) -> Financials:
    f = Financials()
    text = split.principal_terms
    schedule_i_text = split.schedule_i or ""
    schedule_ii_text = split.schedule_ii or ""
    full_text = split.full_text

    f.monthly_rent_hkd = _extract_monthly_rent(text, doc, schedule_ii_text, schedule_i_text)
    f.monthly_rent_psf_hkd = _extract_monthly_rent_psf(text, doc)
    f.management_fee_monthly_hkd = _extract_management_fee(text, doc, schedule_ii_text, schedule_i_text)
    f.management_fee_psf_hkd = _extract_management_fee_psf(text, doc)
    f.rates_quarterly_hkd = _extract_rates_quarterly(text, doc)
    f.rates_monthly_hkd = _extract_rates_monthly(text, doc, schedule_i_text)
    if not f.rates_monthly_hkd.is_found():
        f.rates_monthly_hkd = _derive_rates_monthly(f.rates_quarterly_hkd)
    f.government_rent_monthly_hkd = _extract_govt_rent(text, doc, schedule_i_text)
    f.security_deposit_hkd = _extract_security_deposit(text, doc, schedule_ii_text, schedule_i_text)
    f.security_deposit_multiple = _extract_deposit_multiple(text, doc, schedule_i_text)
    f.security_deposit_note = _build_deposit_note(
        f.security_deposit_hkd, f.security_deposit_multiple
    )
    f.security_deposit_components = _extract_deposit_components(schedule_ii_text)
    (
        f.transferred_security_deposit_hkd,
        f.transferred_security_deposit_note,
        f.security_deposit_balance_hkd,
        f.security_deposit_balance_note,
    ) = _extract_transferred_deposit_terms(full_text, doc)
    f.fit_out_deposit_hkd = _extract_fitout_deposit(text, full_text, doc)
    f.advance_rent_text = _extract_advance_rent(text, doc)

    return f


def _extract_monthly_rent(text: str, doc: DocumentText, schedule_ii_text: str = "",
                          schedule_i_text: str = "") -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Total Monthly Rent",
        "Monthly Rent",
        "Basic Rent",
        "The Rent",
        "Rental",
    )
    if result:
        label, raw = result
        amount = parse_hkd(raw)
        if amount:
            page = _find_page(doc, "Monthly Rent")
            return make_result(amount, 1.0, page, f"{label}: {raw}")

    unit_total = _extract_unit_amount_total_from_section(text, doc, "Rent")
    if unit_total:
        amount, page, quote = unit_total
        return make_result(amount, 1.0, page, quote, method=ExtractionMethod.rule)

    # Formal tenancy agreement: "PARTICULARS OF RENT" in Second Schedule (no colon separator)
    if schedule_ii_text:
        rent_section = find_schedule_section(schedule_ii_text, "PARTICULARS OF RENT")
        if rent_section:
            m = re.search(r"\(HK\$([\d,]+(?:\.\d+)?)\)", rent_section)
            if not m:
                m = re.search(r"HK\$([\d,]+(?:\.\d+)?)", rent_section)
            if m:
                amount = parse_hkd("HK$" + m.group(1))
                if amount and 1000 < amount < 10_000_000:
                    page = _find_page(doc, "PARTICULARS OF RENT")
                    return make_result(amount, 0.90, page, f"Schedule II rent: {rent_section[:60]}",
                                       method=ExtractionMethod.rule)

    # SCHEDULE 1 / The Schedule: "PART V\nRent" or "Part IV - Rent"
    if schedule_i_text:
        rent_block = extract_schedule1_part(schedule_i_text, "Rent")
        if rent_block:
            m = re.search(r"\(HK\$([\d,]+(?:\.\d+)?)\)", rent_block)
            if not m:
                m = re.search(r"HK\$([\d,]+(?:\.\d+)?)", rent_block)
            if m:
                amount = parse_hkd("HK$" + m.group(1))
                if amount and 1000 < amount < 100_000_000:
                    page = _find_page(doc, "per calendar month")
                    return make_result(amount, 0.90, page, f"Schedule 1 Rent: HK${m.group(1)}",
                                       method=ExtractionMethod.rule)

    return not_found("MONTHLY_RENT_NOT_FOUND")


def _extract_management_fee(text: str, doc: DocumentText, schedule_ii_text: str = "",
                            schedule_i_text: str = "") -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Monthly Management Fee/ Monthly Management Fee and Air-Conditioning Charge",
        "Monthly Management Fee and Air-Conditioning Charge",
        "Total Monthly Service Charges",
        "Monthly Service Charges",
        "Monthly Management Fee",
        "Management Fee and Air-Conditioning Charge",
        "The service charge",
        "Service Charge",
    )
    if result:
        label, raw = result
        amount = parse_hkd(raw)
        if amount:
            page = _find_page(doc, "Management Fee")
            return make_result(amount, 1.0, page, f"Management fee: {raw}")

    unit_total = _extract_unit_amount_total_from_section(text, doc, "Management and Air-conditioning Charges")
    if not unit_total:
        unit_total = _extract_unit_amount_total_after_heading(text, doc, "Management and Air-conditioning Charges")
    if unit_total:
        amount, page, quote = unit_total
        return make_result(amount, 1.0, page, quote, method=ExtractionMethod.rule)

    m = re.search(
        r"The\s+service\s+charge\s*:[\s\S]{0,220}?\(HK\$([\d,]+(?:\.\d+)?)\)",
        text,
        re.IGNORECASE,
    )
    if m:
        amount = parse_hkd("HK$" + m.group(1))
        if amount:
            page = _find_page(doc, "The service charge")
            return make_result(amount, 0.90, page, f"Formal schedule service charge: HK${m.group(1)}",
                               method=ExtractionMethod.rule)

    # Formal tenancy agreement: "monthly Service Charges... shall be HK$NNN" in Schedule II
    if schedule_ii_text:
        m = re.search(
            r"(?:service\s+charges?|management\s+fee)[\s\S]{0,200}?shall\s+be\s+(HK\$[\d,]+(?:\.\d+)?)",
            schedule_ii_text, re.IGNORECASE,
        )
        if m:
            raw_val = m.group(1)
            amount = parse_hkd(raw_val)
            if amount and 100 < amount < 5_000_000:
                page = _find_page(doc, "Service Charge")
                return make_result(amount, 0.85, page, f"Schedule II service charges: {raw_val}",
                                   method=ExtractionMethod.regex)

    # SCHEDULE 1 / The Schedule: "PART VII\nOperating Charges" (Trade Desk) or
    # "Part V – Management Fee and Air-Conditioning Charges" (Deacons)
    if schedule_i_text:
        fee_block = extract_schedule1_part(
            schedule_i_text,
            "Operating Charges",
            "Management Fee and Air-Conditioning Charges",
            "Management Fee",
        )
        if fee_block:
            m = re.search(r"\(HK\$([\d,]+(?:\.\d+)?)\)", fee_block)
            if not m:
                m = re.search(r"HK\$([\d,]+(?:\.\d+)?)", fee_block)
            if m:
                amount = parse_hkd("HK$" + m.group(1))
                if amount and 100 < amount < 50_000_000:
                    page = _find_page(doc, "Operating Charges")
                    return make_result(amount, 0.88, page, f"Schedule 1 Op.Charges: HK${m.group(1)}",
                                       method=ExtractionMethod.rule)
    return not_found()


def _extract_rates_quarterly(text: str, doc: DocumentText) -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Rates per quarter / Provisional Rates per quarter",
        "Rates per quarter",
    )
    if result:
        label, raw = result
        if re.match(r"^\s*n/?a\s*$", raw, re.IGNORECASE):
            page = _find_page(doc, "Rates per quarter")
            return make_result("n/a", 1.0, page, "Rates: N/A")
        amount = parse_hkd(raw)
        if amount:
            page = _find_page(doc, "Rates per quarter")
            return make_result(amount, 1.0, page, f"Rates quarterly: {raw}")
    return not_found()


def _extract_rates_monthly(text: str, doc: DocumentText, schedule_i_text: str = "") -> ExtractionResult:
    result = find_labeled_value(text, "Monthly Government Rates")
    if result:
        label, raw = result
        amount = parse_hkd(raw)
        if amount:
            page = _find_page(doc, "Monthly Government Rates")
            return make_result(amount, 1.0, page, f"{label}: {raw}", method=ExtractionMethod.rule)

    if schedule_i_text:
        rates_block = extract_schedule1_part(schedule_i_text, "Rates")
        if rates_block and re.search(r"per\s+calendar\s+month", rates_block, re.IGNORECASE):
            m = re.search(r"HK\$([\d,]+(?:\.\d+)?)", rates_block)
            if m:
                amount = parse_hkd("HK$" + m.group(1))
                if amount:
                    page = _find_page(doc, "Rates")
                    return make_result(amount, 1.0, page, f"Schedule 1 Rates monthly: HK${m.group(1)}",
                                       method=ExtractionMethod.rule)
    return not_found()


def _derive_rates_monthly(quarterly: ExtractionResult) -> ExtractionResult:
    if quarterly.value and quarterly.value != "n/a":
        monthly = Decimal(str(quarterly.value)) / 3
        return ExtractionResult(
            value=monthly,
            confidence=0.70,
            evidence=quarterly.evidence,
            review_flag="RATES_CONVERTED_QUARTERLY_TO_MONTHLY",
        )
    if quarterly.value == "n/a":
        return ExtractionResult(value="n/a", confidence=1.0, evidence=quarterly.evidence)
    return not_found()


def _extract_govt_rent(text: str, doc: DocumentText, schedule_i_text: str = "") -> ExtractionResult:
    # Check for "Monthly Government Rates" first (already a monthly figure — no division)
    monthly_result = find_labeled_value(
        text,
        "Monthly Government Rates",
        "Government Rates",
    )
    if monthly_result:
        label, raw = monthly_result
        if re.match(r"^\s*n/?a\s*$", raw, re.IGNORECASE):
            page = _find_page(doc, "Government Rates")
            return make_result("n/a", 1.0, page, "Govt Rates: N/A")
        amount = parse_hkd(raw)
        if amount:
            page = _find_page(doc, "Government Rates")
            return make_result(amount, 1.0, page, f"Monthly Govt Rates: {raw}")

    # Quarterly government rent (divide by 3)
    result = find_labeled_value(
        text,
        "Government Rent per quarter / Provisional Government Rent per quarter",
        "Government Rent per quarter",
        "Government Rent",
    )
    if result:
        label, raw = result
        if re.match(r"^\s*n/?a\s*$", raw, re.IGNORECASE):
            page = _find_page(doc, "Government Rent")
            return make_result("n/a", 1.0, page, "Government Rent: N/A")
        amount = parse_hkd(raw)
        if amount:
            monthly = amount / 3
            page = _find_page(doc, "Government Rent")
            return make_result(
                monthly, 0.70, page, f"Govt rent quarterly {raw} -> monthly",
                method=ExtractionMethod.computed,
            )

    # SCHEDULE 1 / The Schedule: "PART IX\nRates" (Trade Desk) — stated as monthly
    if schedule_i_text:
        rates_block = extract_schedule1_part(schedule_i_text, "Rates")
        if rates_block:
            # Check if amount is per calendar month (already monthly)
            m = re.search(r"\(HK\$([\d,]+(?:\.\d+)?)\)", rates_block)
            if not m:
                m = re.search(r"HK\$([\d,]+(?:\.\d+)?)", rates_block)
            if m:
                amount = parse_hkd("HK$" + m.group(1))
                if amount and 100 < amount < 50_000_000:
                    # Determine if this is stated as per calendar month or quarterly
                    if re.search(r"per\s+calendar\s+month", rates_block, re.IGNORECASE):
                        page = _find_page(doc, "Rates")
                        return make_result(amount, 0.90, page,
                                           f"Schedule 1 Rates (monthly): HK${m.group(1)}",
                                           method=ExtractionMethod.rule)
                    else:
                        # Treat as quarterly
                        monthly = amount / 3
                        page = _find_page(doc, "Rates")
                        return make_result(monthly, 0.75, page,
                                           f"Schedule 1 Rates (quarterly→monthly): HK${m.group(1)}",
                                           method=ExtractionMethod.computed)
    return not_found()


def _extract_security_deposit(text: str, doc: DocumentText, schedule_ii_text: str = "",
                              schedule_i_text: str = "") -> ExtractionResult:
    result = find_labeled_value(text, "Security Deposit", "Full Security Deposit")
    if result:
        label, raw = result
        page = _find_page(doc, "Security Deposit")

        # Pattern 1: "= HK$NNN" total at end of composed breakdown
        eq_match = re.search(r"=\s*((?:HK\$|Hong\s+Kong\s+\$|HK\s*\$)\s*[\d,]+(?:\.\d+)?)", raw)
        if eq_match:
            amount = parse_hkd(eq_match.group(1))
            if amount:
                return make_result(amount, 1.0, page, f"Security Deposit total: {eq_match.group(1)}")

        # Pattern 2: first sub-item (i) contains the amount (Tinygrad style)
        amount = parse_hkd(raw.split("(ii)")[0])
        if amount:
            return make_result(amount, 1.0, page, f"Security Deposit: {raw[:60]}")

        # Pattern 3: first HK$ amount in raw value
        amounts = find_amounts(raw)
        if amounts:
            return make_result(amounts[0][0], 0.85, page, f"Security Deposit: {raw[:60]}")

    unit_total = _extract_unit_deposit_total(text, doc)
    if unit_total:
        amount, page, quote = unit_total
        return make_result(amount, 1.0, page, quote, method=ExtractionMethod.rule)

    # Formal tenancy agreement: "TOTAL...HK$\nNNN" in Second Schedule deposit table
    if schedule_ii_text:
        total_m = re.search(
            r"TOTAL[\s.:\d]*?(HK[S$]\s*[\d,]+(?:\.\d+)?|HK[S$]\s*\n\s*[\d,]+(?:\.\d+)?)",
            schedule_ii_text, re.IGNORECASE,
        )
        if total_m:
            raw_total = total_m.group(1).replace("\n", "").replace(" ", "").replace("HKS", "HK$")
            amount = parse_hkd(raw_total)
            if amount and amount > 10_000:
                page = _find_page(doc, "TOTAL")
                return make_result(amount, 0.90, page, f"Schedule II deposit total: {total_m.group(1)[:30]}",
                                   method=ExtractionMethod.rule)

    total_m = re.search(
        r"TOTAL[\s.:\d]*?(HK[S$]\s*[\d,]+(?:\.\d+)?|HK[S$]\s*\n\s*[\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if total_m:
        raw_total = total_m.group(1).replace("\n", "").replace(" ", "").replace("HKS", "HK$")
        amount = parse_hkd(raw_total)
        if amount and amount > 10_000:
            page = _find_page(doc, "TOTAL")
            return make_result(amount, 1.0, page, f"Deposit total: {total_m.group(1)[:30]}",
                               method=ExtractionMethod.rule)

    # SCHEDULE 1 / The Schedule: "PART X\nDeposit" (Trade Desk) or "Part VII - Deposit" (Deacons)
    if schedule_i_text:
        dep_block = extract_schedule1_part(schedule_i_text, "Deposit")
        if dep_block:
            # Allow spaces within amounts: "HK$10,996, 128.00" → "10996128.00"
            m = re.search(r"\(HK\$([\d,\s]+(?:\.\d+)?)\)", dep_block)
            if not m:
                m = re.search(r"HK\$([\d,\s]+(?:\.\d+)?)", dep_block)
            if m:
                raw_num = m.group(1).replace(" ", "")
                amount = parse_hkd("HK$" + raw_num)
                if amount and amount > 10_000:
                    page = _find_page(doc, "Deposit")
                    return make_result(amount, 0.90, page, f"Schedule 1 Deposit: HK${raw_num}",
                                       method=ExtractionMethod.rule)

    m_henley = re.search(
        r"THE\s+EIGHTH\s+SCHEDULE\s+The\s+deposit\s*:[\s\S]{0,260}?HK\$([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if m_henley:
        amount = parse_hkd("HK$" + m_henley.group(1))
        if amount:
            page = _find_page(doc, "THE EIGHTH SCHEDULE")
            return make_result(amount, 1.0, page, f"Eighth Schedule deposit: HK${m_henley.group(1)}",
                               method=ExtractionMethod.rule)

    return not_found("SECURITY_DEPOSIT_NOT_FOUND")


def _extract_deposit_multiple(text: str, doc: DocumentText, schedule_i_text: str = "") -> ExtractionResult:
    result = find_labeled_value(
        text,
        "Multiple of (the highest) Monthly Rent and other charges",
        "Multiple of",
    )
    if result:
        label, raw = result
        m = re.search(r"(\d+)", raw)
        if m:
            page = _find_page(doc, "Multiple")
            return make_result(int(m.group(1)), 1.0, page, f"Multiple: {raw}")
    # Try inline pattern
    m = re.search(r"(\d+)\s+times.*monthly\s+rent", text, re.IGNORECASE)
    if m:
        page = _find_page(doc, m.group(0)[:20])
        return make_result(int(m.group(1)), 0.85, page, m.group(0))

    m = re.search(
        r"equivalent\s+to\s+\w+\s*\((\d+)\)\s+months?[’']?\s+Rent",
        text,
        re.IGNORECASE,
    )
    if m:
        page = _find_page(doc, "equivalent to")
        return make_result(int(m.group(1)), 1.0, page, m.group(0), method=ExtractionMethod.rule)

    m = re.search(r"(\d+)\s*\([^)]*\)\s*-\s*Month\s+Actual\s+Rent", text, re.IGNORECASE)
    if m:
        page = _find_page(doc, "Full Security Deposit")
        return make_result(int(m.group(1)), 1.0, page, m.group(0), method=ExtractionMethod.rule)

    # SCHEDULE 1 / The Schedule: "three (3) months' Rent…" in Deposit block
    if schedule_i_text:
        dep_block = extract_schedule1_part(schedule_i_text, "Deposit")
        if dep_block:
            m2 = re.search(r"(\d+)\s*\)\s*months?['']", dep_block, re.IGNORECASE)
            if not m2:
                m2 = re.search(r"\((\d+)\)\s*months?", dep_block, re.IGNORECASE)
            if m2:
                page = _find_page(doc, "Deposit")
                return make_result(int(m2.group(1)), 0.85, page, f"Schedule 1 Deposit: {m2.group(0)}",
                                   method=ExtractionMethod.rule)
    return not_found()


def _build_deposit_note(
    deposit: ExtractionResult, multiple: ExtractionResult,
) -> ExtractionResult:
    if multiple.value and deposit.value:
        note = (
            f"{multiple.value} months highest monthly rent and other charges"
        )
        return ExtractionResult(
            value=note, confidence=0.85,
            evidence=deposit.evidence + multiple.evidence,
        )
    if deposit.value:
        note = "Security deposit as per offer"
        return ExtractionResult(value=note, confidence=0.50, evidence=deposit.evidence)
    return not_found()


def _extract_transferred_deposit_terms(
    full_text: str,
    doc: DocumentText,
) -> tuple[ExtractionResult, ExtractionResult, ExtractionResult, ExtractionResult]:
    if not full_text:
        return not_found(), not_found(), not_found(), not_found()

    transfer_match = re.search(
        r"deposit\s+in\s+the\s+sum\s+of\s*HK\$([\d,]+(?:\.\d+)?)"
        r"[\s\S]{0,500}?Existing\s+Tenancy\s+Agreement"
        r"[\s\S]{0,250}?transferred",
        full_text,
        re.IGNORECASE,
    )
    balance_match = re.search(
        r"excess\s+balance\s+of\s+the\s+deposit\s+in\s+the\s+sum\s+of\s*"
        r"HK\$([\d,]+(?:\.\d+)?)"
        r"[\s\S]{0,200}?settle\s+future\s+monthly\s+rental\s+under\s+this\s+Agreement",
        full_text,
        re.IGNORECASE,
    )

    transferred_amount = not_found()
    transferred_note = not_found()
    balance_amount = not_found()
    balance_note = not_found()

    lht_transfer = re.search(
        r"sum\s+of\s*HK\$([\d,]+(?:\.\d+)?)"
        r"[\s\S]{0,120}?transferred\s+out\s+of\s+the\s+existing\s+1101\s+Deposit",
        full_text,
        re.IGNORECASE,
    )
    if lht_transfer:
        amount = parse_hkd("HK$" + lht_transfer.group(1))
        if amount:
            quote = lht_transfer.group(0)[:260]
            page = _find_page(doc, lht_transfer.group(1))
            transferred_amount = make_result(
                amount, 1.0, page, quote, method=ExtractionMethod.rule
            )
            transferred_note = make_result(
                "Transferred out of existing 1101 Deposit",
                1.0,
                page,
                quote,
                method=ExtractionMethod.rule,
            )

    if transfer_match:
        amount = parse_hkd("HK$" + transfer_match.group(1))
        if amount:
            quote = transfer_match.group(0)[:260]
            page = _find_page(doc, transfer_match.group(1))
            transferred_amount = make_result(
                amount, 0.95, page, quote, method=ExtractionMethod.rule
            )
            transferred_note = make_result(
                "Previous Tenancy Agreement (Transfer)",
                0.85,
                page,
                quote,
                method=ExtractionMethod.rule,
            )

    if balance_match:
        amount = parse_hkd("HK$" + balance_match.group(1))
        if amount:
            quote = balance_match.group(0)[:260]
            page = _find_page(doc, balance_match.group(1))
            balance_amount = make_result(
                amount, 0.95, page, quote, method=ExtractionMethod.rule
            )
            balance_note = make_result(
                "Settle future monthly rental under the new Tenancy",
                0.90,
                page,
                quote,
                method=ExtractionMethod.rule,
            )

    return transferred_amount, transferred_note, balance_amount, balance_note


def _extract_unit_amount_total_from_section(
    text: str,
    doc: DocumentText,
    heading: str,
) -> tuple[Decimal, int, str] | None:
    section = _extract_numbered_section(text, heading)
    if not section:
        return None
    following_amount = re.search(r"following\s+amount", section, re.IGNORECASE)
    if following_amount:
        section = section[following_amount.start():]
    amounts: list[Decimal] = []
    quotes: list[str] = []
    for match in re.finditer(
        r"Unit\s+\d+\s*[:;]\s*HK\$([\d,]+(?:\.\d+)?)\s+per\s+month",
        section,
        re.IGNORECASE,
    ):
        amount = parse_hkd("HK$" + match.group(1))
        if amount:
            amounts.append(amount)
            quotes.append(match.group(0))
    if len(amounts) < 2:
        return None
    page = _find_page(doc, quotes[0][:20]) if quotes else _find_page(doc, heading)
    return sum(amounts, Decimal("0")), page, f"{heading} unit total: {'; '.join(quotes)}"


def _extract_unit_deposit_total(text: str, doc: DocumentText) -> tuple[Decimal, int, str] | None:
    section = _extract_numbered_section(text, "Deposit") or _extract_from_phrase_to_next_numbered(
        text, "The Tenant shall deposit"
    )
    if not section:
        return None
    amounts: list[Decimal] = []
    quotes: list[str] = []
    pattern = re.compile(
        r"Deposit\s+payable\s+for\s+the\s+tenancy\s+to\s+be\s+granted\s+herein\s+"
        r"in\s+respect(?:\s+of)?\s*U(?:n|m)it\s+\d+\s+is\s+in\s+the\s+sum\s+of\s*"
        r"HK\s*\$([\d,]+(?:\.\d+)?)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(section):
        amount = parse_hkd("HK$" + match.group(1))
        if amount:
            amounts.append(amount)
            quotes.append(re.sub(r"\s+", " ", match.group(0)).strip())
    if len(amounts) < 2:
        return None
    page = _find_page(doc, quotes[0][:20]) if quotes else _find_page(doc, "Deposit payable")
    return sum(amounts, Decimal("0")), page, f"Deposit unit total: {'; '.join(quotes)}"


def _extract_numbered_section(text: str, heading: str) -> str | None:
    pattern = re.compile(
        r"(?ms)^\s*\d+\s*[\.,]?\s*(?:\([a-z]\)\s*)?"
        + re.escape(heading)
        + r"[^\n]*\n(.*?)(?=^\s*\d+\s*[\.,]\s*(?:\([a-z]\)\s*)?[A-Z]|\Z)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _extract_unit_amount_total_after_heading(
    text: str,
    doc: DocumentText,
    heading: str,
) -> tuple[Decimal, int, str] | None:
    match = re.search(
        re.escape(heading) + r"[\s\S]{0,1800}",
        text,
        re.IGNORECASE,
    )
    sections = [
        match.group(0)
        for match in re.finditer(re.escape(heading) + r"[\s\S]{0,1800}", text, re.IGNORECASE)
        if re.search(r"following\s+amount", match.group(0), re.IGNORECASE)
    ]
    if not sections:
        return None
    section = sections[-1]
    following_amount = re.search(r"following\s+amount", section, re.IGNORECASE)
    if following_amount:
        section = section[following_amount.start():]
    amounts: list[Decimal] = []
    quotes: list[str] = []
    for amount_match in re.finditer(
        r"Unit\s+\d+\s*[:;<]?\s*HK\$([\d,]+(?:\.\d+)?)\s+per\s+month",
        section,
        re.IGNORECASE,
    ):
        amount = parse_hkd("HK$" + amount_match.group(1))
        if amount:
            amounts.append(amount)
            quotes.append(amount_match.group(0))
    if len(amounts) < 2:
        return None
    page = _find_page(doc, quotes[0][:20]) if quotes else _find_page(doc, heading)
    return sum(amounts, Decimal("0")), page, f"{heading} unit total: {'; '.join(quotes)}"


def _extract_from_phrase_to_next_numbered(text: str, phrase: str) -> str | None:
    match = re.search(
        re.escape(phrase) + r"[\s\S]*?(?=^\s*\d+\s*[\.,]\s*(?:\([a-z]\)\s*)?[A-Z]|\Z)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    return match.group(0).strip() if match else None


def _extract_fitout_deposit(text: str, full_text: str, doc: DocumentText) -> ExtractionResult:
    result = find_labeled_value(text, "Fit-out Deposit", "Fit Out Deposit")
    if result:
        label, raw = result
        amount = parse_hkd(raw)
        if amount:
            page = _find_page(doc, "Fit-out Deposit")
            return make_result(amount, 1.0, page, f"Fit-out Deposit: {raw}")
        if re.match(r"^\s*n/?a\s*$", raw, re.IGNORECASE):
            page = _find_page(doc, "Fit-out Deposit")
            return make_result("n/a", 1.0, page, "Fit-out Deposit: N/A")

    # Check payments-on-signing table
    m = re.search(r"Fit-out Deposit\s*:?\s*\n?\s*(HK\$[\d,]+\.?\d*)", full_text, re.IGNORECASE)
    if m:
        amount = parse_hkd(m.group(1))
        if amount:
            page = _find_page(doc, "Fit-out Deposit")
            return make_result(amount, 0.85, page, f"Fit-out deposit from payments: {m.group(1)}")
    return not_found()


def _extract_deposit_components(schedule_ii_text: str) -> list[DepositComponent]:
    """
    Extract itemised deposit table from Second Schedule DEPOSIT section.
    Handles:
      RENTAL DEPOSIT        HK$   216,714.00
      SERVICE CHARGES DEPOSIT  HK$  60,451.80
      TOTAL                 HK$  277,165.80
    """
    if not schedule_ii_text:
        return []
    # Find DEPOSIT section
    deposit_section_m = re.search(
        r"DEPOSIT\s*\n(.*?)(?=\n\s*PART\s+|\n\s*The\s+monthly|\Z)",
        schedule_ii_text, re.IGNORECASE | re.DOTALL,
    )
    if not deposit_section_m:
        return []
    section = deposit_section_m.group(1)

    components: list[DepositComponent] = []
    # Match lines: "LABEL ... HK$ AMOUNT" (possibly split across lines by OCR)
    line_pat = re.compile(
        r"([A-Z][A-Z\s]+?)\s+HK\$\s*\n?\s*([\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    for m in line_pat.finditer(section):
        label = re.sub(r"\s+", " ", m.group(1)).strip().title()
        try:
            amount = Decimal(m.group(2).replace(",", ""))
            if amount > 0:
                components.append(DepositComponent(label=label, amount=amount))
        except Exception:
            pass
    return components


def _extract_monthly_rent_psf(text: str, doc: DocumentText) -> ExtractionResult:
    """Extract rent per square foot per month."""
    m = re.search(
        r"(?:HK\$|Hong\s+Kong\s+\$|\$)\s*([\d,]+(?:\.\d+)?)\s+per\s+square\s+foot\s+per\s+month",
        text, re.IGNORECASE,
    )
    if m:
        from decimal import Decimal
        val = Decimal(m.group(1).replace(",", ""))
        if 1 < val < 1000:
            page = _find_page(doc, "per square foot")
            return make_result(val, 0.90, page, m.group(0))
    return not_found()


def _extract_management_fee_psf(text: str, doc: DocumentText) -> ExtractionResult:
    """Extract management fee per square foot."""
    m = re.search(
        r"(?:service\s+charge|management\s+fee).{0,200}"
        r"(?:HK\$|Hong\s+Kong\s+\$|\$)\s*([\d,]+(?:\.\d+)?).{0,30}per\s+square\s+foot",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        from decimal import Decimal
        val = Decimal(m.group(1).replace(",", ""))
        if 1 < val < 200:
            page = _find_page(doc, "per square foot")
            return make_result(val, 0.90, page, m.group(0)[:100])
    return not_found()


def _extract_advance_rent(text: str, doc: DocumentText) -> ExtractionResult:
    # Look for advance rent in payments table
    m = re.search(
        r"(?:advance\s+rent|rent.*advance)\s*:?\s*(HK\$[\d,]+\.?\d*|\bN/?A\b)",
        text, re.IGNORECASE,
    )
    if m:
        raw = m.group(1)
        if re.match(r"n/?a", raw, re.IGNORECASE):
            return ExtractionResult(value="n/a", confidence=1.0, evidence=[])
        amount = parse_hkd(raw)
        if amount:
            page = _find_page(doc, "advance rent")
            return make_result(amount, 0.85, page, f"Advance rent: {raw}",
                               method=ExtractionMethod.rule)
    return ExtractionResult(value="n/a", confidence=0.70, evidence=[])


def _find_page(doc: DocumentText, snippet: str) -> int:
    snippet_short = snippet[:20].lower()
    for p in doc.pages:
        if snippet_short in p.text.lower():
            return p.page_num
    return 0
