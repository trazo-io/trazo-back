CERTIFICATION_TYPE_CHOICES = [
    ("usda_organic", "USDA Organic"),
    ("ccof", "CCOF"),
    ("cng", "Certified Naturally Grown"),
    ("real_organic_project", "Real Organic Project"),
    ("roc", "Regenerative Organic Certified"),
    ("non_gmo_project", "Non-GMO Project Verified"),
    ("global_gap", "GlobalG.A.P."),
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
]

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
    "global_gap": "global_gap",
    "non_gmo": "non_gmo_project",
    "certified_naturally_grown": "cng",
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
    "ccof": "ccof",
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
