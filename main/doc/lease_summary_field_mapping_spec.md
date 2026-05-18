# Lease Summary Automation Field Mapping Spec (Python-First MVP)

## 1. Purpose

This document defines a complete Python-first implementation spec for automating the preparation of Opus Hong Kong lease summary files from three common input types:

- Offer to Lease
- Lease
- Signed Lease / Tenancy Agreement

The immediate goal is not to create a general AI chatbot. The goal is to build a reliable document-processing workflow that:

1. reads the source lease document,
2. extracts the fields needed by the Opus lease summary workbook,
3. writes those values into the Excel template,
4. marks uncertain or missing items for staff review,
5. produces an output file ready for internal checking before being sent to the client.

This specification is written for a **Python-first MVP**. No vector database or RAG system is required for the first version.

---

## 2. Recommended Delivery Strategy

### 2.1 Recommended v1 architecture

Use:

- Python
- PDF text extraction
- OCR only when necessary
- deterministic field extractors
- workbook population with `openpyxl`
- validation and review flags

### 2.2 Why this approach fits the task

The Opus HK summary workbook is a fixed template with a stable set of fields. The sample completed summaries show that the required output is not a free-form memo; it is a standardized summary sheet with recurring business fields such as:

- landlord / tenant
- address
- commencement / expiry
- lease term
- monthly rent
- operating expenses
- security deposit
- advance rent
- subletting
- parking
- restoration obligations

That means the core problem is **field extraction and workbook population**, not open-ended Q&A.

### 2.3 What is out of scope for MVP

The following should not be first-version requirements:

- conversational search across all leases
- clause similarity search
- semantic RAG over a vector store
- automated legal advice
- autonomous outbound emailing or CRM updates

These can be added later if needed.

---

## 3. Inputs and Outputs

### 3.1 Inputs

Supported inputs in MVP:

- native text PDFs
- scanned PDFs with OCR fallback
- files representing offer to lease, tenancy agreement, or signed lease

### 3.2 Output files

For each input document, the system should generate:

1. **Filled Excel summary workbook**
2. **Structured JSON extraction result**
3. **Review report** listing missing, ambiguous, and flagged fields

Suggested naming:

- `Offer to Lease_Hollywood Centre 1502 20260203.summary.xlsx`
- `Offer to Lease_Hollywood Centre 1502 20260203.extraction.json`
- `Offer to Lease_Hollywood Centre 1502 20260203.review.json`

---

## 4. Reference Files Used To Define This Spec

The spec below is aligned to the uploaded materials:

- `Opus Lease Summary Template - HK.xlsx`
- `JS Gale Lease Summary 2023-2026 20250403.xlsx`
- `KLDiscovery Lease Summary 2025-2027 Renewal 20250722.xlsx`
- `Offer to Lease_Hollywood Centre 1502 20260203.pdf`

The Tinygrad offer-to-lease sample confirms that many required fields are explicitly labeled in the source document, including landlord, tenant, premises, term commencement, term expiry, monthly rent, monthly management fee, rates, security deposit, rent free period, landlord solicitor, user, handover condition, fit-out deposit and break clause. fileciteturn3file14L1-L59 fileciteturn3file10L1-L33

The offer also contains clause-level detail needed for review fields such as subletting, signage, notice mechanics, landlord redevelopment termination rights, security deposit treatment, and fit-out obligations. fileciteturn3file7L1-L33 fileciteturn3file11L1-L34 fileciteturn3file12L1-L36 fileciteturn3file17L1-L31

---

## 5. High-Level Workflow

### 5.1 Processing pipeline

1. Load source PDF.
2. Extract text page by page.
3. Detect whether OCR is needed.
4. Normalize text.
5. Segment document into headings / numbered sections / schedules.
6. Run field extractors.
7. Standardize values.
8. Validate cross-field consistency.
9. Populate Excel template.
10. Generate review flags.
11. Save workbook and machine-readable outputs.

### 5.2 Human review workflow

The automation is intended to reduce manual drafting time, not eliminate review.

Recommended operational model:

- system drafts summary,
- staff checks flagged fields,
- staff confirms final summary,
- client-ready file is issued.

---

## 6. Proposed Python Project Structure

