
# Lease Summary Automation Plan

## Objective

Build a semi-automated workflow that:

1. reads an **Offer to Lease / Lease / Signed Lease** PDF,
2. extracts the fixed fields required by the **Opus Lease Summary Template - HK.xlsx**,
3. writes the values into the summary template,
4. attaches evidence and confidence flags for staff review,
5. outputs a client-ready lease summary after a quick human check.

This is **not** primarily a RAG/Q&A problem.
It is a **document extraction + normalization + template population** workflow.

---

## 1) Recommended approach

### Recommended stack
Use a **hybrid extraction pipeline**:

- **PDF/OCR parsing** for source ingestion
- **Rule-based extraction** for stable fields
- **LLM extraction** for clause-like or non-standard fields
- **Validation layer** for date / money / term checks
- **Excel writer** to populate the lease summary template

### Why this approach
A pure regex approach will fail once lease wording varies.
A pure RAG approach is too loose for fixed-template output.

The best fit is:

- **Rules first** for dates, amounts, names, addresses, term, deposit, rent
- **LLM second** for narrative clauses like:
  - option to renew
  - termination rights
  - signage
  - subletting
  - restoration obligations
  - parking
  - trigger dates
- **Human review last** for only flagged/low-confidence fields

---

## 2) What the system should do

### Input
Supported source documents:

- Offer to Lease
- Lease
- Lease signed / signed lease
- scanned PDFs
- native text PDFs

### Output
Populate the fixed summary workbook based on **Opus Lease Summary Template - HK.xlsx**.

The template is essentially asking for a fixed set of summary fields such as:

- company / tenant name
- address
- building address
- lease signing date
- scheduled commencement date
- landlord
- premises details
- lease term
- lease commencement / expiry
- option to renew
- trigger date
- right of expansion
- fit-out period
- signage
- operating expenses
- tenant termination right
- monthly rent schedule
- security deposit
- advance rent
- sub-letting
- parking
- restoration obligations

---

## 3) Workflow design

## Stage A — Intake and document classification

For each uploaded document:

1. Detect file type:
   - native PDF
   - scanned PDF
   - image-heavy PDF
2. Classify document:
   - offer to lease
   - signed lease
   - formal lease / tenancy agreement
3. Assign:
   - `document_type`
   - `tenant_name`
   - `property_name`
   - `file_id / filename`

### Notes
- “Offer to Lease” and “Lease” often contain overlapping information.
- If multiple documents exist for the same deal, later signed documents should usually override earlier offer terms **where explicitly inconsistent**.
- Amendment logic should be added in phase 2.

---

## Stage B — Text extraction and structural parsing

### For native PDFs
Use direct PDF text extraction first.

### For scans
Use OCR.

### Preserve structure
The parser should keep:

- page number
- section heading
- paragraph text
- table-like blocks
- source filename

### Internal representation
Convert each document to a normalized structure such as:

```json
{
  "filename": "Offer to Lease_Hollywood Centre 1502 20260203.pdf",
  "document_type": "offer_to_lease",
  "pages": [
    {
      "page": 1,
      "blocks": [
        {
          "section": "header",
          "text": "..."
        }
      ]
    }
  ]
}
```

---

## Stage C — Field-by-field extraction

Do **not** ask one model call to fill the whole summary in one shot.

Instead, use **field-specific extractors**.

### Tier 1 — rule-dominant fields
These should be extracted by pattern/anchor rules first, with LLM fallback only if needed:

- landlord name
- tenant name
- premises / address
- building name
- lease signing date
- term commencement date
- term expiry date
- term length
- monthly rent
- management fee / air-conditioning charge
- rates
- government rent
- security deposit
- fit-out deposit
- rent free period
- landlord solicitor

### Tier 2 — LLM-assisted clause fields
These should use targeted section retrieval plus structured extraction:

- option to renew
- trigger date
- right of expansion
- fit-out period
- signage
- operating expenses summary
- tenant termination right
- sub-letting
- parking
- restoration obligations
- break clause

### Extraction rule
Every extracted field should return:

```json
{
  "value": "...",
  "confidence": 0.0,
  "evidence": "...",
  "page": 1,
  "source_file": "..."
}
```

If unknown:

```json
{
  "value": null,
  "confidence": 0.0,
  "evidence": null,
  "page": null,
  "source_file": "..."
}
```

