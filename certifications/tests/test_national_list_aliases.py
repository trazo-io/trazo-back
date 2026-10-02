"""The alias crosswalk must resolve real listings and must REFUSE ambiguous ones.

Importing a real organic walnut season (2026-08-07) cited only 12 of 40 inputs. Four misses were
substances that are both seeded and listed — "Sulfur" (seeded "Elemental sulfur"), "Pheromone
(codlemone)" ("Pheromones"), "Boron" ("Soluble boron products"), "Zinc sulfate" (the micronutrient
sulfates entry). Sulfur and pheromones are two of the commonest organic orchard inputs.

The tests here are deliberately weighted toward the DANGEROUS direction. A missed citation costs
value; a wrong one asserts that a substance is allowed under organic rules, for a use it may not
be allowed for, on a document a certifier reads.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from certifications.models import NationalListSubstance
from certifications.services.national_list_aliases import (
    ALIASES,
    AMBIGUOUS_NEVER_AUTO_RESOLVE,
    canonical_key,
    resolve_alias,
)


class AliasTableIntegrityTests(TestCase):
    """An alias pointing at a substance that is not seeded is a silent no-op."""

    @classmethod
    def setUpTestData(cls):
        # Seed the REAL list rather than hand-built rows. The whole risk this class guards is a
        # drift between the alias table and what `seed_national_list` actually produces, which a
        # fixture of invented rows would hide.
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())

    def test_every_alias_target_exists_in_the_seeded_list(self):
        seeded = set(NationalListSubstance.objects.values_list("substance_name", flat=True))
        self.assertTrue(seeded, "seed_national_list produced nothing")

        missing = sorted({target for target in ALIASES.values() if target not in seeded})
        self.assertEqual(
            missing,
            [],
            "aliases point at substances with no seeded row — they would silently never classify",
        )

    def test_alias_keys_survive_canonicalisation_unchanged(self):
        """A key that reduces to something else would be unreachable through the index."""
        for key in ALIASES:
            with self.subTest(alias=key):
                self.assertEqual(key, canonical_key(key), f"alias key {key!r} would never match")

    def test_no_alias_key_is_also_declared_ambiguous(self):
        """The two tables must not disagree about the same term."""
        overlap = sorted(set(ALIASES) & set(AMBIGUOUS_NEVER_AUTO_RESOLVE))
        self.assertEqual(overlap, [], "a term cannot be both auto-resolved and ambiguous")

    def test_each_alias_maps_to_exactly_one_substance(self):
        """One-to-one by construction — a dict cannot express otherwise, so assert the intent."""
        for term, target in ALIASES.items():
            with self.subTest(alias=term):
                self.assertIsInstance(target, str)
                self.assertTrue(target.strip())


class AmbiguousTermsAreRefusedTests(TestCase):
    """The listing itself is built to defeat fuzzy matching — these prove we do not try."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())

    def test_soap_is_not_resolved(self):
        """FOUR listings differing by use: algicide (a), herbicide (b), ammonium (d),
        insecticidal (e). Picking one cites the wrong subsection."""
        self.assertIsNone(resolve_alias("soap"))
        self.assertIsNone(resolve_alias("soaps"))

    def test_copper_sulfate_is_not_resolved(self):
        """Algicide (a), insecticide (e) and fungicide (i) are three separate listings."""
        self.assertIsNone(resolve_alias("copper sulfate"))
        self.assertIsNone(resolve_alias("copper"))

    def test_ambiguous_entries_really_are_ambiguous_in_the_seed(self):
        """Guards against the list being pruned until a 'never resolve' term became safe —
        at which point refusing it is merely unhelpful, and the entry should move."""
        seeded = set(NationalListSubstance.objects.values_list("substance_name", flat=True))
        self.assertTrue(seeded, "seed_national_list produced nothing")

        for term, targets in AMBIGUOUS_NEVER_AUTO_RESOLVE.items():
            present = [t for t in targets if t in seeded]
            with self.subTest(term=term):
                self.assertGreater(
                    len(present),
                    1,
                    f"{term!r} now resolves to {present} — no longer ambiguous, move it to ALIASES",
                )

    def test_an_unknown_term_returns_none_rather_than_a_guess(self):
        self.assertIsNone(resolve_alias("something the farmer invented"))
        self.assertIsNone(resolve_alias(""))
        self.assertIsNone(resolve_alias(None))


