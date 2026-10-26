# Trazo activity-capture rehearsal

Completed desktop review, 18–26 October 2026. Live UI evidence only; no code inspection or regulatory conformance opinion. Company 17, farm 20, South Block, Gala 2026 (ASTRA TEST). Grower account: oscar+astrapilot@trazo.io. The season remains open and unpublished with 60 fictional records. Honeycrisp was left untouched.

**Verdict: fail against the requested acceptance criteria.** Records can be entered and retrieved, and the private activity boundary worked in the buyer preview. However, readback changes a weather unit, automatic buyer narratives assert facts not entered, Spanish is incomplete, and some records do not expose enough detail to check what was saved. This does not establish database corruption: several failures are demonstrably in rendering.

## Results by requested path

| Path | Result | What was exercised and observed |
|---|---|---|
| 1. Form, activity types and subtypes | FAIL | All 17 top-level categories exercised. Saved records cover planting then transplantation by edit, all four input types, all three field-work subtypes, pruning/canopy, irrigation, harvest, pollination, frost protection, the four private activities, ten soil subtypes, seven pest subtypes, eight weather subtypes, five certification subtypes and ten other-activity subtypes. Hail minutes display as hours; some units and subtype details disappear from readback; buyer narratives add facts. This was not a Cartesian test of every dropdown option. |
| 2. Templates | FAIL | Applying templates was exercised for irrigation and pruning; chemical template filtering, thinning and private-activity availability were checked. Planting offered a seed-search template, violating chosen-activity-only filtering. Cleanout, transport, buffer and seed search did not offer a template that silently switched the activity. Not every individual template was applied and saved. |
| 3. Paste a note | FAIL, limited | All five requested cases were exercised. No automatic application of suggested values was observed. Chemical values remained for manual review/entry; wrong-activity harvest text produced an explicit switch offer; undated notes required a date. Pure negation produced misleading mixed-action guidance. Spanish harvest quantity extraction also required manual completion. No negated spray was saved. |
| 4. Edit/correct and names | PASS for open-record editing/name rules | The planting record was edited to transplantation while its custom name remained. Before a custom name was set, changing Cultivo to Raleo updated the generated name. The finished Honeycrisp season was not edited. This round does not retest locked-season amendment handling. |
| 5. Record-specific documents | PASS, with picker friction | A fictional text attachment was linked from Documents to ASTRA Seed search form test. The record lists ASTRA-TEST-seed-search-support and its uploader/date. Chemical rows in the linking selector were ambiguous because multiple same-day records shared the same generic activity label. |
| 6. Spanish / 375 px | FAIL Spanish; 375 px NOT TESTED | Spanish form and paste workflows exercised. English help, options, validation, field labels and provenance keys remain. The available browser did not provide a supported viewport-resizing control, so no 375 px layout pass is claimed. |
| 7. Seeded crew notes | PASS for core confirmation/attribution; FAIL presentation | English spray and Spanish harvest were confirmed to Gala after review. Sender, original words, receipt time, confirmer and confirmation time remained distinct. Missing date/block required operator input; sender was not made performer. Negation did not become a spray. The refused note could not be confirmed. Raw provenance keys and misleading negation guidance remain. Actual WhatsApp receipt and live microphone transcription: live untested. |

## Reproduction locations

Start at https://app.trazo.io/admin/dashboard/farm/20 → South Block → Gala 2026 (ASTRA TEST). On the parcel's activity timeline open the named record for its private detail; use Edit without saving to inspect the stored input. For buyer output, open the season → Vista previa → Ver el registro completo. This preview was reached through the app UI; the season was never published.

Observed season URL: https://app.trazo.io/admin/dashboard/farm/20/parcel/49/production/669b91da-29b3-4444-b536-99da30d6673c

## Findings

All rows below are **Observed**, unless the text explicitly identifies an inference or recommendation. IDs are local to this activity-capture round (AC).

