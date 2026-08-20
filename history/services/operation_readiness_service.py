"""Is this operation's dossier fit to hand a certifier — right now?

ONE computation, three surfaces:

* the operation audit PDF stamps a DO-NOT-SUBMIT banner from it,
* the "share with your certifier" card refuses to mint a link past a blocker,
* the producer dashboard shows it as a pre-inspection checklist.

Why it exists: the per-production `AuditExportService` already refused to emit
(and stamped a red banner) when the Organic Fraud Prevention Plan was missing —
but `OperationAuditExportService` builds its own cover and never ran that gate.
So the ONE export that goes straight to a certifier was the only one with no
guardrail, which is backwards. Rather than copy the check into a second place,
the verdict lives here and every surface consults it.

Scope discipline: this reports what a certifier will reject a submission over,
not everything that could be improved. A checklist that cries wolf gets ignored,
and an ignored checklist is worse than none on the day of an inspection.
"""

import logging
import os

logger = logging.getLogger(__name__)

# An OFPP whose file is actually a purchase invoice is a hard non-conformance, not
# a missing document — the operation attested to a plan and filed something else.
# Mirrors AuditExportService._OFPP_SUSPICIOUS_FILENAME_PATTERNS.
OFPP_SUSPICIOUS_FILENAME_PATTERNS = ("factura", "invoice", "receipt", "comprobante", "recibo")

# Only NOP-scoped dossiers carry the OSP and SOE fraud-prevention requirements.
# A GlobalG.A.P. or FSMA 204 packet must never be blocked over either: an Organic
# System Plan is 7 CFR 205.201, not a food-safety artifact.
ORGANIC_PROFILES = ("organic", "all")

# Certification types that mean the operation is in (or entering) the NOP system.
# Mirrors AuditExportService's ORGANIC_CERT_TYPES.
ORGANIC_CONFERRING_CERT_TYPES = ("usda_organic", "ccof", "cng", "real_organic_project", "roc")