```text
lease_summary_automation/
  app/
    main.py
    config.py
    models.py
    pipeline.py
    extractors/
      basic_fields.py
      dates.py
      money.py
      clauses.py
      premises.py
    parsers/
      pdf_text.py
      ocr.py
      section_splitter.py
    writers/
      excel_writer.py
      json_writer.py
    validators/
      field_validator.py
      business_rules.py
    utils/
      text_norm.py
      dates.py
      currency.py
      logging.py
  templates/
    Opus Lease Summary Template - HK.xlsx
  output/
  tests/
    fixtures/
    test_extractors.py
    test_excel_writer.py
```

---

## 7. Data Model

### 7.1 Canonical intermediate JSON schema

The system should extract to JSON first, then write to Excel.

```json
{
  "document_meta": {
    "source_filename": "",
    "document_type": "offer_to_lease | lease | signed_lease | unknown",
    "parsed_with_ocr": false,
    "pages": 0
  },
  "summary_meta": {
    "summary_date": "YYYY-MM-DD",
    "property_type": "Office",
    "opportunity_name": null,
    "opportunity_owner": null,
    "opportunity_office": "Hong Kong"
  },
  "parties": {
    "landlord_name": null,
    "landlord_registered_address": null,
    "landlord_business_address": null,
    "landlord_agent": null,
    "tenant_name": null,
    "tenant_registered_address": null,
    "tenant_correspondence_address": null,
    "tenant_contact_person": null
  },
  "premises": {
    "full_address": null,
    "building_address": null,
    "floor_or_suite": null,
    "rentable_area_sqft": null,
    "net_area_sqft": null,
    "area_comment": null
  },
  "term": {
    "lease_signing_date": null,
    "scheduled_commencement_date": null,
    "lease_commencement_date": null,
    "lease_expiry_date": null,
    "lease_term_months": null,
    "fit_out_period_text": null,
    "rent_free_period_text": null,
    "option_to_renew_text": null,
    "trigger_date_text": null,
    "right_of_expansion_text": null,
    "tenant_termination_right_text": null
  },
  "financials": {
    "monthly_rent_hkd": null,
    "monthly_rent_psf_hkd": null,
    "operating_expense_start": null,
    "operating_expense_end": null,
    "management_fee_monthly_hkd": null,
    "management_fee_psf_hkd": null,
    "government_rates_monthly_hkd": null,
    "government_rent_monthly_hkd": null,
    "operating_expense_note": null,
    "security_deposit_hkd": null,
    "security_deposit_note": null,
    "advance_rent_text": null
  },
  "clauses": {
    "signage_text": null,
    "subletting_text": null,
    "parking_text": null,
    "restoration_obligations_text": null,
    "user_clause_text": null,
    "break_clause_text": null,
    "handover_condition_text": null
  },
  "review": {
    "confidence": 0.0,
    "review_required": false,
    "flags": []
  },
  "evidence": {
    "field_name": [
      {
        "page": 1,
        "quote": "...",
        "method": "regex | rule | computed | manual_default"
      }
    ]
  }
}
```

---

## 8. Workbook Mapping Specification

This section defines the Opus template fields and how each should be populated.

## 8.1 Template assumptions

The workbook contains one visible working sheet named `Lease Summary`.

The template contains stable labels and target values primarily in columns `C`, `D`, `E`, `F`, `G`, `H`, and `I`. Existing formulas in completed examples should be preserved where useful.

## 8.2 Workbook field map

| Business Field | Cell(s) | Type | Source / rule |
|---|---|---:|---|
| Title | `B4` | text | `{account_name} Summary` or tenant name summary title |
| Summary date | `C7` | date | current run date unless business rule says otherwise |
| Property type | `D8` | text | default `Office` unless source clearly differs |
| Account name | `D9` | text | tenant name |
| Address | `D10` | text | full premises address |
| Building address | `E12` | text | usually same as full premises address unless a separate building-only address is preferred |
| Lease signing date | `E14` | date | execution / date of agreement / date signed |
| Scheduled commencement date | `E16` | date | scheduled commencement if stated; else commencement |
| Lessor name | `E18:E21` | text | landlord name and supporting address / agent lines |
| Tenant name | `E22:E23` | text | tenant name and optional registered office line |
| Premises rentable area | `G22` or analogous template row | number | rentable area in sq ft |
| Lease term | `E24` | integer | months |
| Lease commencement date | `E26` | date | commencement |
| Lease expiry date | `E28` or `E30` depending template version | date | expiry |
| Option to renew | `E30` or `E32` | text | clause summary or `n/a` |
| Trigger date | adjacent renewal row | text | clause summary or `n/a` |
| Right of expansion | expansion row | text | clause summary or `n/a` |
| Fit-out period | fit-out row | text | clause summary or `n/a` |
| Signage | signage row | text | signage rights / restrictions or `n/a` |
| Operating expenses text | operating expenses heading rows | text | management fee / AC / rates / government rent |
| Operating expense start date | date cell in op-exp section | date | commencement or stated effective date |
| Operating expense amount | amount cell in op-exp section | currency | monthly management / AC charge |
| Tenant termination right | termination row | text | break / termination right or `n/a` |
| Monthly rent psf | formula cell | formula / value | derive from monthly rent ÷ rentable area |
| Monthly rent total | monthly rent amount cell | currency | monthly rent |
| Security deposit | deposit amount row(s) | currency + note | security deposit amount and composition |
| Advance rent | advance rent row | text | details or `n/a` |
| Sub-letting | subletting row | text | clause summary or `n/a` |
| Parking | parking row | text | clause summary or `n/a` |
| Restoration obligations | restoration row | text | reinstatement / yielding-up summary |

