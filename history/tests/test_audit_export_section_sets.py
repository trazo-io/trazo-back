"""The audit-export certification picker must mean what its labels say.

`AuditExportModal` offers six choices, and the first one — the DEFAULT — reads
"All Certifications / Every event across all supported standards". That is a promise about
set membership, and on 2026-08-22 it was false: the "all" set omitted
`state_organic_registration`, so a California grower who accepted the default downloaded a
packet with no CDFA producer-registration section (CA Food & Ag Code §§ 46000-46029) — a
section the plain "USDA Organic" export did include.

The defect is invisible in every other kind of test: each export generates fine on its own,
and nothing compares the sets to each other. Compare them here.
"""

from django.test import SimpleTestCase

from history.services.audit_export_service import AuditExportService


class CertificationSectionSetTests(SimpleTestCase):
    def test_all_is_a_superset_of_every_other_certification(self):
        sets = AuditExportService.CERTIFICATION_SECTIONS
        every = set(sets["all"])
        for key, sections in sets.items():
            if key == "all":
                continue
            missing = sorted(set(sections) - every)
            self.assertEqual(
                missing,
                [],
                f'"all" is offered as "every event across all supported standards" but is '
                f'missing {missing} that the "{key}" export includes.',
            )

    def test_every_offered_certification_has_a_label_and_sections(self):
        sets = AuditExportService.CERTIFICATION_SECTIONS
        labels = AuditExportService.CERTIFICATION_LABELS
        # The frontend's CertificationKey union — a choice the modal offers with no section
        # set behind it would download an empty document.
        offered = {"all", "organic", "globalgap", "roc", "fsma204", "scs"}
        self.assertEqual(offered - set(sets), set(), "modal offers a certification the service cannot build")
        self.assertEqual(offered - set(labels), set(), "modal offers a certification with no label")
        for key in offered:
            self.assertTrue(sets[key], f"{key} resolves to an empty section list")

    def test_organic_export_excludes_the_carbon_appendix(self):
        # Deliberate, and load-bearing: USDA inspectors do not grade on environmental
        # footprint, and emissions data inside an audit PDF is a greenwashing-by-association
        # risk. If this ever flips, it must be a decision, not a merge artifact.
        self.assertNotIn("carbon", AuditExportService.CERTIFICATION_SECTIONS["organic"])

    def test_every_section_key_has_a_builder(self):
        # A section named in a set but absent from the builder map is a silently skipped
        # section — the export succeeds and the content is simply not there.
        service = AuditExportService.__new__(AuditExportService)
        builders = (
            set(service._section_builders().keys()) if callable(getattr(service, "_section_builders", None)) else None
        )
        if builders is None:
            self.skipTest("_section_builders is not introspectable")
        for key, sections in AuditExportService.CERTIFICATION_SECTIONS.items():
            unknown = sorted(set(sections) - builders)
            self.assertEqual(unknown, [], f'"{key}" names sections with no builder: {unknown}')
