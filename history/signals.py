import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from carbon.services.event_carbon_calculator import EventCarbonCalculator

from .models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    EventAmendment,
    GeneralEvent,
    PestManagementEvent,
    ProductionEvent,
    SalesRecord,
    SoilManagementEvent,
    WeatherEvent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalise block_id on every event type before it is stored.
#
# block_id is free text and load-bearing: CA PUR box 22, the audit export's Input Application Log,
# and the landing site for a COG Pro migration's "Row/Section ID". Without this, "Block 3",
# "block 3 " and "Block  3" are three different blocks to every query that groups by it, and a
# certifier asking "what happened in Block 3" silently gets a subset.
#
# Only mechanical variation is collapsed — the grower's own wording is preserved, because that is
# what they will look for during an inspection. See history/services/block_ids.py.
# ---------------------------------------------------------------------------
@receiver(
    pre_save,
    sender=BusinessEvent,
    dispatch_uid="normalize_block_id_business",
)
@receiver(pre_save, sender=ChemicalEvent, dispatch_uid="normalize_block_id_chemical")
@receiver(pre_save, sender=EquipmentEvent, dispatch_uid="normalize_block_id_equipment")
@receiver(pre_save, sender=GeneralEvent, dispatch_uid="normalize_block_id_general")
@receiver(pre_save, sender=PestManagementEvent, dispatch_uid="normalize_block_id_pest")
@receiver(pre_save, sender=ProductionEvent, dispatch_uid="normalize_block_id_production")
@receiver(pre_save, sender=SoilManagementEvent, dispatch_uid="normalize_block_id_soil")
@receiver(pre_save, sender=WeatherEvent, dispatch_uid="normalize_block_id_weather")
def normalize_event_block_id(sender, instance, **kwargs):
    from history.services.block_ids import normalize_block_id

    instance.block_id = normalize_block_id(instance.block_id)


# ---------------------------------------------------------------------------
# Sprint 3 — Auto-classify ChemicalEvent against the National List (7 CFR 205.601/602)
# on every save. Populates national_list_substance FK so the audit export can
# show "Allowed per §205.601(i)" rather than "Self-reported" even when the
# frontend hasn't been updated to let farmers set it manually.
# Never overwrites a farmer/admin-set value.
# ---------------------------------------------------------------------------

# Warn once per process rather than once per event: an unseeded National List is a deployment
# fact, not a per-record one, and a bulk import would otherwise emit thousands of identical lines.
_warned_national_list_unseeded = False


