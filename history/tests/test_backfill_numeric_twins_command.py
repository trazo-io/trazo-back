"""`backfill_chemical_numeric_twins` repairs the derived columns and nothing else.

These are records already filed with a certifier. A backfill that fills a derived column must
not rewrite anything else about them — an earlier draft used `save(update_fields=[...])`, which
still fires `post_save` and so recalculated the carbon entry of all 223 records it touched.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel, Product


class BackfillNumericTwinsTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Backfill Co")
        est = Establishment.objects.create(name="Backfill Farm", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=1.0)
        crop = CropType.objects.create(
            name="Walnut",
            slug="walnut-backfill",
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
            start_date=timezone.now() - timedelta(days=90),
        )

    def _event(self, **kw):
        base = dict(
            history=self.history,
            type="FU",
            date=timezone.now(),
            description="d",
            commercial_name="Kocide 3000-O",
        )
        base.update(kw)
        event = ChemicalEvent.objects.create(**base)
        # create() runs the model save path, which may populate the twins; null them so the
        # fixture is the pre-2026-08-19 shape the command exists to repair.
        ChemicalEvent.objects.filter(pk=event.pk).update(volume_numeric=None, area_numeric=None)
        return event

    def _run(self, *args):
        out = StringIO()
        call_command("backfill_chemical_numeric_twins", *args, stdout=out)
        return out.getvalue()

    def test_it_fills_both_twins_from_the_strings(self):
        event = self._event(volume="8", volume_unit="oz", area="12.5", area_unit="acres")
        self._run()
        event.refresh_from_db()
        self.assertEqual(float(event.volume_numeric), 8.0)
        self.assertEqual(float(event.area_numeric), 12.5)

    def test_a_grouped_number_is_not_read_as_its_first_digit(self):
        """ "1,200 lb" must not become 1 lb in the mass balance."""
        event = self._event(volume="1,200", volume_unit="lbs", area="15.4", area_unit="acres")
        self._run()
        event.refresh_from_db()
        self.assertEqual(float(event.volume_numeric), 1200.0)

    def test_dry_run_writes_nothing_but_reports(self):
        event = self._event(volume="8", volume_unit="oz")
        output = self._run("--dry-run")
        event.refresh_from_db()
        self.assertIsNone(event.volume_numeric)
        self.assertIn("Would fill", output)

    def test_an_unreadable_value_is_reported_and_left_null(self):
        event = self._event(volume="Unknown")
        output = self._run()
        event.refresh_from_db()
        self.assertIsNone(event.volume_numeric)
        self.assertIn("no leading number", output)
        self.assertIn(str(event.pk), output)

    def test_an_existing_value_is_never_overwritten(self):
        event = self._event(volume="8", volume_unit="oz")
        ChemicalEvent.objects.filter(pk=event.pk).update(volume_numeric=99)
        self._run()
        event.refresh_from_db()
        self.assertEqual(float(event.volume_numeric), 99.0)

    def test_it_spans_more_than_one_batch(self):
        """The loop flushes per batch; a run larger than one batch must not lose the tail."""
        from history.management.commands import backfill_chemical_numeric_twins as cmd

        original = cmd.BATCH_SIZE
        cmd.BATCH_SIZE = 2
        try:
            events = [self._event(volume=str(n + 1), volume_unit="oz") for n in range(5)]
            self._run()
        finally:
            cmd.BATCH_SIZE = original
        for index, event in enumerate(events):
            event.refresh_from_db()
            self.assertEqual(float(event.volume_numeric), float(index + 1), f"event {index} lost")
