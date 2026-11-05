"""
The National List materials a grower may apply only under a condition, read for the OSP questions
that ask about them (WSDA AGR 2121 D4-D6a and H5/H5a, OTCO C4 4.5-1).

Five classes, each tied to the paragraph whose condition it carries:

    micronutrients       § 205.601(j)(7)  deficiency documented by soil or tissue testing, or another
                                          method the certifying agent approves
    magnesium_sulfate    § 205.601(j)(6)  a documented SOIL deficiency
    calcium_chloride     § 205.602(c)     a foliar spray for a calcium-uptake disorder only
    potassium_chloride   § 205.602(e)     mined, applied so chloride does not accumulate
    copper               § 205.601(i)(2), (i)(3)  applied so copper does not accumulate in the soil;
                                          for disease control, after § 205.206(a)-(d) prove insufficient

What decides a material's class, in this order and nothing else:
  * a confirmed National List classification (`confirmed_national_list_substance`), never the
    substring `national_list_suggestion`;
  * the WSDA listing's own product type and subtype, compared exactly ("Copper Hydroxide" under
    disease-and-pest-control); WSDA's copper sulfate under fertilizer-and-soil-amendment is a
    micronutrient, not a disease-control copper;
  * on a chemical record, the operator's `micronutrient_type` (zinc, boron, manganese, iron, copper,
    other: calcium, magnesium and sulfur are not § 205.601(j)(7) micronutrients) and, for copper, a
    fungicide or pesticide record of subtype `copper_fungicide`.
An OMRI-only product is never classified: its class is not Trazo's to guess. Copper logged as a
micronutrient is not "for plant disease control".

Everything here is a reading for the reviewer: the rule's words, the plan's materials of the class,
the records that contradict a No. It writes nothing, and it never rewrites the grower's answer.
"""

from __future__ import annotations

import logging

from certifications.services.national_list_citations import RULE_TEXT

logger = logging.getLogger(__name__)

MICRONUTRIENTS = "micronutrients"
MAGNESIUM_SULFATE = "magnesium_sulfate"
CALCIUM_CHLORIDE = "calcium_chloride"
POTASSIUM_CHLORIDE = "potassium_chloride"
COPPER = "copper"

#: The words a printed line uses for each class.
CLASS_WORDS = {
    MICRONUTRIENTS: "synthetic micronutrients",
    MAGNESIUM_SULFATE: "magnesium sulfate",
    CALCIUM_CHLORIDE: "calcium chloride",
    POTASSIUM_CHLORIDE: "potassium chloride",
    COPPER: "copper sulfate or fixed coppers",
}

#: The paragraphs printed beside an answer about each class, as `RULE_TEXT` keys.
CLASS_RULES = {
    MICRONUTRIENTS: (("205.601", "(j)(7)"),),
    MAGNESIUM_SULFATE: (("205.601", "(j)(6)"),),
    CALCIUM_CHLORIDE: (("205.602", "(c)"),),
    POTASSIUM_CHLORIDE: (("205.602", "(e)"),),
    COPPER: (("205.601", "introductory text"), ("205.601", "(i)(2)"), ("205.601", "(i)(3)")),
}

#: (section, catalogue row name, lowercase) -> class.
_SUBSTANCE_CLASS = {
    ("205.601", "soluble boron products"): MICRONUTRIENTS,
    (
        "205.601",
        "zinc/copper/iron/manganese/molybdenum/selenium/cobalt (sulfates, carbonates, oxides, silicates)",
    ): MICRONUTRIENTS,
    ("205.601", "magnesium sulfate"): MAGNESIUM_SULFATE,
    ("205.602", "calcium chloride (brine process)"): CALCIUM_CHLORIDE,
    ("205.602", "potassium chloride"): POTASSIUM_CHLORIDE,
    ("205.601", "copper hydroxide"): COPPER,
    ("205.601", "copper oxide"): COPPER,
    ("205.601", "copper oxychloride"): COPPER,
    ("205.601", "copper sulfate (fungicide)"): COPPER,
}

_FSA = "fertilizer-and-soil-amendment"
_DPC = "disease-and-pest-control"

