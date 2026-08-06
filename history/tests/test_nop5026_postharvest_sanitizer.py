"""NOP 5026 wash-water sanitizer must survive the write path for POST-HARVEST events.

Found 2026-07-31 (CA organic walnut pilot QA). The five sanitizer columns existed on
ProductionEvent — and were even exposed on the anonymous consumer payload — but:

  * the form rendered them only for EM (equipment maintenance) with operation type CL, and
  * `ProductionTab.jsx` nested them inside a `data.type === 'EM'` spread on submit,

so a post-harvest wash — the dump tank, hydrocooler or huller, which is exactly what
NOP 5026 / 7 CFR 205.605(b) governs — could never record a chlorine residual. Only the
seed/demo management commands ever populated these fields.

§ 205.605(b) caps RESIDUAL chlorine in water at the point of last crop contact at the Safe
Drinking Water Act MRDL (4 mg/L free chlorine/chloramine). That measurement happens where
the water touches the crop, not in the equipment-cleaning log.

These tests pin the SERIALIZER contract: the fields must land on their real model columns
for a PH event, not in extra_data (the failure mode that hid `target_pest_disease` earlier
in the same audit, where a read-path fallback made the UI look correct while the audit PDF
— which reads the column — printed a blank).
"""

from decimal import Decimal

from django.test import SimpleTestCase

from history.models import ProductionEvent
from history.serializers import ProductionEventSerializer

SANITIZER_COLUMNS = (
    "sanitizer_name",
    "sanitizer_ppm",
    "sanitizer_residual_ppm_at_discharge",
    "rinse_step_documented",
    "sanitizer_nop_reference",
)


class SanitizerColumnsExistTests(SimpleTestCase):
    def test_all_five_are_real_model_columns(self):
        names = {f.name for f in ProductionEvent._meta.get_fields()}
        for col in SANITIZER_COLUMNS:
            self.assertIn(col, names, f"{col} is not a ProductionEvent column")


class SanitizerSerializerWritePathTests(SimpleTestCase):
    """The serializer must accept these on a PH event and keep them top-level."""

    PAYLOAD = {
        "type": "PH",
        "date": "2026-02-10T09:00:00Z",
        "description": "Dump-tank wash, chlorinated municipal supply",
        "sanitizer_name": "Chlorine (sodium hypochlorite)",
        "sanitizer_ppm": "80",
        "sanitizer_residual_ppm_at_discharge": "3.6",
        "rinse_step_documented": True,
        "sanitizer_nop_reference": "§ 205.605(b) - Chlorine materials; SDWA MRDL 4 mg/L",
    }

    def test_serializer_declares_the_sanitizer_fields(self):
        fields = ProductionEventSerializer().get_fields()
        for col in SANITIZER_COLUMNS:
            self.assertIn(col, fields, f"{col} not exposed by ProductionEventSerializer")

    def _internal(self, payload=None):
        """Run to_internal_value directly.

        Full is_valid() also demands the unrelated FKs (history/parcels) that a real
        request supplies, and returns {} without them — which would make these assertions
        vacuously pass. to_internal_value is the exact hook where field routing (top-level
        column vs nested extra_data) is decided, so it is what we want to pin.
        """
        return ProductionEventSerializer().to_internal_value(dict(payload or self.PAYLOAD))

    def test_values_land_top_level_not_in_extra_data(self):
        vd = self._internal()
        extra = vd.get("extra_data") or {}
        for col in SANITIZER_COLUMNS:
            self.assertIn(col, vd, f"{col} did not reach validated_data top level")
            self.assertNotIn(
                col,
                extra,
                f"{col} was routed into extra_data — the audit PDF reads the COLUMN, "
                f"so a copy in extra_data renders as blank for the certifier",
            )

    def test_residual_is_parsed_as_a_number(self):
        # The MRDL comparison in the audit export is numeric; a string would break the
        # PASS/REVIEW verdict rather than fail loudly.
        vd = self._internal()
        self.assertEqual(vd["sanitizer_residual_ppm_at_discharge"], Decimal("3.6"))

    def test_residual_above_the_sdwa_mrdl_is_still_accepted_for_review(self):
        # Trazo documents; it does not silently correct. An over-limit reading must be
        # recordable so the audit export can flag it, not rejected at the form.
        vd = self._internal(dict(self.PAYLOAD, sanitizer_residual_ppm_at_discharge="6.5"))
        self.assertEqual(vd["sanitizer_residual_ppm_at_discharge"], Decimal("6.5"))
