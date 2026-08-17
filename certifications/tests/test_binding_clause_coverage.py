"""The binding-clause mapping must stay true, or fail.

A conformance matrix that is only prose rots the moment someone renames a service. This suite
makes every assertion in `binding_clauses.py` mechanically checkable:

  * the clause LIST is re-derived from the frozen CFR text, so a clause cannot be forgotten
    (§ 205.103(b)(5) was missing from the summary that prompted this work);
  * every `verbatim` must actually appear in the frozen CFR, so the quotes cannot drift;
  * every cited implementation file and symbol must exist;
  * every cited test module must exist;
  * a clause claiming SOFTWARE_SATISFIES must name both an implementation and a test.

The last rule is the one with teeth: it makes "we satisfy this" cost something to say.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from pathlib import Path

from django.test import SimpleTestCase

from certifications.conformance import (
    BINDING_CLAUSES,
    CORPUS_CFR_PATH,
    CORPUS_HANDBOOK_DIR,
    Disposition,
    clauses_for_section,
)

#: Repo root — implementation paths are given repo-relative so they can point at the frontend
#: too (the § 205.103(b)(1) "adapted to the business" answer lives in the registry).
REPO_ROOT = Path(__file__).resolve().parents[3]


def _normalize(text: str) -> str:
    """Collapse whitespace and unify quote characters for comparison.

    The CFR text uses typographic quotes and hard-wraps; a `verbatim` string in Python source
    is wrapped by the formatter. Neither difference is a drift in the QUOTE, so neither should
    fail the test — but a changed WORD must.
    """
    text = unicodedata.normalize("NFKC", text)
    for fancy, plain in (("“", '"'), ("”", '"'), ("’", "'"), ("‘", "'")):
        text = text.replace(fancy, plain)
    return re.sub(r"\s+", " ", text).strip()


def _defines_symbol(path: Path, symbol: str) -> bool:
    """Does this file really DEFINE `symbol` — `Name` or `Class.attr`?

    🔴 The first version asked `symbol.split(".")[-1] not in source`, i.e. a substring sweep of
    the whole file. That is the identical weakness this codebase already found and fixed in its
    registry conformance guard, where a field's name appearing in a COMMENT recording its
    removal satisfied the check. It also never verified that `Class.attr` was on that class —
    any mention anywhere passed.

    Python files are parsed. Non-Python files (the registry is TypeScript) cannot be, so they
    keep a text match; that is a stated weaker check, not an oversight.
    """
    source = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix != ".py":
        return symbol.split(".")[-1] in source

    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - a broken file is a louder failure elsewhere
        return False

    def _names(body) -> set[str]:
        found: set[str] = set()
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.add(node.name)
            elif isinstance(node, ast.Assign):
                found.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                found.add(node.target.id)
        return found

    if "." not in symbol:
        return symbol in _names(tree.body)

    owner, attr = symbol.split(".", 1)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == owner:
            # Django fields are class-body assignments; methods are defs. Both are in the body.
            return attr in _names(node.body)
    return False


def _top_level_letters(body: str) -> set[str]:
    """The (a), (b), (c)... paragraph letters of a section.

    A naive `\([a-z]\)` scan is wrong: § 205.203 nests ROMAN NUMERALS — (c)(1)(i), (c)(2)(ii)
    — and "(i)" matches the letter pattern exactly. Reading it as a top-level paragraph
    invents a clause "§ 205.203(i)" that does not exist.

    CFR paragraph letters run in sequence from (a), so the sequence itself is the
    discriminator: keep a letter only when it is the next one expected. A roman numeral
    appearing out of sequence is dropped.

    ⚠️ TWO LIMITS, both loud rather than silent:

    * The walk stops at the first gap. A genuinely skipped paragraph letter drops every letter
      after it, and the caller's set comparison then fails with a visible diff — not a guess.
    * It cannot distinguish paragraph **(i)** from the roman numeral **(i)**. No section mapped
      here reaches (i) — the deepest is § 205.206(f) — and
      `test_no_mapped_section_reaches_the_ambiguous_letter` fails the moment one does, so this
      assumption breaks visibly at the point somebody extends coverage.
    """
    found = re.findall(r"\n\s*\(([a-z])\)\s", body)
    letters: set[str] = set()
    expected = "a"
    for letter in found:
        if letter == expected:
            letters.add(letter)
            expected = chr(ord(expected) + 1)
    return letters


def _paragraph_body(section_body: str, letter: str) -> str:
    """The text of ONE lettered paragraph, e.g. just the (a) of § 205.201.

    Needed because a section's numbered items are not globally unique: § 205.201 has (a)(1)-(6)
    AND (c)(1)-(10), so scanning the whole section for `(\d+)` returns 1-10 with no way to tell
    which paragraph each belongs to.

    The first version of this guard "solved" that with `if int(n) <= 6` — which hardcodes the
    very answer the guard exists to derive. Had an amendment added § 205.201(a)(7), the filter
    would have produced 1-6 from (c)'s list and silently reported full coverage. Slice the
    paragraph instead, and let the count fall out of the text.
    """
    start = re.search(rf"\n\s*\({letter}\)\s", section_body)
    if start is None:
        return ""
    rest = section_body[start.end() :]
    # Terminate at the NEXT letter in sequence, not at any [a-z].
    #
    # 🔴 MEASURED: an "any letter" terminator returned only item (1) for § 205.203(c), which
    # actually has (1), (2) and (3) — because (c)(1) nests ROMAN NUMERALS (i)/(ii)/(iii) and
    # "(i)" matches [a-z] exactly, ending the slice inside the first item. Paragraph (a) ends
    # where (b) begins; nothing else terminates it.
    successor = chr(ord(letter) + 1)
    nxt = re.search(rf"\n\s*\({successor}\)\s", rest)
    return rest[: nxt.start()] if nxt else rest


def _section_body(corpus: str, header: str) -> str:
    """The text of one section, up to the next `§ 205.` header."""
    start = corpus.index(header)
    nxt = re.search(r"\n§ 205\.\d+", corpus[start + len(header) :])
    end = start + len(header) + (nxt.start() if nxt else len(corpus))
    return corpus[start:end]


class BindingClauseCorpusTests(SimpleTestCase):
    """The mapping is derived from the frozen corpus, not from memory."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.corpus = CORPUS_CFR_PATH.read_text(encoding="utf-8", errors="replace")
        cls.normalized_corpus = _normalize(cls.corpus)

    def test_the_frozen_corpus_is_present(self):
        self.assertTrue(
            CORPUS_CFR_PATH.exists(),
            f"The frozen CFR text is missing at {CORPUS_CFR_PATH}. Every clause quotation in "
            f"binding_clauses.py cites it; without it nothing here is verifiable.",
        )

    def test_every_verbatim_appears_in_the_frozen_cfr(self):
        """A quotation that has drifted from the source is worse than no quotation."""
        drifted = [clause.id for clause in BINDING_CLAUSES if _normalize(clause.verbatim) not in self.normalized_corpus]
        self.assertEqual(
            drifted,
            [],
            f"These clauses quote text that does not appear in the frozen CFR: {drifted}. "
            f"Either the quotation was edited, or the corpus was replaced with a different "
            f"revision — resolve which before changing this test.",
        )

    def test_no_mapped_section_reaches_the_ambiguous_letter(self):
        """`_top_level_letters` cannot tell paragraph (i) from roman numeral (i).

        That is fine while every mapped section stops well short of it — § 205.206(f) is the
        deepest — and it is a silent misread the moment one does not. This test is the tripwire:
        if a future section with nine or more paragraphs is mapped, fix the discriminator
        (roman numerals are always nested one level deeper) rather than deleting this.
        """
        headers = {
            "§ 205.103 Recordkeeping by certified operations.",
            "§ 205.201 Organic production and handling system plan.",
            "§ 205.202 Land requirements.",
            "§ 205.203 Soil fertility and crop nutrient management practice standard.",
            "§ 205.206 Crop pest, weed, and disease management practice standard.",
        }
        for header in headers:
            with self.subTest(section=header[:14]):
                letters = _top_level_letters(_section_body(self.corpus, header))
                self.assertNotIn(
                    "i",
                    letters,
                    f"{header[:14]} now has a paragraph (i). The letter/roman-numeral "
                    f"discriminator in _top_level_letters is no longer safe for it.",
                )

    def test_paragraph_slicing_survives_nested_roman_numerals(self):
        """The helper every derivation below depends on, proven rather than assumed.

        § 205.203(c) nests (c)(1)(i)-(iii) and (c)(2)(i)-(iii). An "ends at the next [a-z]"
        terminator stopped at "(i)" INSIDE (c)(1) and reported one item where there are three —
        a silent undercount in the exact helper that is supposed to make undercounting
        impossible.
        """
        body = _section_body(self.corpus, "§ 205.203 Soil fertility and crop nutrient management practice standard.")
        items = re.findall(r"\n\s*\((\d+)\)\s", _paragraph_body(body, "c"))
        self.assertEqual(
            items,
            ["1", "2", "3"],
            "§ 205.203(c) has three material categories — raw manure, composted materials, "
            "uncomposted plant materials. Slicing returned something else.",
        )

    def test_no_205_103_clause_is_missing_from_the_mapping(self):
        """Re-derive the clause list from the regulation itself.

        § 205.103(b)(5) was absent from the summary this mapping was built to check. A hand-
        maintained list would have inherited that omission silently; this reads the source.
        """
        body = _section_body(self.corpus, "§ 205.103 Recordkeeping by certified operations.")
        expected = {"205.103(a)", "205.103(c)"}
        expected |= {f"205.103(b)({n})" for n in re.findall(r"\n\s*\((\d+)\)\s", body)}

        mapped = {c.id for c in clauses_for_section("205.103")}
        self.assertEqual(
            mapped,
            expected,
            f"Mapping and regulation disagree for § 205.103.\n"
            f"  in the CFR but not mapped: {sorted(expected - mapped)}\n"
            f"  mapped but not in the CFR: {sorted(mapped - expected)}",
        )

    def test_no_205_201_top_level_clause_is_missing(self):
        """(a)(1)-(6) plus (b) and (c). The ten (c)(n) sub-clauses inherit (c)'s disposition
        and are deliberately not enumerated — see the note on that clause."""
        body = _section_body(self.corpus, "§ 205.201 Organic production and handling system plan.")
        # ONLY paragraph (a)'s own numbered items — see _paragraph_body for why slicing beats
        # filtering by number.
        a_items = re.findall(r"\n\s*\((\d+)\)\s", _paragraph_body(body, "a"))
        self.assertTrue(a_items, "Could not isolate § 205.201(a) — the section text has changed shape.")
        expected = {f"205.201(a)({n})" for n in a_items}
        expected |= {"205.201(b)", "205.201(c)"}

        mapped = {c.id for c in clauses_for_section("205.201")}
        self.assertEqual(
            mapped,
            expected,
            f"Mapping and regulation disagree for § 205.201.\n"
            f"  in the CFR but not mapped: {sorted(expected - mapped)}\n"
            f"  mapped but not in the CFR: {sorted(mapped - expected)}",
        )

    def test_no_production_standard_top_level_clause_is_missing(self):
        """§§ 205.202-205.206 — the practice standards, derived from the regulation.

        These are the clauses a packet gets REJECTED on: buffers, manure intervals, compost
        specifications, seed sourcing, the pest hierarchy. § 205.103 and § 205.201 only govern
        whether a record exists and traces; these govern whether the practice it describes is
        allowed at all. A silent hole here is the expensive kind.
        """
        sections = {
            "205.202": "§ 205.202 Land requirements.",
            "205.203": "§ 205.203 Soil fertility and crop nutrient management practice standard.",
            "205.206": "§ 205.206 Crop pest, weed, and disease management practice standard.",
        }
        for section, header in sections.items():
            with self.subTest(section=section):
                body = _section_body(self.corpus, header)
                expected = {f"{section}({letter})" for letter in _top_level_letters(body)}
                mapped = {
                    c.id for c in clauses_for_section(section) if re.fullmatch(rf"{re.escape(section)}\([a-z]\)", c.id)
                }
                self.assertEqual(
                    mapped,
                    expected,
                    f"Mapping and regulation disagree for § {section}.\n"
                    f"  in the CFR but not mapped: {sorted(expected - mapped)}\n"
                    f"  mapped but not in the CFR: {sorted(mapped - expected)}",
                )

    def test_seed_standard_exemptions_are_all_mapped(self):
        """§ 205.204(a)(1)-(5) are the exemptions that make non-organic stock usable.

        Enumerated individually rather than folded into (a), because each one is a DIFFERENT
        evidence burden — a commercial-availability search, a treatment basis, a temporary
        variance, a twelve-month clock, a phytosanitary order — and collapsing them hides which
        burdens the product actually carries.
        """
        body = _section_body(self.corpus, "§ 205.204 Seeds and planting stock practice standard.")
        expected = {f"205.204(a)({n})" for n in re.findall(r"\n\s*\((\d+)\)\s", _paragraph_body(body, "a"))}
        mapped = {c.id for c in clauses_for_section("205.204") if re.fullmatch(r"205\.204\(a\)\(\d+\)", c.id)}
        self.assertEqual(
            mapped,
            expected,
            f"§ 205.204 exemptions out of sync.\n"
            f"  in the CFR but not mapped: {sorted(expected - mapped)}\n"
            f"  mapped but not in the CFR: {sorted(mapped - expected)}",
        )

    def test_every_mapped_section_exists_in_the_corpus(self):
        """No clause may cite a section the regulation does not contain."""
        invented = sorted(
            {c.id.split("(")[0] for c in BINDING_CLAUSES if f"§ {c.id.split('(')[0]} " not in self.corpus}
        )
        self.assertEqual(invented, [], f"These clause ids cite sections absent from the frozen CFR: {invented}")

    def test_soe_amendment_is_reflected(self):
        """SOE (88 FR 3621/3622, Jan. 19, 2023) is the newest binding change in scope.

        If the corpus were ever swapped for a pre-2023 revision, the supplier-verification and
        fraud-prevention sentence would vanish from § 205.201(a)(3) and this mapping would be
        quietly describing superseded law.
        """
        self.assertIn(
            "prevent organic fraud",
            self.normalized_corpus,
            "The frozen CFR does not contain the SOE fraud-prevention language. The corpus may "
            "predate 88 FR 3622 (Jan. 19, 2023).",
        )


