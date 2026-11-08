"""
Per-event record completeness for organic-inspection purposes.

Nothing else in the codebase answers "would THIS event survive an inspection?" at the level of an
individual record. `TransparencyCalculator` counts what a production logged per event category (facts for the
consumer QR page, not a field-level check); `AuditExportService.compliance_snapshot_rows()` runs 16
CFR-cited checks but none of them look inside a chemical event's own fields. Every field on
`ChemicalEvent` that a certifier actually reads — commercial name, rate, area, target pest — is
`blank=True, null=True` at the model level (`history/models.py:1070-1273`), so a farmer can save a
spray record with none of them and Trazo says nothing until the certifier PDF prints a blank cell.

This module is the missing layer, modelled directly on the one required-field registry that
already exists: `PUR_COLUMNS` / `REQUIRED_KEYS` / `missing` in
`history/services/pur_export_service.py:32-64,343-370`. Same shape — a declarative list checked
against each event, producing a per-event list of what is missing — generalised from "one CA form"
to "what an organic inspector asks for," and applied at write time rather than only at CA PUR
export time.

Discipline: every entry MUST carry a real regulatory citation. A "required" field with no citation
is exactly the mistake this project already made once and undid — a Trazo-invented standard
presented as an external requirement (see the transparency-score demotion, 2026-08-04). If a field
matters but has no citation, it does not belong in this registry; add it to `PhotoVerificationGap`
or a roadmap suggestion instead, where "recommended" is an honest word.

Scope. v1 was `ChemicalEvent` only, four fields — the highest-stakes record type, and the
smallest citable set that catches the actual failure mode (a record `python manage.py shell` can
happily construct with every field blank).

Extended 2026-08-15 to the seed-sourced production subtypes under § 205.204 —
`SEED_SOURCED_SUBTYPES`: PL planting and TR transplanting, joined by SS seed search on
2026-08-19. The trigger was an audit finding rather than resemblance: the certifier packet
already PRINTS a seed table with columns for organic status, the § 205.2 nonavailability ground,
the supplier searches and the treatment-allowability basis — and none of them were checked
anywhere, so a planting record could reach a certifier with every one of those cells blank while
the farm dashboard's readiness card reported nothing. Every entry carries its own citation, per
the discipline above.

Extend to further event types only alongside specific citations, not by resemblance to these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from common.field_registry import (
    NO_TREATMENT_ANSWERS,
    NON_ORGANIC_SEED_STATUSES,
    ORGANIC_UNRESOLVED_VALUES,
    SEED_SOURCED_SUBTYPES,
)

# Pesticide-type subtypes: an application against a target. Fertilizer (FE) has no "target pest"
# concept, so the target-pest requirement below does not apply to it.
_PEST_TARGETING_TYPES = frozenset({"PE", "FU", "HE"})


def _present(value) -> bool:
    """Same emptiness rule PUR export uses: None, "", and whitespace-only all count as missing."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


@dataclass(frozen=True)
class RequiredField:
    key: str
    label: str
    cfr_cite: str
    # None = applies to every ChemicalEvent regardless of subtype.
    applies_to: Optional[frozenset] = None
    # How to read the value off the event. Default: getattr(event, key). Only needed when a field
    # has a legacy string twin plus a newer numeric one (volume/volume_numeric, area/area_numeric)
    # and either satisfies the requirement.
    present: Callable = field(default=None)  # type: ignore[assignment]
    # A CONDITIONAL requirement: the field is owed only when this predicate holds. Distinct
    # from `applies_to`, which keys on subtype. Use it when a field is required because of
    # something the operator already recorded, rather than because of what kind of event it is.
    applies_when: Callable = field(default=None)  # type: ignore[assignment]

    def applies(self, event) -> bool:
        if self.applies_when is not None and not self.applies_when(event):
            return False
        if self.applies_to is None:
            return True
        # `type` is nullable at the model level (history/models.py:1058) — an event with no
        # recorded subtype is a separate data-integrity problem (see
        # test_event_subtype_validation.py), not grounds to ALSO flag it as missing a
        # target pest it may not need. Stay silent rather than guess.
        return event.type in self.applies_to

    def is_present(self, event) -> bool:
        if self.present is not None:
            return self.present(event)
        return _present(getattr(event, self.key, None))