### 8.3 Important implementation note

The exact template row positions differ slightly between the blank template and the sample completed files. The writer should therefore support **label-based cell discovery** instead of hardcoding every row number.

Recommended method:

1. load workbook,
2. build a map of visible labels in column `B`,
3. resolve target coordinates dynamically,
4. write values relative to the label row.

This is safer than relying only on row numbers.

---

## 9. Extraction Rules By Field

## 9.1 Summary metadata

### 9.1.1 Summary date
- Source: system run date
- Method: Python-generated
- Review required: no

### 9.1.2 Property type
- Default: `Office`
- If source says retail / industrial / warehouse, override.
- Method: rule-based keyword detection

---

## 9.2 Parties

### 9.2.1 Landlord name
**Priority order**
1. `Name of Landlord`
2. `Landlord`
3. named lessor in execution section
4. lessor party definition in formal tenancy agreement

**Method**
- regex on labeled principal terms section
- fallback section parser in formal lease

### 9.2.2 Landlord address / agent
Extract if explicitly present.
Write additional details on subsequent landlord lines when available.

### 9.2.3 Tenant name
**Priority order**
1. `Name of Tenant`
2. tenant party definition
3. signature block name

### 9.2.4 Tenant registered office
Extract when present. In the Tinygrad offer sample, the tenant registered office / principal place of business and correspondence address are explicitly stated and can populate the tenant detail lines. fileciteturn3file14L21-L44

---

## 9.3 Premises

### 9.3.1 Full address
Use the full premises address as shown in the principal particulars. In the Tinygrad sample, the premises are stated as `15/F 02, Floor 15, Hollywood Centre, 233 Hollywood Road, Sheung Wan, Hong Kong`. fileciteturn3file14L45-L55

### 9.3.2 Building address
Default to the same as full address unless a business rule later requires building-only normalization.

### 9.3.3 Floor / suite
Extract from premises text if separable.

### 9.3.4 Size / rentable area
**Priority order**
1. explicit rentable area / saleable area / lettable area in schedule or plan
2. annexed floor plan metadata
3. manual review required if not found

If area is absent, do not invent it.
Set:
- `rentable_area_sqft = null`
- `review_required = true`
- flag `AREA_NOT_FOUND`

---

## 9.4 Dates and term

### 9.4.1 Lease signing date
**Priority order**
1. date of tenancy agreement / date signed
2. print date only if document is clearly an offer and no execution date exists
3. manual review if there are multiple candidate dates

### 9.4.2 Scheduled commencement date
If the document provides a specific scheduled commencement date, use it. Otherwise reuse the lease commencement date.

### 9.4.3 Lease commencement date
Extract from labels such as:
- `Term Commencement Date`
- `Commencement Date`
- `Lease Commencement Date`
- `Date of commencement`

### 9.4.4 Lease expiry date
Extract from labels such as:
- `Term Expiry Date`
- `Expiration Date`
- `Expiry Date`

### 9.4.5 Lease term months
If term months are not explicitly stated, compute as the whole-month difference between commencement and expiry, inclusive by business convention used in the existing summaries.

For the Tinygrad offer sample, commencement is `11 February 2026` and expiry is `10 February 2028`, which corresponds to a 24-month term under standard commercial summary treatment. fileciteturn3file14L45-L59

### 9.4.6 Rent-free period / fit-out period
Extract free-text summary. In the Tinygrad sample, rent free is explicitly stated as `28 days Rent Free from 11 February 2026 to 10 March 2026`. fileciteturn3file10L1-L18

