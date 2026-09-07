"""The input search has to reach the row the grower is holding.

Three real searches came back wrong on 2026-09-06, all from the same screen:

  * ``gus-4423`` — the OMRI product code, pasted straight off the certificate — returned
    nothing. ``verify_input`` accepted a code only through a separate ``omri_id`` query
    parameter that the OSP panel never sent, so the code went down the NAME matcher,
    tokenized to ``["gus", "4423"]``, and matched no product. The grower was told their own
    catalog code was not in the catalog.
  * ``Serenad`` — one character short of the brand — returned nothing. The matcher compared
    whole tokens only, with no prefix pass.
  * ``Serenade`` — spelled correctly — returned ONE brand while the catalogue held several,
    because every catalogue answered with a single winner. The plan's own Serenade Opti was
    unreachable from a search for its own name.

The rule underneath all three: a SEARCH may be generous, because it offers the grower a
choice. A DETECTOR may not, because its match becomes an assertion in a certifier packet.
So the generosity is opt-in (``allow_prefix``) and only ``verify_input`` opts in — these
tests pin both halves, since a permissive default would quietly widen the drift detector
and ``seed_cdfa_oim``, which persist what they match.
"""

from django.test import TestCase

from certifications.models import NationalListSubstance, OMRIProduct, WSDAMaterial
from certifications.services.omri_verifier import (
    _omri_candidates_by_name,
    _resolve_omri_by_name,
    _resolve_wsda_by_name,
    _wsda_candidates_by_name,
    looks_like_omri_code,
    national_list_candidates_by_name,
    omri_certificate_url,
)


class OMRICodeSearchTests(TestCase):
    """A pasted product code is an identity, not a guess — it resolves on every path."""

    @classmethod
    def setUpTestData(cls):
        cls.aso = OMRIProduct.objects.create(
            omri_id="gus-4423",
            product_name="Serenade ASO",
            manufacturer="Bayer CropScience LP",
            category="crop-pest-control",
        )
        cls.entrust = OMRIProduct.objects.create(
            omri_id="dow-2900",
            product_name="Entrust SC Naturalyte Insect Control",
            manufacturer="Dow Agrosciences LLC",
            category="crop-pest-control",
        )

    def test_code_typed_into_the_name_box_resolves(self):
        self.assertEqual(_omri_candidates_by_name("gus-4423"), [self.aso])
        self.assertEqual(_omri_candidates_by_name("GUS-4423"), [self.aso])
        self.assertEqual(_omri_candidates_by_name("  dow-2900 "), [self.entrust])

    def test_a_code_resolves_without_allow_prefix(self):
        """The drift detector calls the strict path; an exact code must still work there."""
        self.assertEqual(_resolve_omri_by_name("dow-2900"), self.entrust)

    def test_a_well_formed_code_we_do_not_hold_is_a_miss_not_a_guess(self):
        """`zzz-9999` must not fall through to matching "zzz" against product names."""
        self.assertEqual(_omri_candidates_by_name("zzz-9999", allow_prefix=True), [])

    def test_code_shape_detection(self):
        for value in ("gus-4423", "GUS-4423", "dow-2900", "nhf-0644", "pfb-18591"):
            self.assertTrue(looks_like_omri_code(value), value)
        for value in ("Serenade", "2-4-1", "Serenade ASO", "", "copper hydroxide"):
            self.assertFalse(looks_like_omri_code(value), value)

    def test_certificate_url_decomposes_the_code(self):
        """
        ⚠️ `/mfg/{omri_id}` is the MANUFACTURER path handed a PRODUCT code and does not
        resolve. OMRI's certificate URL splits the code on its hyphen. Zero padding is part
        of the number and must survive.
        """
        self.assertEqual(omri_certificate_url("gus-4423"), "https://www.omri.org/mfg/gus/certificate/4423")
        self.assertEqual(omri_certificate_url("nhf-0644"), "https://www.omri.org/mfg/nhf/certificate/0644")

    def test_certificate_url_falls_back_to_a_search_for_a_non_code(self):
        self.assertIn("omri-search?query=", omri_certificate_url("Serenade ASO"))


