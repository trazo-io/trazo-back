"""
Guided OSP module registry.

One entry per Common-OSP-style module. The registry is served to the frontend by the
`module-definitions` viewset action and consumed by the completion validator (WS-2.2), the
narrative compiler (WS-2.3), and the per-module PDF renderer (WS-2.6) — one source of truth.

CONTENT_VERSION stamps every saved module response (`definition_version`) so a certifier can
always know which questionnaire text an answer was given against. Bump it on ANY content
change to a shipped module — question wording changes silently reinterpreting old answers is
the failure mode this guards against.

Module keys are permanent identifiers (stored in module_responses); never rename one.
"""

from certifications.models import OSP_SECTION_KEYS

from .g2_0_fraud_prevention import G2_0_FRAUD_PREVENTION
from .g3_0_seeds import G3_0_SEEDS
from .g3_1_container_greenhouse import G3_1_CONTAINER_GREENHOUSE
from .g3_2_planting_stock import G3_2_PLANTING_STOCK
from .g4_0_rotation_soil import G4_0_ROTATION_SOIL
from .g4_1_compost_manure import G4_1_COMPOST_MANURE
from .g4_2_natural_resources import G4_2_NATURAL_RESOURCES
from .g5_0_pest import G5_0_PEST
from .g6_0_production import G6_0_PRODUCTION
from .g6_1_harvest_transport import G6_1_HARVEST_TRANSPORT
from .g6_2_storage import G6_2_STORAGE
from .g7_0_labeling import G7_0_LABELING
from .g8_0_record_keeping import G8_0_RECORD_KEEPING
from .g9_0_facility_pest import G9_0_FACILITY_PEST
from .materials_application import MATERIALS_APPLICATION
from .schema import Module, serialize_module, validate_module
from .stubs import CERTIFICATION_CONTRACT, G3_1_SEEDLINGS, G6_4_HANDLING, G6_5_SALES_SOE, W2_0_WILD_CROP