#: (WSDA product type, WSDA subtype) -> class, compared exactly. From the WSDA Brand Name Material
#: List of 2026-03-06. "Chelated Fertilizer" and "Zinc Product" are left out: neither says the form is
#: one § 205.601(j)(7)(ii) lists. "Potassium Magnesium Sulfate" (langbeinite) is a mined mineral, not
#: § 205.601(j)(6) magnesium sulfate.
_WSDA_CLASS = {
    (_DPC, "Copper Hydroxide"): COPPER,
    (_DPC, "Coppers – fixed"): COPPER,
    (_FSA, "Boron"): MICRONUTRIENTS,
    (_FSA, "Cobalt Sulfate"): MICRONUTRIENTS,
    (_FSA, "Copper Sulfate"): MICRONUTRIENTS,
    (_FSA, "Ferrous Sulfate"): MICRONUTRIENTS,
    (_FSA, "Iron Sulfate"): MICRONUTRIENTS,
    (_FSA, "Manganese Sulfate"): MICRONUTRIENTS,
    (_FSA, "Zinc Sulfate"): MICRONUTRIENTS,
    (_FSA, "Micronutrient Fertilizer"): MICRONUTRIENTS,
    (_FSA, "Magnesium Sulfate"): MAGNESIUM_SULFATE,
    (_FSA, "Calcium Chloride"): CALCIUM_CHLORIDE,
    (_FSA, "Potassium Chloride"): POTASSIUM_CHLORIDE,
}

#: `ChemicalEvent.micronutrient_type` values that are § 205.601(j)(7) micronutrients. The audit
#: export draws the same line (`_build_micronutrient_subtable`).
MICRONUTRIENT_TYPES = frozenset({"zinc", "boron", "manganese", "iron", "copper", "other"})

#: The boolean that asks about each class, and the classes it covers.
GATES = {
    "applies_deficiency_materials": (MICRONUTRIENTS, MAGNESIUM_SULFATE),
    "applies_calcium_chloride": (CALCIUM_CHLORIDE,),
    "applies_potassium_chloride": (POTASSIUM_CHLORIDE,),
    "applies_copper_materials": (COPPER,),
}

#: The classes whose rule turns on the product's SOURCE, which only a product's listing can show:
#: § 205.602(e) prohibits potassium chloride "unless derived from a mined source". § 205.602(c) is not
#: here: it limits calcium chloride's USE (a foliar spray), which `calcium_chloride_foliar` asks, and
#: reading it as a rule about source states it backwards (review of back #311).
_SOURCE_WORDS = {
    POTASSIUM_CHLORIDE: ("§ 205.602(e)", "derived from a mined source"),
}


def substance_class(substance) -> str | None:
    if substance is None:
        return None
    key = (getattr(substance, "cfr_section", ""), " ".join((substance.substance_name or "").lower().split()))
    return _SUBSTANCE_CLASS.get(key)


def wsda_class(material) -> str | None:
    if material is None:
        return None
    return _WSDA_CLASS.get(((material.category or "").strip(), (material.subtype or "").strip()))


# --------------------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------------------


def _chemical_classes(events) -> dict:
    """{event pk: set of classes} for chemical records, in two queries however many records."""
    from certifications.models import NationalListSubstance, WSDAMaterial
    from history.services.national_list_basis import CONFIRMED_BASES

    substance_ids = {
        e.national_list_substance_id
        for e in events
        if e.national_list_substance_id and getattr(e, "national_list_basis", None) in CONFIRMED_BASES
    }
    substances = {s.pk: substance_class(s) for s in NationalListSubstance.objects.filter(pk__in=substance_ids)}
    wsda_ids = {e.wsda_material_id for e in events if getattr(e, "wsda_material_id", None)}
    wsda = {m.pk: wsda_class(m) for m in WSDAMaterial.objects.filter(pk__in=wsda_ids)}
    out = {}
    for e in events:
        found = set()
        if e.national_list_substance_id in substances and e.national_list_basis in CONFIRMED_BASES:
            found.add(substances[e.national_list_substance_id])
        if getattr(e, "wsda_material_id", None) in wsda:
            found.add(wsda[e.wsda_material_id])
        if e.type in ("FU", "PE") and (getattr(e, "chemical_subtype", "") or "") == "copper_fungicide":
            found.add(COPPER)
        if (getattr(e, "micronutrient_type", "") or "") in MICRONUTRIENT_TYPES:
            found.add(MICRONUTRIENTS)
        found.discard(None)
        out[e.pk] = found
    return out


def _soil_name_class(name) -> str | None:
    """A soil amendment's product name, read through the hand-checked alias table only: an exact
    catalogue name or a listed synonym ("Muriate of Potash"). Never a substring."""
    from certifications.services.national_list_aliases import canonical_key, resolve_alias

    key = canonical_key(name)
    if not key:
        return None
    resolved = canonical_key(resolve_alias(name) or "")
    for (_, catalogue_name), cls in _SUBSTANCE_CLASS.items():
        if canonical_key(catalogue_name) in (key, resolved):
            return cls
    return None