class PrefixSearchTests(TestCase):
    """`Serenad` must reach `Serenade ASO` — but only on the search path."""

    @classmethod
    def setUpTestData(cls):
        cls.aso = OMRIProduct.objects.create(
            omri_id="gus-4423", product_name="Serenade ASO", manufacturer="Bayer CropScience LP"
        )
        cls.max = OMRIProduct.objects.create(
            omri_id="gus-4424", product_name="Serenade MAX", manufacturer="Bayer CropScience LP"
        )
        cls.organic_gem = OMRIProduct.objects.create(
            omri_id="ocg-1111", product_name="Organic Gem Fish Fertilizer", manufacturer="Advanced Marine"
        )

    def test_partial_brand_reaches_the_products_when_prefix_is_allowed(self):
        self.assertEqual(
            _omri_candidates_by_name("Serenad", allow_prefix=True),
            [self.aso, self.max],
        )

    def test_partial_brand_matches_nothing_on_the_strict_path(self):
        """⛔ The drift detector and `seed_cdfa_oim` call this. A prefix hit here would
        become a persisted third-party listing claim for a product nobody named."""
        self.assertEqual(_omri_candidates_by_name("Serenad"), [])
        self.assertIsNone(_resolve_omri_by_name("Serenad"))

    def test_a_whole_token_match_always_outranks_a_prefix_match(self):
        """Turning prefix matching on may add rows; it may never displace the exact answer."""
        exact_first = _omri_candidates_by_name("Serenade MAX", allow_prefix=True)
        self.assertEqual(exact_first[0], self.max)

    def test_a_two_character_stem_is_not_a_search(self):
        """ "or" must not prefix-match every product beginning "Organic ...". Three chars is
        the floor, and the brand anchor still applies."""
        self.assertEqual(_omri_candidates_by_name("or", allow_prefix=True), [])


class PluralCatalogueAnswerTests(TestCase):
    """Every catalogue answers with a list. One winner per catalogue hid real rows."""

    @classmethod
    def setUpTestData(cls):
        cls.aso = OMRIProduct.objects.create(omri_id="gus-4423", product_name="Serenade ASO")
        cls.max = OMRIProduct.objects.create(omri_id="gus-4424", product_name="Serenade MAX")
        # Two brands sharing a stem, exactly the shape that returned one row.
        cls.wsda_a = WSDAMaterial.objects.create(wsda_id="1123", brand_name="Kaligreen Fungicide")
        cls.wsda_b = WSDAMaterial.objects.create(wsda_id="2948", brand_name="Kaligreen Plus")
        cls.copper_hydroxide = NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            substance_name_normalized="copper hydroxide",
            cfr_section="205.601",
            subsection="i",
            status="allowed",
        )
        cls.copper_sulfate = NationalListSubstance.objects.create(
            substance_name="Copper sulfate",
            substance_name_normalized="copper sulfate",
            cfr_section="205.601",
            subsection="a",
            status="allowed",
        )

    def test_omri_returns_every_brand_sharing_the_stem(self):
        self.assertEqual(_omri_candidates_by_name("Serenade"), [self.aso, self.max])

    def test_wsda_returns_every_brand_sharing_the_stem(self):
        rows = _wsda_candidates_by_name("Kaligreen")
        self.assertEqual({r.pk for r in rows}, {self.wsda_a.pk, self.wsda_b.pk})

    def test_wsda_singular_resolver_still_answers_with_the_top_row(self):
        """The drift detector reads the singular form; it must keep working unchanged."""
        self.assertEqual(_resolve_wsda_by_name("Kaligreen Plus"), self.wsda_b)

    def test_national_list_reverse_containment_returns_all_the_coppers(self):
        """
        `verify_input` collapsed this with `min(..., key=len)`, so typing "copper" produced
        whichever § 205.601 copper entry had the shortest NAME — a fact about the string,
        not about the grower's product. Both entries are real and the grower must pick.
        """
        rows = national_list_candidates_by_name("copper")
        self.assertEqual({r.pk for r in rows}, {self.copper_hydroxide.pk, self.copper_sulfate.pk})

    def test_national_list_forward_containment_prefers_the_most_specific(self):
        """A pasted label CONTAINS the substance name; the longest match is the specific one."""
        rows = national_list_candidates_by_name("Kocide 3000 (Copper Hydroxide 46.1%)")
        self.assertEqual(rows[0], self.copper_hydroxide)

    def test_an_exact_national_list_name_is_the_answer_not_a_shortlist(self):
        self.assertEqual(national_list_candidates_by_name("copper sulfate"), [self.copper_sulfate])


