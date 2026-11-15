"""
Input application rates and the scouting "zero carbon" stamp stay off the public payload.

WHY (2026-11-05): the frontend registry kept `application_rate` off every consumer surface
(chemicalEvent.ts: a shopper cannot read a rate without the label beside it, so the number
reads as a virtue signal in whichever direction it points). The anonymous payload did not
agree: `application_rate`, `application_rate_oz_acre`, `application_rate_range`,
`application_rate_tons_acre` and the `rate_*` family were all on `ALLOWED_EXTRA_DATA_KEYS`,
so the page hid the rate while the JSON behind it carried it to anyone with the QR link.

The same allow-list carried `carbon_impact`, which the pest scouting summary stamped as
"zero" on every save, fuel or not (beside a note saying scouting "does not directly produce
emissions"). No surface rendered it; the wire published it anyway. The writers are deleted;
this guard keeps the string off the wire for rows already stored with it.

What still has the rate: the producer's own record serializer (asserted below) and the
certifier packet, which reads the event models directly.
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIRequestFactory

from company.models import Company, Establishment
from history.models import ChemicalEvent, PestManagementEvent, Production
from history.serializers import ChemicalEventSerializer, PublicHistorySerializer
from product.models import Parcel, Product
from users.models import User

RATE_KEYS = (
    "application_rate",
    "application_rate_unit",
    "application_rate_oz_acre",
    "application_rate_range",
    "application_rate_tons_acre",
    "rate_L_ha",
    "rate_fl_oz_acre",
    "rate_g_ha",
    "rate_kg_ha",
    "rate_lbs_acre",
    "rate_oz_acre",
    "solubor_rate_kg_ha",
    "zinc_sulfate_rate_kg_ha",
    "n_applied_lbs_acre",
)


def _keys_anywhere(value, found=None):
    """Every dict key at any depth of a serialized payload."""
    found = set() if found is None else found
    if isinstance(value, dict):
        for k, v in value.items():
            found.add(k)
            _keys_anywhere(v, found)
    elif isinstance(value, list):
        for v in value:
            _keys_anywhere(v, found)
    return found


class InputRatesOffPublicWireTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="rates-owner@test.com", password="x")
        self.stranger = User.objects.create_user(email="rates-stranger@test.com", password="x")
        self.company = Company.objects.create(name="Rate Farm")
        self.owner.companies.add(self.company)
        other = Company.objects.create(name="Other Farm")
        self.stranger.companies.add(other)
        establishment = Establishment.objects.create(name="R1", company=self.company, state="WA")
        parcel = Parcel.objects.create(name="RP1", establishment=establishment, area=10.0)
        self.history = Production.objects.create(
            name="Rate Production",
            start_date=timezone.now(),
            product=Product.objects.create(name="Apples"),
            parcel=parcel,
            operator=self.owner,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        legacy_rates = {key: 7 for key in RATE_KEYS}
        legacy_rates["application_rate_range"] = "6-8"
        legacy_rates["application_rate_unit"] = "fl_oz_ac"
        self.chemical = ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Feather meal 12-0-0",
            application_rate=Decimal("37.5"),
            application_rate_unit="lb_ac",
            date=timezone.now(),
            extra_data={**legacy_rates, "application_method": "broadcast"},
        )
        PestManagementEvent.objects.create(
            history=self.history,
            type=PestManagementEvent.SCOUTING,
            date=timezone.now(),
            extra_data={
                "is_summary": True,
                "average_pest_pressure": "low",
                "fuel_consumed_total": 12,
                "carbon_impact": "zero",
            },
        )

    def _payload(self, user=None):
        context = {}
        if user is not None:
            request = APIRequestFactory().get("/")
            request.user = user
            context["request"] = request
        return PublicHistorySerializer(self.history, context=context).data

    def _assert_clean(self, data, who):
        events = data.get("events") or []
        families = {e.get("type") for e in events}
        # The negative assertion must prove it READ the events it claims are clean.
        self.assertIn("chemical", families, f"{who}: chemical event missing from payload")
        self.assertIn("pest_management", families, f"{who}: pest event missing from payload")
        chem = next(e for e in events if e.get("type") == "chemical")
        self.assertEqual(
            (chem.get("extra_data") or {}).get("application_method"),
            "broadcast",
            f"{who}: extra_data was not served at all, so its absence proves nothing",
        )

        keys = _keys_anywhere(events)
        leaked = sorted(set(RATE_KEYS) & keys)
        self.assertEqual(leaked, [], f"{who}: input application rates reached the public payload: {leaked}")
        self.assertNotIn("carbon_impact", keys, f"{who}: the scouting 'zero carbon' stamp reached the public payload")

    def test_anonymous_payload_carries_no_rate_and_no_zero_stamp(self):
        self._assert_clean(self._payload(), "anonymous")

    def test_signed_in_stranger_gets_the_same_payload(self):
        self._assert_clean(self._payload(self.stranger), "another company's user")

    def test_the_producer_record_keeps_its_rate(self):
        """The strip is a wire policy, not a deletion: the owner's record serializer still has it."""
        data = ChemicalEventSerializer(self.chemical).data
        self.assertEqual(Decimal(str(data.get("application_rate"))), Decimal("37.5"))
        self.assertEqual(data.get("application_rate_unit"), "lb_ac")
