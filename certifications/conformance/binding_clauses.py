"""Every BINDING clause of 7 CFR 205.103, 205.201, 205.202-205.206 and subpart E, mapped to code and proof.

WHY THIS FILE EXISTS
--------------------
The question "are we 100% aligned with the official documentation?" cannot be answered yes,
and the honest reason is in the regulation itself. § 205.103(b)(1) requires records "adapted
to the particular business that the certified operation is conducting" — the rule
deliberately refuses to enumerate a field list, because a 4,000-acre almond operation and a
two-acre market garden do not keep the same records. There is no official checklist to be
100% of. The corpus MANIFEST already states the same thing about the USDA crop forms:

    "100% alignment to these forms does not equal current compliance."

What CAN be done, and what this file does, is make the claim checkable instead of rhetorical:
enumerate every binding clause verbatim from the frozen corpus, say for each one what Trazo
does about it, name the code that does it, and name the test that proves the code does it.
"We satisfy § 205.201(a)(3)" stops being an opinion and becomes a query.

FOUR LAYERS, ONLY ONE OF WHICH IS LAW
-------------------------------------
    1. BINDING    7 CFR 205.103 + 205.201 (records, plan)   <- this file
                  7 CFR 205.202-205.206 (practice standards) <- this file
    2. TEMPLATE   Common OSP (AMS)      -> documentation/reference/usda-osp-template
    3. GUIDANCE   NOP Handbook          -> documentation/reference/usda-nop-handbook
                                           (6 crop sections, frozen 2026-08-15)
    4. PRACTICE   what CCOF/OTCO ask    -> certifier-validation-question-DRAFT.md

Only layer 1 is enforceable law. Layers 2-4 shape what a good product looks like; failing to
match them is a competitive problem, not a compliance one. Conflating the layers is how a
product ends up claiming "USDA-required" for a form whose own footer says
"Optional form, not mandated by regulation".

Layer 3 is frozen but stays OUT of the clause list on purpose: AMS states the Handbook "is
non-binding and any citation issued needs to reference the USDA organic regulations". A test
fails if a NOP 50xx number ever appears as a binding clause id. The rule that follows is
short: a product may COACH toward guidance; it must not BLOCK on guidance as though it were
law. Trazo learned that one concretely — the seed form used to refuse a save below three
documented suppliers, a count that appears in NOP 5029 and nowhere in the CFR.

WHAT THIS FILE IS NOT
---------------------
* Not a certification. Trazo is not an accredited certifying agent and this mapping is not
  reviewed by one. It is an engineering artifact.
* Not a claim that a clause is SATISFIED FOR A GIVEN FARM. A clause can be fully supported by
  the software and still be failed by an operation that does not use it.
* Not a consumer-facing statement. Nothing here may be rendered on a public surface.

DISPOSITIONS ARE DELIBERATELY NOT ALL "SATISFIED"
-------------------------------------------------
Some clauses cannot be satisfied by software at all, and saying so plainly is the point.
§ 205.103(c) requires records be made available to an inspector during business hours; no
amount of code does that for the operator. Marking such a clause SATISFIED would be the
failure mode this file exists to prevent.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


#: The frozen CFR text every `verbatim` below is quoted from. Cited by file, never by live
#: URL — the corpus discipline exists so this mapping stays reviewable after AMS republishes.
def _corpus_path(*parts: str) -> Path:
    """Resolve a frozen-corpus path in-repo first, then at the legacy root.

    🔴 2026-09-07 — this was `parents[3]` alone: the directory ABOVE this repository, which git
    does not track and Docker does not copy (`WORKDIR /app` + `COPY . .`). That is the exact
    path bug that made the certifier register invisible in production — the packet's "forms
    Trazo does not generate" section silently vanished from every image — and the register was
    moved in-repo to `parents[2]` to fix it. The CFR corpus did not move with it, and
    `test_binding_clause_coverage` reads this file in `setUpClass`, so the whole suite errors in
    a trazo-back-only checkout. It is also in no CI workflow, which is why nobody noticed.

    Checking both layouts makes the move a file operation rather than a code change, and makes
    the guard work the moment the corpus lands in-repo.
    """
    here = Path(__file__).resolve()
    for root in (here.parents[2], here.parents[3]):  # in-repo, then the legacy untracked root
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    return here.parents[2].joinpath(*parts)  # in-repo is where it SHOULD be; report that path


CORPUS_CFR_PATH = _corpus_path(
    "documentation", "reference", "usda-recordkeeping", "cfr", "title-7-part-205_2026-08-05.txt"
)


#: Frozen NOP Handbook sections (LAYER 3 — guidance, NOT law). AMS states on the Handbook
#: index page that it "is non-binding and any citation issued needs to reference the USDA
#: organic regulations", so nothing in this directory may be presented as a requirement. It is
#: here so certifier EXPECTATIONS can be cited by file instead of from memory.
CORPUS_HANDBOOK_DIR = _corpus_path("documentation", "reference", "usda-nop-handbook")


class Disposition(enum.Enum):
    """What Trazo can honestly say about a clause."""

    #: The product produces the record or output the clause calls for. Requires BOTH an
    #: implementation and a test, enforced by the coverage guard.
    SOFTWARE_SATISFIES = "software_satisfies"

    #: The product materially helps, but the clause is only met when the operator acts —
    #: answers the question, uploads the document, signs the plan.
    SOFTWARE_SUPPORTS = "software_supports"

    #: No software can satisfy this. Retention discipline, opening the filing cabinet for an
    #: inspector, agreeing the plan with a certifying agent. Recorded so the gap is explicit
    #: rather than looking like an oversight.
    OPERATOR_COMMITMENT = "operator_commitment"

    #: Genuinely does not apply to the operations Trazo serves. Requires a reason.
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class Clause:
    """One binding clause and everything asserted about it."""

    id: str
    cite: str
    verbatim: str
    disposition: Disposition
    rationale: str
    #: Repo-relative paths (optionally `path::symbol`) that implement this clause.
    implementation: Sequence[str] = field(default_factory=tuple)
    #: Repo-relative test modules that PROVE the implementation.
    tests: Sequence[str] = field(default_factory=tuple)
    #: Anything a reader would otherwise have to rediscover.
    note: str = ""


# ---------------------------------------------------------------------------------------
# 7 CFR 205.103 — Recordkeeping by certified operations
# As amended 88 FR 3621, Jan. 19, 2023 (Strengthening Organic Enforcement).
# ---------------------------------------------------------------------------------------

_S103 = (
    Clause(
        id="205.103(a)",
        cite="7 CFR 205.103(a)",
        verbatim=(
            "A certified operation must maintain records concerning the production, "
            "harvesting, and handling of agricultural products that are or that are intended "
            "to be sold, labeled, or represented as “100 percent organic,” "
            "“organic,” or “made with organic (specified ingredients or food "
            "group(s)).”"
        ),
        disposition=Disposition.SOFTWARE_SATISFIES,
        rationale=(
            "Production, harvest and handling are all first-class records: ProductionEvent "
            "covers planting through post-harvest, and the seven event types cover the "
            "activity surface. This is the clause the whole event model answers."
        ),
        implementation=("trazo-back/history/models.py::ProductionEvent", "trazo-back/history/models.py::CommonEvent"),
        tests=("trazo-back/history/tests/test_event_subtype_validation.py",),
    ),
    Clause(
        id="205.103(b)(1)",
        cite="7 CFR 205.103(b)(1)",
        verbatim="Be adapted to the particular business that the certified operation is conducting;",
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "This is the clause that makes '100% aligned' incoherent as a goal: the "
            "regulation refuses to prescribe a field list. Trazo adapts by subtype gating — "
            "a Planting record asks the § 205.204 questions and a Harvest record does "
            "not — so the form a grower sees is shaped by the activity they logged. The "
            "operator still decides whether that shape fits their business."
        ),
        implementation=(
            "trazo-app/src/config/events/productionEvent.ts",
            "trazo-app/src/config/events/registry.ts",
        ),
        tests=(
            "trazo-app/src/config/events/__tests__/formRenderConformance.test.tsx",
            "trazo-app/src/config/events/__tests__/formConformance.test.ts",
        ),
        note=(
            "The render-conformance sweep is the guard that a subtype's declared fields are "
            "actually reachable. It covers EM/PH/PL/HA; IR/PR/MO and the rest are NOT swept, "
            "which is a stated limitation, not a clean bill of health."
        ),
    ),
    Clause(
        id="205.103(b)(2)",
        cite="7 CFR 205.103(b)(2)",
        verbatim=(
            "Fully disclose all activities and transactions of the certified operation, in "
            "sufficient detail as to be readily understood and audited; records must span the "
            "time of purchase or acquisition, through production, to sale or transport and be "
            "traceable back to the last certified operation;"
        ),
        disposition=Disposition.SOFTWARE_SATISFIES,
        rationale=(
            "The three spans are separately implemented: PURCHASE by the seed/input purchase "
            "columns, PRODUCTION by the event timeline, SALE by SalesRecord. The trace that "
            "joins them is the harvest lot code plus the sale-to-harvest link, so a buyer "
            "resolves to a pick, a block and a date. Mass balance reconciles the two ends "
            "from the harvest RECORDS rather than a typed season total."
        ),
        implementation=(
            "trazo-back/history/models.py::ProductionEvent.harvest_lot_code",
            "trazo-back/history/models.py::ProductionEvent.suggest_harvest_lot_code",
            "trazo-back/history/models.py::SalesRecord",
            "trazo-back/history/services/audit_export_service.py::AuditExportService._resolve_harvest_total",
        ),
        tests=(
            "trazo-back/history/tests/test_harvest_lot_identity.py",
            "trazo-back/history/tests/test_sales_and_lot_tag.py",
            "trazo-back/history/tests/test_sales_disclosure_precedence.py",
        ),
        note=(
            "'Traceable back to the last certified operation' is only as good as the supplier "
            "identity the grower records; Trazo cannot verify a supplier's certificate."
        ),
    ),
    Clause(
        id="205.103(b)(3)",
        cite="7 CFR 205.103(b)(3)",
        verbatim=(
            "Include audit trail documentation for agricultural products handled or produced "
            "by the certified operation and identify agricultural products on these records as "
            "“100% organic,” “organic,” or “made with organic "
            "(specified ingredients or food group(s)),” or similar terms, as applicable;"
        ),
        disposition=Disposition.SOFTWARE_SATISFIES,
        rationale=(
            "The labeling CATEGORY is a stored field on the sale, not an inference: the "
            "operator selects it and the packet prints it. A boolean 'organic on invoice' "
            "cannot express which of the three categories applies, which is what this clause "
            "actually asks for."
        ),
        implementation=(
            "trazo-back/history/models.py::SalesRecord.organic_label_category",
            "trazo-back/history/services/audit_export_service.py",
        ),
        tests=(
            "trazo-back/history/tests/test_sales_and_lot_tag.py",
            "trazo-back/history/tests/test_transport_export.py",
        ),
    ),
    Clause(
        id="205.103(b)(4)",
        cite="7 CFR 205.103(b)(4)",
        verbatim="Be maintained for not less than 5 years beyond their creation; and",
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Trazo computes a retention floor and REFUSES deletion inside it, so the product "
            "cannot be the reason a record disappears early. It is SUPPORTS and not SATISFIES "
            "because retention is a property of the operation's whole recordkeeping system, "
            "including paper and other software, none of which Trazo controls."
        ),
        implementation=(
            "trazo-back/history/models.py::compute_retention_until",
            "trazo-back/history/models.py::Production.retention_until",
            # What the deletion guards and printed dates read: the stored date, or a later state
            # floor computed now.
            "trazo-back/history/retention.py::effective_retention_until",
        ),
        tests=("trazo-back/history/tests/test_record_retention.py",),
    ),
    Clause(
        id="205.103(b)(5)",
        cite="7 CFR 205.103(b)(5)",
        verbatim="Be sufficient to demonstrate compliance with the Act and the regulations in this part.",
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "A catch-all sufficiency test that no product can self-certify against — only a "
            "certifying agent decides whether a record set is sufficient. Trazo's contribution "
            "is the readiness surface: it names what is MISSING against cited requirements "
            "rather than asserting the record set is complete."
        ),
        implementation=("trazo-back/history/services/record_completeness.py",),
        tests=("trazo-back/history/tests/test_record_completeness.py",),
        note=(
            "Omitted from most summaries of this section, including the one that prompted this "
            "mapping. Enumerated here because the coverage guard reads the clause list out of "
            "the frozen CFR and would fail if it were missing."
        ),
    ),
    Clause(
        id="205.103(c)",
        cite="7 CFR 205.103(c)",
        verbatim=(
            "The certified operation must make such records available for inspection and "
            "copying during normal business hours by authorized representatives of the "
            "Secretary, the applicable State program's governing State official, and the "
            "certifying agent."
        ),
        disposition=Disposition.OPERATOR_COMMITMENT,
        rationale=(
            "No software makes records available to an inspector; a person does, at a time and "
            "place. What Trazo provides is the artifact that makes doing so cheap: a packet "
            "the operator can hand over or print. Marking this SATISFIED would be exactly the "
            "overclaim this file exists to prevent."
        ),
        implementation=("trazo-back/history/services/audit_export_service.py::AuditExportService",),
        tests=("trazo-back/history/tests/test_operation_audit_export.py",),
    ),
)


# ---------------------------------------------------------------------------------------
# 7 CFR 205.201 — Organic production and handling system plan
# As amended 88 FR 3622, Jan. 19, 2023 (SOE: supplier verification + fraud prevention).
# ---------------------------------------------------------------------------------------

_S201 = (
    Clause(
        id="205.201(a)(1)",
        cite="7 CFR 205.201(a)(1)",
        verbatim=(
            "A description of practices and procedures to be performed and maintained, "
            "including the frequency with which they will be performed;"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "The OSP modules ask the practice-and-frequency questions and compile the "
            "operator's own answers. Trazo does not author the description; § 205.201(a) "
            "makes the PRODUCER its author."
        ),
        implementation=(
            "trazo-back/certifications/osp_modules/g4_0_rotation_soil.py",
            "trazo-back/certifications/osp_modules/g5_0_pest.py",
            "trazo-back/certifications/osp_modules/g6_0_production.py",
        ),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
    ),
    Clause(
        id="205.201(a)(2)",
        cite="7 CFR 205.201(a)(2)",
        verbatim=(
            "A list of each substance to be used as a production or handling input, indicating "
            "its composition, source, location(s) where it will be used, and documentation of "
            "commercial availability, as applicable;"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "TWO of the clause's four named attributes are captured; two are not. Held: the "
            "substance list itself, each row's SOURCE via its catalogue listing or certifier "
            "letter, and 'documentation of commercial availability' — the § 205.204(a)(1) "
            "seed search, stored per planting so it is attached to the lot it justifies. "
            "NOT held: COMPOSITION (no field on `PlanMaterialEntry`, and no active-ingredient "
            "capture anywhere) and LOCATION(S) WHERE IT WILL BE USED (the plan's materials list "
            "has no parcel link)."
        ),
        note=(
            "🔴 2026-09-07 — downgraded from SOFTWARE_SATISFIES. The old rationale "
            'defended the claim with "every input application records … where it was '
            'applied", which is the RECORD — a past-tense `ChemicalEvent` — not the '
            'PLAN\'s prospective "location(s) where it WILL be used". Answering a clause with '
            'the nearest adjacent fact is the same "covered for the wrong reason" shape the '
            "certifier register was corrected for, arriving here in the conformance matrix. "
            "⚠️ `test_binding_clause_coverage` checks that a verbatim matches the corpus "
            "and that the named files exist — it does NOT check that the attributes INSIDE a "
            "verbatim are implemented, so nothing else would have caught this. Closing it means "
            "a composition field and a per-material parcel link."
        ),
        implementation=(
            "trazo-back/history/models.py::ChemicalEvent",
            "trazo-back/certifications/osp_modules/materials_application.py",
            "trazo-back/history/models.py::ProductionEvent.seed_search_attempts",
        ),
        tests=(
            "trazo-back/history/tests/test_packet_fields_have_writers.py",
            "trazo-back/certifications/tests/test_common_osp_records.py",
        ),
    ),
    Clause(
        id="205.201(a)(3)",
        cite="7 CFR 205.201(a)(3)",
        verbatim=(
            "A description of the monitoring practices and procedures to be performed and "
            "maintained, including the frequency with which they will be performed, to verify "
            "that the plan is effectively implemented. This must include a description of the "
            "monitoring practices and procedures to verify suppliers in the supply chain and "
            "organic status of agricultural products received, and to prevent organic fraud, "
            "as appropriate to the certified operation's activities, scope, and complexity;"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "The SOE sentence is the second half of this clause and is the newest binding "
            "requirement in the whole mapping. Trazo carries a fraud-prevention module and a "
            "supplier/sales SOE module; both compile operator answers rather than asserting "
            "the monitoring happened."
        ),
        implementation=(
            "trazo-back/certifications/osp_modules/g2_0_fraud_prevention.py",
            "trazo-back/certifications/osp_modules/stubs.py::G6_5_SALES_SOE",
        ),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
        note=(
            "Added by SOE at 88 FR 3622 (Jan. 19, 2023). No 2011-era USDA crop form has a "
            "column for it, so form-parity alone can never demonstrate this clause."
        ),
    ),
    Clause(
        id="205.201(a)(4)",
        cite="7 CFR 205.201(a)(4)",
        verbatim=(
            "A description of the recordkeeping system implemented to comply with the "
            "requirements established in § 205.103;"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Module G8.0 asks the operator to describe their recordkeeping system. Notably "
            "this clause is self-referential for a recordkeeping product: Trazo IS part of the "
            "system being described, but the description is still the operator's to make."
        ),
        implementation=("trazo-back/certifications/osp_modules/g8_0_record_keeping.py",),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
    ),
    Clause(
        id="205.201(a)(5)",
        cite="7 CFR 205.201(a)(5)",
        verbatim=(
            "A description of the management practices and physical barriers established to "
            "prevent commingling of organic and nonorganic products on a split operation and to "
            "prevent contact of organic production and handling operations and products with "
            "prohibited substances; and"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Commingling barriers are a dedicated section of the production module, and the "
            "event layer carries the operational half: shared-equipment flags, the cleaning "
            "link that precedes a shared pass, and buffer-zone disposition on harvest."
        ),
        implementation=(
            "trazo-back/certifications/osp_modules/g6_0_production.py",
            "trazo-back/history/models.py::ProductionEvent.shared_with_conventional",
            "trazo-back/history/models.py::ProductionEvent.equipment_cleaning_event",
        ),
        tests=(
            "trazo-back/history/tests/test_transport_export.py",
            "trazo-back/certifications/tests/test_osp_module_compiler.py",
        ),
    ),
    Clause(
        id="205.201(a)(6)",
        cite="7 CFR 205.201(a)(6)",
        verbatim=(
            "Additional information deemed necessary by the certifying agent to evaluate "
            "compliance with the regulations."
        ),
        disposition=Disposition.OPERATOR_COMMITMENT,
        rationale=(
            "Unbounded by design and resolved per certifier, so no product can close it. Trazo "
            "provides free-text and attachment paths so an agent's extra request has somewhere "
            "to go, but what is 'necessary' is the agent's call."
        ),
        implementation=("trazo-back/certifications/osp_modules/schema.py",),
        tests=(),
    ),
    Clause(
        id="205.201(b)",
        cite="7 CFR 205.201(b)",
        verbatim=(
            "A producer may substitute a plan prepared to meet the requirements of another "
            "Federal, State, or local government regulatory program for the organic system "
            "plan: Provided, That, the submitted plan meets all the requirements of this "
            "subpart."
        ),
        disposition=Disposition.OUT_OF_SCOPE,
        rationale=(
            "A permission granted to the producer, not a requirement placed on anyone. There is "
            "nothing for the software to do; a producer exercising it simply does not use "
            "Trazo's OSP generation."
        ),
        implementation=(),
        tests=(),
    ),
    Clause(
        id="205.201(c)",
        cite="7 CFR 205.201(c)",
        verbatim=(
            "In addition to paragraph (a) of this section, a producer group operation's organic "
            "system plan must describe its internal control system."
        ),
        disposition=Disposition.OUT_OF_SCOPE,
        rationale=(
            "Applies only to PRODUCER GROUP operations (grower groups under one certificate). "
            "Trazo's ICP is single-operation California wholesale orchards, which are not "
            "producer groups. The ten (c)(1)-(10) sub-clauses inherit this disposition."
        ),
        implementation=("trazo-back/history/services/audit_export_service.py",),
        tests=(),
        note=(
            "The packet reports producer-group applicability as an explicit THREE-state "
            "(applicable / not applicable / not recorded) rather than defaulting to 'no', "
            "because silently answering a question the operator never saw is how a packet "
            "asserts something untrue. If a producer group ever becomes an ICP, this clause "
            "and its ten sub-clauses need real implementations, not a re-labelled disposition."
        ),
    ),
)


# ---------------------------------------------------------------------------------------
# 7 CFR 205.202 - 205.206 — the CROP PRODUCTION practice standards.
#
# § 205.103 and § 205.201 govern whether a record EXISTS and TRACES. These five sections
# govern whether the practice the record describes is ALLOWED. They are the clauses a packet
# gets rejected on, and they are where Trazo's event fields either carry a real regulatory
# threshold (90/120-day manure intervals, compost C:N and temperature) or quietly do not.
# ---------------------------------------------------------------------------------------

_PRODUCTION_STANDARDS = (
    Clause(
        id="205.202(a)",
        cite="7 CFR 205.202(a)",
        verbatim="Have been managed in accordance with the provisions of §§ 205.203 through 205.206;",
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "A pointer clause: it makes the four practice standards below a land-eligibility "
            "condition rather than free-standing advice. Trazo's contribution is that the "
            "events which evidence 205.203-205.206 are attached to the PARCEL, so the "
            "'this field was managed accordingly' question has per-field evidence behind it."
        ),
        implementation=("trazo-back/product/models.py::Parcel", "trazo-back/history/models.py::CommonEvent"),
        tests=("trazo-back/history/tests/test_record_completeness.py",),
    ),
    Clause(
        id="205.202(b)",
        cite="7 CFR 205.202(b)",
        verbatim=(
            "Have had no prohibited substances, as listed in § 205.105, applied to it for a "
            "period of 3 years immediately preceding harvest of the crop; and"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "The parcel stores the LAST prohibited substance and the date it was applied, "
            "which is exactly the pair the three-year clock is computed from. Trazo cannot "
            "verify the answer — it is the operator's declaration about land history, often "
            "predating their ownership — so this is SUPPORTS, not SATISFIES."
        ),
        implementation=(
            # ParcelCropHistory, NOT Parcel — and the distinction matters. The clause is per
            # FIELD per CROP ("3 years immediately preceding harvest of the crop"), so the
            # clock belongs to a crop-history record rather than to a standing parcel
            # attribute. An earlier revision of this file named Parcel and was wrong.
            "trazo-back/product/models.py::ParcelCropHistory.last_prohibited_substance",
            "trazo-back/product/models.py::ParcelCropHistory.date_last_prohibited",
        ),
        tests=("trazo-back/history/tests/test_export_block_osp.py",),
    ),
    Clause(
        id="205.202(c)",
        cite="7 CFR 205.202(c)",
        verbatim=(
            "Have distinct, defined boundaries and buffer zones such as runoff diversions to "
            "prevent the unintended application of a prohibited substance to the crop or "
            "contact with a prohibited substance applied to adjoining land that is not under "
            "organic management."
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Boundaries come from the parcel's geospatial definition and block ids; the buffer "
            "half is carried operationally by harvest buffer disposition — whether buffer-row "
            "product entered organic commerce, which is the question a buffer zone exists to "
            "answer and the one an inspector actually asks."
        ),
        implementation=(
            "trazo-back/history/models.py::ProductionEvent.buffer_disposition",
            "trazo-back/certifications/osp_modules/parcel_application.py",
        ),
        tests=("trazo-app/src/config/events/__tests__/bufferEntersCommerce.test.ts",),
    ),
    Clause(
        id="205.203(a)",
        cite="7 CFR 205.203(a)",
        verbatim=(
            "The producer must select and implement tillage and cultivation practices that "
            "maintain or improve the physical, chemical, and biological condition of soil and "
            "minimize soil erosion."
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Tillage passes are recorded events with a working depth; the erosion half is an "
            "OSP narrative question rather than an event field, because erosion control is a "
            "standing practice description, not a dated occurrence."
        ),
        implementation=(
            "trazo-back/certifications/osp_modules/g4_0_rotation_soil.py",
            "trazo-back/history/models.py::SoilManagementEvent",
        ),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
    ),
    Clause(
        id="205.203(b)",
        cite="7 CFR 205.203(b)",
        verbatim=(
            "The producer must manage crop nutrients and soil fertility through rotations, "
            "cover crops, and the application of plant and animal materials."
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "All three named mechanisms are recordable — rotation and cover crops in the soil "
            "module and as events, material applications as amendment events with rates. "
            "Whether the mix constitutes adequate fertility management is a certifier judgement."
        ),
        implementation=(
            "trazo-back/certifications/osp_modules/g4_0_rotation_soil.py",
            "trazo-back/history/models.py::SoilManagementEvent",
        ),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
    ),
    Clause(
        id="205.203(c)",
        cite="7 CFR 205.203(c)",
        verbatim=(
            "The producer must manage plant and animal materials to maintain or improve soil "
            "organic matter content in a manner that does not contribute to contamination of "
            "crops, soil, or water by plant nutrients, pathogenic organisms, heavy metals, or "
            "residues of prohibited substances."
        ),
        disposition=Disposition.SOFTWARE_SATISFIES,
        rationale=(
            "This is the clause whose sub-paragraphs carry hard NUMBERS, and Trazo checks "
            "them rather than merely storing them: the raw-manure interval recorded on a "
            "manure record is checked against the crop's 90/120-day minimum when it is saved, "
            "and every recorded harvest is compared with the raw manure applied on its parcel, "
            "in the save response and the audit export. A harvest inside the interval is "
            "reported, never refused: it happened, and the record must say so. Compost records "
            "carry C:N ratio, temperature log, method and turn count. A threshold that is "
            "stored but never checked is a field, not a control."
        ),
        implementation=(
            # The interval is measured to harvest, so the check reads the recorded harvests against
            # the soil records' manure dates. Until 2026-11-15 this named a model clean() method no API
            # save calls (overall review OV-RK-C02).
            "trazo-back/history/services/manure_check.py::parcel_conflicts",
            "trazo-back/history/services/manure_interval.py::below_minimum",
            "trazo-back/history/models.py::SoilManagementEvent.manure_harvest_interval",
            "trazo-back/history/models.py::SoilManagementEvent.compost_initial_cn_ratio",
            "trazo-back/history/models.py::SoilManagementEvent.compost_method",
            "trazo-back/history/models.py::SoilManagementEvent.compost_temperature_log",
        ),
        tests=(
            "trazo-app/src/config/events/__tests__/grazingManureInterval.test.ts",
            "trazo-back/certifications/tests/test_osp_module_compiler.py",
            "trazo-back/history/tests/test_manure_harvest_check.py",
        ),
        note=(
            "The 90/120-day distinction turns on whether the edible portion contacts the soil "
            "— an orchard crop and a leaf crop get different answers from the same manure "
            "application, so the interval cannot be a single constant."
        ),
    ),
    Clause(
        id="205.203(d)",
        cite="7 CFR 205.203(d)",
        verbatim=(
            "A producer may manage crop nutrients and soil fertility to maintain or improve "
            "soil organic matter content in a manner that does not contribute to contamination "
            "of crops, soil, or water by plant nutrients, pathogenic organisms, heavy metals, "
            "or residues of prohibited substances by applying:"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "A permission list (National List substances, mined substances, ash, chemically "
            "altered materials). Every input application records an organic-approval basis, "
            "and the National List alias crosswalk maps farmer wording onto § 205.601 entries "
            "— deliberately by curated alias, never fuzzy matching."
        ),
        implementation=(
            "trazo-back/certifications/services/national_list_aliases.py",
            "trazo-back/common/field_registry.py::ORGANIC_APPROVED",
        ),
        tests=("trazo-back/certifications/tests/test_national_list_aliases.py",),
    ),
    Clause(
        id="205.203(e)",
        cite="7 CFR 205.203(e)",
        verbatim="The producer must not use:",
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Three flat prohibitions: (e)(1) non-listed synthetics, (e)(2) sewage sludge, and "
            "(e)(3) burning crop residues except to suppress disease or stimulate germination. "
            "The National List alias data carries the prohibited entries so a farmer's input "
            "can be checked against them — that is the (e)(1) leg. The (e)(3) leg is asked "
            "directly in G5.0: whether residue is burned, which residues, and which of the two "
            "statutory reasons applies, with an explicit 'another reason' branch that a "
            "certifier can act on. Trazo does not block a record describing a prohibited "
            "practice — it is a recordkeeping system, and refusing to record what happened "
            "would destroy the audit trail rather than protect it."
        ),
        implementation=(
            "trazo-back/certifications/services/national_list_aliases.py",
            "trazo-back/certifications/management/commands/seed_national_list.py",
            "trazo-back/certifications/osp_modules/g5_0_pest.py",
        ),
        tests=(
            "trazo-back/certifications/tests/test_national_list_aliases.py",
            "trazo-back/certifications/tests/test_osp_modules.py",
        ),
        note=(
            "Deliberate design position: the product records reality and flags it. A system "
            "that silently refuses to store a non-compliant event teaches operators to keep "
            "the real record somewhere else. "
            "2026-08-17: this clause previously named ONLY the National List crosswalk as its "
            "implementation, which covers (e)(1) and touches neither (e)(2) nor (e)(3). The "
            "rationale sentence mentioned burning, so the mapping read as covered while no "
            "field, question or export existed for it. A clause map is only as honest as its "
            "weakest `implementation` tuple. (e)(2) sewage sludge has no question of its own "
            "and does not need one: it is a seeded prohibited entry — `seed_national_list.py` "
            "row ('g', 'amendment', 'Sewage sludge (biosolids)') — so naming it as an input "
            "resolves against the prohibited list on the same path as (e)(1). "
            "2026-08-18: that row was seeded as subsection ('f') and is now ('g'). Sewage "
            "sludge is § 205.105(g); (f) is ionizing radiation. Three § 205.105 rows were "
            "each a letter early, and this note cited one of them as proof of conformance — "
            "evidence named in a clause map is only as good as the row it points at."
        ),
    ),
    Clause(
        id="205.204(a)",
        cite="7 CFR 205.204(a)",
        verbatim=(
            "The producer must use organically grown seeds, annual seedlings, and planting " "stock: Except, That,"
        ),
        disposition=Disposition.SOFTWARE_SATISFIES,
        rationale=(
            "The seed record carries certification status, the commercial-availability search "
            "with named suppliers and dates, the statutory non-availability ground, the "
            "treatment and its allowed basis, and — since 2026-08-15 — excluded-methods "
            "verification and the perennial organic-management start date. The exemptions in "
            "(a)(1)-(a)(5) are the reason this section exists and four of the five are "
            "individually recordable."
        ),
        implementation=(
            "trazo-back/history/models.py::ProductionEvent.seed_search_attempts",
            "trazo-back/history/models.py::ProductionEvent.seed_nonavailability_reason",
            "trazo-back/history/models.py::ProductionEvent.seed_treatment_allowed_basis",
        ),
        tests=(
            "trazo-back/history/tests/test_planting_record_completeness.py",
            "trazo-back/history/tests/test_harvest_lot_identity.py",
        ),
    ),
    Clause(
        id="205.204(a)(3)",
        cite="7 CFR 205.204(a)(3)",
        verbatim=(
            "Nonorganically produced annual seedlings may be used to produce an organic crop "
            "when a temporary variance has been granted in accordance with § 205.290(a)(2);"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "🔴 GAP, recorded rather than papered over. A § 205.290 temporary variance has NO "
            "field anywhere in the codebase — grep finds no reference to 205.290 or to a "
            "variance grant. A grower operating under one can only record it as free text, so "
            "the packet cannot show the variance that makes their seedlings allowable. Low "
            "frequency (variances are granted for disasters and regional emergencies) and "
            "irrelevant to a perennial orchard ICP, which is why it is not urgent — but it is "
            "a real absence, not a covered case."
        ),
        implementation=(),
        tests=(),
        note=(
            "Fixing it is small: a variance reference plus the granting agent and date on the "
            "planting record, printed in the seed section. Left open deliberately so the "
            "matrix reports a gap it actually has."
        ),
    ),
    Clause(
        id="205.204(a)(4)",
        cite="7 CFR 205.204(a)(4)",
        verbatim=(
            "Nonorganically produced planting stock to be used to produce a perennial crop may "
            "be sold, labeled, or represented as organically produced only after the planting "
            "stock has been maintained under a system of organic management for a period of no "
            "less than 1 year; and"
        ),
        disposition=Disposition.SOFTWARE_SATISFIES,
        rationale=(
            "The single most ICP-relevant clause in this section — a California orchard "
            "replanting nursery stock lives or dies on it. `stock_organic_management_start` "
            "records the date and the packet COMPUTES the elapsed year, printing a [REVIEW] "
            "line when the stock was under organic management for less than 12 months at "
            "planting. A stored date that nobody does arithmetic on would not answer the rule."
        ),
        implementation=(
            "trazo-back/history/models.py::ProductionEvent.stock_organic_management_start",
            "trazo-back/history/services/audit_export_service.py",
        ),
        tests=("trazo-back/history/tests/test_harvest_lot_identity.py",),
    ),
    Clause(
        id="205.205",
        cite="7 CFR 205.205",
        verbatim=(
            "The producer must implement a crop rotation including but not limited to sod, "
            "cover crops, green manure crops, and catch crops that provide the following "
            "functions that are applicable to the operation:"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Note the qualifier 'applicable to the operation'. A mature perennial orchard does "
            "not rotate its trees, and the four functions are answered there by cover cropping "
            "and orchard-floor management rather than by a rotation sequence. The OSP module "
            "asks the functions; the events evidence the practices."
        ),
        implementation=("trazo-back/certifications/osp_modules/g4_0_rotation_soil.py",),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
        note=(
            "Getting this wrong in the other direction is a real product risk: forcing an "
            "orchard to answer annual-rotation questions is how a recordkeeping tool reads as "
            "built for row crops."
        ),
    ),
    Clause(
        id="205.204(a)(1)",
        cite="7 CFR 205.204(a)(1)",
        verbatim=(
            "Nonorganically produced, untreated seeds and planting stock may be used to produce "
            "an organic crop when an equivalent organically produced variety is not commercially "
            "available: Except, That, organically produced seed must be used for the production "
            "of edible sprouts;"
        ),
        disposition=Disposition.SOFTWARE_SATISFIES,
        rationale=(
            "The commercial-availability search is stored per planting as structured rows — "
            "supplier, date contacted, result, notes — plus the statutory non-availability "
            "ground (form / quality / quantity per § 205.2). Keeping it on the EVENT rather "
            "than at farm level is the deliberate difference from Quick Organics: the evidence "
            "is attached to the lot it justifies, which is what § 205.103(b)(2) asks for."
        ),
        implementation=(
            "trazo-back/history/models.py::ProductionEvent.seed_search_attempts",
            "trazo-back/history/models.py::ProductionEvent.seed_nonavailability_reason",
        ),
        tests=("trazo-back/history/tests/test_planting_record_completeness.py",),
        note=(
            "§ 205.204 sets NO numeric supplier count. The 'three or more sources' figure comes "
            "from NOP 5029 § 4.2 b.1, now frozen at documentation/reference/usda-nop-handbook — "
            "so it is real and officially published, and it is GUIDANCE, which AMS states is "
            "non-binding. Both halves matter: coaching toward three is well-founded, and the "
            "old hard save-block below three presented guidance as law. The save now blocks at "
            "ZERO documented suppliers (a genuine § 205.204(a)(1) gap) and coaches above that. "
            "NOP 5029 § 4.4.3 is why the expectation has teeth: certifying agents verify it."
        ),
    ),
    Clause(
        id="205.204(a)(2)",
        cite="7 CFR 205.204(a)(2)",
        verbatim=(
            "Nonorganically produced seeds and planting stock that have been treated with a "
            "substance included on the National List of synthetic substances allowed for use in "
            "organic crop production may be used to produce an organic crop when an equivalent "
            "organically produced or untreated variety is not commercially available;"
        ),
        disposition=Disposition.SOFTWARE_SATISFIES,
        rationale=(
            "The seed treatment and the BASIS on which it is allowed are two separate stored "
            "fields, mirroring USDA's Seed Records Part C, which pairs every named treatment "
            "with a documentation-of-allowed-status column. A named treatment with no basis is "
            "unreviewable, so the packet prints the pair or says the basis is missing."
        ),
        implementation=(
            "trazo-back/history/models.py::ProductionEvent.seed_treatment_allowed_basis",
            "trazo-back/common/field_registry.py::NO_TREATMENT_ANSWERS",
        ),
        tests=("trazo-back/history/tests/test_planting_record_completeness.py",),
        note=(
            "Recording 'None' as the treatment used to generate a FALSE § 205.204(a)(2) finding "
            "against a grower who correctly reported that nothing was applied; the basis is now "
            "auto-set to `untreated` for the answers that mean nothing was applied."
        ),
    ),
    Clause(
        id="205.204(a)(5)",
        cite="7 CFR 205.204(a)(5)",
        verbatim=(
            "Seeds, annual seedlings, and planting stock treated with prohibited substances may "
            "be used to produce an organic crop when the application of the materials is a "
            "requirement of Federal or State phytosanitary regulations."
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "A narrow exemption for mandated phytosanitary treatment. The treatment-basis enum "
            "carries a value for it, so the record can state the ground; Trazo does not hold "
            "the phytosanitary orders themselves, so it cannot confirm the requirement applied."
        ),
        implementation=("trazo-back/common/field_registry.py",),
        tests=("trazo-back/history/tests/test_planting_record_completeness.py",),
    ),
    Clause(
        id="205.206(b)",
        cite="7 CFR 205.206(b)",
        verbatim=(
            "Pest problems may be controlled through mechanical or physical methods including " "but not limited to:"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Second rung of the hierarchy — beneficials, habitat, traps and lures. Pest events "
            "record the control actually used, so a packet can show the non-material step was "
            "tried before a substance was reached for, which is what (e) conditions on."
        ),
        implementation=(
            "trazo-back/history/models.py::PestManagementEvent",
            "trazo-back/certifications/osp_modules/g5_0_pest.py",
        ),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
    ),
    Clause(
        id="205.206(c)",
        cite="7 CFR 205.206(c)",
        verbatim="Weed problems may be controlled through:",
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Mulching, mowing, grazing, hand weeding, flame/heat, and removable synthetic "
            "mulch. Directly relevant to the orchard ICP: mowing and flame weeding are the "
            "orchard-floor operations, and both are recordable subtypes."
        ),
        implementation=(
            "trazo-back/history/models.py::ProductionEvent",
            "trazo-back/certifications/osp_modules/g5_0_pest.py",
        ),
        tests=("trazo-app/src/config/events/__tests__/formRenderConformance.test.tsx",),
        note=(
            "(c)(6) carries a condition most lists drop: synthetic mulch is allowed PROVIDED "
            "it is removed from the field at the end of the season. That is a removal event, "
            "not a property of the mulch — and Trazo has no structured field for the removal."
        ),
    ),
    Clause(
        id="205.206(d)",
        cite="7 CFR 205.206(d)",
        verbatim="Disease problems may be controlled through:",
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Suppressive management practices, or nonsynthetic biological/botanical/mineral "
            "inputs. Recorded as pest-management events and as input applications with an "
            "organic-approval basis."
        ),
        implementation=(
            "trazo-back/history/models.py::PestManagementEvent",
            "trazo-back/certifications/osp_modules/g5_0_pest.py",
        ),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
    ),
    Clause(
        id="205.206(a)",
        cite="7 CFR 205.206(a)",
        verbatim=(
            "The producer must use management practices to prevent crop pests, weeds, and "
            "diseases including but not limited to:"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "The top of the § 205.206 hierarchy: prevention through rotation, sanitation and "
            "cultural practice. The pest module is built around the hierarchy explicitly, and "
            "pest events record the cultural practice used."
        ),
        implementation=("trazo-back/certifications/osp_modules/g5_0_pest.py",),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
    ),
    Clause(
        id="205.206(e)",
        cite="7 CFR 205.206(e)",
        verbatim=(
            "When the practices provided for in paragraphs (a) through (d) of this section are "
            "insufficient to prevent or control crop pests, weeds, and diseases, a biological "
            "or botanical substance or a substance included on the National List of synthetic "
            "substances allowed for use in organic crop production may be applied to prevent, "
            "suppress, or control pests, weeds, or diseases: Provided, That, the conditions "
            "for using the substance are documented in the organic system plan."
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "The hinge clause of the whole section: a listed substance is allowable ONLY if "
            "the conditions for its use are documented in the OSP. So the input application "
            "and the OSP entry are two halves of one requirement — recording the spray without "
            "the OSP condition does not make the spray compliant."
        ),
        implementation=(
            "trazo-back/certifications/osp_modules/g5_0_pest.py",
            "trazo-back/certifications/services/drift_detector.py",
        ),
        tests=("trazo-back/certifications/tests/test_osp_module_compiler.py",),
        note=(
            "The OSP-versus-events drift detector exists for exactly this shape: a substance "
            "applied in the field that the plan never authorised."
        ),
    ),
    Clause(
        id="205.206(f)",
        cite="7 CFR 205.206(f)",
        verbatim=(
            "The producer must not use lumber treated with arsenate or other prohibited "
            "materials for new installations or replacement purposes in contact with soil or "
            "livestock."
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "A parcel-level declaration rather than an event: treated lumber is a standing "
            "property of the field's infrastructure, not a dated activity. Recorded on the "
            "parcel and asked in the parcel application."
        ),
        implementation=("trazo-back/product/models.py",),
        tests=("trazo-app/src/store/api/__tests__/mutationPayloadGuards.test.ts",),
        note=(
            "`treated_lumber_present` is one of the guarded keys in the mutation-payload "
            "tripwire: it was previously hardcoded into an unrelated form's payload, which is "
            "how one editor silently overwrote another editor's § 205.206(f) answer."
        ),
    ),
)

# ---------------------------------------------------------------------------------------
# 7 CFR 205.400 / 205.406 — Subpart E, certification and its continuation
#
# 🔴 2026-09-07 — WHY THIS GROUP WAS MISSING, and why that mattered. This file's own opening
# line scoped it to "205.103, 205.201 and 205.202-205.206", and the completeness tests
# hardcoded that same section list — so subpart E had no clause, no disposition, and no test
# that would notice. The obligations that fell through are the ones an ACA acts on fastest:
# the annual update itself, the five-year duty as a CONDITION OF CERTIFICATION rather than a
# recordkeeping rule, and the § 205.400(f) immediate-notification duty for drift.
#
# The register found it the same way: § 205.400(b)-(f) rested on ONE row, CCOF's certification
# contract ref G, graded P2, and WSDA had no counterpart row and no scope exclusion at all.
# ---------------------------------------------------------------------------------------

_S200 = (
    Clause(
        id="205.200",
        cite="7 CFR 205.200",
        verbatim=(
            "Production practices implemented in accordance with this subpart must maintain or "
            "improve the natural resources of the operation, including soil and water quality."
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "The umbrella duty every practice standard in subpart C serves, and the one a "
            "certifier reads the natural-resources answers against. Trazo asks the operation "
            "what it does about soil and water and compiles the answers into the "
            "§ 205.201(a)(1) narrative; whether the practices actually maintain or improve "
            "the resource is the agent's judgement on inspection, not a computation."
        ),
        implementation=("trazo-back/certifications/osp_modules/g4_2_natural_resources.py",),
        tests=("trazo-back/certifications/tests/test_osp_modules.py",),
        note=(
            "🔴 2026-09-07 — found by re-reading the section-scope guard rather than "
            'the regulation: the guard skipped every section id ending in "00", so '
            "§ 205.100 and this one were hidden by a filename-shaped heuristic. A guard that "
            "narrows its own input is the defect it exists to catch."
        ),
    ),
)


_S400 = (
    Clause(
        id="205.400(a)",
        cite="7 CFR 205.400(a)",
        verbatim="Comply with the Act and applicable organic production and handling regulations of this part;",
        disposition=Disposition.OPERATOR_COMMITMENT,
        rationale=(
            "The umbrella duty. No software complies on an operation's behalf; what Trazo does "
            "about it is every other clause in this file."
        ),
    ),
    Clause(
        id="205.400(b)",
        cite="7 CFR 205.400(b)",
        verbatim=(
            "Establish, implement, and update annually an organic production or handling system "
            "plan that is submitted to an accredited certifying agent as provided for in "
            "§ 205.201;"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "Trazo holds the plan, versions it, and produces the § 205.406 filing that carries "
            "the annual update. It does not SUBMIT it — the operation sends the packet to its "
            "agent — and it does not yet tell an operation that a year has passed without one."
        ),
        implementation=(
            "trazo-back/certifications/models.py::OSPAnnualUpdate",
            "trazo-back/certifications/services/osp_module_pdf.py::_annual_update_pdf",
        ),
        tests=("trazo-back/certifications/tests/test_renewal_packet_contents.py",),
        note=(
            "⚠️ NOT satisfied: `reporting_year` appears in no readiness or reminder path, so a "
            "year can pass with no filing and nothing says so until a packet is generated. "
            "That is the honest reason this is SUPPORTS and not SATISFIES."
        ),
    ),
    Clause(
        id="205.400(c)",
        cite="7 CFR 205.400(c)",
        verbatim=(
            "Permit on-site inspections with complete access to the production or handling "
            "operation, including noncertified production and handling areas, structures, and "
            "offices by the certifying agent as provided for in § 205.403;"
        ),
        disposition=Disposition.OPERATOR_COMMITMENT,
        rationale="Physical access to a farm. Nothing in software grants or withholds it.",
    ),
    Clause(
        id="205.400(d)",
        cite="7 CFR 205.400(d)",
        verbatim=(
            "Maintain all records applicable to the organic operation for not less than 5 years "
            "beyond their creation and allow authorized representatives of the Secretary, the "
            "applicable State organic program's governing State official, and the certifying "
            "agent access to such records during normal business hours for review and copying to "
            "determine compliance with the Act and the regulations in this part, as provided for "
            "in § 205.103;"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "TWO duties in one paragraph, and only one of them is software's. The retention half "
            "is enforced, not merely offered: the product refuses to delete "
            "a production inside its five-year window, refuses the same at each cascade "
            "container, and — since 2026-09-07 — refuses to erase a SALE on a closed season, "
            "which is the far end of the § 205.103(b)(2) trail. The access half is the "
            "operator's, and the free records export is what makes it possible."
        ),
        implementation=(
            "trazo-back/history/retention.py",
            "trazo-back/history/services/records_export.py",
        ),
        tests=("trazo-back/history/tests/test_record_retention.py",),
        note=(
            "Same duty as § 205.103(b)(4), stated again here as a CONDITION OF CERTIFICATION. "
            "An operation can be recordkeeping-compliant and still lose certification on this "
            "one, which is why it is mapped twice rather than cross-referenced."
        ),
    ),
    Clause(
        id="205.400(e)",
        cite="7 CFR 205.400(e)",
        verbatim="Submit the applicable fees charged by the certifying agent; and",
        disposition=Disposition.OUT_OF_SCOPE,
        rationale=(
            "A payment between the operation and its certifying agent. Trazo has no reason to "
            "hold it and does not compute any agent's fee schedule."
        ),
    ),
    Clause(
        id="205.400(f)",
        cite="7 CFR 205.400(f)",
        verbatim=(
            "Immediately notify the certifying agent concerning any: (1) Application, including "
            "drift, of a prohibited substance to any field, production unit, site, facility, "
            "livestock, or product that is part of an operation; and (2) Change in a certified "
            "operation or any portion of a certified operation that may affect its compliance "
            "with the Act and the regulations in this part."
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "`OSPChangeNotification` is a real record with the right shape — it distinguishes "
            "(f)(1) from (f)(2), carries the notification date and method, and prints as packet "
            "document 03. The NOTIFYING is the operator's act; Trazo records that it happened."
        ),
        implementation=(
            "trazo-back/certifications/models.py::OSPChangeNotification",
            "trazo-back/certifications/services/osp_module_pdf.py::_change_notifications_pdf",
        ),
        tests=("trazo-back/certifications/tests/test_renewal_packet_contents.py",),
        note=(
            "⚠️ A notice can still be withdrawn indefinitely: the freeze reads "
            "`certifier_acknowledged_at`, and nothing in the product writes that field. So the "
            "(f)(1) drift trail is currently deletable by the operation that filed it."
        ),
    ),
    Clause(
        id="205.400(g)",
        cite="7 CFR 205.400(g)",
        verbatim=(
            "In addition to paragraphs (a) through (f) of this section, a producer group "
            "operation must: (1) Be organized as a person; (2) Use centralized processing, "
            "distribution, and marketing facilities and systems; (3) Be organized into producer "
            "group production units;"
        ),
        disposition=Disposition.OUT_OF_SCOPE,
        rationale=(
            "Producer-group operations with an internal control system, the same scope § "
            "205.201(c) is excluded under. Trazo serves single certified operations."
        ),
        note=(
            "Verbatim stops at (g)(3); (g)(4)-(6) continue with the internal control system, "
            "which is the § 205.201(c) scope this operation type is excluded under."
        ),
    ),
)

_S406 = (
    Clause(
        id="205.406(a)(1)",
        cite="7 CFR 205.406(a)(1)",
        verbatim=(
            "A summary statement, supported by documentation, detailing any deviations from, "
            "changes to, modifications to, or other amendments made to the organic system plan "
            "submitted during the previous year;"
        ),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "`OSPAnnualUpdate.changes_summary` holds the statement and prints under its own "
            "(a)(1) heading in packet document 02. The documentation behind it is "
            "`OSPAnnualUpdate.supporting_documents`: files on the farm's Documents shelf, same farm "
            "only, signed with the filing, printed by name under the summary and shipped in the "
            "renewal packet under annual-update/supporting/. SUPPORTS, not SATISFIES: whether the "
            "files attached actually document the changes is the operator's to get right."
        ),
        implementation=(
            "trazo-back/certifications/models.py::OSPAnnualUpdate.changes_summary",
            "trazo-back/certifications/models.py::OSPAnnualUpdate.supporting_documents",
            "trazo-back/certifications/services/osp_module_pdf.py::_supporting_document_lines",
            "trazo-back/certifications/services/packet_attachments.py::annual_update_document_path",
        ),
        tests=(
            "trazo-back/certifications/tests/test_renewal_packet_contents.py",
            "trazo-back/certifications/tests/test_annual_update_documents.py",
        ),
        note=(
            "Until 2026-11-02 the filing had no attachment at all, while its sibling "
            "`OSPChangeNotification.supporting_document` did. Revisions signed before then name "
            "no documents and keep their signed hash: the list is hashed only when it is not empty."
        ),
    ),
    Clause(
        id="205.406(a)(2)",
        cite="7 CFR 205.406(a)(2)",
        verbatim=(
            "Any additions or deletions to the previous year's organic system plan, intended to "
            "be undertaken in the coming year, detailed pursuant to § 205.201;"
        ),
        disposition=Disposition.SOFTWARE_SATISFIES,
        rationale=(
            "`additions` and `deletions` are structured on the filing and each prints as its own "
            "bulleted section of packet document 02."
        ),
        implementation=(
            "trazo-back/certifications/models.py::OSPAnnualUpdate",
            "trazo-back/certifications/services/osp_module_pdf.py::_annual_update_pdf",
        ),
        tests=("trazo-back/certifications/tests/test_renewal_packet_contents.py",),
    ),
    Clause(
        id="205.406(a)(3)",
        cite="7 CFR 205.406(a)(3)",
        verbatim=("Any additions to or deletions from the information required pursuant to " "§ 205.401(b); and"),
        disposition=Disposition.SOFTWARE_SUPPORTS,
        rationale=(
            "The annual update's company-details step shows the § 205.401(b) details Trazo holds "
            "(business name, trade name, responsible person, farm address, phone, email) from the "
            "Company and Establishment records, in the packet cover's read order. The operator "
            "answers each one correct or changed: a change is written through the record's own "
            "update serializer and appends a dated old -> new line to "
            "`OSPAnnualUpdate.application_info_changes`; every detail confirmed sets the "
            "`application_information` attestation. The filing keeps the answer in one of three "
            "states, kept apart: the changes, the attestation that nothing changed, or neither, "
            'which 02 prints as "Not stated on this filing" and never as "no changes". Both are '
            "signed with the filing. Supports, not satisfies: the operator must answer."
        ),
        implementation=(
            "trazo-back/certifications/models.py::OSPAnnualUpdate.application_info_changes",
            "trazo-back/certifications/services/application_info_review.py::apply_review",
            "trazo-back/certifications/views.py::OSPAnnualUpdateViewSet",
            "trazo-back/certifications/services/osp_module_pdf.py::APPLICATION_INFO_KEY",
            "trazo-back/certifications/services/osp_module_pdf.py::_application_info_sentence",
            "trazo-app/src/views/Dashboard/OSP/OSPCompanyDetailsStep.tsx",
        ),
        tests=(
            "trazo-back/certifications/tests/test_annual_update_company_details.py",
            "trazo-back/certifications/tests/test_annual_update_revisions.py",
            "trazo-back/certifications/tests/test_renewal_packet_contents.py",
        ),
        note=(
            "Partial on one point: § 205.401(b) also asks, for a corporation, for the person authorized to act on its "
            "behalf. Trazo holds one named person (`Establishment.contact_person`), so a "
            "corporation whose authorized person differs states it in the free text. "
            "The statement fields shipped 2026-10-01 (commit 3f7c283); this row read NOT IMPLEMENTED until 2026-11-02. "
            'Before 2026-09-07 packet document 02 was subtitled "(a)(1)-(3)" while rendering '
            "(a)(1) and (a)(2) only. A filing that both attests no change and lists changes prints "
            "both and says they contradict each other, rather than choosing one."
        ),
    ),
    Clause(
        id="205.406(a)(4)",
        cite="7 CFR 205.406(a)(4)",
        verbatim=(
            "Other information as deemed necessary by the certifying agent to determine "
            "compliance with the Act and the regulations in this part."
        ),
        disposition=Disposition.OPERATOR_COMMITMENT,
        rationale=(
            "Whatever the agent asks for. Open by construction — the certifier register is "
            "Trazo's answer to what each agent actually asks, and it is not a clause list."
        ),
    ),
)


BINDING_CLAUSES: tuple[Clause, ...] = _S103 + _S200 + _S201 + _PRODUCTION_STANDARDS + _S400 + _S406


#: Sections of 7 CFR 205 this mapping CLAIMS to cover, and the stated reason for every binding
#: section it does not.
#:
#: 🔴 2026-09-07 — WHY THIS IS DECLARED RATHER THAN IMPLIED. The completeness tests derived the
#: expected clause list from the regulation per section, which is right — but the SECTION LIST
#: itself was hardcoded inside three test methods. So a section nobody had thought of was not a
#: failure, it was silence: § 205.105, § 205.207, § 205.271, § 205.272, § 205.273, § 205.290 and
#: the whole of subpart E had no clause, no disposition, and no test that would notice. That is
#: the same "an exclusion is not an absence" rule the certifier register runs on, applied to the
#: regulation instead of to a certifier's forms.
#:
#: An entry here with a reason is a decision. A binding section in NEITHER map fails
#: `test_every_in_scope_section_has_clauses`.
IN_SCOPE_SECTIONS: tuple[str, ...] = (
    "205.103",
    "205.200",
    "205.201",
    "205.202",
    "205.203",
    "205.204",
    "205.205",
    "205.206",
    "205.400",
    "205.406",
)

#: Binding sections deliberately NOT mapped, each with the reason. Reviewed 2026-09-07.
OUT_OF_SCOPE_SECTIONS: dict[str, str] = {
    "205.105": (
        "The allowed/prohibited substance rule. Not mapped as a clause because it is not a "
        "recordkeeping or practice obligation with a code counterpart — it is the National List "
        "itself, which Trazo implements as data (the OMRI/WSDA/CDFA catalogues and the "
        "§ 205.601-606 classifier) rather than as a clause. ⚠️ It is cited by 8 register rows; "
        "if a disposition is ever asserted about it, it belongs here as a clause."
    ),
    "205.207": (
        "Wild-crop harvesting. Trazo's ICP is cultivated orchard and berry ground; the product "
        "ships an N/A-attestable stub so a crop grower can say the section does not apply."
    ),
    "205.271": (
        "Facility pest management. A handler-facility standard; Trazo covers the grower-side "
        "questions its certifiers ask (module G9.0) without asserting the clause is satisfied."
    ),
    "205.272": (
        "Commingling and contact prevention. Post-SOE this reaches producers, and 25 register "
        "rows cite it — but Trazo's coverage is the certifiers' QUESTIONS about split "
        "operations, containers and transport, not a claim about the standard itself. "
        "⚠️ The strongest candidate for the next clause group."
    ),
    "205.273": (
        "Imports and the NOP Import Certificate. Export-programme territory, excluded from both "
        "certifier registers for the same reason."
    ),
    "205.290": (
        "Temporary variances, granted by the Administrator. No field anywhere in the codebase "
        "represents one, and inventing a record for a rare Administrator action would be worse "
        "than saying so. Relevant when a disaster drives non-organic seedlings under "
        "§ 205.204(a)(3)."
    ),
    "205.401": (
        "Application for certification. A first-time application; Trazo serves already-certified "
        "operations preparing an annual renewal. ⚠️ § 205.406(a)(3) points AT this section, and "
        "that clause is mapped as OPERATOR_COMMITMENT for exactly this reason."
    ),
    "205.100": (
        "What has to be certified. A scope rule about WHICH operations need certification, "
        "answered before an operation becomes a Trazo user at all — the product serves "
        "operations that are already certified and preparing a renewal."
    ),
    "205.101": (
        "Exemptions and exclusions from certification — operations selling under the $5,000 "
        "threshold. Trazo serves CERTIFIED operations preparing a renewal; an exempt operation "
        "has no certifying agent and no OSP to keep."
    ),
    "205.102": (
        "Use of the term organic. A labeling-eligibility rule; Trazo's labeling coverage is the "
        "certifiers' G7.0/§N questions, and its consumer surface is governed by the claim rules "
        "in .claude/rules/compliance.md rather than by a clause disposition here."
    ),
    "205.210": (
        "Mushroom production. A documented excluded scope — the register carries 27 rows about "
        "it across both agents, every one out_of_scope with the same reason."
    ),
    "205.236": "Origin of livestock — crop scope only.",
    "205.237": "Livestock feed — crop scope only.",
    "205.238": "Livestock health care practice standard — crop scope only.",
    "205.239": "Livestock living conditions — crop scope only.",
    "205.240": "Pasture practice standard — crop scope only.",
    "205.241": "Livestock facilities — crop scope only.",
    "205.242": "Animal welfare — crop scope only.",
    "205.270": (
        "Organic handling requirements. A handler standard; Trazo covers simple on-farm "
        "post-harvest handling of a farm's own crop as certifier QUESTIONS, and both registers "
        "exclude the handler OSP forms for the same reason."
    ),
    "205.402": "Review of application — the certifying AGENT's duty, not the operation's.",
    "205.403": "On-site inspection — the certifying AGENT's duty, not the operation's.",
    "205.404": "Granting certification — the agent's duty.",
    "205.405": "Denial of certification — the agent's duty.",
}


def clause_by_id(clause_id: str) -> Clause | None:
    for clause in BINDING_CLAUSES:
        if clause.id == clause_id:
            return clause
    return None


def clauses_for_section(section: str) -> tuple[Clause, ...]:
    """All clauses for e.g. "205.103"."""
    return tuple(c for c in BINDING_CLAUSES if c.id.startswith(section))
