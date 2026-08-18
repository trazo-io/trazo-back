"""`Parcel.agricultural_details` must never reach an anonymous consumer, by ANY path.

There are two independent public-parcel builders, and the 2026-08-07 fix only reached one:

  * carbon/views.py `complete_summary` — dropped the field inline, with a comment naming
    what is in it.
  * history/serializers.py `PublicParcelSerializer` — kept it. That serializer is nested as
    `PublicHistorySerializer.parcel`, and `HistoryViewSet.public_history` serves it under
    `permission_classes=[AllowAny]`. Scanning a QR code returned the whole blob.

The blob is a free-form JSONField the parcel form writes into: soil test results (pH, organic
matter, N, P), irrigation efficiency, and `water_allocation_acre_feet` — commercially
sensitive in California.

This guard asserts the ABSENCE on both builders at once, because "fixed at the site where it
was found" is precisely the failure mode being guarded. A denylist encodes only the last
incident; a field-set assertion encodes the rule.

No database: the serializers' declared field sets and the view module's source are enough, and
that keeps the guard runnable without Postgres.
"""

import inspect
from pathlib import Path

from django.test import SimpleTestCase

from history.serializers import PublicHistorySerializer, PublicParcelSerializer

#: Keys that are private agronomy or commercially sensitive. Named individually so a failure
#: message says WHICH secret escaped rather than just "a field changed".
PRIVATE_AGRONOMY_FIELDS = (
    "agricultural_details",
    "water_allocation_acre_feet",
    "soil_ph",
    "soil_organic_matter",
    "irrigation_efficiency",
)


class PublicParcelSerializerTests(SimpleTestCase):
    def test_agricultural_details_is_not_a_declared_field(self):
        declared = set(PublicParcelSerializer.Meta.fields)
        for field in PRIVATE_AGRONOMY_FIELDS:
            self.assertNotIn(
                field,
                declared,
                f"PublicParcelSerializer publishes '{field}'. This serializer is nested under "
                f"PublicHistorySerializer.parcel and reaches anonymous QR scanners through "
                f"HistoryViewSet.public_history (AllowAny). The certifier keeps full access "
                f"via the audit export, which reads the model directly.",
            )

    def test_the_serializer_still_publishes_what_the_consumer_page_needs(self):
        """Guards the guard: proves the field list was trimmed, not emptied.

        A test that only asserts absence passes just as happily against a serializer that
        publishes nothing at all.
        """
        declared = set(PublicParcelSerializer.Meta.fields)
        for field in ("id", "name", "polygon", "map_metadata", "establishment"):
            self.assertIn(field, declared)

    def test_parcel_is_actually_nested_on_the_public_history_payload(self):
        """The reason this serializer is a consumer surface at all.

        If the nesting ever goes away this guard is measuring nothing, and it should say so
        rather than keep passing for the wrong reason.
        """
        self.assertIsInstance(
            PublicHistorySerializer().fields["parcel"],
            PublicParcelSerializer,
        )


class CarbonViewsPublicParcelTests(SimpleTestCase):
    """The other builder. Kept in the same file so the two can never drift apart again.

    The parcel dict is assembled INLINE inside `complete_summary` rather than in a named
    helper, so the guard reads that method's source.
    """

    def test_complete_summary_does_not_emit_agricultural_details(self):
        from carbon.views import PublicProductionViewSet

        source = inspect.getsource(PublicProductionViewSet.complete_summary)
        code_only = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
        for field in PRIVATE_AGRONOMY_FIELDS:
            self.assertNotIn(
                f'"{field}"',
                code_only,
                f"carbon.views complete_summary emits '{field}' on an anonymous endpoint.",
            )


class BothBuildersAgreeTests(SimpleTestCase):
    def test_neither_public_parcel_path_names_the_blob(self):
        """A single assertion over both files — the shape of the actual defect.

        Reads the source rather than the objects so it also catches the field being
        reintroduced through a SerializerMethodField or a to_representation patch, neither of
        which would show up in `Meta.fields`.
        """
        back = Path(__file__).resolve().parents[2]
        targets = {
            "history/serializers.py": "PublicParcelSerializer",
            "carbon/views.py": 'certification_type": getattr(parcel',
        }
        for relative_path, anchor in targets.items():
            path = back / relative_path
            self.assertTrue(path.is_file(), f"{relative_path} not found — did it move?")
            source = path.read_text(encoding="utf8")
            start = source.find(anchor)
            self.assertNotEqual(start, -1, f"{anchor} not found in {relative_path}")
            # Scope to the ~120 lines after the anchor: both files mention the field elsewhere
            # (in owner-facing serializers, which are legitimate).
            window = "\n".join(source[start:].splitlines()[:120])
            # Comments explaining the removal are expected and must not trip the guard.
            code_only = "\n".join(line for line in window.splitlines() if not line.strip().startswith("#"))
            self.assertNotIn(
                '"agricultural_details"',
                code_only,
                f"{relative_path} :: {anchor} names agricultural_details in CODE (not a comment).",
            )