@receiver(pre_save, sender=ChemicalEvent)
def auto_classify_chemical_against_national_list(sender, instance, **kwargs):
    """Classify against the National List by exact name or curated alias only.

    OSP alignment audit, Phase 5 slice 1 (2026-10-02): the forward-substring and reverse-container
    passes below used to store their guess in `national_list_substance`, and every document then cited
    a § listing for it. They now record a SUGGESTION, which nothing cites. The basis of a stored
    classification is kept in `national_list_basis`; a legacy row (classified before the basis was
    kept) is left exactly as it is until the operator decides.
    """
    from history.models import ChemicalEvent as _CE

    # Respect explicit set — only classify when not already set. A legacy row keeps its value and its
    # basis here, whatever its name now reads. A value set by code that recorded no basis is not
    # presumed exact: it is marked legacy-unverified, the same as a pre-basis row.
    if instance.national_list_substance_id is not None:
        if not instance.national_list_basis:
            instance.national_list_basis = _CE.NL_BASIS_LEGACY
        return
    instance.national_list_basis = ""
    instance.national_list_suggestion = None
    # Try the ACTIVE INGREDIENT first, then the brand.
    #
    # The National List (7 CFR 205.601/.602) is keyed on substance names — "Spinosad", "Copper
    # sulfate". A brand never appears there: "Entrust SC" is not listed and never will be, though
    # its active ingredient is. Matching only on commercial_name therefore returned nothing for
    # any record that named a product rather than a chemical, which is how farmers actually write
    # them and how COG Pro exports them.
    extra = getattr(instance, "extra_data", None) or {}
    active_ingredient = extra.get("active_ingredient") if isinstance(extra, dict) else None
    candidates = [c for c in (active_ingredient, instance.commercial_name) if c]
    if not candidates:
        return

    try:
        from certifications.services.omri_verifier import OMRIProductVerifier, _normalize

        verifier = OMRIProductVerifier()
        if not verifier.health_check():
            # Previously `return` with no signal at all. Silence here is expensive: every
            # ChemicalEvent is saved with no CFR classification, and the certifier-facing
            # findings — the thing the compliance pitch rests on — come back empty with nothing
            # to indicate why. Also surfaced by /health/ via reference_data_status.
            global _warned_national_list_unseeded
            if not _warned_national_list_unseeded:
                _warned_national_list_unseeded = True
                logger.warning(
                    "National List is not seeded — ChemicalEvents are being saved WITHOUT a "
                    "7 CFR 205.601/602 classification, so certifier findings will be empty. "
                    "Run `manage.py seed_national_list`. (Warned once per process.)"
                )
            return
        # Crop rows only. Migration 0038 seeds § 205.605 HANDLING sanitizers into every database: a
        # spray named "Ozone" matched one exactly and was classified under a handling listing, and
        # "hypochlorous acid" found a container in each section and fell through as ambiguous
        # (review, 2026-09-10). A crop input is classified against the crop listings.
        from certifications.services.reference_data_status import national_list_crop_rows

        crop_rows = national_list_crop_rows()
        for candidate in candidates:
            # Deliberately NOT gated on `verifier.verify(...).found`.
            #
            # OMRI and the National List are independent authorities. OMRI lists finished
            # PRODUCTS ("DiPel DF"); 7 CFR 205.601/.602 lists SUBSTANCES, sometimes as a class.
            # Requiring an OMRI hit before consulting the National List meant a substance that is
            # plainly listed could not be cited: "Bacillus thuringiensis" returns found=False from
            # the OMRI verifier, so one of the commonest organic inputs never reached the matcher
            # below and rendered as "Self-reported" on the certifier packet.
            #
            # `health_check()` above is still the right gate — it tests whether the National List
            # table is seeded at all, which is a different question.
            normalized = _normalize(candidate)
            nl = crop_rows.filter(substance_name_normalized=normalized).first()
            basis = _CE.NL_BASIS_EXACT

            if nl is None:
                # Curated crosswalk BEFORE either fuzzy pass, because it is the only one of the
                # three that a human checked against the CFR text. "Sulfur" is listed as
                # "Elemental sulfur", "Boron" as "Soluble boron products" — real listings that
                # neither substring pass can reach, and which the reverse pass actively blocks
                # because it demands >= 12 characters and a space.
                from certifications.services.national_list_aliases import resolve_alias

                canonical = resolve_alias(normalized)
                if canonical:
                    nl = crop_rows.filter(substance_name=canonical).first()
                    basis = _CE.NL_BASIS_ALIAS
                    if nl is None:
                        # The alias names a substance that is not seeded. Silent here would be the
                        # exact failure this table exists to prevent, so say so.
                        logger.warning(
                            "National List alias %r -> %r has no seeded row; classification skipped.",
                            normalized,
                            canonical,
                        )

            if nl is not None:
                instance.national_list_substance = nl
                instance.national_list_basis = basis
                return

            # Below: partial-name passes. A hit is a SUGGESTION, never a classification.
            suggestion = None
            if nl is None:
                # Forward: the list entry appears inside the farmer's text.
                # "Entrust SC (Spinosad 22.5%)" contains "spinosad".
                substrings = [
                    n
                    for n in crop_rows.values_list("substance_name_normalized", flat=True)
                    if len(n) >= 5 and n in normalized
                ]
                if substrings:
                    best = max(substrings, key=len)
                    suggestion = crop_rows.filter(substance_name_normalized=best).first()

            if suggestion is None:
                # Reverse: the farmer's substance appears inside a CATEGORY entry on the list.
                # Several National List entries name a class rather than a chemical — Bacillus
                # thuringiensis is catalogued only as "Microbial products (Bacillus thuringiensis,
                # etc.)", so forward matching alone left one of the commonest organic inputs
                # unclassified and it rendered as "Self-reported" on the certifier packet.
                #
                # Guarded harder than the forward pass: the input must be a substantial phrase,
                # not a bare word. "copper" would otherwise match both "Copper sulfate
                # (algicide)" and "Copper hydroxide", and picking either would be a guess about
                # which substance the farmer applied.
                if len(normalized) >= 12 and " " in normalized:
                    containers = [
                        n for n in crop_rows.values_list("substance_name_normalized", flat=True) if normalized in n
                    ]
                    # Only accept an unambiguous container: two matches means we cannot tell
                    # which listing the farmer meant, and a wrong § citation is worse than none.
                    if len(containers) == 1:
                        suggestion = crop_rows.filter(substance_name_normalized=containers[0]).first()
            # Candidates run active ingredient first: a later candidate (the brand) never replaces the
            # suggestion an earlier one made.
            if suggestion is not None and instance.national_list_suggestion_id is None:
                instance.national_list_suggestion = suggestion
    except Exception:  # noqa: BLE001 — classification is advisory; never block a save
        import logging

        logging.getLogger(__name__).exception(
            "Auto-classification failed for ChemicalEvent commercial_name=%r",
            instance.commercial_name,
        )


