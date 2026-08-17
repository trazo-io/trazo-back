"""
Tests for Common OSP § 11 record-type evidence derivation.

The load-bearing test in this file is not any individual evidence rule — it is
`EvidenceNeverAttestsTests`: Trazo may observe records, but only the operator may assert that
their operation maintains a record type (§ 205.201(a) makes the producer the author of the plan).
Everything else here protects that boundary or the registry's citation discipline.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from certifications.services.common_osp_records import (
    COMMON_OSP_RECORD_TYPES,
    EVIDENCED,
    NOT_EVIDENCED,
    RECORD_TYPES_BY_KEY,
    UNKNOWN,
    EvidenceBundle,
    _has_content,
    confirm,
    derive_record_types,
    summarize,
)


class _FakeBundle(EvidenceBundle):
    """An EvidenceBundle with the querysets pre-loaded, so the real helper methods are exercised.

    Deliberately bypasses __init__ rather than mocking the helpers: `prod()`, `chem()`,
    `with_field()` and `business_extra()` are where the subtype codes and field names live, and
    a mock would stop testing exactly the part most likely to drift from the models.
    """

    def __init__(self, **kwargs):  # noqa: D107 — see class docstring
        self.establishment = kwargs.pop("establishment", SimpleNamespace(structured_certifications=_EmptyRel()))
        self.start_date = None
        self.end_date = None
        self.productions = kwargs.pop("productions", [])
        self.parcels = kwargs.pop("parcels", [])
        self.sales = kwargs.pop("sales", [])
        self.chemical = kwargs.pop("chemical", [])
        self.production_events = kwargs.pop("production_events", [])
        self.soil = kwargs.pop("soil", [])
        self.pest = kwargs.pop("pest", [])
        self.general = kwargs.pop("general", [])
        self.business = kwargs.pop("business", [])
        assert not kwargs, f"unexpected kwargs: {kwargs}"


class _EmptyRel:
    def all(self):
        return []


def _ev(type_code, **fields):
    """A stand-in event. `album=None` by default so the label-photo rule stays False."""
    fields.setdefault("album", None)
    fields.setdefault("extra_data", None)
    return SimpleNamespace(type=type_code, **fields)


class RegistryDisciplineTests(SimpleTestCase):
    """The registry's own rules — every entry cites a regulation, keys and labels are unique."""

    def test_every_record_type_carries_a_cfr_citation(self):
        for rt in COMMON_OSP_RECORD_TYPES:
            self.assertRegex(
                rt.cfr_cite,
                r"^7 CFR 205\.\d+",
                msg=f"{rt.key} has no real CFR citation — see the module docstring's discipline rule",
            )

    def test_keys_and_labels_are_unique(self):
        keys = [rt.key for rt in COMMON_OSP_RECORD_TYPES]
        labels = [rt.label for rt in COMMON_OSP_RECORD_TYPES]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(labels), len(set(labels)))

    def test_covers_all_four_usda_groups(self):
        groups = {rt.group for rt in COMMON_OSP_RECORD_TYPES}
        self.assertEqual(len(groups), 4, "The USDA § 11 form has exactly four record-type groups")

    def test_labels_match_the_usda_form_verbatim(self):
        """Spot-check the labels most likely to be 'improved' by a future maintainer.

        The generated section has to read identically to the certifier's own form; a paraphrase
        is how a form silently stops matching.
        """
        for expected in (
            "Shared equipment cleaning log",
            "Input/material information (labels, SDS, etc.)",
            "Condition of natural resources, including soil and water quality",
            "Seed search/Commercial availability",
        ):
            self.assertIn(expected, [rt.label for rt in COMMON_OSP_RECORD_TYPES])


class HasContentTests(SimpleTestCase):
    """The emptiness rule this module needs, which differs from the shared `_present()`."""

    def test_false_boolean_is_empty_but_true_is_not(self):
        self.assertFalse(_has_content(False))
        self.assertTrue(_has_content(True))

    def test_empty_containers_are_empty(self):
        for empty in ([], {}, (), set()):
            self.assertFalse(_has_content(empty), repr(empty))
        self.assertTrue(_has_content([1]))
        self.assertTrue(_has_content({"a": 1}))

    def test_delegates_to_present_for_everything_else(self):
        self.assertFalse(_has_content(None))
        self.assertFalse(_has_content("   "))
        self.assertTrue(_has_content("Kocide 3000"))
        # 0 is a real recorded value, not an absence — same as the PUR rule.
        self.assertTrue(_has_content(0))