def logged_applications(bundle, cls) -> list:
    """The season's records of `cls`, oldest first. Chemical records by the rules in the module
    docstring; soil amendments by their product name, read through the same hand-checked alias table
    that classifies a spray record on save, so a soil record counts exactly as a chemical one named the
    same would (review of back #311: it suggested a Yes but was not counted against a No)."""
    chemical = list(bundle.chemical)
    classes = _chemical_classes(chemical)
    found = [e for e in chemical if cls in classes.get(e.pk, ())]
    found += [e for e in bundle.soil if _soil_name_class(getattr(e, "amendment_product_name", "")) == cls]
    return sorted(found, key=lambda e: (e.date is None, e.date))


def _product_name(event) -> str:
    for field in ("commercial_name", "amendment_product_name", "name"):
        value = (getattr(event, field, "") or "").strip()
        if value:
            return value
    return "a record with no product name"


def _names(events, limit: int = 6) -> str:
    names = sorted({_product_name(e) for e in events})
    shown = ", ".join(names[:limit])
    return shown + (f", and {len(names) - limit} more" if len(names) > limit else "")


# --------------------------------------------------------------------------------------
# The records check: the readiness row "National List conditions"
# --------------------------------------------------------------------------------------

#: § 205.602(c) allows calcium chloride only "as a foliar spray". These methods put a spray on the
#: canopy (`common.field_registry.APPLICATION_METHOD`).
FOLIAR_METHODS = frozenset({"foliar", "air_blast", "aerial"})
#: These put a material on or into the soil. A ground spray or chemigation can be either, so a record
#: with one of those, or with no method, is counted as "method does not show", never guessed.
SOIL_METHODS = frozenset({"broadcast", "banding", "drip", "injection", "soil_incorporation"})

#: What a lab record sampled. A soil test (`ST`) is soil unless it says otherwise; a lab analysis (`LA`)
#: says so in `sample_matrix`. Hull is a tissue: hull sampling at harvest is the almond boron test.
#: Compost and irrigation water are neither, so a zinc value on a water test is no basis.
SOIL_MATRICES = frozenset({"soil"})
TISSUE_MATRICES = frozenset({"leaf", "petiole", "hull"})

#: The `test_results` key that carries each nutrient's value: the four the soil form collects. A
#: nutrient with no key here (copper, "other", or a record classified by its listing alone) is matched
#: by any soil or tissue result, and the export says the value is not one Trazo records.
MICRONUTRIENT_RESULT_KEYS = {
    "zinc": "zinc_ppm",
    "boron": "boron_ppm",
    "manganese": "manganese_ppm",
    "iron": "iron_ppm",
}

#: `ChemicalEvent.application_purpose` values that name a use § 205.601(j)(7) excludes: "not to be used
#: as a defoliant, herbicide, or desiccant". Weed management is an herbicide use; plant growth
#: regulation is where a defoliant or desiccant is recorded.
EXCLUDED_MICRONUTRIENT_PURPOSES = frozenset({"weed_management", "plant_growth"})


def micronutrient_applications(events) -> tuple[list, list]:
    """(in scope, out of scope) among a season's chemical records that are micronutrient applications.

    In scope: classified as § 205.601(j)(7) micronutrients by the rules in the module docstring.
    Out of scope: a `micronutrient_type` of calcium, magnesium or sulfur with no such classification,
    listed by the export for completeness and never counted."""
    events = list(events)
    classes = _chemical_classes(events)
    in_scope = [e for e in events if MICRONUTRIENTS in classes.get(e.pk, ())]
    out_of_scope = [
        e
        for e in events
        if (getattr(e, "micronutrient_type", "") or "") and MICRONUTRIENTS not in classes.get(e.pk, ())
    ]
    return in_scope, out_of_scope


def lab_results(soil_events) -> list:
    """(date, matrix, results) for each dated soil test or lab analysis, results as recorded."""
    out = []
    for sev in soil_events:
        if sev.type == "ST":
            matrix = getattr(sev, "sample_matrix", None) or "soil"
        elif sev.type == "LA":
            matrix = getattr(sev, "sample_matrix", None)
        else:
            continue
        if matrix and sev.date:
            out.append((sev.date, matrix, sev.test_results if isinstance(sev.test_results, dict) else {}))
    return out


def prior_result(when, results, matrices, key=None):
    """The latest result of `matrices` dated on or before `when`, as (date, matrix, value), carrying a
    value for `key` when one is named; None when there is none. A result measured after an application
    is not the basis the rule asks for."""
    if when is None:
        return None
    found = [
        (date, matrix, values.get(key) if key else None)
        for date, matrix, values in results
        if matrix in matrices and date <= when and (key is None or values.get(key) not in (None, ""))
    ]
    return max(found, key=lambda f: f[0]) if found else None


