# Lease Summary Automation - Python-First Implementation Plan

## 1. Executive summary

This project does **not** need to start as a full RAG system.

Given the current workflow, a **Python-first document extraction pipeline** is the best first implementation:

1. Read `Offer to Lease`, `Lease`, or `Signed Lease` PDFs.
2. Extract the specific fields required by the lease summary template.
3. Normalize those values.
4. Write the values into the existing Excel lease summary template.
5. Produce a review version for staff to check before sending to the client.

A mixed approach is **optional**, not mandatory.

- **Phase 1 / MVP:** Python + PDF text extraction + rules + validation + Excel writing.
- **Phase 2:** add LLM extraction only for fields that remain inconsistent or hard to parse.
- **Phase 3:** add searchable archive / review UI / batch processing if needed.

So the right framing is:

- **Implementation language:** Python
- **Initial extraction method:** deterministic parsing first
- **LLM use:** only where rules are not reliable enough

---

## 2. Why Python alone is enough to start

The current task is not open-ended summarization. It is a **fixed-template abstraction workflow**.

The target output is a structured lease summary spreadsheet with recurring fields such as:

- landlord / lessor
- tenant name
- building address
- premises
- signing date
- commencement date
- expiry date
- term
- monthly rent
- operating expenses
- security deposit
- advance rent
- subletting
- parking
- restoration obligations
- signage
- termination rights
- option to renew

That means the core system is really:

**document extraction -> field mapping -> template population**

not:

**chatbot -> generic Q&A -> free-form summary**

This also matches the test `Offer to Lease_Hollywood Centre 1502 20260203.pdf`, which presents a large number of required summary values in a fairly explicit form, including landlord, tenant, premises, term commencement and expiry, monthly rent, management fee, quarterly rates, security deposit, landlord's solicitors, user, handover condition, rent free period, fit-out deposit and break clause. fileciteturn1file4 fileciteturn1file1 fileciteturn1file5

---

## 3. Recommended delivery strategy

### Recommendation
Build a **Python-first MVP** now, with this design principle:

> Prefer deterministic extraction wherever possible. Use LLM only where the source wording is too variable to handle safely with rules.

### Why this is the best starting point

- Easier to explain to the client
- Faster to deliver
- Lower operating cost
- Easier to debug when staff find an issue
- Better fit for fixed Excel output
- Easier to audit against source document text

### When LLM becomes worth adding

LLM becomes useful later for fields like:

- signage rights
n- restoration obligations
- tenant termination right
- option to renew details
- expansion rights
- complex operating expense wording
- special conditions that modify the main lease

These are the fields most likely to be phrased differently from one landlord form to another.

---

## 4. Scope of documents to support

The workflow should explicitly support three input classes:

1. **Offer to Lease**
2. **Lease / Tenancy Agreement**
3. **Signed Lease / signed package with deposits or schedules**

The system should not assume that all three document types have the same layout.

Instead, it should:

- detect document type from title / keywords / first page
- run a document-type-specific extraction profile
- then map the results into one common internal schema

### Practical rule

If multiple files exist for the same transaction:

- newest signed lease should override earlier offer terms where they conflict
- offer-to-lease data can be used to fill missing fields if final signed lease is unavailable
- every output field should retain a source reference showing which document supplied the value

---

## 5. Proposed system architecture

## 5.1 High-level pipeline

```text
Input PDF(s)
   -> document classifier
   -> PDF text extraction / OCR
   -> section splitter
   -> field extractors
   -> normalizer
   -> validation engine
   -> Excel template writer
   -> review output (xlsx + JSON + QA flags)
```

## 5.2 Core modules

### A. `ingest/`
Responsible for:
- loading files
- identifying PDF type
- naming transaction / company
- choosing extraction profile

### B. `pdf_extract/`
Responsible for:
- extracting text from machine-readable PDFs
- OCR fallback for scans
- preserving page numbers
- preserving line blocks where possible

### C. `segment/`
Responsible for:
- splitting into pages
- finding section headings
- identifying key blocks such as:
  - premises
  - term
  - rent
  - deposit
  - special conditions
  - options
  - notices

### D. `extractors/`
Responsible for field-level extraction.
Each field should have an explicit extractor function.

