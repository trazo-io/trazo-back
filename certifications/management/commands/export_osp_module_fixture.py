"""
Export the guided-OSP module registry + evaluator golden cases for the frontend.

The backend evaluator (`osp_modules/conditions.py`) and its TS twin
(`trazo-app/src/config/osp/conditionEval.ts`) must agree exactly — a drift means the
wizard shows a page the server won't validate, or hides one it requires. This command
freezes the contract: it serializes the registry AND computes, with the PYTHON
evaluator, the visible-question sets and missing-required lists for a battery of
answer fixtures. The frontend test replays the same fixtures through the TS evaluator
and asserts identical output. Change semantics on either side and the other side's
test fails — that is the point.

Run after ANY change to osp_modules content or evaluator semantics:

    poetry run python manage.py export_osp_module_fixture

The fixture is committed alongside the frontend test (same repo pattern as the
padding-detector sync noted in OSPView.tsx).
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from certifications.osp_modules import CONTENT_VERSION, MODULE_REGISTRY, serialize_registry
from certifications.osp_modules.conditions import missing_required, visible_questions

DEFAULT_OUT = (
    Path(__file__).resolve().parents[4] / "trazo-app/src/config/osp/__tests__/fixtures/module-definitions.json"
)

# Answer batteries per module — chosen to exercise every op in CONDITION_OPS and the
# N/A path. Keys are case labels; values are bare answer dicts (the evaluator accepts
# both bare and enveloped shapes).
GOLDEN_ANSWER_CASES = {
    "g3_0_seeds": {
        "unanswered": {},
        "all_none": {
            "seeds_used": ["none"],
            "seedlings_used": ["none"],
            "planting_stock_used": ["none"],
        },
        "non_organic_untreated": {"seeds_used": ["non_organic_untreated"]},
        "organic_treated": {"seeds_used": ["organic_treated"]},
        "non_organic_treated_with_stock": {
            "seeds_used": ["non_organic_treated"],
            "planting_stock_used": ["organic"],
        },
        "stale_hidden_branch": {
            "seeds_used": ["none"],
            "ca_search_before_use": "documented_search",
        },
    },
    # Irrigation sources and shared lines (2026.11.09): `not_includes` is TRUE while unanswered, so the
    # shared-lines question shows until "we do not irrigate" is ticked; the TS twin must agree.
    "g4_2_natural_resources": {
        "unanswered": {},
        "not_irrigated": {"irrigation_source_types": ["not_irrigated"]},
        "district_shared": {
            "irrigation_source_types": ["irrigation_district", "well"],
            "shared_irrigation_with_prohibited": True,
        },
    },
    "g4_0_rotation_soil": {
        "unanswered": {},
        "annual_only": {"system_type": ["annual"]},
        "perennial_with_other": {
            "system_type": ["perennial"],
            "in_lieu_practices": ["cover_crops", "other"],
        },
        "monitoring_no_testing": {"fertility_monitoring": ["no_testing"]},
        "monitoring_soil_tests": {"fertility_monitoring": ["soil_tests"]},
        # Restricted materials (2026.11.13): the approval follow-up needs BOTH micronutrients chosen
        # AND a non-test method (an AND of `includes` and `includes_any`).
        "micronutrients_visual": {
            "applies_deficiency_materials": True,
            "deficiency_materials": ["micronutrients"],
            "micronutrient_verification": ["visual_observation"],
        },
        "magnesium_only_with_stale_method": {
            "applies_deficiency_materials": True,
            "deficiency_materials": ["magnesium_sulfate"],
            "micronutrient_verification": ["visual_observation"],
        },
        "micronutrients_soil_tested": {
            "applies_deficiency_materials": True,
            "deficiency_materials": ["micronutrients", "magnesium_sulfate"],
            "micronutrient_verification": ["soil_analysis"],
        },
        "calcium_chloride_no": {"applies_calcium_chloride": False, "calcium_chloride_foliar": True},
    },
    "g5_0_pest": {
        "unanswered": {},
        "copper_without_inputs": {
            "applies_pest_weed_disease_inputs": False,
            "applies_copper_materials": True,
            "copper_accumulation_practices": ["other"],
        },
        "copper_other_practice": {
            "applies_pest_weed_disease_inputs": True,
            "applies_copper_materials": True,
            "copper_accumulation_practices": ["other"],
        },
    },
    # Who harvests / who transports became checkbox groups (2026.10.25): the gates moved from `eq` /
    # `one_of` to `includes` / `includes_any`, which the TS twin must evaluate the same way.
    "g6_1_harvest_transport": {
        "unanswered": {},
        "own_crew_only": {"who_harvests": ["own_crew"], "who_transports": ["own_vehicles"]},
        "own_crew_and_custom": {"who_harvests": ["own_crew", "custom_harvester"]},
        "other_parties": {"who_harvests": ["other_harvester"], "who_transports": ["broker", "other_transporter"]},
        "sold_standing": {"who_harvests": ["sold_standing"], "who_transports": ["warehouse_packer"]},
        "wooden_bins_from_packer": {
            "container_types": ["wooden_bins"],
            "receives_nondedicated_wood_bins": True,
            "harvest_containers_stamped_organic": "none",
        },
        "stamped_plastic_bins": {"container_types": ["plastic_bins"], "harvest_containers_stamped_organic": "all"},
        "shared_truck": {"transport_shared_with_noncertified": True, "who_transports": ["commercial_carrier"]},
        "custom_work": {"third_party_activities": ["harvest", "material_application"]},
        "no_custom_work": {"third_party_activities": ["none"]},
        "sop_said_attached": {
            "container_safeguards": ["cleaned_prior"],
            "container_cleaning_records": ["sop_attached"],
        },
    },
    "g6_0_production": {
        "unanswered": {},
        "split": {"split_operation": True},
        "not_split": {"split_operation": False},
        # Treated lumber page E (2026.11.09).
        "lumber_with_policy_other": {"treated_lumber_any": True, "treated_lumber_policy": ["other"]},
        "no_lumber": {"treated_lumber_any": False},
        # Roadside management (2026.11.16): the steps and their "other" hang on the road; a stale
        # step answer must hide when the road answer is No.
        "road_with_other_step": {"borders_public_road": True, "roadside_management_steps": ["no_spray_signs", "other"]},
        "no_road_stale_steps": {"borders_public_road": False, "roadside_management_steps": ["other"]},
        "drift_registry_and_self_managed": {
            "drift_safeguards": ["sensitive_crop_registry", "self_managed_adjacent_precautions"]
        },
        "drift_none": {"drift_safeguards": ["none_no_surrounding_prohibited_use"]},
        # Production equipment page F (2026.11.11): a stale "other" or procedure answer must hide with
        # the gate.
        "equipment_sop_and_other": {
            "uses_production_equipment": True,
            "equipment_cleaning_documentation": ["sop_followed", "other"],
        },
        "no_equipment_stale_children": {
            "uses_production_equipment": False,
            "equipment_cleaning_documentation": ["sop_followed", "other"],
        },
    },
    # Sealed packaging gates on `eq False`, so an unanswered plan must hide the unsealed questions in
    # both languages (None is not False).
    "g6_2_storage": {
        "unanswered": {},
        "all_sealed": {"stored_in_sealed_packaging": True},
        "not_sealed_other": {
            "stored_in_sealed_packaging": False,
            "unsealed_storage_controls": ["areas_with_organic_signage", "other"],
            "storage_location_records": ["other"],
        },
        "shared_storage": {"storage_shared_with_nonorganic": True},
    },
    "g7_0_labeling": {
        "unanswered": {},
        "unlabeled_bulk": {"product_leaves_as": ["unlabeled_bulk_documents"]},
        "stamped_bins_with_lots": {
            "product_leaves_as": ["bulk_bins_marked"],
            "nonretail_organic_identification": ["permanent_stamp"],
            "container_markings_tie_to_lot": True,
        },
        "visible_through_only": {"nonretail_organic_identification": ["visible_through_container"]},
        "markings_not_tied": {"container_markings_tie_to_lot": False},
        "no_nonretail_containers": {"nonretail_container_types": ["none"]},
        "no_identifier": {"container_lot_identifier_types": ["no_identifier"]},
    },
    "g8_0_record_keeping": {
        "unanswered": {},
        "own_lot_system": {"lot_numbering": "own_system"},
        # Retired 2026.11.12: an answer of only this reads as unanswered in both languages.
        "trazo_lots": {"lot_numbering": "trazo_lots"},
        # A retired option alone is not an answer; the TS twin must agree or the wizard would
        # offer "complete" on a module the server refuses.
        "retired_none_only": {"import_export_activity": ["none"]},
        "indirect_export": {"import_export_activity": ["indirect_export"]},
        "no_known_export": {"import_export_activity": ["none_no_known_export"]},
    },
}


_NOT_AN_OPTION = "__not_an_option__"


def _condition_key(cond):
    return (cond.question, cond.op, repr(cond.value))


def chained_gates(modules=None):
    """[(module, page, child, ancestor condition)] for every child that does not repeat a condition of
    the question it is gated on (or of that question's page).

    Visibility is transitive since 2026-11-03, so such a child must hide whenever that ancestor
    condition fails, whatever its own trigger still holds. Each chain becomes a stale-answer golden
    case, so both evaluators are held to it (`certifications/tests/test_chained_gates.py`).
    """
    out = []
    for module in modules or MODULE_REGISTRY:
        where = {q.key: (page, q) for page in module.pages for q in page.questions}
        for page in module.pages:
            for q in page.questions:
                own = {_condition_key(c) for c in q.visible_when} | {_condition_key(c) for c in page.visible_when}
                for cond in q.visible_when:
                    parent_page, parent = where[cond.question]
                    for inherited in tuple(parent.visible_when) + tuple(parent_page.visible_when):
                        if _condition_key(inherited) not in own:
                            out.append((module, page, q, inherited))
    return out


def _satisfying(cond, current):
    """A value for `cond.question` that passes `cond`, merged with what is already chosen."""
    if cond.op == "eq":
        return cond.value
    if cond.op in ("includes", "includes_any"):
        wanted = cond.value if cond.op == "includes" else cond.value[0]
        chosen = list(current) if isinstance(current, list) else []
        return chosen if wanted in chosen else chosen + [wanted]
    if cond.op == "one_of":
        return cond.value[0]
    if cond.op == "truthy":
        return current if current else True
    return current  # ne / not_includes / falsy pass while unanswered


def _failing(cond):
    """An ANSWERED value for `cond.question` that fails `cond`: the stale state, not an empty one."""
    return {
        "eq": (not cond.value) if isinstance(cond.value, bool) else _NOT_AN_OPTION,
        "ne": cond.value,
        "includes": [_NOT_AN_OPTION],
        "includes_any": [_NOT_AN_OPTION],
        "one_of": _NOT_AN_OPTION,
        "not_includes": [cond.value],
        "truthy": False,
        "falsy": True,
    }[cond.op]


def stale_answers(page, child, ancestor):
    """The child's own gates answered so they pass and the ancestor's answered so it fails; None
    when the two read the same question and no such set exists."""
    answers = {}
    for cond in tuple(page.visible_when) + tuple(child.visible_when):
        value = _satisfying(cond, answers.get(cond.question))
        if value is not None:
            answers[cond.question] = value
    if ancestor.question in answers:
        return None
    answers[ancestor.question] = _failing(ancestor)
    return answers


class Command(BaseCommand):
    help = "Export module registry + evaluator golden cases to the frontend fixture."

    def add_arguments(self, parser):
        parser.add_argument("--out", default=str(DEFAULT_OUT), help="Fixture output path")

    def handle(self, *args, **options):
        modules_by_key = {m.key: m for m in MODULE_REGISTRY}
        batteries_by_module = [(key, list(batteries.items())) for key, batteries in GOLDEN_ANSWER_CASES.items()]
        # One stale-answer case per chained gate: both evaluators must hide the child (2026-11-03).
        for module, page, child, ancestor in chained_gates():
            answers = stale_answers(page, child, ancestor)
            if answers is not None:
                batteries_by_module.append(
                    (module.key, [(f"stale_chain:{child.key}:{ancestor.question}:{ancestor.op}", answers)])
                )
        cases = []
        for module_key, batteries in batteries_by_module:
            module = modules_by_key.get(module_key)
            if module is None:
                self.stderr.write(f"skipping unknown module '{module_key}'")
                continue
            for label, answers in batteries:
                visible = [q.key for _p, q in visible_questions(module, answers)]
                cases.append(
                    {
                        "module": module_key,
                        "label": label,
                        "answers": answers,
                        "visible_questions": visible,
                        "missing_required": missing_required(module, answers),
                        "missing_required_na": missing_required(module, answers, not_applicable=True),
                    }
                )

        payload = {
            "content_version": CONTENT_VERSION,
            "registry": serialize_registry(),
            "golden_cases": cases,
        }
        out = Path(options["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(cases)} golden cases -> {out}"))
