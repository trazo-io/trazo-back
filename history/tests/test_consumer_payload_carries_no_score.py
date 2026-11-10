"""No consumer payload may carry a self-graded score. Third time this has been true.

🔴 FOUND 2026-09-08. `history/serializers_consumer.py` served TWO self-graded 0-100 numbers to
signed-in consumers, on routes live at `backend/urls.py:85` → `history.urls_consumer`:

- `EnhancedHistoryScanSerializer.transparency_score` — per scanned product, used in real responses
  at `views_consumer.py:106` and `:201`.
- `UserImpactSummarySerializer.transparency_score_avg` — the average across the shopper's scans,
  used at `views_consumer.py:102`.

`get_transparency_score` was a **fourth independent formula** (10 events = 100, 7 = 85, 5 = 70,
3 = 50, ≥1 = 30, else 20 if any certificate exists), agreeing with none of the other three, and its
own docstring called it "transparency-first philosophy: more documented events = higher transparency
score" — a grower-incentive metric, shipped to shoppers.

**Why it survived three sweeps:** the views are `permission_classes = [IsAuthenticated]`, so it
never appeared in an anonymous-payload audit. `authenticated-consumer-score-leak-2026-08-06` is the
same incident, and its lesson is the one that matters here: **logging in does not make a claim
safe.** A signed-in shopper is still a shopper, and ECGT 2024/825 / FTC 16 CFR 260.4 do not have an
authentication exemption.

It was also unrendered — the frontend declares `transparency_score?: number` in two prop types and
displays it nowhere — which is exactly why nobody noticed. A number on the wire is published
whether or not a component draws it.

⛔ The replacement is not a quieter score. It is the factual counts already on these serializers:
`events_viewed`, `farming_events_viewed`, `verified_farms_scanned`.
"""

import inspect

from django.test import SimpleTestCase

from history import serializers_consumer as sc

#: Every serializer in the consumer module that reaches a shopper response.
CONSUMER_SERIALIZERS = (
    sc.EnhancedHistoryScanSerializer,
    sc.ConsumerImpactSerializer,  # was UserImpactSummarySerializer until 2026-11-10
)

#: Substrings that may never name a declared field on those serializers. Shape-matched, because
#: the next one will not be called `transparency_score` — the last three were called
#: `verification_level`, `trustScore` and `transparency_score_avg`.
FORBIDDEN_FIELD_SUBSTRINGS = ("score", "grade", "rating", "tier", "rank")


class ConsumerPayloadCarriesNoScoreTests(SimpleTestCase):
    def test_no_consumer_serializer_declares_a_score_field(self):
        offenders = []
        for serializer in CONSUMER_SERIALIZERS:
            declared = set(getattr(serializer, "_declared_fields", {}))
            meta_fields = set(getattr(getattr(serializer, "Meta", None), "fields", []) or [])
            for name in declared | meta_fields:
                if any(bad in name.lower() for bad in FORBIDDEN_FIELD_SUBSTRINGS):
                    offenders.append(f"{serializer.__name__}.{name}")
        self.assertEqual(
            offenders,
            [],
            "A consumer payload declares a self-graded field. Logging in does not make a claim "
            "safe — see this module's docstring. Serve a factual COUNT instead: "
            f"{offenders}",
        )

    def test_no_score_method_survives_on_those_serializers(self):
        # A `SerializerMethodField` removed from `fields` but left as a method is one edit away
        # from returning, and reads to the next person as though it is still contract.
        offenders = [
            f"{s.__name__}.{name}"
            for s in CONSUMER_SERIALIZERS
            for name, _ in inspect.getmembers(s, predicate=inspect.isfunction)
            if name.startswith("get_") and any(b in name.lower() for b in FORBIDDEN_FIELD_SUBSTRINGS)
        ]
        self.assertEqual(offenders, [], f"score-computing methods still present: {offenders}")

    def test_the_factual_replacements_are_still_served(self):
        """A negative assertion must prove it read something.

        If these counts vanished too, the tests above would pass on an empty payload and the guard
        would be measuring nothing.
        """
        scan_fields = set(sc.EnhancedHistoryScanSerializer.Meta.fields)
        self.assertIn("events_viewed", scan_fields)

        impact_fields = set(sc.ConsumerImpactSerializer._declared_fields)
        self.assertIn("farming_events_viewed", impact_fields)
        self.assertIn("verified_farms_scanned", impact_fields)

    def test_the_shared_event_count_cache_survived_the_removal(self):
        # `_get_event_counts` was shared between the deleted average and `farming_events_viewed`.
        # Deleting the caller must not have taken the cache with it, or the surviving factual
        # count goes N+1.
        self.assertTrue(hasattr(sc.ConsumerImpactSerializer, "_get_event_counts"))