Examples:
- `extract_landlord_name()`
- `extract_tenant_name()`
- `extract_premises()`
- `extract_term_dates()`
- `extract_monthly_rent()`
- `extract_operating_expenses()`
- `extract_security_deposit()`
- `extract_option_to_renew()`
- `extract_termination_right()`
- `extract_subletting()`

### E. `normalize/`
Responsible for:
- date formatting
- money cleanup
- unit cleanup
- `n/a` normalization
- yes/no and free-text consistency

### F. `validate/`
Responsible for business checks.

Examples:
- expiry date must be after commencement date
- lease term months should match date span when available
- deposit should be numeric or clearly `n/a`
- rent-free period should not overlap beyond the term
- if break clause is `n/a`, no trigger date should be populated

### G. `template_writer/`
Responsible for:
- loading the Excel template
- populating cells
- preserving formatting
- writing a completed review workbook

### H. `review/`
Responsible for:
- confidence flags
- unresolved fields list
- source evidence export
- optional side-by-side QA sheet

---

## 6. Internal data model

Use a structured JSON object as the system-of-record before writing to Excel.

```json
{
  "document_meta": {
    "document_type": "offer_to_lease",
    "source_files": [],
    "entity_name": "",
    "extraction_timestamp": ""
  },
  "parties": {
    "landlord_name": null,
    "landlord_address": null,
    "tenant_name": null,
    "tenant_address": null
  },
  "premises": {
    "building_address": null,
    "suite_floor": null,
    "rentable_area_sqft": null,
    "net_area_sqft": null,
    "efficiency_basis": null,
    "comments": null
  },
  "term": {
    "lease_signing_date": null,
    "scheduled_commencement_date": null,
    "lease_commencement_date": null,
    "lease_expiry_date": null,
    "lease_term_months": null,
    "rent_free_period": null,
    "fit_out_period": null
  },
  "economics": {
    "monthly_rent": null,
    "rent_schedule": [],
    "management_fee": null,
    "aircon_fee": null,
    "rates": null,
    "government_rent": null,
    "security_deposit": null,
    "advance_rent": null,
    "fit_out_deposit": null,
    "operating_expenses_notes": null
  },
  "rights": {
    "option_to_renew": null,
    "trigger_date": null,
    "termination_right": null,
    "right_of_expansion": null,
    "subletting": null,
    "parking": null,
    "signage": null,
    "restoration_obligations": null
  },
  "evidence": {
    "landlord_name": {"value": null, "page": null, "quote": null, "confidence": null},
    "tenant_name": {"value": null, "page": null, "quote": null, "confidence": null}
  },
  "qa": {
    "review_required": false,
    "warnings": [],
    "missing_fields": []
  }
}
```

This JSON layer is important because it separates:

- extraction logic
- review logic
- Excel output logic

---

## 7. Extraction strategy by field

## 7.1 Tier 1 - deterministic fields

These should be handled in Python first using rules / regex / block parsing.

### Typical Tier 1 fields
- landlord name
- tenant name
- premises
- building address
- lease signing date
- scheduled commencement date
- lease commencement date
- lease expiry date
- lease term
- monthly rent
- management fee
- rates
- government rent
- security deposit
- advance rent
- fit-out deposit
- break clause if explicitly stated as `N/A` or as a named item

The Tinygrad offer shows exactly this kind of extractable structure, with individually labeled items for landlord, tenant, premises, term commencement date, term expiry date, monthly rent, management fee, rates, security deposit, solicitor, user, handover condition, rent free period, fit-out deposit and break clause. fileciteturn1file4 fileciteturn1file9 fileciteturn1file11

### Techniques
- heading anchors
- regex with nearby line capture
- block extraction using numbered clauses
- date parsers
- currency normalizers
- page-aware extraction

## 7.2 Tier 2 - semi-structured fields

These are still doable in Python, but often need more heuristics and section-aware parsing.

### Typical Tier 2 fields
- operating expenses note
- rent free period wording
- fit-out period wording
- subletting clause summary
- signage clause summary
- restoration obligations
- parking rights
- user restrictions

For example, the Tinygrad offer contains explicit user wording and multiple general terms that could be summarized into staff-review text for signage, subletting, fit-out and insurance-related obligations. fileciteturn1file9 fileciteturn1file12 fileciteturn1file13 fileciteturn1file14

### Techniques
- search specific sections by keyword groups
- extract paragraph windows
- apply clause templates
- return short summaries plus source quotes

## 7.3 Tier 3 - LLM candidates (optional later)

