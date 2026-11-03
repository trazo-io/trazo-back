"""The National List seed writes one row per listing, and never two entries onto the same row.

`NationalListSubstance` is unique on (substance_name_normalized, cfr_section), and the seeder writes
with update_or_create on exactly that key. Two seed entries with the same name in the same section
therefore land on ONE row, and the second silently overwrites the first. Hydrogen peroxide did this
for its two § 205.601 listings, (a) sanitizer and (i) plant disease control: the (a) row was
rewritten as (i) on every run, so every hydrogen peroxide citation printed § 205.601(i). It surfaced
only because the production seed reported "105 updated" over 104 rows (2026-11-02).

A substance with more than one listing in a section is seeded under use-qualified names instead
("Peracetic acid" / "Peracetic acid (fire blight)"), and the search returns every listing so the
grower picks the subsection that covers their use.
"""

from collections import Counter
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from certifications.management.commands import seed_national_list as seed
from certifications.models import NationalListSubstance
from certifications.services.national_list_aliases import resolve_alias
from certifications.services.omri_verifier import national_list_candidates_by_name


def _seed_keys():
    """(section, normalized name) for every entry, keyed the way the seeder's update_or_create is."""
    keys = []
    for _sub, _cat, name, _notes in seed.SECTION_601_ALLOWED:
        keys.append(("205.601", seed._normalize(name)))
    for _sub, _cat, name, _notes in seed.SECTION_602_PROHIBITED:
        keys.append(("205.602", seed._normalize(name)))
    for _cat, name, _notes in seed.SECTION_NONSYN_ALLOWED:
        keys.append((NationalListSubstance.NONSYNTHETIC, seed._normalize(name)))
    for _sub, _cat, name, _notes in seed.SECTION_605_ALLOWED:
        keys.append(("205.605", seed._normalize(name)))
    for _sub, _cat, name, _notes in seed.SECTION_105_PROHIBITED:
        keys.append(("205.105", seed._normalize(name)))
    return keys


class SeedKeysAreUniqueTests(SimpleTestCase):
    def test_no_two_entries_share_a_row(self):
        duplicates = {key: n for key, n in Counter(_seed_keys()).items() if n > 1}
        self.assertEqual(
            duplicates,
            {},
            "Two seed entries write the same (section, name) row, so the later one overwrites the "
            "earlier. Qualify the second listing by use, e.g. 'Peracetic acid (fire blight)'.",
        )


class SeededListingsTests(TestCase):
    def setUp(self):
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())

    def test_one_row_per_entry(self):
        self.assertEqual(NationalListSubstance.objects.count(), len(_seed_keys()))

    def test_hydrogen_peroxide_keeps_both_205_601_listings(self):
        rows = {
            row.substance_name: (row.subsection, row.category)
            for row in NationalListSubstance.objects.filter(
                cfr_section="205.601", substance_name__startswith="Hydrogen peroxide"
            )
        }
        self.assertEqual(
            rows,
            {
                "Hydrogen peroxide": ("a", "sanitizer"),
                "Hydrogen peroxide (disease control)": ("i", "disease_control"),
            },
        )

    def test_searching_the_name_offers_every_listing(self):
        found = {(r.cfr_section, r.subsection) for r in national_list_candidates_by_name("Hydrogen peroxide")}
        self.assertEqual(found, {("205.601", "a"), ("205.601", "i"), ("205.605", "b")})

    def test_the_qualified_sibling_of_peracetic_acid_is_offered_too(self):
        names = [r.substance_name for r in national_list_candidates_by_name("peracetic acid")]
        self.assertIn("Peracetic acid", names)
        self.assertIn("Peracetic acid (fire blight)", names)
        # The exact name stays first.
        self.assertEqual(names[0], "Peracetic acid")

    def test_written_forms_never_auto_resolve_to_one_listing(self):
        for term in ("hydrogen peroxide", "H2O2", "hydrogen dioxide"):
            self.assertIsNone(resolve_alias(term), term)


class SharedRowFromAnEarlierSeedTests(TestCase):
    """A database seeded before the split holds ONE hydrogen peroxide row, last written as (i).

    Records point at it by pk and have printed § 205.601(i). Re-seeding must keep that row as the
    (i) listing and create the (a) row new; upserting first would rewrite it as (a) and silently move
    every existing link to the sanitizer citation.
    """

    def test_the_shared_row_keeps_its_pk_and_its_citation(self):
        legacy = NationalListSubstance.objects.create(
            substance_name="Hydrogen peroxide",
            substance_name_normalized="hydrogen peroxide",
            cfr_section="205.601",
            subsection="i",
            category="disease_control",
            status="allowed",
        )
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())

        legacy.refresh_from_db()
        self.assertEqual(legacy.substance_name, "Hydrogen peroxide (disease control)")
        self.assertEqual(legacy.subsection, "i")
        sanitizer = NationalListSubstance.objects.get(cfr_section="205.601", substance_name="Hydrogen peroxide")
        self.assertNotEqual(sanitizer.pk, legacy.pk)
        self.assertEqual((sanitizer.subsection, sanitizer.category), ("a", "sanitizer"))

        # Idempotent: a second run renames nothing and adds nothing.
        before = NationalListSubstance.objects.count()
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(NationalListSubstance.objects.count(), before)
        legacy.refresh_from_db()
        self.assertEqual(legacy.substance_name, "Hydrogen peroxide (disease control)")