# Module-level singleton — EventCarbonCalculator is stateless, no need to
# re-instantiate (and re-load all USDA factors) on every signal fire.
_calculator = None


def _get_calculator():
    global _calculator
    if _calculator is None:
        _calculator = EventCarbonCalculator()
    return _calculator


# F09 (2026-06): the carbon-calc signal handlers below previously swallowed
# exceptions with a bare print(), so a crashed calculation looked identical to a
# true zero-emission event (no CarbonEntry, no trace). They now log at ERROR with
# exc_info so failures are visible in logs/monitoring (Sentry).
#
# NOTE: an earlier revision of this fix ALSO wrote a 0-amount CarbonEntry flagged
# verification_status="calculation_error" to make failures queryable in the DB.
# That was reverted — its description contained the "{cls}(ID={id})" substring
# that the consumer/event carbon lookup matches on
# (history/serializers.py:~244, description__icontains=event_id_pattern,
# order_by("-created_at").first()), so a failed event could surface co2e=0 and
# data_source="calculation_error" on the consumer event card. A DB error marker
# needs a description that avoids that pattern + success-path cleanup + a
# consumer-query exclusion; deferred as a reviewed change.


@receiver(post_save, sender=ChemicalEvent)
def calculate_chemical_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact when a chemical event is created or updated

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-24): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields like volume_applied are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry

        calculator = _get_calculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Find and delete existing carbon entry for this event
            # Try both new format (with ID) and old format (without ID)
            event_id_pattern = f"ChemicalEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            # that match by source or other criteria for this specific event
            if deleted_count == 0:
                # For older entries without event ID in description, we need a different approach
                # Try matching by registry_verification_id which should have the event ID
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-ChemicalEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(f"🔄 Deleted {deleted_count} existing carbon entries for ChemicalEvent {instance.id} (update)")

        calculation_result = calculator.calculate_chemical_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth
        co2e_value = calculation_result.get("co2e", 0)
        if abs(co2e_value) > 0:
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(f"✅ Carbon calculation {action} for Chemical Event {instance.id}: {calculation_result['co2e']} kg CO2e")

    except Exception as e:
        logger.error("Error calculating carbon for Chemical Event %s: %s", instance.id, e, exc_info=True)


