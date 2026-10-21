"""Reviews: reading is scoped, and a review is written as its own author about a public season.

Found by the 2026-10-20 route inventory (`backend/route_tenancy.py`), reproduced here before the fix:

  * `list`/`retrieve` were AllowAny over `Review.objects.all()`: a stranger listed every tenant's
    reviews with the reviewer's full name and avatar, unpublished seasons included. `get_permissions`
    hid this from `test_anonymous_endpoint_inventory`, which reads only the permission class.
  * `create` took `user` from the body (post as anyone), `production` by integer id with no
    published check (review an unpublished season, which `my_reviews` then echoes back in full), and
    `scan` from any season (`verified_purchase` is `bool(scan_id)`).
  * `establishment_reviews_paginated` took `company_id` from the query string with no membership
    check, and its search matches reviewer emails.

The QR page only ever POSTs (`ModernProductReview.tsx`); nothing in the app GETs `/api/reviews/`.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import History, HistoryScan
from product.models import Parcel
from reviews.models import Review
from users.constants import CONSUMER, PRODUCER
from users.models import User, WorksIn


def _user(email, user_type=PRODUCER):
    return User.objects.create_user(
        email=email, password="x", first_name="Rev", last_name="Iewer", user_type=user_type, is_active=True
    )


class ReviewsScopedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.victim_co = Company.objects.create(name="Victim Farms")
        cls.victim_farm = Establishment.objects.create(name="Victim Farm", company=cls.victim_co)
        parcel = Parcel.objects.create(name="Victim Parcel", establishment=cls.victim_farm, area=2.0)
        cls.published = History.objects.create(name="Victim Published", parcel=parcel, published=True)
        cls.unpublished = History.objects.create(name="Victim Unpublished", parcel=parcel, published=False)
        cls.victim_admin = _user("admin@victim.example")
        WorksIn.objects.create(user=cls.victim_admin, company=cls.victim_co, role=WorksIn.COMPANY_ADMIN)

        cls.shopper = _user("shopper@example.com", CONSUMER)
        cls.review = Review.objects.create(
            production=cls.published, user=cls.shopper, rating=5, headline="Victim review", written_review="x"
        )

        other_co = Company.objects.create(name="Other Farms")
        other_parcel = Parcel.objects.create(
            name="Other Parcel", establishment=Establishment.objects.create(name="Other", company=other_co), area=1
        )
        cls.other_season = History.objects.create(name="Other Published", parcel=other_parcel, published=True)
        cls.other_scan = HistoryScan.objects.create(history=cls.other_season)

        cls.outsider = _user("admin@outsider.example")
        WorksIn.objects.create(
            user=cls.outsider, company=Company.objects.create(name="Outsider"), role=WorksIn.COMPANY_ADMIN
        )

    def _client(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    # --- reading ---------------------------------------------------------------------------------

    def test_anonymous_cannot_list_or_retrieve_reviews(self):
        for url in ("/api/reviews/", f"/api/reviews/{self.review.id}/"):
            with self.subTest(url=url):
                response = self._client().get(url)
                self.assertIn(response.status_code, (401, 403), response.content[:300])

    def test_outsider_sees_no_other_tenants_reviews(self):
        client = self._client(self.outsider)
        self.assertEqual(client.get(f"/api/reviews/{self.review.id}/").status_code, 404)
        listed = client.get("/api/reviews/")
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn(b"Victim review", listed.content)

    def test_author_and_farm_still_read_the_review(self):
        """Controls: the reviewer reads their own review; the reviewed farm's members read it too."""
        for user in (self.shopper, self.victim_admin):
            with self.subTest(user=user.email):
                response = self._client(user).get(f"/api/reviews/{self.review.id}/")
                self.assertEqual(response.status_code, 200, response.content[:300])

    def test_paginated_list_refuses_a_company_the_caller_does_not_work_in(self):
        params = {"establishment_id": self.victim_farm.id, "company_id": self.victim_co.id}
        response = self._client(self.outsider).get("/api/reviews/establishment_reviews_paginated/", params)
        self.assertEqual(response.status_code, 404, response.content[:300])
        self.assertNotIn(b"Victim review", response.content)
        own = self._client(self.victim_admin).get("/api/reviews/establishment_reviews_paginated/", params)
        self.assertEqual(own.status_code, 200, own.content[:300])

    def test_paginated_list_malformed_ids_are_a_400_not_a_500(self):
        # "\u00b2".isdigit() is True but int() raises on it.
        for bad in ("not-a-number", "\u00b2"):
            with self.subTest(company_id=bad):
                response = self._client(self.outsider).get(
                    "/api/reviews/establishment_reviews_paginated/",
                    {"establishment_id": self.victim_farm.id, "company_id": bad},
                )
                self.assertEqual(response.status_code, 400, response.content[:300])

    # --- writing ---------------------------------------------------------------------------------

    def _post(self, client, **fields):
        body = {"headline": "h", "written_review": "w", "rating": 4, **fields}
        return client.post("/api/reviews/", body, format="json")

    def test_review_cannot_be_posted_as_another_user(self):
        response = self._post(
            self._client(self.outsider), production_public_id=str(self.published.public_id), user=self.shopper.id
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(Review.objects.get(id=response.data["id"]).user_id, self.outsider.id)

    def test_anonymous_review_has_no_author_even_if_one_is_named(self):
        response = self._post(self._client(), production_public_id=str(self.published.public_id), user=self.shopper.id)
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertIsNone(Review.objects.get(id=response.data["id"]).user_id)

    def test_unpublished_season_cannot_be_reviewed(self):
        for fields in ({"production": self.unpublished.id}, {"production_public_id": str(self.unpublished.public_id)}):
            with self.subTest(fields=fields):
                response = self._post(self._client(self.outsider), **fields)
                self.assertEqual(response.status_code, 400, response.content[:300])
        self.assertFalse(Review.objects.filter(production=self.unpublished).exists())

    def test_scan_must_belong_to_the_reviewed_season(self):
        response = self._post(
            self._client(), production_public_id=str(self.published.public_id), scan=self.other_scan.id
        )
        self.assertEqual(response.status_code, 400, response.content[:300])

    def test_scan_counts_only_when_it_is_the_reviewers_and_unused(self):
        """Scan ids are sequential: citing somebody else's scan, or reusing one, must not buy a
        verified purchase. The review still saves; it just carries no scan."""
        someone_elses = HistoryScan.objects.create(history=self.published, user=self.shopper)
        anonymous_scan = HistoryScan.objects.create(history=self.published)
        cases = (
            (self.outsider, someone_elses),
            (None, anonymous_scan),
        )
        for user, scan in cases:
            with self.subTest(user=getattr(user, "email", "anonymous"), scan=scan.id):
                response = self._post(
                    self._client(user), production_public_id=str(self.published.public_id), scan=scan.id
                )
                self.assertEqual(response.status_code, 201, response.content[:300])
                self.assertIsNone(Review.objects.get(id=response.data["id"]).scan_id)

        own = HistoryScan.objects.create(history=self.published, user=self.outsider)
        first = self._post(self._client(self.outsider), production_public_id=str(self.published.public_id), scan=own.id)
        self.assertEqual(Review.objects.get(id=first.data["id"]).scan_id, own.id)
        reused = self._post(
            self._client(self.outsider), production_public_id=str(self.published.public_id), scan=own.id
        )
        self.assertIsNone(Review.objects.get(id=reused.data["id"]).scan_id)

    def test_author_can_edit_by_public_id_after_unpublishing(self):
        """Both production paths keep the author's carve-out, not only the integer one."""
        review = Review.objects.create(production=self.unpublished, user=self.shopper, rating=3, headline="old")
        response = self._client(self.shopper).patch(
            f"/api/reviews/{review.id}/",
            {"headline": "edited", "production_public_id": str(self.unpublished.public_id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])

    def test_qr_page_review_still_posts(self):
        """The control: the exact payload ModernProductReview.tsx sends, signed in, with a real scan."""
        scan = HistoryScan.objects.create(history=self.published, user=self.shopper)
        response = self._post(
            self._client(self.shopper),
            production_public_id=str(self.published.public_id),
            user=self.shopper.id,
            scan=scan.id,
            images=[],
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        review = Review.objects.get(id=response.data["id"])
        self.assertEqual(
            (review.user_id, review.scan_id, review.production_id), (self.shopper.id, scan.id, self.published.id)
        )
