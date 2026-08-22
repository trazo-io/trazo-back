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
CONTENT_VERSION = "2026.08.22"

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
