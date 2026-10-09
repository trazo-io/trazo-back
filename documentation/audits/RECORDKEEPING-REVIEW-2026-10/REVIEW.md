# Trazo recordkeeping review: the two outputs, as their readers meet them

Date: 2026-10-07. Reviewer stance: outside expert in organic certification recordkeeping and
field-worker UX. Nothing in code, docs or UI is taken as true until seen in a browser.

Checkout: trazo-back `6b5ef1d`, trazo-app `fcea8c0` (both `origin/main` on 2026-10-06), pair
worktree `~/dev/trazo-wt/rk-review`. Backend on :8001 against `trazo_r8pass`, app on :3001.
Screenshots in `screenshots/`, downloaded documents in `downloads/` (local evidence; see the
folder's note before committing binaries).

## Read this first: what the specimen actually is

- The certifier of record in `trazo_r8pass` is **"Cascadia Organic Certifiers (COC)"**, the
  seed's fictional default (`seed_calapooia_bend.py:88-102`; Oregon Tilth survives only with
  `--real-names`). COC has no form register, so the v3 packet is the "agent without a
  register" case and falls back to CCOF numbering with `is_own=False`. OTCO, CCOF and WSDA
  packets are produced by setting the v4 draft's certifying agent through the UI picker,
  then restoring it to empty; each switch is logged below.
- The database holds 515 events, not 513: the 2 extra are leftover test records from an
  earlier pass.
- OSP ids 4..7 = v1, v2 (superseded), v3 (active), v4 (draft). Annual updates 2026: rev1
  (`legacy_none`), rev2 and rev3 (signed, filed, frozen; rev3 corrects rev2), plus a 2027
  rev1 draft. Frozen rows are never touched in this review.