---

## 4) Data model

A recommended intermediate JSON schema:

```json
{
  "meta": {
    "source_documents": [],
    "primary_document_type": "",
    "tenant_name": "",
    "landlord_name": "",
    "property_name": ""
  },
  "summary": {
    "company_name": "",
    "opportunity_name": "",
    "opportunity_owner": "",
    "opportunity_office": "Hong Kong",
    "property_type": "Office",
    "account_name": "",
    "address": "",
    "building_address": "",
    "lease_signing_date": "",
    "scheduled_commencement_date": "",
    "lessor_name": "",
    "tenant_name": "",
    "premises_floor_and_size": {
      "rentable_area_sqft": null,
      "size_comment": "",
      "efficiency_basis": ""
    },
    "lease_term_months": null,
    "lease_commencement_date": "",
    "lease_expiry_date": "",
    "option_to_renew": "",
    "trigger_date": "",
    "right_of_expansion": "",
    "fit_out_period": "",
    "signage": "",
    "operating_expenses": {
      "description": "",
      "from_date": "",
      "to_date": "",
      "amount_hkd_per_month": null,
      "amount_hkd_per_sqft": null
    },
    "tenant_termination_right": "",
    "monthly_rent_schedule": [],
    "security_deposit": "",
    "advance_rent": "",
    "sub_letting": "",
    "parking": "",
    "restoration_obligations": ""
  },
  "review": {
    "needs_review": false,
    "warnings": []
  }
}
```

---

## 5) Mapping logic to the Excel template

The safest implementation pattern is:

1. extract into **JSON first**
2. validate JSON
3. map JSON to fixed Excel cells
4. save a filled summary workbook
5. optionally save a sidecar QA sheet

### Why
This makes the process debuggable.
If something looks wrong in Excel, staff can inspect the JSON and evidence instead of re-reading the full lease from scratch.

### Recommended workbook outputs
For each lease package, generate:

- `Lease Summary - Draft.xlsx`
- `Lease Summary - Review Notes.xlsx` or a hidden QA sheet
- optional JSON archive:
  - `Lease Summary - Extracted.json`

### Optional QA tab
Add a second worksheet:

- field name
- extracted value
- confidence
- source quote
- page
- source file
- review status

This will make staff review much faster.

---

## 6) Validation rules

Before writing the final workbook, run checks such as:

### Date logic
- commencement date <= expiry date
- scheduled commencement date should usually match or precede lease commencement
- lease term months should roughly align with commencement/expiry dates

### Money logic
- security deposit should be numeric or explicitly marked narrative
- monthly rent should be numeric
- management fee / rates should have units

### Completeness logic
Flag if any key field is missing:

- tenant
- landlord
- premises
- commencement
- expiry
- rent
- deposit

### Consistency logic
- if “Option to Renew” is N/A, trigger date should usually be N/A
- if fit-out deposit appears, fit-out period may need review
- if rates or government rent are listed separately, operating expenses should not be blank

### Review rule
Mark `needs_review = true` if:
- field confidence below threshold
- conflicting values from multiple documents
- scanned/OCR quality is poor
- one of the key fields is missing

---

## 7) Human-in-the-loop review workflow

### Proposed staff process
1. Upload original lease / offer / signed lease
2. Run extraction job
3. System produces:
   - filled lease summary template
   - QA review tab
4. Staff checks only flagged fields
5. Staff approves and sends to client

### Expected benefit
This turns a full manual review into a **targeted exception review**.

Instead of re-reading a whole lease, staff only verify:
- low-confidence fields
- legal clauses
- non-standard commercial points

---

## 8) MVP scope

### MVP goal
Support the most common HK office leases and offers with a usable review-first workflow.

### MVP document types
- native PDFs
- scanned PDFs (OCR)
- single-source document first
- later support multi-document bundles

### MVP fields
Start with these highest-value fields:

1. tenant name
2. landlord name
3. premises / address
4. lease signing date
5. scheduled commencement date
6. lease commencement date
7. lease expiry date
8. lease term
9. monthly rent
10. management fee / AC charge
11. rates
12. government rent
13. security deposit
14. rent free period
15. fit-out deposit / advance rent
16. option to renew
17. break / termination right
18. subletting
19. restoration obligations
20. signage / parking

