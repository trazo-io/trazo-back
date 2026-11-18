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
        # Page B's OR gate (2026.11.25): non-organic seed OR non-organic planting stock opens it; the seed-only
        # questions on it keep their seed gate.
        "or_gate_stock_only": {"seeds_used": ["organic_untreated"], "planting_stock_used": ["non_organic"]},
        "or_gate_seed_only": {"seeds_used": ["non_organic_untreated"], "planting_stock_used": ["organic"]},
        "or_gate_neither": {"seeds_used": ["organic_untreated"], "planting_stock_used": ["organic"]},
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
        # 2026.12.16: grafting practices open on either Yes (`one_of`); other planting stock (OTCO C3 3.1-4)
        # opens on a status and stays closed on "established perennials only".
        "grafts_not_listed_yet": {"planting_stock_used": ["organic"], "grafts_stock": "yes_not_listed"},
        "established_only": {"planting_stock_used": ["established_in_place"], "grafts_stock": "no"},
    },
    # 2026.12.16: the applied-by follow-up opens on either treated answer (WSDA AGR 2121 C3c), and the
    # bought-nonorganic question (C4) only for stock sold as organic.
    "g3_2_planting_stock": {
        "unanswered": {},
        "treated_not_listed": {"stock_organic_status": "mixed", "stock_treatments": "treated_not_listed"},
        "treated_unknown": {"stock_organic_status": "all_nonorganic", "stock_treatments": "unknown"},
        "sells_stock": {"stock_sold_as_organic": "sold_organic_stock"},
        "sells_crop_only": {"stock_sold_as_organic": "not_sold"},
    },
    # Irrigation sources and shared lines (2026.11.09): `not_includes` is TRUE while unanswered, so the
    # shared-lines question shows until "we do not irrigate" is ticked; the TS twin must agree.
    # Compost temperature is asked of the thermophilic methods only (2026.11.24, OTCO C4 4.4-3).
    "g4_1_compost_manure": {
        "unanswered": {},
        "windrow": {"materials_applied": ["on_farm_compost"], "compost_method": "windrow"},
        "vermicompost": {"materials_applied": ["vermicompost"], "compost_method": "vermicompost"},
        "method_unanswered": {"materials_applied": ["on_farm_compost"]},
    },
    # The certificate of the agency the plan is filed with opens on a yes, under ever certified (2026.12.11).
    "certification_contract": {
        "unanswered": {},
        "never_certified": {"history_ever_certified": False, "history_certified_by_this_agency": True},
        "renewal": {"history_ever_certified": True, "history_certified_by_this_agency": True},
        "not_by_this_agency": {"history_ever_certified": True, "history_certified_by_this_agency": False},
    },
    # Conservation in enclosed structures: the other box opens on other (2026.12.12, CCOF G4.2 A8).
    "g3_1_container_greenhouse": {
        "unanswered": {},
        "greenhouse_other": {
            "structure_production_types": ["annual_seedlings"],
            "enclosed_structure_conservation": ["other"],
        },
    },
    # The residue questions open on product testing (2026.11.24, WSDA AGR 2121 P 4a/4b).
    "g2_0_fraud_prevention": {
        "unanswered": {},
        "product_testing": {"fraud_mitigation_practices": ["product_testing"]},
        "no_testing": {"fraud_mitigation_practices": ["verify_certificates"]},
        # The separate plan, the SOPs, the audits, the supply chain and the control points (2026.12.10).
        "separate_plan_sops_audits": {
            "fraud_plan_kept_separately": True,
            "written_sops_kept": True,
            "internal_audits_conducted": True,
            "osp_implementation_monitoring": ["record_review", "employee_evaluations"],
        },
        "no_plan_no_sops": {"fraud_plan_kept_separately": False, "written_sops_kept": False},
        "supply_chain_map": {"supply_chain_shown_as": "map", "critical_control_points": ["transport", "other"]},
        "supply_chain_described": {"supply_chain_shown_as": "described", "critical_control_points": ["sales"]},
    },
    "g4_2_natural_resources": {
        "unanswered": {},
        # The waterway list opens on streams or channels by the land; the agency's other box on other (2026.12.12).
        "streams_adjacent": {"streams_or_channels_adjacent": True, "waterway_practices": ["fish_screens", "other"]},
        "no_streams_stale": {"streams_or_channels_adjacent": False, "waterway_practices": ["fish_screens"]},
        # Irrigation (2026.12.13): a well opens the non-district additives question; a district's yes opens its plan
        # elements; materials not all approved open the prevention practices; lab testing opens what is tested.
        "well_with_materials": {
            "irrigation_source_types": ["well"],
            "materials_via_irrigation": True,
            "irrigation_materials_all_approved": False,
            "water_verification_method": ["lab_testing"],
        },
        "district_adds_prohibited": {
            "irrigation_source_types": ["irrigation_district"],
            "water_from_irrigation_district": True,
            "irrigation_district_additives": "yes",
        },
        "not_irrigated_stale": {"irrigation_source_types": ["not_irrigated"], "materials_via_irrigation": True},
        "other_agency_and_measures": {
            "conservation_plan_agency": ["nrcs", "other"],
            "other_conservation_measures": True,
        },
        "not_irrigated": {"irrigation_source_types": ["not_irrigated"]},
        "district_shared": {
            "irrigation_source_types": ["irrigation_district", "well"],
            "shared_irrigation_with_prohibited": True,
        },
    },
    "g4_0_rotation_soil": {
        "unanswered": {},
        # 2026.12.19: container crops are asked the in-lieu description; the retired merged erosion option alone is
        # no answer, beside a current one it is.
        "container_only": {"system_type": ["container"]},
        "erosion_retired_only": {"erosion_practices": ["contour"]},
        "erosion_retired_and_terraces": {"erosion_practices": ["contour", "terraces"]},
        "erosion_other": {"erosion_practices": ["other"]},
        "annual_with_fertilizer": {"system_type": ["annual"], "applies_fertilizers": True},
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
        # 2026.12.19: the burn target opens for disease or seed only; the plastic questions for plastic only.
        "burn_for_disease": {"burns_crop_residue": True, "burn_reason": ["disease_suppression"]},
        "burn_other_only": {"burns_crop_residue": True, "burn_reason": ["other"]},
        "plastic_pvc": {"plastic_mulch_used": True, "plastic_mulch_material": "pvc"},
        "pest_taxa_other": {"pest_taxa_managed": ["insects", "other"]},
        # 2026.11.22: a retired question shows only while it holds an answer; both evaluators must agree.
        "retired_lists_answered": {
            "prevention_practices": ["crop_rotation", "other"],
            "weed_management_practices": ["mowing"],
        },
        "typed_lists_with_other": {"practices_weeds": ["mowing_grazing", "other"], "practices_vertebrates": ["none"]},
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
    "g6_4_handling": {
        # 2026.11.21: the input types and recording hang on applying inputs; their "other" also on "other".
        "inputs_other": {
            "handling_activities": ["packing"],
            "applies_post_harvest_inputs": True,
            "post_harvest_input_types": ["waxes_coatings", "other"],
        },
        "no_inputs_stale_types": {
            "handling_activities": ["packing"],
            "applies_post_harvest_inputs": False,
            "post_harvest_input_types": ["other"],
        },
    },
    "g6_0_production": {
        "unanswered": {},
        "split": {"split_operation": True},
        "not_split": {"split_operation": False},
        # Non-organic product source (2026.11.17): its "other" text hangs on split AND the "other" box.
        "split_source_other": {"split_operation": True, "nonorganic_product_source": ["buffer_zone_crop", "other"]},
        "not_split_stale_source": {"split_operation": False, "nonorganic_product_source": ["other"]},
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
        # Split records (2026.12.15): split but not parallel asks how records tell crops apart; parallel does not.
        # Split with parallel unanswered is the existing `split` case.
        "split_not_parallel": {"split_operation": True, "parallel_production": False},
        "split_parallel": {"split_operation": True, "parallel_production": True},
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
        # 2026.11.20: the own-facility table shows for on-farm storage only.
        "on_farm_cold": {"storage_locations": ["on_farm_cold"]},
        "off_farm_only": {"storage_locations": ["certified_handler"]},
    },
    "g7_0_labeling": {
        "unanswered": {},
        "unlabeled_bulk": {"product_leaves_as": ["unlabeled_bulk_documents"]},
        # 2026.11.19: statement placement hangs on consumer packaging AND the certifier statement.
        "retail_with_statement": {"product_leaves_as": ["consumer_packaging"], "label_states_certifier": True},
        "retail_no_statement_stale_placement": {
            "product_leaves_as": ["consumer_packaging"],
            "label_states_certifier": False,
            "certifier_statement_below_operation": True,
        },
        "bulk_only_stale_review": {
            "product_leaves_as": ["bulk_bins_marked"],
            "retail_labels_certifier_review": "all_approved",
        },
        "plu_stickers": {"unpackaged_retail_labels": True},
        # 2026.11.18: record elements hang on using nonretail containers.
        "record_elements": {
            "nonretail_container_types": ["harvest_crates_bins"],
            "container_record_elements": ["organic_status"],
        },
        "no_containers_stale_elements": {
            "nonretail_container_types": ["none"],
            "container_record_elements": ["organic_status"],
        },
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
    "g6_5_sales_soe": {
        # Direct marketing (2026.12.18): venues open their lists; signage only when non-organic is sold too.
        "no_direct_sales": {"direct_sales": "no"},
        "markets_and_stand": {
            "direct_sales": "yes",
            "direct_sales_venues": ["farmers_market", "farm_stand"],
            "direct_sales_nonorganic": "also_nonorganic",
            "direct_sales_differentiation": ["separate_areas", "other"],
        },
        "only_organic": {"direct_sales": "yes", "direct_sales_nonorganic": "only_organic"},
        "stale_venues_after_no": {"direct_sales": "no", "direct_sales_venues": ["online"]},
    },
    "g8_0_record_keeping": {
        "unanswered": {},
        "own_lot_system": {"lot_numbering": "own_system"},
        # 2026.11.18: the key hangs on own numbering; a stale key must hide when the answer moves to none.
        "own_lot_system_with_key": {"lot_numbering": "own_system", "lot_code_key": "26 = harvest year"},
        "no_lots_stale_key": {"lot_numbering": "none", "lot_code_key": "26 = harvest year"},
        "trace_other": {"trace_mechanisms": ["field_names", "other"]},
        "trace_only_lots_stale_other": {"trace_mechanisms": ["lot_numbers_only"], "trace_mechanisms_other": "x"},
        # Retired 2026.11.12: an answer of only this reads as unanswered in both languages.
        "trazo_lots": {"lot_numbering": "trazo_lots"},
        # A retired option alone is not an answer; the TS twin must agree or the wizard would
        # offer "complete" on a module the server refuses.
        "retired_none_only": {"import_export_activity": ["none"]},
        "indirect_export": {"import_export_activity": ["indirect_export"]},
        "no_known_export": {"import_export_activity": ["none_no_known_export"]},
        # Sells as organic, records short of organic status; other ways records are kept (2026.12.15).
        "sells_records_short": {"sells_as_organic": True, "records_identify_organic_status": False},
        "records_other": {"records_maintained_as": ["phone_app", "other"]},
        # International trade (2026.12.17): seed imported for the farm opens the import questions; Canada is
        # asked of every answer; sodium nitrate only where crops may reach Canada.
        "imports_seed_only": {"import_export_activity": ["import_seed"], "import_seed_countries": ["other"]},
        "imports_product_and_seed": {"import_export_activity": ["import", "import_seed"]},
        "exports_canada_nitrate": {
            "import_export_activity": ["export"],
            "canada_export_possible": True,
            "sodium_nitrate_used": True,
            "export_shipment_documents": ["other"],
            "equivalency_compliance_method": ["other"],
        },
        "no_canada_stale_nitrate": {
            "import_export_activity": ["none_no_known_export"],
            "canada_export_possible": False,
            "sodium_nitrate_used": True,
        },
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
