# USDA Organic Recordkeeping Corpus — Frozen Reference

**Purpose.** Frozen, reproducible source corpus for the USDA records-alignment audit (P0 of the
organic-recordkeeping alignment plan). Every later phase (form inventory, crosswalk, live proof)
cites *this* corpus by file + line, never a live URL — so the audit is reviewable months later and
does not silently drift when AMS re-publishes a PDF.

**Retrieved:** 2026-08-10
**Index page:** https://www.ams.usda.gov/services/organic-certification/organic-records
(AMS returns HTTP 403 to non-browser agents; the page itself was read via `r.jina.ai`, the PDFs
download fine over `curl` with a browser User-Agent.)

---

## 🔴 Two caveats that constrain every conclusion drawn from this corpus

**1. The forms are explicitly optional.** Every one of the 25 pages of
`NOP-CropDocumentationForms.pdf` carries this running footer, verbatim:

> `Documentation Forms for Organic Crop Producers   March 2011   Optional form, not mandated by regulation`

They are authored by **Ann Baier, NCAT/ATTRA** and *published by* AMS. USDA says on every page that
no operation is required to use them.

- SAFE: "modeled on USDA-published documentation forms", "covers the record areas USDA's own crop
  forms track"
- UNSAFE: "USDA-approved records", "USDA-verified recordkeeping", "the required USDA forms"
- The binding requirement is **§ 205.103**. The form is evidence of *how USDA expects a record to
  look*, never the authority. Same discipline as `record_completeness.py`: no required field
  without a real citation.

**2. The forms are dated March 2011 — twelve years before SOE.** `March 2011` is the only date
appearing anywhere in the publication. But § 205.103 was amended at **88 FR 3621, Jan. 19, 2023**
(Strengthening Organic Enforcement). The 2011 forms cannot reflect it.

⚠️ **Therefore 100% alignment to these forms does not equal current compliance.** The crosswalk must
be scored against **two** baselines, and a row may pass one and fail the other:
- **Baseline A — the 2011 forms:** does Trazo capture what USDA's own templates capture?
- **Baseline B — § 205.103 as amended (2023):** does Trazo satisfy the current regulation, including
  anything SOE added that no 2011 form has a column for?

Baseline B is the one a certifier enforces in 2026. Do not let a clean Baseline A score be reported
as compliance.

---

## Scope boundary

The AMS index page lists **15 PDFs** across 4 content sections (Certification, Organic System Plans,
Recordkeeping, Livestock Feed) plus one non-PDF link to the OSP template page.

**11 of the 15 are excluded** — 10 livestock / dry-matter-intake, 1 processor. Trazo's ICP is
wholesale tree-nut and orchard crops; pulling them in would inflate the crosswalk denominator with
rows that can only ever be `N/A-scope`.

Excluded on purpose (recorded so the omission is visible, not silent):
`Guide-OrganicLivestockProducers.pdf`, `Guide-OrganiceProcessors.pdf`,
`NOP-LivestockDocumentationForms.pdf`, `5017-1.pdf`, `NOP-5017-2/-3/-4/-5/-6/-7`,
`NOP-UnderstandingOrganicPastureRule.pdf`.