class ProhibitedStatusTravelsPerRowTests(TestCase):
    """
    The National List holds § 205.601 allowed AND § 205.602 prohibited substances, and both
    answer the same search. `status` therefore has to travel PER ROW: the panel decides
    whether to render an Add button or the prohibited notice from the row in front of it, so
    a shortlist containing one of each must carry both verdicts, not the verdict of whichever
    ranked first.

    ⚠️ The rows below are FIXTURES chosen for their shape — two substances sharing a stem,
    one allowed and one prohibited. They are not an assertion about what § 205.601/602
    actually list; the seeded catalogue is the authority on that.
    """

    @classmethod
    def setUpTestData(cls):
        cls.allowed = NationalListSubstance.objects.create(
            substance_name="Sulfur dioxide",
            substance_name_normalized="sulfur dioxide",
            cfr_section="205.601",
            subsection="j",
            status="allowed",
        )
        cls.prohibited = NationalListSubstance.objects.create(
            substance_name="Sulfur dioxide smoke bomb",
            substance_name_normalized="sulfur dioxide smoke bomb",
            cfr_section="205.602",
            subsection="",
            status="prohibited",
        )

    def test_a_stem_returns_both_rows_each_carrying_its_own_status(self):
        rows = national_list_candidates_by_name("dioxide")
        by_pk = {r.pk: r.status for r in rows}
        self.assertEqual(by_pk.get(self.allowed.pk), "allowed")
        self.assertEqual(by_pk.get(self.prohibited.pk), "prohibited")

    def test_an_exact_name_answers_alone_by_design(self):
        """
        ⛔ Deliberate, and load-bearing: `_omri_candidates_by_name` and this function both
        return a shortlist of ONE for an exact normalized hit — "an exact hit is the answer,
        not a shortlist". Widening it so an exact match also drags in every row containing
        the same words would put alternatives beside an unambiguous answer, which is the
        ambiguity problem inverted. Pinned so the shortlist work cannot erode it by accident.
        """
        self.assertEqual(national_list_candidates_by_name("sulfur dioxide"), [self.allowed])


class VerifyInputPayloadHonestyTests(TestCase):
    """The endpoint must not EMIT an identifier it cannot stand behind.

    Both readers of `/certifications/verify-input/` already refuse to render a WSDA id that
    is not a bare integer. That is the right behaviour at the far end of the wire and the
    wrong place for the only guard: a claim filtered by its reader is still a claim on the
    wire, and the next reader — a report, an export, someone's integration — inherits the
    defect. `WSDA-REG-BIOAG-2025-001` is not a shape WSDA issues, so the honest payload value
    is null, not the placeholder.

    Real product numbers must still travel, or the fix would suppress the identifiers the
    rebuilt catalogue exists to provide.
    """

    def setUp(self):
        from rest_framework.test import APIClient

        from users.models import User

        self.client = APIClient()
        self.user = User.objects.create_user(email="grower@test.com", password="x")
        self.client.force_authenticate(user=self.user)

    def _get(self, name):
        return self.client.get("/api/certifications/verify-input/", {"name": name})

    def test_a_fabricated_wsda_id_is_never_emitted(self):
        WSDAMaterial.objects.create(wsda_id="WSDA-REG-BIOAG-2025-003", brand_name="Serenade Opti")
        body = self._get("Serenade Opti").json()

        self.assertEqual(body["wsda_material_name"], "Serenade Opti")
        self.assertIsNone(body["wsda_material_id"])
        self.assertEqual([c["wsda_id"] for c in body["wsda_candidates"]], [None])
        self.assertNotIn("WSDA-REG-", str(body))

    def test_a_real_wsda_product_number_still_travels(self):
        WSDAMaterial.objects.create(wsda_id="2948", brand_name="Nature Safe Feather Meal")
        body = self._get("Nature Safe Feather Meal").json()

        self.assertEqual(body["wsda_material_id"], "2948")
        self.assertEqual([c["wsda_id"] for c in body["wsda_candidates"]], ["2948"])

    def test_a_pasted_omri_code_resolves_through_the_endpoint(self):
        """End-to-end for the defect that started this: the panel sends only `name`."""
        OMRIProduct.objects.create(omri_id="gus-4423", product_name="Serenade ASO")
        body = self._get("gus-4423").json()

        self.assertEqual(body["omri_product_name"], "Serenade ASO")
        self.assertEqual(body["omri_product_id"], "gus-4423")
        self.assertEqual(body["omri_candidate_count"], 1)


