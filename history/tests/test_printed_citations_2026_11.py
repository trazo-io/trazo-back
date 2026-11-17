"""Legal citations the certifier packet and the audit dossier print, as corrected in November 2026.

WHY. The 2026-11 overall review (lane L4b) checked every citation the product prints against the
current eCFR (versioner API, 2026-11-01 edition) and found paragraphs that say something else and
claims no paragraph makes. Each wrong string below printed on a document a certifier reads:

  CIT01  "Producer Attestation (7 CFR 205.401(d))": (d) is "Other information necessary to
         determine compliance". No part 205 paragraph prescribes an attestation. "promptly
         notify" understated § 205.400(f), which says "Immediately notify".
  CIT05  "40 CFR 170.309" for restricted-use applicator certification. § 170.309 is agricultural
         employer duties; certification for restricted use pesticides is 7 U.S.C. 136j(a)(2)(F).
  CIT07  sales records labelled § 205.307(a), the nonretail container labeling paragraph. Sales
         records are § 205.103(b)(2) (traceable records) and (b)(3) (audit trail).
  CIT08  treated lumber cited to § 205.272. The prohibition is § 205.206(f).
  CIT09  off-farm hulling, drying and cold storage "must be performed by a certified organic
         handler (7 CFR 205.272)". Who must be certified is § 205.100(a), subject to § 205.101
         (sealed, tamper-evident packages are exempt under § 205.101(e)).
  CIT10  the Strengthening Organic Enforcement rule dated "effective March 19, 2024" (it is 88 FR
         3548, effective March 20, 2023, compliance date March 19, 2024), credited with five-year
         retention (which predates it), and § 205.201(a)(3) described as a written plan with a
         vulnerability assessment and corrective-action protocols (it asks for a description of
         monitoring practices, including those that verify suppliers and prevent organic fraud).
  CIT12  "All soil amendments must be OMRI-listed or NOP-approved" under § 205.203(b). No
         paragraph says it; amendments are § 205.203(d) and (e) with § 205.105.
  CIT13  treated non-organic seed "disqualifies the crop from organic sale" under § 205.204(a)(2).
         The paragraph says when such seed may be used; the outcome is the certifying agent's.
  C05    "Input catalogs last synced: OMRI <date>" printed the date someone ran the loader, never
         the edition of the published list, and the disclaimer promised an OMRI subscription "on
         the Trazo roadmap".
  VID-04 (recordkeeping checklist run, 2026-11-16) a letter to a neighbor cited to
         § 205.400(f)(1), on every boundary that had one and in a note printed on every dossier.
         (f)(1) is the operation's duty to tell its certifying agent about an application or
         drift; a letter to a neighbor is a practice the plan describes to prevent contact,
         § 205.201(a)(5). The same note said the operator "maintains" such a letter whether or
         not one was on file.
  VID-05 the Common OSP record list cited cultivation to § 205.206(a)(1), which is crop rotation
         and nutrient management. Mechanical cultivation is § 205.206(c)(4).

HOW. The printing modules are read as Python and every string literal is collected (adjacent
literals are joined by the parser, so a sentence split over several source lines is one string).
Comments and docstrings are not printed and are not read. Item C05 also runs the freshness line
against real catalog rows, because the fix is behaviour (the edition comes from the data).

The (a)(3) wording is the eCFR text of 7 CFR 205.201(a)(3), retrieved 2026-11-10:
"to verify suppliers in the supply chain and organic status of agricultural products received,
and to prevent organic fraud".
"""

import ast
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase, TestCase

ROOT = Path(__file__).resolve().parents[2]

DOSSIER = "history/services/audit_export_service.py"
PLAN = "certifications/services/osp_pdf_snapshot.py"
MODULE_PDF = "certifications/services/osp_module_pdf.py"
PRODUCTION_EVENT_MODEL = "history/models/production_event.py"
CHEMICAL_EVENT_MODEL = "history/models/chemical_event.py"
SERIALIZERS = "history/serializers.py"
SEED_TEMPLATE = "certifications/management/commands/seed_osp_template.py"