#: One label, read by the snapshot row to tell "an answer awaiting confirmation" from a gap.
UNRESOLVED_BASIS_LABEL = "organic basis not yet confirmed"


def _unresolved_basis_field(key: str) -> RequiredField:
    """§ 205.201(a)(2): the plan documents that each substance is allowed. A grower who recorded
    "Not yet confirmed" has told us the basis is owed (run 8, R8-08), so it is listed as missing
    until confirmed. Blank stays silent: conventional and not-applicable records leave it blank.
    Reads the shared set, never a literal (review of back #125)."""
    return RequiredField(
        key=key,
        # Recordkeeping review S4 (F-08): the grower's "Not yet confirmed" is a recorded answer
        # with the basis still owed, so the label says that, never "missing".
        label=UNRESOLVED_BASIS_LABEL,
        cfr_cite="§ 205.201(a)(2)",
        applies_when=lambda ev: str(getattr(ev, key, "") or "").strip() in ORGANIC_UNRESOLVED_VALUES,
        present=lambda ev: False,
    )


CHEMICAL_EVENT_REQUIRED_FIELDS: list[RequiredField] = [
    # § 205.103(b)(2): records must fully disclose activities, including materials used — an
    # unnamed product cannot be checked against the OSP's approved-inputs list.
    RequiredField(
        key="commercial_name",
        label="product name",
        cfr_cite="§ 205.103(b)(2)",
    ),
    # § 205.103(b)(2): "materials used" is a quantity, not a checkbox — an inspector reconciling
    # purchase records against applications needs how much went on.
    RequiredField(
        key="volume",
        label="amount applied",
        cfr_cite="§ 205.103(b)(2)",
        present=lambda ev: _present(ev.volume_numeric) or _present(ev.volume),
    ),
    # § 205.103(b)(2): extent of the practice — how much ground the application covered.
    RequiredField(
        key="area",
        label="area treated",
        cfr_cite="§ 205.103(b)(2)",
        present=lambda ev: _present(ev.area_numeric) or _present(ev.area),
    ),
    # § 205.206(a): pest, weed and disease management must be through prevention/mechanical/
    # biological practices FIRST — a pesticide/fungicide/herbicide application with no recorded
    # target is unreviewable against that hierarchy. Does not apply to FE (fertilizer).
    RequiredField(
        key="target_pest_disease",
        label="target pest or disease",
        cfr_cite="§ 205.206(a)",
        applies_to=_PEST_TARGETING_TYPES,
    ),
    # § 205.103(b)(2): records must span "the time of purchase or acquisition, through
    # production". A certifier closes that trace by mass balance — quantity purchased against
    # quantity applied — and the packet's own words when it cannot: "Mass balance cannot be
    # reconciled. No purchase quantity is recorded on any chemical event."
    #
    # Measured 2026-08-11: 289 of 289 chemical events have no `quantity_purchased`, so the
    # input side has never reconciled for anybody, on any packet.
    #
    # CONDITIONAL on purchase evidence existing, and that restraint is the point. Not every
    # application is a purchase event — inputs get carried over from last season, produced on
    # farm, or supplied by a custom applicator, and demanding a purchase quantity there would
    # be Trazo inventing a requirement the regulation does not make. But once the operator has
    # recorded a supplier, a date, an invoice or a lot, they have asserted a purchase, and a
    # purchase with no quantity is precisely the half-record that breaks the trace.
    RequiredField(
        key="quantity_purchased",
        label="quantity purchased",
        cfr_cite="§ 205.103(b)(2)",
        applies_when=lambda ev: any(
            _present(getattr(ev, attr, None))
            for attr in ("supplier_name", "purchase_date", "purchase_invoice", "chemical_lot_number")
        ),
    ),
    _unresolved_basis_field("organic_approved"),
]