class CompanyFirstCatalogNameTests(TestCase):
    """The publishers name products COMPANY-FIRST. The matcher must survive that.

    🔴 2026-09-06 — regression caught by smoke-testing the rebuilt catalogues, not by any
    existing test. The hand-typed seeds these replaced carried tidied, brand-first names
    ("Serenade ASO", "Feather Meal 13-0-0"), so the brand-anchor rule — first query token
    must land on the product's first or second token — held by accident. OMRI's real strings
    lead with the registrant:

        Bayer Serenade ASO
        NovaSource Surround WP Agricultural Crop Protectant
        Down to Earth All Natural Fertilizers Feather Meal 12-0-0

    Against those, "Serenade" and "Feather Meal" — what a grower types off the bottle —
    matched NOTHING. Worse than a bad search: the drift detector calls the same matcher, so
    every event naming one of these products would have begun flagging as an unresolved
    § 205.400(f)(2) finding in the certifier packet.

    The fix is a contiguous-run tier: every query token adjacent and in order, anywhere in
    the name. Contiguity is precise enough to be safe on the detector's path, which scattered
    tokens are not.
    """

    @classmethod
    def setUpTestData(cls):
        cls.serenade_aso = OMRIProduct.objects.create(omri_id="gus-4423", product_name="Bayer Serenade ASO")
        cls.serenade_opti = OMRIProduct.objects.create(
            omri_id="gus-5425", product_name="Bayer Serenade Opti A Wettable Powder Biofungicide"
        )
        cls.surround = OMRIProduct.objects.create(
            omri_id="tki-9178", product_name="NovaSource Surround WP Agricultural Crop Protectant"
        )
        cls.feather = OMRIProduct.objects.create(
            omri_id="det-4970", product_name="Down to Earth All Natural Fertilizers Feather Meal 12-0-0"
        )

    def test_the_brand_alone_reaches_a_company_first_name(self):
        """ "Serenade" sits at index 1 — inside the anchor window — so this holds on BOTH paths."""
        self.assertEqual(
            _omri_candidates_by_name("Serenade"),
            [self.serenade_aso, self.serenade_opti],
        )

    def test_a_brand_buried_deep_in_the_name_is_reached_by_a_contiguous_run(self):
        """ "Feather Meal" starts at token 6 of the Down To Earth name — far outside the
        anchor window. Two adjacent tokens is what makes it findable."""
        self.assertEqual(_omri_candidates_by_name("Feather Meal"), [self.feather])
        self.assertEqual(_omri_candidates_by_name("Feather Meal 12-0-0"), [self.feather])

    def test_the_detector_path_resolves_it_too(self):
        """⛔ The point of the tier. A grower logging "Feather Meal 12-0-0" must not collect
        a § 205.400(f)(2) finding because OMRI prints the registrant first."""
        self.assertEqual(_resolve_omri_by_name("Feather Meal 12-0-0"), self.feather)
        self.assertEqual(_resolve_omri_by_name("Surround WP"), self.surround)

    def test_one_token_buried_deep_is_search_only(self):
        """⛔ A single token merely APPEARING somewhere is a coincidence, not identity. On
        the detector's path it would let an event named "Wettable" clear a finding against
        the Serenade listing."""
        self.assertEqual(_omri_candidates_by_name("Wettable"), [])
        self.assertIsNone(_resolve_omri_by_name("Wettable"))
        self.assertEqual(_omri_candidates_by_name("Wettable", allow_prefix=True), [self.serenade_opti])

    def test_scattered_tokens_outside_the_anchor_still_do_not_match(self):
        """Contiguity is the whole safeguard — loosening it to a subsequence anywhere would
        make "Earth Meal" match the Down To Earth row, which is not that product's name."""
        self.assertEqual(_omri_candidates_by_name("Earth Meal", allow_prefix=True), [])

    def test_an_anchored_match_outranks_a_contiguous_one(self):
        """Two products can both contain "Surround"; the one that LEADS with it wins."""
        wsda_brand_first = OMRIProduct.objects.create(omri_id="zzz-1", product_name="Surround CF")
        rows = _omri_candidates_by_name("Surround", allow_prefix=True)
        self.assertEqual(rows[0], wsda_brand_first)
        self.assertIn(self.surround, rows)


