"""The committed OMRI catalogue must be loadable, honest, and complete enough to be useful.

Written when `omri_seed.csv` went from 55 hand-typed rows to the full published Crop
Products List (9,230 rows, September 5, 2026 edition) via `build_omri_seed_csv`. At 55 rows
search reached about one product in every 168 that OMRI lists, so a grower typing a real,
currently-listed product got "no match" and fell through to an operator-entered row — losing
a third-party listing they had actually earned. Nothing failed; the catalogue was simply
almost empty, and no test could see that.

These assertions are about the FILE, not the database, because the file is what production
seeds from. They are deliberately cheap (no DB, no fixtures) so they run in every suite.
"""

import csv
import os
import re

from django.test import SimpleTestCase

from certifications.models import OMRIProduct
from certifications.services.omri_verifier import looks_like_omri_code

_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "omri_seed.csv",
)

# Well below the 9,230 rows of the September 5, 2026 edition, and far above the 55 the
# catalogue carried before it. This is a floor against silent emptying — a truncated write,
# a bad parse, a merge that resolves the file to its old self — not a pin on the edition.
_MIN_ROWS = 5000


def _rows():
    with open(_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class OmriSeedCsvIntegrityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows = _rows()

    def test_the_catalogue_is_not_almost_empty(self):
        self.assertGreaterEqual(
            len(self.rows),
            _MIN_ROWS,
            f"omri_seed.csv holds {len(self.rows)} rows. The published Crop Products List "
            "has ~9,200. Rebuild it with `build_omri_seed_csv` before shipping.",
        )

    def test_every_code_is_omris_own_published_shape(self):
        """`seed_omri_minimal` REFUSES a row whose code is not this shape, so a bad code is
        not a cosmetic problem — it is a row that silently never reaches production."""
        bad = [r["omri_id"] for r in self.rows if not looks_like_omri_code(r["omri_id"])]
        self.assertEqual(bad[:10], [], f"{len(bad)} row(s) carry a code the seeder will refuse")

    def test_codes_are_unique(self):
        """`update_or_create` keys on `omri_id`, so a duplicate is not an error — it is one
        row quietly overwriting another and a catalogue smaller than the file suggests."""
        codes = [r["omri_id"] for r in self.rows]
        self.assertEqual(len(codes), len(set(codes)))

    def test_no_row_exceeds_the_columns_it_is_written_into(self):
        """A name longer than the model's field does not truncate — Postgres raises and the
        whole seed transaction rolls back. Caught here, where the fix is a parse fix, rather
        than on a production dyno mid-deploy."""
        limits = {
            "product_name": OMRIProduct._meta.get_field("product_name").max_length,
            "manufacturer": OMRIProduct._meta.get_field("manufacturer").max_length,
            "category": OMRIProduct._meta.get_field("category").max_length,
            "omri_id": OMRIProduct._meta.get_field("omri_id").max_length,
        }
        for column, limit in limits.items():
            worst = max(self.rows, key=lambda r: len(r.get(column) or ""))
            self.assertLessEqual(
                len(worst.get(column) or ""),
                limit,
                f"{column} is {len(worst.get(column) or '')} chars on {worst['omri_id']}, "
                f"but the column holds {limit}",
            )

    def test_every_row_has_a_product_name(self):
        blank = [r["omri_id"] for r in self.rows if not (r.get("product_name") or "").strip()]
        self.assertEqual(blank[:10], [])

    def test_no_expiration_date_is_invented(self):
        """⛔ OMRI prints expiry only on the per-product certificate, never on the list. A
        value here would be fabricated, and `OMRIProduct` states that NULL means UNKNOWN and
        never "current". Listings DO lapse — five in this catalogue already had."""
        dated = [r["omri_id"] for r in self.rows if (r.get("listing_expiration_date") or "").strip()]
        self.assertEqual(
            dated[:10],
            [],
            "listing_expiration_date is not in the published list; a value here is invented",
        )

    def test_every_row_names_the_edition_and_source_it_came_from(self):
        """`list_edition_date` is what a row's freshness is judged against; without it a
        stale listing is indistinguishable from a current one."""
        editions = {(r.get("list_edition_date") or "").strip() for r in self.rows}
        self.assertNotIn("", editions, "some rows do not say which edition they came from")
        for edition in editions:
            self.assertRegex(edition, r"^\d{4}-\d{2}-\d{2}$")
        sources = {(r.get("source_url") or "").strip() for r in self.rows}
        self.assertNotIn("", sources)
        for url in sources:
            self.assertTrue(url.startswith("https://www.omri.org/"), url)

    def test_categories_are_the_three_omri_crop_classes(self):
        """CF / CP / CT are the only class codes the Crop Products List prints. A fourth
        value means the parse read something that was not a class marker."""
        allowed = {"crop-fertilizer", "crop-pest-control", "crop-management-tool"}
        seen = {(r.get("category") or "").strip() for r in self.rows} - {""}
        self.assertEqual(seen - allowed, set())

    def test_manufacturer_is_blank_rather_than_guessed_where_unresolved(self):
        """The parser leaves the company EMPTY when the company/class split is ambiguous.
        This pins that the ambiguity is rare — if it grows, the parse degraded — while
        allowing it to exist, because a blank is honest and a guessed company is a false
        attribution of a third-party listing."""
        blank = [r["omri_id"] for r in self.rows if not (r.get("manufacturer") or "").strip()]
        self.assertLess(
            len(blank),
            max(10, len(self.rows) // 500),
            f"{len(blank)} rows have no manufacturer; the company/class split is degrading",
        )

    def test_the_products_the_pilot_plan_cites_are_reachable(self):
        """Concrete rather than statistical: these are on the pilot farm's § 205.201(a)(2)
        list, and a rebuild that drops them breaks a real plan."""
        names = " || ".join(r["product_name"].lower() for r in self.rows)
        for product in ("serenade", "entrust", "grandevo", "neptune's harvest", "surround"):
            self.assertIn(product, names, f"{product!r} is not in the catalogue")

    def test_the_header_is_exactly_what_the_seeder_reads(self):
        with open(_CSV, newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        self.assertEqual(
            header,
            [
                "omri_id",
                "product_name",
                "manufacturer",
                "category",
                "listing_expiration_date",
                "list_edition_date",
                "source_url",
            ],
        )


class BuildCommandContractTests(SimpleTestCase):
    """The rebuild tool's promises, pinned at the source.

    It cannot be exercised end-to-end here — it needs poppler and a 3 MB PDF — so what is
    guarded is the part that would quietly produce wrong DATA rather than fail loudly.
    """

    def _source(self):
        import inspect

        from certifications.management.commands import build_omri_seed_csv

        return inspect.getsource(build_omri_seed_csv)

    def test_the_product_code_pattern_is_case_sensitive(self):
        """⛔ Load-bearing. The September 5, 2026 edition contains exactly one uppercase
        code-shaped token in 229 pages — "(LON-16)", a SKU inside a product's NAME. A
        case-insensitive pattern read that entry as carrying two codes and dropped it."""
        from certifications.management.commands.build_omri_seed_csv import CODE_RE

        self.assertIsNone(CODE_RE.search("(LON-16)"))
        self.assertIsNotNone(CODE_RE.search("(llb-22989)"))

    def test_expiration_is_written_empty_and_says_why(self):
        source = self._source()
        self.assertIn('"listing_expiration_date": ""', source)

    def test_an_unresolved_manufacturer_is_left_blank(self):
        """Pinned because the tempting "fix" for the last unresolved row is to take the most
        likely company, and that would be a fabricated third-party attribution."""
        from certifications.management.commands.build_omri_seed_csv import _resolve

        records = [{"tail": ["Some Company Ltd", "Line two", "Line three"]}]
        _resolve(records, vocabulary=set())
        self.assertEqual(records[0]["manufacturer"], "")

    def test_the_two_line_tail_splits_into_company_then_class(self):
        from certifications.management.commands.build_omri_seed_csv import _resolve

        records = [{"tail": ["AgroThrive, Inc.", "Fertilizers and Soil Amendments, Blended (CF)"]}]
        _resolve(records, vocabulary=set())
        self.assertEqual(records[0]["manufacturer"], "AgroThrive, Inc.")
        self.assertEqual(records[0]["klass"], "Fertilizers and Soil Amendments, Blended (CF)")

    def test_a_shared_trailing_phrase_is_read_as_a_class_not_a_company(self):
        """Pass 3. "Anaerobic Digestate, from manure feedstock (CF)" never prints on one
        line, so it is absent from the bootstrap vocabulary; it is recognised because many
        different companies sit above it."""
        from certifications.management.commands.build_omri_seed_csv import _resolve, _resolve_by_shared_tail

        klass = ["Anaerobic Digestate, from manure feedstock", "(CF)"]
        records = [{"tail": [company, *klass]} for company in ("Agricen", "Oily Servants, LLC", "WeWant LLC")]
        _resolve(records, vocabulary=set())
        self.assertEqual([r["manufacturer"] for r in records], ["", "", ""])
        self.assertEqual(_resolve_by_shared_tail(records), 3)
        self.assertEqual(records[0]["manufacturer"], "Agricen")
        self.assertEqual(records[0]["klass"], "Anaerobic Digestate, from manure feedstock (CF)")

    def test_page_furniture_is_matched_on_a_blocks_first_line(self):
        """⛔ Matching furniture against EVERY line of a block condemned 54 real product
        blocks whose company or class line looked like a heading, merged their neighbours
        into two-code entries, and cost the catalogue 54 rows without an error."""
        from certifications.management.commands.build_omri_seed_csv import _is_furniture_block

        self.assertTrue(_is_furniture_block(["OMRI has determined the following products", "are allowed for use"]))
        self.assertTrue(_is_furniture_block(["CF: Crop Fertilizers and Soil Amendments", "Aids"]))
        self.assertFalse(_is_furniture_block(["AgroThrive, Inc.", "Fertilizers and Soil Amendments, Blended (CF)"]))
        self.assertFalse(_is_furniture_block(["Crop Fertility Services, LLC", "Fish Products (CF)"]))

    def test_the_source_url_is_omris_free_published_list(self):
        from certifications.management.commands.build_omri_seed_csv import SOURCE_URL

        self.assertTrue(SOURCE_URL.startswith("https://www.omri.org/"))
        self.assertTrue(SOURCE_URL.endswith(".pdf"))

    def test_the_edition_date_must_be_supplied_not_inferred(self):
        """A file's mtime is not the edition printed on the list. Requiring it keeps a
        re-download of an unchanged PDF from restamping every row as fresh."""
        source = self._source()
        self.assertIn('"--edition-date"', source)
        self.assertIn("required=True", source)


class SeededCatalogueReachTests(SimpleTestCase):
    """Codes the search path must resolve exactly, straight off a certificate."""

    def test_pasted_codes_from_the_committed_catalogue_are_well_formed(self):
        rows = _rows()
        sample = [r["omri_id"] for r in rows[:200]]
        for code in sample:
            self.assertTrue(looks_like_omri_code(code), code)
            self.assertRegex(code, re.compile(r"^[a-z]{2,6}-\d{1,7}$"))
