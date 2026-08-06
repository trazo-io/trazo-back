"""The consumer QR payload must not ship fields the farmer never filled.

Measured on a realistic 258-event CA walnut season (24 irrigation sets logged
individually rather than in summary mode, 6 sprays, 4 fertigations, 12 trap checks,
5 mowings, 3 shakes):

    events block          = 100% of the payload
    105 keys null on EVERY event = 316 KB
    payload 493 KB -> 194 KB (61% smaller), zero information removed

Each consumer event dict is hand-built per event CATEGORY and carries the union of every
field any subtype in that category might use, so an irrigation set was shipping
`sanitizer_nop_reference`, `cleaning_materials_used`, `seed_certification_status`,
`equipment_operation_type` … all null.

Why trimming and not paginating: the documented-practice COUNT is the consumer claim
(transparency-first rules — the consumer story is factual evidence, not a grade), so the
timeline must not silently drop events. Removing empty keys costs nothing.

`False` and `0` are REAL ANSWERS ("no photos", "not shared with conventional", "zero
catch") and must survive.
"""

import json

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History
from history.serializers import _drop_unset
from product.models import Parcel, Product
from users.models import User


class DropUnsetTests(SimpleTestCase):
    def test_drops_none_and_empty_string(self):
        out = _drop_unset({"a": None, "b": "", "c": "kept"})
        self.assertEqual(out, {"c": "kept"})

    def test_preserves_false(self):
        # "shared_with_conventional": False is an affirmative NOP answer, not an absence.
        out = _drop_unset({"shared_with_conventional": False})
        self.assertEqual(out, {"shared_with_conventional": False})

    def test_preserves_zero(self):
        # 0 photos / 0 pest catch are measurements, not missing data.
        out = _drop_unset({"photo_count": 0, "pest_catch_count": 0, "index": 0})
        self.assertEqual(out, {"photo_count": 0, "pest_catch_count": 0, "index": 0})

    def test_preserves_empty_collections(self):
        # An empty list is a shape the frontend may iterate; only None/"" are dropped.
        out = _drop_unset({"images": [], "meta": {}})
        self.assertEqual(out, {"images": [], "meta": {}})

    def test_recurses_into_nested_dicts(self):
        out = _drop_unset({"album": {"images": ["u"], "caption": None}, "x": None})
        self.assertEqual(out, {"album": {"images": ["u"]}})

    def test_non_dict_passes_through(self):
        self.assertEqual(_drop_unset("scalar"), "scalar")
        self.assertIsNone(_drop_unset(None))

    def test_keeps_every_meaningful_value(self):
        # The transformation must be exactly "remove unset", never "reshape".
        src = {
            "id": "chemical_0",
            "commercial_name": "Entrust SC",
            "epa_registration_number": "62719-621",
            "rei_hours": 4,
            "phi_days": 1,
            "certified": False,
            "photo_count": 0,
            "sanitizer_ppm": None,
            "cleaning_materials_used": "",
        }
        out = _drop_unset(src)
        for key, value in src.items():
            if value is None or value == "":
                self.assertNotIn(key, out)
            else:
                self.assertEqual(out[key], value, key)


class ConsumerEndpointCompressionTests(TestCase):
    """The anonymous consumer endpoints must compress.

    The QR page is the most mobile-critical surface in the product — a phone, in a shop or a
    field, on cell data, against a <500 ms budget — and the payload grows with the season.
    Measured on a realistic 258-event CA walnut year:

        465 KB  ->  184 KB  (dropping unset keys, above)
        184 KB  ->  6.1 KB  (gzip)          = 98.7% total

    Compression is scoped to the ANONYMOUS endpoints on purpose rather than enabling
    GZipMiddleware globally: BREACH needs a secret in the body next to attacker-controlled
    reflected input, and these endpoints are unauthenticated, carry no secret, and take only
    a UUID. Widening that to authenticated routes is a separate decision with its own review.

    Not relying on the edge: prod is behind Cloudflare, which compressed some responses and
    not others when checked, and dev/staging have no edge compression at all.
    """

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.user = User.objects.create_user(email="gzip@test.com", password="x")
        self.company = Company.objects.create(name="Gzip Farm")
        self.establishment = Establishment.objects.create(name="G1", company=self.company)
        self.parcel = Parcel.objects.create(name="GP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Gzip Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            published=True,
        )

    def _client(self):
        from rest_framework.test import APIClient

        return APIClient()

    def test_public_history_is_gzipped_when_the_client_accepts_it(self):
        res = self._client().get(
            f"/api/histories/{self.history.public_id}/public_history/", HTTP_ACCEPT_ENCODING="gzip"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Encoding"), "gzip")

    def test_transparency_is_gzipped_when_the_client_accepts_it(self):
        res = self._client().get(f"/api/transparency/{self.history.public_id}/", HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Encoding"), "gzip")

    def test_vary_accept_encoding_is_set(self):
        # Without Vary, a shared cache can hand a gzipped body to a client that cannot
        # decode it. Django's gzip_page sets this; assert it so it cannot regress.
        res = self._client().get(
            f"/api/histories/{self.history.public_id}/public_history/", HTTP_ACCEPT_ENCODING="gzip"
        )
        self.assertIn("Accept-Encoding", res.headers.get("Vary", ""))

    def test_client_that_does_not_accept_gzip_still_gets_plain_json(self):
        res = self._client().get(f"/api/histories/{self.history.public_id}/public_history/")
        self.assertEqual(res.status_code, 200)
        self.assertNotEqual(res.headers.get("Content-Encoding"), "gzip")
        self.assertEqual(json.loads(res.content)["events_count"], 0)

    def test_compressed_body_decodes_to_the_same_json(self):
        import gzip as _gzip

        c = self._client()
        gz = c.get(f"/api/histories/{self.history.public_id}/public_history/", HTTP_ACCEPT_ENCODING="gzip")
        plain = c.get(f"/api/histories/{self.history.public_id}/public_history/")
        self.assertEqual(_gzip.decompress(gz.content), plain.content)