# NEWEST FIRST. Every bump must land a line here — the version exists so a certifier can
# know which questionnaire text an answer was given against, and a version that moves with
# no record of what moved does not deliver that.
#
# 2026.09.6: G8.0 page A gained the three WSDA AGR 2121-O (Recordkeeping, R 02/25) questions
# the § 11 registry structurally cannot answer. Question COUNT +5 (3 asked, 2 conditional).
#   * `records_location` (q5) — all records at the primary business location, yes/no; "No"
#     opens `additional_records_locations`. This is WSDA's routing gate to their AGR 2519
#     (Additional Facilities and Third-Parties), which Trazo does not generate, so the answer
#     names the locations rather than leaving the reviewer a blank.
#   * `primary_contact_records_access` (q6) — can the primary contact reach every record;
#     "No" opens `records_access_delegate` (who holds them, and which types).
#   * `records_maintained_as` (q7) — electronic / hardcopy, both allowed.
#   Registered modules previously marked complete become incomplete until these are answered:
#   that is what a content bump means, and `outstanding_modules` reports it before a packet
#   goes out. Register: documentation/compliance/certifiers/wsda/forms/2121-O-recordkeeping.yaml
# 2026.08.28: the four register blockers closed — post-harvest facility records reach the plan
# layer (`PostHarvestFacility.role`, `embed="post_harvest_facilities"` on G6.1 §C/G6.2 §A),
# G6.1 page D `handled_by_another_operation`, G6.2 `third_party_storage_contracted`. The line
# was missing from this list until 2026-09-06; what shipped is recorded in
# documentation/compliance/CERTIFIER-ALIGNMENT-ROADMAP.md §1.1.
# 2026.08.27: claim-safety. Trazo does not verify or approve materials — it RESOLVES names
# against OMRI / the WSDA Materials List / the National List, and the certifying agent
# approves. Question COUNT drops by 0; one OPTION is removed.
#   * G3.0 `treatment_verification` loses the `trazo_verification` option ("Checked against the
#     National List / OMRI / WSDA in Trazo at logging time"). CCOF's G3.0 D1 accepts exactly two
#     bases — an OMRI/WSDA listing, or written certifier approval — and the drift detector does
#     not check a seed TREATMENT at all (drift_detector.py: "We can't verify the specific
#     treatment"). Its compiled sentence changed from "Seed treatment materials verified via: X"
#     to "Basis on which seed treatment materials are allowed: X".
#   * Materials Application: module education, the panel label ("Approved input materials" →
#     "Input materials on this plan") and its coaching no longer say Trazo verifies; the five
#     category-attestation templates say "the materials list on this plan", not "the verified
#     materials list". BEHAVIOURAL for stored answers only in that the compiled narrative wording
#     changes on next recompile; no answer is reinterpreted.
# 2026.08.18: citation and coaching corrections found by a fresh-eyes CFR audit. No question
# was added or removed; question COUNT is unchanged at 196.
#   * G6.4 `own_products_only` + the module education (both locales) cited § 205.101(b) — the
#     RETAIL-ESTABLISHMENT exemption — and told growers they "may be exempt from a separate
#     handler certification". § 205.101 has no such exemption. Rewritten around § 205.100(a)
#     ("each operation OR PORTION of an operation that produces or handles") as scope, not
#     exemption, and explicitly the certifying agent's determination.
#   * G6.4 `uses_water` cited § 205.272(b); (b) is a closed two-item list (packaging
#     composition, container reuse) and mentions water nowhere. Now § 205.272(a).
#   * G6.1 container reuse: coaching, page education and the follow-up question title offered
#     reuse "behind a protective barrier OR after cleaning". § 205.272(b)(2) allows reuse only
#     where the container "has been thoroughly cleaned and poses no risk of contact" — there is
#     no barrier route. Question relabelled; `compiles_to` template changed accordingly, so the
#     sentence written into the packet changes too.
#   * G6.0 `prohibited_materials_storage.off_site` is now `exclusive=True`. BEHAVIOURAL: the
#     option is only visible when the operator said materials ARE kept on site, so combining it
#     with an on-site measure compiled a self-contradicting sentence into § 205.201(a)(5). Any
#     stored answer set that pairs them will now fail `exclusive_conflicts` on complete.
#
# WS-2.7 (2026-08-08): full crop-scope registry — 10 depth modules + Materials
# Application + 6 N/A-able stubs. Bumped from 2026.08.1 (3-module pilot).
# 2026.08.4: G6.4 Handling graduated from thin stub to full depth (applicability
# gate, products & site, process flow, commingling controls, records) — 11 depth
# modules + Materials Application + 5 N/A-able stubs remain.
# 2026.08.11: prefill for PERENNIAL operations — pest monitoring scope + cadence
# (G5.0) and on-farm storage (G6.2). The original five resolvers were all annual-crop
# shaped, so a mature orchard with a full season logged got 2 suggestions in total.
# 2026.08.10: G4.2 page B — conservation agreements, invasive-species control, and
# the food-safety-vs-§205.200 wildlife/habitat tension. Topics the CERTIFIER form asks
# beyond the federal template; wording authored from §205.200 + NOP guidance 5020.
# 2026.08.9: G4.2 gained the irrigation-district additive questions (§ 205.202(b))
# — CA growers on district water, where the district applies canal algaecides.
# 2026.08.8: G8.0 gained page C Import & Export (Common OSP § 11 subsection —
# export certificates TM-11/COI/NAQS/Canada, NOP Import Certificates, port
# integrity). Gated on a single trigger: domestic-only operations answer once.
# 2026.08.5: G3.0b Perennial Planting Stock graduated from thin stub to full depth
# (establishment record, commercial-availability justification, the § 205.204(a)(4)
# one-year rule, records) — the question every orchard and vineyard answers. 12 depth
# modules + Materials Application + 4 N/A-able stubs remain.
# 2026.09.9: the Oregon Tilth register delta — G4.1 gained raw-manure provenance (source +
# supplier statement on file, OTCO C4 §4.3); G6.0 gained the non-organic system's materials
# list (C9 §9.4) and a runoff risk / mitigation pair beside drift (C9 §9.3); the Parcel
# Application gained treated-lumber contact prevention (§ 205.206(f), C9 §9.3); G6.1's
# off-farm handling gate gained "ownership transfers at delivery" (C7 §7.10, CCOF G6.1 C1).
# 2026.09.10: Parcel Application §F — `currently_certified` relabelled to the certifiers' plain
#   question (its "by another certifier" steered renewing operations to "never certified");
#   `certified_operation_name`, `prior_certificate_site_number`, `certificate_card` (embed
#   certificate_of_record), `no_lapse_attested` and `dlpm_none_within_tenure` added; the affidavit
#   card became the 36-month manager table. CCOF F2/F4/F6/G, OTCO C2 2.1-7/2.4-2/2.5-x, WSDA 2264.
# 2026.09.12: G6.4 page C — cleaning and sanitation asked of EVERY handler, no longer behind the
# water gate. Question COUNT +16. `food_contact_cleaning_methods` (+other; WSDA §L 4, OTCO C7
# 7.6-1), `uses_equipment_sanitizer_or_cleaner` (CCOF G6.4 B1, WSDA §L 5, OTCO 7.6-2) gating
# `equipment_sanitizer_types` (CCOF Materials §E's ten types), `equipment_sanitizer_types_rinsed`,
# `equipment_sanitizer_where_used`, `sanitizer_residual_free_assurance` (+other; CCOF B1(b),
# WSDA 5a, OTCO 7.6-3) and `sanitizer_residual_testing_protocol` (WSDA 5b). `uses_water` itself
# ungated from handling_activities (OTCO 7.5-1) and followed by `post_harvest_water_uses`
# (WSDA §L 12), `post_harvest_water_source` (§L 13, OTCO 7.5-2), `wash_water_additives_added`
# (CCOF B2(a)), `wash_water_chlorine_added` (§L 15) and `wash_water_chlorine_final_rinse`
# (+other; CCOF B2(b), OTCO 7.5-5). Three water booleans prefill from PH records that name a
# sanitizer. Materials Application cites § 205.605; its §D prefill, dead since it filtered
# ChemicalEvent for a type it never carries, reads ProductionEvent PH `sanitizer_name`.
# 2026.09.11: Materials Application — `no_materials_used` (module-level, hides page B and the
#   completeness attestation) and one `<category>_none_used` line per category, each hiding its
#   "all listed" attestation. CCOF ORGB41 Header C / OTCO C11 Hdr-2: a stated "none used" instead
#   of a "Yes" over an empty category.
# 2026.09.30: G8.0 `import_export_activity` asks about indirect and planned export (CCOF contract
#   D2, "directly or indirectly"): new `indirect_export` and `none_no_known_export`; the old `none`
#   is RETIRED, so a plan holding only it reads as unconfirmed until the operator answers again.
#   `export_destinations` shows for either kind of export.
# 2026.10.25: G6.1 `who_harvests` and `who_transports` are checkbox groups (WSDA §J1/§J10, CCOF
#   G6.1 A1/A2 "all that apply"); stored answers wrapped in a one-item list by migration 0059.
#   New options: processor or packer harvests, other (+ text), sold standing in the field
#   (exclusive; requires no harvest records, opens `sold_standing_details` for CCOF A1's "describe");
#   broker, warehouse or packer, other (+ text).
# 2026.10.25.2: G6.1 harvest containers, bins and transport (WSDA AGR 2121 §J and §I3, CCOF G6.1
#   A2/A3, OTCO C9 9.4-2): harvest_method, harvest_records_kept, harvest_transport_records_source,
#   third_party_activities (+ equipment controls, cleaning documentation); container material,
#   cleaning records (+ procedure upload), stamped organic, unstamped safeguards, non-dedicated
#   wooden bins from a packer (+ the packer's practice as confirmed / believed / no, + its
#   documentation), empty-bin storage; carrier beyond transport, transport containers, transport
#   unit cleaning evidence, shared transport units (+ segregation), first stop before the buyer.
#   `container_types` gains wooden bins, plastic bins and picking bags; `field_bins` is RETIRED and
#   reads as given until the operator says which. G6.0 gains `harvest_transport_separation`.
#   Options can carry a [REVIEW] note and a required upload (schema `Option.review`,
#   `Option.requires_upload`).
# 2026.10.26.1: G6.2 storage and G7.0 nonretail containers (WSDA AGR 2121 §K3/K3a/K3b and §N1-N3,
#   CCOF G6.2 B2b and G7.0 A1-A3, OTCO C8 8.1-1/8.1-1a): sealed packaging (+ how unsealed product is
#   protected, + the records of where it is stored and how the area was cleaned, counted from Trazo's
#   records); how organic storage areas are marked; nonretail container types, how they show organic
#   status (+ notes, + a label example), which identifier they carry and how it leads back to the lot.
#   `unlabeled_bulk_documents` gets a write-time notice and a [REVIEW] line citing § 205.307(a)(1).
# 2026.10.28: Spanish only, register. About 290 es strings addressed the grower as usted ("Describa",
#   "su operación", "¿Conserva...?") on the same screens as the newer tuteo questions; es-419 is
#   neutral tuteo. The meaning of every question is unchanged and no English string moved.
# 2026.10.29: Parcel Application asks "Expected first organic harvest (if in transition)" only of a
#   parcel not stated currently certified (`currently_certified` ne "yes"). The ten Materials
#   Application booleans compile a No to its own sentence (`CompileRule.template_false`, never
#   inverted into a claim that materials are used) instead of the Yes statement followed by "(No)";
#   G4.2 wildlife and G8.0 records-location templates reworded to fit their answers.
# 2026.10.31: wording only. G6.1 "stamped organic" asks "How many of your harvest containers…", which
#   is what its All / Some / None options answer; G8.0's "Neither" export option ends its sentence;
#   G6.1's first-stop "none" option reads "Nowhere: it goes straight to the buyer" (the template asks
#   where), and its reused-container template is a sentence. One es label moved to tuteo.
# 2026.11.01: G3.0 / G3.0a / G3.0b gain the seed and planting stock questions CCOF G3.0, OTCO C3 and
#   WSDA AGR 2121 A, B and C ask that no question answered: seed and stock sources, how certified
#   organic material is verified, the seed-side search method, characteristics and records, non-GMO
#   bases for planting stock, treatment types and who applies them, the crop grown from nonorganic
#   stock, seedling growing sites and sale, grafting practices, and two free-text notes fields. All are
#   optional and fact-gated; `planting_stock_used` gains an `established_in_place` option. No option is
#   retired and no stored answer changes meaning.
# 2026.11.02: G4.1 asks what CCOF G4.1, OTCO C4 and WSDA AGR 2121 D ask of compost and manure that no
#   question answered: planned grazing as a § 205.203(c)(1) trigger, the interval rules as a
#   checkbox group (migration 0060 wraps stored answers) with a NOP 5006 processed-manure option, a
#   supplier-statement upload, a "does not meet, so raw manure" compost outcome, whether compost
#   contains manure, what is made on the farm, feedstocks, the logs kept and where, the 90/120-day
#   gates, vermicompost conditions, and a notes page. The water-risk answer is required. G4.0 adds
#   four fertility practices and "other". No option is retired.
# 2026.11.03: monitoring, as CCOF, OTCO and WSDA ask it. G4.0 adds four monitoring methods and
#   other, so observation without lab testing is stated by the methods ticked ("no testing" stays
#   exclusive), and asks a laboratory testing frequency apart from the monitoring frequency, each
#   with daily to annual options and an "other" to describe. G5.0 asks the monitoring method,
#   a frequency per monitored class (weeds, pests, diseases), the triggers for using materials, the
#   burn frequency, and six more prevention practices. G4.2's monitoring_method is a checkbox group
#   (migration 0061 wraps stored answers), with three more methods, an irrigation-efficiency question,
#   eight water practices and four invasive-species options. G2.0 adds quarterly and monthly review
#   and two implementation checks; G9.0 asks how and how often facility pests are monitored.
# 2026.11.04: third-party certificates. G6.1 asks how, and how often, the operation checks that the
#   operations handling its crop stay certified; the handler's certificate copy rides in the packet
#   under handlers/ and the facility line names it. G6.2 takes the statement an uncertified storage
#   facility's manager signs. G2.0 asks how often supplier certificates are reviewed, how suppliers
#   are approved and followed, and takes a written approval procedure. G6.5 asks whether the
#   paperwork of a bought-in product identifies it as organic. All new questions are optional.
# 2026.11.05: seedling suppliers. G3.0a shows, read from the transplant records and the supplier
#   register, each supplier named on a transplant purchase and whether a certificate copy covers its
#   latest purchase; the packet carries that copy under suppliers/. A panel, not a question: nothing
#   is typed and no stored answer changes.
# 2026.11.06: G3.0a's plan-level upload is relabelled "other seedling documents". Its old label asked
#   for the supplier certificates, which now belong in the supplier register beside each supplier.
# 2026.11.07: brands you pack for. G7.0 page C opens when some crop leaves under a buyer's label: it
#   shows each brand owner from the new brand-owner register (status, certifier, the certificate or,
#   uncertified, the agent's agreement, and the products packed with each label's claim), and asks how
#   brand owners' certificates are kept current and how often, whether labels name another agent, and
#   whether the certifying agent has reviewed the labels. All new questions are optional.
# 2026.11.08: sourced products. G6.5 shows, from the supplier register, each supplier the operation buys
#   organic product from (what it buys, the supplier's status and newest certificate, or for an
#   uncertified broker the operation it sources from and its Exempt Handler Affidavit), and asks how
#   bought-in product is kept from prohibited substances and from commingling in transit, and whether
#   records link it back to the last certified operation. All new questions are optional.
# 2026.11.09: water, lumber and the non-organic side. G4.2 asks irrigation sources by type (with "we do
#   not irrigate"), the district or river's name, and whether lines or tailwater are shared with cropland
#   where prohibited materials go into the water, who applies them, how contact is prevented and a piping
#   diagram (asked on the district-additives branch too, as CCOF D5 does). G6.0 asks the non-organic
#   crops of a split operation and gains page E, treated lumber (present or planned, the replacement
#   policy, planned installations). G6.4 asks whether post-harvest inputs are used only on non-certified
#   crops and how certified product is kept from them. All new questions are optional. "We do not
#   irrigate" also hides every question nested under irrigation (test frequency, district additives and
#   documents, shared-line details): each child now repeats its parent's gate, since the evaluator does
#   not chain (guard: tests/test_chained_gates.py).
# 2026.11.10: G9.0 takes the facility pest control records the plan says are kept (service reports,
#   trap and monitoring device logs, sighting logs, the device map, applications in a structure).
#   Shown once a record type is ticked; the files ride in the packet beside the module. Optional.
#   (2026.11.09 is held by back #273.)
# 2026.11.11: G6.0 page F, production equipment. Asks whether equipment contacts organic crops, seeds,
#   transplants or inputs; shows the equipment register (use, dedicated or not, own / rent / borrow /
#   custom hire, cleaning before organic use, materials, rinsed); asks whether any of it is also used on
#   non-organic crops or land, how dedicated equipment is kept from prohibited materials and marked, how
#   cleaning is documented (with a procedure upload), whether cleaning materials are on the materials list,
#   and leaves room for notes. All new questions are optional.
# 2026.11.12: G8.0 `lot_numbering` retires "Trazo lot IDs". Trazo issues no lot numbers and carries none on
#   storage or sales records, so the option's label claimed what Trazo does not do. A stored answer of it
#   reads as unanswered; the operator describes the numbering as their own (CCOF G8.0 B2). G6.1's lot-tag
#   coaching now says what the tag prints (lot ID, harvest date), not the parcel.
# 2026.11.13: the National List materials allowed only under a condition (WSDA AGR 2121 D4-D6a and H5/H5a,
#   OTCO C4 4.5-1). G4.0 page B asks whether synthetic micronutrients or magnesium sulfate are applied and
#   how each deficiency is verified (WSDA's options, soil and tissue analysis apart), whether the agent
#   approved a method other than testing, and whether calcium chloride (foliar? which disorder?) or
#   potassium chloride (how is chloride kept down?) are applied. G5.0 page C asks whether copper sulfate
#   or fixed coppers are applied for disease control and how copper is kept from accumulating. The module
#   PDF prints the rule's words and the plan's materials of each class beside the answers.
# 2026.11.14: Parcel Application page A asks who holds the parcel (WSDA AGR 2264 ref 7/7a/7b, OTCO C2
#   2.1-6): own, lease or rent, manage for the owner, other, and for any answer but "own" the landowner's
#   name, email, phone and address and the lease details with who manages day to day. Page F asks a
#   currently or previously certified parcel whether the whole certified site is applied for or only a
#   portion (WSDA ref 6b). All optional. "¿Cuándo comenzó...?" becomes tuteo.
# 2026.11.15: Parcel Application §D buffer rows say No (CCOF ORGB49 D1, OTCO C2 2.2, WSDA AGR 2264 ref
#   14): organic Yes / No / not answered, `buffer_crop_grown` beside the crop's name, and
#   `prohibited_use_distance_ft`. An explicit "not certified organic" and "no crop grown in the buffer"
#   print. Page F asks a parcel not currently certified CCOF F8/F8a: prohibited materials on its
#   borders or on the same APN / CA PUR site ID not submitted, and which, when and where. The wizard
#   shows §D's change notifications and contamination incidents.
# 2026.11.16: G6.0 page C asks OTCO C9 9.3-1's Yes/No on drift risk from neighbors, and 9.3-3: whether the
#   organic land is bordered by a public road and the steps against roadside management (no-spray signs,
#   notifying the county, city or state, agreements with roadside managers, other). `drift_safeguards` gains
#   CCOF G6.0 A2's exclusive "None, no surrounding use of prohibited materials" and asks the registry's name.
#   `self_managed_adjacent` ("... no third-party spray risk", a conclusion) is RETIRED: a stored answer reads
#   as given and as unconfirmed; its replacement `self_managed_adjacent_precautions` states the fact and asks
#   the precautions. G4.2 page A asks WSDA AGR 2121 E16: streams, shorelines, gullies or irrigation channels
#   on or next to certified land. All optional; nothing existing is gated on the new answers.
# 2026.11.17: G6.0 page A asks, of a split operation, where the non-organic product comes from (buffer-zone
#   crop sold as non-organic, parcels not certified, land in transition, product bought in and resold,
#   other). The split answer itself is unchanged: § 205.2 makes any operation producing non-organic product
#   split, buffer crop included. Optional; nothing existing is gated on it.
# 2026.11.18: G8.0 page B asks the lot number key one part per line (`lot_code_key`, printed as CCOF G8.0
#   B2's Code / Signifies table beside lot numbers from the records) and what besides lot numbers traces a
#   sale to the field (`trace_mechanisms`, OTCO C12 12.2-3). G7.0 page B asks what storage and shipping
#   records show for each organic lot (`container_record_elements`, WSDA N 4). All optional.
# 2026.11.19: G7.0 page A asks whether the "Certified organic by" statement sits below the packer or distributor
#   (CCOF G7.0 B1, OTCO C8 8.2-1; § 205.303(b)(2)), whether the certifying agent has reviewed every current retail
#   label, export labels included (WSDA N 5a, OTCO 8.2-1/8.3-1/8.4-2, CCOF A1), and retail labels on unpackaged
#   product such as PLU stickers, with an upload (CCOF G7.0 B2). G7.0's Not applicable prints a [REVIEW]
#   (§ 205.307(a)(1)). All optional.
# 2026.11.20: the operation's own handling and storage facilities are records (`PostHarvestFacility.operated_by`
#   = this_operation, with postal code, country and a layout file), listed by the `on_farm_facilities` embed on
#   G6.4 §B and G6.2 §A (CCOF G6.4 A1; OTCO C7 7.1, 7.2-1, 7.7-2 OWN). No certificate is asked of them.
# 2026.11.21: G6.4 page C asks whether any input is applied directly to crops after harvest (WSDA L 8), which
#   types (L 9, without the two livestock-feed items) and how each application is recorded (L 11). Optional.
# 2026.11.22: G5.0 page A asks the practices by the pest they target: weeds, insects and other invertebrates,
#   diseases and nematodes, vertebrate pests (CCOF G5.0 §A's four columns; WSDA AGR 2121 F 3, G 4, H 3), each with
#   "Other" and an exclusive none. The untyped `prevention_practices` and `weed_management_practices` are RETIRED
#   (`Question.retired`, new): shown only to a plan that answered them, never asked anew. All new lists optional.
# 2026.11.23: the Parcel Application asks which elements the operator's parcel map shows (`map_elements_shown`,
#   the union of CCOF ORGB49 §E, WSDA AGR 2264 Map and OTCO C2 2.3); the parcel PDF names what the plan's agent
#   asks for that is not ticked. Page A asks for treated lumber within the boundaries that touches neither crops
#   nor soil (CCOF A10, OTCO 2.3-2), shown when the contact question is No. All optional.
# 2026.11.24: G2.0 asks the residue screening performed and the response when a residue is detected (WSDA AGR 2121
#   P 4a, 4b). G4.1 asks compost temperature only of the thermophilic methods (OTCO C4 4.4-3). G4.2 page A opens on
#   a description of the operation's natural resources (CCOF G4.2 A1) and its monitoring list gains cost trends,
#   water use trends and water testing (B1). The Parcel Application asks whether livestock are kept, pastured or
#   grazed: the kept-only "no" is retired, "none" added, a grazing follow-up for "yes" (CCOF §C, WSDA E 12), and
#   livestock is a completion check. All new questions optional.
# 2026.11.25: G3.0 page B opens on non-organic seed OR non-organic planting stock (`ModulePage.visible_when_any`,
#   new; CCOF G3.0 B1, OTCO C3 3.3); its seed-only questions keep the seed gate. `ca_search_before_use` retires
#   "all organic" (it contradicted the answer that opened the page) and adds "no search documented yet" with a
#   [REVIEW]. G6.0 adds routine third-party residue testing to the drift safeguards and uploads for written
#   agreements with neighbors and with the roadside manager (CCOF G6.0 A2). All new questions optional.
# 2026.11.26: CCOF Materials Application §C. The two production-aid statements asked about adjuvants and
#   wetting agents only; retired (shown while they hold an answer) for two that ask CCOF's whole list: seed
#   treatments, growing media and adjuvants. Seed treatments on planting records and tank-mix partners on
#   application records join the Materials List and its reconciliation. G4.0's "all fertility materials are
#   listed" is gated on the same reconciliation as the Materials Application's fertilizer statement.
# 2026.11.27: G3.1 Container & Greenhouse/Shadehouse Production (CCOF ORGB46), a new module after G3.0b. Its
#   not-applicable attestation is CCOF A1's "None of these"; sections B4 and D open only on the answers that make
#   them apply. Every question is new, so no stored answer changes meaning.
# 2026.11.28: post-harvest water and packaging. G6.4 asks where crops are washed (CCOF G6.1 B3), how
#   non-municipal water is shown potable and whether a test came back positive (OTCO C7 7.5-1b/c), and whether water
#   is treated on site and still meets the Safe Drinking Water Act (WSDA L 14, CCOF G6.1 B3a). G6.1 asks what
#   packaging touches the product and its safeguards (OTCO 7.9-1, WSDA L 16/17), the proof for paper, cardboard,
#   twine, compostable and single-use packaging (OTCO 7.9-2 to 7.9-4) and packaging reuse (7.9-5/6). All optional
#   or gated on a new answer, so no finished module reopens.
# 2026.11.29: Operation profile gains B. Certification history and C. What happened (CCOF Certification Contract
#   D5 to D6, OTCO O1 D-1E, D-2 to D-7): ever certified, suspended, revoked, surrendered or withdrawn with
#   outstanding noncompliances, denied; then the explanation, the letters, the OTCO affirmations and the
#   reinstatement request. Every question is new and optional, so no stored answer changes meaning.
# 2026.11.30: on-farm processing scope. G6.4 adds OTCO C7 7.3-1's missing processing steps (freezing, cutting, cooking,
#   mixing, fermenting, seed cleaning), a scope question (non-organic product handled here, multi-ingredient or off-farm
#   ingredients, a multi-farm CSA, complex handling; each prints a [REVIEW]) answering CCOF G6.4's applicability gate,
#   OTCO 7.3-2/7.3-3 and WSDA L 3, and whether the handling area or equipment is shared (OTCO 7.4-1, WSDA L 6). New
#   options and optional questions only.
# 2026.12.01: facility pests. G9.0 asks which pests the plan covers (OTCO 7.8-1, WSDA M 2), adds OTCO's and WSDA's
#   missing prevention and mechanical options and two of OTCO's contamination safeguards (7.8-4b), whether the controls
#   are sufficient and what else is used (OTCO 7.8-4/4a, CCOF G6.2 B5), whether National List materials are sufficient
#   (CCOF B6), why a non-National List synthetic is needed with its letter (CCOF B7, WSDA M 7), and bait station use
#   (WSDA M 5). G6.2's storage pest question now points to G9.0. New options and optional or gated questions only.
# 2026.12.02: storage detail. G6.2 asks whether the operation still owns the crop in off-farm storage (OTCO C7 7.7-1,
#   CCOF G6.2 A1). G6.4's process-flow and facility-documents coaching say either a written flow or an attached flow
#   chart answers OTCO 7.2-2 / CCOF G6.4 A3. One optional, gated question; coaching only otherwise.
# 2026.12.03: parcel location and status. The parcel application asks block numbers (CCOF A2); whether the parcel
#   shares the operation's city, state, ZIP and country, and its own when not (CCOF A3, WSDA AGR 2264 ref 2, OTCO C2
#   2.1 3-4); the computed boundary centre, and other location information for a parcel with no street address
#   (CCOF A5, OTCO 2.1); the status applied for and whether a transitional certificate is needed (WSDA AGR 2264
#   ref 4, 4a); and treated seed planted on the parcel (ref 11, 11a). The expected first organic harvest is asked as the forms word it, without "(if in
#   transition)". All optional; the export answer and the G3.1 pointer print from answers held elsewhere.
# 2026.12.04: parcel crops and acreage. The parcel application asks the total acres to be certified (CCOF A7, OTCO
#   C2 2.1 9), WSDA AGR 2264 ref 8 total site acreage) and lists the crops grown now or planned, each with variety,
#   expected harvest and acres (CCOF A8, WSDA ref 8, OTCO 2.1 10), as rows on `ParcelPlannedCrop`. Optional.
# 2026.12.05: orchard columns on the parcel crop table. Each row may also state its block name, rootstock, year
#   planted and bearing status (overall review 2026-11, OV-FJ-C06); the parcel PDF prints them when any row on the
#   parcel states one. Optional.
# 2026.12.06: container parcels. The parcel application asks what a container parcel's containers stand on
#   (CCOF ORGB49 F3; only impermeable flooring skips the land history) and, on page F, the signed container
#   statement's contents: planting date, materials since, and contamination removal on sealed flooring (§G).
# 2026.12.07: operation contacts. The Operation module's page A shows the people the operation names to its agent, each
#   with name, title, phone, email and roles: legally responsible, primary, billing, authorized to act, responsibly
#   connected with the connection (OTCO O1 B-2 to B-6; CCOF Contract A4, C1, C2). Rows on `OperationContact`.
# 2026.12.08: legal entity and addresses. The Operation module gains page D: legally registered, business structure and
#   state of incorporation, DBAs with where each is registered and used, the registered legal, mailing and billing
#   addresses (each "same as" first), and which contact details may be published (CCOF Contract A1 to A4, A6, A7;
#   OTCO O1 A-1, A-3, B-1, B-7).
# 2026.12.09: the Operation module's scopes add transitional and fungi (OTCO O1 C-1); page A names who signed the
#   agency's contract and when (O1 I-B, CCOF Contract G); page B asks whether another agency certifies the operation
#   today, whether that stays, and its certificate (O1 D-1A, D-1B; CCOF D4); new page E asks the standards to be
#   assessed to, the regulators that inspect the operation and any negative report (O1 C-2, C-5, C-6).
# 2026.12.10: G2.0 asks the fraud prevention team (OTCO OFPP 1-1), where suspected fraud is reported and what would be
#   (OFPP 1-2, WSDA AGR 2121 P 6), whether a separate plan is kept, the upload now shown on its Yes (OFPP 1-4), how
#   often records are reviewed and staff evaluated, when staff are trained on the plan, internal audits, written SOPs
#   and a notes field (OFPP 4-1, WSDA P 1 to 3a and 7, OTCO C12 12.3-1). New page D asks the supply chain as a map or a
#   description and the critical control points, each with its prevention and monitoring (OFPP 2-1, 3-1).
# 2026.12.11: the Operation module asks a short summary of the organic business and its plans (CCOF Contract B1),
#   and on page B whether the agency the plan is filed with certifies the operation today, with that agency's most
#   recent certificate attached (OTCO O1 D-1).
# 2026.12.12: natural resources. G4.2's soil and water list gains the NRCS practices WSDA AGR 2121 E 6, 13, 15 and 17
#   name (and CCOF A3's two); its habitat list the in-field and landscape practices of WSDA E 2, CCOF A4 and A5, OTCO C6 3
#   and 4; a waterway list where streams or channels run by the land (WSDA E 2, OTCO C6 2b); permanent cover and slope
#   (WSDA E 4, 5); other measures (WSDA E 3, CCOF A9, OTCO C6 7); NRCS, FSA, Salmon Safe and other as agencies (OTCO C6
#   1a; the joint federal option retired). G4.0 asks rotation records (WSDA E 1b) and whether fertilizer is applied
#   (E 11); G3.1 conservation in enclosed structures (CCOF G4.2 A8).
# 2026.12.13: irrigation. G4.2 page C asks how irrigation water is verified free of contaminants and what it is tested for
#   (OTCO C9 9.2-1a); the district plan's materials, timing and advance notice (9.2-1b); prohibited additives in water
#   that is not a district's, with the measures taken (CCOF G6.0 D3, D5); materials put through the irrigation system,
#   their types, whether all are approved, and how certified crops are kept from those that are not (CCOF D6; WSDA AGR
#   2121 E 8, 8a, 8b).
# 2026.12.14: the Parcel Application asks an operator who answered No to "no prohibited material since I began
#   managing it" for the date of the last one it applied and whether any followed (CCOF ORGB49 F4). The 36-month
#   accounting runs from that date, and the transition clock reads it.
# 2026.12.15: recordkeeping and split records. G8.0 adds OTCO C12's kinds of electronic records beside "electronic" (12.2-1)
#   and asks whether organic product is sourced or sold and whether records show organic status (12.2-4, 5, 5a); G6.2
#   asks the inventory system and how often (12.2-7); G6.0 asks how input records and harvest, shipping and sales records
#   tell organic from non-organic on a split operation, and contamination prevention through handling (CCOF G8.0 C2, C3;
#   OTCO 12.4-1a, 1b; C9 9.4-3), with three buffer options (CCOF G6.0 A1).
# 2026.12.16: seeds and planting stock. G3.0 asks the status of planting stock other than perennial nursery
#   stock (OTCO C3 3.1-4) and suggests `planting_stock_used` from records of trees, vines, berry plants or
#   rootstock (which no longer suggest seed); grafting and nonorganic stock treatments each gain a "yes, not
#   every material is on the inputs list yet" answer (CCOF G3.0 E1, WSDA AGR 2121 C3c); G3.0b asks whether
#   stock sold as organic was bought nonorganic (WSDA AGR 2121 C4).
# 2026.12.17: international trade. G8.0 page C offers importing seed or planting stock for the farm's own use
#   (WSDA AGR 2121 §Q 1), which opens the import questions and asks the countries and organic standards (Q 2, 3);
#   the import documents kept per shipment (Q 4); export packages and the documents that travel with each
#   shipment (Q 8, 9); how exported products meet the equivalency arrangement (OTCO C8 8.4-4); whether crops may
#   reach Canada, whether sodium nitrate is used and how the two are kept apart (Q Critical Variances: Canada).
# 2026.12.18: direct marketing. G6.5 asks whether the operation sells directly to consumers, where (farmers' markets,
#   CSA, farm stand, u-pick, online, other), each market and venue in CCOF's columns, whether non-organic products are
#   sold too and how the two are told apart, with samples (CCOF G6.5 B1, B1a, B1b, C1). Optional at the top.
# 2026.12.19: pest, weed and soil. G5.0 asks the pests and diseases of concern (OTCO C5 5.1-1, suggested from pest
#   records), the kinds of crop pest managed (WSDA AGR 2121 G 3), the disease or seed a burn targets (CCOF G5.0 C3, OTCO
#   5.2-2), the plastic mulch's material and its condition in a perennial planting (WSDA F 4, 5a), and the records of
#   preventive pest and weed management (G 5, F 6), with notes (F 7). G4.0 adds OTCO C4 4.2-2's practices in lieu of
#   rotation, a description for perennial or container crops and site-specific notes (CCOF G4.0 A1b, A1c), and splits
#   contour farming from terraces, with bare ground and other (CCOF C1, OTCO 4.1-2); the merged option is retired.
# 2026.12.20: post-harvest, storage and harvest leftovers. G6.4 asks how cleaning differs before non-certified crops (WSDA
#   AGR 2121 L 6a), how the chlorine rinse is checked (L 15a), how cleaning and purge records link to production records
#   (L 7), takes the equipment purge procedures (L 4), the product list (CCOF G6.4 A2) and notes (L 18), and points to
#   G9.0 and G6.1 for facility pest materials and packaging (CCOF G6.4 A4, C1). G6.1 asks the documentation behind
#   unstamped containers (J 7b) and notes (J 14); G6.2 notes (K 4). All optional.
# 2026.12.21: record keeping leftovers. G8.0's records attestation also requires storage records, invoices and bills of
#   lading when the plan stores, sells as organic or ships other than by buyer pickup (CCOF G8.0 A1); the audit trail
#   upload asks for the operator's own marked-up sample (B1); G6.0 asks whether bought-in non-organic product is the same
#   as an organic one sold (C1); G5.0 the disease prevention records (WSDA AGR 2121 H 4); G8.0 notes (O 9); the Parcel
#   Application the number and issue date of a certificate another operation held (AGR 2264 6a). Optional.
CONTENT_VERSION = "2026.12.21"