Only add these if staff review shows Python rules are not enough.

### Typical Tier 3 fields
- option to renew details
- trigger date logic
- tenant termination right
- unusual special conditions
- conflicts between schedule and body text
- amendment overrides

### Rule for using LLM later

Never let an LLM write directly to Excel.

Instead:
1. LLM reads only the relevant section text.
2. LLM outputs strict JSON.
3. Python validates the result.
4. Excel writer fills the sheet.

---

## 8. Excel template population design

The Excel template should remain the final client-facing deliverable.

### Rules
- preserve formatting exactly
- write only into mapped content cells
- do not overwrite static disclaimer text
- keep formulas intact where already present
- add a review marker where values are inferred or uncertain

### Suggested mapping asset
Create a separate configuration file such as:

```yaml
account_name:
  sheet: Lease Summary
  cell: D9
building_address:
  sheet: Lease Summary
  cell: E12
lease_signing_date:
  sheet: Lease Summary
  cell: E14
scheduled_commencement_date:
  sheet: Lease Summary
  cell: E16
landlord_name:
  sheet: Lease Summary
  cell: E18
tenant_name:
  sheet: Lease Summary
  cell: E20
rentable_area_sqft:
  sheet: Lease Summary
  cell: G22
lease_term_months:
  sheet: Lease Summary
  cell: E24
lease_commencement_date:
  sheet: Lease Summary
  cell: E26
lease_expiry_date:
  sheet: Lease Summary
  cell: E28
option_to_renew:
  sheet: Lease Summary
  cell: E30
```

The exact mapping file should be completed after one pass through the template and the two historical example summaries.

---

## 9. Validation and human review

Human review should stay in the workflow.

The goal is not fully autonomous legal abstraction on day one.
The goal is to reduce staff effort from “read everything and draft from scratch” to “review and correct an already populated summary.”

## 9.1 Required validation checks

### Date checks
- lease signing date valid
- commencement valid
- expiry valid
- expiry > commencement
- stated lease term consistent with dates if possible

### Financial checks
- amounts parse to currency
- deposit is not negative
- monthly rent and rent schedule are consistent
- rates / management fee do not get swapped accidentally

### Logical checks
- trigger date should not be filled if no renewal / break right is found
- if break clause is `N/A`, termination-right details should not appear unless clearly from another clause
- if `government rent` is `N/A`, leave empty or `n/a` consistently

### Output checks
- no placeholder text left in final cells
- no merged-cell formatting broken
- all required client-facing fields filled or flagged

## 9.2 Review outputs

The system should generate:

1. completed Excel workbook
2. JSON extraction file
3. QA report listing:
   - missing fields
   - low-confidence fields
   - source pages
   - warnings

---

## 10. Recommended folder structure

```text
lease_summary_project/
  data/
    input/
    output/
    samples/
  config/
    field_map.yaml
    extraction_profiles.yaml
  src/
    main.py
    ingest.py
    pdf_extract.py
    ocr.py
    segment.py
    normalizers.py
    validators.py
    excel_writer.py
    review_report.py
    extractors/
      parties.py
      premises.py
      term.py
      economics.py
      rights.py
  tests/
    test_extractors.py
    test_validators.py
  docs/
    implementation_plan.md
    field_mapping.md
```

---

## 11. Suggested Python stack

### Core
- `python 3.11+`
- `pdfplumber` or `pymupdf` for PDF text extraction
- `openpyxl` for Excel template population
- `pydantic` or `dataclasses` for schema validation
- `python-dateutil` for date parsing
- `rapidfuzz` for tolerant label matching

### OCR fallback
- `ocrmypdf` or `tesseract`

### Optional later
- `langchain` or direct model SDK only if LLM support is added later
- vector DB only if document search becomes a later requirement

---

## 12. Proposed implementation phases

## Phase 1 - MVP (recommended immediately)

### Objective
Automate the majority of template completion for common offer / lease documents using Python only.

### Deliverables
- ingest single PDF
- extract core fields
- populate lease summary template
- export completed workbook
- export QA notes

### MVP fields
- account / tenant name
- landlord name
- premises / address
- signing date
- commencement date
- expiry date
- term months
- monthly rent
- management fee / aircon
- rates
- government rent
- security deposit
- advance rent
- rent free period
- break clause
- user