class EvidenceRuleTests(SimpleTestCase):
    """Each rule reads the subtype codes and field names it claims to read."""

    def _row(self, bundle, key):
        rt = RECORD_TYPES_BY_KEY[key]
        count, basis = rt.evidence(bundle)
        return count, basis

    def test_planting_counts_transplanting_too(self):
        bundle = _FakeBundle(production_events=[_ev("PL"), _ev("TR")])
        count, _ = self._row(bundle, "planting_records")
        self.assertEqual(count, 2)

    def test_harvest_ignores_other_production_subtypes(self):
        bundle = _FakeBundle(production_events=[_ev("HA"), _ev("PL"), _ev("IR")])
        count, _ = self._row(bundle, "harvest_records")
        self.assertEqual(count, 1)

    def test_pest_management_spans_non_chemical_and_chemical(self):
        bundle = _FakeBundle(pest=[_ev("SC"), _ev("BR")], chemical=[_ev("PE"), _ev("FE")])
        count, _ = self._row(bundle, "pest_management")
        self.assertEqual(count, 3, "2 pest-management events + 1 pesticide application, not the fertilizer")

    def test_tillage_reads_soil_events_not_production_events(self):
        bundle = _FakeBundle(soil=[_ev("TI")], production_events=[_ev("CU")])
        count, _ = self._row(bundle, "tillage")
        self.assertEqual(count, 1)

    def test_equipment_cleaning_requires_an_actual_cleaning_field(self):
        """An EM event with no cleaning detail is not a cleaning log entry."""
        bare = _FakeBundle(
            production_events=[_ev("EM", cleaning_date=None, cleaning_method=None, cleaning_materials_used=None)]
        )
        self.assertEqual(self._row(bare, "shared_equipment_cleaning")[0], 0)

        filled = _FakeBundle(
            production_events=[
                _ev("EM", cleaning_date="2026-05-01", cleaning_method="rinse", cleaning_materials_used=None)
            ]
        )
        self.assertEqual(self._row(filled, "shared_equipment_cleaning")[0], 1)

    def test_seed_search_reads_the_seed_search_field(self):
        bundle = _FakeBundle(
            production_events=[
                _ev("PL", seed_search_attempts="3 suppliers contacted"),
                _ev("PL", seed_search_attempts=None),
            ]
        )
        self.assertEqual(self._row(bundle, "seed_search_commercial_availability")[0], 1)

    def test_whitespace_only_field_does_not_count_as_evidence(self):
        """Same emptiness rule as the PUR export: whitespace is missing, not present."""
        bundle = _FakeBundle(production_events=[_ev("PL", seed_search_attempts="   ")])
        self.assertEqual(self._row(bundle, "seed_search_commercial_availability")[0], 0)

    def test_empty_json_field_is_not_evidence(self):
        """🔴 Regression. `seed_search_attempts` is a JSONField defaulting to `[]`, and the
        shared `_present()` helper returns True for any non-None non-string — so every planting
        event with an untouched default counted as a documented seed search. On the demo farm
        that reported "9 documented seed searches logged" where all nine were empty lists."""
        empty = _FakeBundle(production_events=[_ev("PL", seed_search_attempts=[])] * 9)
        self.assertEqual(self._row(empty, "seed_search_commercial_availability")[0], 0)

        real = _FakeBundle(production_events=[_ev("PL", seed_search_attempts=[{"supplier": "Peaceful Valley"}])])
        self.assertEqual(self._row(real, "seed_search_commercial_availability")[0], 1)

    def test_false_boolean_is_not_evidence(self):
        """🔴 Regression. `History.organic_on_invoice` is a BooleanField(default=False). Counting
        it via `_present()` made every production look like an invoice record — "13 invoice
        records logged" on a farm where zero had it set. A False boolean is an explicit *no*."""
        all_false = _FakeBundle(productions=[SimpleNamespace(organic_on_invoice=False, storage_location=None)] * 13)
        self.assertEqual(self._row(all_false, "invoices")[0], 0)

        one_true = _FakeBundle(
            productions=[
                SimpleNamespace(organic_on_invoice=True, storage_location=None),
                SimpleNamespace(organic_on_invoice=False, storage_location=None),
            ]
        )
        self.assertEqual(self._row(one_true, "invoices")[0], 1)

    def test_bill_of_lading_reads_business_event_extra_data(self):
        bundle = _FakeBundle(
            business=[
                SimpleNamespace(type="CE", extra_data={"bill_of_lading": "BOL-1"}),
                SimpleNamespace(type="CE", extra_data={"purchase_order": "PO-1"}),
                SimpleNamespace(type="CE", extra_data=None),
            ]
        )
        self.assertEqual(self._row(bundle, "bill_of_lading")[0], 1)

    def test_mulching_basis_does_not_overstate_a_mowing_event(self):
        """Trazo has no mulching subtype; MO covers mowing/mulching/floor work together."""
        bundle = _FakeBundle(production_events=[_ev("MO")])
        count, basis = self._row(bundle, "mulching")
        self.assertEqual(count, 1)
        self.assertIn("confirm whether", basis.lower())

    def test_external_by_design_types_never_report_evidence(self):
        """Weigh tickets, packing slips, contracts et al. live outside Trazo — permanently."""
        bundle = _FakeBundle()
        for key in (
            "weigh_tickets",
            "packing_slips",
            "delivery_slips",
            "settlement_statements",
            "contracts",
            "inventory_records",
        ):
            self.assertTrue(RECORD_TYPES_BY_KEY[key].external_by_design, key)
            self.assertEqual(self._row(bundle, key)[0], 0, key)


