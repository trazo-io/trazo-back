"""The 0-100 transparency score is not served, not written, and not calculable.

`transparency-first.md` retired the score AS A CONCEPT on 2026-09-08: no weights, no 0-100,
and explicitly never "a silent backend KPI". Policy landed that day; the code did not. Until
2026-09-30 `History.transparency_score` was still:

  * declared on `OptimizedHistoryListSerializer` (the producer season list) and on
    `PublicHistorySerializer`, where a non-owner strip hid it from shoppers and handed it to
    the farmer under the "producer-dashboard KPI" justification the policy names as the thing
    that kept the artefact alive;
  * recalculated and written on EVERY event create, edit and delete, through
    `History.update_trust_metrics()`;
  * seeded as a literal "99.7%" string inside `History.extra_data`, which the producer list
    serializer passes through verbatim, so no field-level removal would have caught it.

This module is the guard. It walks the real serializer output rather than reading source text,
because a field can reach a payload through `extra_data`, a `SerializerMethodField` or a nested
event dict without the name ever appearing in a `fields` list.

NEVER read this file's green as "the score is gone everywhere". It covers the two serializers
that carried it and the model write path. `carbon.ConsumerTrustMetric` still declares five
0-100 columns (no writer anywhere) and `History.transparency_score` is still a column pending
its own migration.
"""

import inspect
import io
import re
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIRequestFactory

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.serializers import OptimizedHistoryListSerializer, PublicHistorySerializer
from history.services.transparency_calculator import TransparencyCalculator
from product.models import Parcel, Product
from users.models import User, WorksIn

