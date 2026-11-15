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

import re
from pathlib import Path

from django.test import SimpleTestCase

from certifications.services.certifier_register import (
    _CERTIFIER_MARKERS,
    SEVERITIES,
    _reject_internal_language,
    broken_model_references,
    certifiers,
    certifiers_missing_inventory,
    cited_question_keys,
    cross_certifier_conflicts,
    foreign_markers,
    live_modules,
    live_question_keys,
    load_forms,
    load_published_inventory,
    load_scope,
    load_unmapped,
    question_keys_hidden_in_models,
    referenced_question_keys,
    summarize,
    unaccounted_published_forms,
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
        # describes the current questionnaire. CCOF stamps "ORGB45, V1, R7, 9/21/2021"; WSDA stamps
        # "AGR 2121 (R 02/25)"; OTCO stamps its Word footers "rev. 2025/08/27" (FACT-04 and the
        # Update Form capitalise it) — so require a revision marker, not one house style.
        # A web form prints no stamp at all (CCOF's Annual Renewal Contract, registered 2026-10-01
        # from a capture): its edition is the date it was captured, and the register says so.
        for form in load_forms():
            self.assertRegex(
                form.revision,
                r"(V\d+|R ?\d|[Rr]ev\.? ?\d{4}|captured \d{4}-\d{2}-\d{2})",
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

    def test_a_model_our_app_no_longer_has_is_reported_not_skipped(self):
        """Review of #428: a lookup error was skipped as "not necessarily ours", so a renamed
        model made every row that named it pass unchecked. An app that is not installed is still
        skipped; a model missing from one of ours is a broken reference."""
        from types import SimpleNamespace

        def form(*refs):
            item = SimpleNamespace(ref="1", models=list(refs))
            return SimpleNamespace(certifier="test", code="F", document_id="F", items=[item])

        self.assertEqual(broken_model_references([form("vendor.Thing.field")]), [])
        self.assertEqual(broken_model_references([form("history.Production.retention_until")]), [])
        self.assertEqual(
            broken_model_references([form("history.NoSuchModel.retention_until")]),
            ["test:F 1 -> history.NoSuchModel.retention_until (no model)"],
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
            sum(summary["by_kind"].values()),
            "kind counts must partition every row",
        )
        self.assertEqual(
            summary["by_kind"]["question"],
            sum(summary["by_status"].values()),
            "status counts must partition every question row, and only those",
        )
        self.assertGreaterEqual(summary["items"], summary["by_severity"]["P0"])


class ScopeProseIsCertifierFacingTests(SimpleTestCase):
    """🔴 2026-09-07 — `scope.yaml` `reason` is rendered VERBATIM onto the packet's
    `04-coverage-and-scope.pdf`, so it is certifier-facing prose, not an internal note.

    What was published before this guard: "Not built and not triggered: `G7.0`'s `buyer_label`
    option has no follow-up" on the CCOF page, and on the WSDA page CCOF's own form numbers
    plus "which IS a real grower-side trigger and remains unrepresented in Trazo". The packet
    test's denylist ("P0", "P1", "blocker", "root_cause", "not_covered") matched none of it.

    Rejecting it at LOAD time is the point: a claim filtered by its reader is still on the wire.
    """

    def test_no_reason_carries_internal_language(self):
        # load_scope() itself raises on a bad reason, so simply loading every agent is the
        # assertion. Kept explicit so a failure names this rule rather than looking like a
        # parse error somewhere.
        for certifier in certifiers():
            load_scope(certifier)

    def test_a_backlog_reason_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            _reject_internal_language("ccof", "Some Form", "Not built and not triggered.")
        self.assertIn("backlog", str(ctx.exception))

    def test_a_backticked_identifier_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            _reject_internal_language("ccof", "Some Form", "See `g3_0_seeds.ca_search_before_use`.")
        self.assertIn("backtick", str(ctx.exception))

    def test_another_agents_form_ids_are_refused(self):
        with self.assertRaises(ValueError) as ctx:
            _reject_internal_language("wsda", "Some Form", "Same reasoning as CCOF's ORGB32 exclusion.")
        self.assertIn("another certifying agent", str(ctx.exception))
        # ...and the agent's OWN identifiers are fine on its own page.
        _reject_internal_language("wsda", "Some Form", "WSDA licenses this separately (AGR 2180).")
        _reject_internal_language("ccof", "Some Form", "CCOF collects this on ORGB32.")

    def test_every_registered_certifier_declares_its_markers(self):
        """A third agent registered without a marker row would get NO foreign-id check.

        That is the "knows about two of three" off-by-one this file keeps catching elsewhere;
        here it would fail open, on the one field that is published to a certifier.
        """
        self.assertEqual(
            set(_CERTIFIER_MARKERS),
            set(certifiers()),
            "every registered certifier needs its own name/form-id markers in _CERTIFIER_MARKERS",
        )

    def test_foreign_markers_excludes_the_agents_own(self):
        self.assertNotIn("CCOF", foreign_markers("ccof"))
        self.assertIn("CCOF", foreign_markers("wsda"))
        self.assertIn("Oregon Tilth", foreign_markers("wsda"))
        self.assertNotIn("OTCO", foreign_markers("otco"))
        self.assertIn("AGR 2", foreign_markers("otco"))


class PrintsNamesRealArtifactsTests(SimpleTestCase):
    """🔴 2026-09-07 — `prints` is a factual claim about the packet and NOTHING validated it.

    `test_a_row_claiming_partial_or_full_coverage_says_where` only checks the field is
    non-empty. `_workbook_filename` changed on 2026-09-07 to write `workbooks/<spec.title>.xlsx`
    and seven citations — one on a `covered` row — went on naming paths that no longer exist. A
    reviewer following a covered row into the ZIP finds nothing, which is the register's own
    "a citation naming an artifact that does not print the fact" trap arriving by drift rather
    than by mistake.

    Only the tokens that are mechanically checkable are checked: workbook filenames and the
    numbered top-level documents. Section letters and prose stay a human claim.
    """

    def _prints_tokens(self, pattern):
        for form in load_forms():
            for item in form.items:
                for token in re.findall(pattern, item.prints or ""):
                    yield f"{form.certifier}/{form.code or form.title} {item.ref}", token

    def test_every_workbook_named_in_prints_is_one_the_packet_writes(self):
        from certifications.services.common_osp_workbooks import WORKBOOKS
        from certifications.services.osp_module_pdf import _workbook_filename

        real = {f"workbooks/{_workbook_filename(spec)}" for spec in WORKBOOKS}
        bad = [
            f"{where}: {token!r}"
            for where, token in self._prints_tokens(r"workbooks/[^;,)\s][^;,)]*\.xlsx")
            if token.strip() not in real
        ]
        self.assertEqual(bad, [], f"`prints` names a workbook the packet does not write. Real: {sorted(real)}. {bad}")

    def test_every_module_pdf_named_in_prints_is_one_the_packet_writes(self):
        """Review of #64: the register kept citing `modules/certification_contract.pdf` after the
        packet renamed it `modules/operation_profile.pdf`, because this class checked only
        workbooks and top-level documents."""
        from certifications.osp_modules import MODULE_REGISTRY
        from certifications.services.packet_coverage import module_file_stem

        real = {f"modules/{module_file_stem(module)}.pdf" for module in MODULE_REGISTRY}
        bad = [
            f"{where}: {token!r}"
            for where, token in self._prints_tokens(r"modules/[A-Za-z0-9_]+\.pdf")
            if token not in real
        ]
        self.assertEqual(bad, [], f"`prints` names a module PDF the packet does not write. {bad}")

    def test_every_numbered_document_named_in_prints_is_one_the_packet_writes(self):
        # The 0N-*.pdf names are the packet's top-level documents, written by `generate_osp_packet`.
        source = (Path(__file__).resolve().parents[1] / "services" / "osp_module_pdf.py").read_text()
        # Written through `zf.writestr(...)` or the packet's `write(...)` helper (which also keeps the
        # bytes for 06, the question index); the name may sit on the next line.
        real = set(re.findall(r'(?:zf\.writestr|\bwrite)\(\s*"(\d\d-[a-z-]+\.pdf)"', source))
        self.assertTrue(real, "could not read the packet's document names — re-point this guard")
        bad = [
            f"{where}: {token!r}" for where, token in self._prints_tokens(r"\b\d\d-[a-z-]+\.pdf") if token not in real
        ]
        self.assertEqual(bad, [], f"`prints` names a packet document that does not exist. Real: {sorted(real)}. {bad}")


class PublishedInventoryIsAccountedForTests(SimpleTestCase):
    """🔴 2026-09-07 — the register measured itself against itself.

    `forms/` says what we registered; `scope.yaml` says what we deliberately did not. Nothing
    said what the CERTIFYING AGENT publishes, so a form in neither file was invisible to every
    guard here AND to the packet's coverage page. Seven were — worst of them AGR 2519, which
    five register rows quote by name as the attachment WSDA demands and whose own fix note says
    to "state its absence in the coverage page", while `exclusion_rows()` builds that page from
    `scope.yaml` alone. Also CCOF's Crop Update (ORGB88), which cites § 205.201 and
    § 205.400(f)(2) and collects parcel × crop × acreage — Trazo's own data shape.

    An exclusion is not an absence; neither is an omission. This is the outside edge.
    """

    def test_every_published_form_is_registered_or_excluded_with_a_reason(self):
        holes = {}
        for certifier in certifiers():
            missing = unaccounted_published_forms(certifier)
            if missing:
                holes[certifier] = [f"{f.document_id} — {f.form}" for f in missing]
        self.assertEqual(
            holes,
            {},
            "These forms the certifying agent publishes are in neither forms/ nor scope.yaml, so "
            "nothing states whether Trazo covers them and the packet cannot say so either. "
            f"Register each, or add a scope.yaml entry with a written reason: {holes}",
        )

    def test_every_registered_certifier_has_a_published_inventory(self):
        """Without one, this guard passes vacuously for that agent — which is the failure mode
        it exists to remove, not a state to leave a new certifier in."""
        self.assertEqual(
            certifiers_missing_inventory(),
            [],
            "a registered certifier with no published_inventory.yaml has no outside edge to be "
            "measured against, so the accounting guard above cannot see it at all",
        )

    def test_the_inventory_does_not_double_count_a_document_id(self):
        for certifier in certifiers():
            ids = [f.document_id for f in load_published_inventory(certifier)]
            self.assertEqual(sorted(ids), sorted(set(ids)), f"{certifier}: duplicate document_id in the inventory")

    def test_the_inventory_names_the_edition_the_form_was_read_from(self):
        """2026-10-25: OTCO's O1 was re-read at rev. 2026/10/02 while this file still said
        2026/03/25, so the record of what the agent publishes named an edition nobody had read.
        Where the inventory states a revision, it names every registered file's edition. One
        document_id can cover many files (WSDA AGR 2121 is 20, with §S at its own edition), so every
        file is checked, never one per id. CCOF's inventory states none."""
        for certifier in certifiers():
            published = {p.document_id: p for p in load_published_inventory(certifier)}
            for form in load_forms(certifier):
                row = published.get(form.document_id)
                if row is None or not row.revision:
                    continue
                with self.subTest(form=str(form.path)):
                    self.assertTrue(
                        form.revision in row.revision or form.revision.startswith(row.revision),
                        f"published_inventory.yaml says {row.revision!r}; the form was read at {form.revision!r}",
                    )

    def test_a_forms_pdf_link_is_the_file_its_inventory_hashed(self):
        """2026-10-25: three CCOF forms linked the 2025 uploads CCOF replaced on 2026-10-10 while
        their inventories recorded the 2026/10 files. `form.pdf` is the link a reader follows."""
        import yaml

        for form in load_forms():
            if not form.pdf:
                continue
            inventory = form.path.parent.parent / "inventory" / form.path.name
            with self.subTest(form=str(form.path)):
                source = (yaml.safe_load(inventory.read_text()) or {}).get("source") or {}
                self.assertEqual(form.pdf, source.get("url"), f"{inventory} hashed a different file")


class FormsDeclareTheModulesTheyCiteTests(SimpleTestCase):
    """`trazo_module` is the load-bearing field, not `register_status`.

    🔴 2026-09-07 — three WSDA forms (§F Weed, §H Disease, §I Farm Equipment) declared NO
    module while their 22 rows cited `g5_0_pest`, `g6_0_production` and
    `g6_1_harvest_transport`. Two consequences, both silent:

      * `packet_coverage._classify` routes on `trazo_modules`, so a WSDA packet printed
        "4 further WSDA forms have not yet been compared against this plan" about forms the
        register had compared question by question and the packet answers inside G5.0 — the
        module's own docstring uses §F as its worked example of the opposite;
      * flipping one to `register_status: complete` would have been a no-op the reverse-coverage
        guard could not see, because it iterates `form.trazo_modules`.

    ⛔ The reverse implication is NOT checked: eight CCOF complete forms legitimately cite other
    modules' questions (G8.0 cites four), so "declared ⊇ cited" would be wrong. What is checked
    is that a form citing a module declares at least one.
    """

    def test_a_form_whose_rows_cite_questions_declares_a_module(self):
        undeclared = []
        for form in load_forms():
            if form.trazo_modules:
                continue
            cited = {key.split(".")[0] for item in form.items for key in item.questions}
            if cited:
                undeclared.append(f"{form.certifier}/{form.path.name} cites {sorted(cited)} but declares none")
        self.assertEqual(
            undeclared,
            [],
            "A form whose rows cite module questions must declare `trazo_module`: it is what the "
            f"packet coverage page routes on and what reverse coverage iterates. {undeclared}",
        )

    def test_every_declared_module_exists(self):
        live = {m.key for m in live_modules()}
        bad = [
            f"{form.certifier}/{form.path.name}: {key}"
            for form in load_forms()
            for key in form.trazo_modules
            if key not in live
        ]
        self.assertEqual(
            bad,
            [],
            "A `trazo_module` typo silently switches reverse coverage off for that module — "
            f"nothing else would notice: {bad}",
        )


class NotServedFormsTests(SimpleTestCase):
    """2026-10-25. Mushroom and wild-harvest forms are for operations Trazo decided not to serve.
    That is a business decision with a reason and a date, kept on the form; the statement counts
    those forms apart so a total describes the operations Trazo serves, and nothing disappears."""

    def test_a_not_served_form_states_why_and_when(self):
        unserved = [f for f in load_forms() if not f.served]
        self.assertTrue(unserved, "read something: the register marks at least one form not served")
        for form in unserved:
            self.assertTrue(form.not_served_basis.strip(), form.label)
            self.assertTrue(form.not_served_decided, form.label)
            self.assertFalse(form.required_of_every_grower, f"{form.label} is filed by every grower")

    def test_the_loader_refuses_a_bare_or_misplaced_mark(self):
        from certifications.services.certifier_register import _not_served_meta

        with self.assertRaises(ValueError):
            _not_served_meta({"not_served": {"basis": "mushrooms"}}, "x")
        with self.assertRaises(ValueError):
            _not_served_meta({"not_served": {"decided": "2026-10-25"}}, "x")
        with self.assertRaises(ValueError):
            _not_served_meta(
                {"required_of_every_grower": True, "not_served": {"basis": "b", "decided": "2026-10-25"}}, "x"
            )
        self.assertEqual(_not_served_meta({}, "x"), {})

    def test_the_statement_counts_them_apart_and_drops_none(self):
        import re

        from certifications.management.commands.certifier_conformance import render

        forms = load_forms()
        served = [f for f in forms if f.served]
        unserved = [f for f in forms if not f.served]
        text = render(forms, load_scope())
        stand = text.split("## Where we stand", 1)[1].split("## ", 1)[0]
        quoted = int(re.search(r"\| Questions compared \| (\d+) \|", stand).group(1))
        self.assertEqual(quoted, summarize(served)["by_kind"]["question"])
        apart = summarize(unserved)["by_kind"]["question"]
        self.assertIn(f"({apart} questions)", stand)
        self.assertEqual(quoted + apart, summarize(forms)["by_kind"]["question"])
        section = text.split("## Operation types Trazo does not serve", 1)[1]
        for form in unserved:
            self.assertIn(f"### {form.label}", section)
            self.assertNotIn(f"### {form.label}\n", text.split("## Operation types Trazo does not serve", 1)[0])

    def test_the_blockers_section_reads_the_forms_the_headline_counts(self):
        """Review of #229: a P0 on a not-served form must not appear under a headline that says 0."""
        from certifications.management.commands import certifier_conformance as cc

        forms = load_forms()
        unserved = [f for f in forms if not f.served]
        seen = []
        original = cc.blockers_by_root_cause
        cc.blockers_by_root_cause = lambda fs: seen.append(list(fs)) or {}
        try:
            cc.render(forms, load_scope())
        finally:
            cc.blockers_by_root_cause = original
        self.assertEqual(len(seen), 1)
        self.assertFalse(any(f in seen[0] for f in unserved))
        self.assertEqual(len(seen[0]), len(forms) - len(unserved))