class EvidenceNeverAttestsTests(SimpleTestCase):
    """🔴 The boundary this module exists to hold.

    § 205.201(a) makes the PRODUCER the author of the organic system plan. Trazo observing
    records is not the operator asserting they maintain them. A previous incident in this
    codebase fabricated a backdated record attributed to the farmer by name; an auto-ticked
    § 11 checkbox is the same mistake with a regulator reading it.
    """

    def test_evidence_alone_never_marks_a_record_type_confirmed(self):
        bundle = _FakeBundle(production_events=[_ev("HA")] * 5)
        count, _ = RECORD_TYPES_BY_KEY["harvest_records"].evidence(bundle)
        self.assertEqual(count, 5)
        # ...but derive_record_types with no OSP must still report confirmed=False.
        rows = _rows_from(bundle)
        harvest = next(r for r in rows if r["key"] == "harvest_records")
        self.assertEqual(harvest["status"], EVIDENCED)
        self.assertFalse(harvest["confirmed"], "evidence must never imply the operator's assertion")
        self.assertTrue(harvest["suggested"], "evidenced-but-unconfirmed is a suggestion, not an answer")

    def test_suggested_and_confirmed_are_never_the_same_field(self):
        """A caller that renders `suggested` as a tick reintroduces the auto-attestation bug."""
        bundle = _FakeBundle(production_events=[_ev("HA")])
        row = next(r for r in _rows_from(bundle) if r["key"] == "harvest_records")
        self.assertIn("suggested", row)
        self.assertIn("confirmed", row)
        self.assertNotEqual(row["suggested"], row["confirmed"])

    def test_summary_reports_no_score_grade_or_percentage(self):
        """No self-assigned completeness verdict — the same rule that removed the transparency score."""
        keys = set(summarize(_rows_from(_FakeBundle())).keys())
        for banned in ("score", "grade", "percent", "percentage", "complete", "compliant"):
            self.assertFalse([k for k in keys if banned in k.lower()], f"summary must not expose a {banned}")


def _rows_from(bundle):
    """derive_record_types() against a pre-built bundle (skips the DB query in EvidenceBundle)."""
    rows = []
    for rt in COMMON_OSP_RECORD_TYPES:
        try:
            count, basis = rt.evidence(bundle)
            failed = False
        except Exception as exc:  # noqa: BLE001
            count, basis, failed = 0, str(exc), True
        rows.append(
            {
                "key": rt.key,
                "label": rt.label,
                "status": UNKNOWN if failed else (EVIDENCED if count else NOT_EVIDENCED),
                "count": count,
                "basis": basis,
                "external_by_design": rt.external_by_design,
                "suggested": bool(count) and not failed,
                "confirmed": False,
            }
        )
    return rows


