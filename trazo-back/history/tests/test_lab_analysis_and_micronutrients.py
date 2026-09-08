class MicronutrientCitationIsCurrentTests(SimpleTestCase):
    """🔴 2026-09-07 — the micronutrient listing had MOVED and every cite was one paragraph stale.

    Magnesium oxide was inserted at § 205.601(j)(5), pushing micronutrients from (j)(6) to
    **(j)(7)**; its subparagraphs are (i) soluble boron and (ii) the sulfates/carbonates/
    oxides/silicates. `(j)(6)` is now Magnesium sulfate, and `(j)(6)(iii)` — which four call
    sites cited — has never existed in any edition.

    A stale cite reached a PDF *section heading* in the certifier dossier, and the assertions
    in this very file pinned it there. Verified against the repo's frozen corpus
    `documentation/reference/usda-recordkeeping/cfr/title-7-part-205_2026-08-05.xml`, which is
    byte-identical to the live eCFR pull.
    """

    #: Files that state the citation to a certifier, an operator, or a reviewer.
    _CITING_FILES = (
        "history/models.py",
        "history/serializers.py",
        "history/services/audit_export_service.py",
        "certifications/services/national_list_aliases.py",
    )

    def _sources(self):
        root = Path(__file__).resolve().parents[2]
        for rel in self._CITING_FILES:
            yield rel, (root / rel).read_text(encoding="utf-8")

    def test_no_source_still_cites_the_pre_2016_micronutrient_paragraph(self):
        stale = [rel for rel, text in self._sources() if "205.601(j)(6)" in text or "(j)(6)(" in text]
        self.assertEqual(
            stale,
            [],
            "§ 205.601(j)(6) is Magnesium sulfate. Micronutrients are (j)(7). Stale in: " f"{stale}",
        )

    def test_no_source_invents_a_third_micronutrient_subparagraph(self):
        invented = [rel for rel, text in self._sources() if "(j)(7)(iii)" in text]
        self.assertEqual(
            invented,
            [],
            f"§ 205.601(j)(7) has (i) and (ii) only — molybdenum, selenium and cobalt sit inside (ii): {invented}",
        )

    def test_the_deficiency_basis_is_not_narrowed_to_soil_testing(self):
        """The current text allows soil OR TISSUE testing, or another verifiable method the
        certifying agent approves. Coaching soil-only is coaching a superseded, stricter rule."""
        root = Path(__file__).resolve().parents[2]
        text = (root / "history/services/audit_export_service.py").read_text(encoding="utf-8")
        i = text.find("micronutrients only where a deficiency is documented")
        self.assertGreater(i, -1, "the micronutrient finding text moved — re-point this guard")
        window = text[i : i + 400]
        self.assertIn("TISSUE", window.upper())
        self.assertIn("certifying agent", window)
