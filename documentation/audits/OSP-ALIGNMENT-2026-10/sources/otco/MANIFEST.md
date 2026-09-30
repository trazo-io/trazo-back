# OTCO source forms: retrieval manifest (2026-09-30)

The audit (AUDIT.md, T27) could not download Oregon Tilth's original forms and left OTCO without an
independent source check. We downloaded them. The binaries are kept locally, not committed (same
rule as `E2E-AUDIT-2026-09/.gitignore`); this file records enough to re-fetch and prove it is the
same file.

## How to retrieve

`tilth.org` answers 403 to a bare client. Both headers are needed:

```bash
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"
curl -L -A "$UA" -e https://tilth.org/help-center/blank-forms-all/ -O <url>
```

The listing page itself (`/help-center/blank-forms-all/`) still returns 403 to curl; it was read
through `r.jina.ai` to confirm every URL below is the one it links today.

## Files (retrieved 2026-09-30)

Base URL `https://tilth.org/wp-content/uploads/`. "Register rev." is the `revision:` field of the
matching `documentation/compliance/certifiers/otco/forms/*.yaml` at trazo-back `4959284`.

| File | Path | Bytes | sha256 | Live rev. stamp | Register rev. | Match |
|---|---|---:|---|---|---|---|
| O1 Operation Information | 2015/05/O1OperationInformation.docx | 126380 | `65bd0254ca019e5e1c05b038ab774b7d18b290c62423f07bfe632aa74fe768a8` | rev. 2026/03/25 | rev. 2025/08/27 | **NO** |
| OFPP Organic Fraud Prevention Plan | 2024/01/OFPP-OrganicFraudPreventionPlan.docx | 107059 | `97be17b9d1e28708d4fbede4a7f53f55989c57aba93d41a487cc6b6b539e9432` | rev 2025/08/27 | rev 2025/08/27 | yes |
| C1 Crop Activities Checklist | 2015/01/C1CropActivitiesChecklist.docx | 99907 | `31b0be4e1cc5ad62f43a207903d49599079fa80b9ce87eccd2efff78392cdb2b` | not read | not registered (scope.yaml) | n/a |
| C2 Crops, Acreage and Land History | 2015/05/C2CropsAcreageLandHistory.docx | 113163 | `24785f863cbd165fb04354dd0ba9d6dbd55f9ab0cfe21a7eb773b676e9d9fb9f` | rev. 2024/06/05 | rev. 2024/06/05 | yes |
| C3 Seeds, Planting Stock, Transplants | 2015/01/C3SeedsPlantingStockTransplants.docx | 69816 | `3a528be3b9657045ca565a7f72417dc18255ab907b231a5adb094445f665eca3` | rev. 2025/08/27 | rev. 2025/08/27 | yes |
| C4 Soil and Crop Fertility | 2015/01/C4SoilCropFertilityManagement.docx | 68819 | `409e03fd6532c98dc24a3b4ad0f906486edbf68d8db2660c42d45ea81e74fb3d` | rev. 2025/08/27 | rev. 2025/08/27 | yes |
| C5 Pest, Disease, Weed | 2015/01/C5CropPestDiseaseManagement.docx | 54149 | `30bfc7bf913579203cb983ad794a0b5059f53105206cd41d4a279cbcd296b107` | rev. 2023/09/14 | rev. 2023/09/14 | yes |
| C6 Natural Resources and Biodiversity | 2015/01/C6NaturalResourcesBiodiversity.docx | 88681 | `40d22285fb16287108c743d2356c4cb936be74735fdf5282e84a5e9f2c81346f` | rev. 2023/09/14 | rev. 2023/09/14 | yes |
| C7 Harvest, Processing, Storage, Transport | 2015/01/C7CropHarvestStorageTransport.docx | 127677 | `a8bc4d74d97cc1cb238ed4d2746c52c17440d66b598256b776959cfe39c3d70e` | rev. 2025/08/27 | rev. 2025/08/27 | yes |
| C8 Labeling and Sales | 2015/01/C8CropLabelingSales.docx | 73765 | `1f236a94554c9345b2a49958907f7b9188d32d2df5b6070a73743004b0c1bb03` | rev. 2025/08/27 | rev. 2025/08/27 | yes |
| C9 Contamination Prevention | 2015/04/C9CropContaminationPrevention.docx | 64596 | `449fc5868ed9996f64e6bdd328926128e0ff050e1bc1b8f1599a86971835b194` | rev. 2023/09/14 | rev. 2023/09/14 | yes |
| C11 Crop Materials List | 2015/01/C11CropMaterialsList.docx | 58421 | `ab22abe1e0c91b545941b67eac7a6037c92fbb139ea9ceb9911be1b2a2986f40` | rev. 2023/09/14 | rev. 2023/09/14 | yes |
| C12 Crop Record Keeping | 2015/01/C12CropRecordKeeping.docx | 62605 | `0f1f210688dd9d1e4c43d8244bb668d439bb223594a39e819d8a1fa245fc7a06` | rev. 2023/12/18 | rev. 2023/12/18 | yes |
| FACT Field and Crop Table | 2015/01/FieldAndCropTableFACT.docx | 93885 | `8677f2616b0450325849c6d1593ccd2b8ecb482a4a4d39487d93308c0984cb65` | Rev. 2022/09/01 | Rev. 2022/09/01 | yes |
| OSP Update Form | 2023/03/OSPUpdateFormWeb.docx | 47433 | `c1d81ce1c8c3140829e35bf8c974ae378b96006224a5c7ae69f7038d461bfe35` | Rev. 2024/09/20 | Rev. 2024/09/20 | yes |
| Crop OSP bundle | 2025/09/CROP-OSP-Oregon-Tilth-2025.zip | 1643101 | `14096042e9688e378b2794bd5813d5707bd39356985392164fbea6116fd2a2be` | ZIP dated 2025-09-10 | n/a | see below |

