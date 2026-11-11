"""The farm home names what a block grows, also between seasons.

`ParcelBasicSerializer.product` is the CURRENT season's crop, and other screens read its null as
"nothing growing now", so it stays as it is. The farm home's parcel rows printed it as the crop, and
on 2026-11-11 a walnut block whose season had just been finished read "15.4 ac" with no crop at all,
as if it had never grown anything. `crop_names` answers the row's question: the current season's
crop, else the crops the operator planned for the parcel, else the parcel's own product, else the
crop of its latest season.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from company.serializers import EstablishmentSerializer, RetrieveEstablishmentSerializer
from history.models import History
from product.models import Parcel, ParcelPlannedCrop, Product


class ParcelCropNamesTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Crop Names Co.")
        self.est = Establishment.objects.create(name="Crop Names Farm", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=6.2)
        self.walnuts = Product.objects.create(name="Walnuts")
        now = timezone.now()
        self.last_year = now - timedelta(days=400)
        self.this_year = now - timedelta(days=200)

    def season(self, product, start, finished=True):
        return History.objects.create(
            parcel=self.parcel,
            product=product,
            name=f"{product.name} {start.year}",
            start_date=start,
            finish_date=start + timedelta(days=150) if finished else None,
        )

    def row(self):
        rows = EstablishmentSerializer(self.est).get_parcels(self.est)
        return next(r for r in rows if r["id"] == self.parcel.id)

    def test_a_finished_season_still_names_its_crop(self):
        self.season(self.walnuts, self.this_year)
        row = self.row()
        self.assertIsNone(row["product"], "product stays the CURRENT season's crop")
        self.assertEqual(row["crop_names"], ["Walnuts"])

    def test_the_latest_season_wins_over_an_older_one(self):
        self.season(Product.objects.create(name="Almonds"), self.last_year)
        self.season(self.walnuts, self.this_year)
        self.assertEqual(self.row()["crop_names"], ["Walnuts"])

    def test_the_current_season_is_named_first(self):
        current = self.season(self.walnuts, self.this_year, finished=False)
        self.parcel.current_history = current
        self.parcel.save(update_fields=["current_history"])
        ParcelPlannedCrop.objects.create(parcel=self.parcel, crop="Cherries")
        self.assertEqual(self.row()["crop_names"], ["Walnuts"])

    def test_planned_crops_name_a_block_with_no_season_underway(self):
        self.season(Product.objects.create(name="Almonds"), self.last_year)
        ParcelPlannedCrop.objects.create(parcel=self.parcel, crop="Walnuts")
        ParcelPlannedCrop.objects.create(parcel=self.parcel, crop="Walnuts ")
        ParcelPlannedCrop.objects.create(parcel=self.parcel, crop="Cherries")
        self.assertEqual(self.row()["crop_names"], ["Walnuts", "Cherries"])

    def test_a_parcel_that_never_grew_anything_names_nothing(self):
        self.assertEqual(self.row()["crop_names"], [])

    def test_the_fallback_costs_no_query_per_parcel(self):
        """Planned crops arrive in ONE prefetch and the latest season's crop inside the parcel query
        itself, however many parcels the farm has."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for i in range(4):
            parcel = Parcel.objects.create(name=f"Block {i}", establishment=self.est, area=2.0)
            History.objects.create(parcel=parcel, product=self.walnuts, name=f"S{i}", start_date=self.this_year)
        with CaptureQueriesContext(connection) as ctx:
            rows = EstablishmentSerializer(self.est).get_parcels(self.est)
        sqls = [q["sql"] for q in ctx.captured_queries]
        self.assertEqual(sum("product_parcelplannedcrop" in q for q in sqls), 1)
        self.assertIn("latest_season_crop", sqls[0], "the fallback rides on the parcel query")
        self.assertEqual(
            sum('"product_product"."name"' in q and "product_parcel" not in q for q in sqls),
            0,
            "no per-parcel lookup of a season's product",
        )
        self.assertEqual([r["crop_names"] for r in rows if r["name"].startswith("Block")], [["Walnuts"]] * 4)

    def test_a_season_with_no_start_date_does_not_outrank_a_dated_one(self):
        """PostgreSQL sorts NULL first under DESC; the fallback orders NULLS LAST."""
        self.season(self.walnuts, self.this_year)
        History.objects.create(
            parcel=self.parcel, product=Product.objects.create(name="Almonds"), name="Undated", start_date=None
        )
        self.assertEqual(self.row()["crop_names"], ["Walnuts"])

    def test_the_retrieve_serializer_names_the_crop_without_a_query_per_parcel(self):
        """The list/retrieve path (`RetrieveEstablishmentSerializer.get_parcels`) reads the same
        field, so it carries the same prefetches (review of #388)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for i in range(3):
            parcel = Parcel.objects.create(name=f"Block {i}", establishment=self.est, area=2.0)
            # An open season, so get_crop_names dereferences current_history.product.
            parcel.current_history = History.objects.create(
                parcel=parcel, product=self.walnuts, name=f"S{i}", start_date=self.this_year
            )
            parcel.save(update_fields=["current_history"])
        serializer = RetrieveEstablishmentSerializer(self.est)
        with CaptureQueriesContext(connection) as ctx:
            rows = serializer.get_parcels(self.est)
        sqls = [q["sql"] for q in ctx.captured_queries]
        self.assertEqual(sum("product_parcelplannedcrop" in q for q in sqls), 1)
        self.assertEqual(
            sum(q.lstrip().startswith('SELECT "product_product"') for q in sqls),
            0,
            "no per-parcel lookup of a parcel's or a season's product",
        )
        self.assertEqual([r["crop_names"] for r in rows if r["name"].startswith("Block")], [["Walnuts"]] * 3)