#: Every spelling of the retired grade. `transparency_percentage` is the calculator's internal
#: name for the same number and `transparency_tier` was its farm-level label, so a payload that
#: carries either has reintroduced the score under a different key.
FORBIDDEN_KEYS = frozenset(
    {
        "transparency_score",
        "transparency_percentage",
        "transparency_tier",
    }
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def walk(node, path="$"):
    """Yield (path, key, value) for every key AND every scalar in a nested structure.

    Scalars inside lists are yielded with their index in the path. A walker that only
    descended dicts missed exactly that case in `test_live_carbon_payloads_carry_no_grade`
    and had to be fixed after review, so this one is tested against a planted list below.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield (path, str(key), value)
            yield from walk(value, "%s.%s" % (path, key))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from walk(value, "%s[%d]" % (path, index))
            if not isinstance(value, (dict, list, tuple)):
                yield ("%s[%d]" % (path, index), "", value)


def forbidden_hits(payload):
    return ["%s -> %s = %r" % (path, key, value) for path, key, value in walk(payload) if key in FORBIDDEN_KEYS]


def strip_python_comments(source):
    """Drop `#` comments so a scan matches CODE, not prose about the code.

    A guard that reads raw source matches its own explanatory comment and passes for the
    wrong reason. Crude on a `#` inside a string literal, which is acceptable for a
    key-presence scan and is why the scan below also proves it still fires on a real write.
    """
    return "\n".join(re.sub(r"#.*$", "", line) for line in source.splitlines())


class _SeasonFixture(TestCase):
    """One published season with one event, owned by a company admin."""

    def setUp(self):
        self.owner = User.objects.create_user(email="owner@score.test", password="x")
        self.stranger = User.objects.create_user(email="stranger@score.test", password="x")
        self.company = Company.objects.create(name="Score Retirement Farm")
        WorksIn.objects.create(user=self.owner, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="SR1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="SRP1", establishment=self.establishment, area=4.0)
        self.product = Product.objects.create(name="Walnut")
        self.history = History.objects.create(
            name="Score Retirement Season",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.owner,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            is_outdoor=True,
            published=True,
        )
        ProductionEvent.objects.create(
            history=self.history,
            type=ProductionEvent.IRRIGATION,
            date=timezone.now(),
        )
        self.factory = APIRequestFactory()

    def _request(self, user=None):
        request = self.factory.get("/")
        request.user = user
        return request


class TheProducerSeasonListCarriesNoScore(_SeasonFixture):
    """The producer's own payload. This is the half the retired "KPI" framing protected."""

    def test_owner_payload_has_no_score(self):
        data = OptimizedHistoryListSerializer(self.history, context={"request": self._request(self.owner)}).data
        hits = forbidden_hits(data)
        self.assertEqual(
            hits,
            [],
            "the producer season list must carry no transparency grade; found: %s" % hits,
        )

    def test_extra_data_cannot_smuggle_a_score(self):
        """`extra_data` is served verbatim, so a key written there IS a served claim.

        The demo seeder wrote "transparency_score": "99.7%" here. This asserts the guard
        notices, which is the point: there is no allow-list on `extra_data`, so the
        protection is that nothing writes a grade into it (see the seeder scan below),
        not that the serializer filters one out.
        """
        self.history.extra_data = {"transparency_score": "99.7%"}
        self.history.save(update_fields=["extra_data"])
        data = OptimizedHistoryListSerializer(self.history, context={"request": self._request(self.owner)}).data
        self.assertNotEqual(
            forbidden_hits(data),
            [],
            "a score planted in extra_data reached the payload unnoticed, so this guard "
            "cannot see the extra_data route at all",
        )


class TheConsumerPayloadCarriesNoScore(_SeasonFixture):
    def test_anonymous_payload_has_no_score(self):
        data = PublicHistorySerializer(self.history, context={"request": self._request(None)}).data
        hits = forbidden_hits(data)
        self.assertEqual(hits, [], "anonymous consumer payload carries a grade: %s" % hits)

    def test_owner_payload_has_no_score_either(self):
        """The owner used to receive it. A strip that fires for one audience is not a removal."""
        data = PublicHistorySerializer(self.history, context={"request": self._request(self.owner)}).data
        hits = forbidden_hits(data)
        self.assertEqual(hits, [], "owner consumer payload carries a grade: %s" % hits)

    def test_non_owner_member_payload_has_no_score(self):
        data = PublicHistorySerializer(self.history, context={"request": self._request(self.stranger)}).data
        hits = forbidden_hits(data)
        self.assertEqual(hits, [], "signed-in stranger payload carries a grade: %s" % hits)

    def test_the_serializers_declare_no_strip_for_it(self):
        """`_SELF_GRADED_FIELDS` is gone, not emptied.

        An empty tuple still reads as "we strip the score", which is the framing the policy
        retired, and a no-op loop invites someone to add the field back and trust the strip.
        """
        self.assertFalse(
            hasattr(PublicHistorySerializer, "_SELF_GRADED_FIELDS"),
            "_SELF_GRADED_FIELDS is back; nothing is served that needs stripping",
        )


class TheWritePathIsGone(_SeasonFixture):
    def test_the_model_cannot_calculate_a_score(self):
        self.assertFalse(
            hasattr(History, "calculate_transparency_score"),
            "History.calculate_transparency_score is back; it was the write-path entry",
        )

    def test_update_trust_metrics_saves_only_confidence(self):
        with mock.patch.object(History, "save", autospec=True) as saved:
            self.history.update_trust_metrics()
        self.assertEqual(saved.call_count, 1)
        self.assertEqual(
            list(saved.call_args.kwargs.get("update_fields") or []),
            ["confidence_score"],
            "update_trust_metrics writes a field it should not",
        )

    def test_update_trust_metrics_body_mentions_no_score(self):
        body = strip_python_comments(inspect.getsource(History.update_trust_metrics))
        self.assertNotIn(
            "transparency_score",
            body.split('"""')[-1],
            "the method body assigns a transparency score again",
        )


class TheCalculatorExposesNoGrade(TestCase):
    """The calculator stays: the consumer QR endpoint reads it for FACTS. Its graders do not."""

    def test_the_three_graded_methods_are_absent(self):
        for name in ("get_transparency_insights", "_get_category_suggestion", "compare_with_own_history"):
            self.assertFalse(
                hasattr(TransparencyCalculator, name),
                "TransparencyCalculator.%s is back; all three returned a grade and had no callers" % name,
            )

    def test_the_facts_entry_point_survives(self):
        """Deleting the graders must not have taken the fact source with them."""
        self.assertTrue(hasattr(TransparencyCalculator, "calculate_transparency_score"))
        self.assertTrue(hasattr(TransparencyCalculator, "event_prefetch_lookups"))


class NoManagementCommandWritesAScore(TestCase):
    """A seeder is a claim surface when it writes into a field that is served verbatim."""

    KEY_WRITE = re.compile(r"""['"]transparency_(?:score|percentage|tier)['"]\s*:""")

    def _command_files(self):
        files = sorted(BACKEND_ROOT.glob("*/management/commands/*.py"))
        self.assertGreater(len(files), 20, "command glob found almost nothing; the path is wrong")
        return files

    def test_no_command_writes_a_score_key(self):
        offenders = []
        for path in self._command_files():
            body = strip_python_comments(io.open(path, encoding="utf-8").read())
            if self.KEY_WRITE.search(body):
                offenders.append(str(path.relative_to(BACKEND_ROOT)))
        self.assertEqual(
            offenders,
            [],
            "these commands write a transparency grade into data that is served: %s" % offenders,
        )

    def test_the_scan_sees_a_real_write(self):
        """Proves the comment stripping did not blind the scan."""
        self.assertTrue(self.KEY_WRITE.search('{"transparency_score": "99.7%"}'))
        self.assertTrue(self.KEY_WRITE.search("{'transparency_tier' : 'Excellent'}"))

    def test_the_scan_ignores_prose(self):
        self.assertFalse(self.KEY_WRITE.search(strip_python_comments('# "transparency_score": "99.7%",')))
        self.assertFalse(self.KEY_WRITE.search("NOTE: `transparency_score` was removed"))


class TheGuardCanActuallyFail(TestCase):
    """Every assertion above is negative. These prove the machinery detects a planted grade."""

    def test_top_level_key(self):
        self.assertNotEqual(forbidden_hits({"transparency_score": 88}), [])

    def test_nested_dict_key(self):
        self.assertNotEqual(forbidden_hits({"a": {"b": {"transparency_tier": "Excellent"}}}), [])

    def test_key_inside_a_list_of_dicts(self):
        payload = {"events": [{"id": 1}, {"transparency_percentage": 74.0}]}
        self.assertNotEqual(forbidden_hits(payload), [])

    def test_walk_descends_into_scalars_inside_lists(self):
        """The bug this walker was written to avoid: lists of scalars never visited."""
        seen = [value for _, key, value in walk({"tiers": ["Excellent", "Fair"]}) if key == ""]
        self.assertEqual(seen, ["Excellent", "Fair"])

    def test_a_clean_payload_passes(self):
        self.assertEqual(forbidden_hits({"events_count": 12, "photos": [{"url": "x"}]}), [])