#: (finding, source, strings that must be gone, strings that must be printed). A string matches
#: when it is a substring of one literal in the source.
CASES = (
    (
        "CIT03/CIT13",
        PRODUCTION_EVENT_MODEL,
        ("disqualifies the crop", "before the crop it produces may be sold as organic"),
        ("may itself be sold, ", "is the certifying agent's decision"),
    ),
    # Found by the review bot on back #377: the same errors in places the first pass missed.
    (
        "CIT10",
        DOSSIER,
        ("88 FR 3622)", "required under SOE 2024", "SOE 2024 Compliance Items"),
        ("Strengthening Organic Enforcement Compliance Items (88 FR 3548)",),
    ),
    (
        "CIT10",
        "history/management/commands/_solana_verde_base.py",
        ("SOE rule effective ", "Vulnerability assessment covers"),
        ("88 FR 3548, effective 2023-03-20, compliance date 2024-03-19):\n",),
    ),
    (
        "CIT01",
        PLAN,
        ("Producer Attestation (7 CFR 205.401", "promptly notify"),
        ("I agree to immediately notify my certifying agent",),
    ),
    (
        "CIT01",
        DOSSIER,
        ("Producer Attestation (7 CFR 205.401", "promptly notify"),
        ("I agree to immediately notify my certifying agent",),
    ),
    (
        "CIT01",
        MODULE_PDF,
        ("Producer attestation (7 CFR 205.401(d))",),
        ("Producer attestation: the information above is true",),
    ),
    (
        "CIT05",
        CHEMICAL_EVENT_MODEL,
        ("170.309", "per EPA Worker Protection Standard"),
        ("7 U.S.C. 136j(a)(2)(F)",),
    ),
    (
        "CIT05",
        SERIALIZERS,
        ("170.309", "per EPA Worker Protection Standard"),
        ("7 U.S.C. 136j(a)(2)(F)",),
    ),
    (
        "CIT07",
        DOSSIER,
        (
            "Sales Records on File (§ 205.307(a))",
            "Itemized Sales Records (7 CFR 205.307(a))",
            "itemized sales record(s) on file (§ 205.307(a))",
        ),
        (
            "Sales Records on File (§ 205.103(b)(2) and (b)(3))",
            "Itemized Sales Records (7 CFR 205.103(b)(2) and (b)(3))",
            "itemized sales record(s) on file (§ 205.103(b)(2) and (b)(3))",
        ),
    ),
    (
        "CIT08",
        DOSSIER,
        ("205.272 \u2014 Treated lumber",),
        ("Treated lumber present (7 CFR 205.206(f))",),
    ),
    (
        "CIT09",
        DOSSIER,
        ("certified organic handler (7 CFR 205.272)", "organic certificate must accompany the lot (7 CFR 205.272"),
        ("certified organic handler (7 CFR 205.100(a)), subject to the exemptions in § 205.101", "§ 205.101(e)"),
    ),
    (
        "CIT10",
        DOSSIER,
        (
            "effective March 19, 2024",
            "effective 2024-03-19",
            "effective 2024-03-",
            "5-year record retention",
            "vulnerability assessment",
            "corrective-action protocols",
            "requires every certified operation to",
        ),
        (
            "88 FR 3548; effective March 20, 2023, compliance date March 19, 2024",
            "to verify suppliers in the supply chain and organic status of agricultural products received, "
            "and to prevent organic fraud",
        ),
    ),
    (
        "CIT10",
        SEED_TEMPLATE,
        ("SOE rule effective 2024-03-19",),
        ("88 FR 3548, effective 2023-03-20, compliance date 2024-03-19",),
    ),
    (
        "CIT12",
        DOSSIER,
        ("must be OMRI-listed or NOP-approved", "NOP 7 CFR 205.203(b):"),
        ("7 CFR 205.203(d) and (e), § 205.105",),
    ),
    (
        "CIT13",
        DOSSIER,
        ("Non-organic seed treated with substances not on the National List disqualifies the crop",),
        (
            "This paragraph allows nonorganically produced seeds and planting stock treated with a substance "
            "included on the National List",
            "What follows for the crop is the certifying agent's decision.",
        ),
    ),
    (
        "C05",
        DOSSIER,
        ("Input catalogs last synced", "on the Trazo roadmap", "partial copy of the WSDA"),
        ("Input catalogs: ", "edition date not recorded in Trazo", "each as of the edition date given below"),
    ),
    (
        "VID-04",
        DOSSIER,
        (
            "drift-notification letter on file (§ 205.400(f)(1))",
            "drift-notification readiness",
            "Operator maintains the drift-prevention measures above",
            # Review of back #462: the field is a yes and a date, never the letter itself.
            "letter to this neighbor on file",
            "those on file are listed above",
        ),
        (
            " (drift prevention, § 205.201(a)(5))",
            "prevention practice the plan describes under § 205.201(a)(5)",
            "to the certifying agent immediately (§ 205.400(f)(1))",
        ),
    ),
    (
        "VID-04",
        "certifications/models.py",
        ("drift-notification readiness",),
        ("(a drift-prevention practice, § 205.201(a)(5))",),
    ),
    (
        "VID-04",
        "history/management/commands/seed_showcase_walnut_farm.py",
        ("letter on file (§ 205.400(f)(1))",),
        ("letter on file (§ 205.201(a)(5))",),
    ),
    (
        "VID-05",
        "certifications/services/common_osp_records.py",
        ("7 CFR 205.206(a)(1)",),
        ("7 CFR 205.206(c)(4)",),
    ),
)


