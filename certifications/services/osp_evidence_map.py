"""Which OSP statements assert that a RECORD exists, and what backs each one.

WHY THIS EXISTS
---------------
The OSP is a producer attestation under § 205.201(a), and it is the first document a certifier
opens. Most of its compiled statements describe a *practice* ("we use drip irrigation"), which
needs no artifact — the plan is the right home for a plan. But some assert that an *artifact
exists*: "Temperature logs kept for each compost batch: Yes", "Lot identity maintained through
storage (bin cards, pallet tags): Yes". Those are checkable, and where the record layer cannot
produce the artifact the packet contradicts itself in the certifier's hands.

Two such contradictions were found in August 2026, which is what makes this a class rather
than an anecdote:

  * `lot_identity_maintained` compiled "bin cards, pallet tags: Yes" while
    `ProductionEvent.storage_location` was empty and no storage record type existed at all.
  * `container_markings_tie_to_lot` compiled "Yes" while the lot-tag generator printed the
    literal string `LOT —` for 63% of published productions (fixed 2026-08-10; the tag now
    refuses to generate without a lot ID).

THE RULE THIS FILE ENFORCES
---------------------------
Every compiled statement that asserts a record exists must declare how it is evidenced. The
declaration is one of:

  EVIDENCED       a model field / relation a certifier can be shown. Names it explicitly.
  NOT_EVIDENCED   honest gap. The statement is a farmer attestation and nothing in Trazo can
                  corroborate it. Allowed — but recorded here rather than discovered by a
                  certifier, and each carries the ship-list item that would close it.
  OUT_OF_SCOPE    the practice does not apply to the ICP (wholesale tree nut / orchard), so
                  the statement is normally answered "not applicable".

`test_osp_evidence_map.py` fails when a record-asserting statement has no entry here. That is
the point: a NEW statement cannot be added to an OSP module without someone deciding, in
writing, whether Trazo can back it. A denylist would only encode the last incident.

Adding a statement here is not a substitute for building the record. NOT_EVIDENCED is a debt
marker, not an absolution.
"""

from dataclasses import dataclass

EVIDENCED = "evidenced"
NOT_EVIDENCED = "not_evidenced"
OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class EvidenceEntry:
    """How one record-asserting OSP statement is (or is not) backed by the record layer.

    ``source`` is "app.Model.field" for EVIDENCED entries — checked for existence by the test,
    so a renamed or deleted field breaks the build instead of silently orphaning a claim.
    ``note`` explains a NOT_EVIDENCED / OUT_OF_SCOPE decision.
    """

    status: str
    source: str = ""
    note: str = ""


