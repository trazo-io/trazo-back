"""
The onboarding wizard's goal ids and this service's consumer labels must agree.

⛔ 2026-08-25 — they did not. `AddCompany.jsx` offers six goals; `goal_labels` in
`transparency_response_formatter` carried six DIFFERENT ids. Two of the six a farmer could
tick (`waste_reduction`, `renewable_energy`) had no label at all, and the old
`goal_labels.get(g, g)` fallback published the raw snake_case id to a shopper scanning a QR
code. Two labels in the map were for ids the wizard can no longer produce.

Same shape as [[display-registry-is-the-fifth-gate]]: a display registry nothing compares
against the form that feeds it. The registry lives in Python and the form lives in a React
file, so no import can tie them — this test names the contract instead, and the JS side is
guarded by `addCompanyI18n.test.ts`'s "wire values are NOT translated" case.
"""

from django.test import SimpleTestCase

from history.services.transparency_response_formatter import TransparencyResponseFormatter


def _goal_labels():
    """
    Read the map out of the source, because it is a local inside the formatter method rather
    than a module constant. Parsing beats re-declaring: a copy of the dict in this file would
    assert only that the copy matches itself.
    """
    import inspect
    import re

    source = inspect.getsource(TransparencyResponseFormatter)
    block = source[source.index("goal_labels = {") :]
    block = block[: block.index("}")]
    return dict(re.findall(r'"([a-z_]+)":\s*"([^"]+)"', block))


# The six the wizard offers, in wizard order.
# Source of truth: trazo-app/src/views/Dashboard/Dashboard/Company/AddCompany.jsx
WIZARD_GOAL_IDS = [
    "full_transparency",
    "water_conservation",
    "soil_health",
    "biodiversity",
    "waste_reduction",
    "renewable_energy",
]

# Written by an earlier wizard, still possible in stored rows. A label for each is what keeps
# an old row off the public page as raw snake_case.
LEGACY_GOAL_IDS = ["carbon_reduction", "local_sourcing"]


class SustainabilityGoalLabelTests(SimpleTestCase):
    def test_the_map_was_actually_found(self):
        """Anti-vacuity. An empty parse satisfies every 'is in' assertion below."""
        labels = _goal_labels()

        self.assertGreaterEqual(len(labels), len(WIZARD_GOAL_IDS))

    def test_every_goal_the_wizard_offers_has_a_consumer_label(self):
        labels = _goal_labels()

        missing = [g for g in WIZARD_GOAL_IDS if g not in labels]

        self.assertEqual(missing, [], "these would reach a shopper as raw snake_case")

    def test_legacy_ids_keep_their_labels(self):
        labels = _goal_labels()

        missing = [g for g in LEGACY_GOAL_IDS if g not in labels]

        self.assertEqual(missing, [], "rows written by the old wizard still carry these")

    def test_no_label_is_the_id_itself(self):
        """
        A label equal to its key is the `.get(g, g)` fallback wearing a disguise — it would
        satisfy the presence test above while still publishing snake_case.
        """
        labels = _goal_labels()

        echoes = [k for k, v in labels.items() if v == k]

        self.assertEqual(echoes, [])

    def test_labels_make_no_verified_or_certified_claim(self):
        """
        These are goals a farmer TICKED during onboarding. Nothing audits them, so the
        consumer-facing wording must not imply third-party verification —
        `.claude/rules/compliance.md`, FTC 16 CFR 260.6.
        """
        labels = _goal_labels()

        banned = ("verified", "certified", "guaranteed", "proven", "audited")
        offenders = [f"{k} = {v}" for k, v in labels.items() if any(b in v.lower() for b in banned)]

        self.assertEqual(offenders, [])
