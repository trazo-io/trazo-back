"""
Phase 4 / §E-4 + §E-5 — the two records a California organic orchard could not keep.

§E-4  Winter sanitation. 7 CFR 205.206(a) requires PREVENTIVE practices, and § 205.206(e) only
      permits a substance once those practices prove insufficient. In a California almond or
      walnut block the preventive practice for navel orangeworm is the December mummy shake,
      blow and shred — the single most common non-spray control an organic grower performs, and
      it had no subtype. A grower who did the work all winter had nothing to show for it, while
      the spray they applied in June was fully documented. That asymmetry reads, to an inspector
      and to a shopper, as an operation that only sprays.

§E-5  Custom operators. The UC Davis 2024 organic-almond study hires out cover-crop seeding,
      flame weeding, brush shredding, winter sanitation, harvest and hulling, and that custom
      harvest equipment moves between conventional and organic orchards. That is the § 205.272
      commingling exposure in its most concrete form — yet the operation could not say "a
      contractor ran this pass" or "this is the cleaning that preceded it".

      The page-1 snapshot previously answered a coarser question: "does this operation keep
      cleaning records at all". With the link it answers the real one: "was THIS pass preceded by
      a cleaning". Note the deliberate restraint below — an operation that has NOT adopted the
      link is judged exactly as before, rather than being retroactively downgraded for missing a
      feature that did not exist when it logged its season.
"""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, PestManagementEvent, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class OrchardBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="cu@test.com", password="x")
        company = Company.objects.create(name="Sanitation Farm")
        establishment = Establishment.objects.create(name="SF1", company=company, state="CA")
        parcel = Parcel.objects.create(name="cu-parcel", establishment=establishment, area=44.5)
        product = Product.objects.create(name="Almond")
        self.history = History.objects.create(
            name="Sanitation Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _section_text(self, builder_name, certification_type="organic"):
        svc = AuditExportService(self.history, certification_type=certification_type)
        out = []
        for el in getattr(svc, builder_name)():
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    if getattr(cell, "text", None):
                        out.append(cell.text)
            if getattr(el, "text", None):
                out.append(el.text)
        return " ".join(out)


class CulturalControlTests(OrchardBase):
    def _sanitation(self, practice="mummy_removal", **kwargs):
        return PestManagementEvent.objects.create(
            history=self.history,
            type="CU",
            date=kwargs.pop("date", timezone.now()),
            description="December mummy shake",
            cultural_practice=practice,
            **kwargs,
        )

    def test_cu_is_a_real_subtype(self):
        self.assertIn("CU", dict(PestManagementEvent._meta.get_field("type").choices))

    def test_the_uc_davis_practices_are_selectable(self):
        codes = dict(PestManagementEvent._meta.get_field("cultural_practice").choices)
        for practice in ("mummy_removal", "sanitation_shake", "brush_shred", "pruning_removal"):
            self.assertIn(practice, codes)

    def test_a_cultural_event_must_name_its_practice(self):
        """ "We did cultural control" supports nothing at inspection."""
        event = PestManagementEvent(history=self.history, type="CU", date=timezone.now(), description="Winter work")
        with self.assertRaises(ValidationError) as ctx:
            event.clean()
        self.assertIn("cultural_practice", ctx.exception.message_dict)

    def test_other_pest_subtypes_are_unaffected(self):
        PestManagementEvent(
            history=self.history, type="SC", date=timezone.now(), description="Scouting pass"
        ).clean()  # must not raise

    def test_it_renders_in_the_organic_packet(self):
        self._sanitation(pest_species="Navel orangeworm", area_covered=44.5, area_unit="acres")
        text = self._section_text("_build_pest_section")
        self.assertIn("Preventive Cultural Practices", text)
        self.assertIn("Mummy nut removal", text)
        self.assertIn("Navel orangeworm", text)
        self.assertIn("205.206(a)", text)

    def test_the_table_is_absent_without_cultural_events(self):
        PestManagementEvent.objects.create(history=self.history, type="SC", date=timezone.now(), description="Scouting")
        self.assertNotIn("Preventive Cultural Practices", self._section_text("_build_pest_section"))

    def test_the_practice_is_shown_not_the_raw_code(self):
        self._sanitation(practice="brush_shred")
        text = self._section_text("_build_pest_section")
        self.assertIn("Brush / mummy shredding", text)
        self.assertNotIn("brush_shred", text)


class CustomOperatorAndCleaningLinkTests(OrchardBase):
    def _cleaning(self, when=None, documented=True):
        when = when or timezone.now() - timezone.timedelta(days=2)
        return ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=when,
            description="Harvester wash-down",
            equipment_operation_type="CL",
            cleaning_date=when.date() if documented else None,
            cleaning_method="Pressure wash + compressed air" if documented else "",
            cleaned_by="R. Alvarez" if documented else "",
        )

    def _shared_harvest(self, when=None, cleaning=None, custom=True):
        return ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=when or timezone.now(),
            description="Custom harvest",
            area_covered=44.5,
            area_unit="acres",
            performed_by="Valley Custom Harvesting",
            operator_is_custom=custom,
            shared_with_conventional=True,
            equipment_cleaning_event=cleaning,
        )

    def test_a_cleaning_after_the_operation_is_refused(self):
        """Evidence has to precede the thing it protects (§ 205.272)."""
        now = timezone.now()
        late = self._cleaning(when=now + timezone.timedelta(days=3))
        event = self._shared_harvest(when=now)
        event.equipment_cleaning_event = late
        with self.assertRaises(ValidationError) as ctx:
            event.clean()
        self.assertIn("equipment_cleaning_event", ctx.exception.message_dict)

    def test_a_non_cleaning_event_cannot_be_the_link(self):
        harvest = ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), description="Other harvest", area_covered=1
        )
        event = self._shared_harvest()
        event.equipment_cleaning_event = harvest
        with self.assertRaises(ValidationError) as ctx:
            event.clean()
        self.assertIn("equipment_cleaning_event", ctx.exception.message_dict)

    def test_an_event_cannot_be_its_own_cleaning_record(self):
        event = self._cleaning()
        event.equipment_cleaning_event = event
        with self.assertRaises(ValidationError):
            event.clean()

    def test_a_valid_prior_cleaning_is_accepted(self):
        now = timezone.now()
        cleaning = self._cleaning(when=now - timezone.timedelta(days=1))
        event = self._shared_harvest(when=now, cleaning=cleaning)
        event.clean()  # must not raise
        self.assertEqual(event.equipment_cleaning_event_id, cleaning.pk)

    def test_the_coverage_table_names_the_cleaning(self):
        now = timezone.now()
        self._shared_harvest(when=now, cleaning=self._cleaning(when=now - timezone.timedelta(days=1)))
        text = self._section_text("_build_equipment_section")
        self.assertIn("Cleaning Coverage", text)
        self.assertIn("Valley Custom Harvesting", text)
        self.assertIn("Pressure wash", text)

    def test_an_unlinked_shared_operation_is_flagged(self):
        self._cleaning()
        self._shared_harvest()  # deliberately unlinked
        self.assertIn("REVIEW — no cleaning event linked", self._section_text("_build_equipment_section"))

    def test_the_coverage_table_is_absent_without_shared_or_custom_work(self):
        ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), description="Own harvest", area_covered=44.5
        )
        self.assertNotIn("Cleaning Coverage", self._section_text("_build_equipment_section"))


