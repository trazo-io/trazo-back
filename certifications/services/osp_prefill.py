"""
Guided-OSP prefill resolution — evidence → SUGGESTION, never an answer.

## The rule this service lives under

§ 205.201(a) makes the **producer** the author of the organic system plan, and the same
project history that shaped `common_osp_records.py` applies verbatim here: a Smart Setup
template once fabricated a backdated record attributed to the farmer by name, and this
codebase has already had to un-ship auto-attestation once. So:

  - A resolver output is returned on module GET as a `suggestions` entry and is NEVER
    written to `module_responses`. The only path from suggestion to answer is the
    operator pressing "Use suggestion" in the wizard, which submits it through the
    normal PUT like any hand-typed answer.
  - Every suggestion carries a `basis` string naming the records it came from
    ("6 cover-crop events this season"), so the operator is accepting a described
    claim, not a mystery checkbox.
  - A resolver only ever suggests option values that exist on the question TODAY
    (`_limit_to_options`) — module content edits can't strand invalid suggestions.

## Why resolvers live here and not on the Question

`Prefill(source="...")` on a question declares intent; the mapping from farm records to
answer values needs the event models, and schema.py deliberately imports no Django. The
registry below is keyed by those source names. A declared source with no registered
resolver is a no-op (logged once) — content authors may declare sources ahead of
resolver support.

Reuses `EvidenceBundle` from common_osp_records so "what counts as evidence" — the
windowing, the prefetch, the emptiness rules — has exactly one definition.
"""

from __future__ import annotations

import logging

from certifications.services.common_osp_records import EvidenceBundle, _has_content

logger = logging.getLogger(__name__)
_warned_missing: set = set()


def _limit_to_options(values: list, question) -> list:
    """Keep only values that are real options on the question, preserving option order."""
    declared = [o.value for o in (question.options or ())]
    return [v for v in declared if v in values]


def _date_span(events) -> str:
    dates = sorted(e.date.date() if hasattr(e.date, "date") else e.date for e in events if e.date)
    if not dates:
        return ""
    if dates[0] == dates[-1]:
        return f" on {dates[0].isoformat()}"
    return f" between {dates[0].isoformat()} and {dates[-1].isoformat()}"


# --------------------------------------------------------------------------------------
# Resolvers — each returns {"value": <kind-shaped>, "basis": str, "count": int} or None.
# value shape by question kind: checkbox_group -> list[str], radio -> str, textarea -> str.
# --------------------------------------------------------------------------------------


def _cover_crop_evidence(bundle, question):
    """G4.0 in_lieu_practices — biological diversity practices with logged evidence."""
    cover = bundle.soils("CC")
    habitat = bundle.soils("HD")
    values = []
    parts = []
    if cover:
        values.append("cover_crops")
        parts.append(f"{len(cover)} cover-crop event{'s' if len(cover) != 1 else ''}")
    if habitat:
        values.append("hedgerows")
        parts.append(f"{len(habitat)} habitat/hedgerow event{'s' if len(habitat) != 1 else ''}")
    values = _limit_to_options(values, question)
    if not values:
        return None
    return {
        "value": values,
        "basis": " and ".join(parts) + " logged this season",
        "count": len(cover) + len(habitat),
    }


def _soil_amendment_evidence(bundle, question):
    """G4.0 fertility_components — components evidenced by logged soil/input events."""
    values = []
    parts = []
    cover = bundle.soils("CC")
    compost = bundle.soils("CO")
    fertilizer = bundle.chem("FE")
    if cover:
        values.append("cover_crops")
        parts.append(f"{len(cover)} cover-crop event{'s' if len(cover) != 1 else ''}")
    if compost:
        values.append("compost")
        parts.append(f"{len(compost)} composting event{'s' if len(compost) != 1 else ''}")
    if fertilizer:
        values.append("blended_fertilizers")
        parts.append(f"{len(fertilizer)} fertilizer application{'s' if len(fertilizer) != 1 else ''}")
    values = _limit_to_options(values, question)
    if not values:
        return None
    return {
        "value": values,
        "basis": ", ".join(parts) + " logged this season",
        "count": len(cover) + len(compost) + len(fertilizer),
    }


