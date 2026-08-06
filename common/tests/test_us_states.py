"""Tests for canonical US state resolution.

The contract these lock down is "unknown resolves to None, never to a state" —
the regression that let a Florida farm be costed as Californian.
"""

from django.test import TestCase

from common.us_states import (
    US_STATE_CHOICES,
    US_STATE_NAMES,
    event_is_in_state,
    normalize_state,
    resolve_establishment_state,
    resolve_event_state,
)


class _Stub:
    """Minimal attribute holder — these helpers only read attributes."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class NormalizeStateTest(TestCase):
    def test_code_passthrough(self):
        self.assertEqual(normalize_state("CA"), "CA")

    def test_lowercase_code(self):
        self.assertEqual(normalize_state("ca"), "CA")

    def test_strips_whitespace(self):
        self.assertEqual(normalize_state("  fl  "), "FL")

    def test_full_name(self):
        self.assertEqual(normalize_state("California"), "CA")

    def test_lowercase_full_name(self):
        self.assertEqual(normalize_state("florida"), "FL")

    def test_multiword_full_name(self):
        self.assertEqual(normalize_state("New York"), "NY")

    def test_blank_is_none(self):
        self.assertIsNone(normalize_state(""))
        self.assertIsNone(normalize_state("   "))

    def test_none_is_none(self):
        self.assertIsNone(normalize_state(None))

    def test_unknown_is_none_not_california(self):
        # The whole point of this module.
        self.assertIsNone(normalize_state("Unknown State"))
        self.assertIsNone(normalize_state("XX"))

    def test_near_miss_does_not_guess(self):
        # "Baja California" is a Mexican state; prefix matching would map it to CA.
        self.assertIsNone(normalize_state("Baja California"))
        self.assertIsNone(normalize_state("Calif"))

    def test_territories_resolve(self):
        self.assertEqual(normalize_state("PR"), "PR")
        self.assertEqual(normalize_state("District of Columbia"), "DC")

    def test_all_fifty_states_round_trip(self):
        for code, name in US_STATE_NAMES.items():
            self.assertEqual(normalize_state(code), code)
            self.assertEqual(normalize_state(name), code)


class ChoicesTest(TestCase):
    def test_choices_cover_every_state(self):
        self.assertEqual(len(US_STATE_CHOICES), len(US_STATE_NAMES))

    def test_choices_sorted_by_display_name(self):
        names = [name for _, name in US_STATE_CHOICES]
        self.assertEqual(names, sorted(names))


class ResolveEstablishmentStateTest(TestCase):
    def test_reads_and_normalizes(self):
        self.assertEqual(resolve_establishment_state(_Stub(state="Florida")), "FL")

    def test_blank_state_is_none(self):
        self.assertIsNone(resolve_establishment_state(_Stub(state="")))

    def test_missing_attribute_is_none(self):
        self.assertIsNone(resolve_establishment_state(_Stub()))

    def test_none_establishment_is_none(self):
        self.assertIsNone(resolve_establishment_state(None))


class ResolveEventStateTest(TestCase):
    def _event(self, state):
        return _Stub(history=_Stub(parcel=_Stub(establishment=_Stub(state=state))))

    def test_walks_the_chain(self):
        self.assertEqual(resolve_event_state(self._event("CA")), "CA")

    def test_normalizes_full_name_on_the_walk(self):
        self.assertEqual(resolve_event_state(self._event("California")), "CA")

    def test_broken_chain_returns_none_rather_than_raising(self):
        self.assertIsNone(resolve_event_state(_Stub(history=_Stub(parcel=None))))
        self.assertIsNone(resolve_event_state(_Stub()))
        self.assertIsNone(resolve_event_state(None))

    def test_event_is_in_state(self):
        self.assertTrue(event_is_in_state(self._event("California"), "CA"))
        self.assertFalse(event_is_in_state(self._event("Florida"), "CA"))

    def test_unknown_state_is_not_in_california(self):
        # Guards the drift-detector gate: an unresolvable state must not be
        # treated as CA just because CA is the default everywhere else.
        self.assertFalse(event_is_in_state(self._event(""), "CA"))
        self.assertFalse(event_is_in_state(self._event("Baja California"), "CA"))
