"""Seals: version 2 is deterministic; version 1 is checked honestly and never rewritten (2026-11-05).

The production finding these pin: a Calapooia season resealed at 00:28:37 (65 events sharing one
`index`) failed its own v1 check minutes later with nothing changed, because v1 sorts by `index`
only and Postgres returns tied rows in no fixed order. On the QR page that read as `tampered`.
"""

from unittest import mock

from django.db import connection, transaction
from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history import seals
from history.models import ChemicalEvent, GeneralEvent, Production
from product.models import Parcel


class _Season(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Seal Co")
        est = Establishment.objects.create(name="Seal Farm", company=company)
        self.parcel = Parcel.objects.create(name="North", establishment=est, area=1)
        self.history = Production.objects.create(parcel=self.parcel, name="2026")

    def _events(self, n=3, index=None):
        out = []
        for i in range(n):
            out.append(
                GeneralEvent.objects.create(
                    history=self.history,
                    name=f"g{i}",
                    description=f"general {i}",
                    date=timezone.now(),
                    index=i + 1 if index is None else index,
                )
            )
        out.append(
            ChemicalEvent.objects.create(
                history=self.history,
                type=ChemicalEvent.FERTILIZER,
                commercial_name="Fish",
                description="chemical",
                date=timezone.now(),
                index=n + 1 if index is None else index,
            )
        )
        return out

    def _store(self, digest, version=None):
        extra = {"finalization_hash": digest, "finalization_event_count": 4}
        if version is not None:
            extra["finalization_hash_version"] = version
        Production.objects.filter(pk=self.history.pk).update(extra_data=extra)
        self.history.refresh_from_db()


class VersionTwoTests(_Season):
    def test_seal_records_its_version_and_algorithm_and_verifies(self):
        self._events()
        fields = seals.seal(self.history)
        self.history.refresh_from_db()
        self.assertEqual(self.history.extra_data["finalization_hash_version"], seals.V2)
        self.assertEqual(self.history.extra_data["finalization_hash_algorithm"], "sha256")
        self.assertEqual(self.history.extra_data["finalization_hash"], fields["finalization_hash"])
        self.assertEqual(seals.verify(self.history).status, seals.INTACT)

    def test_the_hash_does_not_depend_on_the_order_the_database_returns_ties_in(self):
        """All events on one index, as on the 65-event Calapooia season."""
        self._events(n=5, index=0)
        digest, _ = seals.v2_hash(self.history)

        real_model = seals._model

        class Reversed:
            def __init__(self, model):
                self.objects = self
                self._model = model

            def filter(self, **kwargs):
                self._qs = self._model.objects.filter(**kwargs)
                return self

            def values(self, *fields):
                return list(reversed(list(self._qs.values(*fields))))

        with mock.patch.object(seals, "_model", lambda name: Reversed(real_model(name))):
            reversed_digest, _ = seals.v2_hash(self.history)
        self.assertEqual(reversed_digest, digest)

    def test_a_changed_record_is_a_mismatch(self):
        events = self._events()
        seals.seal(self.history)
        self.history.refresh_from_db()
        GeneralEvent.objects.filter(pk=events[0].pk).update(description="changed after sealing")
        self.assertEqual(seals.verify(self.history).status, seals.MISMATCH)

    def test_the_bytes_name_kinds_not_classes(self):
        """A model rename must not change a v2 seal."""
        self._events(n=1)
        rows = seals.v2_rows(self.history)
        self.assertEqual({r["kind"] for r in rows}, {"general", "chemical"})
        self.assertNotIn("event_type", rows[0])


class VersionOneTests(_Season):
    def test_an_existing_v1_seal_still_verifies(self):
        self._events()
        self._store(self.history.compute_finalization_hash()[0])  # no version key: v1
        check = seals.verify(self.history)
        self.assertEqual((check.status, check.version), (seals.INTACT, seals.V1))

    def test_a_v1_seal_taken_in_another_tie_order_verifies(self):
        self._events(n=2, index=1)
        rows = seals.v1_rows(self.history)
        other = list(reversed(rows))
        sha, keccak = seals._v1_digests(other)
        if (keccak or sha) == self.history.compute_finalization_hash()[0]:
            self.skipTest("both orders hash the same")
        self._store(keccak or sha)
        self.assertEqual(seals.verify(self.history).status, seals.INTACT)

    def test_a_small_tie_searched_exhaustively_that_matches_nothing_is_a_mismatch(self):
        """Review of back #298: every order of 3 tied rows (6) was tried, so order was not the
        cause and the content changed."""
        self._events(n=2, index=1)
        self._store("0" * 64)
        self.assertEqual(seals.verify(self.history).status, seals.MISMATCH)

    def test_an_unreproducible_v1_seal_with_a_wide_tie_is_inconclusive_not_tampered(self):
        """8 rows on one index: 40,320 orders, beyond MAX_TIE_ORDERS, so only the likely
        seal-time orders are tried and a non-match cannot prove a change."""
        self._events(n=7, index=1)
        self._store("0" * 64)
        check = seals.verify(self.history)
        self.assertEqual(check.status, seals.INCONCLUSIVE)
        self.assertIn("cannot be re-checked exactly", check.detail)

    def test_an_unreproducible_v1_seal_without_ties_is_a_mismatch(self):
        self._events()
        self._store("0" * 64)
        self.assertEqual(seals.verify(self.history).status, seals.MISMATCH)

    def test_verify_never_writes_and_keeps_a_v1_seal(self):
        self._events()
        stored = self.history.compute_finalization_hash()[0]
        self._store(stored)
        seals.verify(self.history)
        self.history.refresh_from_db()
        self.assertEqual(self.history.extra_data["finalization_hash"], stored)
        self.assertNotIn("finalization_hash_version", self.history.extra_data)


class VerifyIsSafeInsideATransactionTests(_Season):
    def test_a_database_error_is_an_error_status_and_the_outer_transaction_survives(self):
        self._events()
        self._store("0" * 64)

        def broken(history):
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM table_that_does_not_exist")

        with transaction.atomic():
            with mock.patch.object(seals, "v1_rows", broken):
                check = seals.verify(self.history)
            self.assertEqual(check.status, seals.ERROR)
            self.assertEqual(Production.objects.filter(pk=self.history.pk).count(), 1)  # still usable


class VerifyEndpointTests(_Season):
    def _integrity(self):
        Production.objects.filter(pk=self.history.pk).update(published=True)
        res = self.client.get(f"/api/transparency/{self.history.public_id}/verify-blockchain/")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()["data"]["data_integrity"] if "data" in res.json() else res.json()["data_integrity"]

    def test_an_inconclusive_v1_seal_is_not_reported_as_tampered(self):
        self._events(n=7, index=1)
        self._store("0" * 64)
        self.assertEqual(self._integrity(), "inconclusive")

    def _submitted(self, recomputed_matches):
        """A v1 seal with a wide tie, also submitted to the blockchain (review of back #298)."""
        self._events(n=7, index=1)
        Production.objects.filter(pk=self.history.pk).update(
            extra_data={
                "finalization_hash": "0" * 64,
                "finalization_event_count": 8,
                "blockchain_tx_hash": "0xabc",
                "blockchain_verified": True,
                "blockchain_data_hash": "chainhash",
            }
        )
        recomputed = "chainhash" if recomputed_matches else "drifted-after-a-carbon-recalculation"
        return (
            mock.patch(
                "carbon.services.blockchain.BlockchainCarbonService.read_on_chain_record",
                return_value={"data_hash": "chainhash"},
            ),
            mock.patch("history.transparency_views._recompute_production_data_hash", return_value=recomputed),
        )

    def test_a_submitted_inconclusive_seal_whose_data_hash_drifted_is_not_tampered(self):
        chain, recompute = self._submitted(recomputed_matches=False)
        with chain, recompute:
            self.assertEqual(self._integrity(), "inconclusive")

    def test_a_verified_layer_two_cannot_make_unchecked_events_intact(self):
        chain, recompute = self._submitted(recomputed_matches=True)
        with chain, recompute:
            self.assertEqual(self._integrity(), "inconclusive")

    def test_a_changed_v2_record_is_reported_as_tampered(self):
        events = self._events()
        seals.seal(self.history)
        GeneralEvent.objects.filter(pk=events[0].pk).update(description="changed")
        self.assertEqual(self._integrity(), "tampered")

    def test_an_intact_v2_record_is_reported_intact(self):
        self._events()
        seals.seal(self.history)
        self.assertEqual(self._integrity(), "intact")


class FinishingSealsWithTheCurrentVersionTests(_Season):
    def test_store_finalization_hash_writes_version_two(self):
        from product.views import ParcelViewSet

        self._events()
        ParcelViewSet()._store_finalization_hash(self.history)
        self.history.refresh_from_db()
        self.assertEqual(self.history.extra_data["finalization_hash_version"], seals.V2)
        self.assertEqual(seals.verify(self.history).status, seals.INTACT)
