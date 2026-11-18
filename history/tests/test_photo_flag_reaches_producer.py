"""The Vision verdict on a record's photos is on its detail, for the farm (2026-11-17).

The activity sheet warns "this photo looks like a stock image" from `photo_content_flag`. Only
`PublicHistorySerializer` computed it, and returns it only to members of the farm's company, on
the Production Profile's season payload. The lists that open the sheet most, the parcel timeline
(`current_production`) and the Activities feed, never carried it, so from there the warning never
showed (measured in a browser on a copy of the vid03 database).

The fix puts it on the record DETAIL (`EventViewSet._with_photo_content_flag`), which the sheet
reads for its notices, in the season payload's shape: the key only when a photo is flagged. NOT
on the shared per-type serializers: those feed `HistorySerializer`, which the signed-in shopper's
`my_reviews` returns. The last test guards that boundary.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from common.models import Gallery, GalleryImage
from company.models import Company
from history.constants import CHEMICAL_EVENT_TYPE
from history.models import ChemicalEvent, Production
from history.serializers import HistorySerializer
from product.models import Establishment, Parcel
from users.models import WorksIn


class PhotoFlagReachesProducerTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(email="owner@example.com", password="pw-for-tests-only")
        cls.company = Company.objects.create(name="Owner Co")
        WorksIn.objects.create(user=cls.owner, company=cls.company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Owner Farm", company=cls.company)
        parcel = Parcel.objects.create(name="North", establishment=est, area=1)
        cls.history = Production.objects.create(parcel=parcel, name="2026 Season")

        cls.flagged = cls._spray("Kocide 3000-O", content_validation="stock_photo")
        cls.clean = cls._spray("Entrust SC", content_validation="agricultural")
        cls.no_photo = ChemicalEvent.objects.create(
            history=cls.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Dipel DF",
            description="no photo",
            date=timezone.now(),
        )

    @classmethod
    def _spray(cls, name, content_validation):
        album = Gallery.objects.create()
        GalleryImage.objects.create(
            gallery=album,
            image_url="https://example.test/photo.jpg",
            extra_data={"content_validation": content_validation},
        )
        return ChemicalEvent.objects.create(
            history=cls.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name=name,
            description=name,
            date=timezone.now(),
            album=album,
        )

    def _detail(self, event):
        return reverse("events-detail", args=[event.pk]) + f"?event_type={CHEMICAL_EVENT_TYPE}"

    def test_the_detail_carries_the_verdict_to_the_farmer(self):
        self.client.force_authenticate(user=self.owner)
        res = self.client.get(self._detail(self.flagged))
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.json()["photo_content_flag"], "stock_photo")

    def test_a_clean_photo_or_no_photo_carries_no_key(self):
        """Absent, not null: the season payload drops unset keys, and the two must not disagree."""
        self.client.force_authenticate(user=self.owner)
        for event in (self.clean, self.no_photo):
            res = self.client.get(self._detail(event))
            self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
            self.assertNotIn("photo_content_flag", res.json())

    def test_the_shared_season_payload_never_carries_it(self):
        """`HistorySerializer` is what `my_reviews` hands a signed-in shopper.

        Reads the serialized events first, so a payload with no events cannot pass vacuously.
        """
        events = HistorySerializer(self.history).data["events"]
        names = {e.get("commercial_name") for e in events}
        self.assertIn("Kocide 3000-O", names)
        for event in events:
            self.assertNotIn("photo_content_flag", event)
