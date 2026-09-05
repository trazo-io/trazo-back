"""A fuzzy name match may not be presented as THE answer when several products fit.

`_resolve_omri_by_name` returns one row, which is right for search and for the drift
detector. It became dangerous the day the UI grew a one-tap "Use this listing" that writes
`ChemicalEvent.omri_product`: the FK is what earns a bare "OMRI Listed" on the certifier
dossier and on the buyer page, so attaching the wrong row publishes a third-party listing
claim for a product the operation never applied.

`consumer-omri-listing-leak-2026-08-09` names this exact pair as the reason never to
auto-populate: "Neptune's Harvest 2-3-1" resolves to "Fish Fertilizer 2-4-1". Both are real
catalog rows. This pins the plural answer so the UI can make the grower choose.
"""

from django.test import TestCase

from certifications.models import OMRIProduct
from certifications.services.omri_verifier import _omri_candidates_by_name, _resolve_omri_by_name


class OMRICandidateAmbiguityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fish_241 = OMRIProduct.objects.create(
            omri_id="nhf-0644",
            product_name="Neptune's Harvest Organic Fish Fertilizer 2-4-1",
            manufacturer="Ocean Crest Seafoods",
            category="crop-fertilizer",
        )
        cls.seaweed_231 = OMRIProduct.objects.create(
            omri_id="nhf-3041",
            product_name="Neptune's Harvest Organic Fish and Seaweed Fertilizer 2-3-1",
            manufacturer="Ocean Crest Seafoods",
            category="crop-fertilizer",
        )
        cls.seaweed_2305 = OMRIProduct.objects.create(
            omri_id="nhf-6230",
            product_name="Neptune's Harvest Organic Fish and Seaweed Fertilizer 2-3-0.5",
            manufacturer="Ocean Crest Seafoods",
            category="crop-fertilizer",
        )
        cls.entrust = OMRIProduct.objects.create(
            omri_id="dow-2900",
            product_name="Entrust SC Naturalyte Insect Control",
            manufacturer="Dow Agrosciences LLC",
            category="crop-pest-control",
        )

    def test_a_brand_only_query_is_ambiguous_and_returns_every_match(self):
        candidates = _omri_candidates_by_name("Neptune")
        self.assertGreater(
            len(candidates),
            1,
            "a brand-only query must not collapse to one product — the UI has to offer a choice",
        )
        names = {c.product_name for c in candidates}
        self.assertIn(self.fish_241.product_name, names)
        self.assertIn(self.seaweed_231.product_name, names)

    def test_the_single_resolver_would_have_picked_the_wrong_product(self):
        """The documented failure, pinned so the shortlist's reason for existing stays visible."""
        picked = _resolve_omri_by_name("Neptune")
        self.assertIsNotNone(picked)
        self.assertNotEqual(
            picked.pk,
            self.seaweed_231.pk,
            "if this ever starts picking 2-3-1 the tiebreaker changed; the shortlist is still "
            "required, because 'which Neptune product' is not answerable from the query alone",
        )

    def test_a_full_product_name_is_unambiguous(self):
        candidates = _omri_candidates_by_name("Neptune's Harvest Organic Fish and Seaweed Fertilizer 2-3-1")
        self.assertEqual([c.pk for c in candidates], [self.seaweed_231.pk])

    def test_an_exact_match_is_never_offered_alternatives(self):
        candidates = _omri_candidates_by_name("Entrust SC Naturalyte Insect Control")
        self.assertEqual([c.pk for c in candidates], [self.entrust.pk])

    def test_a_confident_partial_stays_unambiguous(self):
        """ "Entrust SC" is a prefix of exactly one catalog row — no chooser needed."""
        self.assertEqual([c.pk for c in _omri_candidates_by_name("Entrust SC")], [self.entrust.pk])

    def test_no_match_returns_empty_rather_than_a_guess(self):
        self.assertEqual(_omri_candidates_by_name("Glyphosate 41"), [])
        self.assertEqual(_omri_candidates_by_name("   "), [])

    def test_the_shortlist_is_ranked_like_the_single_resolver(self):
        """One ranking, two shapes. `_resolve_omri_by_name` delegates here rather than holding
        its own copy of the scoring loop — two copies of a tiebreaker drift, and the day they
        disagreed the chooser's top row would not be the row the drift detector resolves to."""
        for query in ("Neptune", "Neptune's Harvest Organic Fish", "Entrust", "Entrust SC"):
            with self.subTest(query=query):
                self.assertEqual(
                    _omri_candidates_by_name(query)[0].pk,
                    _resolve_omri_by_name(query).pk,
                )

    def test_the_shortlist_is_never_silently_truncated(self):
        """It carried `limit=6`, which dropped the 7th Neptune row and — worse — made the
        caller's len() a truncated number the UI printed as a total ("6 products match" when 7
        did). Capping is now the caller's job, and the caller reports the real count."""
        for extra in range(4):
            OMRIProduct.objects.create(
                omri_id=f"nhf-pad-{extra}",
                product_name=f"Neptune's Harvest Padding Product {extra}",
                category="crop-fertilizer",
            )
        total = OMRIProduct.objects.filter(product_name__istartswith="Neptune").count()
        self.assertGreater(total, 6, "fixture must exceed the old cap for this to mean anything")
        self.assertEqual(len(_omri_candidates_by_name("Neptune")), total)
