"""F25 — the § 205.201(a)(5) split-operation declaration has exactly ONE editor.

## What went wrong

`Establishment.has_split_operation` (a switch on the farm profile) and OSP module G6.0's
`split_operation` answer recorded the same regulated fact with nothing binding them. The
Calapooia Bend rehearsal answered "yes, we sell the buffer rows conventional" in the OSP
wizard and then filed a packet whose § 205.272 row read **"Split Operation: No"**, followed
by a REVIEW telling the operator that the two statements inside their own packet disagreed
— about a question they had already answered in the place the regulation cares about.

## Why it mattered

§ 205.272(a) binds any operation producing both organic and non-organic product. A packet
that reports the wrong side of that question sends an inspector looking for commingling
controls that the plan says, two pages earlier, are in place — or worse, tells them none
are needed. The export was taught to prefer the OSP answer, which removed the contradiction
from the document; these tests pin the fix at the SOURCE, which is where a second editor
could reintroduce it.

## What is pinned here

  1. Saving the G6.0 answer WRITES THROUGH to the establishment columns, in the same
     transaction (`bindings.establishment_writes` + `OSPViewSet.module_detail`).
  2. Deleting the answer clears the column — a withdrawn declaration must not stand.
  3. The establishment write serializer REFUSES the two columns. They were writable for the
     farm-profile switch; that is what made the profile a second editor.
  4. The declaration resolves to three states, never two: a `False` column nobody has
     touched is UNANSWERED, not a declared "no".
  5. Every question that declares `establishment_field` names a real column, and the
     coercion matches the column's type — a typo here writes nothing and fails silently.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.bindings import bound_establishment_fields, establishment_writes
from certifications.services.split_operation import DECLARED_NO, DECLARED_YES, UNANSWERED, split_operation_declaration
from company.models import Company, Establishment
from users.models import User, WorksIn


class SplitOperationBindingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Brandt Family Farms LLC")
        self.user = User.objects.create_user(email="split@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        self.client.force_authenticate(user=self.user)

    def _module_url(self, key="g6_0_production"):
        return (
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}"
            f"/osps/{self.osp.id}/modules/{key}/"
        )

    # --- 1. write-through -----------------------------------------------------------

    def test_answering_g6_0_writes_the_declaration_onto_the_establishment(self):
        """The packet's § 205.272 row reads the column; the OSP answer must reach it."""
        response = self.client.put(
            self._module_url(),
            {
                "answers": {
                    "split_operation": True,
                    "split_operation_separation": (
                        "Buffer rows are picked last into labelled conventional lugs, "
                        "weighed on the same scale with a separate ticket book, and hauled "
                        "on a cleaned trailer with the cleaning logged."
                    ),
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.establishment.refresh_from_db()
        self.assertTrue(self.establishment.has_split_operation)
        self.assertIn("labelled conventional lugs", self.establishment.split_operation_plan)
        # …and the resolver agrees, which is what the profile card renders.
        self.assertEqual(split_operation_declaration(self.establishment), DECLARED_YES)

    def test_answering_no_writes_false_rather_than_leaving_the_old_yes_standing(self):
        self.establishment.has_split_operation = True
        self.establishment.save(update_fields=["has_split_operation"])

        response = self.client.put(self._module_url(), {"answers": {"split_operation": False}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        self.establishment.refresh_from_db()
        self.assertFalse(self.establishment.has_split_operation)
        self.assertEqual(split_operation_declaration(self.establishment), DECLARED_NO)

    def test_deleting_the_answer_clears_the_column(self):
        """A withdrawn declaration must not keep standing in the packet."""
        self.client.put(self._module_url(), {"answers": {"split_operation": True}}, format="json")
        self.establishment.refresh_from_db()
        self.assertTrue(self.establishment.has_split_operation)

        response = self.client.put(self._module_url(), {"answers": {"split_operation": None}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        self.establishment.refresh_from_db()
        self.assertFalse(self.establishment.has_split_operation)
        self.assertEqual(split_operation_declaration(self.establishment), UNANSWERED)

    def test_clearing_an_already_empty_text_column_writes_nothing(self):
        """`None` and `""` are the same emptiness on a `null=True, blank=True` column, and which
        one is stored depends on who wrote the row. Comparing them naively makes every "clear
        this answer" save write a column that was already empty — a real row in the
        § 205.400(f)(1) audit log recording that nothing happened."""
        from auditlog.models import LogEntry

        self.assertIsNone(self.establishment.split_operation_plan)
        before = LogEntry.objects.get_for_object(self.establishment).count()

        response = self.client.put(self._module_url(), {"answers": {"split_operation_separation": None}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        self.establishment.refresh_from_db()
        self.assertFalse(self.establishment.split_operation_plan)
        self.assertEqual(
            LogEntry.objects.get_for_object(self.establishment).count(),
            before,
            "clearing an already-empty column wrote an audit row saying nothing changed",
        )

    def test_saving_an_unrelated_question_does_not_touch_the_bound_columns(self):
        """Recomputing every bound column on every save would clobber this to the default."""
        self.establishment.has_split_operation = True
        self.establishment.split_operation_plan = "Separate bins, separate tickets."
        self.establishment.save(update_fields=["has_split_operation", "split_operation_plan"])

        response = self.client.put(self._module_url(), {"answers": {"parallel_production": False}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        self.establishment.refresh_from_db()
        self.assertTrue(self.establishment.has_split_operation)
        self.assertEqual(self.establishment.split_operation_plan, "Separate bins, separate tickets.")

    # --- 2. the profile is no longer an editor --------------------------------------

    def test_the_establishment_write_serializer_refuses_the_split_columns(self):
        """The farm profile was the SECOND editor. It writes nothing here now."""
        from company.serializers import UpdateEstablishmentSerializer

        serializer = UpdateEstablishmentSerializer(
            instance=self.establishment,
            data={"has_split_operation": True, "split_operation_plan": "typed on the profile"},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("has_split_operation", serializer.validated_data)
        self.assertNotIn("split_operation_plan", serializer.validated_data)

    # --- 3. three states, never two -------------------------------------------------

    def test_an_untouched_column_is_unanswered_not_a_declared_no(self):
        """`has_split_operation` defaults to False. A default is not a declaration."""
        self.assertEqual(split_operation_declaration(self.establishment), UNANSWERED)

    def test_a_pre_binding_profile_declaration_is_not_thrown_away(self):
        """Farms that ticked the old switch made a real statement — it still reads as yes."""
        self.establishment.has_split_operation = True
        self.establishment.save(update_fields=["has_split_operation"])
        self.assertEqual(split_operation_declaration(self.establishment), DECLARED_YES)

    def test_the_osp_answer_beats_a_stale_column(self):
        """Legacy rows written before the binding must not outvote the plan of record."""
        self.establishment.has_split_operation = True
        self.establishment.save(update_fields=["has_split_operation"])
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {"g6_0_production": {"answers": {"split_operation": {"value": False, "at": "2026-08-21"}}}},
            "parcel_modules": {},
        }
        self.osp.save(update_fields=["module_responses"])
        self.assertEqual(split_operation_declaration(self.establishment), DECLARED_NO)

    def test_the_profile_endpoint_serves_the_three_state_declaration(self):
        """The card renders this string; a boolean column cannot express 'unanswered'."""
        url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["split_operation_declaration"], UNANSWERED)

        self.client.put(self._module_url(), {"answers": {"split_operation": True}}, format="json")
        response = self.client.get(url)
        self.assertEqual(response.data["split_operation_declaration"], DECLARED_YES)

    def test_the_declaration_is_not_computed_on_the_establishment_LIST(self):
        """`EstablishmentViewSet` hands the SAME serializer to `list`, and the resolver costs
        up to two OSP queries per establishment — 2N on the farm switcher of an
        Operation-tier company, for a value no list surface renders. The profile always
        arrives through `retrieve`, where it IS computed (asserted above)."""
        self.client.put(self._module_url(), {"answers": {"split_operation": True}}, format="json")

        response = self.client.get(f"/api/companies/{self.company.id}/establishments/")
        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["results"] if isinstance(response.data, dict) else response.data
        row = next(r for r in rows if r["id"] == self.establishment.id)
        self.assertIsNone(
            row.get("split_operation_declaration"),
            "the list view is paying for a value it does not render",
        )

    # --- 4. the declarations themselves ---------------------------------------------

    def test_every_declared_establishment_field_is_a_real_column(self):
        """A typo in `establishment_field` writes nothing and reports no error."""
        columns = {f.name for f in Establishment._meta.get_fields() if hasattr(f, "attname")}
        for module in MODULES_BY_KEY.values():
            for question_key, field in bound_establishment_fields(module).items():
                self.assertIn(
                    field,
                    columns,
                    f"{module.key}.{question_key} binds '{field}', which is not an Establishment column",
                )

    def test_coercion_matches_the_column_type(self):
        """A boolean question must not write '' into a BooleanField, or vice versa."""
        for module in MODULES_BY_KEY.values():
            for question_key, field in bound_establishment_fields(module).items():
                question = next(q for page in module.pages for q in page.questions if q.key == question_key)
                written = establishment_writes(module, {question_key: None})[field]
                column = Establishment._meta.get_field(field)
                if question.kind == "boolean":
                    self.assertIsInstance(written, bool)
                    self.assertEqual(column.get_internal_type(), "BooleanField")
                else:
                    self.assertIsInstance(written, str)
                    self.assertIn(column.get_internal_type(), ("CharField", "TextField"))

    def test_g6_0_binds_both_halves_of_the_declaration(self):
        """The export flags 'declares split but files no separation plan' off the TEXT column,
        so the plan text has to travel with the boolean or that check fires on a complete plan."""
        self.assertEqual(
            bound_establishment_fields(MODULES_BY_KEY["g6_0_production"]),
            {
                "split_operation": "has_split_operation",
                "split_operation_separation": "split_operation_plan",
            },
        )