# Wizard/list order follows the Common OSP grower taxonomy: seeds & stock →
# soil → pest → production/handling chain → labeling → recordkeeping →
# materials → contract. Wild crop last among crop-scope modules.
MODULE_REGISTRY: tuple = (
    G2_0_FRAUD_PREVENTION,
    G3_0_SEEDS,
    G3_1_SEEDLINGS,
    G3_2_PLANTING_STOCK,
    G3_1_CONTAINER_GREENHOUSE,
    G4_0_ROTATION_SOIL,
    G4_1_COMPOST_MANURE,
    G4_2_NATURAL_RESOURCES,
    G5_0_PEST,
    G6_0_PRODUCTION,
    G6_1_HARVEST_TRANSPORT,
    G6_2_STORAGE,
    G6_4_HANDLING,
    G6_5_SALES_SOE,
    G7_0_LABELING,
    G8_0_RECORD_KEEPING,
    G9_0_FACILITY_PEST,
    W2_0_WILD_CROP,
    MATERIALS_APPLICATION,
    CERTIFICATION_CONTRACT,
)

MODULES_BY_KEY = {m.key: m for m in MODULE_REGISTRY}


def registry_errors() -> list:
    """Definition errors across the whole registry (test suite asserts this is empty)."""
    errors = []
    seen = set()
    for module in MODULE_REGISTRY:
        if module.key in seen:
            errors.append(f"duplicate module key '{module.key}'")
        seen.add(module.key)
        errors.extend(validate_module(module, OSP_SECTION_KEYS))
    return errors


def serialize_registry() -> dict:
    return {
        "content_version": CONTENT_VERSION,
        "modules": [serialize_module(m) for m in MODULE_REGISTRY],
    }


__all__ = [
    "CONTENT_VERSION",
    "MODULE_REGISTRY",
    "MODULES_BY_KEY",
    "Module",
    "registry_errors",
    "serialize_registry",
]