| ID / severity | Exact reproduction and observed result | Expected / suggested correction |
|---|---|---|
| AC-01 / major | Open ASTRA Weather hail test, 19 Oct 16:20. Entry used Granizada, Duración (minutos) = 7. Card/detail show **7 hours**. Opening Edit confirms the value remains 7 in the minutes field. | Render seven minutes consistently. Test the field's unit through form, card, detail, consumer output and exports; export behavior was not exercised here. Evidence: astra-hail-minutes-shown-hours.jpg. |
| AC-02 / major | Buyer preview → certification group → ASTRA Certification in progress test. Private record is Verification In Progress, USDA Organic, no certifier or certificate number. Buyer says **“Se registró una certificación de tercera parte para este cultivo”** and **“El número de certificado se publica aquí…”**. Expanded buyer detail shows only USDA Organic, not the in-progress status or a number. ASTRA Review in progress form test similarly says an external body reviewed the operation against a written standard, although none was recorded. | Base assertions on the actual status and present evidence. A producer-report badge does not repair an invented completed-review statement. Do not promise a published certificate number when absent. Evidence: astra-certification-buyer-overclaim.jpg. |
| AC-03 / major | Buyer preview → soil group → ASTRA Compost process incomplete test. It is a composting-process record, windrow, initial C:N 30, peak 140°F, 3 days, 2 turns; no application. Buyer says **“Se esparció compost en el lote”**. ASTRA pH adjustment test, with no material or quantity established, says a mineral amendment was applied and its identity/amount can be seen. | Distinguish making/monitoring compost from applying it. Render only entered actions and quantities. Evidence: astra-compost-public-overclaim.jpg. |
| AC-04 / major | Buyer preview → full timeline. ASTRA Orchard floor test explicitly says manual weeding; generated text says **“Se segó la vegetación…”**. ASTRA Weather frost/hail/heat tests add crop-effect or damage inspections that were left blank. Tropical storm says wind damage was recorded although damage was blank. ASTRA Emergency response test records placing a warning cone; generated text says emergency cleaning and repairs. | Remove unconditional narrative assertions inferred solely from a subtype. Use the operator's words or factual field-driven descriptions. Root cause in shared narrative logic is an inference, not a code finding. |
| AC-05 / major | Same buyer timeline: ASTRA Canopy tying test is Amarre but talks about leaf removal/trimming; ASTRA Habitat test records native yarrow but claims hedges, flower strips and living cover; ASTRA Nest box test records two barn-owl boxes but claims songbird boxes, raptor perches and bee blocks as well. Pollination adds flowering; grazing adds a cover-crop-consumption purpose. | Narrow narratives to selected methods/species and documented timing/purpose. Do not turn examples into completed facts. |
| AC-06 / minor | Create Siembra / plantación → Usar una plantilla. A seed-search template is offered alongside planting choices. | Filter templates by the selected activity and subtype; applying a template must preserve the activity and its privacy boundary. No claim is made here that the wrong template was saved. |
| AC-07 / minor | Paste **“Did not spray today, too windy”**; also inspect crew note **“No fumigamos hoy”**. No chemical amounts/products are offered, but guidance describes a mixture of things done and not done. | Distinguish pure negation from mixed-action notes. Keep the successful no-spray behavior. A confusing banner is the observed failure, not a saved invented application. |
| AC-08 / major | Create Suelo y enmiendas → Análisis de laboratorio → irrigation-water sample, lab/sample ID and boron 0.2 ppm; leave area blank because no acreage is established. Continue requires Area Covered > 0. An explicit fictional one-acre scope was entered to finish ASTRA Water lab test. | Make area conditional on the record's meaning, or explain why it is mandatory. Do not force an arbitrary area to record a laboratory sample. |
| AC-09 / minor | Spanish throughout: first-step performer placeholder **Enter operator/worker name**; soil/pest option lists in English; detail **Additional Details**, **Business Type**, **Verification In Progress**, **Pest Species**, **Duration**, **7 hours**; crew provenance exposes stored field keys. | Translate visible labels/help/errors and render provenance with readable labels. Operator-authored English ASTRA notes are test data, not translation defects. |
| AC-10 / minor | ASTRA Weather drought test shows Water Deficit 15 without mm; tropical-storm record shows Wind Speed 60 and Precipitation Amount 20 without km/h or mm; humidity records show 90 or 20 without %. | Keep value and unit together on cards and details. Correct °F/°C conversion was observed for frost and heat. |
| AC-11 / minor | ASTRA Canopy tying test detail calls Amarre **Tucking**. ASTRA pH adjustment test detail presents **Soil Amendment**, while Edit retains pH Adjustment. Cultivation and orchard-floor detail use generic Producción without identifying the subtype. Seed-search outcome was available in Edit but omitted from ordinary detail. | Make readback precise enough to check what was entered. These observations do not prove values were lost from storage. Evidence: astra-canopy-readback.jpg. |
| AC-12 / minor | Documents → upload fictional support → link to record. The selector lists multiple input applications on 18/19 Oct with the same generic type and date, without enough distinguishing information. | Include product/title and time, with record ID as secondary information. Specific linking worked when the record was unambiguous. |
| AC-13 / minor | Certification/compliance form defaults to pending verification but Continue blocks with an English error requiring a definitive status. In-progress can be selected and saved. Selectors such as “Evaluación de sostenibilidad aprobada” still allow Verification Failed, as demonstrated by ASTRA Sustainability failed test. | Allow an honest unfinished record or explain the required status next to it. Use neutral activity names that do not presume a passed result. |
| AC-14 / minor | ASTRA Generic activity test says no emissions are estimated, then shows **0 kg CO₂e / Mínima**. Many weather/pest/other cards also display zero. Soil pH, tillage and water-lab cases without recorded fuel display estimates labelled **De insumos registrados** (0.12, 61 and 0.41 kg respectively). | Distinguish no estimate, measured inputs and default/activity/area-based estimates. The calculation's correctness cannot be established from UI evidence. Cultivation correctly says no estimate because fuel, energy and area were not recorded. |
| AC-15 / minor | Open any public-eligible record on the unpublished Gala season, including ASTRA Generic activity test. Detail says **“Este registro aparece en tu página de comprador”**, while the season correctly says scanners cannot view it until publication. | Use conditional/current-state wording. This is a misleading status message; no unintended public publication was observed. |