#: Keyed by Question.key. Only statements whose compiled text asserts an artifact exists.
OSP_EVIDENCE_MAP: dict = {
    # --- G2.0 fraud prevention -------------------------------------------------
    "fraud_risk_areas": EvidenceEntry(
        EVIDENCED,
        source="certifications.OrganicSystemPlan.module_responses",
        note="OFPP upload is separately checked by the packet's OFPP (§ 205.201(a)(3)) row.",
    ),
    # --- G3.0 / G3.0b seeds and planting stock ---------------------------------
    "gmo_documentation": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.seed_certification_status",
    ),
    "planting_stock_description": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.seeds_source",
    ),
    "stock_search_records": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.seed_search_attempts",
        note=(
            "JSON is [{supplier_name, date_contacted, result, notes}]. The three statutory "
            "nonavailability axes (form/quality/quantity) are NOT structured — `result` is free "
            "text. Partial evidence; ship-list Tier 3 (#11)."
        ),
    ),
    "stock_records_kept": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.seed_lot_number",
    ),
    # --- G4.1 compost and manure ------------------------------------------------
    "compost_temp_logs_kept": EvidenceEntry(
        EVIDENCED,
        source="history.SoilManagementEvent.compost_temperature_log",
        note=(
            "TextField, not structured rows, so the per-reading responsible-party initials the "
            "USDA form carries are not queryable. The § 205.203(c)(2) thresholds themselves are "
            "checked against the scalar compost_peak_temp_f / duration / turning_count fields."
        ),
    ),
    "purchased_compost_documentation": EvidenceEntry(
        EVIDENCED,
        source="history.SoilManagementEvent.amendment_manufacturer",
        note="Names the supplier; the supplier's own document is not stored as an attachment.",
    ),
    "raw_manure_supplier_statement": EvidenceEntry(
        NOT_EVIDENCED,
        note=(
            "Compiles 'Supplier statement that off-farm manure is untreated on file: Yes' — the "
            "operator's attestation and nothing more. No upload holds the label or supplier "
            "statement OTCO C4 §4.3 asks to be PROVIDED (OTCO's own Manure Verification sheet is "
            "the supplier's half of that exchange), and module uploads do not travel into the "
            "packet in any case. Added 2026-09-09 with the question itself, so the debt is written "
            "down on day one: a `raw_manure_supplier_statement_upload` carried into the ZIP the "
            "way parcel maps travel would flip this to EVIDENCED."
        ),
    ),
    # --- G5.0 pest --------------------------------------------------------------
    "input_use_conditions": EvidenceEntry(
        EVIDENCED,
        source="history.PestManagementEvent.threshold_rationale",
    ),
    "monitoring_records": EvidenceEntry(
        EVIDENCED,
        source="history.PestManagementEvent.monitoring_count",
    ),
    # --- G6.1 harvest and transport ---------------------------------------------
    "custom_harvester_records": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.operator_is_custom",
        note="Flags the custom operator; the harvester's own per-pass record is not stored.",
    ),
    "lot_identification_on_every_load": EvidenceEntry(
        EVIDENCED,
        source="history.History.lot_id",
        note=(
            "Enforced at the point of printing since 2026-08-10: may_label_container() refuses "
            "to generate a tag without a lot ID rather than printing a placeholder."
        ),
    ),
    "non_own_transport_records": EvidenceEntry(
        EVIDENCED,
        source="history.SalesRecord.bill_of_lading",
        note="Reference number, not the document itself. Carrier and vehicle are alongside it.",
    ),
    "harvest_records_kept": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.harvest_lot_code",
        note=(
            "Harvest activities carry the date, quantity, crop, parcel or block and the harvest lot "
            "code; a weigh ticket or receiving record is a file the operator adds."
        ),
    ),
    "harvest_transport_records_source": EvidenceEntry(
        NOT_EVIDENCED,
        note=(
            "States who generates the harvest and transport records. Records a custom harvester or "
            "carrier gives the operation are not stored per pass; a bill of lading is a reference "
            "number on SalesRecord, not the document."
        ),
    ),
    "third_party_cleaning_documentation": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.cleaned_by",
        note=(
            "A cleaning activity names who cleaned the equipment; an affidavit a custom operator signs "
            "is a file in Documents, not tied to this answer."
        ),
    ),
    "container_cleaning_records": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.cleaning_asset_class",
        note=(
            "Cleaning activities logged against harvest bins. A written procedure rides as the "
            "container_cleaning_sop_upload file, and the module PDF prints a [REVIEW] line when the "
            "answer says it is attached and nothing is."
        ),
    ),
    "carrier_handles_beyond_transport": EvidenceEntry(
        NOT_EVIDENCED,
        note=(
            "A fact about the carrier's role, the CCOF trigger for certification or an Exempt Handler "
            "Affidavit (NOPB107). The affidavit itself is not tracked (CCOF G6.2 ref A, G6.5 ref A1)."
        ),
    ),
    # --- G6.2 storage -----------------------------------------------------------
    "lot_identity_maintained": EvidenceEntry(
        NOT_EVIDENCED,
        note=(
            "Compiles 'Lot identity maintained through storage (bin cards, pallet tags): Yes' "
            "while ProductionEvent.storage_location is a bare CharField, empty on the live "
            "fixture, and no storage record type exists — no dated in/out movements, no "
            "per-location balance. Ship-list Tier 2 item 8 (storage ledger).\n\n"
            "SCOPE OF THE CONCERN, corrected 2026-08-10. An earlier draft called this a "
            "claim-safety defect. It is not. The packet carries an explicit Producer Attestation "
            "(§ 205.401 / § 205.400(a)) — 'I, the undersigned, hereby certify under penalty of "
            "law...' — so a grower attesting that they keep bin cards in their own shed is a "
            "legitimate OSP answer, and Trazo is not obliged to hold every artifact a farm "
            "maintains. What remains true is narrower and still worth closing: a certifier who "
            "asks 'show me' gets nothing from Trazo, so the operation falls back to paper for a "
            "record the platform could carry. That is a product gap, not an overclaim."
        ),
    ),
    "uncertified_facility_records": EvidenceEntry(
        EVIDENCED,
        source="certifications.PostHarvestFacility.cert_document",
    ),
    "uncertified_handler_records": EvidenceEntry(
        NOT_EVIDENCED,
        note=(
            "The operator describes what an UNCERTIFIED handler gives them — lot tags, "
            "separation logs, cleaning records for the equipment used. By definition that "
            "operation has no organic certificate to hold, so `PostHarvestFacility.cert_document` "
            "is the wrong evidence and the honest answer is that Trazo carries nothing. Its "
            "certified counterpart IS evidenced: the facility's name, certifier, certificate "
            "number and freshness now print in the plan (G6.1 \u00a7D, shipped 2026-08-28). Closing "
            "this one means an upload slot on the facility record for the handler's own "
            "identity-preservation paperwork, which is the same attachment loop CCOF G6.1 C2 "
            "still needs for the certificate itself."
        ),
    ),
    # --- G6.4 handling ----------------------------------------------------------
    "custom_handling_separation": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.shared_with_conventional",
    ),
    "handling_records": EvidenceEntry(
        EVIDENCED,
        source="history.ProductionEvent.harvest_contract_number",
    ),
    # --- G7.0 labeling ----------------------------------------------------------
    "label_states_certifier": EvidenceEntry(
        EVIDENCED,
        source="certifications.Certification.certifier_name",
        note="Consumer surface renders it only via public_certifier_name() in claim_authority.",
    ),
    "label_has_usda_seal": EvidenceEntry(
        EVIDENCED,
        source="certifications.Certification.verification_source",
        note="Seal shows only on an OID match (§ 205.311); TrustSummaryHeader gates on it.",
    ),
    "invoices_identify_lot": EvidenceEntry(
        EVIDENCED,
        source="history.SalesRecord.invoice_number",
        note=(
            "Trazo records the invoice NUMBER against a lot; it does not produce the invoice, so "
            "whether the printed invoice carries the lot remains the operation's attestation."
        ),
    ),
    "container_markings_tie_to_lot": EvidenceEntry(
        EVIDENCED,
        source="history.History.lot_id",
        note=(
            "Was NOT_EVIDENCED until 2026-08-10: the tag printed 'LOT —' whenever lot_id was "
            "null, which was 63% of published productions. Now refused at generation time."
        ),
    ),
    "label_claim_review_process": EvidenceEntry(
        EVIDENCED,
        source="history.LabelImage.gallery_image",
        note="Uploaded label artwork is the artifact; the review process itself is narrative.",
    ),
    # --- G8.0 recordkeeping -----------------------------------------------------
    "records_retention_attestation": EvidenceEntry(
        EVIDENCED,
        source="history.History.retention_until",
        note=(
            "Computed at finalization and enforced by the deletion guard on History. The "
            "5-calendar-year arithmetic was corrected 2026-08-10 (was 1825 days, 1-2 days short "
            "of the § 205.103(b)(4) floor)."
        ),
    ),
    "lot_numbering": EvidenceEntry(
        EVIDENCED,
        source="history.History.lot_id",
    ),
    # WSDA AGR 2121-O q5/q6/q7 (added 2026-09-06). All five are NOT_EVIDENCED and that is the
    # honest answer, not a debt to pay down: each states a fact about the operation's OFFICE —
    # where paper lives, who holds the key, whether anything is on paper at all — and Trazo is
    # one of the systems being described, not a witness to the others. There is no field that
    # could corroborate "the bookkeeper keeps the deposit statements", and inventing one would
    # be a self-report wearing a record's clothes.
    "records_location": EvidenceEntry(
        NOT_EVIDENCED,
        note=(
            "Where the operation's records physically live. Unknowable from inside the product; "
            "an inspector confirms it on the day (§ 205.103(c))."
        ),
    ),
    "additional_records_locations": EvidenceEntry(
        NOT_EVIDENCED,
        note="Free-text rider on records_location — the same limit applies.",
    ),
    "primary_contact_records_access": EvidenceEntry(
        NOT_EVIDENCED,
        note=(
            "Who can reach the records. Trazo knows its own users' permissions and nothing about "
            "a filing cabinet, a bookkeeper or a packing house."
        ),
    ),
    "records_access_delegate": EvidenceEntry(
        NOT_EVIDENCED,
        note="Free-text rider on primary_contact_records_access — the same limit applies.",
    ),
    "records_maintained_as": EvidenceEntry(
        NOT_EVIDENCED,
        note=(
            "Electronic / hardcopy. The 'electronic' half is self-demonstrating — the packet was "
            "generated from the system — but the hardcopy half is a statement about paper Trazo "
            "has never seen, and half a corroboration is not one."
        ),
    ),
    "import_documentation": EvidenceEntry(
        OUT_OF_SCOPE,
        note="ICP is domestic wholesale tree nut / orchard; import controls do not apply.",
    ),
    "import_documentation_other": EvidenceEntry(OUT_OF_SCOPE, note="Free-text rider on import_documentation."),
    "import_export_records": EvidenceEntry(
        OUT_OF_SCOPE,
        note=(
            "Domestic ICP. Note § 205.307(d) export marking would apply if an operation ever "
            "ships 'For Export Only' — revisit before selling into that segment."
        ),
    ),
    # --- G9.0 facility pest -----------------------------------------------------
    "pest_control_records": EvidenceEntry(
        EVIDENCED,
        source="history.PestManagementEvent.pest_species",
        note="Facility pest control shares the PestManagementEvent model; there is no separate one.",
    ),
    "preventive_measures_documentation": EvidenceEntry(
        EVIDENCED,
        source="history.PestManagementEvent.ipm_strategy",
        note="§ 205.271(c) escalation rationale; the packet's IPM strategy row reads the same field.",
    ),
    "preventive_measures_documentation_other": EvidenceEntry(
        EVIDENCED,
        source="history.PestManagementEvent.threshold_rationale",
    ),
}


def unevidenced_statements():
    """Statement keys whose OSP claim nothing in Trazo can corroborate.

    Surfaced deliberately: these are the statements where the packet is relaying a farmer
    attestation and should not imply record backing.
    """
    return sorted(k for k, v in OSP_EVIDENCE_MAP.items() if v.status == NOT_EVIDENCED)
