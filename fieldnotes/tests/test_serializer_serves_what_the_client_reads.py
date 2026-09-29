"""Every field the inbox branches on is actually served.

WHY THIS EXISTS. `audio_deleted_at` was added to the model, to the frontend's `FieldNote` interface,
and to the component that branches on it, and NOT to the serializer. So the client read `undefined`
forever: the audio player rendered for a note whose recording had been deleted, and pressing it
answered 410 and failed silently.

⛔ **A COMPONENT TEST CANNOT CATCH THIS**, which is the whole reason for a parity guard rather than
another render assertion. The fixture in `FieldNotesInbox.test.tsx` supplies `audio_deleted_at`
itself, so the component behaved correctly on data the API never sends. The same blindness applies to
every field here: the test data is written by the person who forgot the serializer.

It reads the FRONTEND's own interface rather than a list maintained here, because a hand-kept list is
the thing that drifts. The sibling lookup is the project's usual relative path, which is why a
worktree must sit beside a matching `trazo-app` (see CLAUDE.md on worktree layout).

⛔ LOCAL ONLY. Do NOT name this module in `.github/workflows/ci.yml`. That job checks out one repo,
so the sibling is absent and this fails on every run, which is exactly what happened when it was
added there. The workflow already spells the rule out for `test_season_plan_not_records`: a
cross-repo guard fails rather than skips when the sibling is missing, deliberately, because a guard
that no-ops in half the checkouts is decorative, and the consequence is that it cannot live in that
allowlist.

The CI-visible half of this check runs from the other side, in
`trazo-app/src/store/api/__tests__/fieldNoteContractParity.test.ts`. The frontend job DOES check out
`trazo-back` as a sibling, so the same parity is enforced there on every run, in the direction the
environment allows.
"""

import re
from pathlib import Path

from django.test import TestCase

from fieldnotes.serializers import FieldNoteSerializer

APP = Path(__file__).resolve().parents[3] / "trazo-app"
API = APP / "src" / "store" / "api" / "fieldNoteApi.ts"

# Fields the client declares but the server is not expected to send, each with the reason. Anything
# else missing is the bug this file is about.
CLIENT_ONLY = {
    # Served under `words`, which resolves to the transcript for a voice note. The client keeps the
    # name for documentation; no surface reads it directly.
    "transcript",
    "transcript_language",
}


def declared_client_fields():
    """The property names on the frontend's `FieldNote` interface."""
    source = API.read_text(encoding="utf-8")
    start = source.index("export interface FieldNote {")
    body = source[start : source.index("\n}", start)]
    # `name: type;` or `name?: type;` at the start of a line, skipping comments.
    return {
        match.group(1)
        for line in body.split("\n")
        if not line.strip().startswith(("*", "/*", "//"))
        for match in [re.match(r"\s{2}([A-Za-z_][A-Za-z0-9_]*)\??:", line)]
        if match
    }


class SerializerParityTests(TestCase):
    def test_the_frontend_interface_exists_where_this_test_expects_it(self):
        """A negative assertion has to prove it read something.

        Without this, a moved or renamed file would make every assertion below pass over an empty set,
        and the guard would report success while checking nothing.
        """
        self.assertTrue(API.exists(), f"expected the frontend api slice at {API}")
        fields = declared_client_fields()
        self.assertGreater(len(fields), 5, f"parsed too few fields from {API}, the parser is broken")
        # Anchors: if these stop being found the parse has silently changed shape.
        self.assertIn("public_id", fields)
        self.assertIn("status", fields)

    def test_every_field_the_client_declares_is_served(self):
        served = set(FieldNoteSerializer().fields.keys())
        declared = declared_client_fields()

        missing = declared - served - CLIENT_ONLY
        self.assertEqual(
            missing,
            set(),
            "the client reads these and the serializer does not send them, so they are undefined at "
            f"runtime and no component test would notice: {sorted(missing)}",
        )

    def test_the_fields_the_player_depends_on_are_served(self):
        """Named explicitly, because these three decide whether a recording can be played at all and
        a regression in any of them fails silently in the browser rather than loudly here."""
        served = set(FieldNoteSerializer().fields.keys())
        for field in ("kind", "status", "audio_deleted_at"):
            self.assertIn(field, served, f"the inbox branches on `{field}` and it is not served")