## Other observed narrative problems, same AC-04/05 mechanism

Irrigation promises to show the source although it was left unknown. Cover-crop text places it before the current crop without entered timing. Tillage assumes seedbed preparation and promises a pass count that was not supplied. Fungicide text promises a recorded target although that field is blank. Pest identification asserts it preceded any treatment decision. Internal-inspection text asserts a safety inspection of facilities and equipment although only a generic internal visual inspection was entered. These are reproduction examples of the narrative finding, not separate independently verified code defects.

## What passed and should be preserved

- Explicit review before applying parsed suggestions. No guessed date was observed on the tested note flows; chemical fields were entered manually.
- Crew-message provenance distinguished reporter and confirmer. The English spray and Spanish harvest records retained original wording and receipt/confirmation times. Missing performer remained missing rather than inferred from sender.
- Custom event names survived activity edits; generated names followed activity until manually changed.
- Bins, weight ounces and fluid ounces were kept distinct in the tested harvest and application records. Hail is a separate failing unit path.
- The fictional document appears on its specifically linked seed-search record.
- At the final buyer check before the last cultivation save, the season had 59 internal records and the preview had 55: the four certifier-only activities (cleanout, transport, buffer use, seed search) and their private markers were absent. No private marker was observed in the buyer output. This verifies the preview, not an anonymously published season.
- Buyer self-report disclosure remained visible and carbon remained collapsed/secondary.
- Generic and cultivation records saved successfully. Final parcel count is 60. The last cultivation card names John Doe as the entering account and preserves the supplied public/private notes; no worker was filled in.

## Limits and remaining checks

- 375 px: not tested, no supported viewport control available. Desktop screenshots do not establish phone usability.
- Microphone voice recording and WhatsApp delivery: live untested, as requested. Paste tests exercise the visible parser workflow, not proof of equivalence with microphone/network ingestion.
- No audit export, signing, filing, review access, billing, messaging or publication was performed in this activity round. Document upload was fictional and authorized.
- No raw API calls, database inspection or backend tests. Storage and code claims must be verified by Claude against code before implementation.
- No complete cross-product of template items, field options, languages and units; top-level activity/subtype coverage is broader than template coverage.
- The final buyer count was observed at 59 internal / 55 eligible, before saving the 60th cultivation record. A 56-count buyer refresh after that save was not performed.
- Some follow-up form guidance references organic or food-safety regulations. This report does not determine legal adequacy of that wording or treat an absent optional warning as a certification violation.
- The fixture's California map coordinates versus Chelan address were noticed but not investigated.

## Recommended corrective sequence

1. Fix and regression-test hail units and missing weather units (AC-01/10).
2. Make buyer narratives factual and status-aware, starting with certification, compost process, weather damage and manual weeding (AC-02–05). Preserve the four private-activity exclusions.
3. Fix template filtering and parser-negation guidance (AC-06/07).
4. Remove unjustified required acreage for laboratory records; improve status validation and readback (AC-08/11/13).
5. Finish Spanish and record-picker labels; distinguish carbon estimates and publication state (AC-09/12/14/15).
6. Run a focused confirmation with these named records, plus a real 375 px session. Do not commission another full-app audit to confirm this round.

Screenshots referenced above are companion evidence from the browser session. No production deployment was identified from the UI; these conclusions apply to the observed state, not an inferred commit.
