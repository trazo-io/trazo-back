"""
Guards for the certifier conformance registers (`documentation/compliance/certifiers/<certifier>/`).

These registers are what we point at when someone asks how aligned Trazo is with a certifying
agent's OSP forms. That claim is only worth anything if a register cannot quietly stop describing
the product, so these tests check it from both sides:

  * every question the register cites still exists in MODULE_REGISTRY (a rename or deletion fails
    here rather than in front of a certifier);
  * every question of a module whose form is marked `register_status: complete` is either cited by
    that certifier's register or listed in its `unmapped/<module_key>.yaml` with a written reason —
    so a question added to a mapped module forces someone to decide what the certifier asks about it.

Reverse coverage is scoped to *complete* forms on purpose: the register is built one form at a
time, and a guard that fails until the last form lands would simply be disabled.

These tests read files and the module registry only — no database, no fixtures.
"""

from django.test import SimpleTestCase

from certifications.services.certifier_register import (
    SEVERITIES,
    broken_model_references,
    certifiers,
    cited_question_keys,
    cross_certifier_conflicts,
    live_modules,
    live_question_keys,
    load_forms,
    load_scope,
    load_unmapped,
    question_keys_hidden_in_models,
    referenced_question_keys,
    summarize,
)


class RegisterSchemaTests(SimpleTestCase):
    def test_register_parses_and_every_row_is_well_formed(self):
        # load_forms() raises on any schema fault with a path-prefixed message, which is the
        # whole validation surface: statuses, severities, required fields per status, duplicate
        # refs, missing form metadata.
        forms = load_forms()
        self.assertGreater(len(forms), 0)

    def test_every_form_records_the_revision_it_was_read_against(self):
        # A form is revised without warning. Without the stamp there is no way to know the register
        # describes the current questionnaire. CCOF stamps "NOPB45, V1, R7, 9/21/2021"; WSDA stamps
        # "AGR 2121 (R 02/25)" — so require a revision marker, not one house style.
        for form in load_forms():
            self.assertRegex(
                form.revision,
                r"(V\d+|R ?\d)",
                msg=f"{form.certifier}/{form.path.name}: revision should carry the form's own stamp",
            )
            self.assertTrue(
                form.url.startswith("https://"),
                f"{form.certifier}/{form.path.name}: url should point at the certifier's own page",
            )

    def test_a_row_claiming_partial_or_full_coverage_says_where(self):
        """`covered` and `partial` are claims about the product, so they must be checkable.

        A row asserting the fact is captured, with nothing naming a question, a model field or an
        artifact it prints in, cannot be verified or falsified by a reader — and cannot be flipped
        with confidence when the gap is closed. `prints` alone is enough: several materials rows
        are about a column that has no question behind it but does reach the narrative.
        """
        unlocated = [
            f"{form.certifier}:{form.code or form.title} {item.ref}"
            for form in load_forms()
            for item in form.items
            if item.status in ("covered", "partial") and not (item.questions or item.models or item.prints)
        ]
        self.assertEqual(
            unlocated,
            [],
            "These rows claim the fact is captured but name nowhere it lives — no question, no "
            f"model field, no artifact it prints in: {unlocated}",
        )

    def test_every_model_reference_names_something_that_exists(self):
        """`trazo.models` is free text, which is how invented field names got in.

        Seven rows cited cleanout fields on `history.EquipmentEvent` — a model that records
        equipment name, type, fuel and hours and has no cleaning fields whatsoever. The fields were
        real but lived on `history.ProductionEvent`, so the register described the product from the
        wrong model, underneath the defect that currently tops the roadmap. Only strict
        `app.Model.field` refs are checked; prose and non-Django locations are skipped rather than
        guessed at.
        """
        broken = broken_model_references(load_forms())
        self.assertEqual(
            broken,
            [],
            f"These rows name a model field or property that does not exist: {broken}",
        )

    def test_no_question_key_hides_in_the_free_text_models_field(self):
        """`models` is free text; `questions` is validated. Real keys were parked in the free one.

        Three WSDA rows cited `module_key.question_key` values inside `trazo.models`, each with a
        parenthetical explaining why they were not in `questions` — they were routing around the
        cited-vs-unmapped guard back when it compared the two ACROSS certifiers and so called a
        legitimate WSDA citation a contradiction. Nothing validated them and they counted toward
        no coverage. The guard is scoped per certifier now; this closes the hiding place.
        """
        hidden = question_keys_hidden_in_models(load_forms())
        self.assertEqual(
            hidden,
            [],
            "These rows name a live OSP question inside `trazo.models`, where nothing validates it "
            f"and no coverage check counts it. Move it to `trazo.questions`: {hidden}",
        )

    def test_gap_rows_carry_a_severity_we_recognise(self):
        for form in load_forms():
            for item in form.items:
                if item.is_gap:
                    self.assertIn(item.severity, SEVERITIES, f"{form.code} [{item.ref}]")