- Every record this review creates carries `REVIEW-2026-10` in its name or description.
- ADR-011 (date and time semantics) is in the workspace repo
  (`documentation/adr/011-farm-record-date-and-time-semantics.md`, workspace #15).

## Honesty rules checked on every surface

No score, percentage or grade of documentation. "Verified" only for a confirmed USDA OID
match; OMRI, WSDA and National List are listings; a grower's own answer is "recorded" or "as
reported by the farm". Carbon without a basis is "not estimated". Factor sources per input
class. Descriptions state what the record holds, never an outcome. On the plan is not
approved; recorded is not allowed. Readiness is a documentation check, not a verdict. es-419
is neutral tuteo; the farm is "finca".

## 1. Warnings catalog

### 1.1 Farm home: the two "not matched" counts (Oscar's starting example)

Seen: `screenshots/02-farm-home-readiness-card-en.png` (farm home, signed in, en-US). The card
"Before your certifier packet" reads "Liberty 2026 — River Block — 16 record checks on your
latest season", "2 open items", then:

- Whole operation: "12 logged products are not on your materials list" + the first five brand
  names + "Open Organic System Plan → Materials and add anything genuinely missing."
- This season: "Inputs not matched to the plan's approved inputs (§ 205.400(f)(2))", chip
  "Needs attention", "12 input record(s) not matched to the plan's approved inputs — see
  Inputs Not Matched to the Plan's Approved Inputs section".
- Footer: "These are documentation checks on your records in Trazo, not a compliance
  decision. Your certifying agent makes that determination." (good)

**Are those one finding?** No, and the two 12s are a coincidence of the specimen. Verified
in the database and in code:

| | whole-operation row | this-season row |
|---|---|---|
| counts | distinct product NAMES, every season, chemical + soil + sanitizer | EVENT records with a stored `drift_warning`, one production only (Liberty 2026) |
| compared to | the plan being filed (v4 draft) by exact normalised name only (`plan_materials.py:343`) | the ACTIVE plan (v3), stamped at save (`drift_detector.py:61-99`) |
| source | `operation_readiness_service.py:622` | `audit_export_service.py:3912`, RAW English, no i18n key |
| Calapooia | 11 names + 1 leftover test record = 12 | 11 chemical + 1 soil event on Liberty 2026 = 12 |

**Is the 12 real?** No. OSP v3 and v4 both list the same products, under their OMRI
listing names: "Bayer Serenade Opti A Wettable Powder Biofungicide", "Down to Earth All
Natural Fertilizers Feather Meal 12-0-0", "Entrust SC Naturalyte Insect Control", "Grandevo",
"Neptune's Harvest Organic Fish Fertilizer 2-4-1", "NovaSource Surround WP Agricultural Crop
Protectant", plus National List "Lime sulfur", "Elemental sulfur", "Peracetic acid". The
records log the jug names: "Serenade Opti", "Down To Earth Feather Meal 12-0-0", "Entrust SC",
"Grandevo WDG", "Surround WP Crop Protectant", "Rex Lime Sulfur", "Tiger 90CR elemental
sulfur". The stored finding on each event already says so: `reason` = "Input 'Down To Earth
Feather Meal 12-0-0' not matched to any approved OSP input. Possible match, not confirmed:
Down to Earth All Natural Fertilizers Feather Meal 12-0-0 (OMRI)." Nothing on the farm has a
`MaterialIdentityDecision` (0 rows), no chemical event has an OMRI link (0 of 81), so every
one of the 81 chemical events and 15 soil events on the farm carries `reason_code =
unresolved`. Only one of the twelve is a genuine discrepancy a certifier would want: the plan
lists Neptune's Harvest **2-4-1** and the records say **2-3-1**.

**Should the demo farm show it?** As built, the demo shows the worst case a real farm will
hit on day one (brand on the jug, listing name on the plan, nobody has confirmed identity),
and that is the honest state of the policy "never fuzzy-match". What it must not do is state
the policy as a fact about the catalogs; see F-01 and F-09.

### 1.2 Production page drift banner (Liberty 2026)

Seen: `screenshots/03-prod21-drift-banner-expanded-en.png`. Banner: "12 events reference
inputs not in your active OSP. Per 7 CFR 205.400(f)(2), you must immediately notify your
certifier of any change to your operation that may affect its organic status. Add the input to
your OSP or file a change-notification with the certifier." Each row: "“Rex Lime Sulfur” did
not match any product on your OSP's approved-inputs list or in the reference catalogs." chip
"Name unresolved", link "Search on omri.org".

- The rows drop the candidate the detector found (`reason_params.possibleMatches` is stored,
  the i18n string `drift.reason.unresolved` does not print it). The grower is told there was
  no match when the server wrote the match down.
- "Rex Lime Sulfur" and "Entrust SC" DO carry a National List link (`national_list_substance_id`
  → Lime sulfur, Spinosad) with `national_list_basis = legacy_unverified`; the row still says
  "did not match … in the reference catalogs".
- "you must immediately notify your certifier" is a legal instruction issued on a finding that
  is, for 11 of 12 rows, a naming difference. On a farm that logs honestly this reads as
  "you are out of compliance".
- Same production, event cards: chip "Organic-approved · grower-reported" with tooltip
  "Trazo did not find it in the OMRI or National List catalogs" on Rex Lime Sulfur, which has
  a National List link. Policy (basis `legacy_unverified` is not a confirmed match) is right;
  the sentence is false.

### 1.3 OSP pages (module list and narrative view), en-US

Seen: `screenshots/04-osp-page-en.png`, `screenshots/05-osp-narratives-en.png`.

What reads right:
- "15 of 19 farm-wide modules have every answer" and "6 of 6 narrative sections have text",
  each followed by "Having an answer is not a review, an approval or readiness for renewal;
  the certifier decides." Counts, not grades.
- The certifying-agent card names COC from the certificate on file and says plainly "Trazo
  holds no form register for Cascadia Organic Certifiers (COC), so the packet borrows no
  agent's form numbers."
- The inputs panel says "Your certifier reviews the list and decides what is approved."
- Module chips: "All answers given", "In progress", "Not applicable", "Continue here".

What does not:
- Plan review badge "2 to confirm" sits above two groups holding 22 and 9 items. The badge
  counts groups (`OSPPlanReviewPanel.tsx:64`, `findings.length`), the groups count records.
  A grower reads "2" and stops; the certifier reads 31.
- Version chip on v3: "Active / Approved" (`osp.status.active`, es "Activo / Aprobado").
  Activation is the grower recording that the agent approved the plan ("Mark as Active" asks
  for the approval document and certificate number). "Approved" with no date and no agent on
  the chip states the outcome as Trazo's. The packet dropped this wording in run 7 (R7-02);
  the app kept it.
- Parcel buttons "Home Field East · Complete" keep the per-section "Complete" that R8-10
  removed from the OSP bar.
- Annual update card: the 2026 row says "Plan v1 → v3" while its own text continues v3;
  below the list, a continuation-year form defaults to 2026, then says "The 2026 update is
  signed or filed. Change it with Create correction on its row." The form offers a year it
  will refuse.
- The 2027 draft row reads "No changes — OSP reaffirmed" while the plan-review panel on the
  same page lists 22 record types the plan does not confirm. Both are true (the draft is
  unsigned), but a grower who signs the draft as-is files "no changes" against a plan that
  the page itself says moved.

### 1.4 Farm profile (certifier link card, dossier, certifications, attestations), en-US

Seen: `screenshots/06-farm-profile-en.png`.

- The "Share with your certifier" card repeats the whole-operation readiness warning ("12
  logged products are not on your materials list") word for word from the farm home. Third
  copy of the same warning on the farm (home card, link card, and the OSP inputs panel's drift
  note). It does not block link creation here (it is a warning, not a blocker).
- "Operation Audit Dossier" copy is right: "This is the evidence behind your plan, not the plan
  itself — your renewal filing is the OSP packet".
- Certifications: both rows read "Specimen record, not checked against any registry" (honest
  for `is_demo`). Under USDA Organic the card also prints "USDA Organic Integrity Database not
  loaded. Run: python manage.py import_usda_organic_data" — a developer instruction
  (`usda_organic_verifier.py:96`, stored as the verification note). Seen on the local
  database, where the OID table is empty (0 rows); production has the table loaded, so this
  is a dev-only sighting unless an import ever fails in production.
- "SOE Compliance" heading with chip "Plan on file" (`farm.soe.title`): the chip is a count
  of one document; the heading is a verdict word.
- Header: "138.6 acres · est. 2004 · 6 parcels" (`total_acreage`). The six parcels sum to
  86.9 ac, which is what the OSP calls the certified acreage. The profile figure is the whole
  property; nothing on the page says so. Checked in the packet below (does any document print
  138.6 as certified acreage?).
- CA PUR: not offered (Oregon farm). Correct.

### 1.5 Parcel application, transition tab, en-US

Seen: `screenshots/07-parcel-application-en.png`, `08-parcel-transition-tab-en.png`.
"Computed transition status · § 205.202(b) · Computed from your records · No prohibited input
on record · No prohibited substance applications recorded. Field history affidavits may still
be required by the certifier per 7 CFR 205.202(b)." States what the records hold and what they
cannot show. Right. Tab chips "Section complete" and the page chip "Complete" are the
per-section "Complete" wording again (counts answered questions, not a review).
### 1.6 Documents page, en-US

Seen: `screenshots/09-documents-en.png`. Two specimen uploads; folders Exports 0 (fills as
documents are generated below). "Export all records (CSV)" is the records ZIP link
(`/records-export/`). Nothing misleading.

### 1.7 Activity wizard, desktop, en-US (Onions 2026 — Upper Terrace, open season)

Seen: `screenshots/10-wizard-step1-en.png`, `11-wizard-step2-chemical-en.png`,
`12-wizard-lookup-serenade-en.png`.

- Step 1: verbs, then "Which one was it?" (Fertilizer / Pesticide / Fungicide / Herbicide).
  Event Date Time is prefilled with the VIEWER's clock (`2026-10-07T00:11` in a UTC-3
  browser while it was 20:11 on the farm). ADR-011 says the stored value is the farm's wall
  clock; the prefill is whoever's laptop opened the form. A crew phone in Oregon is fine; a
  manager correcting records from elsewhere is not.
- Step 2 "My products" offers "Producto Prueba 301" (the leftover test record) beside Serenade
  Opti and Rex Lime Sulfur. A test record is one tap from becoming a new record.
- Lookup: "Serenade Opti" → "Checked just now · OMRI · Bayer Serenade Opti A Wettable Powder
  Biofungicide · OMRI #gus-5425 · List of Sep 5, 2026 · Use this listing", then "Matching a
  catalog does not approve the input on your OSP. Your certifier adds approved inputs to the
  OSP separately." The helper finds in one click exactly the candidate the drift detector
  refuses to confirm on the 81 seeded records. The two surfaces are consistent in policy
  (the grower must press "Use this listing"); the seed never pressed it.
- Weather option "Overcast & Humid - Good for herbicides" on an organic input form.
- "Fungicide Concentration*" is required with a free-text format hint; the ledger's 375 px
  pass already lists it as English-in-Spanish.
- Unknown input "Producto Desconocido 77" → "No match in OMRI, WSDA or the National List. You
  can save the record; that does not mean the input is allowed. Check it with your
  certifier." + "Search omri.org manually" (`screenshots/13-wizard-lookup-nomatch-en.png`).
  Right.

### 1.8 The same desk surfaces in es-419

Seen: `screenshots/14-farm-home-es.png`, `15-prod21-drift-banner-es.png`, `16-osp-page-es.png`,
`17-prod21-inputs-es.png`.

- Farm card, season row: entirely English inside a Spanish page. "Inputs not matched to the
  plan's approved inputs (§ 205.400(f)(2))", "12 input record(s) not matched to the plan's
  approved inputs — see Inputs Not Matched to the Plan's Approved Inputs section", and a
  half-translated "Detalle completo en Inputs Not Matched to the Plan's Approved Inputs
  section de tu exportación de auditoría". The label and detail come raw from
  `audit_export_service.py:3912-3933`; the certifier page has a `row_key` and a translation,
  the farm card does not (`dashboardMetricsApi.ts:84` carries no `row_key`).
- Register: "en su temporada más reciente" (usted, `certifierReadiness.subtitle`) inside a
  card that otherwise says "tu expediente", "Tus registros". OSP page: "Complete cada
  módulo. Sus respuestas…", "ocurrió en sus registros" (usted) beside "Tus registros
  muestran" (tuteo). Ledger R8-06 deferred the full usted sweep; these are on the two pages a
  manager opens most.
- Plan review items raw English in es: "Cultivation — 21 cultivation events logged",
  "Mulching — 30 orchard-floor / mowing event(s) logged — confirm whether…"
  (`plan_review.py:194-236`, `details[]`).
- Event subtypes raw English in es: "Rex Lime Sulfur · disease prevention", "· soil
  nutrition" (ledger 375 px pass lists "disease prevention" as open; still open).
- Input chip in es: "Aprobado para uso orgánico · informado por el productor". The English
  "Organic-approved · grower-reported" at least hyphenates the claim; the Spanish reads as a
  plain verdict "Approved for organic use" with the qualifier after the dot. Tooltip in
  both: "Trazo did not find it in the OMRI or National List catalogs" (false for the two
  inputs that carry a National List link).
- Drift banner and rows: fully translated (`drift.*`), same content defects as English.
- "Plan Orgánico del Sistema" (farm card fix line) vs "Plan del Sistema Orgánico (OSP)"
  (menu, page title): two names for one thing on one screen (ledger lists the leftover).


### 1.9 Catalog table

Columns: id · category · where it shows / trigger · true for every farm it fires on · names
the record and the next step · repeats another · reads as a verdict · localized (es-419) ·
seen (screenshot or file). "code" in the last column means not reproduced in the browser.

| id | cat | where / trigger | true for every farm | record + next step | repeats | verdict | es-419 | seen |
|---|---|---|---|---|---|---|---|---|
| W-01 | readiness | farm home, whole-operation row "N logged products are not on your materials list"; exact-name mismatch vs the plan being filed (`operation_readiness_service.py:622`) | no: 11 of 12 are brand-vs-listing names of inputs the plan lists | names products + "Open OSP → Materials" | W-02, W-03, link card, packet materials [REVIEW], workbook comments | no | yes | 02, 14 |
| W-02 | readiness | farm home, season row "Inputs not matched to the plan's approved inputs (§ 205.400(f)(2)) · Needs attention"; count of stored `drift_warning` on latest production (`audit_export_service.py:3912`) | no, same | section name only, no record, no link | W-01, W-03, certifier page, dossier | "approved inputs" | NO, raw English | 02, 14 |
| W-03 | drift | production page banner "N events reference inputs not in your active OSP … you must immediately notify your certifier" (`DriftFindingsBanner.tsx`) | no, same | date + input per row; drops the stored candidate | W-02 | legal instruction | yes | 03, 15 |
| W-04 | drift | drift row "did not match any product … or in the reference catalogs" (`drift.reason.unresolved`) | false when `possibleMatches` or a National List link exists | names input | W-03 | no | yes | 03 |
| W-05 | buyer chip + producer card | "Organic-approved · grower-reported", tooltip "Trazo did not find it in the OMRI or National List catalogs"; `organic_approved=omri_listed` with no link | tooltip false for NL-linked inputs | no | across app and buyer page | "Organic-approved"; es "Aprobado para uso orgánico" | yes | 17, 31, 36 |
| W-06 | buyer chip | "Documented" / "Insumo documentado" for `unverified` basis | yes | no | no | no | yes | 69, 90 |
| W-07 | buyer chip | "Grower record" / "Registro del productor" on certificates and filings | yes | no | no | no | yes | 31 |
| W-08 | readiness | new farm, blockers "OFPP not on file", "No OSP", "no production records", each "Fix it here →" | yes | yes + link | no | "SOE 2024 … prohibits certification" (quoted) | yes | 49 |
| W-09 | deadlines | new farm strip "OSP annual update (2026) · Not filed" | no: fires on a never-certified farm | no | no | no | yes | 49 |
| W-10 | readiness | farm card footer "documentation checks … not a compliance decision" | yes | n/a | n/a | no | yes | 02 |
| W-11 | readiness chip | "Needs attention" on REVIEW/FAIL rows | yes | no | n/a | no | yes | 02 |
| W-12 | OSP | plan review badge "N to confirm" (counts groups, `OSPPlanReviewPanel.tsx:64`) | count misleads | no | no | no | yes; items raw English | 04, 16 |
| W-13 | OSP | version chip "Active / Approved" (`osp.status.active`) | "Approved" is the grower's recorded claim | no | dossier "Active (approval date not recorded)" | yes | "Activo / Aprobado" | 05 |
| W-14 | OSP | module chips "All answers given / In progress / Not applicable / Continue here"; parcel "Complete", tab "Section complete" | yes | yes | no | "Complete" | yes | 04, 07 |
| W-15 | OSP | "15 of 19 modules have every answer … not a review, an approval or readiness" | yes | n/a | no | no | yes (usted) | 04 |
| W-16 | OSP | certifying-agent note "Trazo holds no form register for COC…" | yes | yes | no | no | yes | 04, 16 |
| W-17 | toast | "Drift detection runs against the farm's currently active OSP…" on annual-update save, sign and file | wrong surface | no | no | no | yes | 92, 96 |
| W-18 | annual update | row "No changes — OSP reaffirmed" rendered from an EMPTY summary | no: empty ≠ reaffirmed | no | no | affirmative | yes | 05, 91 |
| W-19 | annual update | status line "Annual update 2027: Filed. Nothing pending…" | yes | yes | no | no | yes | 96 |
| W-20 | annual update | continuation-year form defaults to a filed year, then refuses it | no | yes | no | no | yes | 05 |
| W-21 | save nudge | "Saved — a certifier will also ask for: target pest, what shows the input is allowed (organic basis)" | no: basis "not yet confirmed" counted as missing | fields, not record, no link | certifier page "Missing" | no | yes | 68 |
| W-22 | offline toast | title "Error", body "Sin conexión, así que todavía no se guardó…" | body yes; title wrong | yes | no | no | yes | 67 |
| W-23 | wizard | step 1 "Required", "When did this activity occur and who performed it?" | n/a | n/a | n/a | n/a | NO | 63 |
| W-24 | wizard help | "Consumer trust information … Esa transparencia genera confianza"; "La no conformidad más frecuente a nivel nacional es…" (unsourced) | unsourced | n/a | n/a | no | yes | 64 |
| W-25 | wizard note | cleanout "Record for the certifier only — not shown on your buyer page" | yes | yes | no | no | yes | 76 |
| W-26 | template | "Plantilla aplicada — Cosecha"; prefills name "Harvesting", efficiency "Normal Efficiency" | prefills become record values | n/a | no | no | prefills English | 74 |
| W-27 | lookup | "Checked just now · OMRI · … · Use this listing · Matching a catalog does not approve the input on your OSP" | yes | yes | no | no | yes | 12 |
| W-28 | lookup | "No match in OMRI, WSDA or the National List. You can save the record; that does not mean the input is allowed." | yes | yes | no | no | yes | 13, 65 |
| W-29 | NL chip | "Allowed input" / `nlStatus.allowed` | n/a | n/a | n/a | "Allowed" | yes | code only: no NL-confirmed input on the specimen |
| W-30 | transition | parcel tab "No prohibited input on record" → "Not established: input status not recorded" after one `unverified` input | second state false ("not recorded") | names inputs | dossier p.235 | no | yes | 08, 100 |
| W-31 | certifier page | chips "For review / Not assessed / Missing"; "Missing — … organic basis (2)" | "Missing" false for unverified | section pointer | W-21 | no | en only exercised | 98 |
| W-32 | certifier page | row details "Add buyer + organic-on-invoice flag", "fill before audit" | grower strings | n/a | farm card | no | en | 98 |
| W-33 | certifier page | "documentation checks … not a compliance decision"; "Built from the operation's current records… expires" | yes | n/a | n/a | no | en | 98, 99 |
| W-34 | buyer tile | "60 practices documented" | count | n/a | n/a | no | yes | 30 |
| W-35 | buyer line | "Practice records are farmer-reported… Certifications are labeled separately as Verified or Self-Reported" | "Verified" promised, never shown on the page | n/a | n/a | no | yes | 31 |
| W-36 | buyer | "Demonstration record, not a certified operation"; "Specimen record, not checked against any registry" | yes | n/a | n/a | no | yes | 31 |
| W-37 | buyer | "DEMO FARM" tag + red box | yes | n/a | n/a | no | yes | 30 |
| W-38 | buyer carbon | collapsed section, per-kg figure, scope and per-class sources | page copy yes; number includes area estimates (F-02) | n/a | n/a | no | yes; "Blueberries" untranslated | 37 |
| W-39 | public payload | `/api/transparency/<id>/`: `carbon_scope "Direct operational emissions only (EPA/USDA-sourced factors)"`, `per_kg_miles`, `per_kg_phone_charges`, `blockchain_verified` | no | n/a | n/a | yes | n/a | curl (anonymous) |
| W-40 | toasts | "Export Ready — Your audit report is downloading"; "Gathering operation-wide records…"; "Your dossier is ready … email on its way"; "Certifier link created"; "Update signed"; "Filing recorded. The packet now carries it exactly as filed." | yes | yes | no | no | en exercised | 21, 97 |
| W-41 | profile | "USDA Organic Integrity Database not loaded. Run: python manage.py import_usda_organic_data" | dev only | no | no | no | raw | 06 |
| W-42 | sign-up | "Password strength: Strong" + "Password contains common words or predictable patterns" | contradictory | n/a | n/a | n/a | en | 41 |
| W-43 | sign-up | Terms label click → opens trazo.io; "You must accept the terms and conditions" | n/a | n/a | n/a | n/a | en | 41 |
| W-44 | overlay | "Getting Started · N of 7 complete" panel intercepts clicks on the parcel page | n/a | n/a | n/a | n/a | en | 55 |
| W-45 | dossier modal | button "Download packet" on the per-production dossier | mislabelled | n/a | packet | no | en | 20 |
| W-46 | packet menu | "v4 — draft, still being written … A draft packet is a working copy" | yes | yes | no | no | en | 18 |
| W-47 | finish dialog | read-only, 5-year retention, "available to your certifier packet", publish switch, amendment note | yes | yes | no | no | en | 87 |
| W-48 | parcel page | event cards "No CO₂ data", "3833 kg CO₂e", "Area Covered", "Tillage" on the es page | n/a | n/a | n/a | no | NO | 68 |
| W-49 | packet | materials module "[REVIEW] 12 product name(s) … do not match an entry above"; workbook "Identity not confirmed" | same as W-01 | names products | W-01 | no | en | packet |
| W-50 | dossier | snapshot "DOCUMENTED / REVIEW / N/A / FYI" with legend; "100% materially complete"; "Complete — N characters" | legend yes; % no | section links | n/a | "100%", "Complete" | en | p-01, p-03 |
| W-51 | dossier | "Pre-Export Consistency Check": yield delta 69.9%, handler chain "COC, COD, Cascadia Organic Certifiers" | false | "Resolve each row before handing this PDF to a certifier" | n/a | yes | en | p-02 |
| W-52 | dossier | "Supply-chain traceability audit readiness: Producer attests that … Trazo infrastructure supports rapid retrieval (target: 24-hour response)" | unsigned | n/a | ×12 in the operation dossier | yes | en | p-52 |
| W-53 | voice | "Iniciar entrada por voz" with no microphone: no message | silent | no | n/a | n/a | yes | 80 |
| W-54 | email / setup | "Welcome to Trazo - Agricultural Transparency Platform"; "start building consumer trust through transparency"; "Sustainability Goals" tiles → public "Sustainability Commitment" | retired framing; public claim with no record | n/a | n/a | yes | en | 42, 44, MailDev |

## 2. Output 1, read as the certifier

(The certifier review link is read in journey 4e, from both sides.)
### 2.0 Environment notes for this step

- Document files the seed wrote live in the seeding checkout's media folder
  (`~/dev/trazo-wt/r8pass/trazo-back/backend/media`). This worktree had none, so the first
  v3 packet printed "Invoice CBF-INV-26--RB-F (specimen): not in this packet (could not be
  read from storage)" in the audit trail exhibit. The two specimen files were copied into this
  worktree's media folder (git-ignored) before the later packets. The sentence itself is the
  right behaviour for a missing file: it says missing rather than inventing.