def _tillage_evidence(bundle, question):
    """G4.0 tillage_practices (textarea) — a drafted starting sentence from logged passes.

    The draft states only what the log shows (counts and dates); the operator adds
    implement, depth, and intent. It must never assert practices the events don't show.
    """
    tillage = bundle.soils("TI")
    cultivation = bundle.prod("CU")
    n = len(tillage) + len(cultivation)
    if n == 0:
        return None
    span = _date_span(tillage + cultivation)
    draft = (
        f"This season's log shows {n} tillage/cultivation pass{'es' if n != 1 else ''}{span}. "
        "Implements and working depth: "
    )
    parts = []
    if tillage:
        parts.append(f"{len(tillage)} tillage event{'s' if len(tillage) != 1 else ''}")
    if cultivation:
        parts.append(f"{len(cultivation)} cultivation event{'s' if len(cultivation) != 1 else ''}")
    return {
        "value": draft,
        "basis": " and ".join(parts) + " logged",
        "count": n,
    }


# ProductionEvent.seed_certification_status -> seeds_used option value. Treatment
# (seed_treatment free text) upgrades the *_untreated value to its *_treated sibling.
_SEED_STATUS_TO_OPTION = {
    "certified_organic": ("organic_untreated", "organic_treated"),
    # Transitional seed is not certified organic; for § 205.204 purposes it is
    # non-organic seed and needs the same commercial-availability documentation.
    "transitional": ("non_organic_untreated", "non_organic_treated"),
    "non_organic_untreated": ("non_organic_untreated", "non_organic_treated"),
    "non_organic_treated": ("non_organic_treated", "non_organic_treated"),
}


def _seed_status(bundle, question):
    """G3.0 seeds_used — seed classes evidenced by planting events."""
    plantings = [e for e in bundle.prod("PL") if getattr(e, "seed_certification_status", None)]
    if not plantings:
        return None
    values = set()
    for e in plantings:
        pair = _SEED_STATUS_TO_OPTION.get(e.seed_certification_status)
        if not pair:
            continue
        untreated, treated = pair
        values.add(treated if _has_content(getattr(e, "seed_treatment", None)) else untreated)
    values = _limit_to_options(sorted(values), question)
    if not values:
        return None
    n = len(plantings)
    return {
        "value": values,
        "basis": f"seed status recorded on {n} planting event{'s' if n != 1 else ''}",
        "count": n,
    }


def _seed_search_evidence(bundle, question):
    """G3.0 ca_search_before_use (radio): documented search, from plantings that used non-organic seed."""
    plantings = [e for e in bundle.prod("PL") if getattr(e, "seed_certification_status", None)]
    if not plantings:
        return None
    non_organic = [e for e in plantings if e.seed_certification_status != "certified_organic"]
    if not non_organic:
        # "All organic" was retired as an answer (2026.11.25): the question shows only when non-organic seed
        # or stock is declared, so all-organic plantings suggest nothing here.
        return None
    searched = [e for e in non_organic if _has_content(getattr(e, "seed_search_attempts", None))]
    if not searched:
        # Non-organic seed with NO documented search is a § 205.204(a)(1) gap, not a
        # suggestion — stay silent rather than suggest an answer the records refute.
        return None
    attempts = sum(len(e.seed_search_attempts or []) for e in searched)
    return {
        "value": "documented_search",
        "basis": (
            f"{attempts} documented supplier contact{'s' if attempts != 1 else ''} on "
            f"{len(searched)} planting event{'s' if len(searched) != 1 else ''} using non-organic seed"
        ),
        "count": attempts,
    }