class BindingClauseIntegrityTests(SimpleTestCase):
    """Every claim in the mapping must cost something to make."""

    def test_clause_ids_are_unique(self):
        ids = [c.id for c in BINDING_CLAUSES]
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate clause ids: {ids}")

    def test_every_clause_has_a_real_rationale(self):
        thin = [c.id for c in BINDING_CLAUSES if len(c.rationale.strip()) < 40]
        self.assertEqual(
            thin,
            [],
            f"These clauses have no real rationale written against them: {thin}. A disposition "
            f"without a reason is a label, not an assessment.",
        )

    def test_satisfied_clauses_name_both_code_and_proof(self):
        """SOFTWARE_SATISFIES is the strongest thing this file can say."""
        unproven = [
            c.id
            for c in BINDING_CLAUSES
            if c.disposition is Disposition.SOFTWARE_SATISFIES and not (c.implementation and c.tests)
        ]
        self.assertEqual(
            unproven,
            [],
            f"These clauses claim SOFTWARE_SATISFIES without naming both an implementation and "
            f"a test: {unproven}. Downgrade the disposition or add the proof.",
        )

    def test_out_of_scope_clauses_explain_themselves(self):
        for clause in BINDING_CLAUSES:
            if clause.disposition is Disposition.OUT_OF_SCOPE:
                with self.subTest(clause=clause.id):
                    self.assertTrue(
                        len(clause.rationale) > 60,
                        f"{clause.id} is marked OUT_OF_SCOPE. That is a substantive claim about "
                        f"who Trazo serves and needs a substantive reason.",
                    )

    def test_every_cited_implementation_exists(self):
        """The anti-rot guard: a rename must break this, not silently orphan the mapping."""
        missing = []
        for clause in BINDING_CLAUSES:
            for ref in clause.implementation:
                path_part, _, symbol = ref.partition("::")
                path = REPO_ROOT / path_part
                if not path.exists():
                    missing.append(f"{clause.id}: no such file {path_part}")
                    continue
                if symbol and not _defines_symbol(path, symbol):
                    missing.append(f"{clause.id}: {path_part} does not define {symbol}")
        self.assertEqual(missing, [], "Stale implementation references:\n  " + "\n  ".join(missing))

    def test_the_symbol_check_is_actually_strict(self):
        """Prove the anti-rot guard can FAIL, not just pass.

        A citation checker that only ever returns True is decorative. Two cases matter most:
        a symbol that does not exist, and a symbol that exists on a DIFFERENT class — the
        second is what a substring sweep can never catch, and is what this file itself got
        wrong (§ 205.202(b) named `Parcel` for fields that live on `ParcelCropHistory`).
        """
        history_models = REPO_ROOT / "trazo-back/history/models.py"
        product_models = REPO_ROOT / "trazo-back/product/models.py"

        self.assertTrue(_defines_symbol(history_models, "ProductionEvent"))
        self.assertTrue(_defines_symbol(history_models, "ProductionEvent.harvest_lot_code"))
        self.assertTrue(_defines_symbol(history_models, "compute_retention_until"))

        self.assertFalse(
            _defines_symbol(history_models, "ProductionEvent.totally_made_up_field"),
            "a nonexistent attribute must not satisfy the citation check",
        )
        self.assertFalse(
            _defines_symbol(product_models, "Parcel.last_prohibited_substance"),
            "the field exists in this FILE but on ParcelCropHistory — naming the wrong owner "
            "must fail, which is precisely what a substring sweep cannot detect",
        )

    def test_every_cited_test_module_exists(self):
        missing = [
            f"{clause.id}: {ref}"
            for clause in BINDING_CLAUSES
            for ref in clause.tests
            if not (REPO_ROOT / ref).exists()
        ]
        self.assertEqual(missing, [], "Stale test references:\n  " + "\n  ".join(missing))

    def test_no_clause_claims_more_than_software_can_do(self):
        """Two clauses are known to be unsatisfiable by software. Pin them.

        § 205.103(c) is a person opening records to an inspector; § 205.201(a)(6) is whatever
        a certifying agent additionally asks for. If either is ever upgraded to
        SOFTWARE_SATISFIES, that is an overclaim and this test should be the thing that says so.
        """
        for clause_id in ("205.103(c)", "205.201(a)(6)"):
            clause = next(c for c in BINDING_CLAUSES if c.id == clause_id)
            with self.subTest(clause=clause_id):
                self.assertIs(
                    clause.disposition,
                    Disposition.OPERATOR_COMMITMENT,
                    f"{clause_id} cannot be satisfied by software. Re-read the clause before " f"changing this.",
                )