- Agent switches on the v4 draft, all through the UI picker ("Save agent", toast "Certifying
  agent saved"): OTCO → CCOF → WSDA → restored to empty. Logged in the review log at the end.

### 2.1 Renewal packet, OSP v3 (active), agent of record COC (no register)

File: `downloads/calapooia-bend-farm-osp-v3-packet.zip` (40 files: 00-06, annual-update/ ×3,
modules/ ×19, parcels/ ×6, workbooks/ ×4). Page counts: cover 2, narrative 11, annual update
2, routing 1, change notifications 1, coverage 2, audit trail 2, question index 1.
Visual check (`downloads/img-v3/*.png`, 80 dpi): cover, audit-trail table, materials module and
routing page render cleanly; the diagonal "SPECIMEN — FABRICATED RECORDS — NOT A REAL
OPERATION" watermark sits over every page (right for `is_demo`).

What reads right, as a certifier:
- Cover: operation block per § 205.401(b); "Plan version: v1 to v3"; "Continues certification
  for: 2026 · Filed: 2026-10-02"; a plan-review list that "names no conclusion"; a contents
  list of the ZIP.
- 02 annual update is the frozen revision 3 as filed (sha256 printed; matches
  `filed_sha256` in the row). It states what revision 3 corrects in revision 2, in four
  numbered points, and reports COC's acknowledgment "as the operation's account, not as a
  recorded acknowledgment". The sales subtotal is labelled "not reconciled" and "not any
  certifying agent's fee figure".
- 02s: revision 1 "No signature was recorded in Trazo … rendered from current records, not
  the filed document". Honest about the legacy revision.
- 04: "Cascadia Organic Certifiers (COC) is not one Trazo holds a form register for"; lists
  "Sections of this plan still to finish" (4 modules) "listed by the operation, for the
  operation".
- 05 audit trail, Part B: lot CBF-26-RB traced harvest (4 records, 114,240 lb) → storage →
  2 sales (110,702 lb) → balance "The handler's pack-out records 3,538 lb less than was
  harvested." A missing link "is reported as missing rather than supplied".
- 06: "Trazo holds no question register for this certifying agent, so this index lists no
  forms or rows."

What does not:
- **01 narrative, "Last updated: 2026-10-07"** on a document titled "Submission Snapshot v3 ·
  Submitted: 2026-08-21". The packet build calls `_refresh_narratives_if_editable(osp)`
  (`osp_module_pdf.py:3171`), which recompiles `sections` on plans whose status is draft OR
  **active**, and saved v3 (`updated_at` moved from 2026-08-21 to 2026-10-07 03:16:11 during
  this download). The docstring's own rule is "a submitted or superseded plan's sections are
  the text that was FILED"; the active plan is the one the certifier holds, and it is the one
  being rewritten on read. For this specimen the text did not change (modules are locked),
  but the date printed did, and the write happened. On a real farm, an approved input or a
  handler added after approval changes the on-file narrative silently.
- **No frozen submission for the active plan.** `submission_pdf` is set for v1 and v2 and
  EMPTY for v3 (the seed activated v3 without the submit step). 01 is therefore a
  reconstruction, and nothing in the packet says so, unlike annual-update revision 1, which
  is marked "rendered from current records, not the filed document". Specimen gap plus a
  missing disclosure in the renderer.
- Materials Application module, "[REVIEW] 12 product name(s) in the logged applications do
  not match an entry above: Rex Lime Sulfur, Down To Earth Feather Meal 12-0-0, Serenade
  Opti, Neptune's Harvest Fish Fertilizer 2-3-1, Surround WP Crop Protectant, Entrust SC,
  Grandevo WDG, Producto Prueba 301, Tiger 90CR elemental sulfur …, Douglas-fir sawdust,
  untreated, Rexius Organic Compost, SaniDate 5.0 (peracetic acid)." This is the same
  brand-versus-listing list as the farm card, now in the certifier's hands, with the leftover
  test record "Producto Prueba 301" in it. Each National List row reads "brand and
  formulation not stated — manufacturer not stated — reason for use not stated" and each OMRI
  row "reason for use not stated": true of the specimen plan, and a certifier reads twelve
  "not stated" before reaching the list.
- No PDF outlines (bookmarks) in any packet PDF (checked for `/Outlines`; 01 is 11 pages,
  modules up to 2). The cover's contents list has no page numbers, which is defensible for a
  ZIP of separate files but leaves the 11-page narrative without navigation. Ledger R8-28
  closed outlines for the DOSSIER (back #122); the packet did not get them.
- "Plan version: v1 to v3" on the cover, 02 and 02s: the filing's `prior_osp` is v1 while
  v2 (Feb 2026) sits between. Specimen data; the renderer prints what the row says.

### 2.2 Renewal packet, OSP v4 (draft), agent set to OTCO, then CCOF, then WSDA

Files: `downloads/calapooia-bend-farm-osp-v4-packet-{OTCO,CCOF,WSDA}.zip`, unpacked under
`downloads/v4-*/`. Visual check `downloads/img-v4-otco/*.png`: cover, coverage page 2, index
page 1 and routing page render cleanly; the long "Still open:" paragraphs are dense but legible.

| | OTCO | CCOF | WSDA |
|---|---|---|---|
| 04 coverage pages | 4 | 4 | 4 |
| 06 question index pages | 33 | 33 | 32 |
| 02s routing | OSP Update Form steps 1-6 mapped; Step 6 gross-sales scope stated | Annual Renewal Contract + Crop Update NOPB88 mapped | Renewal application (unpublished form, said so) + AGR 2516 + AGR 2521 |
| agent workbook | FACT-04 added | none | none |
| attachments | audit-trail/sale-13 invoice, labels/ | same | same |

What reads right:
- Cover says "v4 (draft — not yet submitted) … This packet is a working copy for the
  operation to review — it is not the plan on file with the certifying agent." Continuation
  block: "Filed: draft — not yet filed".
- 02s (every agent): "Sales figure: the subtotal printed on 02 is … not this agent's fee
  figure", then the agent's own fee rule in one sentence (OTCO Step 6, WSDA AGR 2521).
- 04 opens "every compliance determination is the certifying agent's", lists "Forms this
  packet answers in part" with the open question ids per form, then "Forms the operation
  files with <agent>" that the packet only supports. 06 says "No entry says that a question
  is satisfied, accepted or compliant" and cites the agent's forms URL and retrieval date.
- The specimen invoice and label proof travel inside the ZIP once the files are readable.

What does not:
- **04, Parcel Application rows: "the route is not determined (certifying agent not
  recognised, or none named)"**, printed once per question per parcel (7 questions × 6 parcel
  names on OTCO's C2; 9 on CCOF's NOPB49), while the same packet is numbered to OTCO/CCOF
  and the cover names the plan's agent. The parcel route is resolved from each parcel's own
  "prior certifier" answer (`stated_agent(parcel)`, `certified_parcel_branch.py:279-303`):
  Calapooia's parcels name COC, which is not a registered agent, so `route_for` returns
  "unresolved" for OTCO and WSDA and the sentence prints per question per parcel. The
  sentence is about the parcel answer but reads as about the certifying agent the packet is
  addressed to. On a real OTCO farm whose parcels name OTCO it does not fire; on any farm
  whose parcels name an agent outside the 42-entry list, or that is switching agents at
  renewal, the parcel section of 04 collapses into 42-54 copies of this sentence instead of
  one line saying which answer to fix.
- 06 is 32-33 pages of rows, most "not collected by Trazo" or "not checked against this
  plan's answers". Honest, and the right thing to ship; but there is no outline and no
  per-form page list, so an inspector pages through 33 pages to find C11. Same outline gap
  as 2.1.
- Materials workbook / C11 "Still open: 11.1 Table (manufacturer), (third party review
  agency), (intended use) not checked against this plan's answers" even though the module
  prints manufacturer and OMRI number per row. The register check and the module disagree
  about what is answered (code-only reading; the certifier sees "still open").

### 2.3 Per-production audit dossier, Duke 2026 — Home Field East (PDF 69 pages, CSV 150 rows)

Files: `downloads/duke-2026-dossier.pdf` (title "Trazo Audit Report — Calapooia Bend Farm",
has a PDF outline), `downloads/duke-2026-dossier.csv`. The producer-side modal's button says
"Download packet" (`screenshots/20-audit-export-modal-en.png`) while its own text says the
dossier is not the renewal packet. Visual check `downloads/img-dossier/p-*.png`.

What reads right:
- A red specimen box on page 1: "Do not file, forward or rely on it as evidence of
  compliance."
- The snapshot table's legend: "DOCUMENTED = the supporting record is on file in Trazo …
  N/A = … an absence of records, not a clean result. These marks reflect documentation
  status in Trazo, not a compliance determination."
- Land requirements row: "Organic certification recorded, effective 2006-05-15
  (self-reported — no USDA Organic Integrity Database match on file). The 36-month
  determination under § 205.202(b) is the certifying agent's."
- "Section narratives — as held in Trazo for v3. This export does not compare them with
  the copy filed with the certifier. Trazo holds no copy generated at submission for this
  version." The dossier discloses what the packet (2.1) does not.
- Certification summary: both certificates "Self-Reported"; USDA certificates "do not
  expire per 7 CFR § 205.404(d)". Record retention "Kept until at least 2031-10-06".
- Output reconciliation: "Harvest Yield: 121,250 lb · Harvest basis: sum of 4 harvest
  record(s) · Quantity Sold: 117,336 lb".

What does not:
- **Page 1, OSP row: "v3 Active (approval date not recorded in Trazo) — 100% materially
  complete"; page 3: "Section Completion (material): 100% of § 205.201(a)(1)-(6)
  substantively filled" and six rows "Complete — 11,238 characters".** A percentage and the
  word Complete in the certifier's first table. The app lost its % bar in run 8 (R8-10);
  the dossier kept it (`audit_export_service.py:3606`).
- **Page 2, "Pre-Export Consistency Check": "Yield reconciliation — Production header:
  121,250 lb · Harvest-event narrative value(s): 36,500 lb · closest delta 69.9% (tolerance
  ±15%)".** The four harvest records carry `yield_quantity` 36,500 + 36,200 + 30,300 +
  18,250 = 121,250 lb, which page 49 of the same document sums correctly. Page 2 parsed one
  number out of the pick-1 narrative and compared it to the header. The certifier is told on
  page 2 to "Resolve each row before handing this PDF to a certifier" about a discrepancy
  page 49 shows does not exist.
- **Page 2, "Handler chain: Other handler(s) named in event/OSP narratives: COC, COD,
  Cascadia Organic Certifiers."** The certifying agent, parsed out of free text, reported
  as an undeclared handler.