def micronutrient_result(event, results):
    """The soil or tissue result on file on or before a micronutrient application, or None."""
    key = MICRONUTRIENT_RESULT_KEYS.get(getattr(event, "micronutrient_type", "") or "")
    return prior_result(event.date, results, SOIL_MATRICES | TISSUE_MATRICES, key)


def records_check(chemical_events, soil_events) -> dict:
    """The counts behind the readiness row, over one season's records. Counts only: a count says a record
    is not on file in Trazo, never that the application broke the rule."""
    bundle = _Records(list(chemical_events), list(soil_events))
    results = lab_results(bundle.soil)

    # A soil amendment record went on the soil by what it is; a chemical record says how in its method.
    sprays = {id(e) for e in bundle.chemical}
    calcium = logged_applications(bundle, CALCIUM_CHLORIDE)
    calcium_soil = calcium_unknown = 0
    for e in calcium:
        if id(e) not in sprays:
            calcium_soil += 1
            continue
        method = getattr(e, "application_method_structured", None)
        if method in FOLIAR_METHODS:
            continue
        if method in SOIL_METHODS:
            calcium_soil += 1
        else:
            calcium_unknown += 1

    micro = logged_applications(bundle, MICRONUTRIENTS)
    magnesium = logged_applications(bundle, MAGNESIUM_SULFATE)
    return {
        "calcium_chloride": len(calcium),
        "calcium_chloride_soil": calcium_soil,
        "calcium_chloride_method_unknown": calcium_unknown,
        "micronutrients": len(micro),
        "micronutrients_no_result": sum(1 for e in micro if micronutrient_result(e, results) is None),
        "micronutrients_excluded_purpose": sum(
            1 for e in micro if (getattr(e, "application_purpose", "") or "") in EXCLUDED_MICRONUTRIENT_PURPOSES
        ),
        "magnesium_sulfate": len(magnesium),
        "magnesium_sulfate_no_soil_result": sum(
            1 for e in magnesium if prior_result(e.date, results, SOIL_MATRICES) is None
        ),
    }


class _Records:
    """The two record lists `logged_applications` reads, for a caller that holds them already."""

    def __init__(self, chemical, soil):
        self.chemical = chemical
        self.soil = soil


# --------------------------------------------------------------------------------------
# The plan's materials list
# --------------------------------------------------------------------------------------


def plan_materials_of_class(osp, cls) -> tuple[list, int]:
    """([(PlanMaterial, how the operator says the restriction is met)], OMRI-only rows on the plan).

    A row is of the class by its National List row, its WSDA listing, or the operator entry's link to
    either. An OMRI-only row is counted, never classified."""
    from certifications.models import NationalListSubstance, PlanMaterialEntry, WSDAMaterial
    from certifications.services.material_restrictions import material_ref, operator_how_met
    from certifications.services.plan_materials import plan_materials

    rows = plan_materials(osp)
    nl_ids = {m.source_id for m in rows if m.source == "National List" and m.source_id}
    wsda_ids = {m.source_id for m in rows if m.source == "WSDA" and m.source_id}
    entries = {
        e.pk: e
        for e in PlanMaterialEntry.objects.filter(
            pk__in=[m.entry_id for m in rows if m.entry_id], osp=osp
        ).select_related("national_list_substance", "wsda_material")
    }
    substances = {s.pk: s for s in NationalListSubstance.objects.filter(pk__in=nl_ids)}
    wsda = {m.pk: m for m in WSDAMaterial.objects.filter(pk__in=wsda_ids)}

    matched, omri_only = [], 0
    for material in rows:
        found = None
        if material.source == "National List":
            found = substance_class(substances.get(material.source_id))
        elif material.source == "WSDA":
            found = wsda_class(wsda.get(material.source_id))
        entry = entries.get(material.entry_id)
        if found is None and entry is not None:
            found = substance_class(entry.national_list_substance) or wsda_class(entry.wsda_material)
        if found == cls:
            kind, mid, _ = material_ref(material)
            matched.append((material, operator_how_met(osp, kind, mid)))
        elif found is None and material.source == "OMRI":
            omri_only += 1
    return matched, omri_only


# --------------------------------------------------------------------------------------
# What the module PDF prints under an answer
# --------------------------------------------------------------------------------------