If the template needs separate fit-out wording, use the explicit fit-out wording if present; otherwise map rent-free / fitting-out wording to the fit-out period row and flag when interpretation is needed.

---

## 9.5 Renewal / trigger / expansion / termination

### 9.5.1 Option to renew
Extract only when the tenant has a clear renewal right.

Indicators:
- `option to renew`
- `option to extend`
- `renewal term`
- `further term`

If none is found, write `n/a`.

### 9.5.2 Trigger date
Only populate when renewal or break notice mechanics clearly state a trigger / notice deadline.

### 9.5.3 Right of expansion
Only populate when the tenant has express first right / right of expansion / right of first offer on adjacent premises.

### 9.5.4 Tenant termination right
Populate only for an actual tenant break / tenant termination right.

Important distinction:
- landlord redevelopment termination right is **not** the same as tenant termination right.
- it may still be captured in a review note if desired.

In the Tinygrad offer, the principal particulars say `Break Clause: N/A`. The general conditions also give the landlord a redevelopment / sale termination right on six months' notice, but that should not be mapped as a tenant termination right. fileciteturn3file10L18-L30 fileciteturn3file17L9-L21

---

## 9.6 Operating expenses and rent

### 9.6.1 Monthly rent
Extract from labels such as:
- `Monthly Rent`
- `Basic Rent`
- `Rent`
- `Rental`

In the Tinygrad sample, monthly rent is `HK$15,015.00`. fileciteturn3file14L55-L59

### 9.6.2 Monthly management fee / AC charge
Extract from labels such as:
- `Monthly Management Fee`
- `Management Fee and Air-Conditioning Charge`
- `Service Charge`

In the Tinygrad sample, monthly management fee / AC charge is `HK$5,253.00`. fileciteturn3file14L55-L59

### 9.6.3 Government rates
The Tinygrad offer states `Rates per quarter: HK$2,775.00`. Convert quarterly rates to a monthly equivalent when the template requires monthly display. That yields `HK$925.00 per month`. fileciteturn3file14L55-L59

### 9.6.4 Government rent
If stated as `N/A`, keep `n/a` or leave blank according to workbook conventions.

### 9.6.5 Monthly rent psf
If rentable area is available, use formula:

```text
monthly_rent_psf = monthly_rent_hkd / rentable_area_sqft
```

If area is unavailable, leave psf blank and flag review.

### 9.6.6 Operating expense note
The workbook can show:
- management fee / AC monthly amount,
- date range,
- optional psf equivalent,
- optional rates / government rent note in adjacent lines if needed.

Because completed summary examples differ, the writer should preserve the workbook structure and populate only the cells already used by the selected template version.

---

## 9.7 Security deposit and advance rent

### 9.7.1 Security deposit amount
Extract the explicit deposit amount.

In the Tinygrad sample, security deposit is `HK$63,579.00`, and the document also states that it equals `3` times the highest monthly rent and other charges. fileciteturn3file5L23-L41

### 9.7.2 Security deposit note
Populate note text where useful, for example:
- `3 months highest monthly rent and other charges`
- deposit composition if formal summary style requires it

### 9.7.3 Advance rent
Use explicit wording from payment schedule if needed.

In the Tinygrad sample, the payments-on-signing schedule breaks out rent, management fee, rates, deposit, fit-out deposit and stamp duty. That can support advance-rent notes if the business wants them summarized. fileciteturn3file10L1-L26

---

## 9.8 Clause summary fields

These fields should be concise business summaries, not long verbatim clause dumps.

### 9.8.1 Signage
Extract whether signage is allowed, prohibited, or subject to landlord approval.

In the Tinygrad offer, signs visible from outside the premises require prior approval, and signage that is not of an appropriate standard can be required to be removed or replaced. fileciteturn3file12L18-L36

Suggested summary format:
- `Any external signage/display subject to landlord / building manager prior approval.`

### 9.8.2 Sub-letting
If the lease prohibits assignment, underletting, licensing or sharing possession, summarize that.

The Tinygrad offer prohibits transfer, assignment, underletting, licensing, sharing or otherwise parting with possession. fileciteturn3file11L18-L24

Suggested summary format:
- `No transfer, assignment, underletting, licensing or sharing of possession.`

### 9.8.3 Parking
Only populate if parking rights / car parks are expressly granted.
Otherwise write `n/a`.

### 9.8.4 Restoration obligations
Summarize yielding-up / reinstatement / handback obligations.