- Page 2 footer copy: "Trazo's value-add is catching these gaps first." Marketing in the
  inspector's document.
- Page 52, "Supply-chain traceability audit readiness: Producer attests that all event
  logs … are the same records that would be pulled for a certifier-initiated supply-chain
  traceability audit. Trazo infrastructure supports rapid retrieval (target: 24-hour
  response) …". Nobody signed this; the producer did not write it. A statement printed in
  the producer's voice that the producer never made, next to a platform performance promise.
- Page 3, "Last Updated 2026-10-07" on five of six v3 sections: the packet build's
  narrative refresh (2.1) is visible here too.
- "Inputs Not Matched …" section (page 12): the 12 rows again, each "Input 'X' not matched
  to any approved OSP input. Possible match, not confirmed: …" (here the candidate IS
  printed, unlike the app banner) with "Resolution: Name match only / (unresolved)" and an
  omri.org search URL. The dossier is more honest than the app on this.
- Page 3 "Approved by Certifier: Not recorded in Trazo · Certifier Template: —": fine, but
  "Active" next to "approval date not recorded" is the same chip problem as the app.
- CSV: 150 rows, one per event, with a specimen banner as row 1 and the readiness table
  absent; drift and reconciliation do not travel with the CSV. The CSV holds "Organic
  Status" as the grower's dropdown value with no catalog column.

### 2.4 Operation audit dossier (PDF, 448 pages)

File: `downloads/operation-dossier.pdf` ("Trazo Operation Audit Report — Calapooia Bend
Farm"). Built as a background job from the farm profile ("Prepare dossier" → "Gathering
operation-wide records…" → "Your dossier is ready … filed under Documents › Exports. An email
with the link is on its way."), 11 s on this database. Has a PDF outline and a contents table
with a page number per production (12 rows: parcel, crop, window, lot id, page).
Visual check `downloads/img-opdossier/p-001.png`, `p-115.png`: clean.

- It is twelve per-production dossiers back to back (each with its own "Documentation
  Snapshot"), plus an "Operation-Wide Records" chapter. The per-production defects in 2.3
  repeat twelve times: "100% materially complete" (pages for Duke 2026, Draper 2026,
  Liberty 2026 at least; three hits), the v3 "Last Updated 2026-10-07" rows, the
  "Producer attests … Trazo infrastructure supports rapid retrieval (target: 24-hour
  response)" paragraph.
- The pre-export consistency check (yield delta, handler chain) is NOT in the operation
  dossier. The false yield alarm lives only in the per-production PDF.
- 448 pages for a 6-parcel farm is what an inspector gets for "All productions"; the
  audit-window fields exist for narrowing it. Fine.

### 2.5 Records ZIP (`trazo-records-2-2026-10-07.zip`)

16 files: README.txt + 15 CSVs (business, carbon_entries, chemical, crew messages and
confirmations, general, parcels, pest, photos, production, productions, sale_harvest_links,
sales_records, soil, weather). Every CSV opens with the specimen banner as row 1 and the raw
column names as row 2. README states what is NOT in the export and where each lives (OSP
versions and filed updates → packet; materials list and identity decisions → packet;
facilities, certifications, amendments, edit history, equipment events → dossier; uploads →
Documents). `sale_harvest_links.csv` (33 rows) joins sales to harvest events. Honest and
complete for what it claims; ledger T12 (full relational export) stays open as filed.

- `carbon_entries.csv` (417 rows) carries columns `trust_score`, `verification_level`,
  `verification_status`, `additionality_verified`, `audit_status`,
  `third_party_verification_url`, `registry_verification_id`, `usda_factors_based`: the
  retired carbon-credit vocabulary, raw, in the operator's own records export. A certifier
  who opens it reads "trust_score" and "verified" about carbon. Values need checking before
  calling this misleading; the column names alone are the finding.
- `productions.csv` carries `reputation`, `confidence_score`: the retired score columns, in
  the export.
  Values checked: `trust_score` = 0.5 on all 417 rows, `verification_level` =
  `self_reported` on all, `verification_status` = `factors_verified` on 255 rows,
  `area_estimate` on 34, `no_factor_applied` on 128; `data_source` = "USDA Agricultural
  Research Service" on all 417 rows, `usda_factors_based` True on 255. A blanket "USDA"
  source on every carbon row (including the 34 area estimates and the 128 with no factor) is
  the blanket attribution `compliance.md` forbids, inside the operator's own records export.
  The 34 `area_estimate` rows are the per-hectare fallback R8-04 retired; this database has
  not had `recompute_unreported_carbon` run (the ledger lists it as a pending production
  step), so on production the same rows exist until it runs.
- `productions.csv`: `confidence_score` = 64.0 on 7 of 12 productions, `reputation` 0.0.
  The retired score, exported.

## 3. Output 2, read as the buyer

Anonymous context, 375 × 812, `consumer.localhost:3001/production/68cf4720-…` (Duke 2026 —
Home Field East). Screenshots `30-buyer-duke-en-375-viewport.png`, `31-…-full.png`,
`33-…-proof-full.png`, `34-…-impact.png`, `35-buyer-duke-es-375-full.png`,
`36-buyer-rex-expanded-{en-US,es-419}.png`, `37-buyer-carbon-{en-US,es-419}.png`.
Page height 9,208 px at 375 wide.

### 3.1 The 20-second shopper

What they get: a black "DEMO FARM" tag, the farm name, "Blueberries · Lot CBF-26-HFE ·
Harvested Jun 22 – Jul 6, 2026", a "60 practices documented" tile, then a location-consent
sheet ("Share your approximate location and time on page with this farmer? Declining still
counts your visit.") that covers the bottom tab bar until answered. The hero has no cover
photo (the specimen has no photos), so the first 900 px are a striped background. Below:
"Documented growing story", three tiles (Origin · Harvest · Records on file / Farmer-logged
records), and the disclosure line "Practice records are farmer-reported, not independently
audited. Certifications are labeled separately as Verified or Self-Reported."

Understood in 20 s: a farm, a lot code, a harvest window, a count of records, "demo". Not
understood: what "60 practices documented" buys them; that the certifications block says
"Demonstration record, not a certified operation" for the demo. The count is a count, not
a grade: the honesty rule holds.

### 3.2 The 5-minute skeptic

Every claim and the record behind it:
- "60 Farming Events Documented" → the timeline lists 60 cards in 6 groups (3 + 13 + 11
  + 18 + 10 + 4 = 59 shown plus "incl. 1 operational"). Backed.
- "121,250 LB · CBF-26-HFE · Lot and harvest records entered by the farm" → the four
  harvest cards carry 36,500 / 36,200 / 30,300 / 18,250 lb in the farmer's notes. Backed,
  and labelled as entered by the farm.
- Certifications: "Demonstration record, not a certified operation"; Real Organic Project
  "Specimen record, not checked against any registry". Withheld rather than claimed. The
  USDA Organic row is not shown at all on the specimen. Honest.
- Input chips: **"Organic-approved · grower-reported"** on Rex Lime Sulfur, Feather Meal
  (and the other 9). The rule for a grower's own answer is "recorded" or "as reported by
  the farm"; this chip leads with "Organic-approved". The Spanish is worse: **"Aprobado
  para uso orgánico · informado por el productor"** reads as "Approved for organic use" with
  the qualifier trailing. The expanded card adds "What's in it: Calcium polysulfide", "Area
  Treated 12.5 acres", "What it protects against: Mummy berry — dormant". Backed facts; the
  chip is the only overclaim.
- "Certificates and filings the farm recorded · 4 events … Entered by the farm. Independent
  confirmation, where there is any, is shown with the certification above." Then the OSP
  change-notice note: "COC acknowledged and approved the addition 26 Feb (ticket
  OT-26-01174)". Chip "Grower record". The farmer's own words say COC approved; the
  certifier packet (2.1) says that acknowledgment is not recorded. Both are honest about
  whose claim it is; a skeptic who reads both sees the farm asserting on the public page
  what it could not evidence to its certifier. That is the specimen's story, not a defect.
- "2026 organic certificate reissued — COC-1463 … The certificate number is published here,
  so this is a claim a buyer can check rather than take on trust." For a fictional certifier
  there is nowhere to check. On the demo this sits under "DEMO FARM"; on a real farm the
  sentence is true only if the certificate is in the OID.
- Carbon, last section, collapsed by default: "Growing 1 kg of Blueberries produced 0.076
  kg of greenhouse gases (as CO2 equivalent) from recorded farm work and purchased inputs.
  Counts the fuel and electricity this operation burns, plus the manufacturing of the
  fertilizer and crop-protection products it buys. Not a full life-cycle footprint …
  Fuel and electricity factors are EPA-published; phosphorus and potassium are Trazo
  estimates where published values are sparse. Each factor shows its own source." Scope and
  per-class sources stated. Passes.
- Farm block: "Purchased OMRI compost ([supplier withheld])": the redaction placeholder is
  visible to the shopper, inside the farmer's own soil-health list.
- Proof view (`?view=proof`): filter tabs, "Performed by: Farm team (J.M.)" initials, same
  chips. Nothing certifier-only leaks: no invoice numbers, no prices, no worker surnames, no
  readiness rows, no drift findings.

What a shopper would misunderstand: "Organic-approved" as a third party's approval;
"Verified or Self-Reported" in the disclosure line when nothing on this page is "Verified"
(the word is promised, never shown); "60 practices" as 60 different practices (they are 60
records, many repeats of scouting and irrigation).

### 3.3 es-419

Translated and neutral tuteo throughout the page copy ("Puedes ver…", "No la uses…").
Left in English: event titles and the farmer's notes (farmer-authored, expected), the crop
name "Blueberries" in the hero, "Datos de carbono de Blueberries", event subtypes "·
disease prevention", "· soil nutrition", "Calcium polysulfide", "Mummy berry — dormant".
The bottom tab bar reads **"Historia · Granja · Impacto"**: "Granja" where the project's
term is "finca" (the hero itself says "FINCA DE DEMOSTRACIÓN" and "Finca rastreada"). Two
words for farm on one screen.

## 4. The five journeys

### 4a. Sign-up, first farm, first season
Feeds: everything. A farm that cannot get through sign-up logs nothing; a farm set up with
the wrong framing (goals, claims) carries that into the buyer page.

Desktop, fresh context, `review-j1@trazo.test`, MailDev at :1080 (up).
Screenshots `40-signup-en.png` … `49-farm-created.png`.

What happened:
- Sign-up copy: "Set up your farm records. Log the season once. Trazo assembles your
  certifier packet from it." and "Starter plan free forever · No credit card". Right.
- The Terms checkbox: clicking the label text "I agree to the Terms of Service and
  Privacy Policy" opens trazo.io/terms-of-service in a new tab and leaves the box
  unticked; the submit then says "You must accept the terms and conditions". The box only
  ticks on its square. A first-time user who taps the sentence is sent away from the form.
- Password hints: "Password strength: Strong" and, under it, "Password contains common
  words or predictable patterns" for the same password. Two verdicts, one of them wrong.
- Verification mail arrived in MailDev (subject "Verify Your Trazo Account"); the welcome
  mail is still titled "Welcome to Trazo - Agricultural Transparency Platform", the retired
  tagline. The link worked and landed on company setup, signed in.
- Company setup, step 1 heading: "Create your company profile and start building consumer
  trust through transparency" (`AddCompany.jsx`): the retired events → transparency →
  consumer-trust framing, on the first screen a new farm reads.
- Company setup, step 3 "Sustainability Goals — Select your sustainability and transparency
  objectives": six tiles (Full Farming Transparency, Water Conservation, Soil Health
  Practices, Biodiversity Support, Waste Reduction, Clean Energy Use). Whatever is ticked
  prints on the public buyer page as "Sustainability Commitment"
  (`CompanyFarmInfo.tsx:324-336`, served via `farmer.company.sustainability_goals`). A
  checkbox at sign-up becomes a public environmental-benefit claim with no record behind it
  (16 CFR 260.4 class). Not ticked here, so not shown on J1; the input side is on
  `44-company-step3.png`, the output side is code-read.
- Farm wizard: four steps, "Certifications are managed in your Farm Profile with
  automated USDA Organic verification" (a promise of "verification" at the moment the user
  has no certificate; the profile later says "Specimen"/"Self-Reported" honestly). "Personal
  Message to Consumers". Saved as farm 3.
