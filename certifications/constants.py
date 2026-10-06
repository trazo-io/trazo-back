"""Certification vocabularies, and the two SET questions the rest of the codebase asks.

⛔ A CERTIFICATION TYPE IS A PROGRAM, NEVER A CERTIFYING AGENT.
   "CCOF" was in this list until 2026-08-27. CCOF is an ACA — it *issues* USDA Organic.
   The category error was not cosmetic:
     * `VERIFIER_REGISTRY` wires Organic Integrity Database verification to `usda_organic`
       ONLY, and `CertificationManager.tsx` renders the USDA operation-name + verify fields
       only for that type. A grower picking the honest-looking "CCOF" silently lost database
       verification — for the one operation OID would have confirmed.
     * The same form's `certifier_name` placeholder read "e.g., Oregon Tilth, CCOF", so one
       form offered the same fact as two different fields with no rule.
     * It hardcoded ONE certifier into the product vocabulary. Of the 981 operations on the
       September named list, 288 are certified by WSDA and zero by CCOF; naming CCOF and no
       other certifier baked a superseded California-first assumption into the data model.
   The certifying agent belongs in `Certification.certifier_name`. Migration
   `0031_retire_ccof_certification_type` moves the existing rows and keeps the agent name.

SET AUTHORITY
-------------
Five hardcoded copies of "which types count as organic" were spread across
`operation_readiness_service`, `audit_export_service` (three of them) and `osp_module_pdf`,
with FOUR different definitions between them — one even listed `ccof_organic` and
`ams_organic`, slugs that appear in no vocabulary at all. The sets below are the only
answer; `certifications/tests/test_cert_type_set_authority.py` fails if a copy reappears.
"""

CERTIFICATION_TYPE_CHOICES = [
    ("usda_organic", "USDA Organic"),
    ("cng", "Certified Naturally Grown"),
    ("real_organic_project", "Real Organic Project"),
    ("roc", "Regenerative Organic Certified"),
    ("korean_organic", "Korean Organic Certification"),
    ("non_gmo_project", "Non-GMO Project Verified"),
    ("global_gap", "GlobalG.A.P."),
    # 2026-08-27: the Washington channel motion sells through packing houses (§3d), and a
    # packer's buyer asks for PrimusGFS or GlobalG.A.P. by name. GlobalG.A.P. was here;
    # PrimusGFS was not, so a WA tree-fruit operation had to file its buyer-facing food
    # safety certificate as "Other".
    ("primus_gfs", "PrimusGFS"),
    # Pacific-Northwest specific and genuinely third-party (a named programme with a public
    # directory), which is what separates it from a self-created sustainability label.
    ("salmon_safe", "Salmon-Safe"),
    ("fair_trade", "Fair Trade Certified"),
    ("rainforest_alliance", "Rainforest Alliance"),
    ("sqf", "SQF Certified"),
    ("kosher", "Kosher Certified"),
    ("other", "Other"),
]

VERIFICATION_STATUS_CHOICES = [
    ("pending", "Pending Verification"),
    ("verified", "Verified via Database"),
    ("self_reported", "Self-Reported (Unverified)"),
    ("not_found", "Not Found in Database"),
    ("expired", "Certification Expired"),
    ("revoked", "Certification Revoked"),
    ("suspended", "Certification Suspended"),
    # Run 8 (2026-10-05). "verified" means a confirmed Organic Integrity Database entry and
    # nothing else. A similar name is a candidate the operator has not confirmed; a material
    # listing (OMRI, WSDA, National List) describes a product and never verifies a farm.
    ("possible_match", "Self-Reported (possible USDA database entry, not confirmed)"),
    ("listing_match", "Material listing match (not a verification)"),
]

#: Statuses a consumer surface lists. possible_match and listing_match are shown, as
#: self-reported (`Certification.consumer_display_status`); a list that omitted them made a
#: certification disappear from the buyer page the moment it was re-checked (review of #119).
CONSUMER_LISTED_STATUSES = ("verified", "self_reported", "possible_match", "listing_match")

