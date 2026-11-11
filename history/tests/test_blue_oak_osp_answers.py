"""Blue Oak's plan answers must still answer the questionnaire, and must name nobody real.

WHY THIS EXISTS
---------------
`seed_showcase_walnut_farm` builds the farm on the landing page. Until 2026-11-11 it stamped
`completed_at` on every Organic System Plan module over an EMPTY answers dict; the answers the
screenshots showed lived only in database copies. When the OSP page started counting required
answers, the showcase farm read "8 of 20 farm-wide modules have every answer" on a marketing
image. The answers now ship as `_blue_oak_osp_answers.json`, and the seeder refuses to run if a
module is out of step with its definition.

That refusal happens at seed time, which is minutes before a screenshot is needed. This test
moves it to CI: a content change that adds a required question, retires an option or renames a
question fails here, next to the change that caused it.

The copies those answers were rescued from also named a real accredited certifier four times, a
real nursery and a real water district acting on a farm that does not exist. A demo packet gets
forwarded, so the second test keeps them out.

No database: the loader compares the fixture against the module registry, which is code.
"""

import json
from pathlib import Path

from django.apps import apps
from django.test import SimpleTestCase

from certifications.osp_modules import MODULE_REGISTRY
from history.management.commands.seed_showcase_walnut_farm import _load_osp_answers, _module_entry

FIXTURE = Path(apps.get_app_config("history").path) / "management" / "commands" / "_blue_oak_osp_answers.json"

# Real organisations a fictional farm's records must not credit with anything. Not exhaustive by
# nature; these are the ones that were actually in the answers before they were rewritten, plus
# the certifiers on the outreach ladder.
REAL_NAMES = (
    "CCOF",
    "Oregon Tilth",
    "OTCO",
    "WSDA",
    "Quality Certification Services",
    "NRCS",
    "EQIP",
    "Sierra Gold",
    "Flood Control",
    "Putah Creek",
    "Cache Creek",
)


class BlueOakOspAnswersTests(SimpleTestCase):
    def test_every_module_is_answered_against_the_current_questionnaire(self):
        # The seeder's own loader: raises CommandError naming each module.question out of step.
        fixture = _load_osp_answers()
        self.assertEqual(
            {module.key for module in MODULE_REGISTRY} - set(fixture),
            set(),
            "every registered module needs an entry, even if it is not applicable",
        )

    def test_the_answers_name_no_real_organisation(self):
        text = FIXTURE.read_text(encoding="utf-8")
        found = [name for name in REAL_NAMES if name.lower() in text.lower()]
        self.assertEqual(found, [], f"{FIXTURE.name} names a real organisation: {found}")

    def test_entries_have_the_shape_the_module_save_path_writes(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        user = type("User", (), {"id": 7})()

        answered = _module_entry("g8_0_record_keeping", fixture, "2026-04-15T00:00:00+00:00", user)
        self.assertEqual(answered["status"], "completed")
        self.assertFalse(answered["not_applicable"])
        self.assertIsNone(answered["na_attestation"])
        self.assertEqual(
            answered["answers"]["lot_numbering"],
            {"at": "2026-04-15T00:00:00+00:00", "value": "own_system"},
        )

        not_applicable = _module_entry("g6_4_handling", fixture, "2026-04-15T00:00:00+00:00", user)
        self.assertEqual(not_applicable["status"], "not_applicable")
        self.assertEqual(not_applicable["answers"], {})
        self.assertEqual(not_applicable["na_attestation"], {"at": "2026-04-15T00:00:00+00:00", "by": 7})
