"""Deleting a CONTAINER must not erase records NOP still requires (2026-08-18).

`History.delete()` refuses to erase a production inside its 7 CFR 205.103(b)(4) window,
but that only fires on a bound model delete. History.parcel, Parcel.establishment and
Establishment.company are all `on_delete=CASCADE`, and Django's collector deletes
cascaded rows in bulk — so `History.delete()` was never called and deleting a parcel, a
farm or a company erased retained productions straight past the guard.

These tests pin all three levels, and pin that a container whose records have aged out of
retention still deletes normally (the guard must not become a permanent tombstone).
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company
from history.models import History
from history.retention import RetentionConflict, assert_deletable
from product.models import Establishment, Parcel


class RetentionCascadeGuardTests(TestCase):
    def _tree(self, retention_until):
        company = Company.objects.create(name="Cascade Co")
        est = Establishment.objects.create(name="Cascade Farm", company=company)
        parcel = Parcel.objects.create(name="Cascade Parcel", establishment=est, area=1)
        History.objects.create(
            parcel=parcel,
            name="Season",
            finish_date=timezone.now() - timedelta(days=1),
            retention_until=retention_until,
        )
        return company, est, parcel

    # --- inside retention: every level refuses -----------------------------

    def test_parcel_delete_blocked(self):
        _, _, parcel = self._tree(timezone.now().date() + timedelta(days=365))
        with self.assertRaises(RetentionConflict):
            assert_deletable("parcel", parcel=parcel)

    def test_farm_delete_blocked(self):
        _, est, _ = self._tree(timezone.now().date() + timedelta(days=365))
        with self.assertRaises(RetentionConflict):
            assert_deletable("farm", parcel__establishment=est)

    def test_company_delete_blocked(self):
        company, _, _ = self._tree(timezone.now().date() + timedelta(days=365))
        with self.assertRaises(RetentionConflict):
            assert_deletable("company", parcel__establishment__company=company)

    def test_conflict_is_409_and_names_the_date(self):
        until = timezone.now().date() + timedelta(days=365)
        _, _, parcel = self._tree(until)
        with self.assertRaises(RetentionConflict) as ctx:
            assert_deletable("parcel", parcel=parcel)
        self.assertEqual(ctx.exception.status_code, 409)
        detail = ctx.exception.detail
        self.assertEqual(str(detail["retention_until"]), until.isoformat())
        self.assertIn("205.103(b)(4)", str(detail["detail"]))
        self.assertIn("parcel", str(detail["detail"]))

    # --- outside retention / never finished: deletes proceed ----------------

    def test_expired_retention_does_not_block(self):
        """The guard is a retention floor, not a tombstone."""
        _, _, parcel = self._tree(timezone.now().date() - timedelta(days=1))
        assert_deletable("parcel", parcel=parcel)  # must not raise

    def test_null_retention_does_not_block(self):
        """Drafts never went through finish(), so they have no floor and must stay deletable."""
        company = Company.objects.create(name="Draft Co")
        est = Establishment.objects.create(name="Draft Farm", company=company)
        parcel = Parcel.objects.create(name="Draft Parcel", establishment=est, area=1)
        History.objects.create(parcel=parcel, name="Unfinished draft")
        assert_deletable("parcel", parcel=parcel)  # must not raise

    def test_empty_container_does_not_block(self):
        company = Company.objects.create(name="Empty Co")
        est = Establishment.objects.create(name="Empty Farm", company=company)
        parcel = Parcel.objects.create(name="Empty Parcel", establishment=est, area=1)
        assert_deletable("parcel", parcel=parcel)  # must not raise

    def test_singular_wording_for_one_record(self):
        """Farmer-facing copy: '1 finished production ... would erase it', not 'productions ... them'."""
        _, _, parcel = self._tree(timezone.now().date() + timedelta(days=365))
        with self.assertRaises(RetentionConflict) as ctx:
            assert_deletable("parcel", parcel=parcel)
        detail = str(ctx.exception.detail["detail"])
        self.assertIn("1 finished production ", detail)
        self.assertNotIn("productions", detail)