At minimum, if explicit restoration wording is not found but handover condition is stated and fit-out / landlord approval obligations exist, flag for review instead of inventing a restoration clause. The Tinygrad offer includes fit-out controls and landlord-approved contractor requirements, and references fit-out deposit and handover condition, but the exact final reinstatement wording should be confirmed from the tenancy agreement if not explicit in the offer. fileciteturn3file5L41-L59 fileciteturn3file11L23-L34

---

## 10. Extraction Method By Field Class

## 10.1 Rule-only fields

These should be handled deterministically in Python first:

- landlord name
- tenant name
- registered addresses
- premises address
- commencement date
- expiry date
- lease term months
- monthly rent
- management fee
- rates
- government rent
- security deposit amount
- landlord solicitor
- handover condition
- break clause
- rent free period

## 10.2 Rule + summarization fields

These require clause extraction plus concise summarization:

- signage
- sub-letting
- restoration obligations
- option to renew
- trigger date
- right of expansion
- tenant termination right
- parking

For the Python-first MVP, these can still be handled without LLM by:

1. locating the clause section,
2. applying clause-specific keywords,
3. generating a short standardized summary from template rules.

Example:

- detect `shall not transfer, assign, underlet, license, share or otherwise part with possession`
- map directly to standard summary text `No subletting / assignment / sharing of possession.`

---

## 11. Section Detection Rules

The parser should split source text using:

- numbered headings (`1.`, `2.`, `3.`)
- roman numerals (`(i)`, `(ii)`, `(iii)`)
- schedule headings (`SCHEDULE I`, `SCHEDULE II`, `ANNEXURE`)
- common clause names (`Rent`, `Security Deposit`, `User`, `Notice`, `Break Clause`)

This is especially useful because the Tinygrad offer separates principal commercial terms on the first pages and general / special conditions in schedules. fileciteturn3file14L1-L59 fileciteturn3file8L1-L29

---

## 12. Normalization Rules

### 12.1 Dates
Store internally as ISO:

- `YYYY-MM-DD`

Write to Excel using date objects with the workbook's display format.

### 12.2 Currency
Store numeric amounts as decimal-compatible floats or `Decimal`.

Examples:
- `HK$15,015.00` -> `15015.00`
- `HK$63,579.00` -> `63579.00`

### 12.3 Null handling
Use:

- `null` in JSON
- `n/a` in workbook text fields when the business convention is textual absence
- blank numeric cells when a numeric value is truly unavailable

### 12.4 Text normalization
Normalize:
- smart quotes
- broken line wraps
- OCR hyphenation
- full-width punctuation where needed
- duplicate spaces

---

## 13. Validation Rules

### 13.1 Mandatory checks

Flag review if any of the following is missing:

- tenant name
- landlord name
- premises address
- commencement date
- expiry date
- monthly rent

### 13.2 Cross-field consistency checks

- commencement date must be earlier than expiry date
- term months should reconcile with commencement and expiry within tolerance
- if security deposit multiple is present, amount should roughly reconcile
- if rates are quarterly and workbook needs monthly, conversion should be exact quarterly / 3
- if break clause is `N/A`, tenant termination right should normally be `n/a` unless another tenant termination clause exists

### 13.3 Example Tinygrad validation

For Tinygrad:
- commencement = `2026-02-11`
- expiry = `2028-02-10`
- rent = `15015.00`
- management fee = `5253.00`
- rates quarterly = `2775.00`
- security deposit = `63579.00`
- break clause = `N/A`

These values are internally consistent and support a clean first-pass summary. fileciteturn3file14L45-L59 fileciteturn3file5L1-L23 fileciteturn3file10L18-L26

---

## 14. Review Flags

Recommended review flags:

- `AREA_NOT_FOUND`
- `MULTIPLE_SIGNING_DATES`
- `TERM_COMPUTED_NOT_EXPLICIT`
- `DEPOSIT_COMPOSITION_NEEDS_CHECK`
- `CLAUSE_SUMMARY_LOW_CONFIDENCE`
- `OCR_USED`
- `PARKING_UNCLEAR`
- `RESTORATION_UNCLEAR`
- `RENEWAL_UNCLEAR`

Each flag should carry:

- field name
- reason
- evidence snippet
- page number

---

## 15. Excel Writing Rules

## 15.1 Preserve formatting
Do not rebuild the template from scratch.
Always start from a copy of `Opus Lease Summary Template - HK.xlsx`.

## 15.2 Label-driven writing
Resolve row positions by matching labels such as:

- `BUILDING ADDRESS`
- `LEASE SIGNING DATE`
- `LESSOR NAME / Landlord`
- `ACCOUNT NAME / Tenant`
- `LEASE TERM`
- `MONTHLY RENT`
- `SECURITY DEPOSIT`

## 15.3 Formula preservation
If the workbook already contains useful formulas, preserve them.
If the template cell is blank but the completed sample uses a formula, insert a formula rather than a hard-coded value where appropriate.

Example:

- monthly rent psf = total monthly rent / rentable area

## 15.4 Review highlighting
For fields requiring review, optionally add:

- cell comment,
- orange fill,
- or a review note in the JSON report.

---

## 16. Python Implementation Notes

## 16.1 Suggested libraries

- `pdfplumber` or `pymupdf` for PDF text extraction
- `pytesseract` only for scanned PDFs
- `re` for extraction rules
- `python-dateutil` for date parsing
- `openpyxl` for workbook writing
- `pydantic` or dataclasses for schema enforcement

## 16.2 Suggested extraction order

```python
extract_document_meta()
extract_parties()
extract_premises()
extract_term_dates()
extract_financials()
extract_clause_summaries()
validate_result()
write_excel()
write_json()
```

## 16.3 Suggested confidence scoring

- 1.00 = explicit labeled field
- 0.85 = inferred from nearby heading / table structure
- 0.70 = computed from two explicit fields
- 0.50 = clause summary from heuristic pattern
- below 0.50 = manual review required

---

## 17. Tinygrad Test Extraction Target

For the file `Offer to Lease_Hollywood Centre 1502 20260203.pdf`, the Python MVP should be able to extract the following immediately:

- landlord name: `Capital Faith (Hong Kong) Limited`
- tenant name: `Tinygrad HK Corp Limited`
- tenant registered address: `4002A Tower I, Lippo Centre, 89 Queensway Admiralty`
- premises: `15/F 02, Floor 15, Hollywood Centre, 233 Hollywood Road, Sheung Wan, Hong Kong`
- building: `Hollywood Centre`
- commencement: `2026-02-11`
- expiry: `2028-02-10`
- term: `24 months` (computed)
- monthly rent: `15015.00`
- management fee / AC charge: `5253.00`
- rates quarterly: `2775.00`
- government rent: `n/a`
- security deposit: `63579.00`
- deposit multiple: `3`
- landlord solicitor: `Woo, Kwan, Lee & Lo`
- user: `office premises`
- handover condition: `Standard Landlord Provision`
- rent free period: `28 days Rent Free from 11 February 2026 to 10 March 2026`
- fit-out deposit: `5000.00`
- break clause: `N/A`
- subletting summary: prohibited
- signage summary: landlord approval required

These fields are all supported by explicit text in the uploaded offer. fileciteturn3file14L1-L59 fileciteturn3file5L1-L59 fileciteturn3file10L1-L30 fileciteturn3file11L18-L34 fileciteturn3file12L18-L36

The likely weak point for first-pass automation is rentable area, because it is not visible in the extracted text snippet and may require a floor plan or manual input. That should be flagged rather than guessed.

---

## 18. MVP Acceptance Criteria

The MVP should be considered successful if it can:

1. process at least 5 historical sample lease / offer files,
2. populate all core commercial fields into the Opus template,
3. achieve strong accuracy on labeled financial and date fields,
4. clearly flag uncertain clause summary fields,
5. reduce manual summary drafting time materially.

Suggested first target:

- >95% accuracy on explicit labeled fields
- >80% acceptable accuracy on clause summary fields after staff review
- <10 minutes review time per lease after auto-draft

---

## 19. Phase Plan

### Phase 1: specification and mapping
- finalize workbook field mapping
- collect 5 to 10 sample leases and completed summaries
- lock review conventions (`blank` vs `n/a` vs note text)

### Phase 2: Python prototype
- PDF extraction
- field extractors
- JSON output
- Excel writer
- review flags

### Phase 3: testing
- run historical samples
- compare against manual summaries
- refine rules

### Phase 4: operations handoff
- document usage
- package as CLI or simple internal desktop workflow
- train staff review process

---

## 20. Final Recommendation

Build version 1 as a **Python document extraction and Excel population tool**.

Do not start with RAG.
Do not start with a chatbot.
Do not try to solve every lease clause in one pass.

Instead:

- extract explicit commercial fields deterministically,
- summarize a small number of clause fields with controlled rules,
- populate the existing workbook,
- require staff review only for flagged items.

That is the fastest route to a usable internal system and the most realistic path to replacing the current manual lease-summary drafting workflow.
