"""
The register's rows are the agent's form, item for item (OSP alignment audit 2026-10, T26 and T27).

A register row says what Trazo does about one question on a certifying agent's form. Until
2026-09-30 nothing checked that the rows WERE the form's questions. They were transcribed by hand,
and the audit found rows folding several numbered questions into one, refs the form never prints,
optional sections with no row, and OTCO's O1 transcribed from an edition the agent had replaced.

Each form now has a source inventory derived from the agent's own file
(`certifications/services/form_inventory.py`). These tests hold the register to it:

  * the register form names the source file's sha256, and its revision is the stamp that file
    prints, so a form transcribed from one edition cannot claim another;
  * the register's question and instruction rows are the inventory's items, one to one and in the
    form's order, with the same optional flag. A Trazo interpretation is the only row allowed
    outside the inventory, and it never counts as an answer.

The source binaries are not committed. `manage.py verify_form_inventory --sources <dir>` re-derives
the inventories from the files; these tests need only the committed YAML.
"""

from django.test import SimpleTestCase

from certifications.services.certifier_register import load_forms
from certifications.services.form_inventory import inventory_path, load_inventory, same_revision

#: Registered forms whose inventory has not been derived yet. Empty since 2026-10-01: every
#: registered form has one. Kept so a newly registered agent can be built a form at a time; a form
#: listed here that HAS an inventory fails, so the list cannot go stale.
NOT_YET_INVENTORIED: set[tuple[str, str]] = set()


def _inventoried():
    for form in load_forms():
        path = inventory_path(form.path)
        if path.is_file():
            yield form, load_inventory(path)


class EveryFormHasASourceInventoryTests(SimpleTestCase):
    def test_a_form_without_an_inventory_is_listed_and_a_listed_form_has_none(self):
        missing, stale = [], []
        for form in load_forms():
            key = (form.certifier, form.path.stem)
            has = inventory_path(form.path).is_file()
            if not has and key not in NOT_YET_INVENTORIED:
                missing.append(key)
            if has and key in NOT_YET_INVENTORIED:
                stale.append(key)
        self.assertEqual(missing, [], "these forms have no source inventory and are not listed as pending")
        self.assertEqual(stale, [], "these forms have an inventory now: take them off NOT_YET_INVENTORIED")

    def test_the_register_names_the_file_and_the_edition_it_was_read_from(self):
        problems = []
        for form, inventory in _inventoried():
            if form.source_sha256 != inventory.sha256:
                problems.append(f"{form.path.name}: source_sha256 does not match the inventory's source file")
            if not same_revision(form.revision, inventory.revision):
                problems.append(
                    f"{form.path.name}: register revision {form.revision!r}, but the source prints {inventory.revision!r}"
                )
        self.assertEqual(problems, [])


class RowsAreTheFormsItemsTests(SimpleTestCase):
    def test_question_and_instruction_rows_match_the_inventory_one_to_one_in_order(self):
        problems = []
        for form, inventory in _inventoried():
            rows = [(i.ref, i.kind, i.optional) for i in form.items if i.kind != "interpretation"]
            items = [(i.ref, i.kind, i.optional) for i in inventory.items]
            if rows != items:
                only_rows = [r for r in rows if r not in items]
                only_items = [r for r in items if r not in rows]
                problems.append(
                    f"{form.path.name}: rows not on the form {only_rows}; form items with no row {only_items}"
                    + ("" if only_rows or only_items else "; same items in a different order")
                )
        self.assertEqual(problems, [])

    def test_no_placeholder_ref_survives_review(self):
        # The extractor marks a ref the form prints twice as "7a (2)" for a person to describe.
        leftovers = [
            f"{form.path.name} [{item.ref}]"
            for form, inventory in _inventoried()
            for item in inventory.items
            if item.ref.endswith(tuple(f"({n})" for n in range(2, 30)))
        ]
        self.assertEqual(leftovers, [])
