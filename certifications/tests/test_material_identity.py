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
        self.assertIn(f"Also logged as '{LOGGED}'", planned.identity)
        self.assertIn("identified by the operator", planned.identity)

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
