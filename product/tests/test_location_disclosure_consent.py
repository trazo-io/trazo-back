"""A published field boundary must be a decision somebody made.

WHAT WENT WRONG
---------------
`Parcel.location_disclosure_level` gates what the PUBLIC consumer page may show — full polygon
(`exact`), a ~1 km centre with no boundary (`approximate`), or nothing (`hidden`). New parcels
default to `approximate`, `public_parcel_geo` fails closed to `approximate` on an unknown value,
and the marketing site describes the level as the farmer's control.

Migration 0013 then wrote `exact` onto every parcel that already existed — correct at the time,
because those parcels were already publishing boundaries. But the setting was never surfaced
anywhere in the producer app, so those farms have been publishing a field boundary under a value
they were never shown and could not reach. Measured 2026-08-31 on a development database: 33
parcels at `exact`, **0** of them chosen by anyone, 28 actually carrying a polygon.

WHY IT MATTERS MORE THAN A PRIVACY PREFERENCE
---------------------------------------------
The consumer page carries the boundary, a satellite view, the harvest date and the lot quantity
on one screen. Together those read as an operating schedule rather than a provenance claim, and
many parcels contain the family residence. Town and state already establish that a lot came from
a real place; the certifier and the inspector get the parcel map from the packet, which is
audience-gated.

WHAT THESE TESTS PIN
--------------------
1. The gate still reaches ONLY the consumer surface — the parcel application, the dashboard and
   the parcel form keep their polygon.
2. Disclosure cannot be written by the parcel form, only by the endpoint whose UI asks.
3. Answering settles the parcel; the safety narrowing does NOT, because a default applied on
   someone's behalf is not consent.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.services.privacy import public_parcel_geo
from product.models import Parcel
from product.serializers import CreateParcelSerializer
from users.models import User

POLYGON = [
    {"lat": 36.6362, "lng": -119.3831},
    {"lat": 36.6328, "lng": -119.3832},
    {"lat": 36.6327, "lng": -119.3798},
]


class LocationDisclosureConsentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="parcelowner@test.com", password="x")
        self.company = Company.objects.create(name="Disclosure Co")
        self.user.companies.add(self.company)
        self.establishment = Establishment.objects.create(name="Disclosure Farm", company=self.company)
        self.parcel = Parcel.objects.create(
            name="Block A",
            establishment=self.establishment,
            area=10.0,
            polygon=POLYGON,
            map_metadata={"center": {"lat": 36.63, "lng": -119.38}, "zoom": 15},
            location_disclosure_level="exact",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _url(self):
        # Flat route: `product/urls.py` registers `parcels` on a plain DefaultRouter and
        # `CompanyNestedViewSet` scopes the queryset from the request, not the path.
        return f"/api/parcels/{self.parcel.id}/location-disclosure/"

    # ---- the gate reaches the consumer surface only -------------------------

    def test_narrowing_disclosure_never_removes_the_operations_own_boundary(self):
        """The property that makes this safe to run in production.

        The parcel application asks for these vertices, the dashboard draws them and the parcel
        form edits them. All three read `Parcel.polygon` through `CreateParcelSerializer`;
        disclosure gates `public_parcel_geo`, which only the consumer surface calls. If this ever
        stops being true, narrowing a farm's disclosure would delete work they were asked for.
        """
        self.parcel.location_disclosure_level = "approximate"
        self.parcel.save(update_fields=["location_disclosure_level"])

        self.assertIsNone(public_parcel_geo(self.parcel)["polygon"], "the consumer page must lose the boundary")
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.polygon, POLYGON, "the operation's own boundary must survive")
        self.assertEqual(
            CreateParcelSerializer(self.parcel).data["polygon"],
            POLYGON,
            "the producer serializer feeding the form, dashboard and application must still carry it",
        )

    def test_hidden_also_keeps_the_stored_boundary(self):
        self.parcel.location_disclosure_level = "hidden"
        self.parcel.save(update_fields=["location_disclosure_level"])
        self.assertIsNone(public_parcel_geo(self.parcel)["polygon"])
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.polygon, POLYGON)

    # ---- one editor per fact ------------------------------------------------

    def test_the_parcel_form_cannot_write_disclosure(self):
        """`.claude/rules/frontend.md`: one editor per fact, and a payload sends only what its
        UI renders. A field writable by a form that never displays it is how a farm ends up
        publishing a boundary nobody chose — the defect this change closes."""
        serializer = CreateParcelSerializer(
            self.parcel,
            data={"location_disclosure_level": "hidden", "location_disclosure_choice_made": True},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        # Asserted on validated_data rather than by calling save(): the point is that the input
        # is DISCARDED before it can reach the model, and checking that directly does not drag
        # the parcel form's image-upload machinery into a test about a disclosure enum.
        self.assertNotIn(
            "location_disclosure_level",
            serializer.validated_data,
            "the parcel form accepted a disclosure level it does not render",
        )
        self.assertNotIn("location_disclosure_choice_made", serializer.validated_data)
        for field in ("location_disclosure_level", "location_disclosure_choice_made"):
            self.assertTrue(serializer.fields[field].read_only, field)

    # ---- the endpoint that does ask -----------------------------------------

    def test_answering_settles_the_parcel(self):
        response = self.client.patch(self._url(), {"location_disclosure_level": "approximate"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.location_disclosure_level, "approximate")
        self.assertTrue(self.parcel.location_disclosure_choice_made)

    def test_keeping_exact_also_settles_it(self):
        """Choosing to publish IS an answer. Without this the prompt would reappear forever for
        a farm that deliberately wants its boundary public."""
        response = self.client.patch(self._url(), {"location_disclosure_level": "exact"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.location_disclosure_level, "exact")
        self.assertTrue(self.parcel.location_disclosure_choice_made)

    def test_an_invalid_level_is_refused(self):
        response = self.client.patch(self._url(), {"location_disclosure_level": "public"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.location_disclosure_level, "exact")
        self.assertFalse(self.parcel.location_disclosure_choice_made)

    def test_another_company_cannot_read_or_change_it(self):
        stranger = User.objects.create_user(email="stranger@test.com", password="x")
        stranger.companies.add(Company.objects.create(name="Other Co"))
        client = APIClient()
        client.force_authenticate(user=stranger)

        self.assertIn(
            client.patch(self._url(), {"location_disclosure_level": "hidden"}, format="json").status_code,
            (403, 404),
        )
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.location_disclosure_level, "exact")

    def test_has_boundary_tells_the_prompt_whether_to_warn(self):
        """A parcel at `exact` with no polygon publishes nothing, so the prompt must not warn it
        about a boundary it does not have."""
        self.assertTrue(self.client.get(self._url()).data["has_boundary"])
        self.parcel.polygon = None
        self.parcel.save(update_fields=["polygon"])
        self.assertFalse(self.client.get(self._url()).data["has_boundary"])

    # ---- the safety narrowing is not consent --------------------------------

    def test_the_bulk_narrowing_does_not_settle_the_choice(self):
        """`audit_parcel_location_disclosure --apply --to-approximate` applies a safer default on
        the farm's behalf. That is not an answer, so the prompt must still ask — otherwise the
        command would consume the very consent it exists to obtain."""
        from django.core.management import call_command

        call_command("audit_parcel_location_disclosure", "--apply", "--to-approximate", verbosity=0)

        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.location_disclosure_level, "approximate")
        self.assertFalse(
            self.parcel.location_disclosure_choice_made,
            "a default applied on someone's behalf must not record as their decision",
        )

    def test_the_bulk_narrowing_leaves_a_deliberate_choice_alone(self):
        """A farm that chose `exact` outranks the safety default. The command must never
        overrule an answer it asked for."""
        from django.core.management import call_command

        self.parcel.location_disclosure_choice_made = True
        self.parcel.save(update_fields=["location_disclosure_choice_made"])

        call_command("audit_parcel_location_disclosure", "--apply", "--to-approximate", verbosity=0)

        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.location_disclosure_level, "exact")
