"""Block identifier normalisation and the per-parcel vocabulary.

`block_id` is free text on all 8 event types and is emitted as CA PUR box 22, folded into the
audit export, and is where a COG Pro migration lands "Row/Section ID". Without normalisation,
"Block 3", "block 3 " and "Block  3" are three different blocks to every query that groups by
them — and a certifier asking "what happened in Block 3" silently receives a subset.
"""

from django.test import TestCase

from history.services.block_ids import blocks_match, known_block_ids_for_parcel, normalize_block_id


class NormalizeBlockIdTests(TestCase):
    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(normalize_block_id("  Block 3  "), "Block 3")

    def test_internal_whitespace_runs_collapse(self):
        self.assertEqual(normalize_block_id("Block   3"), "Block 3")
        self.assertEqual(normalize_block_id("Block\t3"), "Block 3")
        self.assertEqual(normalize_block_id("Block\n3"), "Block 3")

    def test_non_breaking_space_is_handled(self):
        # Phone keyboards emit U+00A0. It looks identical to a space on screen, so without this
        # a grower could stare at two rows that are visibly the same and query-wise different.
        self.assertEqual(normalize_block_id("Block 3 "), "Block 3")
        self.assertEqual(normalize_block_id("Block 3"), "Block 3")

    def test_empty_values_become_none_not_empty_string(self):
        # Otherwise "no block" has two spellings in the column.
        for value in ("", "   ", "\t", None):
            with self.subTest(value=value):
                self.assertIsNone(normalize_block_id(value))

    def test_the_growers_own_wording_is_preserved(self):
        # Deliberately conservative. "Block 3" is NOT rewritten to "3" or "BLOCK 3": the farmer's
        # label is what they look for during an inspection, and rewriting it would make the
        # record disagree with the map on their wall.
        for value in ("Block 3", "Hillside Grove A", "B-7", "North Orchard"):
            with self.subTest(value=value):
                self.assertEqual(normalize_block_id(value), value)

    def test_numbers_are_accepted(self):
        self.assertEqual(normalize_block_id(3), "3")


class BlocksMatchTests(TestCase):
    def test_case_and_spacing_differences_still_match(self):
        self.assertTrue(blocks_match("Block 3", " block  3 "))
        self.assertTrue(blocks_match("HILLSIDE GROVE A", "Hillside Grove A"))

    def test_genuinely_different_blocks_do_not_match(self):
        self.assertFalse(blocks_match("Block 3", "Block 4"))

    def test_absent_never_matches_absent(self):
        # "Neither record states a block" is not evidence they are the same block.
        self.assertFalse(blocks_match(None, None))
        self.assertFalse(blocks_match("", "  "))
        self.assertFalse(blocks_match("Block 3", None))


class NormalizationOnSaveTests(TestCase):
    """The pre_save signal must cover every event type, not just the ones with a form input."""

    def _make_history(self):
        from company.models import Company, Establishment
        from history.models import History
        from product.models import Parcel

        company = Company.objects.create(name="Orchard Co")
        establishment = Establishment.objects.create(name="Home Ranch", company=company, country="US", state="CA")
        parcel = Parcel.objects.create(name="North", establishment=establishment, area=10.0)
        return History.objects.create(parcel=parcel, name="2026 Season"), parcel

    def test_every_event_type_normalizes_on_save(self):
        from django.utils import timezone

        from history.models import (
            BusinessEvent,
            ChemicalEvent,
            EquipmentEvent,
            GeneralEvent,
            PestManagementEvent,
            ProductionEvent,
            SoilManagementEvent,
            WeatherEvent,
        )

        history, _ = self._make_history()
        models = [
            ChemicalEvent,
            ProductionEvent,
            SoilManagementEvent,
            PestManagementEvent,
            GeneralEvent,
            WeatherEvent,
            BusinessEvent,
            EquipmentEvent,
        ]
        for model in models:
            with self.subTest(model=model.__name__):
                event = model.objects.create(
                    history=history,
                    description="x",
                    date=timezone.now(),
                    block_id="  Block   3 ",
                )
                event.refresh_from_db()
                self.assertEqual(event.block_id, "Block 3")

    def test_blank_block_id_is_stored_as_null(self):
        from django.utils import timezone

        from history.models import ChemicalEvent

        history, _ = self._make_history()
        event = ChemicalEvent.objects.create(history=history, description="x", date=timezone.now(), block_id="   ")
        event.refresh_from_db()
        self.assertIsNone(event.block_id)