### MVP operating model
- fully automated extraction
- mandatory human check before client delivery

---

## 9) Phase 2 enhancements

After MVP works, add:

### Multi-document package handling
Combine:
- offer to lease
- signed lease
- lease agreement
- side letters
- amendments

### Conflict resolution
Document priority example:
1. signed lease / amendment
2. tenancy agreement
3. offer to lease

### Better table extraction
Useful for:
- stepped rent schedules
- service charge tables
- deposit breakdowns

### Training set
Build a small ground-truth library:
- 20–50 leases
- corresponding completed summaries
- field-by-field expected output

This can be used for:
- prompt tuning
- regression tests
- QA scoring

---

## 10) Suggested technical architecture

### Option A — Fast private deployment
- Python
- PDF parser + OCR
- rule engine
- LLM API
- Excel writer (`openpyxl`)
- local/shared-folder batch runner

### Option B — Production workflow
- upload queue
- document store
- extraction service
- review UI
- audit trail
- template output service

### Recommendation
For this engagement, start with **Option A** and keep it simple.

---

## 11) Implementation plan

## Week 1 — Discovery and field mapping
- review 5–10 sample leases
- compare against completed summaries
- finalize field dictionary
- define document priority rules
- define Excel cell mapping

## Week 2 — Extraction prototype
- build parser
- build Tier 1 rule extractors
- build Tier 2 LLM prompts
- produce intermediate JSON
- output first draft Excel

## Week 3 — Validation and QA
- add confidence scoring
- add review sheet
- test on 10–20 historical files
- measure precision / recall by field

## Week 4 — Pilot
- run on live files
- collect staff corrections
- improve rules/prompts
- stabilize before wider rollout

---

## 12) Proposed prompt strategy

### A. Field extractor prompt
Use targeted prompts like:

> Extract the lease commencement date from the provided lease text.
> Return JSON only with:
> - value
> - confidence
> - evidence
> - page
> If not explicitly stated, return null.

### B. Clause summarizer prompt
For complex fields:

> Review only the provided clause text and summarize the tenant’s subletting rights for a lease summary template.
> Return concise business language, no legal essay, and state N/A if no right is granted.

### C. Normalizer prompt
For rent schedules:

> Convert the extracted rent schedule into a normalized list of yearly rent periods with start date, end date, annual rent and notes.

---

## 13) Tinygrad test case — initial extraction from the uploaded offer

Using **Offer to Lease_Hollywood Centre 1502 20260203.pdf**, the following core fields are already extractable from the offer:

- Landlord: **Capital Faith (Hong Kong) Limited**
- Tenant: **Tinygrad HK Corp Limited**
- Premises: **15/F 02, Floor 15, Hollywood Centre, 233 Hollywood Road, Sheung Wan, Hong Kong**
- Term commencement date: **11 February 2026**
- Term expiry date: **10 February 2028**
- Monthly rent: **HK$15,015.00**
- Monthly management fee / air-conditioning charge: **HK$5,253.00**
- Rates per quarter: **HK$2,775.00**
- Security deposit: **HK$63,579.00**
- User: **office premises**
- Rent free period: **28 days from 11 February 2026 to 10 March 2026**
- Break clause: **N/A**
- Fit-out deposit: **HK$5,000.00**
- Landlord’s solicitors: **Woo, Kwan, Lee & Lo**

This is a good candidate for a first end-to-end test because the source document is already well-structured.

---

## 14) What should be built first

### Build first
- parser
- JSON extractor
- Excel population script
- review tab
- field confidence flags

### Do not build first
- full semantic search / RAG chatbot
- generalized knowledge base
- sophisticated UI
- amendment resolution engine
- automated email delivery

---

## 15) Recommended deliverables

1. **Field dictionary**
2. **Excel cell mapping spec**
3. **Python extraction prototype**
4. **QA review workbook**
5. **Test results on sample files**
6. **Operations guide for staff**

---

## 16) Bottom-line recommendation

Yes — this is very feasible.

The right solution is **not** “ask AI to summarize leases generally.”
The right solution is a **fixed-template lease abstraction workflow**:

- read lease documents
- extract fixed commercial/legal fields
- write to the summary template
- attach evidence/confidence
- let staff review exceptions only

That will save time, reduce manual data entry, and still keep human control before anything is sent to the client.
