"""The § 205.206(a) IPM warning belongs to interventions, not to monitoring records.

§ 205.206(a) requires cultural, mechanical and biological practices BEFORE a pest-control
substance is applied. A trap count, a scouting round, a species identification and a
threshold assessment are how a grower decides whether to intervene at all — none of them
implements an IPM strategy, so a blank strategy field on one is not a gap.

The packet was printing "[WARNING] 3 pest event(s) missing IPM strategy" for a season whose
three pest records were one sanitation practice — which IS the preventive practice the clause
asks for — and two monitoring records. Nothing the grower could do would clear it, which is
what makes it worse than no warning: it teaches the reader to skim past the amber that counts.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import PestManagementEvent, Production
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product


def _text(elements):
    out = []
    for el in elements:
        out.append(getattr(el, "text", "") or "")
        for attr in ("_cellvalues",):
            rows = getattr(el, attr, None) or []
            for row in rows:
                for cell in row:
                    out.append(getattr(cell, "text", "") or "")
    return " ".join(out)


class PestIpmWarningScopeTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="IPM Co")
        est = Establishment.objects.create(name="IPM Farm", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=1.0)
        crop = CropType.objects.create(
            name="Walnut",
            slug="walnut-ipm",
            category="tree_nut",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Walnut")
        self.history = Production.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=120),
        )

    def _add(self, type_code, ipm_strategy=""):
        return PestManagementEvent.objects.create(
            history=self.history,
            type=type_code,
            date=timezone.now(),
            pest_species="Rhagoletis completa",
            ipm_strategy=ipm_strategy,
        )

    def _pest_text(self):
        return _text(AuditExportService(self.history, certification_type="organic")._build_pest_section())

    def test_monitoring_records_alone_raise_no_warning(self):
        for code in ("SC", "TM", "PI", "TA"):
            self._add(code)
        self.assertNotIn("missing IPM strategy", self._pest_text())

    def test_an_intervention_without_a_strategy_still_warns(self):
        self._add("TM")
        self._add("IP")
        text = self._pest_text()
        self.assertIn("missing IPM strategy", text)
        self.assertIn("1 pest event(s)", text)

    def test_an_intervention_with_a_strategy_raises_no_warning(self):
        self._add("CU", ipm_strategy="Mummy nut removal by hand poling before bloom")
        self.assertNotIn("missing IPM strategy", self._pest_text())


class LongStrategyPrintedOnceTests(PestIpmWarningScopeTests):
    """VID-12 (recordkeeping checklist run 2026-11-16): the ~800-character IPM programme sat in the
    IPM Strategy cell of every scouting and trap row and was most of a 449-page dossier. A long
    strategy recorded word for word on several records is printed once below the table, with the
    number of records that hold it, and each row refers to it."""

    PROGRAMME = (
        "Blueberry program, in order: prevention first, permanent sod alleys and clean cultivation "
        "under the bushes, pruning for airflow, sanitation of dropped fruit; monitoring with six traps "
        "per block and weekly fruit checks; treatment only at threshold, rotating modes of action. "
    ) * 2

    def test_a_long_repeated_strategy_is_printed_once_and_referred_to(self):
        for _ in range(3):
            self._add("TM", ipm_strategy=self.PROGRAMME)
        self._add("SC", ipm_strategy="Weekly walk of 20 bushes per block")
        text = self._pest_text()
        self.assertEqual(text.count(self.PROGRAMME.strip()), 1, "the programme printed more than once")
        self.assertEqual(text.count("Strategy A (full text below this table)"), 3)
        self.assertIn("IPM strategy A</b>, as recorded on 3 of these records", text)
        # A short strategy stays in its row.
        self.assertIn("Weekly walk of 20 bushes per block", text)

    def test_a_long_strategy_on_one_record_stays_in_its_row(self):
        self._add("TM", ipm_strategy=self.PROGRAMME)
        text = self._pest_text()
        self.assertNotIn("Strategy A", text)
        self.assertIn(self.PROGRAMME.strip()[:80], text)

    def test_the_label_and_reference_helpers(self):
        from history.services.audit_export_service import _repeated_long_texts, _strategy_cell

        long_a, long_b = "a" * 250, "b" * 250
        refs = _repeated_long_texts([long_a, "short", long_b, long_a, long_b, long_b, None])
        self.assertEqual(refs, {long_a: ("A", 2), long_b: ("B", 3)})
        self.assertEqual(_strategy_cell(long_b, refs), "Strategy B (full text below this table)")
        self.assertEqual(_strategy_cell("short", refs), "short")
        self.assertIsNone(_strategy_cell("", refs))