# ---------------------------------------------------------------------------
# The two set questions. Import these — never retype the members.
# ---------------------------------------------------------------------------

# "Is this certificate issued under 7 CFR Part 205?" — the NOP question.
#
# Only a NOP certificate carries the § 205.404(d) no-expiry semantic and the § 205.406
# annual-continuation duty. ROP and ROC sit ON TOP of a USDA Organic certificate but are
# private standards with their own expiry; CNG is a non-NOP peer-review programme. Answering
# this question with any of them would print "does not expire per § 205.404(d)" over a
# certificate that does expire.
NOP_CERTIFICATION_TYPES = ("usda_organic",)

# "Does this operation hold an organic certification of some kind?" — deliberately broader
# than NOP_CERTIFICATION_TYPES.
#
# Used to decide whether organic checks APPLY at all, so a conventional grower is never told
# they will fail an inspection they were never taking. Being generous here shows a CNG or ROC
# operation guidance it can ignore; being narrow hides real blockers from an operation that
# needs them. `korean_organic` is out on purpose: it is a foreign equivalence, not a US
# organic certification, and the checks behind this set are all NOP-shaped.
ORGANIC_CONFERRING_CERT_TYPES = (
    "usda_organic",
    "cng",
    "real_organic_project",
    "roc",
)

# Maps cert types to their verifier dotted paths (extensible)
VERIFIER_REGISTRY = {
    "usda_organic": "certifications.services.usda_organic_verifier.USDAOrganicVerifier",
}

# Maps BusinessEvent.certification_type values to Certification.certification_type
BUSINESS_EVENT_TYPE_MAP = {
    "organic_usda": "usda_organic",
    "rainforest_alliance": "rainforest_alliance",
    "fair_trade": "fair_trade",
    "regenerative": "roc",
    "real_organic": "real_organic_project",
    "global_gap": "global_gap",
    "non_gmo": "non_gmo_project",
    "certified_naturally_grown": "cng",
    "cng": "cng",
    # Retired BusinessEvent options. Kept so a legacy record still maps rather than
    # disappearing — see history.models.DEPRECATED_CERTIFICATION_TYPES.
    "carbon_neutral": "other",
    "sustainable_agriculture": "other",
    "water_stewardship": "other",
    "food_safety": "sqf",
    "kosher": "kosher",
}

# Known text mappings for data migration from Establishment.certifications TextField
LEGACY_TEXT_MAP = {
    "usda organic": "usda_organic",
    "organic": "usda_organic",
    # A certifier's name in the free-text field means the operation is USDA Organic — the
    # agent is not the certification. The certifier itself is recovered into `certifier_name`
    # by the importer, not by this map.
    "ccof": "usda_organic",
    "certified naturally grown": "cng",
    "cng": "cng",
    "real organic project": "real_organic_project",
    "regenerative organic": "roc",
    "regenerative organic certified": "roc",
    "non-gmo": "non_gmo_project",
    "non gmo": "non_gmo_project",
    "non-gmo project": "non_gmo_project",
    "gap": "global_gap",
    "global gap": "global_gap",
    "globalgap": "global_gap",
    "global g.a.p.": "global_gap",
    "primusgfs": "primus_gfs",
    "primus gfs": "primus_gfs",
    "salmon-safe": "salmon_safe",
    "salmon safe": "salmon_safe",
    "fair trade": "fair_trade",
    "fair trade certified": "fair_trade",
    "rainforest alliance": "rainforest_alliance",
    "sqf": "sqf",
    "sqf certified": "sqf",
    "safe quality food": "sqf",
    "gfsi": "sqf",
    "kosher": "kosher",
    "ou kosher": "kosher",
    "orthodox union": "kosher",
    "kosher certified": "kosher",
}
