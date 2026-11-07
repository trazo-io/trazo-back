"""The carbon appendix may state a FACTOR BASIS. It may never state verification.

WHY THIS EXISTS
---------------
🔴 2026-08-29. The audit export's carbon appendix printed `CarbonEntry.verification_status` RAW
under a column headed **"Verification Status"**. That field is an untyped `CharField`, and its
live values on the pilot alone include:

    factors_verified 1256 · usda_verified 88 · epa_usda_verified_aggregate 2
    no_factor_applied 15 · estimated 8

So a document a certifier reads stated **"usda_verified"** against emission lines. That is the
claim `.claude/rules/compliance.md` forbids by name — "EPA/USDA-sourced" is SAFE, "USDA Verified"
is UNSAFE — and an FTC 16 CFR 260.6 exposure. Nothing about a Trazo carbon calculation is
verified by USDA or anyone else; USDA publishes the FACTORS.

It shipped in the `scs`, `roc` and `all` variants. SCS Global Services is a GHG verifier, which
is the worst possible audience for a column headed "Verification Status" reading "verified".

The carbon panel was audited twice (2026-08-20 provenance typing, 2026-08-22 display registry)
and this survived both, because it lives in the EXPORT rather than the panel. Hence a guard on
the string itself, not on one call site.

2026-11-05: the SAFE wording itself moved. `compliance.md` now lists a blanket "EPA/USDA-sourced"
as UNSAFE too (factor sources are per input class), and this appendix kept its own five-status
copy of the map, saying exactly that, beside the records export's twelve-status, per-class one.
The appendix now derives from the export's map and states the per-class sources in one note
under the table.
"""

from django.test import SimpleTestCase

from history.services.audit_export_service import _EMISSION_FACTOR_BASIS, CARBON_FACTOR_NOTE, _emission_factor_basis
from history.services.records_export import FACTOR_BASIS

#: Every value the field actually holds in production-shaped data.
LIVE_VALUES = (
    "factors_verified",
    "usda_verified",
    "epa_usda_verified_aggregate",
    "no_factor_applied",
    "estimated",
)


class EmissionFactorBasisTests(SimpleTestCase):
    def test_no_rendering_of_any_live_value_claims_verification(self):
        for value in LIVE_VALUES:
            rendered = _emission_factor_basis(value).lower()
            self.assertNotIn("verified", rendered, f"{value!r} renders as a verification claim")
            self.assertNotIn("certified", rendered, f"{value!r} renders as a certification claim")

    def test_the_usda_values_name_no_agency_wholesale(self):
        # compliance.md: "USDA Verified" and a blanket "EPA/USDA-sourced" are both UNSAFE; the
        # source is stated per input class, once, in the note under the table.
        for value in ("usda_verified", "epa_usda_verified_aggregate", "factors_verified"):
            rendered = _emission_factor_basis(value)
            self.assertIn("source per input class", rendered)
            self.assertNotIn("EPA/USDA", rendered)
            self.assertNotIn("USDA Verified", rendered)
            self.assertNotIn("usda_verified", rendered)

    def test_the_note_states_sources_per_class_and_no_verification(self):
        self.assertIn("diesel, petrol, electricity: EPA-published", CARBON_FACTOR_NOTE)
        self.assertIn("academic LCA", CARBON_FACTOR_NOTE)
        self.assertNotIn("EPA/USDA", CARBON_FACTOR_NOTE)
        self.assertIn("no third party has verified it", CARBON_FACTOR_NOTE)

    def test_the_appendix_and_the_records_export_know_the_same_statuses(self):
        # The drift this replaced: five statuses here, twelve there, so seven printed
        # "Factor basis not stated" in the PDF while the export named them.
        self.assertEqual(set(_EMISSION_FACTOR_BASIS), set(FACTOR_BASIS))

    def test_an_absent_factor_is_not_dressed_up(self):
        self.assertEqual(_emission_factor_basis("no_factor_applied"), "No factor applied")
        self.assertIn("no published factor", _emission_factor_basis("estimated"))

    def test_an_unknown_value_degrades_to_not_stated(self):
        # A new enum value must not inherit a neighbour's claim, and must not print raw.
        for value in ("", None, "some_future_status", "third_party_verified"):
            rendered = _emission_factor_basis(value)
            self.assertEqual(rendered, "Factor basis not stated")
            self.assertNotIn("verified", rendered.lower())

    def test_the_raw_enum_never_reaches_a_reader(self):
        for value in LIVE_VALUES:
            self.assertNotIn(value, _emission_factor_basis(value))

    def test_the_column_header_does_not_say_verification(self):
        # The header was half the claim: "verified" under "Verification Status" reads as a
        # third party having checked the number.
        import inspect

        from history.services import audit_export_service

        source = inspect.getsource(audit_export_service)
        self.assertNotIn(
            '"Amount (kg CO2e)", "Verification Status"',
            source,
            "the carbon appendix header must not claim verification",
        )

    def test_every_live_value_is_mapped(self):
        # Anti-vacuity: if the map were empty, every assertion above would pass on the fallback.
        for value in LIVE_VALUES:
            self.assertIn(value, _EMISSION_FACTOR_BASIS)


class NoBlanketAttributionInOutputsTests(SimpleTestCase):
    """No reader-facing string says "EPA/USDA-sourced" or "Direct Operational Emissions" (2026-11-05).

    Review of back #309: fixing the appendix's row label left the same section's Methodology line
    printing "Direct Operational Emissions — EPA/USDA-sourced factors", and a sweep found the
    phrase in the signup and invitation emails (HTML and text), a report generator, a crop
    templates payload and a seeded FAQ answer. compliance.md: factor sources are stated per input
    class, never as a blanket "EPA/USDA-sourced"; "direct on-farm emissions only" misstates the
    boundary, which includes the manufacturing of purchased fertilizer and chemicals.

    Python files are read through `ast` for STRING LITERALS only, so a comment explaining why a
    phrase was removed can still name it.
    """

    BANNED = ("EPA/USDA-sourced", "EPA/USDA sourced", "Direct Operational Emissions")
    PY_OUTPUTS = (
        "history/services/audit_export_service.py",
        "history/services/records_export.py",
        "carbon/views.py",
        "education/management/commands/seed_education_content.py",
    )
    TEMPLATE_DIR = "users/templates/emails"

    @staticmethod
    def _root():
        from pathlib import Path

        return Path(__file__).resolve().parents[2]

    def _string_literals(self, path):
        """Every string literal except docstrings (developer documentation, never output)."""
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                    docstrings.add(id(body[0].value))
        return [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
        ]

    def test_no_python_output_states_it(self):
        offenders, read = [], 0
        for rel in self.PY_OUTPUTS:
            path = self._root() / rel
            literals = self._string_literals(path)
            read += len(literals)
            for text in literals:
                for phrase in self.BANNED:
                    if phrase in text:
                        offenders.append(f"{rel}: {phrase!r} in {text[:80]!r}")
        self.assertGreater(read, 1000, "the sweep read almost no string literals")
        self.assertEqual(offenders, [])

    def test_no_email_template_states_it(self):
        templates = sorted((self._root() / self.TEMPLATE_DIR).glob("*.*"))
        self.assertGreater(len(templates), 3, "no email templates found to scan")
        offenders = [
            f"{t.name}: {phrase!r}"
            for t in templates
            for phrase in self.BANNED
            if phrase in t.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])