@receiver(post_save, sender=ProductionEvent)
def calculate_production_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact when a production event is created or updated

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-24): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry

        calculator = _get_calculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Try both new format (with ID) and old format (using registry_verification_id)
            event_id_pattern = f"ProductionEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-ProductionEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(f"🔄 Deleted {deleted_count} existing carbon entries for ProductionEvent {instance.id} (update)")

        calculation_result = calculator.calculate_production_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth.
        #
        # A zero is only worth storing when it is an ANSWER. For most subtypes a 0 means the
        # calculation had nothing to work with, and writing a row would dress a gap up as a
        # measurement. For the subtypes below, 0 is the correct and expected result:
        #
        #   EM / PO / PH — electric packing lines, pollination by bee hive, equipment cleaning
        #                  with no fuel use. Facility or biological work.
        #   TP / BU / SS — not area-driven at all (see `_calculate_reported_fuel_only_emissions`).
        #                  A seed search is phone calls; a buffer disposal is a recordkeeping
        #                  act; a haul with no diesel entered has nothing to count.
        #
        # Without an entry the serializer answers `carbon_data: null`, which the detail modal
        # treats as its "carbon data not available" ERROR branch — so the Carbon Impact card
        # and the zero-emission copy (`eventDetails.noDirectEmissions`, plus the record-value
        # alert) both disappear. "No CO₂ data" reads as missing data; "0 kg CO₂e — no direct
        # emissions" is the transparency signal the grower earned by logging the activity.
        #
        # 🔴 TP/BU/SS added 2026-08-22. Until the routing fix that day they were charged a
        # per-hectare diesel estimate, so they always had a (wrong, non-zero) entry and never
        # reached this branch. Correcting the calculation moved them from "wrong number" to
        # "no card at all" — the list had to widen with the fix, not after it.
        # Run 8 (R8-04, Oscar's amendment 2026-10-05): unknown is not zero. When the record holds
        # nothing to count from (no fuel or energy, and no area on area-driven work), no entry is
        # stored at all and the event carries `not_estimated` with a null estimate instead. The
        # Every other result was computed from something the record holds (reported fuel or
        # energy, the event's own area, a transport distance), so its value is an answer, zero
        # included: an electric line on solar, or a pollination with no fuel, is "no direct
        # emissions", not missing data. Review of back #123: a subtype allowlist here dropped
        # those zeros, leaving neither an entry nor a status, so the card vanished.
        if calculation_result.get("not_estimated"):
            calculator.record_carbon_status(instance, calculation_result)
        elif (calculation_result.get("co2e") or 0) >= 0:
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)
            calculator.record_carbon_status(instance, None)

        action = "created" if created else "updated"
        print(
            f"✅ Carbon calculation {action} for Production Event {instance.id}: {calculation_result['co2e']} kg CO2e"
        )

    except Exception as e:
        logger.error("Error calculating carbon for Production Event %s: %s", instance.id, e, exc_info=True)


@receiver(post_save, sender=WeatherEvent)
def calculate_weather_event_carbon(sender, instance, created, **kwargs):
    """
    Calculate carbon impact for weather events.

    Some weather events generate real emissions (frost protection with heaters,
    drought irrigation, hailstorm cleanup, high-temp cooling). Others are purely
    transparency documentation (storms, winds, humidity).

    FIX (2026-03-10): Previously skipped CarbonEntry creation for ALL weather
    events, losing real emissions from frost/drought/hail/heat responses.
    """
    try:
        from carbon.models import CarbonEntry

        calculator = _get_calculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            event_id_pattern = f"WeatherEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-WeatherEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(f"🔄 Deleted {deleted_count} existing carbon entries for WeatherEvent {instance.id} (update)")

        calculation_result = calculator.calculate_weather_event_impact(instance)
        co2e_value = calculation_result.get("co2e", 0)

        if abs(co2e_value) > 0:
            calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        if abs(co2e_value) > 0:
            print(f"✅ Carbon calculation {action} for Weather Event {instance.id}: {co2e_value} kg CO2e")
        else:
            print(
                f"✅ Transparency documentation {action} for Weather Event {instance.id}:"
                " 0.0 kg CO2e (transparency value only)"
            )

    except Exception as e:
        logger.error("Error calculating carbon for Weather Event %s: %s", instance.id, e, exc_info=True)