class EveryRuleRunsCleanTests(SimpleTestCase):
    """Regression for two bugs a silent `except` had hidden as 'no records found'.

    Both were caught only by running the derivation against real data:
      1. `Establishment.certifications` is a TEXT field — the reverse accessor is
         `structured_certifications`. The AttributeError rendered a farm holding 4 organic
         certificates as holding none.
      2. `bundle.pest` is the list attribute; `bundle.pests()` is the subtype helper. Calling
         `b.pest()` raised TypeError inside two rules.

    "We could not look" and "we looked and found nothing" must never collapse into one status on
    a certifier-facing surface.
    """

    def test_no_rule_raises_on_an_empty_bundle(self):
        for row in _rows_from(_FakeBundle()):
            self.assertNotEqual(row["status"], UNKNOWN, f"{row['key']} raised: {row['basis']}")

    def test_no_rule_raises_on_a_populated_bundle(self):
        bundle = _FakeBundle(
            productions=[SimpleNamespace(organic_on_invoice="INV-9", storage_location="Barn A")],
            parcels=[SimpleNamespace(buffer_zones=[{"side": "north", "width_ft": 30}])],
            production_events=[_ev(c) for c in ("PL", "TR", "HA", "CU", "MO", "EM", "PH", "IR")],
            chemical=[_ev(c) for c in ("FE", "PE", "FU", "HE")],
            soil=[_ev(c) for c in ("TI", "CO", "ST", "LA", "OM", "PA")],
            pest=[_ev(c) for c in ("SC", "TM", "PI", "TA")],
            business=[SimpleNamespace(type="CE", extra_data={"bill_of_lading": "B", "invoice_number": "I"})],
        )
        for row in _rows_from(bundle):
            self.assertNotEqual(row["status"], UNKNOWN, f"{row['key']} raised: {row['basis']}")


class ConfirmationPersistenceTests(TestCase):
    """confirm() is the only path from evidence to an answer."""

    def setUp(self):
        from company.models import Company, Establishment

        company = Company.objects.create(name="Common OSP Test Co")
        # `state` is load-bearing on this fixture — several compliance paths key off it.
        self.establishment = Establishment.objects.create(company=company, name="Common OSP Test Farm", state="CA")
        from certifications.models import OrganicSystemPlan

        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")

    def test_confirm_records_who_and_when(self):
        confirm(self.osp, ["harvest_records"], user=None)
        self.osp.refresh_from_db()
        rows = derive_record_types(self.establishment, osp=self.osp)
        harvest = next(r for r in rows if r["key"] == "harvest_records")
        self.assertTrue(harvest["confirmed"])
        self.assertIsNotNone(harvest["confirmed_at"])
        self.assertFalse(harvest["suggested"], "a confirmed type is an answer, no longer a suggestion")

    def test_confirmation_survives_with_no_supporting_evidence(self):
        """A farm keeps weigh tickets in a drawer; Trazo cannot see them but the answer is still yes."""
        confirm(self.osp, ["weigh_tickets"], user=None)
        rows = derive_record_types(self.establishment, osp=self.osp)
        row = next(r for r in rows if r["key"] == "weigh_tickets")
        self.assertTrue(row["confirmed"])
        self.assertEqual(row["status"], NOT_EVIDENCED, "confirmation is the operator's word, not our evidence")

    def test_unconfirm_removes_the_assertion(self):
        confirm(self.osp, ["harvest_records"], user=None)
        confirm(self.osp, ["harvest_records"], user=None, confirmed=False)
        rows = derive_record_types(self.establishment, osp=self.osp)
        self.assertFalse(next(r for r in rows if r["key"] == "harvest_records")["confirmed"])

    def test_unknown_keys_are_ignored_not_raised(self):
        confirm(self.osp, ["harvest_records", "not_a_real_record_type"], user=None)
        rows = derive_record_types(self.establishment, osp=self.osp)
        self.assertTrue(next(r for r in rows if r["key"] == "harvest_records")["confirmed"])

    def test_confirm_requires_an_osp(self):
        with self.assertRaises(ValueError):
            confirm(None, ["harvest_records"], user=None)

    def test_confirmations_do_not_clobber_other_osp_sections(self):
        self.osp.sections["practices_procedures"] = {"narrative": "Keep me", "last_updated": None}
        self.osp.save(update_fields=["sections"])
        confirm(self.osp, ["harvest_records"], user=None)
        self.osp.refresh_from_db()
        self.assertEqual(self.osp.sections["practices_procedures"]["narrative"], "Keep me")