- Day-one farm home: "Certifier deadlines — OSP annual update (2026) — Not filed" on an
  operation that has never been certified; three readiness blockers, each with "Fix it here
  →" (OFPP "SOE 2024 … prohibits certification without a valid Organic Fraud Prevention
  Plan", "No Organic System Plan has been created", "no production records"), a "Getting
  Started 0 of 7" list. The blockers name the record and the next step. The deadline strip
  assumes a certified operation.
- First parcel: the quick form (name, acres) with "Need boundaries, crops, or contacts? Use
  the full form →". Saved in one step. Right.
- First season ("Quick Start Production"): crop type search, then "Crop template — Start
  from the operations typical for this crop — every one stays yours to accept or skip";
  picking "Blueberries - Organic Production" shows "21 practices suggested for this crop —
  you choose which go on your plan" and a "Season plan" checklist: "Nothing here is a
  record. Ticking a practice adds it to your season checklist — you log it". Exactly the
  plan-not-record line. Submitted without ticking anything: the production exists
  (`history_history` 25, `production_method = organic`, type `OR`) with **0 plan items**.
  Nothing told the operator that an unticked template adds nothing; the page after submit
  shows "Records: 0" and a chip "NT".
- The floating "Getting Started · 2 of 7 complete" panel (bottom right at 1366 × 900) sits
  over the parcel's production card; a click on the card lands on the panel ("Share your QR
  code" intercepts pointer events, Playwright log). The operator cannot open the season they
  just created from the parcel page without scrolling the panel away.
- Production page of the new season (`56-production-page-j1.png`): the template's own
  blurb landed in the production's Description, "Organic production template for Blueberries
  using organic production practices. All 7 event types with organic-specific defaults."
  That field is marked as shown on the public page. A sentence Trazo wrote about its
  template becomes the farm's public description of its season, unless the operator
  notices and deletes it. The plan-not-record rule held for plan items; the description is
  the leak.
- "QR Code & Consumer Access — Not yet visible to anyone who scans. This lot's page goes
  live when you finish the production." Right. "ADDRESS: Tangent, -" (no state): the
  address line formatter prints a dash for a missing part on Calapooia too.

Where the journey goes wrong downstream: a season started with no plan items gives the
manager no checklist and the certifier no "planned vs logged" view; a public description
written by a template reads as the farm's claim on the buyer page.
### 4b. Crew lead daily logging (es-419, 375 px)
Feeds: the input records behind the materials list, the drift findings, the audit dossier's
application table, the buyer page's Crop Inputs. A record the crew lead cannot save, or saves
twice, or saves with the wrong time, is wrong in every output.

Fresh mobile context, 375 × 812, es-419, signed in through the real form as the owner
account (the crew-lead persona). Screenshots `60-crew-signin-es.png` … .

Sign-in in Spanish: "Bienvenido de nuevo. Tus registros de la finca te esperan." Tuteo,
"finca". Right.

Wizard step 1 (`62-`, `63-`): verbs translated. Left in English: "Required" (chip on
"¿Cuál fue?"), "When did this activity occur and who performed it?". Both on the ledger's
open list; still there.

Step 2, Fungicida (`64-crew-step2-es.png`): translated except "Fungicide Concentration*",
its two help lines, and the receipt-file option names (specimen titles). New findings in
the Spanish copy:
- "Información de confianza para el consumidor — A los consumidores les importa saber si los
  productos usados en sus alimentos están aprobados para uso orgánico … Esa transparencia
  genera confianza en tus prácticas." The retired transparency → consumer-trust framing,
  as a help block inside the input form (English equivalent present).
- "La no conformidad más frecuente a nivel nacional es la documentación insuficiente de
  balance de masa." A national statistic with no source, in form help text
  (`compliance.md` rule 1).
- "Mis productos" offers "Producto Prueba 301", the leftover test record.
- Date-time field accepted `2026-10-06T23:30` (farm wall clock) for the ADR-011 trace.
- Lookup of "Producto Prueba REVIEW-2026-10" (`65-crew-lookup-nomatch-es.png`): "Sin
  coincidencias en OMRI, WSDA ni la Lista Nacional. Puedes guardar el registro; eso no
  significa que el insumo esté permitido. Consúltalo con tu certificador." Right, and
  translated. Basis set to "Sin confirmar todavía (a consultar con mi certificador)".
- Step 3 (`66-crew-step3-es.png`): "Preview" in English; "Pegar con ⌘V" on a phone;
  usted in the photo block ("Agregue fotos de su finca", "Muestre el tamaño del envase")
  beside tuteo everywhere else (ledger open item, still open).
- Offline at save (`67-crew-offline-save-es.png`): toast titled "Error", body "Sin
  conexión, así que todavía no se guardó. Lo que escribiste sigue aquí y queda como borrador
  en este dispositivo; vuelve a guardar cuando tengas señal." Form stayed on step 3 with
  the draft. Right. The title "Error" is the only off note: nothing went wrong.
- Online retry (`68-crew-online-retry-es.png`): "Éxito — Evento creado exitosamente", then
  the completeness nudge "Guardado — un certificador también pedirá: Plaga/enfermedad
  objetivo, Qué muestra que el insumo está permitido (base orgánica)". The basis WAS given
  ("Sin confirmar todavía"); the nudge asks for it again, so the honest answer "not yet
  confirmed" reads to the crew lead as "you forgot a field". One record created (checked in
  the database below).
- After save the app lands on the PARCEL page, not the production: a list of all the
  parcel's events with English fragments in the Spanish page ("Area Covered", "No CO₂
  data", "Tillage", "Soil Testing", "DE INSUMOS REGISTRADOS"), a Google Maps "For
  development purposes only" overlay (dev key), and per-event carbon numbers ("3833 kg
  CO₂e" for a compost spread). The crew lead who just saved one record is shown the whole
  parcel's history to scroll.
- Database after the retry: exactly one `ChemicalEvent` (id 90) on Onions 2026, `date =
  2026-10-06 23:30:00+00` (the farm wall clock, stored as typed), `organic_approved =
  unverified`, `drift_warning.reason_code = unresolved`, volume 5, area 14.2,
  concentration "10%". Offline save lost nothing and created nothing twice.
- The farm home now says "13 productos registrados no están en tu lista de materiales"
  (was 12): the review's own unknown input joined the list, as it should.

ADR-011 trace of record 90 (logged 23:30 farm time):
| surface | shows | right? |
|---|---|---|
| timeline card, production page (es) | "6 oct 2026" | yes (date only) |
| proof view card | "6 oct 2026" | yes |
| edit form | `2026-10-06T23:30` | yes |
| buyer page (after close, 4c) | "6 oct 2026" | yes |
| certifier page | not listed per record (findings only) | n/a |
| per-production CSV | `2026-10-06` (date column only) | yes |
| per-production dossier and certifier-link dossier | "2026-10-06" | yes |
No surface shifted the date; no output prints the time at all (the application table,
CSV and buyer card are date-only), so a 23:30 record and a 06:00 record are
indistinguishable everywhere but the edit form. ADR-011 holds; the time is simply absent
from the outputs.
- Full record modal in Spanish (`72-crew-full-record-es.png`): date only ("6 oct 2026"), no
  time and no carbon line (ledger open item, still open). English inside the Spanish modal:
  "Ground Spray", "Not yet confirmed" (the stored basis, shown under "Estado Organico" with
  the marker "En tu página de comprador"), "Additional Details". The field the modal says a
  buyer will see carries an untranslated English value.

Harvest from a template (`73-crew-harvest-template-picker-es.png`, `74-…`):
- Step 1 "Cosecha" offers "Cosecha / Poscosecha". Step 2 of a production activity in
  Spanish still carries "Auto-generated from production type. Customize for multi-pass
  harvests, etc.", "Essential for calculating carbon emissions per hectare", and the unit
  list "Hectares / Acres / Square Meters / Square Kilometers" in English (ledger open items,
  still open). "Loading..." and "Guardando borrador…" flash on entry.
- "Usar una plantilla" opens "Elige una plantilla: Siembra, Riego, Cosecha, Poda,
  Trasplante, Cultivo mecánico, Raleo, Mantenimiento de equipo, Búsqueda de semilla
  orgánica". Translated.
- After "Cosecha" from the template: "Plantilla aplicada — Cosecha"; Cantidad cosechada,
  Área cubierta, combustible, horas de equipo all EMPTY (checked field by field). The
  template produced no values. Right. What it did prefill: "Nombre de la actividad" =
  "Harvesting" (English) and "Eficiencia" = "Normal Efficiency (standard operation)"
  (ledger: "Eficiencia: normal arrives preset", still true, and in English here).