def _pest_monitoring_scope(bundle, question):
    """G5.0 monitoring_scope (checkbox_group) — from scouting and trap records.

    Scouting is the single most-logged record on a perennial operation and, until this
    resolver existed, it suggested nothing: the original five resolvers were all
    annual-crop shaped (seed status, seed search, tillage), so a mature orchard with a
    full season on file got two suggestions out of the whole questionnaire.

    Deliberately conservative. A scouting record proves the operation monitors pest
    pressure; it does not prove they track disease, weeds or beneficials as distinct
    programmes. Suggesting those from the same events would put words in the operator's
    mouth, so only `pest_populations` is offered and the rest stay theirs to add.
    """
    scouting = bundle.pests("SC", "TM", "TA")
    if not scouting:
        return None
    values = _limit_to_options(["pest_populations"], question)
    if not values:
        return None
    return {
        "value": values,
        "basis": (
            f"{len(scouting)} scouting and trap-monitoring record"
            f"{'s' if len(scouting) != 1 else ''} logged{_date_span(scouting)}"
        ),
        "count": len(scouting),
    }


def _pest_monitoring_frequency(bundle, question):
    """G5.0 monitoring_frequency (radio) — the cadence the records actually show.

    The median gap between scouting records is reported verbatim in the basis so the
    operator can see what the suggestion was derived from and correct it. Bands are wide
    on purpose: records cluster around field visits, not calendars, and a suggestion that
    reads "weekly" off a fortnightly history would be a false statement about the
    operation dressed up as help.
    """
    scouting = sorted(
        (e for e in bundle.pests("SC", "TM", "TA") if e.date),
        key=lambda e: e.date,
    )
    if len(scouting) < 3:
        return None

    dates = [e.date.date() if hasattr(e.date, "date") else e.date for e in scouting]
    gaps = sorted((dates[i + 1] - dates[i]).days for i in range(len(dates) - 1))
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return None
    median = gaps[len(gaps) // 2]

    if median <= 10:
        candidate = "weekly"
    elif median <= 45:
        candidate = "monthly"
    else:
        candidate = "seasonally"
    if candidate not in [o.value for o in (question.options or ())]:
        return None

    return {
        "value": candidate,
        "basis": (
            f"{len(scouting)} scouting records logged, a median of {median} day" f"{'s' if median != 1 else ''} apart"
        ),
        "count": len(scouting),
    }


def _storage_location_evidence(bundle, question):
    """G6.2 storage_locations (checkbox_group) — from where harvests were actually stored.

    Only `on_farm_dry` / `on_farm_cold` can be inferred, and only when a harvest or
    post-harvest record names a storage location on this operation. Off-farm and
    third-party storage are relationships Trazo does not observe, so they are never
    suggested — their absence here is not evidence they do not exist.
    """
    stored = bundle.with_field(bundle.prod("HA", "PH"), "storage_location")
    if not stored:
        return None
    named = {str(getattr(e, "storage_location", "")).lower() for e in stored}
    values = []
    if any("cold" in n or "cooler" in n or "refriger" in n for n in named):
        values.append("on_farm_cold")
    if any(("dry" in n or "shed" in n or "barn" in n) for n in named):
        values.append("on_farm_dry")
    values = _limit_to_options(values, question)
    if not values:
        return None
    return {
        "value": values,
        "basis": (
            f"{len(stored)} harvest or post-harvest record"
            f"{'s' if len(stored) != 1 else ''} naming an on-farm storage location"
        ),
        "count": len(stored),
    }


def _applies_inputs_evidence(bundle, question):
    """G5.0 applies_pest_weed_disease_inputs (boolean) — did the operation apply any?

    The one question on the module the log answers with certainty: a logged pesticide,
    herbicide or fungicide application IS the operation applying a pest/weed/disease input.

    Note the asymmetry, which is the whole point. A logged application suggests TRUE. The
    absence of one suggests NOTHING — an operation that applied something and did not log it
    would otherwise have Trazo draft "no" on its behalf, which is the auto-attestation failure
    this service exists to prevent (§ 205.201(a): the producer authors the plan).
    """
    applications = bundle.chem("PE", "HE", "FU")
    if not applications:
        return None
    return {
        "value": True,
        "basis": (
            f"{len(applications)} pest, weed or disease input application"
            f"{'s' if len(applications) != 1 else ''} logged{_date_span(applications)}"
        ),
        "count": len(applications),
    }


#: Materials Application row -> (event types logged for it, the words the suggestion uses).
MATERIALS_CATEGORIES = {
    "fertilizers_listed": (("FE",), "soil-fertility"),
    "pest_disease_weed_listed": (("PE", "HE", "FU"), "pest, weed or disease"),
    "post_harvest_contact_listed": (("PH",), "post-harvest contact"),
    # CCOF Materials Application §C: seed treatments on planting records and tank-mix partners on
    # application records (growing media have no record of their own; the list is their only source).
    "crop_production_aids_listed": ((), "seed treatment or adjuvant"),
}

#: Statements elsewhere in the plan that say the same thing as a Materials Application row, read against
#: that row's products: CCOF G4.0 A3 "List all fertility materials planned for use on your Grower Materials
#: Application" is the fertilizer row's statement asked on G4.0.
MATERIALS_CATEGORY_OF = {"fertility_inputs_listed": "fertilizers_listed"}


def materials_category(question_key):
    """The Materials Application row a statement is read against, or None."""
    key = MATERIALS_CATEGORY_OF.get(question_key, question_key)
    return key if key in MATERIALS_CATEGORIES else None


def _seed_treatment_names(events) -> list:
    """(event, name) for each planting record naming a seed treatment, less "untreated" and its spellings."""
    from certifications.services.common_osp_workbooks import names_a_treatment

    out = []
    for e in events:
        name = (getattr(e, "seed_treatment", "") or "").strip()
        if getattr(e, "seed_treatment_allowed_basis", "") == "untreated" or not names_a_treatment(name):
            continue
        out.append((e, name))
    return out


def _tank_mix_names(events) -> list:
    """(event, name) for each tank-mix partner an application record names."""
    out = []
    for e in events:
        for partner in getattr(e, "tank_mix_partners", None) or []:
            if isinstance(partner, dict):
                out.append((e, (partner.get("commercial_name") or "").strip()))
    return out


def category_applications(bundle, question_key):
    """(applications, distinct product names, applications with no name) for one Materials
    Application row. An unnamed application cannot be matched to the list, so callers need the
    count apart from the names.

    The fertilizer row reads soil amendments too: compost, manure and mined minerals are logged
    as soil management events, not chemical ones, and the row's own question covers "all
    fertilizer and soil amendment materials" (review of back #279).
    """
    question_key = materials_category(question_key)
    spec = MATERIALS_CATEGORIES.get(question_key)
    if spec is None:
        return [], [], 0
    types, _label = spec
    if question_key == "crop_production_aids_listed":
        named = _seed_treatment_names(getattr(bundle, "production_events", []))
        named += _tank_mix_names(getattr(bundle, "chemical", []))
    elif question_key == "post_harvest_contact_listed":
        # NOTE: dead until 2026-09-12. This branch filtered ChemicalEvent for type "PH", a code that
        # model never carries (FE/PE/FU/HE only). A post-harvest sanitizer is a ProductionEvent
        # of type PH with `sanitizer_name` set, so the suggestion could not fire whatever was
        # logged (CCOF Materials Application §D, listing evidence).
        named = [(e, getattr(e, "sanitizer_name", "")) for e in bundle.prod("PH")]
        named = [(e, n) for e, n in named if (n or "").strip()]
    else:
        named = [(e, e.commercial_name) for e in bundle.chem(*types)]
        if question_key == "fertilizers_listed":
            # A soil event that names no amendment is tillage or a cover crop, not an application.
            amendments = [(e, getattr(e, "amendment_product_name", "")) for e in getattr(bundle, "soil", [])]
            named += [(e, n) for e, n in amendments if (n or "").strip()]
    events = [e for e, _n in named]
    names = sorted({(n or "").strip() for _e, n in named if (n or "").strip()})
    return events, names, sum(1 for _e, n in named if not (n or "").strip())


def logged_category_names(establishment, question_key) -> list[str]:
    """The product names the records show for one Materials Application row, read straight from the
    event tables: the attestation gate runs on every module write and status read, and an
    `EvidenceBundle` loads every production with six event relations to answer it."""
    from history.models import ChemicalEvent, ProductionEvent, SoilManagementEvent

    question_key = materials_category(question_key)
    spec = MATERIALS_CATEGORIES.get(question_key)
    if spec is None:
        return []
    types, _label = spec
    scope = {"history__parcel__establishment": establishment}
    if question_key == "crop_production_aids_listed":
        planting = (
            ProductionEvent.objects.filter(**scope).exclude(seed_treatment__isnull=True).exclude(seed_treatment="")
        )
        applied = ChemicalEvent.objects.filter(**scope).exclude(tank_mix_partners=[])
        named = _seed_treatment_names(planting) + _tank_mix_names(applied)
        return sorted({n for _e, n in named if n})
    if question_key == "post_harvest_contact_listed":
        names = ProductionEvent.objects.filter(type="PH", **scope).values_list("sanitizer_name", flat=True)
    else:
        names = list(ChemicalEvent.objects.filter(type__in=types, **scope).values_list("commercial_name", flat=True))
        if question_key == "fertilizers_listed":
            names += list(SoilManagementEvent.objects.filter(**scope).values_list("amendment_product_name", flat=True))
    return sorted({(n or "").strip() for n in names if (n or "").strip()})


def unlisted_category_products(osp, bundle, question_key) -> list[str]:
    """Logged product names for one Materials Application row that the plan's list does not hold.

    The one reading of "not on the plan" is `plan_materials.unmatched_logged_materials`, which the
    materials page prints from as well, so the category line and the page cannot disagree: a name
    is on the plan by exact match or by a current identity decision that folds every one of its
    uses into a listed product. UNMATCHED, not unapproved.
    """
    from certifications.services.plan_materials import _norm, unmatched_logged_materials

    _events, names, _unnamed = category_applications(bundle, question_key)
    if not names:
        return []
    not_on_plan = {_norm(name) for name in unmatched_logged_materials(osp)}
    return [name for name in names if _norm(name) in not_on_plan]


def _materials_category_evidence(bundle, question):
    """Materials Application: is each category of applied input on the materials list?

    The certifier's real question is not "do you have a list" but "does the list match what
    you actually used". Trazo holds both sides of that comparison, so it suggests Yes only when
    the comparison says so: every application in the category names its product, and every
    product is on this plan's materials list, by name or by the operator's identity decision.

    Until 2026-11-04 the suggestion was Yes whenever anything had been applied, without reading
    the list at all, so a product used and never listed produced a "Suggested from your records:
    Yes" to OTCO C5 5.1-6 ("I have listed all substances on my OSP Materials List section C11").
    A suggestion is the operator's to accept, but it pointed the wrong way in exactly the case
    the statement exists to catch.

    Keyed by question so one resolver serves every category row.
    """
    spec = MATERIALS_CATEGORIES.get(question.key)
    osp = getattr(bundle, "osp", None)
    if spec is None or osp is None:
        # Without the plan there is no list to compare against, so there is nothing to suggest.
        return None
    _types, label = spec
    events, named, unnamed = category_applications(bundle, question.key)
    if not events:
        # No logged application in this category. That is NOT evidence the category is
        # complete or empty — the operator may use materials Trazo never sees — so suggest
        # nothing rather than a reassuring "yes".
        return None
    if unnamed:
        # An application with no product name cannot be matched to the list.
        return None
    if unlisted_category_products(osp, bundle, question.key):
        # The records name a product the list does not hold. The module PDF names them beside
        # the answer; the suggestion stays silent rather than say No, because a brand covered by
        # a substance entry is on the list under another name until the operator ties the two.
        return None
    shown = ", ".join(named[:4]) + (f" and {len(named) - 4} more" if len(named) > 4 else "")
    return {
        "value": True,
        "basis": (
            f"{len(events)} {label} application{'s' if len(events) != 1 else ''} logged, using: {shown}. "
            "Each one is on this plan's materials list."
        ),
        "count": len(events),
    }


# G4.1 materials_applied — lexical markers that identify an amendment category WITHOUT
# guessing. Deliberately incomplete: the categories left out are the ones whose options carry
# a regulatory consequence that a wrong guess would misapply.
#
# Picking wrong here is not a cosmetic error. "Raw manure" triggers the § 205.203(c)(1) 90/120
# day pre-harvest intervals; "compost produced on this farm" triggers the § 205.203(c)(2) C:N,
# temperature and turning regime; "purchased compost" needs only supplier documentation. Each
# option opens a different downstream question set, so a suggestion the operator accepts on
# trust changes which rules their plan claims to follow.
#
# So a marker only maps when the operator's own wording is unambiguous, and on-farm vs
# purchased is never inferred from a product name — that distinction is settled by whether a
# manufacturer is recorded, and by nothing else.
_AMENDMENT_MARKERS = (
    ("vermicompost", "vermicompost"),
    ("worm casting", "vermicompost"),
    ("compost tea", "compost_tea"),
    ("raw manure", "raw_manure"),
    ("fresh manure", "raw_manure"),
    ("uncomposted", "raw_manure"),
    ("pelleted", "processed_manure"),
    ("heat-treated", "processed_manure"),
)


def _manure_compost_evidence(bundle, question):
    """G4.1 materials_applied (checkbox_group) — categories evidenced by logged amendments.

    Fires on the amendment's own fields rather than on the subtype alone: a walnut grower logs
    "Composted Poultry Manure 3-2-2" as an organic-matter amendment, not under a composting
    subtype, so § 205.203(c) was asking twelve questions with nothing suggested while the
    amendment sat in the log by name.

    Ambiguous wording yields NO suggestion. "Composted Poultry Manure 3-2-2" could be purchased
    compost or a processed manure product, and only the operator knows which — see
    `_AMENDMENT_MARKERS` for why that matters.
    """
    amendments = bundle.soils("OM", "CO")
    named = [e for e in amendments if _has_content(getattr(e, "amendment_type", None))]
    if not named:
        return None

    values = []
    matched = []
    for event in named:
        label = str(getattr(event, "amendment_type", "")).strip()
        lowered = label.lower()
        for marker, option in _AMENDMENT_MARKERS:
            if marker in lowered:
                if option not in values:
                    values.append(option)
                matched.append(label)
                break
        else:
            # A "compost" product with a recorded manufacturer was bought, not made here.
            # Without a manufacturer we say nothing: absence of the field is not evidence the
            # operation composted it themselves.
            if "compost" in lowered and _has_content(getattr(event, "amendment_manufacturer", None)):
                if "purchased_compost" not in values:
                    values.append("purchased_compost")
                matched.append(label)

    values = _limit_to_options(values, question)
    if not values:
        return None
    labels = sorted(set(matched))
    return {
        "value": values,
        "basis": (
            f"{len(matched)} amendment record{'s' if len(matched) != 1 else ''} logged"
            f"{_date_span(named)}: {', '.join(labels[:3])}"
        ),
        "count": len(matched),
    }


def _post_harvest_water_evidence(bundle, question):
    """G6.4 uses_water / wash_water_additives_added / wash_water_chlorine_added — from PH records.

    A post-harvest processing record that names a wash sanitizer (`sanitizer_name`, with its ppm
    and rinse step) IS water contacting product with a substance added to it. So:

      uses_water                  → True when any PH record names a sanitizer
      wash_water_additives_added  → True, same evidence
      wash_water_chlorine_added   → True only when a named sanitizer reads as a chlorine material

    Same asymmetry as every resolver here: a record suggests TRUE, its absence suggests nothing.
    A packing line that rinses with plain water logs no sanitizer and gets no suggestion either
    way — the operator says so. Chlorine is matched on the substance words, never on a brand.
    """
    events = [e for e in bundle.prod("PH") if (getattr(e, "sanitizer_name", "") or "").strip()]
    if not events:
        return None
    names = sorted({(getattr(e, "sanitizer_name", "") or "").strip() for e in events})
    if question.key == "wash_water_chlorine_added":
        chlorine = [n for n in names if any(w in n.lower() for w in ("chlor", "bleach"))]
        if not chlorine:
            return None
        names = chlorine
    shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    plural = len(events) != 1
    return {
        "value": True,
        "basis": (
            f"{len(events)} post-harvest record{'s' if plural else ''} name{'' if plural else 's'} a wash-water "
            f"sanitizer{_date_span(events)}: {shown}."
        ),
        "count": len(events),
    }


def _restricted():
    # Imported late: restricted_materials imports `_date_span` from here.
    from certifications.services import restricted_materials

    return restricted_materials


PREFILL_RESOLVERS = {
    "post_harvest_water_evidence": _post_harvest_water_evidence,
    "applies_inputs_evidence": _applies_inputs_evidence,
    "materials_category_evidence": _materials_category_evidence,
    "manure_compost_evidence": _manure_compost_evidence,
    "cover_crop_evidence": _cover_crop_evidence,
    "soil_amendment_evidence": _soil_amendment_evidence,
    "tillage_evidence": _tillage_evidence,
    "seed_status": _seed_status,
    "seed_search_evidence": _seed_search_evidence,
    "pest_monitoring_scope": _pest_monitoring_scope,
    "pest_monitoring_frequency": _pest_monitoring_frequency,
    "storage_location_evidence": _storage_location_evidence,
    # The National List materials allowed only under a condition (restricted_materials).
    "deficiency_materials_evidence": lambda bundle, q: _restricted().deficiency_materials_evidence(bundle, q),
    "calcium_chloride_evidence": lambda bundle, q: _restricted().calcium_chloride_evidence(bundle, q),
    "potassium_chloride_evidence": lambda bundle, q: _restricted().potassium_chloride_evidence(bundle, q),
    "copper_evidence": lambda bundle, q: _restricted().copper_evidence(bundle, q),
}


def resolve_suggestions(module, establishment, start_date=None, end_date=None, osp=None) -> dict:
    """All resolvable suggestions for one module: {question_key: {value, basis, count}}.

    Returns suggestions for answered questions too — the wizard decides visibility
    (it shows the chip only while the question is unanswered). A resolver exception
    is contained per-question: one broken resolver must not take down the module GET.
    """
    wanted = [(page, q) for page in module.pages for q in page.questions if q.prefill is not None]
    if not wanted:
        return {}

    bundle = EvidenceBundle(establishment, start_date=start_date, end_date=end_date, osp=osp)
    out: dict = {}
    for _page, q in wanted:
        resolver = PREFILL_RESOLVERS.get(q.prefill.source)
        if resolver is None:
            if q.prefill.source not in _warned_missing:
                _warned_missing.add(q.prefill.source)
                logger.warning("No prefill resolver registered for source '%s'", q.prefill.source)
            continue
        try:
            suggestion = resolver(bundle, q)
        except Exception:  # noqa: BLE001 — per-question containment, see docstring
            logger.exception("Prefill resolver '%s' failed for question '%s'", q.prefill.source, q.key)
            continue
        if suggestion:
            out[q.key] = suggestion
    return out
