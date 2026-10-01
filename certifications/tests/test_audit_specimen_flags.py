"""The specimen-flag census: read-only, and it must not rely on names alone.

Every control that stops invented records presenting as a real certified farm keys on
`Establishment.is_demo`, which is opt-IN by design. This command is what makes the resulting
blind spot visible. Two properties matter and both are pinned here:

  * an operation carrying a registry-verified badge is reported EVEN IF its name looks
    perfectly genuine — the case a name heuristic would miss, and the one measured live
    (`Loewen Family Farm`, no seeded substring anywhere, publishing "Verified via USDA Organic
    Integrity Database" from invented records); and
  * it WRITES NOTHING.
"""

from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from certifications.models import Certification
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User


class AuditSpecimenFlagsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="census@test.com", password="x")
        self.company = Company.objects.create(name="Census Co")
        self.product = Product.objects.create(name="Walnuts")

    def _operation(self, name, *, is_demo, published, verified, company_name=None):
        company = Company.objects.create(name=company_name) if company_name else self.company
        establishment = Establishment.objects.create(name=name, company=company, state="CA", is_demo=is_demo)
        parcel = Parcel.objects.create(name=f"{name} block", establishment=establishment, area=3.0)
        History.objects.create(
            name=f"{name} season",
            start_date=timezone.now() - timedelta(days=30),
            product=self.product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=10.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=published,
        )
        if verified:
            Certification.objects.create(
                establishment=establishment,
                certification_type="usda_organic",
                certifier_name="CCOF Certification Services, LLC",
                effective_date=date(2022, 1, 1),
                expiry_date=date(2030, 12, 31),
                verification_status="verified",
                verification_source=Certification.DATABASE_VERIFICATION_SOURCE,
            )
        return establishment

    def _run(self, *args):
        out = StringIO()
        call_command("audit_specimen_flags", *args, stdout=out)
        return out.getvalue()

    def test_it_reports_a_genuine_looking_name_that_carries_a_verified_badge(self):
        """The measured case. A name heuristic alone would never have found this one."""
        self._operation("Loewen Family Farm", is_demo=False, published=True, verified=True)
        output = self._run()
        self.assertIn("Loewen Family Farm", output)
        self.assertIn("Verified via USDA Organic Integrity Database", output)

    def test_it_reports_a_seeded_looking_name_without_a_badge(self):
        self._operation("QA Test Farm Estate", is_demo=False, published=True, verified=False)
        self.assertIn("QA Test Farm Estate", self._run())

    def test_it_stays_quiet_about_a_properly_flagged_demo_farm(self):
        """The whole point of the flag: a marked operation is not a finding."""
        self._operation("Calapooia Bend Farm", is_demo=True, published=True, verified=True)
        output = self._run()
        self.assertNotIn("Calapooia Bend Farm", output)

    def test_it_stays_quiet_about_a_real_operation(self):
        """The mirror. Reporting everyone would make the report useless."""
        self._operation(
            "Blue Ridge Orchards", is_demo=False, published=True, verified=False, company_name="Blue Ridge Orchards LLC"
        )
        output = self._run()
        self.assertNotIn("Blue Ridge Orchards", output)
        self.assertIn("No unflagged operation is publishing a registry-verified claim", output)

    def test_unpublished_operations_need_the_all_flag(self):
        """Public exposure is the default filter: an unpublished fixture harms nobody yet."""
        self._operation("Test Draft Farm", is_demo=False, published=False, verified=False)
        self.assertNotIn("Test Draft Farm", self._run())
        self.assertIn("Test Draft Farm", self._run("--all"))

    def test_it_writes_nothing(self):
        """⛔ Read-only. Deciding an operation is fabricated is a human judgment — flipping
        `is_demo` from a string match would stamp SPECIMEN across a real farm's packet."""
        establishment = self._operation("Test Farm", is_demo=False, published=True, verified=True)
        before = (
            establishment.is_demo,
            Establishment.objects.count(),
            Certification.objects.count(),
            History.objects.count(),
        )
        self._run()
        establishment.refresh_from_db()
        self.assertEqual(
            (
                establishment.is_demo,
                Establishment.objects.count(),
                Certification.objects.count(),
                History.objects.count(),
            ),
            before,
        )

    def test_fail_on_risk_exits_non_zero_only_when_a_badge_is_published(self):
        self._operation("Test Farm", is_demo=False, published=True, verified=True)
        with self.assertRaises(SystemExit):
            self._run("--fail-on-risk")

    def test_fail_on_risk_is_quiet_when_there_is_no_published_badge(self):
        self._operation("Test Farm", is_demo=False, published=True, verified=False)
        self._run("--fail-on-risk")  # must not raise