- English in the Spanish harvest form: unit lists ("Kilograms / Tonnes / Pounds / Boxes /
  Bins / Plants / Seeds", "Gallons", "Kilometers"), "Select harvest method (optional)",
  "Hand Picking / Selective Hand Picking / Mechanical Harvester / Shake and Catch / Strip
  Picking", "How the crop was harvested (consumer trust indicator)", "Harvest Summary
  Mode", "Log multiple harvest picks as one summary record to reduce logging burden while
  maintaining full transparency.", "Select fuel type...". Usted in "Su certificador la
  usa…", "Seleccione la categoría de su registro de empaque…", "indíquelo y señale".
- The equipment-cleaning link dropdown offers "2026-10-06 — Equipment Maintenance": the
  leftover test record, one tap from being cited as the cleanout that covers this harvest.
- Harvest saved: `ProductionEvent` 229, type HA, 1,000 lbs, lot `REVIEW-2026-10-H1`,
  area 14.2, fuel NULL, hours NULL, `production_efficiency = normal` (the preset went in),
  name and description "Harvesting" (the English prefill went in as the record's name).

Cleanout (`76-crew-cleanout-step2-es.png`):
- Step 2 opens with "Registro solo para el certificador — no se muestra en tu página de
  comprador. Una bitácora de limpieza … revela el manejo de una operación dividida, así que
  queda fuera de tu página de comprador". Right, and the categorical policy is stated to
  the person logging.
- The cleanout verb prefills "Nombre de la actividad" = "Equipment Maintenance" and
  "Tipo de operación" = "Cleaning - Equipment cleaning (NOP 205.272)". A crew lead who
  leaves the name alone files a cleaning record titled "Equipment Maintenance"; that is
  exactly what the leftover test record is called, and what the harvest form's
  "cleaning event that covers this pass" dropdown then shows. The certifier's cleaning log
  reads "maintenance" where it should read "cleanout".
- English in the Spanish cleanout form: every option list ("Fuel Consumption - Regular
  operation", "Tractor / Harvester/Combine / Sprayer …", "High Efficiency (well-maintained,
  optimal conditions)"), "Specify equipment operation type and equipment used for accurate
  carbon emission calculations.", "Document equipment cleaning per NOP 7 CFR 205.272…",
  "Person who performed or verified the cleaning", "Cleaning agents used (must be
  NOP-approved for organic operations)". The sanitizer block below it is fully
  translated and states the § 205.605(b) chlorine limit and "for other sanitizers, record
  the reading; Trazo does not evaluate a limit for them". That block is the model.
- Cleanout saved with no fuel and no hours (`78-crew-cleanout-card-es.png`). The card on
  the production page (proof view): "REVIEW-2026-10 limpieza de cosechadora · 6 oct 2026 ·
  Uso o mantenimiento de equipo agrícola registrado · Se registró la limpieza del equipo
  antes de este trabajo en el cultivo." chip "Solo certificador". Expanded: equipment
  type, operation "Limpieza", date, method, materials. No carbon line on the card or the
  expanded card at all, so the ledger's "reads Sin estimar" could not be observed on this
  surface; the API value is checked below.
- The leftover test record sits beside it as "Mantenimiento de equipos · 6 oct 2026 · Solo
  certificador": a maintenance-titled cleanout from an earlier pass, on the open season the
  crew logs into.

Voice (`79-crew-voice-es.png`, `80-…`): "Entrada por voz — Describe la actividad y
completamos lo que podamos. Revisas cada campo antes de guardar. Hablar en: English /
Español. Prueba diciendo: «Apliqué fertilizante hoy, 200 libras por acre, NPK 10-10-10»…".
Translated, with Spanish examples. "Iniciar entrada por voz" in this headless context (no
microphone) produced no message of any kind within 5 s: no "no words captured", no "no
microphone", no toast. The ledger's pass saw the no-words message with a real microphone;
the no-device branch is silent. Environment-dependent; reported as seen.

Carbon on the records this journey created (database, `carbon_carbonentry`):
| event | basis recorded | stored entry |
|---|---|---|
| ChemicalEvent 90, unknown product, 5 gal | no catalog match, basis "not yet confirmed" | 39.94 kg CO₂e, `verification_status = factors_verified`, description "verified_epa_usda_factors", `data_source` "USDA Agricultural Research Service" |
| ProductionEvent 229, harvest, 14.2 ac, no fuel, no hours | area only | 41.07 kg CO₂e, `verification_status = area_estimate`, description "verified_epa_usda_factors_with_electric_support", `usda_factors_based = false`, same USDA data_source |
| ProductionEvent 230, cleanout, no fuel | nothing | no entry (right) |
An unknown product with no listing got a "verified" factor; a harvest with no fuel got a
per-area guess stored as a number. What is SERVED on the buyer page from these rows is
checked in 4c below after the season closes (the R8-04 fix nulls `area_estimate` on the
way out; the unknown-input row is not an area estimate and has no such guard).

Where journey b goes wrong downstream: a crew lead who logs honestly produces one correct
record per save; what the outputs then do with it (an unresolved drift row in the packet,
a "verified" carbon factor on an unknown product, an English prefill as the record's name)
is the defect, not the logging.
### 4c. Manager closes a Calapooia season
Feeds: the buyer page (publish happens here), the packet's audit trail and the dossier's
yield-to-sales reconciliation (lot id, production amount, finish date), the records ZIP.

Owner, desktop, en-US, Onions 2026 — Upper Terrace (production 23, the season the crew
lead logged into in 4b). Screenshots `85-finish-production-form.png`,
`86-finish-step2.png`, `87-finish-confirm-dialog.png`, `88-finished-production.png`.

- Step 1 "Harvest Output": Production amount prefilled 349,000 lb (the sum of the
  season's harvest records, including the review's 1,000 lb), unit, Lot Number (empty,
  required), Finish date, then an optional "Quality & Harvest Details — Printed in your
  certifier packet alongside the lot number and yield. Not shown to consumers." and notes
  "for your certifier and your team. Not shown on your buyer page." A "Still needed: Lot
  Number, Finish date" line names what is missing. Right.
- Step 2 "Media Upload": photos, then a "CONSUMER PREVIEW" of the cover. Then the confirm
  dialog: "Finish this season? Closing it makes the season read-only … Trazo keeps this
  record for 5 years … the retention period 7 CFR 205.103(b)(4) requires … This season
  becomes available to your certifier packet and OSP renewal export … Publish the buyer
  page now [on by default] — Anyone scanning this lot's QR code sees the practices you
  documented. You can hide it again any time from the Buyer Page … a mistake is corrected by
  recording an amendment beside the original … not by editing it away." The one place in
  the product that explains both outputs at once, and it does it well. Publish is a
  season-level switch, on by default, visible before the irreversible step.
- Filled: lot `REVIEW-2026-10-ONIONS`, finish 2026-10-06 18:00, notes marked
  REVIEW-2026-10.
- After confirm: no toast; the app lands on the parcel page, where the season reads
  "COMPLETE · Apr 1, 26 - Oct 6, 26 · Records: 27 · Lot REVIEW-2026-10-ONIONS · No sale
  recorded". Database: `published = true`, `finish_date = 2026-10-06 18:00`, 349,000 lb.
  The production page now shows the drift banner "6 events reference inputs not in your
  active OSP" (the 5 seeded onion inputs plus the review's unknown input; the leftover
  "Producto Prueba 301" is among them).
- Buyer page of the closed season, anonymous, 375 px, es and en
  (`89-buyer-onions-{es-419,en-US}-full.png`, `90-buyer-onions-review-input-es.png`):
  "Onions · Lote REVIEW-2026-10-ONIONS · Cosechado 17 ago – 6 oct 2026 · 25 prácticas
  documentadas". The review's harvest shows as "Harvesting · 6 oct 2026 · Cosecha
  registrada" (English title on the Spanish page; the date is right). The review's unknown
  input shows "Producto Prueba REVIEW-2026-10 · disease prevention · 6 oct 2026 · Insumo
  documentado" (neutral chip; anonymous payload `input_status = {status: unclassified,
  label: Documented}`, `organic_approved = unverified`). The cleanout and the leftover
  "Equipment Maintenance" record are withheld (categorical policy, confirmed). The
  leftover "Producto Prueba 301" is now PUBLIC on the demo farm's buyer page because this
  review closed the season it sits on; the reseed removes it.
- Anonymous payload carries `blockchain_verified: false` on every event. The value is
  false, the add-on is withdrawn, and the key is still served to the public.
- ADR-011 on this page: the 23:30 record prints "6 oct 2026" (date only); the harvest
  window "17 ago – 6 oct" uses the stored dates. Right.
- Carbon: "Producir 1 kg de Onions generó 0.035 kg" with the scope and per-class source
  sentence. Whether the review's two new entries (an area estimate and an unknown-product
  "verified" factor) are inside that 0.035 is checked against the public carbon payload
  below.

Where journey c goes wrong downstream: nothing in the close itself; what it publishes
is whatever the crew logged, test records included.
- **Public carbon payload** (`GET /api/transparency/6823d524-…/`, anonymous):
  `carbon_impact.total_emissions = 12294.0`, `kg_per_kg = 0.035`. The database rows for
  this production sum to 12,294.0 = 12,211.9 (`factors_verified`, 16 rows, including the
  review's unknown product at 39.9) + 82.1 (`area_estimate`, 2 rows, including the
  review's fuel-less harvest at 41.1) + 0 (`no_factor_applied`). The per-area guesses R8-04
  retired on the event cards are still inside the number a shopper reads, and so is a
  "verified" factor for a product nobody could find. Same payload:
  `methodology.carbon_scope = "Direct operational emissions only (EPA/USDA-sourced
  factors)"` (both phrases on the `compliance.md` UNSAFE list: a blanket "EPA/USDA" and
  "direct on-farm emissions only" when manufacturing of inputs is counted),
  `calculation_method = "USDA_EPA_factors"`, and `consumer_context.per_kg_miles = 0.1`,
  `per_kg_phone_charges = 11` (the car and phone equivalents R8-14 removed from the page,
  still served). The page copy itself is right; the payload under it is not.
### 4d. Annual update and renewal packet
Feeds: the renewal packet (02 annual update, 02s routing, 03 notifications) and the
certifier's own renewal form. A filing that says the wrong thing, or that cannot be filed,
is the renewal.

Owner, desktop, en-US. The 2027 revision-1 draft that the seed left open is used; the two
frozen 2026 revisions are untouched. Screenshots `91-annual-update-edit.png` …

- Edit (`91-`): "Continuation year 2027", "Summary of Changes (§ 205.406(a)(1))",
  additions and deletions planned, six "Sections unchanged since the prior OSP" boxes with
  "Mark all unchanged", the (a)(3) "Business name, address, telephone and the person
  responsible … are unchanged" box ("The filing prints your answer either way"), (a)(4)
  text and "My certifying agent asked for nothing further this year". The draft's summary
  was EMPTY, which the row above rendered as "No changes — OSP reaffirmed": an empty field
  shown as an affirmative statement. Filled with a REVIEW-2026-10 summary; "Mark all
  unchanged" ticked all eight boxes; "Update Filing" → "Annual update saved".
- A toast "Drift detection runs against the farm's currently active OSP. Edits here apply
  to this version when it is activated." fires on this save too; it belongs to the inputs
  panel, not to the annual update.
- Sign: an inline panel, not a dialog: "Signing records your name and the date against
  exactly what this update says. After signing it cannot be edited; a change is made as a
  correction. Your title (optional)". Right.
- Signed with title "Member-manager": "Update signed", row chip "Signed, not filed", then
  "Record filing": "Date filed with your certifier" (prefilled today) and "How it was
  filed" (Not recorded / Agent's web form / Agent's client portal / Email / Mail / In
  person). "Record as filed" → "Filing recorded. The packet now carries it exactly as
  filed." Row: "Filed Oct 7, 2026 · Filed · Create correction · Withdraw"; status line
  "Annual update 2027: Filed. Nothing pending. A change goes through Create correction on
  its row." (`96-annual-update-filed.png`).
- Database row 5: `snapshot_state = frozen_at_filing`, `filed_sha256 =
  0ba8ed0d…`, `signed_content_sha256 = d0b87c03…`, `filing_method = email`.
- v4 packet downloaded after filing (`downloads/calapooia-bend-farm-osp-v4-packet-after-filing.zip`):
  `annual-update/2027-revision-1.pdf` hashes to `0ba8ed0d…`, the row's `filed_sha256`. The
  packet ships the frozen bytes. 02 prints the REVIEW summary, "Filed: 2026-10-07
  (Email)", the six sections attested unchanged, the (a)(3) and (a)(4) attestations, the
  2026 sales subtotal "(not reconciled)", and "Signed in Trazo by Pass Owner,
  Member-manager on 2026-10-07. Signed content: sha256 d0b87c03…". 02s lists revision 1
  as "the current filing for the year" with the same hash. The cover gained "Productions
  closed after the plan's answers were written — 1 • Onions 2026 — Upper Terrace —
  2026-10-06". The filing chain works end to end.

What does not:
- **"(a)(2) Additions intended for the coming year (2028)" on a continuation for 2027.**
  The form's own help text says "A renewal due 1 March 2026 continues 2026 and reports on
  the 2025 season", so the year the additions are intended for IS the continuation year;
  the renderer prints continuation year + 1 (the 2026 revision 3 likewise says "(2027)").
  Either the help text or the heading is wrong; a certifier reading "intended for 2028" on
  a 2027 renewal will ask.
- The signature line names the ACCOUNT ("Pass Owner"), not the responsible person the
  cover names ("Laurel Brandt"). On the specimen that is the seed's login; on a pilot farm
  set up by Trazo staff it is whoever was signed in. The signer is a fact about the
  session, and the packet presents it as the operation's attestation.
- The summary of changes is free text with no check against the plan review on the same
  page: the 2027 filing says "No change to … inputs" while the plan-review panel above it
  lists 22 record types the plan does not confirm and the farm card lists 13 unmatched
  products. Nothing connects the two; the certifier gets the attestation and the
  contradiction in the same ZIP (02 vs cover).
- The "Drift detection runs against the farm's currently active OSP" toast fires on sign
  and on file as well as on save.

Where journey d goes wrong downstream: the heading-year defect lands in the certifier's
hands on every filing; the free-text summary lets a grower attest "no changes" against a
plan Trazo itself flags as moved.
### 4e. Sharing with the certifier, both sides
Feeds: the certifier's pre-inspection read. What the link shows is what the inspector
walks in with.

Owner side (desktop, `97-certifier-link-created.png`): farm profile → "Share with your
certifier": label, period (Current year 2026 / Last 12 months / All records), "Create
link" → "Certifier link created"; row "REVIEW-2026-10 certifier link · 0 · Jan 1, 2026 –
Dec 31, 2026 · Expires Jan 5, 2027 · Revoke". The link URL itself is in the row (copy).
The card repeats the whole-operation warning ("13 logged products are not on your
materials list") above the form; it is a warning, not a blocker, so the link was created.

Certifier side (fresh signed-out desktop context, `98-certifier-review-page.png`):
`/certifier-review/<token>` opened with no account and no cookies. "ORGANIC AUDIT DOSSIER
· Calapooia Bend Farm · Tangent, OR · Covering Jan 1, 2026 – Dec 31, 2026 · RECORD
READINESS · These are documentation checks on the records in Trazo, not a compliance
decision." Then, per production, the readiness rows with chips "For review" / "Not
assessed" / "Missing", each with "In the dossier: <section>". One button: "Download audit
dossier (PDF)".

What reads right:
- No account, no sign-in, the disclaimer first, every row named with its CFR section and
  the dossier section it points to.
- The compost rows say what is missing and why: "C:N 18:1 is outside 25:1-40:1. Manure
  interval assessment unresolved; missing: whether the C:N is the starting mix or a
  finished-product analysis (supplier documentation of the composting process)."
- Land requirements: "self-reported — no USDA Organic Integrity Database match on file.
  The 36-month determination under § 205.202(b) is the certifying agent's."

What does not:
- Grower instructions printed to the certifier: "Sales documentation — For review — Add
  buyer + organic-on-invoice flag"; "Lot traceability — For review — Lot ID assigned at
  finish". These are the farm card's fix-it strings, shown to the person who cannot fix
  them.
- "Inputs not matched to the plan's inputs list, a plan change to notify (§ 205.400(f)(2))
  — For review — 12 input record(s) not matched …" on every production (12 Duke, 14
  Draper, 4 Carrots BGB, 3 Spinach, 1 Carrots BGA …). The brand-versus-listing count,
  now phrased to the certifier as "a plan change to notify", for inputs that are on the
  plan.