The 2025 ZIP holds byte-identical copies of every crop form above **except O1**, whose ZIP copy
(`08a6e9d0…5b98`, 125454 bytes) is the older rev. 2025/08/27. The individual O1 URL was
re-uploaded in place with rev. 2026/03/25 (docx modified 2026-03-25). So the ZIP is not the
current set, and the register's "Source" URL for O1 now serves a different edition from the
one it transcribed.

The ZIP also carries forms the register does not hold as `forms/`: C13, C14, W1, A1, IS,
Land Transfer, Commercial Availability, Contact Change, Crop Input Verification Evaluation,
Terms and Conditions. Whether each is correctly declared in `otco/scope.yaml` is Phase 2 work.

## O1: what changed between rev. 2025/08/27 (register) and rev. 2026/03/25 (live)

Text diff of `word/document.xml`, 184 paragraphs in each.

Substantive (section D, certification history):
- New NOTE: "you" now means the person completing the application, the legally responsible
  contact, the primary contact **and anyone responsibly connected**.
- Every history question now reads "Have you, the responsibly connected, or this operation
  ever…" (certified, suspended, revoked, surrendered with noncompliance, denied, withdrawn).
- **Three new checkboxes:**
  - after suspension: affirm no product sold or represented as organic since the suspension date;
  - after suspension: request that NOP reinstate a currently suspended certification;
  - after revocation: affirm no product sold or represented as organic since the revocation date.

Non-substantive: DBA wording and capitalisation, "Responsibility" → "Responsibly Connected"
heading fix, punctuation, and the membership-benefits bullets removed from the fee section.

**Effect on the register:** `O1-operation-information.yaml` rows `D-2–6` (grouped) and the
responsibly-connected row `B-6` were transcribed from the older edition. The three affirmation
checkboxes have no rows. Recorded in LEDGER.md as T27; the register edit is Phase 2.