@receiver(post_save, sender=GeneralEvent)
def calculate_general_event_carbon(sender, instance, created, **kwargs):
    """
    General events record no carbon.

    A general event is administration, planning, training, record-keeping or an inspection —
    there is no farmer-controlled operational input to measure, and Trazo's methodology is
    direct operational emissions only (.claude/rules/carbon-methodology.md).

    Until 2026-07 this receiver persisted a fabricated 0.1 kg CO2e, gated on a keyword match
    over the event name and notes. See the note below and the tests in
    history/tests/test_general_event_no_carbon.py.

    The receiver is kept (rather than deleted) so that saving a general event actively
    REMOVES any legacy fabricated entry still attached to it.
    """
    try:
        from carbon.models import CarbonEntry

        # Sweep any CarbonEntry attached to this event. This runs on create as well as
        # update on purpose: rows written by the pre-2026-07 fabricated-value path are still
        # in the database, and touching the event is the natural moment to purge one. Both
        # lookup shapes are tried because entries were keyed inconsistently over time.
        stale_entries = CarbonEntry.objects.filter(
            production=instance.history,
            description__icontains=f"GeneralEvent(ID={instance.id})",
        )
        if not stale_entries.exists():
            stale_entries = CarbonEntry.objects.filter(
                production=instance.history,
                registry_verification_id=f"REG-GeneralEvent-{instance.id}",
            )
        removed = stale_entries.count()
        if removed:
            stale_entries.delete()
            logger.info(
                "Removed %s carbon entr%s for GeneralEvent %s (general events record no carbon)",
                removed,
                "y" if removed == 1 else "ies",
                instance.id,
            )

        # A2 fix (2026-07): general events no longer get a fabricated carbon figure.
        #
        # This used to persist a literal {"co2e": 0.1, "calculation_method":
        # "general_event_standard", "data_source": "Industry Standards"} — a number with no
        # derivation, attributed to an unnamed standard, written into a table that feeds an
        # audit-adjacent export. Worse, it was gated on a substring match over the event's
        # name and notes for ["fuel", "energy", "transport", "machinery", "equipment"], so
        # "Diesel delivery" logged 0.1 kg while "Tractor top-up" logged nothing. The keyword
        # gate made the output depend on the farmer's choice of words, not on any activity.
        #
        # A general event is administration, planning, training or record-keeping. Trazo's
        # methodology is direct operational emissions (see .claude/rules/carbon-methodology.md);
        # there is no farmer-controlled operational input here to measure. Recording nothing
        # is the honest answer, and an absent entry is easier to reason about than an
        # unverifiable 0.1.
        #
        # The context-aware `calculate_general_event_impact` in event_carbon_calculator was
        # never reachable from this signal and remains unused — if general-event energy is
        # ever worth modelling, it needs real duration/participant inputs, not a constant.
        logger.debug(
            "General Event %s: no CarbonEntry created (no direct operational emissions to attribute)",
            instance.id,
        )

    except Exception as e:
        logger.error("Error handling carbon for General Event %s: %s", instance.id, e, exc_info=True)


@receiver(post_save, sender=BusinessEvent)
def calculate_business_event_carbon(sender, instance, created, **kwargs):
    """
    Business events (certifications, audits, compliance) have no direct operational
    emissions. Log for transparency tracking only — no CarbonEntry created.
    """
    action = "created" if created else "updated"
    print(f"✅ Transparency documentation {action} for Business Event {instance.id}: 0.0 kg CO2e (no direct emissions)")


