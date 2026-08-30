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
"""

from django.test import SimpleTestCase

from history.services.audit_export_service import _EMISSION_FACTOR_BASIS, _emission_factor_basis

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

    def test_the_usda_values_render_as_sourced_not_verified(self):
        # The exact SAFE/UNSAFE pair from compliance.md.
        for value in ("usda_verified", "epa_usda_verified_aggregate"):
            rendered = _emission_factor_basis(value)
            self.assertIn("EPA/USDA-sourced", rendered)
            self.assertNotIn("USDA Verified", rendered)
            self.assertNotIn("usda_verified", rendered)

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