class ContaminationSnapshotTests(OrchardBase):
    """The page-1 row is the first thing an inspector or a buyer's QA reads."""

    def _snapshot_row(self):
        svc = AuditExportService(self.history, certification_type="organic")
        for row in svc._build_compliance_snapshot():
            if isinstance(row, (list, tuple)) and row and "205.272" in str(row[0]):
                return row
        # The builder may return flowables; fall back to scanning rendered text.
        return None

    def _snapshot_text(self):
        return self._section_text("_build_compliance_snapshot")

    def _cleaning(self, when, documented=True):
        return ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=when,
            description="Wash-down",
            equipment_operation_type="CL",
            cleaning_date=when.date() if documented else None,
            cleaning_method="Pressure wash" if documented else "",
            cleaned_by="R. Alvarez" if documented else "",
        )

    def _shared(self, when, cleaning=None):
        return ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=when,
            description="Custom harvest",
            area_covered=44.5,
            shared_with_conventional=True,
            operator_is_custom=True,
            equipment_cleaning_event=cleaning,
        )

    def test_linking_every_shared_operation_reads_as_covered(self):
        now = timezone.now()
        self._shared(now, cleaning=self._cleaning(now - timezone.timedelta(days=1)))
        text = self._snapshot_text()
        self.assertIn("shared-equipment operation(s) reference a documented", text)

    def test_a_partly_linked_season_is_reported_as_a_fraction(self):
        now = timezone.now()
        cleaning = self._cleaning(now - timezone.timedelta(days=1))
        self._shared(now, cleaning=cleaning)
        self._shared(now, cleaning=None)
        text = self._snapshot_text()
        self.assertIn("1/2 shared-equipment operation(s)", text)

    def test_a_cleaning_record_is_not_itself_an_operation_needing_coverage(self):
        """Asking the wash-down record to reference a wash-down is circular.

        The EM event legitimately carries shared_with_conventional=True (it documents cleaning
        BECAUSE the equipment is shared). Counting it as an operation awaiting coverage reported
        "1/2 covered" for a season with exactly one harvest and the cleaning that preceded it —
        an operation doing everything right, told it was half-documented.
        """
        now = timezone.now()
        cleaning = self._cleaning(now - timezone.timedelta(days=1))
        cleaning.shared_with_conventional = True
        cleaning.save(update_fields=["shared_with_conventional"])
        self._shared(now, cleaning=cleaning)

        text = self._snapshot_text()
        self.assertIn("All 1 shared-equipment operation(s) reference a documented", text)
        self.assertNotIn("1/2", text)

    def test_an_operation_not_using_links_is_judged_exactly_as_before(self):
        """No retroactive downgrade for a feature that did not exist last season."""
        now = timezone.now()
        self._cleaning(now - timezone.timedelta(days=1))
        self._shared(now, cleaning=None)
        text = self._snapshot_text()
        # The legacy aggregate verdict, not the new per-operation wording.
        self.assertNotIn("shared-equipment operation(s) reference", text)
        self.assertIn("205.272", text)


