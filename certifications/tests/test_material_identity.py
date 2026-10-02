"""The operator decides what a logged product name IS; nothing is inferred (OSP alignment T18, Phase 5 slice 2).

Oscar's acceptance list (2026-10-02), one test or more each: a formulation difference never resolves
silently; a National List substance is never an identity target; an edited event or a later one is not
covered; exceptions are honoured; overlap is refused and supersession keeps history; the history is
append-only; one operation's decisions never reach another's; a decision answers "not matched" and
nothing else, so an approval or CDFA finding on the identified product stands; and no event field,
classification or plan approval changes.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import MaterialIdentityDecision as MID
from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, PlanMaterialEntry
from certifications.services.common_osp_workbooks import IDENTITY_NOT_CONFIRMED, _material_rows
from certifications.services.material_identity import (
    COVERED,
    EXCEPTED,
    STALE,
    UNREVIEWED,
    IdentityError,
    coverage,
    record_decision,
)
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel
from users.models import User, WorksIn

LOGGED = "Neptune's Harvest Fish Fertilizer 2-3-1"
PLANNED = "Neptune's Harvest Organic Fish Fertilizer 2-4-1"


def _history(est, user):
    parcel = Parcel.objects.create(name=f"P{est.pk}", establishment=est, area=1.0)
    return History.objects.create(name="H", start_date=timezone.now(), parcel=parcel, operator=user)


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="id@test.com", password="x", is_verified=True, first_name="Laurel")
        self.company = Company.objects.create(name="Identity Farms")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Home", company=self.company, state="OR")
        self.history = _history(self.est, self.user)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        self.omri = OMRIProduct.objects.create(omri_id="nhf-0644", product_name=PLANNED, category="fertilizer")
        self.osp.approved_omri_products.add(self.omri)
        self.spray = [self._spray(LOGGED) for _ in range(3)]

    def _spray(self, name, history=None, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return ChemicalEvent.objects.create(
                history=history or self.history,
                date=timezone.now(),
                description="spray",
                commercial_name=name,
                **kwargs,
            )

    def _decide(self, **overrides):
        data = {
            "source": "chemical",
            "logged_name": LOGGED,
            "decision": MID.SAME_AS,
            "target_kind": MID.TARGET_OMRI,
            "target_id": self.omri.pk,
            "event_ids": [e.pk for e in self.spray],
            "formulation_difference_acknowledged": True,
            "formulation_note": "Same fish fertilizer; the label analysis was updated.",
        }
        data.update(overrides)
        return record_decision(self.osp, self.user, data)


class FormulationAndTargetTests(_Farm):
    def test_a_formulation_difference_never_resolves_silently(self):
        for overrides in ({"formulation_difference_acknowledged": False}, {"formulation_note": ""}):
            with self.subTest(**overrides), self.assertRaises(IdentityError) as err:
                self._decide(**overrides)
            self.assertEqual(err.exception.field, "formulation_difference_acknowledged")
        self.assertFalse(MID.objects.exists())
        self.assertEqual(self._decide().decision, MID.SAME_AS)

    def test_a_national_list_substance_is_never_an_identity_target(self):
        substance = NationalListSubstance.objects.create(
            substance_name="Fish emulsion", substance_name_normalized="fish emulsion", cfr_section="205.601"
        )
        self.osp.approved_national_list_substances.add(substance)
        with self.assertRaises(IdentityError) as err:
            self._decide(target_kind="national_list", target_id=substance.pk)
        self.assertIn("classification, not a product", str(err.exception))

    def test_a_target_must_be_on_the_plan(self):
        other = OMRIProduct.objects.create(omri_id="xx-1", product_name="Not On Plan 2-3-1")
        with self.assertRaises(IdentityError):
            self._decide(target_id=other.pk)


class OwnershipTests(_Farm):
    def test_another_establishment_of_the_same_company_is_refused(self):
        sister = Establishment.objects.create(name="Sister", company=self.company)
        foreign_event = self._spray(LOGGED, history=_history(sister, self.user))
        with self.assertRaises(IdentityError) as err:
            self._decide(event_ids=[self.spray[0].pk, foreign_event.pk])
        self.assertEqual(err.exception.status_code, 404)

    def test_another_company_cannot_read_or_decide(self):
        outsider = User.objects.create_user(email="out@test.com", password="x", is_verified=True)
        other = Company.objects.create(name="Other")
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        client = APIClient()
        client.force_authenticate(outsider)
        url = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.osp.pk}/material-identities/"
        self.assertIn(client.get(url).status_code, (403, 404))
        res = client.post(
            url,
            {
                "source": "chemical",
                "logged_name": LOGGED,
                "decision": "different_product",
                "event_ids": [self.spray[0].pk],
            },
            format="json",
        )
        self.assertIn(res.status_code, (403, 404))
        self.assertFalse(MID.objects.exists())

    def test_the_owner_reads_and_decides_through_the_api(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.osp.pk}/material-identities/"
        body = client.get(url).json()
        self.assertEqual(body["targets"], [{"kind": "omri", "id": self.omri.pk, "name": PLANNED}])
        listed = body["identities"]
        row = next(r for r in listed if r["logged_name"] == LOGGED)
        self.assertEqual({e["state"] for e in row["events"]}, {UNREVIEWED})
        res = client.post(
            url,
            {
                "source": "chemical",
                "logged_name": LOGGED,
                "decision": "different_product",
                "event_ids": [e.pk for e in self.spray],
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content[:300])


class CoverageTests(_Farm):
    def test_coverage_is_per_event_and_per_content(self):
        excluded = self.spray[2]
        self._decide(exceptions=[{"event_id": excluded.pk, "reason": "Logged on the wrong block; checking the label."}])
        self.assertEqual(coverage(self.spray[0], "chemical").state, COVERED)
        self.assertEqual(coverage(excluded, "chemical").state, EXCEPTED)
        later = self._spray(LOGGED)
        self.assertEqual(coverage(later, "chemical").state, UNREVIEWED, "a later event was covered by name alone")
        edited = self.spray[1]
        edited.description = "spray, north rows"  # not identity content
        edited.save()
        self.assertEqual(coverage(edited, "chemical").state, COVERED)
        edited.manufacturer = "Another Maker"
        edited.save()
        self.assertEqual(coverage(edited, "chemical").state, STALE, "an edited manufacturer stayed covered")
        edited.manufacturer = None
        edited.epa_registration_number = "1234-5"
        edited.save()
        self.assertEqual(coverage(edited, "chemical").state, STALE)


class HistoryTests(_Farm):
    def test_overlap_is_refused_and_supersession_keeps_history(self):
        first = self._decide()
        with self.assertRaises(IdentityError) as err:
            self._decide(decision=MID.DIFFERENT_PRODUCT, target_kind="", target_id=None)
        self.assertEqual(err.exception.status_code, 409)
        second = record_decision(
            self.osp,
            self.user,
            {
                "source": "chemical",
                "logged_name": LOGGED,
                "decision": MID.DIFFERENT_PRODUCT,
                "event_ids": [e.pk for e in self.spray],
                "supersedes": first.pk,
            },
        )
        first.refresh_from_db()
        self.assertIsNotNone(first.superseded_at)
        self.assertEqual(second.supersedes_id, first.pk)
        self.assertEqual(MID.objects.filter(name_key=first.name_key).count(), 2)

    def test_one_current_decision_per_name_even_when_two_arrive_at_once(self):
        self._decide()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MID.objects.create(
                establishment=self.est,
                osp=self.osp,
                source="chemical",
                logged_name=LOGGED,
                name_key=MID.objects.first().name_key,
                decision=MID.DIFFERENT_PRODUCT,
                decided_at=timezone.now(),
            )

    def test_the_history_is_append_only(self):
        decision = self._decide()
        decision.note = "rewritten"
        with self.assertRaises(ValidationError):
            decision.save()
        with self.assertRaises(ValidationError):
            decision.delete()
        with self.assertRaises(ValidationError):
            MID.objects.filter(pk=decision.pk).update(note="rewritten")
        with self.assertRaises(ValidationError):
            MID.objects.filter(pk=decision.pk).delete()


class SeparationTests(_Farm):
    def test_a_decision_changes_no_event_classification_or_approval(self):
        def snapshot():
            events = list(
                ChemicalEvent.objects.filter(pk__in=[e.pk for e in self.spray]).values(
                    "commercial_name",
                    "omri_product_id",
                    "wsda_material_id",
                    "national_list_substance_id",
                    "national_list_basis",
                    "national_list_suggestion_id",
                )
            )
            plan = (
                set(self.osp.approved_omri_products.values_list("pk", flat=True)),
                set(self.osp.approved_wsda_materials.values_list("pk", flat=True)),
                set(self.osp.approved_national_list_substances.values_list("pk", flat=True)),
                PlanMaterialEntry.objects.filter(osp=self.osp).count(),
            )
            return events, plan

        before = snapshot()
        self._decide()
        self.assertEqual(snapshot(), before)


class DriftScopeTests(_Farm):
    def _warning(self, event):
        from certifications.services.drift_detector import evaluate_chemical_event

        # Fresh from the database, as every recompute path loads it: `_evaluate` compares with the
        # instance's own `drift_warning`.
        fresh = ChemicalEvent.objects.get(pk=event.pk)
        evaluate_chemical_event(fresh)
        fresh.refresh_from_db()
        return fresh.drift_warning

    def test_an_unreviewed_name_is_unresolved(self):
        warning = self._warning(self.spray[0])
        self.assertIsNotNone(warning)
        self.assertEqual(warning["reason_code"], "unresolved")

    def test_a_covering_decision_answers_not_matched_and_nothing_else(self):
        self._decide()
        self.assertIsNone(self._warning(self.spray[0]))
        # A later event under the same name is not covered: still unresolved.
        self.assertEqual(self._warning(self._spray(LOGGED))["reason_code"], "unresolved")

    def test_the_identified_products_own_approval_finding_stands(self):
        self._decide()
        self.osp.approved_omri_products.remove(self.omri)
        warning = self._warning(self.spray[0])
        self.assertIsNotNone(warning, "an identity decision cleared an approval finding")
        self.assertEqual(warning["reason_code"], "name_omri_not_in_osp")
        self.assertIn("identified by the operator", warning["reason"])

    def test_a_cdfa_finding_on_the_identified_product_stands(self):
        self.est.state = "CA"
        self.est.save(update_fields=["state"])
        self._decide()
        warning = self._warning(self.spray[0])
        self.assertIsNotNone(warning, "an identity decision cleared a CDFA finding")
        self.assertEqual(warning["reason_code"], "approved_with_issues")
        self.assertIn("cdfa_unknown", warning["reason_params"]["issues"])


class WorkbookTests(_Farm):
    def _row(self, name):
        return next((r for r in _material_rows(self.est, self.osp) if r.name == name), None)

    def test_an_unidentified_name_says_so(self):
        self.assertEqual(self._row(LOGGED).identity, IDENTITY_NOT_CONFIRMED)

    def test_an_identified_name_joins_its_plan_row_with_the_basis(self):
        self._decide()
        self.assertIsNone(self._row(LOGGED), "the name stayed its own row")
        planned = self._row(PLANNED)
        from certifications.services.common_osp_workbooks import _material_comments

        comments = _material_comments(planned)
        self.assertIn(f"Also logged as '{LOGGED}'", comments)
        self.assertIn("identified by the operator", comments)
        self.assertIsNone(planned.event, "the plan row took another record's event")

    def test_a_partly_reviewed_name_is_not_confirmed(self):
        self._decide()
        self._spray(LOGGED)
        self.assertEqual(self._row(LOGGED).identity, IDENTITY_NOT_CONFIRMED)

    def test_a_different_product_stays_its_own_row_with_the_basis(self):
        record_decision(
            self.osp,
            self.user,
            {
                "source": "chemical",
                "logged_name": LOGGED,
                "decision": MID.DIFFERENT_PRODUCT,
                "event_ids": [e.pk for e in self.spray],
            },
        )
        self.assertIn("a different product", self._row(LOGGED).identity)


class ReviewOfBack98Tests(_Farm):
    def test_malformed_ids_are_a_400_never_a_500(self):
        for bad in (
            {"event_ids": ["abc"]},
            {"exceptions": [{"event_id": "x", "reason": "r"}]},
            {"exceptions": ["not-a-row"]},
            {"supersedes": "nope"},
        ):
            with self.subTest(**{k: str(v) for k, v in bad.items()}):
                try:
                    self._decide(**bad)
                    raised = None
                except Exception as exc:  # noqa: BLE001 - the type IS the assertion
                    raised = exc
                self.assertIsInstance(raised, IdentityError, f"{bad} raised {raised!r}, a 500")
                self.assertEqual(raised.status_code, 400)

    def test_a_sanitizer_decision_names_only_post_harvest_events(self):
        from history.models import ProductionEvent

        not_ph = ProductionEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="irrigation",
            type="IR",
            sanitizer_name="SaniDate 5.0",
        )
        with self.assertRaises(IdentityError) as err:
            record_decision(
                self.osp,
                self.user,
                {
                    "source": "sanitizer",
                    "logged_name": "SaniDate 5.0",
                    "decision": MID.DIFFERENT_PRODUCT,
                    "event_ids": [not_ph.pk],
                },
            )
        self.assertEqual(err.exception.status_code, 404)

    def test_each_merged_name_keeps_its_own_records_listing_note(self):
        from certifications.services.common_osp_workbooks import _material_comments

        substance = NationalListSubstance.objects.create(
            substance_name="Fish product",
            substance_name_normalized="fish product",
            cfr_section="205.602",
            status="prohibited",
        )
        ChemicalEvent.objects.filter(pk__in=[e.pk for e in self.spray]).update(
            national_list_substance=substance, national_list_basis="operator"
        )
        self._decide()
        comments = _material_comments(next(r for r in _material_rows(self.est, self.osp) if r.name == PLANNED))
        self.assertIn(f"Also logged as '{LOGGED}'", comments)
        self.assertIn("205.602", comments, "the identified record's own listing note was lost")

    def test_the_identity_finding_carries_its_verification_dates(self):
        from certifications.services.drift_detector import evaluate_chemical_event

        self.est.state = "CA"
        self.est.save(update_fields=["state"])
        self._decide()
        fresh = ChemicalEvent.objects.get(pk=self.spray[0].pk)
        evaluate_chemical_event(fresh)
        fresh.refresh_from_db()
        self.assertIsNotNone(fresh.drift_warning)
        self.assertTrue(fresh.drift_warning.get("cdfa_oim_verified_at"))
        self.assertTrue(fresh.drift_warning.get("omri_verified_at"))


# ---------------------------------------------------------------------------------------------
# Phase 5 slice 2b: restriction statements (Oscar's rules, 2026-10-02).
# ---------------------------------------------------------------------------------------------
from certifications.models import PlanMaterialRestrictionStatement as PRS  # noqa: E402
from certifications.services.material_restrictions import (  # noqa: E402
    APPLICABILITY_NOT_ESTABLISHED,
    NEEDS_REVIEW,
    NOT_DOCUMENTED,
    TRANSCRIBED_LABEL,
    RestrictionError,
    material_restriction_text,
    record_statement,
    statement_state,
)


class _Restrictions(_Farm):
    def setUp(self):
        super().setUp()
        self.calcium = NationalListSubstance.objects.create(
            substance_name="Calcium chloride",
            substance_name_normalized="calcium chloride",
            cfr_section="205.602",
            subsection="c",
            status="prohibited",
            annotation_kind="condition_of_use",
            restriction_notes="Allowed only as a foliar spray to treat a physiological disorder associated with calcium uptake.",
            effective_date=timezone.now().date().replace(year=2023, month=1, day=1),
        )
        self.osp.approved_national_list_substances.add(self.calcium)

    def _transcribed(self, **overrides):
        data = {
            "material_kind": "omri",
            "material_id": self.omri.pk,
            "restriction_source": "operator_transcribed",
            "restriction_text": "Apply no more than 5 gal/acre per application.",
            "source_type": "product_label",
            "source_identifier": "Label rev. 2025-03",
            "source_locator": "Directions for use, p. 2",
            "how_met": "Calibrated sprayer delivers 3 gal/acre; logged on every application.",
        }
        data.update(overrides)
        return record_statement(self.osp, self.user, data)


class RestrictionStatementTests(_Restrictions):
    def test_regulation_text_keeps_its_citation_and_never_claims_applicability(self):
        statement = record_statement(
            self.osp,
            self.user,
            {
                "material_kind": "national_list",
                "material_id": self.calcium.pk,
                "restriction_source": "regulation",
                "how_met": "Foliar only, for bitter pit.",
            },
        )
        self.assertEqual((statement.citation, statement.source_effective_date.year), ("§ 205.602(c)", 2023))
        printed = material_restriction_text(self.osp, "national_list", self.calcium.pk)
        self.assertIn("regulation wording held by Trazo, effective 2023-01-01", printed)
        self.assertIn(APPLICABILITY_NOT_ESTABLISHED, printed)
        self.assertIn("the operator's statement, not a compliance finding", printed)

    def test_regulation_text_is_refused_where_trazo_holds_none(self):
        with self.assertRaises(RestrictionError):
            self._transcribed(restriction_source="regulation")
        # A § 205.601 catalogue note is descriptive, not the rule's wording: never offered as regulation.
        sulfur = NationalListSubstance.objects.create(
            substance_name="Lime sulfur",
            substance_name_normalized="lime sulfur",
            cfr_section="205.601",
            status="allowed",
            restriction_notes="For use as an insecticide, fungicide.",
        )
        self.osp.approved_national_list_substances.add(sulfur)
        with self.assertRaises(RestrictionError):
            record_statement(
                self.osp,
                self.user,
                {
                    "material_kind": "national_list",
                    "material_id": sulfur.pk,
                    "restriction_source": "regulation",
                    "how_met": "x",
                },
            )
        self.assertEqual(material_restriction_text(self.osp, "national_list", sulfur.pk), NOT_DOCUMENTED)

    def test_a_transcription_is_labelled_unverified_with_its_source(self):
        self._transcribed()
        printed = material_restriction_text(self.osp, "omri", self.omri.pk)
        self.assertIn(TRANSCRIBED_LABEL, printed)
        self.assertIn("Label rev. 2025-03, Directions for use, p. 2", printed)

    def test_a_material_can_carry_several_restrictions(self):
        self._transcribed()
        self._transcribed(restriction_text="Do not apply within 3 days of harvest.", how_met="Harvest log checked.")
        self.assertEqual(PRS.objects.filter(superseded_at__isnull=True).count(), 2)

    def test_missing_restriction_text_reads_not_documented_never_none(self):
        printed = material_restriction_text(self.osp, "omri", self.omri.pk)
        self.assertEqual(printed, NOT_DOCUMENTED)
        self.assertNotIn("no restriction", printed.lower())
        held = material_restriction_text(self.osp, "national_list", self.calcium.pk)
        self.assertIn("How it is met: not stated.", held)

    def test_material_and_attachment_must_belong_to_this_plan(self):
        with self.assertRaises(RestrictionError) as err:
            self._transcribed(material_id=999999)
        self.assertEqual(err.exception.status_code, 404)
        from documents.models import GeneratedDocument

        other = Establishment.objects.create(name="Other", company=Company.objects.create(name="Other Co"))
        doc = GeneratedDocument.objects.create(establishment=other, title="label", source="upload")
        with self.assertRaises(RestrictionError) as err:
            self._transcribed(attachment=doc.pk)
        self.assertEqual(err.exception.status_code, 404)

    def test_history_is_kept_and_a_change_supersedes_explicitly(self):
        first = self._transcribed()
        with self.assertRaises(RestrictionError) as err:
            self._transcribed(how_met="New method.")
        self.assertEqual(err.exception.status_code, 409)
        second = self._transcribed(how_met="New method.", supersedes=first.pk)
        first.refresh_from_db()
        self.assertIsNotNone(first.superseded_at)
        self.assertEqual(second.supersedes_id, first.pk)
        with self.assertRaises(ValidationError):
            second.delete()
        with self.assertRaises(ValidationError):
            PRS.objects.filter(pk=second.pk).update(how_met="edited")

    def test_a_changed_plan_restriction_or_material_needs_review(self):
        statement = record_statement(
            self.osp,
            self.user,
            {
                "material_kind": "national_list",
                "material_id": self.calcium.pk,
                "restriction_source": "regulation",
                "how_met": "Foliar only.",
            },
        )
        self.assertNotEqual(statement_state(statement, self.osp), NEEDS_REVIEW)
        v2 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=2, status="draft")
        v2.approved_national_list_substances.add(self.calcium)
        self.assertEqual(statement_state(statement, v2), NEEDS_REVIEW)
        NationalListSubstance.objects.filter(pk=self.calcium.pk).update(restriction_notes="Changed text.")
        self.assertEqual(statement_state(statement, self.osp), NEEDS_REVIEW)
        transcribed = self._transcribed()
        self.osp.approved_omri_products.remove(self.omri)
        self.assertEqual(statement_state(transcribed, self.osp), NEEDS_REVIEW)

    def test_a_statement_clears_no_finding_and_approves_nothing(self):
        from certifications.services.drift_detector import evaluate_chemical_event

        fresh = ChemicalEvent.objects.get(pk=self.spray[0].pk)
        evaluate_chemical_event(fresh)
        fresh.refresh_from_db()
        before = (fresh.drift_warning["reason_code"], set(self.osp.approved_omri_products.values_list("pk", flat=True)))
        self._transcribed()
        fresh = ChemicalEvent.objects.get(pk=self.spray[0].pk)
        evaluate_chemical_event(fresh)
        fresh.refresh_from_db()
        after = (fresh.drift_warning["reason_code"], set(self.osp.approved_omri_products.values_list("pk", flat=True)))
        self.assertEqual(after, before)

    def test_the_materials_workbook_prints_each_rows_restrictions(self):
        from certifications.services.common_osp_workbooks import _material_comments

        self._transcribed()
        row = next(r for r in _material_rows(self.est, self.osp) if r.name == PLANNED)
        self.assertIn(TRANSCRIBED_LABEL, _material_comments(row, row.osp) or "")
        calcium = next(r for r in _material_rows(self.est, self.osp) if r.name == "Calcium chloride")
        self.assertIn("How it is met: not stated.", _material_comments(calcium, calcium.osp) or "")

    def test_statements_belong_to_their_plan_version(self):
        """Review of back #99: another version's statement is never listed as this version's answer."""
        from certifications.services.material_restrictions import restrictions_view

        first = self._transcribed()
        v2 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=2, status="draft")
        v2.approved_omri_products.add(self.omri)
        row = next(m for m in restrictions_view(v2) if m["material_kind"] == "omri")
        self.assertEqual((row["statements"], row["history"]), ([], []))
        self.assertEqual([s["id"] for s in row["earlier_versions"]], [first.pk])
        self.assertEqual(row["earlier_versions"][0]["state"], NEEDS_REVIEW)
        self.assertIn("[REVIEW] A restriction statement recorded on plan version 1 is on file", row["printed"])
        self.assertNotIn(first.how_met, row["printed"])
        restated = record_statement(
            v2,
            self.user,
            {
                "material_kind": "omri",
                "material_id": self.omri.pk,
                "restriction_source": "operator_transcribed",
                "restriction_text": first.restriction_text,
                "source_type": "product_label",
                "source_identifier": first.source_identifier,
                "how_met": "Restated for v2.",
            },
        )
        row = next(m for m in restrictions_view(v2) if m["material_kind"] == "omri")
        self.assertEqual([s["id"] for s in row["statements"]], [restated.pk])
        self.assertNotIn("[REVIEW]", row["printed"])
        self.assertEqual([s["id"] for s in row["earlier_versions"]], [first.pk], "own statement listed as earlier")
        v1_row = next(m for m in restrictions_view(self.osp) if m["material_kind"] == "omri")
        self.assertEqual([s["id"] for s in v1_row["statements"]], [first.pk], "v1 keeps its own statement")