### Success criterion
Staff should be able to review the generated summary in a few minutes instead of drafting manually from the raw lease.

## Phase 2 - accuracy hardening

### Add
- OCR support for scanned leases
- better section parsing
- clause summarization for subletting / signage / restoration
- more template fields
- richer QA checks

## Phase 3 - selective AI augmentation

### Add only if needed
- LLM for ambiguous clause extraction
- amendment conflict detection
- comparison between offer and signed lease
- staff review assistant

---

## 13. Implementation checklist

## 13.1 Discovery
- [ ] confirm every input file type to support
- [ ] confirm all template fields that must be filled
- [ ] collect 5 to 10 example leases plus completed summaries
- [ ] define which fields are mandatory vs optional
- [ ] define expected `n/a` handling

## 13.2 Engineering
- [ ] build PDF extractor
- [ ] build field schema
- [ ] build field extractors
- [ ] build normalizers
- [ ] build validators
- [ ] build Excel writer
- [ ] build QA export

## 13.3 Testing
- [ ] test on Tinygrad offer
- [ ] compare against completed JS Gale summary
- [ ] compare against completed KLDiscovery summary
- [ ] measure field accuracy
- [ ] refine extraction rules by field

---

## 14. Test case: Tinygrad HK Corp Limited

The file `Offer to Lease_Hollywood Centre 1502 20260203.pdf` is a good MVP test because it already exposes many template fields clearly.

### Readily extractable candidate fields
- landlord: Capital Faith (Hong Kong) Limited fileciteturn1file4
- tenant: Tinygrad HK Corp Limited fileciteturn1file4
- premises: 15/F 02, Floor 15, Hollywood Centre, 233 Hollywood Road, Sheung Wan, Hong Kong fileciteturn1file4
- term commencement date: 11 February 2026 fileciteturn1file4
- term expiry date: 10 February 2028 fileciteturn1file4
- monthly rent: HK$15,015.00 fileciteturn1file4
- monthly management fee / air-conditioning charge: HK$5,253.00 fileciteturn1file4
- rates per quarter: HK$2,775.00 fileciteturn1file4
- government rent per quarter: N/A fileciteturn1file4
- security deposit: HK$63,579.00 fileciteturn1file1
- landlord's solicitors: Woo, Kwan, Lee & Lo fileciteturn1file1
- user: office premises only fileciteturn1file1
- handover condition: Standard Landlord Provision fileciteturn1file1
- rent free period: 28 days from 11 February 2026 to 10 March 2026 fileciteturn1file1
- fit-out deposit: HK$5,000.00 fileciteturn1file5
- break clause: N/A fileciteturn1file5

### Why it is a strong first test
- front pages are highly labeled
- financial items are itemized
- there is a clear distinction between summary particulars and standard conditions
- it lets us test both exact extraction and section-aware extraction

---

## 15. Risks and mitigations

## Risk 1: scanned PDFs
**Mitigation:** add OCR fallback early.

## Risk 2: landlord templates vary
**Mitigation:** create per-document-type extraction profiles and add field-specific synonyms.

## Risk 3: ambiguous clause summaries
**Mitigation:** keep staff review mandatory and add source quotes.

## Risk 4: final lease differs from offer
**Mitigation:** record source file priority and allow override logic.

## Risk 5: template drift
**Mitigation:** keep field-to-cell mapping in config, not hardcoded everywhere.

---

## 16. Recommended answer to the client

A practical answer to the client would be:

> Yes. We can build a Python-based workflow that scans the lease or offer document, extracts the information required for the lease summary, inserts it into the existing lease summary template, and produces a review copy for staff to check before it is sent to the client. We suggest starting with a Python-first MVP using deterministic extraction and validation, then adding AI only for fields that remain difficult to extract consistently.

That answer is honest, implementable, and avoids over-promising a fully autonomous AI legal abstraction engine on day one.

---

## 17. Final recommendation

### Recommended build path

**Start with Python only.**

Do not make “hybrid AI” a requirement for the first version.

The first version should be:

- Python-based
- field-driven
- Excel-template-driven
- auditable
- reviewable by staff

### Best implementation sequence

1. map all template fields
2. build PDF text extraction
3. build deterministic field extractors
4. build Excel writer
5. build QA report
6. test on Tinygrad and historical samples
7. only then decide whether any field truly needs LLM support

This will give the fastest route to a production-worthy internal workflow.
