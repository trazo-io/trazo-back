"""The "edited after finalization" flag must fire on real corrections and stay silent otherwise.

Until 2026-08-19 the packet compared every audit timestamp against `finish_date` — the season
end date the GROWER types on the finish form. A pilot entering last season's records (the
October use case) sets that to last autumn and does the data entry today, so every edit landed
"after finalization" and the packet asked the inspector to review all of them. A flag that
fires on every well-kept backfilled season teaches an inspector to ignore it.

The comparison is now against the moment the season was closed IN TRAZO, taken from the log
entry that first wrote `finish_date` — and extended to the end of that second, because closing
writes `finish_date` and `extra_data` as two rows microseconds apart and counting the second
one would put a [REVIEW] on every correctly closed season.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User


class PacketPostCloseEditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="postclose@test.com", password="x")
        company = Company.objects.create(name="Close Farm")
        self.est = Establishment.objects.create(name="C Block", company=company)
        parcel = Parcel.objects.create(name="P1", establishment=self.est, area=1.0)
        crop = CropType.objects.create(
            name="Walnuts",
            slug="walnuts-postclose",
            category="tree_nut",
            description="Tree nut",
            typical_farm_size="10-40 ha",
            growing_season="Feb-Oct",
            harvest_season="Sep-Oct",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Walnuts")
        # A BACKFILLED season: the season ended last year, the data entry happens now.
        self.history = History.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=400),
        )

    def _flag_text(self):
        from history.services import audit_export_service as svc

        captured = []
        original = svc.AuditExportService._warning_style

        # The flag is a Paragraph built with _warning_style; capture the rendered strings via
        # the body/Paragraph path instead by scanning the produced PDF text is unreliable, so
        # spy on Paragraph construction through the service's own helper.
        import reportlab.platypus as platypus

        orig_para = platypus.Paragraph

        def spy_para(text, *a, **kw):
            captured.append(str(text))
            return orig_para(text, *a, **kw)

        platypus.Paragraph = spy_para
        svc.Paragraph = spy_para
        try:
            svc.AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        finally:
            platypus.Paragraph = orig_para
            svc.Paragraph = orig_para
        # Anchored on "closed in Trazo on" — the load-bearing phrase, not the whole sentence.
        # The sentence was reworded on 2026-08-20 to name which of the two dates it means, and
        # the old literal stopped matching: the positive test failed loudly, but the NEGATIVE
        # test would have gone on passing because the text had become invisible rather than
        # absent. `self._captured` lets that test prove it read something.
        self._captured = captured
        return [t for t in captured if "closed in Trazo on" in t]

    def test_a_cleanly_closed_backfilled_season_is_not_flagged(self):
        self.history.finish_date = timezone.now() - timedelta(days=300)
        self.history.lot_id = "LOT-X"
        self.history.save()

        flags = self._flag_text()
        self.assertGreater(
            len(self._captured), 20, "the export produced almost no paragraphs — the spy is not reading the document"
        )
        self.assertEqual(
            flags,
            [],
            "closing a backfilled season must not flag the close itself as a post-close edit",
        )

    def test_a_genuine_edit_after_closing_is_flagged(self):
        self.history.finish_date = timezone.now() - timedelta(days=300)
        self.history.save()

        # A later, separate correction — the thing the flag exists for. The test writes both
        # saves within the same second, which the close-window rule deliberately treats as one
        # operation, so the correction's log entry is moved to a realistic later moment. A
        # grower cannot type a correction inside the same second they closed the season.
        from django.contrib.contenttypes.models import ContentType

        from auditlog.models import LogEntry

        self.history.production_amount = 123.0
        self.history.save()

        ct = ContentType.objects.get_for_model(History)
        latest = LogEntry.objects.filter(content_type=ct, object_pk=str(self.history.pk)).order_by("-timestamp").first()
        latest.timestamp = latest.timestamp + timedelta(minutes=5)
        latest.save(update_fields=["timestamp"])

        flags = self._flag_text()
        self.assertTrue(flags, "a real edit made after the season was closed should be flagged")
        self.assertIn("closed in Trazo", flags[0])
