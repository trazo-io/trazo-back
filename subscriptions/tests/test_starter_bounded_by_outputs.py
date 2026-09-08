"""Starter is bounded by its OUTPUT, not by how much it can log.

The old limiter was `max_productions_per_year: 1`. A production is a crop cycle and the ICP — a
mid-size California wholesale orchard — runs about twenty a year, so Starter let a grower model
every block and then 403'd at production #2: it bit at the exact moment the farm began generating
the records the product exists to produce. Nobody evaluates a RECORDKEEPING tool on one cycle.

The wall moved onto the artifacts a farm hands to somebody else — the OSP renewal packet, its
module PDFs, the audit exports, the CA PUR export and the certifier review link. That decision is
only real if it is ENFORCED, which is what these tests are for: a `compliance_exports` flag that
merely decorates a pricing page would be a price list, not a plan.

Every test here asserts a promise (what a plan grants, what a door refuses), never a call graph,
so they survive moving the check to a different layer.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from subscriptions.gating import ComplianceExportRequired, company_has_compliance_exports, require_compliance_exports
from subscriptions.models import AddOn, Plan, Subscription

# Plans seeded by `create_plans` that MUST grant the exports. Compliance is the one tier for sale;
# pilot is Compliance comped, and if a pilot could not produce a packet the October pilots would be
# testing a product nobody is being asked to buy. The four legacy tiers are retired but were PAID.
PLANS_THAT_EXPORT = [
    "compliance-yearly",
    "pilot",
    "basic-monthly",
    "basic-yearly",
    "standard-monthly",
    "standard-yearly",
    "corporate-monthly",
    "corporate-yearly",
    "enterprise-monthly",
    "enterprise-yearly",
]


def _company_on(plan, name):
    company = Company.objects.create(name=name)
    Subscription.objects.create(
        company=company,
        plan=plan,
        status="active",
        current_period_start=timezone.now() - timedelta(days=5),
        current_period_end=timezone.now() + timedelta(days=25),
    )
    company.refresh_from_db()
    return company


class SeededPlanShapeTests(TestCase):
    """Asserts what a FRESH environment actually gets, by running the seeder.

    Reading the constants out of the command module would only prove the file parses. `create_plans`
    is what runs on a new deployment, and it is the thing that has silently written nothing before
    (the Stripe-key guard exists because of that), so the seeder is the subject under test.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", verbosity=0)

    def test_starter_no_longer_caps_productions(self):
        features = Plan.objects.get(slug="starter").features
        self.assertEqual(
            features["max_productions_per_year"],
            -1,
            "Starter caps productions again. A production is a crop cycle and the ICP runs ~20 a "
            "year, so any finite cap here blocks the farm at the moment it starts producing "
            "records — which is the behaviour migration 0014 exists to remove.",
        )

    def test_starter_storage_survives_a_season_of_photos(self):
        """`storage_utils` REFUSES an upload past the limit.

        Removing the production cap while leaving 2 GB would have re-imposed the same wall in a
        worse form: not a legible "upgrade to add another production" but a failed photo upload
        in the field, mid-season.
        """
        features = Plan.objects.get(slug="starter").features
        self.assertGreaterEqual(
            features["storage_limit_gb"],
            10,
            "Starter storage is back under 10 GB — a season of photo evidence does not fit, and "
            "storage_utils turns that into a refused upload rather than an upgrade prompt.",
        )

    def test_starter_can_use_voice(self):
        """The measured adoption barriers are time/labour (63-65%) and training (53%) ahead of
        cost (44%). Gating the fastest gloves-on input path suppresses the logging that creates
        the records that create the upgrade."""
        self.assertIs(Plan.objects.get(slug="starter").features["voice_recording"], True)

    def test_starter_does_not_grant_the_exports(self):
        """The whole tier design rests on this one False."""
        self.assertIs(Plan.objects.get(slug="starter").features["compliance_exports"], False)

    def test_every_paid_tier_grants_the_exports(self):
        missing = [
            slug
            for slug in PLANS_THAT_EXPORT
            if not Plan.objects.filter(slug=slug).exists()
            or Plan.objects.get(slug=slug).features.get("compliance_exports") is not True
        ]
        self.assertEqual(
            missing,
            [],
            f"{missing} do not grant compliance_exports. `Company.has_feature` treats a missing "
            "key as False, so an omission here silently strips the certifier packet, the audit "
            "export, the PUR export and the certifier link from a PAID plan.",
        )


class ExtraFarmAddOnTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", verbosity=0)

    def test_second_farm_is_not_dearer_than_the_first(self):
        """The defect this replaces, stated as an invariant.

        At $30/month the add-on cost $360/yr against a $249/yr plan, so farm #2 cost 45% more than
        farm #1 — the marginal price went UP with volume, and it punished the multi-farm grower
        hardest. Comparing annualised figures rather than the raw column is the point: the old
        price looked smaller and was larger.
        """
        base = Plan.objects.get(slug="compliance-yearly")
        addon = AddOn.objects.get(slug="extra-establishment")

        per_year = {"monthly": 12, "yearly": 1}
        base_annual = Decimal(base.price) * per_year[base.interval]
        addon_annual = Decimal(addon.price) * per_year[addon.interval]

        self.assertLessEqual(
            addon_annual,
            base_annual,
            f"An extra farm costs ${addon_annual}/yr against a ${base_annual}/yr plan. The "
            "marginal unit must not cost more than the first one.",
        )

    def test_the_add_on_states_its_period(self):
        """A price with no period is not a price.

        `AddOn.interval` did not exist: the period was passed to Stripe and dropped on the way
        into the database, so the app rendered a bare "$30.00" next to a plan labelled "/Yearly"
        and nothing on screen distinguished the two.
        """
        addon = AddOn.objects.get(slug="extra-establishment")
        self.assertEqual(addon.interval, "yearly")

    def test_retired_add_ons_keep_the_period_they_actually_billed(self):
        """A withdrawn row is still a record; it should not start lying on the way out."""
        for slug in ("extra-production", "extra-parcel", "blockchain-verification"):
            with self.subTest(slug=slug):
                self.assertEqual(AddOn.objects.get(slug=slug).interval, "monthly")


class GateUnitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", verbosity=0)
        cls.starter = _company_on(Plan.objects.get(slug="starter"), "Starter Ranch")
        cls.paid = _company_on(Plan.objects.get(slug="compliance-yearly"), "Paid Ranch")

    def test_starter_is_refused(self):
        self.assertIs(company_has_compliance_exports(self.starter), False)
        with self.assertRaises(ComplianceExportRequired):
            require_compliance_exports(self.starter)

    def test_compliance_is_allowed(self):
        self.assertIs(company_has_compliance_exports(self.paid), True)
        require_compliance_exports(self.paid)  # must not raise

    def test_no_company_fails_closed(self):
        """A company that cannot be resolved is refused, not waved through. The alternative —
        treating "unknown" as permitted — is how a gate becomes decorative."""
        self.assertIs(company_has_compliance_exports(None), False)
        with self.assertRaises(ComplianceExportRequired):
            require_compliance_exports(None)

    def test_a_company_with_no_subscription_is_refused(self):
        orphan = Company.objects.create(name="No Plan Co")
        self.assertIs(company_has_compliance_exports(orphan), False)

    def test_the_refusal_is_distinguishable_from_not_yours(self):
        """The frontend has to tell "this is not yours" from "this IS yours, here is how to take
        it out" — they call for opposite screens. That branch is only possible if the code
        survives serialisation."""
        self.assertEqual(ComplianceExportRequired().get_codes(), "compliance_exports_required")