- "Not assessed" rows ("No compost events this period", "No raw manure events this
  period", "Documentation depth — 65 events, 0 photos …") are listed with the findings
  and counted; a certifier scans 46 rows to find the 21 that carry a finding.
- Ledger deferred "finding-to-record deep links" and "row details still in English"; both
  still as deferred (rows are English here because the viewer is English; the Spanish
  certifier case was not exercised).
- Onions 2026 (the season closed in 4c) on the certifier page: "Record completeness,
  applications (§ 205.103(b)(2)) — Missing — 2/5 chemical records missing required fields
  — target pest or disease (2), what shows the input is allowed (organic basis) (2)". One
  of the two is the review's record, whose basis is "Not yet confirmed (to check with my
  certifier)". The certifier is told the basis is MISSING when the grower answered
  honestly that it is unconfirmed. Same mis-count as the save-time nudge in 4b, now on the
  certifier's screen. "Input traceability — Missing — 3/5 inputs have supplier — fill
  before audit": again an instruction to the grower, addressed to the certifier.
- Counts on this page: 19 "For review", 25 "Not assessed", 2 "Missing".
- "Download audit dossier (PDF)" → "Preparing the dossier from the operation's current
  records…" → the file downloaded (`downloads/certifier-link-dossier.pdf`). The footer
  says "Built from the operation's current records; a new copy is generated whenever the
  records change. This link expires Jan 5, 2027." Right.
- Owner side after the certifier's visit: the link row reads "3 · Show activity (3
  opens)" (metadata, readiness, dossier: one access-log row each). Right.
- Certifier-link dossier (`downloads/certifier-link-dossier.pdf`, 258 pages, outline
  present; visual check `downloads/img-cert/p-*.png`): the Onions 2026 chapter (pages
  235-242) shows the review's three records. Land requirements, page 235: **"Organic
  Transition Status: Not established from records in Trazo — 2 input(s) on this parcel
  inside the 36-month window have no organic status recorded (Producto Prueba 301 …;
  Producto Prueba REVIEW-2026-10 …), so no start date can be fixed (§ 205.202(b))"**, on a
  parcel the same page says "the operation states … is currently certified organic" and
  managed since 2007. The review's record HAS a recorded status: "Not yet confirmed". The
  sentence calls an unconfirmed basis "no organic status recorded" and, from one such
  record, declines to fix a transition start date for a parcel certified for twenty years.
  The parcel application's own tab (`100-parcel12-transition-after-review.png`) flipped
  from "No prohibited input on record" to "Not established: input status not recorded" the
  moment the record was saved. Unknown is still not prohibited here (right), but one
  honest "not yet confirmed" answer now outweighs the certificate on file.
- Application table, page 241: the review's input prints "2026-10-06 · Fungicide ·
  Record description · Fungicide application: Producto Prueba REVIEW-2026-10". Equipment
  table, page 242: "2026-10-06 · Equipment Maintenance · REVIEW-2026-10 limpieza de
  cosechadora" (the cleanout under the "Equipment Maintenance" type label) beside
  "Equipment Maintenance · Equipment Maintenance" (the leftover). Harvest table:
  "2026-10-06 · REVIEW-2026-10-H1 · 1,000 lb · Estimated · Stored on farm". The
  per-production CSV (`downloads/onions-2026-dossier.csv`): the input row carries
  "Not yet confirmed: what shows it is allowed is still to be checked" in the Organic
  Status column and "unresolved" in the drift block; the harvest row is named
  "Harvesting,Harvesting" with a computed "70.42 lbs/acre".

- Certifier-link dossier p.237 (visual check `downloads/img-cert/p-237.png`, clean layout):
  the Onions snapshot table prints **"GAP"** in red for "Record completeness — chemical …
  what shows the input is allowed (organic basis) (2)" and "Input traceability — 3/5 inputs
  have supplier — fill before audit". GAP is defined on the same page as "a required record
  appears to be missing"; the basis was recorded as unconfirmed. F-08 reaches the dossier
  in red.

Where journey e goes wrong downstream: the certifier opens a page that lists the
grower's to-do strings, counts an honest "not yet confirmed" as a missing field, and
reads the brand-versus-listing count as "a plan change to notify" on every season.

## 5. Ranked findings


Severity: **F** = false or misleading · **B** = blocks a renewal · **S** = slows the work ·
**P** = polish. "seen" = browser (B), downloaded document (D), code only (C), anonymous API (A).

| id | surface | what the user sees | evidence | seen | why it matters | sev |
|---|---|---|---|---|---|---|
| F-01 | farm card, production banner, certifier link card, certifier page, packet materials module + workbook, dossier | "12 input records not matched to the plan's approved inputs", "12 events reference inputs not in your active OSP … you must immediately notify your certifier", "[REVIEW] 12 product name(s) … do not match", "a plan change to notify" | 02, 03, 15, 98; packet `modules/materials_application.pdf` p.1; dossier p.12; DB: 81/81 chemical events `unresolved`, 0 OMRI links, 0 identity decisions, candidate stored in `reason_params.possibleMatches`; `drift.reason.unresolved` drops it | B, D | A certifier is told twelve inputs are off-plan on a farm whose plan lists them under their OMRI names; the grower is told to file a change notification. The policy (never fuzzy-match) is right; the wording states the policy as a fact about the catalogs. | F |
| F-02 | buyer page (anonymous payload) | "Growing 1 kg of Onions produced 0.035 kg…" | `GET /api/transparency/6823d524…/`: `total_emissions 12294 = 12211.9 factors_verified + 82.1 area_estimate`; `carbon_scope "Direct operational emissions only (EPA/USDA-sourced factors)"` (`transparency_views.py:401`), `calculation_method "USDA_EPA_factors"` (`:290`), `per_kg_miles 0.1`, `per_kg_phone_charges 11`, `blockchain_verified false` on every event | A, D | The shopper's number includes per-area guesses and a "verified" factor on an unknown product; the payload carries the two phrases `compliance.md` forbids and the equivalents R8-14 removed. | F |
| F-03 | per-production dossier p.2 | "Yield reconciliation — header 121,250 lb · narrative 36,500 lb · delta 69.9%"; "Handler chain … COC, COD, Cascadia Organic Certifiers"; "Resolve each row before handing this PDF to a certifier … Trazo's value-add" | `downloads/duke-2026-dossier.pdf` p.2 vs p.49; DB `yield_quantity` 36,500+36,200+30,300+18,250 = 121,250 | D | Page 2 tells the certifier of a yield gap that page 49 shows does not exist, and names the certifier as an undeclared handler. | F |
| F-04 | per-production and operation dossiers p.1/p.3 | "v3 Active … 100% materially complete"; "Section Completion (material): 100%"; "Complete — 11,238 characters" | duke p.1, p.3; op dossier ×3 hits; `audit_export_service.py:3606` | D | A percentage and "Complete" in the certifier's first table; the app removed its bar in run 8, the documents kept it. | F |
| F-05 | dossiers p.52 (×12 in the operation dossier) | "Producer attests that all event logs … Trazo infrastructure supports rapid retrieval (target: 24-hour response)" | duke p.52 | D | An attestation in the producer's voice that no one signed, beside a platform promise, in an inspector's document. | F |
| F-06 | packet 01, dossier OSP table | "Submission Snapshot v3 · Submitted 2026-08-21 · Last updated: 2026-10-07" | `osp_module_pdf.py:3171,3160` (`_refresh_narratives_if_editable` on `active`); DB `updated_at` of OSP 6 moved during the download; `submission_pdf` empty for v3; dossier discloses "Trazo holds no copy generated at submission", the packet does not | D, DB | Downloading a packet rewrites the on-file plan's narrative and dates it today; a plan activated without a submit step has no frozen text and the packet says nothing. | F |
| F-07 | packet 02 (every filing) | "(a)(2) Additions intended for the coming year (2028)" on a continuation for 2027 | `osp_module_pdf.py:1924` (`reporting_year + 1`); help text `osp.annual.reportingYearHelp` | D | Off by one against the form's own definition of the continuation year; a certifier will query it. Oscar's call on which is right. | F |
| F-08 | save nudge, certifier page, parcel transition tab, dossier p.235 | "a certifier will also ask for … what shows the input is allowed (organic basis)"; "Missing — organic basis (2)"; "Not established: input status not recorded … no start date can be fixed" | 68, 98, 100; `certifier-link-dossier.pdf` p.235; DB `organic_approved=unverified` | B, D | The honest answer "not yet confirmed" is reported as a missing field to the grower and the certifier, and one such record unsets the transition date of a parcel certified since 2006. Unknown is still not prohibited (right); unknown is treated as unanswered (wrong). | F |
| F-09 | buyer page and producer timeline chips | "Organic-approved · grower-reported" / "Aprobado para uso orgánico · informado por el productor"; tooltip "Trazo did not find it in the OMRI or National List catalogs" | 17, 31, 36; DB: Rex Lime Sulfur and Entrust SC carry `national_list_substance_id` with basis `legacy_unverified` | B | "Approved" leads a chip for a grower's own answer; the tooltip is false for the two inputs with a National List link. | F |
| F-10 | records ZIP | `carbon_entries.csv` columns `trust_score` (0.5 ×417), `verification_level self_reported`, `verification_status factors_verified` (255), `data_source "USDA Agricultural Research Service"` (×417 incl. 34 area estimates); `productions.csv` `confidence_score 64.0` ×7 | `downloads/records-zip/` | D | The operator's own records export carries the retired score and a blanket USDA source on every carbon row. | F |
| F-11 | company sign-up → buyer page | "Sustainability Goals: Full Farming Transparency … Clean Energy Use" tiles; public "Sustainability Commitment" list | 44; `CompanyFarmInfo.tsx:324-336`, served as `farmer.company.sustainability_goals` | B (input), C (output) | A checkbox at sign-up becomes a public environmental-benefit claim with no record (16 CFR 260.4). | F |
| F-12 | new season, production description | "Organic production template for Blueberries using organic production practices. All 7 event types with organic-specific defaults." in the public Description | 56 | B | Trazo's template blurb becomes the farm's public season description unless deleted. | F |
| F-13 | cleanout records in certifier tables | cleanout verb prefills name "Equipment Maintenance"; certifier dossier p.242 lists the cleanout under "Equipment Maintenance"; harvest form offers "2026-10-06 — Equipment Maintenance" as the covering cleanout | 76; `certifier-link-dossier.pdf` p.242; `activityVerbs.ts:153` | B, D | The cleaning log the certifier reads says "maintenance". | F |
| F-14 | annual update row | empty summary shown as "No changes — OSP reaffirmed" | 05, 91; `osp.annual.noChanges` | B | An unfilled draft is rendered as an affirmative attestation. | F |
| F-15 | packet 04 (OTCO/CCOF/WSDA) | "the route is not determined (certifying agent not recognised, or none named)" ×42-54 | `v4-otco/04-coverage-and-scope.pdf` p.2-3; `certified_parcel_branch.py:279-303,731` | D | The parcel's own prior-certifier answer drives the route; the sentence reads as if about the addressed agent, and repeats per question per parcel. | S |
| F-16 | certifier page | "Add buyer + organic-on-invoice flag", "3/5 inputs have supplier — fill before audit"; 25 "Not assessed" rows among 19 findings | 98 | B | The certifier reads the grower's to-do list and scans 46 rows for the 21 that carry a finding. | S |
| F-17 | packet PDFs | no outlines; 06 index 32-33 pages without per-form page list; cover contents without page numbers | `v3-coc/*.pdf` (no `/Outlines`); dossier has one | D | An inspector pages through 33 pages to find C11. | S |
| F-18 | Spanish producer surfaces | farm card season row raw English; wizard "Required", "When did this activity occur…", "Fungicide Concentration", unit lists, option lists, "Preview", prefills "Harvesting"/"Equipment Maintenance"; plan-review items; event subtypes; parcel-page fragments; usted pockets; "Plan Orgánico del Sistema" | 14, 63, 64, 68, 74, 76, 16 | B | The crew lead's daily screens are half English; the prefills land in the record as its name. | S |
| F-19 | parcel page / getting started | "Getting Started · 2 of 7" panel intercepts clicks on the production card | 55 (Playwright click log) | B | A new farm cannot open the season it just created from the parcel page. | S |
| F-20 | sign-up | Terms label opens the terms site and leaves the box unticked; "Strong" + "contains common words" | 41 | B | First-screen friction for the fresh account. | S |
| F-21 | new season | template picked, nothing ticked → 0 plan items, no notice; parcel card chip "NT" | 53, 55; DB 0 plan items | B | No season checklist; the operator does not learn why. | S |
| F-32 | voice | "Iniciar entrada por voz" with no microphone: silence | 80 | B (headless) | Environment-dependent; the no-device branch says nothing. | S |
| F-22 | packet, OSP page | "Plan version: v1 to v3"; "Active / Approved" chip; "2 to confirm" badge; continuation-year form defaulting to a filed year | 04, 05; packet cover | B, D | Verdict word on the version chip; counts that mislead; a form offering a year it refuses. | P |
| F-23 | annual update | signature line "Signed in Trazo by Pass Owner" (account) vs cover "Responsible person: Laurel Brandt" | packet 02 | D | The signer is a fact about the session, printed as the operation's attestation. | P |
| F-24 | toasts | "Drift detection runs against the farm's currently active OSP…" on annual-update save/sign/file; offline toast titled "Error" | 67, 92, 96 | B | Wrong surface; wrong title. | P |
| F-25 | buyer page | "[supplier withheld]" placeholder; "Tangent, -"; es tab "Granja"; "Blueberries" untranslated; "Harvesting" as a card title | 31, 89 | B | Visible redaction and two words for farm on one screen. | P |
| F-26 | farm profile | "USDA Organic Integrity Database not loaded. Run: python manage.py import_usda_organic_data" | 06; `usda_organic_verifier.py:96` | B (dev) | A developer instruction stored as the verification note. Dev-only unless an import fails in production. | P |
| F-27 | new farm | "Certifier deadlines — OSP annual update (2026) — Not filed" on a never-certified farm | 49 | B | Assumes certification on day one. | P |
| F-28 | wizard | date-time prefilled with the viewer's clock; "Borrador guardado a las 12:38 a.m." | 10 | B | Fine on a phone in the field; wrong for a manager correcting records elsewhere. | P |
| F-29 | wizard help | "Consumer trust information … that transparency builds trust"; "the most frequent noncompliance nationally is…" | 64 | B | Retired framing and an unsourced statistic inside the input form. | P |
| F-30 | onboarding copy | welcome email "Agricultural Transparency Platform"; "start building consumer trust through transparency" | MailDev, 42 | B | Retired framing on the first screens. | P |
| F-31 | per-production dossier modal | button "Download packet" | 20 | B | Two things called packet. | P |
| F-33 | specimen | leftover test records "Producto Prueba 301" and "Equipment Maintenance" on the open season, now public after 4c; offered in "My products" and as a covering cleanout | 64, 74, 89 | B | Reseed removes them; until then they are on a demo buyer page. | P |
| F-34 | farm profile | "138.6 acres" beside parcels summing to 86.9 (the packet and FACT-04 use 86.9) | 06; workbook | B, D | Only the profile shows the larger figure; nothing says it is the whole property. | P |

