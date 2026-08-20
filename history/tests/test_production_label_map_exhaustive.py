"""Every production subtype needs a human label in the packet.

`PRODUCTION_TYPE_LABELS` is hand-maintained, and both lookups use
`.get(ev.type, _val(ev.type))` — so a subtype absent from the map does not fail loudly, it
prints its RAW CODE. An inspector reading the audit PDF sees "TP" where the record should say
"Transport", on the one page whose whole job is to be legible to someone outside the company.

This is the same shape as the orphaned-feature class already recorded for this codebase: a
definition exists, nothing enforces that its consumers know about it. Reading the vocabulary
from the model means adding a subtype fails here until someone names it.
"""

from django.test import TestCase

from history.models import ProductionEvent
from history.services.audit_export_service import PRODUCTION_TYPE_LABELS


class ProductionLabelMapTests(TestCase):
    def test_every_subtype_has_a_label(self):
        declared = {code for code, _ in ProductionEvent.PRODUCTION_EVENTS}
        missing = sorted(declared - set(PRODUCTION_TYPE_LABELS))
        self.assertEqual(
            missing,
            [],
            f"these production subtypes would print their raw code in the certifier packet: "
            f"{missing}. Add each to PRODUCTION_TYPE_LABELS in audit_export_service.py.",
        )

    def test_the_map_has_no_labels_for_subtypes_that_do_not_exist(self):
        """The mirror. A stale entry is harmless at runtime but means the two have drifted,
        and drift in the harmless direction is how the harmful direction goes unnoticed."""
        declared = {code for code, _ in ProductionEvent.PRODUCTION_EVENTS}
        stale = sorted(set(PRODUCTION_TYPE_LABELS) - declared)
        self.assertEqual(stale, [], f"labels for subtypes the model no longer offers: {stale}")

    def test_it_is_reading_a_real_vocabulary(self):
        """Non-vacuity: an empty `declared` would make both tests above pass silently."""
        self.assertGreaterEqual(len({c for c, _ in ProductionEvent.PRODUCTION_EVENTS}), 13)