SOIL_EVENT_REQUIRED_FIELDS: list[RequiredField] = [_unresolved_basis_field("amendment_organic_approved")]


def _seed_search_documented(event, minimum: int = 1) -> bool:
    """At least `minimum` search rows that actually NAME a supplier.

    A row with a result but no supplier is not evidence — § 205.204(a)(1) turns on WHO was
    contacted. `supplier` is the pre-2026-08-15 key (see migration 0205).
    """
    rows = getattr(event, "seed_search_attempts", None) or []
    named = [r for r in rows if isinstance(r, dict) and str(r.get("supplier_name") or r.get("supplier") or "").strip()]
    return len(named) >= minimum


def _uses_non_organic_seed(event) -> bool:
    return getattr(event, "seed_certification_status", None) in NON_ORGANIC_SEED_STATUSES


def _named_a_seed_treatment(event) -> bool:
    """A treatment was actually applied — "None" in the box is an answer, not a treatment."""
    treatment = str(getattr(event, "seed_treatment", None) or "").strip()
    return bool(treatment) and treatment.lower() not in NO_TREATMENT_ANSWERS


#: Planting / Transplanting (7 CFR 205.204). Added 2026-08-15 — this registry was
#: chemical-only, so a planting record missing its § 205.204 evidence never appeared on the
#: readiness card the farm dashboard leads with, even though the certifier packet prints
#: exactly those columns.
PLANTING_EVENT_REQUIRED_FIELDS: list[RequiredField] = [
    # § 205.204(a): the whole standard turns on whether the seed was organic. Without this the
    # record cannot be classified at all, and osp_prefill's G3.0 resolver stays silent.
    RequiredField(
        key="seed_certification_status",
        label="seed organic status",
        cfr_cite="§ 205.204(a)",
    ),
    # § 205.2 defines "commercially available" by FORM, QUALITY or QUANTITY, and
    # § 205.204(a)(1) permits non-organic seed only when that test fails. The supplier rows say
    # WHO was contacted; this says the ground the exemption rests on.
    RequiredField(
        key="seed_nonavailability_reason",
        label="reason organic seed was unavailable",
        cfr_cite="§ 205.204(a)(1)",
        applies_when=_uses_non_organic_seed,
    ),
    # The certifier EXPECTATION of three contacts. Deliberately a readiness check and not a
    # save-blocking validator: § 205.204 sets no count, and USDA's Guide for Organic Crop
    # Producers is where "at least three" comes from. One documented supplier is enforced at
    # save time; the second and third belong here, framed as "what an inspector will ask for".
    RequiredField(
        key="seed_search_attempts",
        label="three documented supplier searches",
        cfr_cite="§ 205.204(a)(1)",
        applies_when=_uses_non_organic_seed,
        present=lambda ev: _seed_search_documented(ev, minimum=3),
    ),
    # USDA's Seed Records Part C pairs every named treatment with a "Documentation of Allowed
    # Status" column. A named treatment with no basis is unreviewable under § 205.204(a)(2) —
    # the same "named but unjustified" shape as the 2026-08-09 OMRI incident.
    RequiredField(
        key="seed_treatment_allowed_basis",
        label="why the seed treatment is allowed",
        cfr_cite="§ 205.204(a)(2)",
        applies_when=_named_a_seed_treatment,
    ),
    # § 205.103(b)(2): records must span "the time of purchase or acquisition". Conditional on
    # the operator having already asserted a purchase, exactly as the chemical
    # `quantity_purchased` check is — a farm-saved or nursery-gifted planting is not a purchase,
    # and demanding a supplier there would invent a requirement the regulation does not make.
    RequiredField(
        key="seed_supplier_name",
        label="seed supplier",
        cfr_cite="§ 205.103(b)(2)",
        applies_when=lambda ev: any(
            _present(getattr(ev, attr, None))
            for attr in ("seed_purchase_invoice", "seed_purchase_date", "seed_lot_number")
        ),
    ),
]