class RegisterDriftTests(SimpleTestCase):
    """The two directions. These are the tests that make the register maintainable."""

    def test_every_cited_question_exists_in_the_live_registry(self):
        live = live_question_keys()
        stale = sorted(key for key in referenced_question_keys(load_forms()) if key not in live)
        self.assertEqual(
            stale,
            [],
            "The register cites questions that no longer exist. Either the question was renamed "
            "(update the register row) or removed (decide what the form question maps to now): "
            f"{stale}",
        )

    def test_every_question_of_a_mapped_module_is_accounted_for(self):
        # PER CERTIFIER. A module whose WSDA form is complete must be accounted for by WSDA's own
        # citations or WSDA's own unmapped file — CCOF's coverage says nothing about whether WSDA
        # asks the question.
        missing = []
        for certifier in certifiers():
            forms = load_forms(certifier)
            cited = cited_question_keys(forms)
            unmapped = load_unmapped(certifier)

            mapped_modules = {
                module for form in forms if form.register_status == "complete" for module in form.trazo_modules
            }
            for module in live_modules():
                if module.key not in mapped_modules:
                    continue
                for page in module.pages:
                    for question in page.questions:
                        key = f"{module.key}.{question.key}"
                        if key not in cited and key not in unmapped:
                            missing.append(f"{certifier}:{key}")

        self.assertEqual(
            sorted(missing),
            [],
            "These questions belong to a module whose CCOF form is marked complete, but nothing "
            "says which CCOF question they answer. Add them to the relevant form row, or to "
            "unmapped/<module>.yaml with the reason the certifier's forms do not ask for them: "
            f"{sorted(missing)}",
        )

    def test_no_question_is_both_cited_and_declared_unmapped(self):
        """PER CERTIFIER, and the scoping matters.

        `unmapped` means "THIS certifier's forms do not ask this". A question cited by that same
        certifier's register has a counterpart there by definition, so being in both places is a
        contradiction — a quiet one, because each half passes its own check.

        Comparing them ACROSS certifiers is wrong, and was: a question CCOF does not ask but WSDA
        does is the most informative row in the whole register, and a merged check called it a
        contradiction. It cost real fidelity before it was caught — an agent registering WSDA's
        international-trade section downgraded correct citations to prose to get around the
        spurious failure.
        """
        offenders = {}
        for certifier in certifiers():
            forms = load_forms(certifier)
            cited = cited_question_keys(forms)
            for key in sorted(set(cited) & set(load_unmapped(certifier))):
                offenders[f"{certifier}:{key}"] = [
                    f"{form.code or form.title} {item.ref}"
                    for form in forms
                    for item in form.items
                    if key in item.questions
                ]
        self.assertEqual(
            offenders,
            {},
            "These questions are cited by a certifier's own register AND listed in that same "
            "certifier's unmapped file. The citation is the truth; delete the unmapped entry: "
            f"{offenders}",
        )

    def test_unmapped_entries_point_at_questions_that_exist(self):
        live = live_question_keys()
        stale = sorted(key for key in load_unmapped() if key not in live)
        self.assertEqual(
            stale,
            [],
            f"unmapped/ names questions that no longer exist: {stale}",
        )


class CrossCertifierConsistencyTests(SimpleTestCase):
    """Two certifiers, one product.

    CCOF and WSDA are overlays of the same federal content, so a second certifier is registered as
    a delta against the first rather than re-audited — precisely because two independent passes
    over one product disagree about it. That already happened once inside a single register (nine
    questions cited by one form and declared to have no counterpart by another), and adding a
    certifier multiplies the opportunity.
    """

    def test_no_question_is_covered_for_one_certifier_and_absent_for_another(self):
        conflicts = cross_certifier_conflicts(load_forms())
        self.assertEqual(
            conflicts,
            {},
            "A Trazo question is described as covered by one certifier's register and as not "
            "covered by another's. Either the fact is capturable and printable or it is not — "
            f"differences in how deeply a form asks belong in `partial`: {conflicts}",
        )


class ScopeTests(SimpleTestCase):
    def test_scope_entries_state_a_reason_and_gaps_name_their_trigger(self):
        # load_scope() enforces both. Asserting it here keeps the rule visible where someone
        # editing the register will look, and fails the build rather than the reader.
        entries = load_scope()
        self.assertGreater(len(entries), 0, "scope.yaml should record the forms we do not register")
        for entry in entries:
            self.assertTrue(entry.reason.strip(), entry.form)
            if entry.disposition == "gap":
                self.assertTrue(entry.triggered_from.strip(), entry.form)

    def test_a_registered_form_is_not_also_listed_as_excluded(self):
        # Two files describing one form is how they drift apart. A form with its own register entry
        # states a verdict per question; an exclusion line states there is nothing to say. It cannot
        # be both.
        registered_ids = {f.document_id for f in load_forms() if f.document_id}
        clashes = sorted(e.form for e in load_scope() if e.document_id in registered_ids)
        self.assertEqual(
            clashes,
            [],
            "These forms are registered in forms/ AND listed in scope.yaml as not registered. "
            f"Delete the scope.yaml entry — the register entry is the better answer: {clashes}",
        )


class RegisterSummaryTests(SimpleTestCase):
    def test_summary_counts_are_derived_not_typed(self):
        # The generated statement quotes these numbers. Asserting the shape here means a hand-typed
        # count in a document can never silently disagree with the register.
        summary = summarize(load_forms())
        self.assertEqual(
            summary["items"],
            sum(summary["by_status"].values()),
            "status counts must partition every row",
        )
        self.assertGreaterEqual(summary["items"], summary["by_severity"]["P0"])