@receiver(post_delete, sender=BusinessEvent)
@receiver(post_delete, sender=ChemicalEvent)
@receiver(post_delete, sender=ProductionEvent)
@receiver(post_delete, sender=WeatherEvent)
@receiver(post_delete, sender=GeneralEvent)
@receiver(post_delete, sender=EquipmentEvent)
@receiver(post_delete, sender=SoilManagementEvent)
@receiver(post_delete, sender=PestManagementEvent)
def cleanup_carbon_entries_on_event_delete(sender, instance, **kwargs):
    """
    Clean up associated carbon entries when events are deleted
    """
    try:
        from carbon.models import CarbonEntry

        # A CASCADE delete reaches here with the parent History already gone, so
        # `instance.history` raises DoesNotExist. That is the ordinary path when a season, a
        # parcel or a whole establishment is removed — not an error — and there is nothing to
        # clean up in it either, because `CarbonEntry.production` is itself on_delete=CASCADE
        # and the database has already removed the rows (verified: 0 orphans after deleting a
        # 512-event farm).
        #
        # It mattered because the broad `except` below printed "❌ Error cleaning up carbon
        # entries" once per event — 512 lines for one farm — and a REAL cleanup failure was
        # indistinguishable from that noise. Same shape as the `except Exception` that once
        # disguised a fixture bug as a product bug.
        from history.models import History

        if instance.history_id is None or not History.objects.filter(pk=instance.history_id).exists():
            return

        # Find and delete associated carbon entries
        # FIX: Match by event ID pattern to delete only the correct CarbonEntry
        event_class_name = instance.__class__.__name__
        event_id_pattern = f"{event_class_name}(ID={instance.id})"

        # First try to match with event ID (new format)
        carbon_entries = CarbonEntry.objects.filter(
            production=instance.history, description__icontains=event_id_pattern
        )

        deleted_count = carbon_entries.count()
        carbon_entries.delete()

        if deleted_count > 0:
            print(f"🗑️ Cleaned up {deleted_count} carbon entries for deleted {event_class_name} {instance.id}")

    except Exception as e:
        print(f"❌ Error cleaning up carbon entries for {instance.__class__.__name__} {instance.id}: {e}")


@receiver(post_save, sender=EquipmentEvent)
def calculate_equipment_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact for equipment events

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-26): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields like fuel_consumed are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry

        calculator = _get_calculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Find and delete existing carbon entry for this event
            event_id_pattern = f"EquipmentEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-EquipmentEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(f"🔄 Deleted {deleted_count} existing carbon entries for EquipmentEvent {instance.id} (update)")

        calculation_result = calculator.calculate_equipment_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth
        if calculation_result.get("co2e", 0) > 0:
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(f"✅ Carbon calculation {action} for Equipment Event {instance.id}: {calculation_result['co2e']} kg CO2e")

    except Exception as e:
        logger.error("Error calculating carbon for Equipment Event %s: %s", instance.id, e, exc_info=True)


@receiver(post_save, sender=SoilManagementEvent)
def calculate_soil_management_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact for soil management events

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-26): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields like fuel_consumed or amendment_amount are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry

        calculator = _get_calculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Find and delete existing carbon entry for this event
            # Try both new format (with ID) and old format (without ID)
            event_id_pattern = f"SoilManagementEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            # that match by registry_verification_id which should have the event ID
            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-SoilManagementEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(
                    f"🔄 Deleted {deleted_count} existing carbon entries for SoilManagementEvent {instance.id} (update)"
                )

        calculation_result = calculator.calculate_soil_management_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth
        if calculation_result.get("co2e", 0) > 0:
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(
            f"✅ Carbon calculation {action} for Soil Management Event {instance.id}: {calculation_result['co2e']} kg CO2e"
        )

    except Exception as e:
        logger.error("Error calculating carbon for Soil Management Event %s: %s", instance.id, e, exc_info=True)


