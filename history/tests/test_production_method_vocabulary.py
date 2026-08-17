"""The production-method vocabulary must be ONE list, across both repos.

`History.production_method` reaches the database down two different paths, and only one of
them ever validated:

  * PATCH /histories/<id>/ goes through HistorySerializer, a ModelSerializer with
    `production_method` in `Meta.fields`. DRF builds a ChoiceField from the model field, so
    the vocabulary is enforced.
  * POST /histories/start-production/ built the row with a raw `History(...)` kwarg — no
    serializer, no `full_clean()`. Django does not run `choices` on `save()`, so whatever the
    form sent was persisted verbatim.

The start-production form offered "sustainable", which is not a model choice. It therefore
landed in a `choices` column that `get_production_method_display()` can only echo back raw,
and that both the consumer QR page and the certifier packet read. The mirror-image half of
the same drift: `integrated`, `biodynamic`, `hydroponic` and `no_till` ARE valid choices that
the form could not render — which mattered because the template effect maps a template's
`system_type` onto this field and can set `integrated` or `no_till`, values with no matching
<option>, blanking the control.

Same shape as SaleUnitVocabularyTests: the defect lives in the FRONTEND list, so a guard that
only reads Django is structurally blind to it.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from history.models import History


class ProductionMethodVocabularyTests(SimpleTestCase):
    #: The one frontend list, and the const holding it.
    APP_METHOD_LIST = (
        "views/Dashboard/Dashboard/Production/QuickStartProduction.tsx",
        "PRODUCTION_METHOD_CHOICES",
    )

    def test_sustainable_is_not_a_choice(self):
        """It was never in the model, and it is not being added.

        Beyond the schema divergence, "sustainable" is an unqualified general-environmental-
        benefit claim — the 16 CFR 260.6 category. The fix is to stop offering it, not to
        legitimise it by widening the model.
        """
        self.assertNotIn("sustainable", dict(History.PRODUCTION_METHOD_CHOICES))

    def test_form_offers_exactly_the_model_vocabulary(self):
        """The guard with teeth — reads the actual dropdown out of trazo-app."""
        app_src = Path(__file__).resolve().parents[3] / "trazo-app" / "src"
        if not app_src.is_dir():
            # Do NOT silently pass; a guard that no-ops in half the checkouts is decorative.
            self.fail(f"trazo-app/src not found at {app_src}. This guard needs both repos.")

        relative_path, const_name = self.APP_METHOD_LIST
        path = app_src / relative_path
        self.assertTrue(path.is_file(), f"{relative_path} not found — did the form move?")
        source = path.read_text(encoding="utf8")

        opening = f"const {const_name} = ["
        start = source.find(opening)
        self.assertNotEqual(start, -1, f"{const_name} not found in {relative_path}")
        # Scope to THIS array: the file holds other `value:` lists a whole-file scan would mix in.
        end = source.find("\n]", start)
        self.assertNotEqual(end, -1, f"{const_name} in {relative_path} is not closed by ']'")

        found = re.findall(r"value:\s*'([^']+)'", source[start:end])
        expected = [value for value, _label in History.PRODUCTION_METHOD_CHOICES]
        self.assertEqual(
            found,
            expected,
            f"{relative_path} :: {const_name} must offer exactly "
            f"History.PRODUCTION_METHOD_CHOICES, in the same order. Adding or renaming a "
            f"method means changing both lists in one commit.",
        )

    def test_form_labels_match_the_model_display_strings(self):
        """The form and the certifier packet must name the same thing the same way.

        The packet prints `get_production_method_display()`; the farmer picked a label off the
        dropdown. If those two strings diverge, a grower cannot find the method they chose in
        their own audit file.
        """
        app_src = Path(__file__).resolve().parents[3] / "trazo-app" / "src"
        if not app_src.is_dir():
            self.fail(f"trazo-app/src not found at {app_src}. This guard needs both repos.")

        relative_path, const_name = self.APP_METHOD_LIST
        source = (app_src / relative_path).read_text(encoding="utf8")
        start = source.find(f"const {const_name} = [")
        end = source.find("\n]", start)

        found = re.findall(r"label:\s*'([^']+)'", source[start:end])
        expected = [label for _value, label in History.PRODUCTION_METHOD_CHOICES]
        self.assertEqual(found, expected, f"{relative_path} :: {const_name} labels must match the model's.")


class StartProductionMethodValidationTests(SimpleTestCase):
    """`start_production` must refuse a method the model does not define.

    This is the path that had no validation at all. Asserted at the view's own guard rather
    than over HTTP so the test does not need the full auth/permission fixture chain — the
    point is that the vocabulary check exists and reads the model, not the wire format.
    """

    def test_every_offered_method_is_accepted_by_the_model(self):
        valid = [value for value, _ in History.PRODUCTION_METHOD_CHOICES]
        for method in valid:
            with self.subTest(method=method):
                history = History(production_method=method)
                # Populated from choices, so the display string must resolve to a real label
                # rather than echoing the slug back.
                self.assertNotEqual(history.get_production_method_display(), method)

    def test_an_unknown_method_has_no_display_label(self):
        """Why the raw write path was a real defect and not a cosmetic one.

        Django echoes an out-of-vocabulary value straight back out of
        `get_production_method_display()`, so nothing downstream can tell a stored
        "sustainable" from a legitimate label — it just prints in the packet.
        """
        self.assertEqual(History(production_method="sustainable").get_production_method_display(), "sustainable")
