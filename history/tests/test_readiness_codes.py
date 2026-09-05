"""Every readiness item must carry a translatable code, and every code must be reachable.

WHY THIS EXISTS
---------------
🌐 2026-09-02. A Spanish-locale farm dashboard rendered the heading "TODA LA OPERACIÓN" over
the item "2 logged product(s) are not on your materials list" — English prose, on a Spanish
screen, in an app whose own rule is that every user-facing string goes through
`intl.formatMessage` with a key in BOTH locales. The prose came from this service, and a
server that returns prose has effectively opted the client out of translation. Same defect,
same settlement as `users/constants.py` + `authErrors.ts`: a stable code plus the VALUES.

WHAT THIS GUARDS, AND WHY EACH ONE
  1. Every emitted item has a `code` from `READINESS_CODES` and a `params` DICT. A new check
     added without a code renders in English on a Spanish dashboard and nothing notices —
     which is exactly how the original defect shipped.
  2. Every code in `READINESS_CODES` is actually emitted by this module. A registry that only
     grows is a registry the frontend test passes against vacuously: `readinessMessages.ts`
     asserts a message id per code, so a dead code buys a translated string for a row that
     can never render, while the row that DOES render goes unnoticed.
  3. `title`/`detail`/`fix` survive. They are not vestigial — `OperationAuditExportService`
     prints them into a document written for a US certifying agent, and they are the client's
     fallback for a code it has not learned. Deleting them to "finish" the i18n work would
     blank the packet.
  4. A LIST param stays a list. Pre-joining names into "A, B, and 3 more" bakes an English
     conjunction into a value, and the translation cannot come apart again. This is the one
     rule a well-meaning refactor is most likely to undo.
"""

import inspect
import re

from django.test import TestCase

from company.models import Company, Establishment
from history.services import operation_readiness_service as mod
from history.services.operation_readiness_service import (
    ATTESTATION_CLAUSE_CODES,
    READINESS_CODES,
    OperationReadinessService,
)


class ReadinessCodeContractTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Codes Co")
        # farming_method carries the operation into NOP scope, so the organic-only checks run
        # and the blocker/warning branches are actually reachable from evaluate().
        self.est = Establishment.objects.create(name="Coded Ranch", company=self.company, farming_method="organic")

    def _items(self):
        return OperationReadinessService(self.est).evaluate()["checked_items"]

    def test_every_emitted_item_carries_a_registered_code(self):
        items = self._items()
        self.assertTrue(items, "no checks ran — the fixture stopped reaching NOP scope")
        for item in items:
            self.assertIn("code", item, f"item {item.get('key')!r} has no code")
            self.assertIn(
                item["code"],
                READINESS_CODES,
                f"code {item['code']!r} is emitted but not registered in READINESS_CODES",
            )

    def test_every_emitted_item_carries_a_params_dict(self):
        for item in self._items():
            self.assertIsInstance(
                item.get("params"),
                dict,
                f"item {item['code']!r} must carry params as a dict, even when empty",
            )

    def test_every_registered_code_is_emitted_somewhere_in_this_module(self):
        """Anti-vacuity. `readinessMessages.ts` demands a message id per registered code."""
        source = inspect.getsource(mod)
        for code in READINESS_CODES:
            self.assertIn(
                f'"code": "{code}"',
                source,
                f"{code!r} is registered but no check emits it — delete it or emit it",
            )

    def test_no_check_emits_a_code_the_registry_has_never_heard_of(self):
        """The mirror of the test above, and the half a runtime assertion cannot cover.

        `test_every_emitted_item_carries_a_registered_code` only sees the branches this
        fixture actually reaches — a bare establishment fires `records.none` and little else,
        so an unregistered code buried in the handler-certificate branch would sail past it.
        Counting the literals in the source closes that: 22 registered must mean 22 emitted,
        in both directions.
        """
        source = inspect.getsource(mod)
        emitted = set(re.findall(r'"code": "([^"]+)"', source))
        self.assertEqual(
            emitted - set(READINESS_CODES),
            set(),
            "a check emits a code that is not in READINESS_CODES, so no message id covers it",
        )
        self.assertEqual(len(emitted), len(READINESS_CODES))

    def test_every_attestation_clause_code_is_appended_somewhere(self):
        source = inspect.getsource(mod)
        for clause in ATTESTATION_CLAUSE_CODES:
            self.assertIn(f'"{clause}",', source, f"clause {clause!r} is registered but never appended")

    def test_the_english_sentence_survives_beside_the_code(self):
        """The packet prints these. A code is an ADDITION, never a replacement."""
        for item in self._items():
            for field in ("title", "detail", "fix"):
                self.assertIn(field, item, f"{item['code']!r} dropped {field!r} — the packet reads it")

    def test_a_blocker_states_its_case_in_english_too(self):
        """`records.none` fires on this bare fixture; its English title is the fallback."""
        blockers = OperationReadinessService(self.est).evaluate()["blockers"]
        codes = {b["code"] for b in blockers}
        self.assertIn("records.none", codes)
        for blocker in blockers:
            self.assertTrue(blocker["title"].strip(), f"{blocker['code']!r} has an empty English title")

    # -- the rule most likely to be undone by a refactor -------------------

    def test_list_params_are_lists_not_pre_joined_english(self):
        """ "A, B, and 3 more" cannot be re-separated by the client, so es-419 cannot say "y 3 más"."""
        source = inspect.getsource(mod)
        # The params blocks name these; each must be built from a comprehension/slice, never
        # from the ", ".join(...) that builds the English `detail` alongside it.
        for param_name in ('"products"', '"parcels"', '"stale"', '"undated"'):
            index = source.find(f"{param_name}:")
            self.assertNotEqual(index, -1, f"{param_name} param disappeared")
            line = source[index : source.find("\n", index)]
            self.assertNotIn(
                '", ".join',
                line,
                f"{param_name} was pre-joined into English — send the list and the overflow count",
            )