No finding blocks a renewal outright: every document generates and every flow completes.
F-01, F-03, F-06 and F-08 are what a certifier would send back.

## Review log (records created, switches made)

All on `trazo_r8pass` (local). Nothing frozen was touched; the 2026 revisions 2 and 3 keep
their hashes (`e20e0567…`, `4cd62bbf…`).

| when (UTC) | what | id |
|---|---|---|
| 03:16 | v3 packet downloaded (side effect: `_refresh_narratives_if_editable` saved OSP 6, `updated_at` 2026-10-07 03:16:11) | OSP 6 |
| 03:18-03:22 | OSP v4 `certifier_name` set to OTCO, then CCOF, then WSDA via the picker; three v4 packets downloaded; **restored to empty** (picker "Choose your certifying agent" + "Save agent", toast "Certifying agent saved"; DB `certifier_name` = '') | OSP 7 |
| 03:21 | specimen document files copied from `~/dev/trazo-wt/r8pass/trazo-back/backend/media/documents/2026/10/` into this worktree's media (git-ignored) | files only |
| 03:23 | Duke 2026 dossier PDF + CSV; 03:25 operation dossier job (`documents_exportjob` 1); records ZIP | documents 7, 8, 9 |
| 03:3x | fresh account `review-j1@trazo.test`, company "REVIEW-2026-10 Journey One Farm Co" (Tangent OR), farm "REVIEW-2026-10 J1 Farm" (establishment 3), parcel "REVIEW-2026-10 Block A" (13), season "REVIEW-2026-10 Blueberries 2026" (history 25, 0 plan items) | user, company, est. 3 |
| 03:38 | crew: ChemicalEvent 90 "Producto Prueba REVIEW-2026-10", 2026-10-06 23:30, basis unverified, Onions 2026 | event 90 |
| 03:41 | crew: ProductionEvent 229 harvest, lot REVIEW-2026-10-H1, 1,000 lb | event 229 |
| 03:44 | crew: ProductionEvent 230 cleanout "REVIEW-2026-10 limpieza de cosechadora" | event 230 |
| 03:48 | owner: Onions 2026 — Upper Terrace finished, lot REVIEW-2026-10-ONIONS, 349,000 lb, finish 2026-10-06 18:00, published | history 23 |
| 03:51-03:54 | owner: 2027 annual update revision 1 edited (summary marked REVIEW-2026-10), signed (Member-manager), filed (email, 2026-10-07); packet after filing downloaded | OSPAnnualUpdate 5 |
| 03:56 | owner: certifier link "REVIEW-2026-10 certifier link" (2026, expires 2027-01-05); opened 3 times from a signed-out context; dossier built | CertifierAccessLink 1 |
| 03:58 | owner: Onions 2026 dossier PDF + CSV | documents |

Clean-up for Oscar (local database only): the Calapooia reseed (`seed_calapooia_bend
--rebuild --dry-run` first) removes events 89, 90, 228, 229, 230, the closed state of
history 23, filing 5, link 1 and the packet/dossier documents; the J1 user, company and
establishment 3 are separate rows to delete or keep as a second demo farm.

## 6. Proposed slices for Phase 2 (for Oscar's go-ahead)

One PR per slice, backend before app, each with behavioural tests red on the old code.
"Check" = what I re-check in the browser before opening the PR.

| # | slice | repo | findings | what changes | check |
|---|---|---|---|---|---|
| S1 | Dossier tells the truth | back | F-03, F-04, F-05 | Pre-export check: yield from `yield_quantity` (narrative parse dropped or shown as a note only), handler-chain regex excludes certifier names or is dropped; remove "Trazo's value-add"; remove the unsigned "Producer attests … 24-hour" paragraph; replace "100% materially complete" / "Complete — N characters" with counts. | Duke dossier p.1-3, p.52; operation dossier same pages. |
| S2 | Packet does not rewrite the on-file plan | back | F-06, F-07, F-17 | `_refresh_narratives_if_editable` draft-only; 01 prints "Snapshot generated" not "Last updated" and, when `submission_pdf` is empty, the same disclosure the dossier prints; (a)(2) heading year per the help text (or the help text corrected, Oscar decides); PDF outlines on 01 and 06, per-form bookmarks in 06. | v3 packet 01 + 06; `updated_at` of OSP 6 unchanged across a download. |
| S3 | Public carbon payload | back | F-02 (+ F-10) | Transparency endpoint: total and per-kg exclude `area_estimate` and `no_factor_applied`; `carbon_scope` replaced by the per-class sentence; `per_kg_miles`, `per_kg_phone_charges`, `calculation_method "USDA_EPA_factors"`, `blockchain_verified` dropped from the anonymous payload; records ZIP drops `trust_score`, `verification_level`, `additionality_verified`, `audit_status`, `confidence_score`, `reputation` and renames `data_source` to the per-row factor source. | Onions buyer page number and `curl` of the payload; records ZIP headers. |
| S4 | Unconfirmed is an answer | back + app | F-08, F-13 | Completeness nudge and certifier-page "Missing" exclude `unverified` (it is a recorded basis); transition status says "basis not yet confirmed" and keeps the certificate date on a certified parcel, with the unconfirmed inputs listed as a note; cleanout verb's default name per verb ("Equipment cleanout" / "Limpieza de equipo") and the equipment table prints the operation type. | Save an unverified input: no nudge for basis; certifier page row; parcel tab; certifier dossier p.235/242. |
| S5 | Name the drift honestly | back + app | F-01 | `drift.reason.unresolved` prints the stored candidate ("closest listing: …, not confirmed"); banner body drops "you must immediately notify" for findings whose only cause is an unconfirmed identity and says what to do (confirm identity on the OSP Materials panel); farm-card season row gets a `row_key` and translations; the whole-operation row, the packet [REVIEW] list and the certifier-page row say "not confirmed against the plan's listings" rather than "not on the plan"; NL-linked `legacy_unverified` reads "listed; basis not confirmed". | Farm card en/es, banner, certifier page, packet materials module. |
| S6 | Buyer page claims | app (+ back for goals) | F-09, F-11, F-12, F-25 | Chip "Recorded by the farm as allowed for organic use" / es "Registrado por la finca como permitido en orgánico"; tooltip states a National List link when one exists; remove the public "Sustainability Commitment" block and the sign-up tiles (or keep tiles as private goals); template blurb never copied into `description`; drop "[supplier withheld]" from the public list; es tab "Finca"; address formatter skips missing parts. | Duke and Onions buyer pages en/es; J1 new season description. |
| S7 | Annual update form | back + app | F-14, F-22, F-23 | Empty summary renders "Summary not written"; continuation-year form defaults to the next unfiled year; signer line offers the responsible person with the account as the recorder; "2 to confirm" counts items; drift toast scoped to the inputs panel; version chip "Active (approval recorded <date>)" / "Active (approval not recorded)". | Narratives page; a fresh draft; packet 02. |
| S8 | Spanish crew screens | app | F-18, F-24, F-28 | The ledger's open list plus this pass: farm-card season row, "Required", step-1 question, concentration labels, unit and option lists, "Preview", verb-specific localized default names (no "Harvesting"/"Equipment Maintenance" as record names), efficiency unset by default, plan-review details, event subtypes, parcel-page fragments, usted pockets on the pages the crew sees; offline toast title; date-time prefill left blank or in farm time. | Journey b again at 375 px es-419. |
| S9 | Certifier page and packet 04 | back + app | F-15, F-16 | Certifier page hides "Not assessed" rows behind a toggle, replaces grower to-do strings with certifier wording; packet 04 collapses the unresolved-route sentence to one line per parcel naming the answer to fix. | Certifier link page; OTCO v4 packet 04. |
| S10 | Onboarding polish | app | F-19, F-20, F-21, F-26, F-27, F-29, F-30, F-31 | Getting Started panel below content (or dismissable, server-side); Terms label toggles the box; one password verdict; "nothing ticked" notice on the season plan; deadline strip only for certified operations; dev-only OID note not stored as a user-facing note; wizard help block and statistic removed; welcome mail subject; company-setup heading; dossier modal button "Download dossier". | Journey a again. |

Before outreach: S1, S2, S3, S4, S5, S6 (what a certifier or a shopper reads that is not
true). S7 and S8 next (the crew and the filing). S9 and S10 after.

Data operations (Oscar runs, through `data_operations.py`): on production, nothing new from
this review; the ledger's pending `recompute_unreported_carbon` and the Calapooia reseed stand.
Locally: reseed `trazo_r8pass` after Phase 2 starts.
