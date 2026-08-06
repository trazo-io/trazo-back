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

        mirrored = set(re.findall(r"'([a-z0-9_]+)'", match.group(1)))
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
