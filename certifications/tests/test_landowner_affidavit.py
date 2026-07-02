"""
Landowner affidavit serializer — blank-attestation default.

The form field is labeled "leave blank to use the standard wording", but the model TextField
has default="" without blank=True, so DRF's mapped field rejected an explicit "" with
"This field may not be blank" (a silent 400 for a farmer following the hint). The serializer
now allows blank and fills the canonical MOFGA attestation.
"""

from django.test import TestCase

from certifications.models import LandownerAffidavit
from certifications.serializers import LandownerAffidavitSerializer
from company.models import Company, Establishment
from product.models import Parcel


class LandownerAffidavitAttestationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Affidavit Farm")
        self.establishment = Establishment.objects.create(name="AE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="AP", establishment=self.establishment, area=10.0)

    def _base_data(self):
        return {"parcel": self.parcel.id, "previous_manager_name": "Prior Owner"}

    def test_blank_attestation_defaults_to_standard_wording(self):
        data = {**self._base_data(), "attestation_text": ""}
        ser = LandownerAffidavitSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data["attestation_text"], LandownerAffidavit.ATTESTATION_TEXT)

    def test_missing_attestation_defaults_to_standard_wording(self):
        ser = LandownerAffidavitSerializer(data=self._base_data())
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data["attestation_text"], LandownerAffidavit.ATTESTATION_TEXT)

    def test_custom_attestation_is_preserved(self):
        custom = "Custom attestation wording the signer agreed to."
        data = {**self._base_data(), "attestation_text": custom}
        ser = LandownerAffidavitSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data["attestation_text"], custom)

    def test_partial_update_omitting_attestation_does_not_overwrite(self):
        """A PATCH that doesn't touch attestation_text must leave the saved custom text intact."""
        custom = "Signer's own custom attestation."
        affidavit = LandownerAffidavit.objects.create(
            parcel=self.parcel, previous_manager_name="Prior Owner", attestation_text=custom
        )
        ser = LandownerAffidavitSerializer(affidavit, data={"previous_manager_phone": "530-555-0000"}, partial=True)
        self.assertTrue(ser.is_valid(), ser.errors)
        obj = ser.save()
        obj.refresh_from_db()
        self.assertEqual(obj.attestation_text, custom, "partial PATCH overwrote the custom attestation")
