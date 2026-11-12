"""Every certificate note reads back as a code the app can word in the reader's language.

Settings audit leftover, 2026-11-12: a Spanish reader saw the verifier's English ("Found 504 organic
operations in Oregon but none matched 'Test' above 90% confidence") under their certificate.
"""

from datetime import date

from django.test import SimpleTestCase, TestCase

from certifications.models import Certification, USDAOrganicOperation
from certifications.serializers import CertificationSerializer
from certifications.services.usda_organic_verifier import USDAOrganicVerifier
from certifications.verification_notes import TEMPLATES, parse, render
from company.models import Company
from product.models import Establishment

SAMPLES = {
    "not_loaded": {},
    "no_automated_check": {},
    "no_operations_in_state": {"state": "Oregon"},
    "no_match": {"count": 504, "state": "Oregon", "name": "Test's Farm (North)", "threshold": 90},
    "matched": {"op_name": "Earthbound Farm, LLC", "confidence": 97},
    "possible_name_similar": {"op_name": "Green Valley Vineyards, Inc.", "similarity": 91},
    "possible_name_shared": {"op_name": "Sunrise Orchards", "similarity": 100, "same_name_count": 2},
    "possible_certifier_missing": {"op_name": "Sunrise Orchards", "similarity": 100, "farm_certifier": "WSDA"},
    "possible_certifier_differs": {
        "op_name": "Sunrise Orchards",
        "similarity": 100,
        "db_certifier": "Oregon Tilth",
        "farm_certifier": "WSDA",
    },
}


class TemplateRoundTripTests(SimpleTestCase):
    def test_every_template_has_a_sample(self):
        self.assertEqual(set(SAMPLES), set(TEMPLATES))

    def test_every_note_parses_back_to_its_code_and_params(self):
        for code, params in SAMPLES.items():
            with self.subTest(code=code):
                self.assertEqual(parse(render(code, **params)), (code, params))

    def test_text_no_template_wrote_has_no_code(self):
        self.assertEqual(parse("Verified by hand by the certifier"), (None, {}))
        self.assertEqual(parse(""), (None, {}))
        self.assertEqual(parse(None), (None, {}))

    def test_notes_stored_before_the_codes_still_parse(self):
        """Wording that was in the database before 2026-11-12, byte for byte."""
        old = "Found 504 organic operations in Oregon but none matched 'Test' above 90% confidence"
        self.assertEqual(parse(old), ("no_match", {"count": 504, "state": "Oregon", "name": "Test", "threshold": 90}))
        old = (
            "Possible database entry 'Sunrise Orchards' (100% name similarity); not confirmed: 2 operations "
            "in the state carry this name. The certification stays self-reported until the operator's own "
            "entry is confirmed."
        )
        self.assertEqual(parse(old)[0], "possible_name_shared")


class VerifierWritesParseableNotesTests(TestCase):
    def setUp(self):
        USDAOrganicOperation.objects.create(
            op_name="Sunrise Orchards",
            op_name_normalized=USDAOrganicVerifier._normalize_name("Sunrise Orchards"),
            state="Oregon",
            status="Certified",
            data_snapshot_date=date(2026, 11, 1),
        )
        for n in range(3):
            USDAOrganicOperation.objects.create(
                op_name=f"Blue Heron {n}",
                op_name_normalized=USDAOrganicVerifier._normalize_name(f"Blue Heron {n}"),
                state="Oregon",
                status="Certified",
                data_snapshot_date=date(2026, 11, 1),
            )

    def test_the_verifier_notes_all_parse(self):
        verifier = USDAOrganicVerifier()
        results = [
            verifier.verify("Nothing Alike Whatsoever", "OR"),
            verifier.verify("Sunrise Orchards", "OR"),
            verifier.verify("Sunrise Orchards", "OR", certifier_name="Washington State Department of Agriculture"),
            verifier.verify("Anyone", "Vermont"),
        ]
        codes = [parse(r.notes)[0] for r in results]
        self.assertEqual(codes, ["no_match", "matched", "possible_certifier_missing", "no_operations_in_state"])

    def test_the_serializer_serves_code_and_params(self):
        company = Company.objects.create(name="Note Co")
        farm = Establishment.objects.create(name="Note Farm", company=company, state="OR")
        cert = Certification.objects.create(
            establishment=farm,
            certification_type="usda_organic",
            verification_notes=render("no_match", count=4, state="Oregon", name="Note Farm", threshold=90),
        )
        data = CertificationSerializer(cert).data
        self.assertEqual(data["verification_note_code"], "no_match")
        self.assertEqual(data["verification_note_params"]["count"], 4)
        self.assertIn("none matched", data["verification_notes"], "the English stays for the PDFs and the admin")

    def test_a_note_stored_with_the_none_sentinel_reads_as_missing(self):
        """Review of #406: before the code existed the verifier wrote certifier 'none'."""
        old = (
            "Possible database entry 'Sunrise Orchards' (100% name similarity); not confirmed: the database "
            "lists certifier 'none', the farm recorded 'WSDA'. The certification stays self-reported until "
            "the operator's own entry is confirmed."
        )
        code, params = parse(old)
        self.assertEqual(code, "possible_certifier_missing")
        self.assertNotIn("db_certifier", params)
