"""
Per-event record completeness for organic-inspection purposes.

Nothing else in the codebase answers "would THIS event survive an inspection?" at the level of an
individual record. `TransparencyCalculator` measures whether a production logged roughly as many
events as expected for its crop (`transparency_calculator.py:251,289` — an evenly-split count
target, not a field-level check); `AuditExportService.compliance_snapshot_rows()` runs 16
CFR-cited checks but none of them look inside a chemical event's own fields. Every field on
`ChemicalEvent` that a certifier actually reads — commercial name, rate, area, target pest — is
`blank=True, null=True` at the model level (`history/models.py:1070-1273`), so a farmer can save a
spray record with none of them and Trazo says nothing until the certifier PDF prints a blank cell.

This module is the missing layer, modelled directly on the one required-field registry that
already exists: `PUR_COLUMNS` / `REQUIRED_KEYS` / `_missing_required` in
`history/services/pur_export_service.py:32-64,343-370`. Same shape — a declarative list checked
against each event, producing a per-event list of what is missing — generalised from "one CA form"
to "what an organic inspector asks for," and applied at write time rather than only at CA PUR
export time.

Discipline: every entry MUST carry a real regulatory citation. A "required" field with no citation
is exactly the mistake this project already made once and undid — a Trazo-invented standard
presented as an external requirement (see the transparency-score demotion, 2026-08-04). If a field
matters but has no citation, it does not belong in this registry; add it to `PhotoVerificationGap`
or a roadmap suggestion instead, where "recommended" is an honest word.

Scope, deliberately narrow for v1: `ChemicalEvent` only, four fields. This is the highest-stakes
record type — spray records are what an inspector reaches for first — and the smallest citable set
that catches the actual failure mode (a record `python manage.py shell` can happily construct with
every field blank). Extend to other event types only alongside a specific citation, not by
resemblance to this one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

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

    def applies(self, event) -> bool:
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
]


def missing_required_fields(event) -> list[dict]:
    """Required fields absent on this ChemicalEvent. Empty list = record is complete.

    Each item: {"key", "label", "cfr_cite"} — same shape PUR export's `_missing_required` implies,
    minus the CA-only "which PUR box" framing.
    """
    return [
        {"key": rf.key, "label": rf.label, "cfr_cite": rf.cfr_cite}
        for rf in CHEMICAL_EVENT_REQUIRED_FIELDS
        if rf.applies(event) and not rf.is_present(event)
    ]


def is_complete(event) -> bool:
    return not missing_required_fields(event)


@dataclass(frozen=True)
class ChemicalRecordCompletenessSummary:
    total: int
    complete: int
    incomplete: int
    # {field_label: count_of_events_missing_it}, for a "what to fix first" ranking.
    missing_field_counts: dict
    # One representative incomplete event's missing labels, for a concrete example in UI copy.
    example_missing_labels: list

    @property
    def all_complete(self) -> bool:
        return self.incomplete == 0


def summarize_chemical_events(events: Iterable) -> ChemicalRecordCompletenessSummary:
    """Roll many ChemicalEvent rows into one summary for a snapshot row / dashboard card."""
    events = list(events)
    missing_field_counts: dict = {}
    example_missing_labels: list = []
    incomplete = 0

    for event in events:
        missing = missing_required_fields(event)
        if not missing:
            continue
        incomplete += 1
        if not example_missing_labels:
            example_missing_labels = [m["label"] for m in missing]
        for m in missing:
            missing_field_counts[m["label"]] = missing_field_counts.get(m["label"], 0) + 1

    return ChemicalRecordCompletenessSummary(
        total=len(events),
        complete=len(events) - incomplete,
        incomplete=incomplete,
        missing_field_counts=missing_field_counts,
        example_missing_labels=example_missing_labels,
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
        if getattr(event, "national_list_substance_id", None):
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