Also not re-pulled: the **OSP template page**
(https://www.ams.usda.gov/reports/organic-system-plan-template) — already audited against the
federal Common OSP, 19 modules, see `osp-parity-qa-2026-08-09`.

---

## Sources

| File | Pages | SHA-256 | Source URL |
|---|---|---|---|
| `pdf/NOP-CropDocumentationForms.pdf` | 25 | `246121457faaa2130eae8251cc86e907ff9bba19569da876ab1b82a527aa5766` | https://www.ams.usda.gov/sites/default/files/media/NOP-CropDocumentationForms.pdf |
| `pdf/NOP-DocumentationFormsIntro.pdf` | 8 | `697c5a0807aff96c3fa56904273288ea3f4670ba2868348ef5437030eb13b250` | https://www.ams.usda.gov/sites/default/files/media/NOP-DocumentationFormsIntro.pdf |
| `pdf/GuideForOrganicCropProducers.pdf` | 64 | `c4d3623db5775a982e5a163ca31ccb6786ca4c7c1911311ed0d969596c393d7e` | https://www.ams.usda.gov/sites/default/files/media/GuideForOrganicCropProducers.pdf |
| `pdf/Guide-OrganicCertification.pdf` | 8 | `ef60de1e0fab7f0edaa8da1cdd20591a6399c6a16f091f45e3d24f004e7230c3` | https://www.ams.usda.gov/sites/default/files/media/Guide-OrganicCertification.pdf |
| `cfr/title-7-part-205_2026-08-05.xml` | 106 sections | `090c5fc32216ffac5d3bc46669a96542aa802d47af374b102d2d8de744a2d3b9` | eCFR API, `versioner/v1/full/2026-08-05/title-7.xml?chapter=I&subchapter=M&part=205` |

`txt/*.txt` are `pdftotext -layout` renderings of the PDFs above (layout preserved — the forms are
tables, and column structure is what the crosswalk reads). `cfr/*.txt` is a tag-stripped rendering
of the XML. Text files are derived artifacts; the PDF/XML hashes are the provenance.

**Extraction quality:** all 25 form pages produced 461–2514 chars of text; no image-only pages, no
OCR needed. (A 26th split element after the final form feed is empty and is not a page.)

**eCFR currency:** title 7 `latest_amended_on` 2026-08-03, `latest_issue_date` 2026-08-05,
`up_to_date_as_of` 2026-08-07. Requesting 2026-08-10 returns 404 — the API rejects dates past the
title's most recent issue date. Re-pull before the December verdict gate and diff.

---

## § 205.103 — the actual obligation

Full text at `cfr/title-7-part-205_2026-08-05.txt`. The operative clauses the crosswalk scores
against:

- **(b)(1)** adapted to the particular business
- **(b)(2)** fully disclose all activities and transactions, "in sufficient detail as to be readily
  understood and audited"; **must span purchase/acquisition → production → sale or transport, and
  be traceable back to the last certified operation**
- **(b)(3)** audit-trail documentation, products identified by their organic label category
- **(b)(4)** retained **≥ 5 years**
- **(b)(5)** sufficient to demonstrate compliance
- **(c)** available for inspection and copying by the Secretary, State official, and certifying agent

Citation line: `[65 FR 80637, Dec. 21, 2000, as amended at 88 FR 3621, Jan. 19, 2023]`.

(b)(2)'s span clause and (b)(4)'s 5-year floor are the two most likely product-level gaps and must
be scored as their own rows, not folded into any form row — no 2011 form has a column for either.

---

## Form inventory — `NOP-CropDocumentationForms.pdf` (25 crop forms)

Authoritative list and section groupings taken from the **"Included Forms"** enumeration in
`txt/NOP-DocumentationFormsIntro.txt:219-338` (that intro is shared by the crop *and* livestock
publications; only its Crops half applies here). Line anchors are into
`txt/NOP-CropDocumentationForms.txt`.

**Citations in the "Reg hooks (per intro)" column are quoted from the intro's own section headers —
they are not Trazo inferences.** Where the intro cites only at group level, the column shows the
group-level cite; narrowing it to a subsection (e.g. § 205.203(c) for compost) is a P1 judgement and
must be recorded as such.

Where the form's own heading differs from the intro's name for it, both are shown — the crosswalk
keys on the PDF heading.

### Land Use Records — *NOP § 205.202 Land Requirements*
| # | Form (PDF heading) | txt line |
|---|---|---|
| 1 | Field History / Previous Land Use Record | 2 |
| 2 | Land Use History Verification | 46 |

### Activity Records — *§ 205.2 (Records, Crop Rotation); § 205.103; § 205.201*
| # | Form | txt line |
|---|---|---|
| 3 | Activity Log | 76 |
| 4 | Activity Calendar | 90 |

### Planting and Harvest and Crop Rotation Records — *§ 205.2 (Crop Rotation); § 205.205*
| # | Form | txt line |
|---|---|---|
| 5 | Planting and Harvest Record | 125 |
| 6 | Crop Rotation Record | 140 |

### Input Material Records — *§ 205.2 (Agricultural Input, Compost); § 205.203; § 205.205; § 205.601; § 205.602*
| # | Form | txt line |
|---|---|---|
| 7 | Input Material Application Record | 163 |
| 8 | Compost Production Record | 202 |
| 9 | Manure Application / Food Crop Harvest Interval Record | 231 |

### Seed and Planting Stock Records — *§ 205.204; § 205.2 (Commercially Available)*
| # | Form (PDF heading) | Intro name | txt line |
|---|---|---|---|
| 10 | Seed Records **Part A**: Suppliers of Seed or Planting Stock | Suppliers of Seed or Planting Stock | 254 |
| 11 | Seed Records **Part B**: Nonorganic Seed or Planting Stock | Nonorganic Seed or Planting Stock | 275 |
| 12 | Seed Records **Part C**: Documentation of Allowability of Seed Treatments, Coatings, or Inoculants | Documentation of Allowability of Seed Treatments, Coatings, or Inoculants | 300 |
| 13 | Seed-saving and Planting-stock Propagation Record | Seed Saving and Plant Propagation Record | 312 |

### Harvest, Inventory/Storage, Sales, and Transaction Records — *§ 205.103; § 205.201*
| # | Form (PDF heading) | Intro name | txt line |
|---|---|---|---|
| 14 | Harvest Record | — | 322 |
| 15 | Farmers Market Load List or Farm Stand Sales Record | — | 341 |
| 16 | Harvest Plan and Record "Pick List" | — | 365 |
| 17 | Community Supported Agriculture (CSA) Weekly Harvest And Cost Summary | CSA Weekly Harvest and Cost Summary | 383 |
| 18 | Harvest Instructions / Record | — | 424 |
| 19 | Total Farm Sales Record | — | 443 |
| 20 | Storage Inventory Record | — | 462 |

### Prevention of Commingling and Contamination Records — *§ 205.201(a)(5),(6); § 205.103; § 205.272*
| # | Form | txt line |
|---|---|---|
| 21 | Equipment Cleaning Log | 478 |
| 22 | Clean Transport Affidavit | 493 |
| 23 | Buffer Crop Disposition Records | 533 |
| 24 | Sample Neighbor Notification Letter | 562 |
| 25 | Adjoining Land Use Verification | 610 |

**First read of the shape of the gap** (hypothesis for P2 to prove or kill, not an asserted finding):
forms 1–13 and 21–25 sit on territory Trazo already models (events, parcels, buffers, OSP modules).
Forms **14–20 — the harvest → storage → sales audit trail, seven of the twenty-five** — are the
block with the least existing coverage, and § 205.103(b)(2) makes them non-optional even though the
*forms* are optional: records must run "through production, to sale or transport" and be "traceable
back to the last certified operation." Trazo's event model currently stops at the farm gate.

Note forms 15–17 (farmers market, pick list, CSA) are **direct-market** shaped. For a wholesale ICP
they are likely `N/A-scope`, which would leave 14, 18, 19, 20 as the live audit-trail gap. Record
the scope call explicitly rather than letting the denominator quietly shrink.

---

## Key CFR sections in the corpus

Records/OSP: § 205.103, § 205.201, § 205.400, § 205.401, § 205.406
Crop practice standards: § 205.202, § 205.203, § 205.204, § 205.205, § 205.206
Integrity: § 205.272
Labeling (governs the **buyer page**, P4 — a different authority from the records audit):
§ 205.300, § 205.303, § 205.307, § 205.310, § 205.311

---

## Reproduce

```bash
cd documentation/reference/usda-recordkeeping
mkdir -p pdf txt cfr
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
for f in NOP-CropDocumentationForms NOP-DocumentationFormsIntro GuideForOrganicCropProducers Guide-OrganicCertification; do
  curl -sSL -A "$UA" -o "pdf/$f.pdf" "https://www.ams.usda.gov/sites/default/files/media/$f.pdf"
  pdftotext -layout "pdf/$f.pdf" "txt/$f.txt"
done

# Read latest_issue_date for title 7 first — a future date 404s.
ISSUE=$(curl -sS https://www.ecfr.gov/api/versioner/v1/titles.json \
  | python3 -c "import sys,json;print([t for t in json.load(sys.stdin)['titles'] if t['number']==7][0]['latest_issue_date'])")
curl -sS -o "cfr/title-7-part-205_$ISSUE.xml" \
  "https://www.ecfr.gov/api/versioner/v1/full/$ISSUE/title-7.xml?chapter=I&subchapter=M&part=205"

shasum -a 256 pdf/*.pdf cfr/*.xml
```

⚠️ Homebrew python 3.14 ships a broken `pyexpat` (`Symbol not found: _XML_SetAllocTrackerActivationThreshold`),
so `xml.etree` cannot parse the eCFR XML. The `cfr/*.txt` rendering was produced by regex tag-strip
over `<DIV8>` blocks instead.

---

## What P0 does not do

No field-level extraction, no crosswalk, no verdicts, no gap claims beyond the hypothesis flagged
above. Column-by-column form extraction is P1; the join against `record_completeness.py`,
`common_osp_records.py`, `AuditExportService`, and `osp_prefill.py` is P2; rendered-artifact proof
is P3.