def _docstring_ids(tree):
    """ids of the Constant nodes that are docstrings: never printed, so never read here."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            first = body[0] if body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def printed_strings(rel):
    """Every non-docstring string literal in `rel`, including the literal parts of f-strings."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    skip = _docstring_ids(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
    ]


class PrintedCitationsTests(SimpleTestCase):
    def test_the_sources_are_read(self):
        """Non-vacuity: an unreadable or renamed module would make every absence pass."""
        for rel in {source for _, source, _, _ in CASES}:
            with self.subTest(source=rel):
                self.assertGreater(len(printed_strings(rel)), 10, f"{rel} yielded too few strings to trust")

    def test_the_matcher_finds_a_planted_wrong_string(self):
        """The absence checks below are negative; prove the matcher fires on a real literal."""
        tree_text = 'x = ("Producer Attestation " "(7 CFR 205.401(d))")\n'
        literals = [n.value for n in ast.walk(ast.parse(tree_text)) if isinstance(n, ast.Constant)]
        self.assertTrue(any("Producer Attestation (7 CFR 205.401" in s for s in literals))

    def test_no_wrong_citation_is_printed(self):
        offenders = []
        for finding, rel, wrong, _ in CASES:
            strings = printed_strings(rel)
            for phrase in wrong:
                hits = [s for s in strings if phrase in s]
                if hits:
                    offenders.append(f"{finding} {rel}: {phrase!r} still printed in {hits[0][:120]!r}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_corrected_citation_is_printed(self):
        missing = []
        for finding, rel, _, right in CASES:
            strings = printed_strings(rel)
            for phrase in right:
                if not any(phrase in s for s in strings):
                    missing.append(f"{finding} {rel}: {phrase!r} not printed")
        self.assertEqual(missing, [], "\n".join(missing))

    def test_both_producer_attestation_headings_carry_no_paragraph(self):
        for rel in (PLAN, DOSSIER):
            with self.subTest(source=rel):
                self.assertIn("Producer Attestation", printed_strings(rel))


class CatalogEditionLineTests(TestCase):
    """C05 is behaviour: the edition comes from the catalog rows, so it is checked on rows."""

    def _line(self):
        from history.services.audit_export_service import AuditExportService

        # The freshness line reads class state and catalog rows only, never a production.
        return AuditExportService.__new__(AuditExportService)._catalog_freshness_line()

    def test_the_edition_prints_beside_the_load_date(self):
        from certifications.models import IngestionRun, OMRIProduct, WSDAMaterial

        OMRIProduct.objects.create(omri_id="dow-2900", product_name="Entrust", list_edition_date=date(2026, 9, 26))
        WSDAMaterial.objects.create(wsda_id="1123", brand_name="Kaligreen", list_effective_date=date(2026, 3, 6))
        omri = IngestionRun.objects.create(source="omri", status="ok")
        wsda = IngestionRun.objects.create(source="wsda", status="ok")
        cdfa = IngestionRun.objects.create(source="cdfa_oim", status="ok")

        line = self._line()

        self.assertIn(f"OMRI list of 2026-09-26 (loaded {omri.ran_at.date().isoformat()})", line)
        self.assertIn(f"WSDA list of 2026-03-06 (loaded {wsda.ran_at.date().isoformat()})", line)
        # CDFA OIM is a flag on the rows above with no edition of its own: said, never borrowed.
        self.assertIn(
            f"CDFA OIM list, edition date not recorded in Trazo (loaded {cdfa.ran_at.date().isoformat()})", line
        )
        self.assertNotIn(f"OMRI {omri.ran_at.date().isoformat()}", line)

    def test_a_failed_catalog_is_still_not_confirmed_current(self):
        from certifications.models import IngestionRun

        IngestionRun.objects.create(source="wsda", status="error", message="boom")

        line = self._line()

        self.assertIn("Not confirmed current", line)
        self.assertNotIn("WSDA list of", line)