class ExportDoorTests(TestCase):
    """The doors, exercised over HTTP.

    Real requests, because the promise is "a Starter farm cannot download a certifier document",
    and only a response proves that. Each door is checked BOTH ways: refused on Starter, and served
    (or at least not refused for plan reasons) on Compliance. A one-sided test would pass just as
    happily if the gate rejected everybody.
    """

    @classmethod
    def setUpTestData(cls):
        from users.models import User, WorksIn

        call_command("create_plans", verbosity=0)

        def _farm(company, user, name):
            est = Establishment.objects.create(name=name, company=company, country="US", state="CA")
            WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
            return est

        cls.starter_user = User.objects.create_user(
            email="starter@example.com", password="x", first_name="S", last_name="U", is_active=True
        )
        cls.paid_user = User.objects.create_user(
            email="paid@example.com", password="x", first_name="P", last_name="U", is_active=True
        )
        cls.starter_co = _company_on(Plan.objects.get(slug="starter"), "Starter Ranch")
        cls.paid_co = _company_on(Plan.objects.get(slug="compliance-yearly"), "Paid Ranch")
        cls.starter_farm = _farm(cls.starter_co, cls.starter_user, "Starter Home Block")
        cls.paid_farm = _farm(cls.paid_co, cls.paid_user, "Paid Home Block")

        # Rows the OSP and production doors need in order to get PAST `get_object()` — without
        # them a 404 would stand in for the 403 and the test would pass while the gate was gone.
        from certifications.models import OrganicSystemPlan
        from history.models import History
        from product.models import Parcel

        cls.starter_osp = OrganicSystemPlan.objects.create(establishment=cls.starter_farm, version_number=1)
        cls.paid_osp = OrganicSystemPlan.objects.create(establishment=cls.paid_farm, version_number=1)
        cls.starter_parcel = Parcel.objects.create(name="Block A", establishment=cls.starter_farm, area=4.0)
        cls.starter_production = History.objects.create(parcel=cls.starter_parcel, name="2026 Navels")

    def _client(self, user):
        # `force_authenticate`, never `force_login`: DRF here authenticates only via
        # users.auth.CustomAuthentication (JWT cookie) and has no SessionAuthentication, so a
        # session login leaves the request anonymous and every assertion below would pass for
        # the wrong reason (401, not 403).
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _operation_export_url(self, company, farm):
        return f"/api/companies/{company.id}/establishments/{farm.id}/operation-audit-export/"

    def _osp_url(self, company, farm, osp, action):
        return f"/api/companies/{company.id}/establishments/{farm.id}/osps/{osp.id}/{action}/"

    # ------------------------------------------------------------------------------------
    # The four doors that had a STATIC check and no runtime one.
    #
    # `test_compliance_export_door_inventory` reads each view's AST and asserts the gate is
    # CALLED. That catches a new endpoint written by somebody who did not know the gate exists,
    # and it cannot catch the gate being unreachable — an early return above it, a decorator
    # that answers first, a branch that skips it. Which is not academic: the OSP packet was the
    # door a Starter farm actually hit (2026-09-07), and the only reason we knew the server
    # refused it was a screenshot.
    #
    # Every door is asserted BOTH ways, same as the three above: refused on Starter with a code
    # the client can branch on, and not refused for plan reasons on Compliance.
    # ------------------------------------------------------------------------------------

    def test_osp_packet_refused_on_starter(self):
        response = self._client(self.starter_user).get(
            self._osp_url(self.starter_co, self.starter_farm, self.starter_osp, "packet")
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get("detail").code, "compliance_exports_required")

    def test_osp_packet_not_plan_refused_on_compliance(self):
        response = self._client(self.paid_user).get(
            self._osp_url(self.paid_co, self.paid_farm, self.paid_osp, "packet")
        )
        self.assertNotEqual(
            response.status_code,
            403,
            f"Compliance was refused its own packet: {getattr(response, 'data', None)}",
        )

    def test_osp_module_pdf_refused_on_starter(self):
        """The components of the packet. Gating the ZIP alone would leave the whole artifact
        reassemblable one download at a time."""
        response = self._client(self.starter_user).get(
            self._osp_url(self.starter_co, self.starter_farm, self.starter_osp, "module-pdf")
            + "?module=monitoring_fraud_prevention"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get("detail").code, "compliance_exports_required")

    def test_module_pdf_gate_precedes_its_own_argument_check(self):
        """Refused for the PLAN, not for the missing `?module=`.

        Ordered the other way the Starter farm gets a 400 about a query parameter — a validation
        error standing where a plan boundary belongs, which tells the app nothing to show and the
        farmer nothing true. This is the assertion the AST test structurally cannot make: both
        orderings contain the call.
        """
        response = self._client(self.starter_user).get(
            self._osp_url(self.starter_co, self.starter_farm, self.starter_osp, "module-pdf")
        )
        self.assertEqual(response.status_code, 403, f"Expected the plan answer, got {response.data}")

    def test_osp_workbook_refused_on_starter(self):
        """`?workbook=` streams an .xlsx the price list sells. The parameterless branch is
        deliberately open — it returns blank COUNTS about the farm's own records, which is what
        the operator needs in order to decide whether the packet is worth buying."""
        gated = self._client(self.starter_user).get(
            self._osp_url(self.starter_co, self.starter_farm, self.starter_osp, "attachments")
            + "?workbook=field_and_crop_information"
        )
        self.assertEqual(gated.status_code, 403)
        self.assertEqual(gated.data.get("detail").code, "compliance_exports_required")

        counts = self._client(self.starter_user).get(
            self._osp_url(self.starter_co, self.starter_farm, self.starter_osp, "attachments")
        )
        self.assertEqual(
            counts.status_code,
            200,
            f"The blank-cell counts are the farm reading its OWN records: {getattr(counts, 'data', None)}",
        )

    def test_production_audit_export_refused_on_starter(self):
        response = self._client(self.starter_user).get(f"/api/histories/{self.starter_production.id}/audit-export/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get("detail").code, "compliance_exports_required")

    def test_production_audit_export_by_uuid_refused_on_starter(self):
        """The UUID twin produces the identical document, so a farm must not be able to reach
        it around the gate on the numeric route."""
        response = self._client(self.starter_user).get(
            f"/api/histories/{self.starter_production.public_id}/audit-export/"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get("detail").code, "compliance_exports_required")

    def test_background_dossier_build_refused_on_starter(self):
        """The POST that STARTS a build carries the same gate as the inline export it replaced —
        otherwise the paywalled document simply arrives on the Documents shelf instead."""
        response = self._client(self.starter_user).post(
            f"/api/companies/{self.starter_co.id}/establishments/{self.starter_farm.id}/export-jobs/",
            {"kind": "operation_dossier"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get("detail").code, "compliance_exports_required")

    def test_operation_audit_export_refused_on_starter(self):
        response = self._client(self.starter_user).get(self._operation_export_url(self.starter_co, self.starter_farm))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data.get("detail").code,
            "compliance_exports_required",
            f"403 for the wrong reason: {response.data}. A plan refusal must be distinguishable "
            "from an ownership refusal, or the app cannot show an upgrade prompt.",
        )

    def test_operation_audit_export_not_plan_refused_on_compliance(self):
        """The paid farm has no productions, so the export may still be empty — what must NOT
        happen is a refusal. Asserting on the STATUS rather than only on the error code matters:
        the first version checked `code != "compliance_exports_required"`, which a 500 satisfies
        just as happily as a working PDF, so the paid half of the test proved nothing.

        Not asserting 200 either, because that would make this a test of PDF generation. 403 is
        the assertion that belongs here: this user is COMPANY_ADMIN of the owning company on the
        tier that buys this document, so no refusal of any kind is legitimate.
        """
        response = self._client(self.paid_user).get(self._operation_export_url(self.paid_co, self.paid_farm))
        self.assertNotEqual(
            response.status_code,
            403,
            f"Compliance was refused its own artifact: {getattr(response, 'data', None)}",
        )

    def test_pur_export_refused_on_starter(self):
        response = self._client(self.starter_user).get(
            f"/api/histories/pur-export/?establishment_id={self.starter_farm.id}&month=7&year=2026"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get("detail").code, "compliance_exports_required")

    def test_out_of_state_farm_is_told_it_does_not_apply_not_to_pay(self):
        """ "Does not apply to you" must win over "costs money".

        The gate used to sit before the CA-state check, so a Florida farm on Starter was told to
        buy Compliance to unlock the CALIFORNIA Pesticide Use Report — a document that does not
        exist for their operation at any price.
        """
        florida = Establishment.objects.create(
            name="Gulf Coast Grove", company=self.starter_co, country="US", state="FL"
        )
        response = self._client(self.starter_user).get(
            f"/api/histories/pur-export/?establishment_id={florida.id}&month=7&year=2026"
        )
        self.assertEqual(
            response.status_code,
            404,
            f"Expected 404 (not a California filing), got {response.status_code}: {response.data}",
        )

    def test_pur_export_not_plan_refused_on_compliance(self):
        """Same reasoning as the operation dossier: assert no refusal, not merely no PLAN
        refusal. The paid farm is in California and the user administers it, so a 403 here has
        no legitimate cause."""
        response = self._client(self.paid_user).get(
            f"/api/histories/pur-export/?establishment_id={self.paid_farm.id}&month=7&year=2026"
        )
        self.assertNotEqual(
            response.status_code,
            403,
            f"Compliance was refused its own PUR export: {getattr(response, 'data', None)}",
        )

    def test_certifier_link_cannot_be_minted_on_starter(self):
        """Refused BEFORE the readiness walk, so a Starter farm gets a plan answer rather than a
        list of blockers it cannot act on."""
        response = self._client(self.starter_user).post(
            f"/api/companies/{self.starter_co.id}/establishments/{self.starter_farm.id}/certifier-links/",
            {"certification_type": "organic"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get("detail").code, "compliance_exports_required")

    def test_starter_can_still_list_its_certifier_links(self):
        """Gate on CREATE only. If a farm lapses to Starter it must still be able to see and
        REVOKE links a certifier already holds — otherwise lapsing strands live tokens the grower
        can neither view nor withdraw."""
        response = self._client(self.starter_user).get(
            f"/api/companies/{self.starter_co.id}/establishments/{self.starter_farm.id}/certifier-links/"
        )
        self.assertEqual(response.status_code, 200)


class LoggingStaysFreeTests(TestCase):
    """The other half of the promise. Moving the wall to the output is worthless if the input
    quietly stayed capped somewhere else."""

    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", verbosity=0)
        cls.starter = _company_on(Plan.objects.get(slug="starter"), "Starter Ranch")

    def test_a_starter_farm_can_create_a_twentieth_production(self):
        from history.models import History
        from product.models import Parcel

        farm = Establishment.objects.create(name="Home", company=self.starter, country="US", state="CA")
        parcel = Parcel.objects.create(name="Block 1", establishment=farm, area=10.0)
        for i in range(19):
            History.objects.create(parcel=parcel, name=f"Cycle {i}")

        self.assertIs(
            self.starter.can_create_production(),
            True,
            "Starter blocked production #20. The free tier is bounded by what it can PRODUCE, not "
            "by how much it can log.",
        )

    def test_a_starter_farm_can_create_many_parcels(self):
        farm = Establishment.objects.create(name="Home", company=self.starter, country="US", state="CA")
        self.assertIs(self.starter.can_create_parcel(farm), True)