class OperationReadinessService:
    """Evaluate an establishment's submission-readiness for a certification profile."""

    def __init__(self, establishment, certification_type="organic"):
        self.establishment = establishment
        self.certification_type = (certification_type or "organic").lower()
        # Every check consults _nop_checks_apply(), which costs two queries.
        # Memoize so one evaluate() is not four round-trips for the same answer.
        self._nop_applies = None

    # ------------------------------------------------------------------

    def evaluate(self) -> dict:
        """Return {"ready", "applicable", "blockers", "warnings", "checked_items"}.

        `blockers` stop a submission. `warnings` are worth fixing but a certifier
        will still accept the packet. Both carry a `fix` string that names the
        concrete action, because "OFPP missing" without "upload it on the farm
        profile" is a puzzle, not a task.

        `applicable` is False when the NOP checks do not apply to this operation —
        a conventional grower must not be told they will fail an organic
        inspection they were never taking.
        """
        blockers = []
        warnings = []
        checked = []

        for check in (
            self._check_ofpp,
            self._check_osp,
            self._check_attestation_support,
            self._check_has_records,
        ):
            try:
                result = check()
            except Exception:  # noqa: BLE001 — a broken check must not hide the others
                logger.exception("Operation readiness check %s failed", check.__name__)
                continue
            if result is None:
                continue
            checked.append(result)
            if result["status"] == "blocker":
                blockers.append(result)
            elif result["status"] == "warning":
                warnings.append(result)

        return {
            "ready": not blockers,
            "applicable": self._nop_checks_apply(),
            "blockers": blockers,
            "warnings": warnings,
            "checked_items": checked,
        }

    # ------------------------------------------------------------------

    def _nop_checks_apply(self) -> bool:
        """Is this operation actually in the NOP system?

        Without this, every conventional farm's dashboard announced that its
        Organic Fraud Prevention Plan was missing — a requirement they are not
        subject to. Intent is read from the artifacts that only an organic
        operation creates, plus the free-text farming method captured at signup.
        """
        if self._nop_applies is not None:
            return self._nop_applies

        self._nop_applies = self._compute_nop_checks_apply()
        return self._nop_applies

    def _compute_nop_checks_apply(self) -> bool:
        if self.certification_type not in ORGANIC_PROFILES:
            return False

        from certifications.models import Certification, OrganicSystemPlan

        if OrganicSystemPlan.objects.filter(establishment=self.establishment).exists():
            return True
        if Certification.objects.filter(
            establishment=self.establishment, certification_type__in=ORGANIC_CONFERRING_CERT_TYPES
        ).exists():
            return True
        return "organic" in (getattr(self.establishment, "farming_method", "") or "").lower()

    # ------------------------------------------------------------------
    # Individual checks. Each returns a dict or None (not applicable).
    # ------------------------------------------------------------------

    def _ofpp_module_completed(self) -> bool:
        """True when the operator has completed OSP module G2.0.

        Since 2026-08-09 there are two legitimate routes to a fraud-prevention plan: attach a
        document the operator wrote elsewhere, or answer G2.0, whose questions ARE the plan
        (risk areas, mitigation practices, and the review process — the Common OSP Section 2
        content). Treating only the upload as valid would tell a farmer who just completed the
        module that they still have a blocker.
        """
        from certifications.models import OrganicSystemPlan

        for plan in OrganicSystemPlan.objects.filter(establishment=self.establishment):
            entry = ((plan.module_responses or {}).get("modules") or {}).get("g2_0_fraud_prevention") or {}
            if entry.get("completed_at"):
                return True
        return False

    def _check_ofpp(self):
        """Organic Fraud Prevention Plan — 7 CFR 205.201(a)(3), SOE 2024.

        SOE prohibits certification without a valid OFPP, so a missing or
        mis-filed plan blocks the submission outright.
        """
        if not self._nop_checks_apply():
            return None

        est = self.establishment
        if self._ofpp_module_completed():
            return {
                "key": "ofpp",
                "status": "ok",
                "title": "Organic Fraud Prevention Plan on file",
                "detail": "Authored in OSP module G2.0 — Monitoring & Organic Fraud Prevention.",
                "fix": "",
            }

        uploaded = bool(getattr(est, "fraud_prevention_plan_uploaded", False))
        doc = getattr(est, "fraud_prevention_plan_document", None)
        doc_name = ""
        if doc and getattr(doc, "name", ""):
            try:
                doc_name = os.path.basename(doc.name)
            except Exception:  # noqa: BLE001
                doc_name = ""

        suspicious = any(p in doc_name.lower() for p in OFPP_SUSPICIOUS_FILENAME_PATTERNS)

        if not uploaded:
            return {
                "key": "ofpp",
                "status": "blocker",
                "title": "Organic Fraud Prevention Plan is not on file",
                "detail": (
                    "SOE 2024 (7 CFR 205.201(a)(3)) prohibits certification without a valid "
                    "Organic Fraud Prevention Plan."
                ),
                "fix": (
                    "Complete OSP module G2.0 (Monitoring & Organic Fraud Prevention), or "
                    "upload a plan you already have on the farm profile."
                ),
            }

        if suspicious:
            return {
                "key": "ofpp",
                "status": "blocker",
                "title": "The uploaded Fraud Prevention Plan looks like the wrong document",
                "detail": (
                    f"The attached file is named “{doc_name}”, which reads as a purchase "
                    "document rather than a fraud-prevention plan. An inspector will treat "
                    "this as a non-conformance."
                ),
                "fix": "Replace the attachment with the actual Organic Fraud Prevention Plan.",
            }

        return {
            "key": "ofpp",
            "status": "ok",
            "title": "Organic Fraud Prevention Plan on file",
            "detail": "",
            "fix": "",
        }

    def _check_osp(self):
        """Organic System Plan — 7 CFR 205.201.

        A draft-only OSP is a warning, not a blocker: certifiers routinely receive
        the OSP and the records together, and the plan is what the review approves.
        Having none at all is what stops a submission.

        NOP-scoped: a GlobalG.A.P. dossier was being blocked over a missing OSP,
        which made it impossible for a non-organic operation to share anything.
        """
        if not self._nop_checks_apply():
            return None

        from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan

        plans = OrganicSystemPlan.objects.filter(establishment=self.establishment)
        if not plans.exists():
            return {
                "key": "osp",
                "status": "blocker",
                "title": "No Organic System Plan has been created",
                "detail": (
                    "7 CFR 205.201 requires an Organic System Plan covering the operation. "
                    "The dossier has nothing to reference."
                ),
                "fix": "Create the OSP from the farm's Organic System Plan page.",
            }

        # A materially EMPTY plan is a blocker, not a draft.
        #
        # This was a warning on the reasoning that certifiers routinely receive the
        # OSP and the records together. That holds for a drafted plan; it does not
        # hold for one with zero narrative. The 2026-08-03 dossier review proved it:
        # the PDF stamped its own front page "DRAFT — NOT FOR CERTIFIER SUBMISSION.
        # This OSP is materially incomplete and would not be accepted by an
        # accredited certifier" while this service returned ready=True — so the
        # share guard would have minted a certifier link to it.
        latest = plans.order_by("-version_number").first()
        filled = 0
        if latest is not None:
            sections = latest.sections if isinstance(latest.sections, dict) else {}
            # Any non-empty string counted as "filled", so "Test Test Test..."
            # padded past the dossier's 400-char floor cleared this too and the
            # share guard reopened (2026-08-04). Reuse the dossier's own content
            # test so the two surfaces cannot disagree again.
            from history.services.audit_export_service import looks_like_padding

            filled = sum(
                1
                for key in OSP_SECTION_KEYS
                for narrative in [str((sections.get(key) or {}).get("narrative", "") or "").strip()]
                if narrative and not looks_like_padding(narrative)
            )

        if filled == 0:
            return {
                "key": "osp",
                "status": "blocker",
                "title": "The Organic System Plan has no usable content",
                "detail": (
                    "No § 205.201(a) section contains real narrative — the sections are "
                    "empty or filled with repeated placeholder text. Per 7 CFR 205.662(c) an "
                    "OSP missing required sections is grounds for a Notice of Noncompliance."
                ),
                "fix": "Write the six OSP sections on the farm's Organic System Plan page.",
            }

        if not plans.filter(status__in=("submitted", "active")).exists():
            return {
                "key": "osp",
                "status": "warning",
                "title": "The Organic System Plan has not been submitted from Trazo",
                # 🔴 2026-08-19: this read "the plan has never been submitted to or approved by
                # a certifier" — a claim about the world that Trazo cannot make. All it knows
                # is its own `status`. An operation certified by CCOF already has an OSP agreed
                # with its agent, on CCOF's own forms; for that grower the sentence was simply
                # false, on a card they were being asked to trust.
                #
                # § 205.201(a) does require the plan be "agreed to by the producer and an
                # accredited certifying agent", so this remains a real item — unlike the
                # certificate or the photo count. It is the phrasing that overreached.
                "detail": (
                    f"{filled} of {len(OSP_SECTION_KEYS)} § 205.201(a) sections have content, "
                    "but this plan has not been submitted from Trazo. If your certifier already "
                    "holds an agreed OSP, submitting here keeps the two in step."
                ),
                "fix": "Finish the OSP sections and submit it to your certifier.",
            }

        return {"key": "osp", "status": "ok", "title": "Organic System Plan on file", "detail": "", "fix": ""}

    def _check_attestation_support(self):
        """Attestations the operation's own packet contradicts.

        A certifier read of a completed packet found modules attesting to lists that were
        empty: G3.0b said "planting stock suppliers are listed on the Supplier List" while
        the Supplier List had zero rows, and Materials Application made four separate
        "all materials are entered" statements against a near-empty list. Nothing is
        falsified — the workbooks are honest about blanks — but an attestation the packet
        itself contradicts is the fastest route to a noncompliance, and the operator has no
        way to notice before sending it.

        A WARNING, never a blocker. The producer authors the plan (§ 205.201(a)); Trazo does
        not refuse their statement or edit it. It reports what a reviewer will see.
        """
        if not self._nop_checks_apply():
            return None

        from certifications.models import OrganicSystemPlan

        plan = OrganicSystemPlan.objects.filter(establishment=self.establishment).order_by("-version_number").first()
        if plan is None:
            return None

        modules = (plan.module_responses or {}).get("modules") or {}

        def _answer(module_key, question_key):
            entry = (modules.get(module_key) or {}).get("answers") or {}
            return (entry.get(question_key) or {}).get("value")

        unsupported = []

        materials_attested = any(
            _answer("materials_application", key) is True
            for key in (
                "materials_list_complete",
                "fertilizers_listed",
                "pest_disease_weed_listed",
                "production_aids_listed",
                "post_harvest_contact_listed",
            )
        )
        approved_count = plan.approved_national_list_substances.count() + plan.approved_omri_products.count()
        if materials_attested and approved_count == 0:
            unsupported.append(
                "the Materials Application attests that all input materials are entered, "
                "but no materials are on the approved list"
            )

        if _answer("g3_2_planting_stock", "suppliers_on_supplier_list") is True:
            from certifications.services.common_osp_workbooks import WORKBOOKS_BY_KEY

            spec = WORKBOOKS_BY_KEY.get("supplier_list")
            try:
                supplier_rows = list(spec.rows(self.establishment)) if spec else []
            except Exception:  # noqa: BLE001
                supplier_rows = []
            if not supplier_rows:
                unsupported.append(
                    "G3.0b attests that planting stock suppliers are on the Supplier List, "
                    "but the Supplier List is empty"
                )

        # 🔴 2026-08-19, found the same way the two above were — by reading a finished packet
        # as a certifier would. G3.0b answered "no search records kept yet" while the Seed &
        # Planting Stock section of the very same packet printed three documented nursery
        # searches per planting event, and G3.0 two lines earlier said searches ARE
        # documented. § 205.204(a)(1) turns on those records; a plan that disowns evidence the
        # packet contains is worse than one that simply lacks it.
        if _answer("g3_2_planting_stock", "stock_search_records") == ["none_yet"]:
            from history.models import ProductionEvent

            documented = any(
                any(
                    isinstance(row, dict) and str(row.get("supplier_name") or row.get("supplier") or "").strip()
                    for row in (ev.seed_search_attempts or [])
                )
                for ev in ProductionEvent.objects.filter(
                    history__parcel__establishment=self.establishment
                ).exclude(seed_search_attempts__isnull=True)
            )
            if documented:
                unsupported.append(
                    "G3.0b attests that no commercial-availability search records are kept, "
                    "but the packet prints documented supplier searches against planting events"
                )

        if not unsupported:
            return {
                "key": "attestation_support",
                "status": "ok",
                "title": "OSP attestations are supported by the packet",
                "detail": "",
                "fix": "",
            }

        return {
            "key": "attestation_support",
            "status": "warning",
            "title": "An OSP attestation is not supported by the rest of the packet",
            "detail": (
                "A reviewer cross-checks each attestation against the document that should "
                "corroborate it: " + "; ".join(unsupported) + "."
            ),
            "fix": (
                "Add the missing entries, or change the answer — an attestation the packet "
                "itself contradicts reads as a noncompliance."
            ),
        }

    def _check_has_records(self):
        """An empty dossier wastes the reviewer's time and the farmer's credibility."""
        from history.models import History

        has_any = History.objects.filter(parcel__establishment=self.establishment).exists()
        if not has_any:
            return {
                "key": "records",
                "status": "blocker",
                "title": "This operation has no production records",
                "detail": "There is nothing for a certifier to review.",
                "fix": "Start a production and log the season's events.",
            }
        return {"key": "records", "status": "ok", "title": "Production records present", "detail": "", "fix": ""}