class FrozenGuidanceCorpusTests(SimpleTestCase):
    """Layer 3 — the NOP Handbook. Guidance, and it must stay labelled as guidance.

    Frozen so certifier EXPECTATIONS can be cited by file rather than from memory. The whole
    reason this corpus exists is that "NOP 5029" was being cited across the Planting form, the
    certifier packet and the demo seeder while appearing nowhere in any frozen source.
    """

    #: (file, the phrase that proves it is the right document)
    EXPECTED = {
        "NOP-5029.txt": "Seeds, Annual Seedlings, and Planting Stock",
        "NOP-5021.txt": "Compost and Vermicompost",
        "NOP-5006.txt": "Processed Animal Manures",
        "NOP-5025.txt": "Commingling and Contamination Prevention",
        "NOP-5026.txt": "Chlorine Materials",
        "NOP-5012.txt": "Liquid Fertilizers",
    }

    def test_the_guidance_corpus_is_present_and_is_what_it_claims(self):
        missing = []
        for name, phrase in self.EXPECTED.items():
            path = CORPUS_HANDBOOK_DIR / "txt" / name
            if not path.exists():
                missing.append(f"{name}: absent")
                continue
            if phrase.lower() not in path.read_text(encoding="utf-8", errors="replace").lower():
                missing.append(f"{name}: does not contain {phrase!r} — wrong document at this path")
        self.assertEqual(missing, [], "Frozen guidance corpus problems:\n  " + "\n  ".join(missing))

    def test_nop_5029_actually_supports_the_three_source_expectation(self):
        """The citation that started this. Pin the sentence, not the memory of it.

        If a re-pull ever removes or reworks this passage, the product's seed-search coaching
        loses its basis and should change with it — loudly, not silently.
        """
        text = _normalize((CORPUS_HANDBOOK_DIR / "txt" / "NOP-5029.txt").read_text(encoding="utf-8", errors="replace"))
        self.assertIn(
            "documentation of contact with three or more seed or planting stock sources",
            text,
            "NOP 5029 no longer contains the three-or-more-sources passage the seed-search "
            "coaching is based on. Re-read the document before changing the product.",
        )

    def test_the_guidance_is_recorded_as_non_binding(self):
        """The single most important property of this corpus.

        A product that blocks a save on guidance has treated non-binding text as law. The
        MANIFEST must keep saying so, in AMS's own words.
        """
        manifest = (CORPUS_HANDBOOK_DIR / "MANIFEST.md").read_text(encoding="utf-8", errors="replace")
        self.assertIn("non-binding", manifest)
        self.assertIn("must not BLOCK on guidance", manifest)

    def test_guidance_is_not_mapped_as_a_binding_clause(self):
        """Layer separation, enforced.

        Handbook sections are expectations, not clauses. If a NOP 50xx number ever appears as a
        binding clause id, the layers have been conflated — which is how a form ends up telling
        a grower that a certifier's preference is federal law.
        """
        leaked = [c.id for c in BINDING_CLAUSES if "5029" in c.id or "NOP" in c.id.upper()]
        self.assertEqual(leaked, [], f"Guidance documents mapped as binding clauses: {leaked}")
