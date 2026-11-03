"""A question gated on another question must also carry that question's own gates.

`visible_questions` evaluates each question's `visible_when` against the stored answers alone; it
never asks whether the question it points at is itself visible. So a child gated only on its
parent's answer outlives the parent: a grower who answered `water_quality_tested = yes` and later
said "we do not irrigate" would still be asked how often the water is tested (required, so the
module never completes) and the stale answer would print in the plan. The packet's coverage page
already reads the upstream gate (`packet_answers.hidden_state`); the wizard, completion and the
compiler do not.

Until the evaluator itself becomes transitive (Python and `conditionEval.ts` together, with golden
cases), each child repeats its ancestors' conditions. KNOWN_GAPS freezes the chains that predate
this guard (2026-11-09): a new one fails, and a fixed one must leave the list.
"""

from django.test import SimpleTestCase

from certifications.osp_modules import MODULES_BY_KEY

KNOWN_GAPS = {
    ("g2_0_fraud_prevention", "supplier_certificate_review_frequency_other"),
    ("g3_0_seeds", "buyer_search_documents"),
    ("g3_2_planting_stock", "first_organic_harvest_handling_other"),
    ("g4_0_rotation_soil", "in_lieu_other"),
    ("g4_0_rotation_soil", "monitoring_frequency_other"),
    ("g4_0_rotation_soil", "fertility_testing_frequency_other"),
    ("g4_1_compost_manure", "raw_manure_supplier_statement_upload"),
    ("g4_2_natural_resources", "wildlife_habitat_mitigation_other"),
    ("g5_0_pest", "burn_reason_other"),
    ("g6_0_production", "prohibited_materials_storage_other"),
    ("g6_1_harvest_transport", "container_cleaning_sop_upload"),
    ("g6_1_harvest_transport", "handler_bin_practice"),
    ("g6_1_harvest_transport", "handler_bin_documentation_upload"),
    ("g6_1_harvest_transport", "handler_cert_verification_method_other"),
    ("g6_1_harvest_transport", "handler_cert_verification_frequency_other"),
    ("g6_4_handling", "sanitizer_residual_free_assurance_other"),
    ("g6_4_handling", "sanitizer_residual_testing_protocol"),
    ("g6_4_handling", "wash_water_chlorine_added"),
    ("g6_4_handling", "wash_water_chlorine_final_rinse"),
    ("g6_4_handling", "wash_water_chlorine_final_rinse_other"),
    ("g6_5_sales_soe", "sourced_products_identification_detail"),
    ("g6_5_sales_soe", "sourcing_transport_verification_other"),
    ("g6_5_sales_soe", "sourcing_transport_commingling_other"),
    ("g6_5_sales_soe", "sourced_records_link_detail"),
    ("g8_0_record_keeping", "export_certificate_types_other"),
    ("g8_0_record_keeping", "import_documentation_other"),
    ("g9_0_facility_pest", "preventive_measures_documentation_other"),
}


def _key(cond):
    return (cond.question, cond.op, repr(cond.value))


def chained_gate_gaps():
    """{(module, question): missing ancestor conditions} for every child that outlives its parent."""
    gaps = {}
    for module_key, module in MODULES_BY_KEY.items():
        where = {q.key: (page, q) for page in module.pages for q in page.questions}
        for page in module.pages:
            for q in page.questions:
                own = {_key(c) for c in q.visible_when} | {_key(c) for c in page.visible_when}
                for cond in q.visible_when:
                    if cond.question not in where:
                        continue
                    parent_page, parent = where[cond.question]
                    inherited = {_key(c) for c in parent.visible_when} | {_key(c) for c in parent_page.visible_when}
                    missing = inherited - own
                    if missing:
                        gaps.setdefault((module_key, q.key), set()).update(missing)
    return gaps


class ChainedGateTests(SimpleTestCase):
    def test_no_new_child_outlives_its_parent(self):
        new = {k: sorted(v) for k, v in chained_gate_gaps().items() if k not in KNOWN_GAPS}
        self.assertEqual(new, {}, "add the parent's own visible_when to each of these children")

    def test_a_fixed_chain_leaves_the_known_list(self):
        self.assertEqual(sorted(KNOWN_GAPS - set(chained_gate_gaps())), [])