def _rule_lines(cls) -> list[str]:
    out = []
    for section, paragraph in CLASS_RULES[cls]:
        where = f"§ {section}, {paragraph}" if paragraph == "introductory text" else f"§ {section}{paragraph}"
        out.append(f'{where}: "{RULE_TEXT[(section, paragraph)]}"')
    return out


def _materials_lines(osp, cls) -> list[str]:
    matched, omri_only = plan_materials_of_class(osp, cls)
    words = CLASS_WORDS[cls]
    lines = []
    if matched:
        parts = []
        for material, how_met in matched:
            part = f"{material.name} ({material.source})"
            parts.append(f"{part}, how the restriction is met: {how_met}" if how_met else part)
        lines.append(f"On this plan's materials list as {words}: " + "; ".join(parts) + ".")
        if cls in _SOURCE_WORDS and all(m.source == "National List" and not m.entry_id for m, _ in matched):
            cite, source = _SOURCE_WORDS[cls]
            lines.append(
                f"[REVIEW] {cite} prohibits {words} unless it is {source}. The only {words} on this plan's list "
                "is the National List entry, which names no product whose listing shows its source."
            )
    elif omri_only:
        lines.append(
            f"No material on this plan's list is classified as {words} by its National List or WSDA listing; "
            f"the {omri_only} OMRI-listed product(s) on it are not classified by Trazo."
        )
    else:
        lines.append(f"[REVIEW] This plan's materials list holds no material classified as {words}.")
    return lines


def _chosen_classes(question_key, answers) -> tuple:
    from certifications.osp_modules.conditions import answer_value

    classes = GATES[question_key]
    if question_key != "applies_deficiency_materials":
        return classes
    chosen = answer_value(answers, "deficiency_materials") or []
    return tuple(c for c in classes if c in chosen) or classes


def module_lines(osp, module, question, value, answers, bundles: dict) -> list[str]:
    """The lines printed under one answered question of G4.0 or G5.0 about these materials."""
    if module.key not in ("g4_0_rotation_soil", "g5_0_pest"):
        return []
    key = question.key
    if key == "magnesium_sulfate_verification" and isinstance(value, (list, tuple)):
        if "soil_analysis" not in value:
            return [
                "[REVIEW] § 205.601(j)(6) allows magnesium sulfate with a documented soil deficiency; soil "
                "analysis is not among the methods given."
            ]
        return []
    if key == "calcium_chloride_foliar" and value is False:
        return [
            "[REVIEW] § 205.602(c) prohibits calcium chloride except as a foliar spray to treat a physiological "
            "disorder associated with calcium uptake."
        ]
    if key not in GATES or not isinstance(value, bool):
        return []
    lines = []
    try:
        if value:
            for cls in _chosen_classes(key, answers):
                lines += _rule_lines(cls)
                lines += _materials_lines(osp, cls)
        else:
            from certifications.services.common_osp_records import EvidenceBundle
            from certifications.services.osp_prefill import _date_span

            if "bundle" not in bundles:
                bundles["bundle"] = EvidenceBundle(osp.establishment)
            for cls in GATES[key]:
                events = logged_applications(bundles["bundle"], cls)
                if events:
                    lines.append(
                        f"[REVIEW] The records in Trazo show {len(events)} application(s) of products classified "
                        f"as {CLASS_WORDS[cls]}{_date_span(events)}: {_names(events)}."
                    )
    except Exception:  # noqa: BLE001 - a reading that fails must not sink the packet
        logger.exception("Restricted-material lines could not be read for %s", key)
        return ["In Trazo: the materials and records for this answer could not be read."]
    return lines


# --------------------------------------------------------------------------------------
# Prefill: a record suggests Yes; no record suggests nothing
# --------------------------------------------------------------------------------------


def _suggest(bundle, classes) -> dict | None:
    from certifications.services.osp_prefill import _date_span

    events = []
    for cls in classes:
        events += logged_applications(bundle, cls)
    if not events:
        return None
    words = " or ".join(CLASS_WORDS[c] for c in classes)
    plural = len(events) != 1
    return {
        "value": True,
        "basis": (f"{len(events)} record{'s' if plural else ''} of {words}{_date_span(events)}: {_names(events, 3)}."),
        "count": len(events),
    }


def deficiency_materials_evidence(bundle, question):
    return _suggest(bundle, (MICRONUTRIENTS, MAGNESIUM_SULFATE))


def calcium_chloride_evidence(bundle, question):
    return _suggest(bundle, (CALCIUM_CHLORIDE,))


def potassium_chloride_evidence(bundle, question):
    return _suggest(bundle, (POTASSIUM_CHLORIDE,))


def copper_evidence(bundle, question):
    return _suggest(bundle, (COPPER,))
