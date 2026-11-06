"""
The backend strip list and its frontend mirror must not drift.

WHY (2026-08-01): `PublicHistorySerializer._CERTIFIER_ONLY_EVENT_FIELDS` decides what an
anonymous shopper receives. `trazo-app/src/utils/consumerDisplay.ts` re-declares the same set
because one surface builds a consumer card from data that never went through the public API —
`EventPreviewModal`, the producer's "How consumers will see this event" preview, which renders
raw wizard form data.

The two lists carry a comment telling the next person to keep them in step. That comment did
not work: `verification_status` was added to the backend and not the mirror within the hour,
which would have left growers seeing a self-attested "Verified" in the preview labelled as what
shoppers get, right after it was removed from what shoppers actually get. A comment is not an
invariant; this is.

Direction is one-way on purpose. The frontend list is a SUPERSET: it also covers supplier-chain
and form-only keys (`volume_applied`) that the backend strips through other paths or never
serialises. Every backend entry must appear in the frontend; the reverse is not required.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from history.serializers import PublicHistorySerializer
from history.services.claim_authority import _CONSUMER_WITHHELD_PRODUCTION_SUBTYPES

MIRROR = Path(__file__).resolve().parents[3] / "trazo-app" / "src" / "utils" / "consumerDisplay.ts"


class CertifierOnlyFieldParityTests(SimpleTestCase):
    def test_every_backend_stripped_field_is_in_the_frontend_mirror(self):
        if not MIRROR.exists():
            self.skipTest(f"frontend checkout not present at {MIRROR}")

        source = MIRROR.read_text(encoding="utf-8")
        match = re.search(
            r"export const CERTIFIER_ONLY_EVENT_FIELDS: readonly string\[\] = \[(.*?)\];",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "could not find CERTIFIER_ONLY_EVENT_FIELDS in consumerDisplay.ts — if it was "
            "renamed or moved, update this test rather than deleting it.",
        )

        # Mixed case on purpose: `rate_L_ha` is a real key, and a lowercase-only pattern would
        # report it missing from a mirror that lists it.
        mirrored = set(re.findall(r"'([A-Za-z0-9_]+)'", match.group(1)))
        self.assertGreater(len(mirrored), 10, "parsed suspiciously few entries — check the regex")

        missing = sorted(set(PublicHistorySerializer._CERTIFIER_ONLY_EVENT_FIELDS) - mirrored)
        self.assertEqual(
            missing,
            [],
            "These fields are stripped from the anonymous consumer payload but NOT from the "
            "producer's consumer-preview: "
            f"{missing}. Add them to CERTIFIER_ONLY_EVENT_FIELDS in "
            "trazo-app/src/utils/consumerDisplay.ts.",
        )


class WithheldSubtypeParityTests(SimpleTestCase):
    """The EVENT-level withhold list has the same drift problem as the field list.

    `_CONSUMER_WITHHELD_PRODUCTION_SUBTYPES` (claim_authority.py) drops whole events from
    the anonymous payload, but the OWNER still receives them on ProfileProduction — so the
    frontend mirror `CONSUMER_WITHHELD_PRODUCTION_SUBTYPES` is what lets the producer
    preview label those cards "certifier-only, never on your buyer page" instead of
    presenting a withheld record as a consumer card (2026-08-25, found when a grower
    screenshotted a Seed Search "consumer card" that no shopper can ever see).
    """

    def test_every_withheld_subtype_is_in_the_frontend_mirror(self):
        if not MIRROR.exists():
            self.skipTest(f"frontend checkout not present at {MIRROR}")

        source = MIRROR.read_text(encoding="utf-8")
        match = re.search(
            r"export const CONSUMER_WITHHELD_PRODUCTION_SUBTYPES[^=]*=\s*\{(.*?)\};",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "could not find CONSUMER_WITHHELD_PRODUCTION_SUBTYPES in consumerDisplay.ts — "
            "if it was renamed or moved, update this test rather than deleting it.",
        )

        mirrored = set(re.findall(r"^\s*([A-Z]{2}):", match.group(1), re.MULTILINE))
        self.assertGreaterEqual(len(mirrored), 2, "parsed suspiciously few entries — check the regex")

        backend = set(_CONSUMER_WITHHELD_PRODUCTION_SUBTYPES)
        self.assertEqual(
            sorted(backend - mirrored),
            [],
            "These production subtypes are withheld from the anonymous payload but the "
            "producer preview does not know it — the farmer would see them dressed as "
            "consumer cards. Add them to CONSUMER_WITHHELD_PRODUCTION_SUBTYPES in "
            "trazo-app/src/utils/consumerDisplay.ts.",
        )
        self.assertEqual(
            sorted(mirrored - backend),
            [],
            "The frontend claims these subtypes are withheld but the backend publishes "
            "them — the farmer would be told a PUBLISHED record is private. Unlike the "
            "field list, this mirror must match exactly in both directions.",
        )
