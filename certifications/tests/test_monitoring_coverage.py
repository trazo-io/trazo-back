"""Monitoring: what CCOF, OTCO and WSDA ask about how and how often an operation watches (2026.11.03).

WHY THIS EXISTS
---------------
* The fertility monitoring list had no soil observation, yield comparison or crop quality option, and
  one frequency answered both how often the farm observes and how often it sends samples (CCOF G4.0
  B1/B1a/B2a, WSDA D1/D1a). "No laboratory testing" stays exclusive: a farm that walks its blocks and
  sends no samples ticks the observation methods, and the lab frequency never opens.
* Each frequency carries an "other" with a text to describe it, so the answer never prints as a bare
  "Other" (CCOF B1a/B2a, OTCO 4.6-2, WSDA E10).
* One monitoring frequency answered three questions WSDA asks apart, for weeds (F2), pests (G2) and
  diseases (H2), and no question said which METHOD does the monitoring (F1, G1, H1; OTCO C5 5.3-1).
* Biodiversity monitoring was one choice where CCOF G4.2 B1 and OTCO C6 8 ask all that apply.
"""

from django.test import SimpleTestCase, TestCase

from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions


def _envelope(value):
    return {"at": "2026-08-21T11:28:46+00:00", "value": value}


def _visible(module_key, **answers):
    return {
        q.key
        for _page, q in visible_questions(MODULES_BY_KEY[module_key], {k: _envelope(v) for k, v in answers.items()})
    }


def _question(module_key, key):
    return next(q for page in MODULES_BY_KEY[module_key].pages for q in page.questions if q.key == key)


class FertilityMonitoringTests(SimpleTestCase):
    def test_observation_without_lab_testing_keeps_its_frequency(self):
        keys = _visible("g4_0_rotation_soil", fertility_monitoring=["crop_observation", "soil_observation"])
        self.assertIn("monitoring_frequency", keys)
        self.assertNotIn("fertility_testing_frequency", keys)

    def test_no_testing_asks_no_frequency(self):
        # Required and with no "not applicable" option: shown here it would force a cadence for
        # monitoring the grower just said is not done.
        keys = _visible("g4_0_rotation_soil", fertility_monitoring=["no_testing"])
        self.assertNotIn("monitoring_frequency", keys)
        self.assertNotIn("fertility_testing_frequency", keys)

    def test_no_testing_cannot_stand_beside_a_lab_test(self):
        from certifications.osp_modules.conditions import exclusive_conflicts

        answers = {"fertility_monitoring": _envelope(["no_testing", "soil_tests"])}
        self.assertEqual(
            exclusive_conflicts(MODULES_BY_KEY["g4_0_rotation_soil"], answers),
            {"fertility_monitoring": "no_testing"},
        )

    def test_lab_testing_has_its_own_frequency(self):
        keys = _visible("g4_0_rotation_soil", fertility_monitoring=["soil_tests"])
        self.assertIn("fertility_testing_frequency", keys)

    def test_lab_frequency_takes_every_cadence_the_forms_list(self):
        options = {o.value for o in _question("g4_0_rotation_soil", "fertility_testing_frequency").options}
        self.assertTrue({"daily", "weekly", "monthly", "annually", "as_needed", "per_crop", "other"} <= options)

    def test_each_frequency_other_opens_its_description(self):
        self.assertIn(
            "monitoring_frequency_other",
            _visible("g4_0_rotation_soil", fertility_monitoring=["crop_observation"], monitoring_frequency="other"),
        )
        self.assertIn(
            "fertility_testing_frequency_other",
            _visible("g4_0_rotation_soil", fertility_monitoring=["soil_tests"], fertility_testing_frequency="other"),
        )
        self.assertNotIn(
            "fertility_testing_frequency_other",
            _visible("g4_0_rotation_soil", fertility_monitoring=["soil_tests"], fertility_testing_frequency="annually"),
        )


class PestMonitoringTests(SimpleTestCase):
    def test_each_monitored_class_gets_its_own_frequency(self):
        keys = _visible("g5_0_pest", monitoring_scope=["weed_pressure", "disease_pressure"])
        self.assertIn("weed_monitoring_frequency", keys)
        self.assertIn("disease_monitoring_frequency", keys)
        self.assertNotIn("pest_monitoring_frequency", keys)

    def test_the_method_is_asked_beside_the_scope(self):
        options = {o.value for o in _question("g5_0_pest", "monitoring_methods").options}
        self.assertTrue({"scouting", "traps_lures", "modeling", "crop_yield_comparison"} <= options)

    def test_material_triggers_show_only_when_materials_are_used(self):
        self.assertIn("input_use_triggers", _visible("g5_0_pest", applies_pest_weed_disease_inputs=True))
        self.assertNotIn("input_use_triggers", _visible("g5_0_pest", applies_pest_weed_disease_inputs=False))


class BiodiversityMonitoringTests(SimpleTestCase):
    def test_biodiversity_monitoring_is_all_that_apply(self):
        self.assertEqual(_question("g4_2_natural_resources", "monitoring_method").kind, "checkbox_group")

    def test_the_other_text_follows_an_other_tick(self):
        keys = _visible("g4_2_natural_resources", monitoring_method=["photo_points", "other"])
        self.assertIn("monitoring_method_other", keys)

    def test_irrigation_efficiency_other_is_described(self):
        keys = _visible("g4_2_natural_resources", irrigation_efficiency_monitoring=["other"])
        self.assertIn("irrigation_efficiency_monitoring_other", keys)

    def test_invasive_other_prints_beside_its_checklist(self):
        # The parent prints under Practices & Procedures; its description must not land in the
        # module's default Monitoring Plan section, detached from what it describes.
        parent = _question("g4_2_natural_resources", "invasive_species_practices")
        other = _question("g4_2_natural_resources", "invasive_species_practices_other")
        self.assertEqual(other.compiles_to.section_key, parent.compiles_to.section_key)


class BiodiversityMigrationTests(TestCase):
    """Migration 0061 wraps the stored single answer; nothing is remapped, and the reverse unwraps one."""

    def setUp(self):
        from company.models import Company, Establishment

        company = Company.objects.create(name="Monitor Co")
        self.est = Establishment.objects.create(name="Monitor Farm", company=company, state="OR")

    def _plan(self, version, value):
        from certifications.models import OrganicSystemPlan

        osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=version, status="superseded")
        osp.module_responses = {
            "modules": {"g4_2_natural_resources": {"answers": {"monitoring_method": _envelope(value)}}}
        }
        osp.save(update_fields=["module_responses"])
        return osp

    def _value(self, osp):
        osp.refresh_from_db()
        return osp.module_responses["modules"]["g4_2_natural_resources"]["answers"]["monitoring_method"]["value"]

    def test_wrap_and_reverse(self):
        import importlib

        from django.apps import apps as django_apps

        migration = importlib.import_module("certifications.migrations.0061_biodiversity_monitoring_multichoice")
        one, several = self._plan(1, "photo_points"), self._plan(2, ["photo_points", "surveys"])
        migration.wrap_scalars(django_apps, None)
        self.assertEqual(self._value(one), ["photo_points"])
        self.assertEqual(self._value(several), ["photo_points", "surveys"])
        migration.unwrap_single(django_apps, None)
        self.assertEqual(self._value(one), "photo_points")
        self.assertEqual(self._value(several), ["photo_points", "surveys"])
