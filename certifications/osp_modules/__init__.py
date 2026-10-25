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
CONTENT_VERSION = "2026.10.25.2"

# Wizard/list order follows the Common OSP grower taxonomy: seeds & stock →
# soil → pest → production/handling chain → labeling → recordkeeping →
# materials → contract. Wild crop last among crop-scope modules.
MODULE_REGISTRY: tuple = (
    G2_0_FRAUD_PREVENTION,
    G3_0_SEEDS,
    G3_1_SEEDLINGS,
    G3_2_PLANTING_STOCK,
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