class ProvisionalDraftPlanTests(TestCase):
    """A first-renewal farm gets a real comparison, reported as PROVISIONAL.

    🔴 Activation requires certifier approval evidence, which is the CORRECT gate and is not
    loosened. But it meant an operation in its FIRST certification year — the cohort the
    October outreach names by hand ("first-renewal farms facing their annual update this
    winter") — could not have an active plan until AFTER the renewal it bought Trazo to
    prepare for. The detector returned None for every event it logged, all season.

    ⛔ The fix is not just reaching the draft. A finding measured against a draft breaches a
    DIFFERENT regulation and prescribes a DIFFERENT action:

        filed plan  § 205.400(f)(2)  notify your certifier of the change
        draft plan  § 205.201(a)(2)  the plan's input list is incomplete; add it before filing

    Stamping (f)(2) on a draft told a grower to file a change notice about a plan no certifier
    has read — an instruction they cannot carry out, and the over-claim class this codebase
    keeps removing.
    """

    @classmethod
    def setUpTestData(cls):
        from company.models import Company, Establishment

        cls.company = Company.objects.create(name="Cascade Ridge LLC")
        cls.establishment = Establishment.objects.create(name="Cascade Ridge Orchards", company=cls.company, state="WA")

    def _plan(self, status, version):
        from certifications.models import OrganicSystemPlan

        return OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=version, status=status)

    def test_an_active_plan_is_preferred_and_is_not_provisional(self):
        from certifications.services.drift_detector import _osp_for_drift

        self._plan("draft", 2)
        active = self._plan("active", 1)
        osp, provisional = _osp_for_drift(self.establishment.id)
        self.assertEqual(osp, active)
        self.assertFalse(provisional)

    def test_the_newest_draft_is_used_when_nothing_is_active(self):
        from certifications.services.drift_detector import _osp_for_drift

        self._plan("draft", 1)
        newest = self._plan("draft", 2)
        osp, provisional = _osp_for_drift(self.establishment.id)
        self.assertEqual(osp, newest)
        self.assertTrue(provisional)

    def test_a_submitted_or_superseded_plan_is_not_a_fallback(self):
        """Only a DRAFT. A submitted plan is with the certifier and a superseded one has been
        replaced — neither is the plan the operator is currently writing."""
        from certifications.services.drift_detector import _osp_for_drift

        self._plan("submitted", 1)
        self._plan("superseded", 2)
        osp, provisional = _osp_for_drift(self.establishment.id)
        self.assertIsNone(osp)
        self.assertFalse(provisional)

    def test_no_plan_at_all_still_yields_nothing(self):
        from certifications.services.drift_detector import _osp_for_drift

        self.assertEqual(_osp_for_drift(self.establishment.id), (None, False))

    def test_a_draft_finding_cites_205_201_and_never_205_400(self):
        from certifications.services.drift_detector import _build_drift_warning

        draft = self._plan("draft", 1)
        warning = _build_drift_warning(
            osp=draft,
            reason="Input 'X' not in active OSP approved inputs",
            reason_code="unresolved",
            input_label="X",
            resolved_via="unresolved",
        )
        self.assertTrue(warning["provisional"])
        self.assertEqual(warning["cfr_reference"], "7 CFR 205.201(a)(2)")
        self.assertNotIn("205.400", warning["cfr_reference"])

    def test_a_draft_finding_never_calls_the_plan_active(self):
        from certifications.services.drift_detector import _build_drift_warning

        draft = self._plan("draft", 1)
        warning = _build_drift_warning(
            osp=draft,
            reason="Input 'X' not in active OSP approved inputs",
            reason_code="unresolved",
            input_label="X",
            resolved_via="unresolved",
        )
        self.assertNotIn("active OSP", warning["reason"])
        self.assertIn("draft OSP", warning["reason"])
        self.assertIn("before you submit", warning["reason"])

    def test_a_filed_plan_finding_is_unchanged(self):
        """The existing contract must not move — this is what a certifier already reads."""
        from certifications.services.drift_detector import _build_drift_warning

        active = self._plan("active", 1)
        warning = _build_drift_warning(
            osp=active,
            reason="Input 'X' not in active OSP approved inputs",
            reason_code="unresolved",
            input_label="X",
            resolved_via="unresolved",
        )
        self.assertFalse(warning["provisional"])
        self.assertEqual(warning["cfr_reference"], "7 CFR 205.400(f)(2)")
        self.assertIn("active OSP", warning["reason"])
        self.assertNotIn("before you submit", warning["reason"])

    def test_provisional_is_derived_from_the_plan_not_passed_in(self):
        """A caller that had to remember the flag would eventually forget, and the failure
        mode is a draft finding wearing a filed plan's regulation."""
        import inspect

        from certifications.services import drift_detector

        sig = inspect.signature(drift_detector._build_drift_warning)
        self.assertNotIn("provisional", sig.parameters)
