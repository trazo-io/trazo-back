"""
Phase 1 / B3 — fields the farmer fills in must reach the certifier PDF.

Every field below was collected by a form, stored on the model, and rendered in NO export
section. That is the worst failure mode this document has: the farmer did the work, the
record looks complete, and the evidence is silently absent when an inspector asks.

This is a COVERAGE test, not a layout test. It asserts the value string appears somewhere
in the rendered flowables for its section. It deliberately does not assert which column —
the point is that the data reaches the page at all, so a future layout change that moves a
field is fine and one that drops it is not.
"""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import (
    ChemicalEvent,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
)
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def flowable_text(elements):
    """Flatten rendered flowables (tables + paragraphs) into one searchable string."""
    out = []
    for el in elements:
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                text = getattr(cell, "text", None)
                if text:
                    out.append(text)
        paragraph_text = getattr(el, "text", None)
        if paragraph_text:
            out.append(paragraph_text)
    return " ".join(out)


class PdfFieldCoverageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="coverage@test.com", password="x")
        self.company = Company.objects.create(name="Coverage Farm")
        self.establishment = Establishment.objects.create(name="CE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="C-parcel", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Almond")
        self.now = timezone.now()
        self.history = History.objects.create(
            name="Coverage Production",
            start_date=self.now - timedelta(days=200),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _service(self):
        return AuditExportService(self.history, certification_type="organic")

    # ---- Chemical section -------------------------------------------------

    def test_authorizer_name_reaches_the_input_traceability_table(self):
        """GLOBALG.A.P. FV-GFS 32.02.01 #10 — who approved the application."""
        ChemicalEvent.objects.create(
            history=self.history,
            type="PE",
            date=self.now,
            description="Spinosad for NOW",
            commercial_name="Entrust SC",
            supplier_name="Wilbur-Ellis",
            applicator_name="Ana Torres",
            authorizer_name="Jordan Blake PCA",
        )
        text = flowable_text(self._service()._build_chemical_log())
        self.assertIn("Jordan Blake PCA", text)
        self.assertIn("Ana Torres", text)
        self.assertIn("Application Context", text)

    def test_state_application_facts_reach_the_conditions_table(self):
        """WAC 16-228-1320(1) items (e), (h), (k), (l), (n): typed on the spray form, so printed.

        2026-11-12 (OV-FJ-C11). Wind, temperature, carrier volume, apparatus plate and the
        applicator's and firm's contact details each have a column on ChemicalEvent and an input
        on the spray form; a packet that dropped any of them would hand an inspector a blank the
        grower had filled.
        """
        ChemicalEvent.objects.create(
            history=self.history,
            type="FU",
            date=self.now,
            description="Copper before rain",
            commercial_name="Cueva",
            wind_from="SW",
            wind_speed_mph=3,
            air_temperature_f=55,
            carrier_volume=150,
            carrier_volume_unit="gal_per_acre",
            apparatus_license_plate="8F12345",
            applicator_address="3 Ridge Road, Hood River, OR 97031",
            applicator_phone="541-555-0110",
            applied_by_pcb=True,
            pcb_name="Gorge Spray Co",
            commercial_firm_address="9 Mill Street, The Dalles, OR 97058",
        )
        text = flowable_text(self._service()._build_chemical_log())
        for expected in (
            "from SW at 3 mph",
            "55 °F",
            "150 gal/acre",
            "8F12345",
            "3 Ridge Road, Hood River, OR 97031",
            "541-555-0110",
            "9 Mill Street, The Dalles, OR 97058",
        ):
            self.assertIn(expected, text, f"{expected!r} never reached the certifier packet")

    def test_contamination_incident_note_reaches_the_packet(self):
        """The operator's own account of an incident, in the section that holds the incident.

        🔴 2026-08-31 — it reached NEITHER table. `_build_general_events_section` deliberately
        excludes contamination events and points the reader to the § 205.272 log; that log
        carried only the structured fields. So the grower's narrative fell through the gap
        between the two — the one event class in the packet whose field notes were missing, and
        the class where what the operator says happened is most of what an inspector reads for.
        """
        GeneralEvent.objects.create(
            history=self.history,
            date=self.now,
            name="Spray drift from neighbouring block",
            activity_type="emergency",
            observation=(
                "Neighbour applied to the vineyard across the county road on a rising wind. "
                "Two outside rows showed deposit at the fence line."
            ),
            is_contamination_incident=True,
            contamination_source="spray_drift",
            contamination_affected_area=1.2,
            corrective_action_taken="Rows flagged and held pending residue screening.",
        )
        text = flowable_text(self._service()._build_soe_compliance_section())
        self.assertIn("Contamination Incident Log", text)
        self.assertIn(
            "Neighbour applied to the vineyard",
            text,
            "the operator's own account of the incident never reached the packet",
        )
        # The structured fields must still be there — the note is additional, not a replacement.
        self.assertIn("Rows flagged and held", text)

    def test_one_incident_on_two_parcels_reads_as_one_in_the_operation_dossier(self):
        """The incident log has no parcel column, and the operation dossier lists every
        production's incidents. One drift event logged on two parcels is two records sharing
        an application_group: each row must say it is one incident and where else it hit,
        or the certifier reads two incidents."""
        other_parcel = Parcel.objects.create(name="D-parcel", establishment=self.establishment, area=4.0)
        other = History.objects.create(
            name="Second Production",
            start_date=self.now - timedelta(days=200),
            product=self.product,
            parcel=other_parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        group = uuid.uuid4()
        for season, area in ((self.history, 1.2), (other, 0.4)):
            GeneralEvent.objects.create(
                history=season,
                date=self.now,
                name="Drift",
                is_contamination_incident=True,
                contamination_source="spray_drift",
                contamination_affected_area=area,
                application_group=group,
            )
        service = self._service()
        service.scope_productions = [self.history, other]
        text = flowable_text(service._build_soe_compliance_section())
        self.assertIn("one incident on 2 parcels: C-parcel, D-parcel; this row: C-parcel", text)
        self.assertIn("this row: D-parcel", text)

        # A season export (or a date window) holds only some of the incident's records: the
        # note still names every parcel it hit, read from the database, not from the scope.
        alone = flowable_text(self._service()._build_soe_compliance_section())
        self.assertIn("one incident on 2 parcels: C-parcel, D-parcel; this row: C-parcel", alone)

    def test_tank_mix_adjuvant_reaches_the_input_application_log(self):
        """An adjuvant is a material applied to the crop, so § 205.105 covers it too.

        🔴 2026-08-31 — tank-mix partners had NO route into this packet, for any subtype. They
        reached the CA PUR export on their own DPR-PML-017C line and nothing else, so a
        certifier reading the input log never saw the spreader-sticker that went in the tank.
        On a FERTILIZER it was worse: PUR does not report fertilizers at all (box 23), and the
        display registry gated the field to PE/FU/HE, so the grower could not see it either.
        """
        ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=self.now,
            description="Fish emulsion with a spreader-sticker",
            commercial_name="Neptune's Harvest 2-3-1",
            tank_mix_partners=[
                {
                    "commercial_name": "Nu-Film-P",
                    "manufacturer": "Miller Chemical",
                    "epa_registration_number": "50011-AA",
                    "volume": "1.5",
                    "volume_unit": "qt",
                    "organic_approved": True,
                }
            ],
        )
        text = flowable_text(self._service()._build_chemical_log())
        self.assertIn("Nu-Film-P", text, "the adjuvant never reached the certifier packet")
        self.assertIn("Adjuvant", text)
        self.assertIn("50011-AA", text, "the adjuvant's registration number is what makes it checkable")
        self.assertIn("1.5 qt", text)
        self.assertIn("Miller Chemical", text)
        # A bare checkbox may not be reported as a listing programme — same rule the parent
        # row's "grower-selected, no listing on file" enforces.
        self.assertIn("grower-reported", text)
        self.assertNotIn("OMRI Listed", text)

    def test_blank_tank_mix_rows_are_not_printed(self):
        """The form leaves empty partner objects behind; they are not applications."""
        ChemicalEvent.objects.create(
            history=self.history,
            type="PE",
            date=self.now,
            description="Spinosad",
            commercial_name="Entrust SC",
            tank_mix_partners=[{"commercial_name": "", "epa_registration_number": "", "volume": ""}, "junk"],
        )
        text = flowable_text(self._service()._build_chemical_log())
        self.assertNotIn("Adjuvant", text, "a blank partner row printed as an application")

    def test_fertigation_flag_reaches_the_application_table(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=self.now,
            description="Fish hydrolysate through drip",
            commercial_name="Fish Hydrolysate 2-4-1",
            is_fertigation=True,
            way_of_application="drip",
        )
        self.assertIn("Fertigated", flowable_text(self._service()._build_chemical_log()))

    def test_growth_stage_reaches_the_application_table(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type="FU",
            date=self.now,
            description="Sulfur at bloom",
            commercial_name="Kumulus DF",
            target_pest_disease="Brown rot",
            growth_stage="bloom",
        )
        text = flowable_text(self._service()._build_chemical_log())
        self.assertIn("Brown rot", text)
        self.assertIn("Bloom/Flowering", text)

    def test_application_context_subtable_absent_when_nothing_recorded(self):
        # A plain spray with no stage, no fertigation and no authoriser must not add an
        # empty context table to the packet.
        ChemicalEvent.objects.create(
            history=self.history,
            type="PE",
            date=self.now,
            description="Routine spray",
            commercial_name="Entrust SC",
        )
        self.assertNotIn("Application Context", flowable_text(self._service()._build_chemical_log()))

    # ---- Soil section -----------------------------------------------------

    def test_working_depth_and_texture_reach_the_soil_section(self):
        SoilManagementEvent.objects.create(
            history=self.history,
            type="TI",
            date=self.now,
            description="Shallow incorporation",
            area_covered=5.0,
            working_depth=6.0,
            depth_unit="in",
            soil_texture="sandy_loam",
            soil_moisture="field_capacity",
        )
        text = flowable_text(self._service()._build_soil_section())
        self.assertIn("6.00 in", text)
        self.assertIn("sandy_loam", text)
        # `soil_moisture` is deliberately NOT printed (dropped 2026-08-15). Its input was
        # removed from SoilManagementTab because it duplicated the Weather event, so the
        # column could only ever render "—" for any record created since — an empty promise
        # on a certifier's desk. The model column survives so pre-removal rows still render
        # elsewhere; this asserts the packet stays quiet about it.
        self.assertNotIn("field_capacity", text)

    def test_soil_condition_subtable_absent_when_nothing_recorded(self):
        SoilManagementEvent.objects.create(
            history=self.history,
            type="CC",
            date=self.now,
            description="Cover crop seeded",
            area_covered=5.0,
        )
        self.assertNotIn("Soil Condition", flowable_text(self._service()._build_soil_section()))

    # ---- Pest section -----------------------------------------------------

    def test_chemical_free_period_reaches_the_pest_section(self):
        PestManagementEvent.objects.create(
            history=self.history,
            type="SC",
            date=self.now,
            description="Scouting pass",
            pest_species="Navel orangeworm",
            chemical_free_period_days=145,
        )
        self.assertIn("145", flowable_text(self._service()._build_pest_section()))

    def test_growth_stage_reaches_the_pest_section(self):
        PestManagementEvent.objects.create(
            history=self.history,
            type="SC",
            date=self.now,
            description="Scouting pass",
            pest_species="Navel orangeworm",
            extra_data={"crop_growth_stage": "hull split"},
        )
        text = flowable_text(self._service()._build_pest_section())
        self.assertIn("Navel orangeworm", text)
        self.assertIn("hull split", text)

    # ---- Production + traceability ---------------------------------------

    def test_growth_stage_reaches_the_production_events_table(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="TH",
            date=self.now,
            description="Thinning pass",
            area_covered=5.0,
            growth_stage="fruit_set",
        )
        self.assertIn("Fruit Set", flowable_text(self._service()._build_production_events()))

    def test_transport_distance_reaches_the_traceability_section(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=self.now,
            description="Harvest and haul to huller",
            area_covered=5.0,
            transportation_distance=42.5,
            transportation_unit="miles",
        )
        text = flowable_text(self._service()._build_traceability_section())
        self.assertIn("42.50 miles", text)

    def test_traceability_omits_transport_row_when_no_haul_recorded(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=self.now,
            description="Harvest, no haul recorded",
            area_covered=5.0,
        )
        self.assertNotIn("Transport Distance", flowable_text(self._service()._build_traceability_section()))

    # ---- Supervisor sign-off (attestation) -------------------------------

    def test_supervisor_signoff_reaches_the_attestation_section(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="IR",
            date=self.now,
            description="Irrigation set",
            area_covered=5.0,
            reviewed=True,
            reviewer_name="Marta Ruiz",
            review_date=self.now.date(),
        )
        text = flowable_text(self._service()._build_producer_attestation_section())
        self.assertIn("Supervisor Record Review", text)
        self.assertIn("Marta Ruiz", text)

    def test_equipment_signoffs_are_scanned_too(self):
        """§ 112.161(b) names "equipment and tool cleaning" as a review-required record.

        EquipmentEvent inherits reviewed/reviewer_name/review_date from CommonEvent like
        every other event model, so omitting it from the scan would drop exactly the
        sign-offs the regulation asks about.
        """
        from history.models import EquipmentEvent

        EquipmentEvent.objects.create(
            history=self.history,
            type="CL",
            date=self.now,
            description="Harvester cleaned before organic block",
            reviewed=True,
            reviewer_name="Dana Okonkwo",
            review_date=self.now.date(),
        )
        text = flowable_text(self._service()._build_producer_attestation_section())
        self.assertIn("Dana Okonkwo", text)
        self.assertIn("Equipment", text)

    def test_attestation_has_no_signoff_table_when_nothing_reviewed(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="IR",
            date=self.now,
            description="Irrigation set",
            area_covered=5.0,
        )
        self.assertNotIn(
            "Supervisor Record Review",
            flowable_text(self._service()._build_producer_attestation_section()),
        )

    # ---- Application fuel stays out of the organic packet -----------------

    def test_application_fuel_renders_in_the_carbon_appendix(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type="PE",
            date=self.now,
            description="Spinosad",
            commercial_name="Entrust SC",
            application_fuel_type="diesel",
            application_fuel_consumed=3.5,
            application_fuel_unit="gal",
        )
        self.assertIn("3.50 gal", flowable_text(self._service()._build_carbon_section()))

    def test_carbon_appendix_is_not_part_of_the_organic_export(self):
        """Energy figures on a certifier document invite greenwashing-by-association.

        The application-fuel table is only reachable through the carbon appendix, so this
        assertion is what keeps it out of the organic packet.
        """
        from history.services.audit_export_service import AuditExportService as Svc

        self.assertNotIn("carbon", Svc.CERTIFICATION_SECTIONS["organic"])
        self.assertIn("carbon", Svc.CERTIFICATION_SECTIONS["all"])