class KnownBlockIdsForParcelTests(TestCase):
    """The vocabulary the autocomplete offers."""

    def setUp(self):
        from company.models import Company, Establishment
        from history.models import History
        from product.models import Parcel

        company = Company.objects.create(name="Orchard Co")
        establishment = Establishment.objects.create(name="Home Ranch", company=company, country="US", state="CA")
        self.parcel = Parcel.objects.create(name="North", establishment=establishment, area=10.0)
        self.other_parcel = Parcel.objects.create(name="South", establishment=establishment, area=8.0)
        self.history = History.objects.create(parcel=self.parcel, name="2026")
        self.other_history = History.objects.create(parcel=self.other_parcel, name="2026")

    def _add(self, block_id, history=None, model=None):
        from django.utils import timezone

        from history.models import ChemicalEvent

        (model or ChemicalEvent).objects.create(
            history=history or self.history,
            description="x",
            date=timezone.now(),
            block_id=block_id,
        )

    def test_empty_parcel_offers_nothing(self):
        self.assertEqual(known_block_ids_for_parcel(self.parcel), [])

    def test_none_parcel_is_tolerated(self):
        self.assertEqual(known_block_ids_for_parcel(None), [])

    def test_distinct_blocks_are_collected(self):
        self._add("Block 3")
        self._add("Block 1")
        self.assertEqual(known_block_ids_for_parcel(self.parcel), ["Block 1", "Block 3"])

    def test_case_variants_collapse_to_one_entry(self):
        # The whole point: the grower must be offered ONE "Block 3" to pick, not three.
        self._add("Block 3")
        self._add("block 3")
        self._add("BLOCK 3")
        self.assertEqual(len(known_block_ids_for_parcel(self.parcel)), 1)

    def test_the_most_used_spelling_wins(self):
        # A block written "Block 3" repeatedly and "BLOCK 3" once by accident should be offered
        # back as "Block 3" — the grower's actual convention, not their typo.
        for _ in range(3):
            self._add("Block 3")
        self._add("BLOCK 3")
        self.assertEqual(known_block_ids_for_parcel(self.parcel), ["Block 3"])

    def test_the_winning_spelling_is_deterministic_on_a_tie(self):
        # Regression: an earlier version kept "the first spelling seen", but `.distinct()` has no
        # ORDER BY, so the winner depended on Postgres row order and could differ between calls.
        self._add("Block 3")
        self._add("BLOCK 3")
        first = known_block_ids_for_parcel(self.parcel)
        for _ in range(4):
            self.assertEqual(known_block_ids_for_parcel(self.parcel), first)

    def test_blocks_from_other_parcels_are_not_offered(self):
        # Offering another parcel's blocks would invite recording a spray against a block that
        # is not in the field being treated.
        self._add("Block 3")
        self._add("South Block 9", history=self.other_history)
        self.assertEqual(known_block_ids_for_parcel(self.parcel), ["Block 3"])

    def test_blocks_are_gathered_across_all_event_types(self):
        from history.models import ProductionEvent, SoilManagementEvent

        self._add("Block 3")
        self._add("Block 5", model=ProductionEvent)
        self._add("Block 1", model=SoilManagementEvent)
        self.assertEqual(known_block_ids_for_parcel(self.parcel), ["Block 1", "Block 3", "Block 5"])

    def test_sorting_is_case_insensitive(self):
        self._add("apple block")
        self._add("Block 1")
        self.assertEqual(known_block_ids_for_parcel(self.parcel), ["apple block", "Block 1"])

    def test_blank_and_null_are_excluded(self):
        self._add("Block 3")
        self._add("")
        self._add(None)
        self.assertEqual(known_block_ids_for_parcel(self.parcel), ["Block 3"])