class AliasResolutionTests(TestCase):
    """The four real misses from the walnut import, plus the shorthand the guard blocked."""

    @classmethod
    def setUpTestData(cls):
        # Seeded because two tests below assert through the CLASSIFIER, not just the alias
        # table. `history/signals.py` health-checks the list first and returns early when it is
        # empty, so without this those assertions would report "unexpectedly None" for terms
        # that resolve perfectly well — a vacuous failure, which is the mirror of the vacuous
        # pass this file exists to prevent.
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())

    def test_the_four_misses_from_the_walnut_season_now_resolve(self):
        expected = {
            "sulfur": "Elemental sulfur",
            "boron": "Soluble boron products",
            "codlemone": "Pheromones",
            "pheromone": "Pheromones",
        }
        for term, target in expected.items():
            with self.subTest(term=term):
                self.assertEqual(resolve_alias(term), target)

    def test_zinc_sulfate_resolves_to_the_micronutrient_listing(self):
        resolved = resolve_alias("zinc sulfate")
        self.assertIsNotNone(resolved)
        self.assertIn("sulfates", resolved)
        self.assertNotEqual(resolved, "Polyoxin D zinc salt", "that is a fungicide, not a micronutrient")

    def test_bt_shorthand_resolves(self):
        """The full binomial reaches the classifier's reverse pass, but that pass requires >= 12
        characters and a space — so the shorthand every grower writes was blocked."""
        self.assertEqual(resolve_alias("bt"), "Microbial products (Bacillus thuringiensis, etc.)")

    def test_the_bt_SUBSPECIES_resolve_too(self):
        """🔴 2026-08-21, MEASURED. A bare "Bacillus thuringiensis" reached the classifier's
        reverse pass and resolved; **"Bacillus thuringiensis subsp. kurstaki" did not** — the
        reverse pass needs the operator's text to be a SUBSTRING of the listing, and the
        subspecies is not in it. So writing the organism PRECISELY, which is the correct way to
        name it and the only way to say whether it works on a caterpillar or a beetle, made the
        record LESS placeable than the vague form and printed "Self-reported" in the packet.

        The subspecies is agronomically load-bearing and regulatorily irrelevant: § 205.601's
        listing is the class, so every subspecies maps to the same row."""
        listing = "Microbial products (Bacillus thuringiensis, etc.)"
        terms = (
            "Bacillus thuringiensis subsp. kurstaki",
            "Bacillus thuringiensis var. kurstaki",
            "Bt kurstaki",
            "Bacillus thuringiensis subsp. tenebrionis",
            "Bt tenebrionis",
            "Bacillus thuringiensis subsp. aizawai",
            "Bti",
        )
        for term in terms:
            self.assertEqual(resolve_alias(term), listing, term)

        # And end to end through the classifier, on the field the grower actually fills. The
        # alias table is one of four passes; asserting only the table proves the entry exists,
        # not that a record reaches it.
        from history.models import ChemicalEvent
        from history.signals import auto_classify_chemical_against_national_list as classify

        for term in terms:
            event = ChemicalEvent(commercial_name="DiPel DF", extra_data={"active_ingredient": term})
            classify(ChemicalEvent, event)
            self.assertIsNotNone(event.national_list_substance, term)
            self.assertEqual(event.national_list_substance.substance_name, listing, term)

    def test_the_chemical_name_of_a_soap_is_never_auto_resolved(self):
        """Potassium salts of fatty acids are the active in M-Pede (an insecticidal soap) AND in
        the soap-based herbicides listed under a different subsection. Resolving it would pick a
        § citation for the operator based on a use only they know — the same reason bare "soap"
        and bare "copper" are in this table."""
        self.assertIsNone(resolve_alias("potassium salts of fatty acids"))
        self.assertIn("potassium salts of fatty acids", AMBIGUOUS_NEVER_AUTO_RESOLVE)

        # …while the name that DOES pick a subsection still places, asserted through the
        # CLASSIFIER rather than through `resolve_alias`. The crosswalk is one of four passes
        # (exact → alias → forward substring → reverse substring), and "insecticidal soap"
        # resolves on the LAST of them because it is a substring of the listing's plural. A
        # test at the alias layer would report a miss for a term the product places correctly —
        # which is exactly the wrong-layer mistake this file's own header warns about.
        from history.models import ChemicalEvent
        from history.signals import auto_classify_chemical_against_national_list as classify

        event = ChemicalEvent(commercial_name="M-Pede", extra_data={"active_ingredient": "Insecticidal soap"})
        classify(ChemicalEvent, event)
        # Phase 5 slice 1: reached by a substring pass, so it is a suggestion, not a classification.
        self.assertIsNone(event.national_list_substance)
        self.assertEqual(event.national_list_suggestion.substance_name, "Insecticidal soaps")

    def test_pheromone_traps_are_not_confused_with_applied_pheromones(self):
        """ "Pheromone traps" is a separate listing — a monitoring device, not an application."""
        self.assertEqual(resolve_alias("pheromone"), "Pheromones")
        self.assertNotEqual(resolve_alias("pheromone"), "Pheromone traps")

    def test_lime_sulfur_is_not_swallowed_by_the_sulfur_alias(self):
        """A distinct listing; growers write it in full and it must not become elemental sulfur."""
        self.assertIsNone(resolve_alias("lime sulfur"))


class RawFarmerStringsResolveTests(TestCase):
    """Resolution must work on what the farmer actually typed, not on a tidied key.

    🔴 The parenthesis gap. `omri_verifier._normalize` only lowercases, so the real COG Pro value
    "Pheromone (codlemone)" reduced to "pheromone (codlemone)" and missed a table written in plain
    words — while a test that only checked ALIAS KEYS passed, because the keys were fine. The
    defect was in the space between the farmer's string and the key.
    """

    def test_the_exact_strings_from_the_walnut_season_resolve(self):
        cases = {
            "Sulfur": "Elemental sulfur",
            "Boron": "Soluble boron products",
            "Pheromone (codlemone)": "Pheromones",
            "Zinc sulfate": "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt "
            "(sulfates, carbonates, oxides, silicates)",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(resolve_alias(raw), expected)

    def test_bracketed_active_ingredient_forms_resolve(self):
        """Growers and COG Pro both write the ingredient in brackets."""
        for raw in ("Pheromone (Codlemone)", "PHEROMONE (CODLEMONE)", "  Pheromone  (codlemone) "):
            with self.subTest(raw=raw):
                self.assertEqual(resolve_alias(raw), "Pheromones")

    def test_punctuation_stripping_does_not_create_a_false_match(self):
        """Reducing punctuation must never turn an ambiguous term into a confident one."""
        for raw in ("Copper sulfate (algicide)", "Copper sulfate (fungicide)", "Insecticidal soap"):
            with self.subTest(raw=raw):
                self.assertIsNone(resolve_alias(raw))

    def test_canonical_key_is_stable_and_lossless_enough(self):
        self.assertEqual(canonical_key("Pheromone (codlemone)"), "pheromone codlemone")
        self.assertEqual(canonical_key("Zinc-sulfate"), "zinc sulfate")
        self.assertEqual(canonical_key(None), "")