def _registry_for(event) -> list[RequiredField]:
    """Which required-field registry governs this event.

    Deliberately NOT `isinstance`. This module is called with real model instances from the
    viewset and with `SimpleNamespace` fixtures from its own tests, and an isinstance dispatch
    silently returned "no requirements" for every duck-typed caller — which reads as "this
    record is complete" and is the worst possible failure mode for a completeness check.

    Discriminates on Django's own model_name when there is one, and falls back to a field that
    only exists on the production model. Chemical stays the default so the v1 behaviour is
    bit-for-bit unchanged for every existing caller.
    """
    model_name = getattr(getattr(event, "_meta", None), "model_name", None)

    if model_name == "productionevent" or (model_name is None and hasattr(event, "seeds_source")):
        # Only the subtypes that actually put seed or planting stock in the ground owe § 205.204
        # evidence. Every other production subtype returns [] — silence, not a completeness claim.
        if getattr(event, "type", None) in SEED_SOURCED_SUBTYPES:
            return PLANTING_EVENT_REQUIRED_FIELDS
        return []

    if model_name == "chemicalevent" or (model_name is None and hasattr(event, "commercial_name")):
        return CHEMICAL_EVENT_REQUIRED_FIELDS

    # Soil amendments carry the same organic-basis choice (review of back #125: "Not yet
    # confirmed" on a soil amendment was never listed as owed). Only that one requirement; the
    # write-time nudge acts on a non-empty list only, so [] here claims nothing.
    if model_name == "soilmanagementevent" or (model_name is None and hasattr(event, "amendment_organic_approved")):
        return SOIL_EVENT_REQUIRED_FIELDS

    # Weather, soil, pest, business, general: no citable registry yet. Return nothing rather
    # than running the chemical checks against a model that has none of those columns — doing
    # so raised AttributeError inside the write-time nudge and 500'd the whole event save.
    return []


def has_registry(event) -> bool:
    """Is this event type CHECKED at all — as distinct from checked and found complete?

    `missing_required_fields()` returns `[]` for both, and the two mean opposite things to a
    caller: "every citable field is filled in" versus "nobody has written a citable registry for
    this event type yet". Only the first is a completeness claim.

    Callers used `isinstance(event, ChemicalEvent)` to tell them apart, which was accurate when
    the module was chemical-only and silently wrong from the day the § 205.204 planting registry
    landed — a complete planting looked identical to an unchecked weather log. Ask here instead,
    so the answer moves with the registries.
    """
    return bool(_registry_for(event))


def missing_required_fields(event) -> list[dict]:
    """Required fields absent on this event. Empty list = record is complete.

    Each item: {"key", "label", "cfr_cite"} — same shape PUR export's `missing` implies,
    minus the CA-only "which PUR box" framing.

    Covers ChemicalEvent and the SEED_SOURCED_SUBTYPES production subtypes. Any other event type
    returns [] — silence, not a claim of completeness.
    """
    return [
        {"key": rf.key, "label": rf.label, "cfr_cite": rf.cfr_cite}
        for rf in _registry_for(event)
        if rf.applies(event) and not rf.is_present(event)
    ]


def is_complete(event) -> bool:
    return not missing_required_fields(event)


def completeness_gap_keys(event) -> list[str]:
    """Machine keys of required fields absent on this ChemicalEvent, for API payloads.

    The write-time nudge (EventViewSet create/update) sends keys, not labels: the frontend owns
    the human wording via i18n, and a key survives copy changes. Same source of truth as
    `missing_required_fields` — this is a projection, not a second registry.
    """
    return [m["key"] for m in missing_required_fields(event)]