class CulturalPracticeConsumerPayloadTests(OrchardBase):
    """The practice must survive into the anonymous payload.

    Found in the Phase 6 dress rehearsal: `cultural_practice` was wired into the read and update
    serializers, the display registry and the normalizer allow-list — but NOT into
    PublicHistorySerializer's hand-built pest dict. So a winter-sanitation event reached the
    consumer page as a generic pest record with nothing to say, which is the opposite of why the
    subtype exists. Every surface has to be checked; a field is not shipped until the last one has it.
    """

    def _payload_events(self):
        from history.serializers import PublicHistorySerializer

        return PublicHistorySerializer(self.history, context={}).data.get("events") or []

    def test_the_practice_reaches_the_consumer(self):
        PestManagementEvent.objects.create(
            history=self.history,
            type="CU",
            date=timezone.now(),
            description="December mummy shake",
            cultural_practice="sanitation_shake",
            pest_species="Navel orangeworm",
        )
        event = next(e for e in self._payload_events() if e.get("pest_management_type") == "CU")
        self.assertEqual(event.get("cultural_practice"), "sanitation_shake")

    def test_a_non_cultural_pest_event_carries_no_practice(self):
        PestManagementEvent.objects.create(history=self.history, type="SC", date=timezone.now(), description="Scouting")
        event = next(e for e in self._payload_events() if e.get("pest_management_type") == "SC")
        self.assertIsNone(event.get("cultural_practice"))