# Pest subtypes whose 0 kg CO2e is an ANSWER, so the signal stores it. The pest calculator adds
# no base emissions for any subtype — it counts reported fuel and nothing else — and these are
# observation and hand work: walking a block to scout, checking traps, identifying a pest, calling
# a threshold, releasing beneficials (BR, and IP, which the form pairs with the same beneficial
# fields). Every one of them offers a fuel field (scouting summaries too, as a season total), so a
# grower who drove can say so and it is counted; with none entered there is nothing to count.
#
# CULTURAL_CONTROL is left off on purpose. A sanitation shake or brush shred is tractor work, so
# a 0 there with no fuel entered is a GAP, and "No direct emissions from this activity" would be
# false. A new subtype must be sorted into one side or the other — guarded by
# history/tests/test_pest_zero_carbon_card.py.
PEST_SUBTYPES_ZERO_IS_AN_ANSWER = (
    PestManagementEvent.SCOUTING,
    PestManagementEvent.BENEFICIAL_RELEASE,
    PestManagementEvent.TRAP_MONITORING,
    PestManagementEvent.PEST_IDENTIFICATION,
    PestManagementEvent.THRESHOLD_ASSESSMENT,
    PestManagementEvent.IPM_IMPLEMENTATION,
)


@receiver(post_save, sender=PestManagementEvent)
def calculate_pest_management_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact for pest management events

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-26): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields like pesticide_amount are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry

        calculator = _get_calculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Find and delete existing carbon entry for this event
            event_id_pattern = f"PestManagementEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-PestManagementEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(
                    f"🔄 Deleted {deleted_count} existing carbon entries for PestManagementEvent {instance.id} (update)"
                )

        calculation_result = calculator.calculate_pest_management_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth.
        #
        # Until 2026-09-10 this gate was `abs(co2e) > 0.05`, so a scouting record with no fuel
        # stored no row. The serializer then answers `carbon_data: null`, the detail modal takes
        # its "not available" error branch, and the Carbon Impact card and the zero-emission
        # caption both vanish — on every pest record logged without fuel. Same defect the
        # Production subtypes above were fixed for on 2026-08-22.
        #
        # A failed calculation also returns co2e 0 (with an `error` key). Never store that as an
        # answer: it would render "No direct emissions" for an event nobody computed (F09 note).
        co2e_value = calculation_result.get("co2e", 0)
        if "error" not in calculation_result and (
            co2e_value > 0 or (co2e_value >= 0 and instance.type in PEST_SUBTYPES_ZERO_IS_AN_ANSWER)
        ):
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(
            f"✅ Carbon calculation {action} for Pest Management Event {instance.id}: {calculation_result['co2e']} kg CO2e"
        )

    except Exception as e:
        logger.error("Error calculating carbon for Pest Management Event %s: %s", instance.id, e, exc_info=True)


# Run 7 (R7-10): a record created after a season closed moves its retention floor forward.
@receiver(post_save, sender=SalesRecord, dispatch_uid="retention_floor_sales")
@receiver(post_save, sender=EventAmendment, dispatch_uid="retention_floor_amendment")
@receiver(post_save, sender=ChemicalEvent, dispatch_uid="retention_floor_chemical")
@receiver(post_save, sender=ProductionEvent, dispatch_uid="retention_floor_production")
@receiver(post_save, sender=SoilManagementEvent, dispatch_uid="retention_floor_soil")
@receiver(post_save, sender=PestManagementEvent, dispatch_uid="retention_floor_pest")
@receiver(post_save, sender=GeneralEvent, dispatch_uid="retention_floor_general")
@receiver(post_save, sender=WeatherEvent, dispatch_uid="retention_floor_weather")
@receiver(post_save, sender=EquipmentEvent, dispatch_uid="retention_floor_equipment")
@receiver(post_save, sender=BusinessEvent, dispatch_uid="retention_floor_business")
def extend_retention_floor(sender, instance, created, **kwargs):
    # Sales are voided by an update, and a void is a dated record (review of #113); events and
    # amendments count when created.
    if not created and not (sender is SalesRecord and getattr(instance, "voided_at", None)):
        return
    from .retention import extend_retention

    history = getattr(instance, "production", None) if sender is SalesRecord else getattr(instance, "history", None)
    try:
        extend_retention(history)
    except Exception:  # noqa: BLE001 — retention bookkeeping must never fail a record's save
        logger.exception("Could not extend retention for production %s", getattr(history, "pk", None))