@dataclass(frozen=True)
class ChemicalRecordCompletenessSummary:
    total: int
    complete: int
    incomplete: int
    # {field_label: count_of_events_missing_it}, for a "what to fix first" ranking.
    missing_field_counts: dict
    # One representative incomplete event's missing labels, for a concrete example in UI copy.
    example_missing_labels: list

    #: Records with a gap OTHER than a basis recorded as "not yet confirmed" (an answer awaiting
    #: confirmation, never a missing field: recordkeeping review S4, F-08).
    incomplete_other: int = 0
    #: Records whose organic basis is recorded as not yet confirmed.
    basis_unconfirmed: int = 0

    @property
    def all_complete(self) -> bool:
        return self.incomplete == 0


def summarize_chemical_events(events: Iterable) -> ChemicalRecordCompletenessSummary:
    """Roll many ChemicalEvent rows into one summary for a snapshot row / dashboard card."""
    events = list(events)
    missing_field_counts: dict = {}
    example_missing_labels: list = []
    incomplete = 0

    incomplete_other = 0
    basis_unconfirmed = 0

    for event in events:
        missing = missing_required_fields(event)
        if not missing:
            continue
        incomplete += 1
        labels = [m["label"] for m in missing]
        if UNRESOLVED_BASIS_LABEL in labels:
            basis_unconfirmed += 1
        if any(label != UNRESOLVED_BASIS_LABEL for label in labels):
            incomplete_other += 1
        if not example_missing_labels:
            example_missing_labels = labels
        for m in missing:
            missing_field_counts[m["label"]] = missing_field_counts.get(m["label"], 0) + 1

    return ChemicalRecordCompletenessSummary(
        total=len(events),
        complete=len(events) - incomplete,
        incomplete=incomplete,
        missing_field_counts=missing_field_counts,
        example_missing_labels=example_missing_labels,
        incomplete_other=incomplete_other,
        basis_unconfirmed=basis_unconfirmed,
    )


@dataclass(frozen=True)
class NationalListCoverage:
    """How many of a season's inputs carry a 7 CFR 205.601/.602 citation.

    A miss is NOT a compliance judgement. It means Trazo could not map the farmer's wording to a
    listing, so the packet cites nothing and falls back to "self-reported". Surfacing the number
    is what turns that from an invisible gap into something a grower can fix, and it is the honest
    framing: coverage of OUR crosswalk, not a verdict on THEIR inputs.
    """

    total: int
    cited: int
    #: Distinct substance/product names Trazo could not map, most frequent first.
    unmatched_terms: list

    @property
    def uncited(self) -> int:
        return self.total - self.cited

    @property
    def all_cited(self) -> bool:
        return self.total > 0 and self.uncited == 0

    @property
    def percent(self) -> int:
        return round(self.cited / self.total * 100) if self.total else 0


def summarize_national_list_coverage(events: Iterable) -> NationalListCoverage:
    """Count ChemicalEvents that resolved to a National List entry.

    Reads the substance the classifier keys on — `extra_data["active_ingredient"]` first, then the
    brand — so the unmatched list names what the FARMER wrote, which is what they need to see to
    correct it. Reporting the canonical name would be circular: the ones with no canonical name
    are precisely the ones that failed.
    """
    total = 0
    cited = 0
    counts: dict = {}

    for event in events:
        total += 1
        from history.services.national_list_basis import confirmed_national_list_substance

        if confirmed_national_list_substance(event) is not None:
            cited += 1
            continue
        extra = getattr(event, "extra_data", None) or {}
        term = (extra.get("active_ingredient") if isinstance(extra, dict) else None) or getattr(
            event, "commercial_name", None
        )
        term = (term or "").strip()
        if term:
            counts[term] = counts.get(term, 0) + 1

    unmatched = [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return NationalListCoverage(total=total, cited=cited, unmatched_terms=unmatched)
