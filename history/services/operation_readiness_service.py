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

⛔ EVERY item carries a stable `code` and machine-readable `params` ALONGSIDE its
English `title`/`detail`/`fix`. Read `READINESS_CODES` below before adding one.
"""

import logging
import os

# Imported, not restated. "Mirrors AuditExportService's ORGANIC_CERT_TYPES" was a comment
# standing where an import belonged: there were FIVE hand-maintained copies of "which types
# count as organic" across three modules, with FOUR different answers between them and no
# test holding any of them together. certifications.constants is the authority.
from certifications.constants import ORGANIC_CONFERRING_CERT_TYPES

logger = logging.getLogger(__name__)

# An OFPP whose file is actually a purchase invoice is a hard non-conformance, not
# a missing document — the operation attested to a plan and filed something else.
# Mirrors AuditExportService._OFPP_SUSPICIOUS_FILENAME_PATTERNS.
OFPP_SUSPICIOUS_FILENAME_PATTERNS = ("factura", "invoice", "receipt", "comprobante", "recibo")

# Only NOP-scoped dossiers carry the OSP and SOE fraud-prevention requirements.
# A GlobalG.A.P. or FSMA 204 packet must never be blocked over either: an Organic
# System Plan is 7 CFR 205.201, not a food-safety artifact.
ORGANIC_PROFILES = ("organic", "all")

# The wire contract with `readinessMessages.ts`. A code that is not in this tuple is drift;
# `test_readiness_codes.py` fails on an emitted code that is missing here, and the frontend
# test fails on one this file adds that no message id covers.
#
# 🌐 2026-09-02 — WHY CODES EXIST. Read before adding an item.
#
# Every string below used to reach the farm dashboard as English prose and nothing else, so a
# Spanish-locale farmer read "TODA LA OPERACIÓN" over "2 logged product(s) are not on your
# materials list". A server that returns prose has effectively opted the client out of
# translation — the same defect `users/constants.py` + `authErrors.ts` fixed for auth, settled
# the same way: a stable code plus the VALUES, and the client owns the sentence.
#
# `title`/`detail`/`fix` stay on the wire and stay English. They are not vestigial:
#   * `OperationAuditExportService` and the certifier-review page print them into a document
#     written FOR a US certifying agent, which is an English artifact by design, and
#   * they are the fallback for a code the client has not learned yet — an English sentence
#     that is TRUE beats a blank row (`authErrors.ts` calls this `fallbackText`).
#
# ⚠️ A param that is a LIST stays a list. Pre-joining it here ("A, B, and 3 more") bakes English
# conjunctions into a value and the translation cannot come apart again; the truncated array
# plus its overflow count is what lets es-419 write "y 3 más".
READINESS_CODES = (
    "check_unavailable",
    "ofpp.missing",
    "ofpp.suspicious_document",
    "ofpp.ok_module",
    "ofpp.ok",
    "osp.none",
    "osp.no_content",
    "osp.not_submitted",
    "osp.ok",
    "attestation_support.unsupported",
    "attestation_support.ok",
    "unmatched_materials.unlisted",
    "unmatched_materials.ok",
    "unmatched_materials.not_applicable",
    "parcel_maps.missing",
    "parcel_maps.ok",
    "parcel_maps.not_applicable",
    "handler_certificates.attention",
    "handler_certificates.ok",
    "handler_certificates.not_applicable",
    "records.none",
    "records.ok",
)

# Clause codes for `attestation_support.unsupported`. Each names ONE attestation the packet
# contradicts; the client renders them as a list, so the joining punctuation is the client's.
ATTESTATION_CLAUSE_CODES = (
    "materials_list_empty",
    "supplier_list_empty",
    "search_records_disowned",
)


class OperationReadinessService:
    """Evaluate an establishment's submission-readiness for a certification profile."""

    def __init__(self, establishment, certification_type="organic"):
        self.establishment = establishment
        self.certification_type = (certification_type or "organic").lower()
        # Every check consults _nop_checks_apply(), which costs two queries.
        # Memoize so one evaluate() is not four round-trips for the same answer.
        self._nop_applies = None
        # Five checks read the establishment's OSP versions; fetch them once (was 7 queries).
        self._plans = None

    @property
    def plans(self):
        """All OSP versions for the establishment, newest version first (cached per evaluate)."""
        if self._plans is None:
            from certifications.models import OrganicSystemPlan

            self._plans = list(
                OrganicSystemPlan.objects.filter(establishment=self.establishment).order_by("-version_number")
            )
        return self._plans

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

        # (key, callable) rather than bare callables: the key a failed check reports must not
        # depend on reading `__name__` off the object, which is exactly what is unavailable
        # when the callable has been replaced — including by the test that proves this path.
        for check_key, check in (
            ("ofpp", self._check_ofpp),
            ("osp", self._check_osp),
            ("attestation_support", self._check_attestation_support),
            ("has_records", self._check_has_records),
            # 🔴 2026-08-28 — the three below read exactly what the PACKET reads. Without them
            # the pilot's card said "ready · 0 warnings" on the same day its own packet printed
            # "[REVIEW] 8 product name(s) in the logged applications do not match an entry
            # above". Two numbers for one farm on one day is the defect this card was built to
            # remove, reappearing between the card and the document instead of between two cards.
            ("unmatched_materials", self._check_unmatched_materials),
            ("parcel_maps", self._check_parcel_maps),
            ("handler_certificates", self._check_handler_certificates),
        ):
            try:
                result = check()
            except Exception:  # noqa: BLE001 — a broken check must not hide the others
                # 🔴 2026-08-20 — `continue` here made a CRASHED check indistinguishable from a
                # PASSED one. `_check_attestation_support` was raising AttributeError on every
                # OSP whose answers came from the module wizard, and the operator's readiness
                # panel simply did not mention attestation support — reading, to them, as
                # nothing to fix. On a compliance surface "we could not evaluate this" and
                # "this is fine" must never render the same; the log line nobody opens is not
                # a disclosure. Surfaced as a warning: it is not a finding about the farm, so
                # it must not block, but it does have to be visible.
                logger.exception("Operation readiness check %s failed", check_key)
                result = {
                    "key": f"{check_key}_unavailable",
                    "code": "check_unavailable",
                    "params": {"check": check_key},
                    "status": "warning",
                    "title": "A readiness check could not be completed",
                    "detail": (
                        "Trazo could not finish one of its own readiness checks, so this list "
                        "is incomplete. This is a problem with Trazo, not a finding about your "
                        "operation."
                    ),
                    "fix": "Contact support so the check can be repaired before you submit.",
                }
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

        from certifications.models import Certification

        if self.plans:
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
        for plan in self.plans:
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
                "code": "ofpp.ok_module",
                "params": {},
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
                "code": "ofpp.missing",
                "params": {},
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
                "code": "ofpp.suspicious_document",
                "params": {"filename": doc_name},
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
            "code": "ofpp.ok",
            "params": {},
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

        from certifications.models import OSP_SECTION_KEYS

        plans = self.plans
        if not plans:
            return {
                "key": "osp",
                "code": "osp.none",
                "params": {},
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
        latest = plans[0] if plans else None  # `plans` is newest-version-first
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
                "code": "osp.no_content",
                "params": {},
                "status": "blocker",
                "title": "The Organic System Plan has no usable content",
                "detail": (
                    "No § 205.201(a) section contains real narrative — the sections are "
                    "empty or filled with repeated placeholder text. Per 7 CFR 205.662(c) an "
                    "OSP missing required sections is grounds for a Notice of Noncompliance."
                ),
                "fix": "Write the six OSP sections on the farm's Organic System Plan page.",
            }

        if not any(plan.status in ("submitted", "active") for plan in plans):
            return {
                "key": "osp",
                "code": "osp.not_submitted",
                "params": {"filled": filled, "total": len(OSP_SECTION_KEYS)},
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

        return {
            "key": "osp",
            "code": "osp.ok",
            "params": {},
            "status": "ok",
            "title": "Organic System Plan on file",
            "detail": "",
            "fix": "",
        }

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

        plan = self.plans[0] if self.plans else None
        if plan is None:
            return None

        modules = (plan.module_responses or {}).get("modules") or {}

        def _answer(module_key, question_key):
            # 🔴 2026-08-20 — `module_responses` holds TWO answer shapes and always has: the
            # REST endpoint writes an envelope `{"value": …, "at": …}` while the module wizard
            # writes the bare value. `(entry.get(key) or {}).get("value")` raises
            # AttributeError on a str, a bool or a list — and this whole readiness evaluation
            # is wrapped in a broad except, so the crash showed up as a silently absent
            # attestation-support warning rather than an error anyone could see.
            #
            # Third site of this class today (osp_module_pdf.py:366, certifications/views.py:1329
            # were the first two). `answer_value()` is the one reader that tolerates both.
            from certifications.osp_modules.conditions import answer_value

            entry = (modules.get(module_key) or {}).get("answers") or {}
            return answer_value(entry, question_key)

        # (clause_code, English sentence). The code is what es-419 renders; the sentence is
        # what the packet and the untranslated fallback print. Appended in lockstep so a new
        # clause cannot arrive with only one of the two.
        unsupported: list = []

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
        # ⛔ Count ALL FOUR sources, through the one reader. This counted National List + OMRI
        # only, so a plan whose materials are WSDA-listed or operator-entered — the CCOF NOPB41
        # §A case of compost, manure, gypsum and limestone — was told its own attestation was
        # unsupported, and a fabricated nonconformance went into the certifier register.
        # `plan_materials()` exists precisely so no caller has to remember how many sources
        # there are.
        from certifications.services.plan_materials import plan_materials

        approved_count = len(plan_materials(plan))
        if materials_attested and approved_count == 0:
            unsupported.append(
                (
                    "materials_list_empty",
                    "the Materials Application attests that all input materials are entered, "
                    "but no materials are on the approved list",
                )
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
                    (
                        "supplier_list_empty",
                        "G3.0b attests that planting stock suppliers are on the Supplier List, "
                        "but the Supplier List is empty",
                    )
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
                for ev in ProductionEvent.objects.filter(history__parcel__establishment=self.establishment).exclude(
                    seed_search_attempts__isnull=True
                )
            )
            if documented:
                unsupported.append(
                    (
                        "search_records_disowned",
                        "G3.0b attests that no commercial-availability search records are kept, "
                        "but the packet prints documented supplier searches against planting events",
                    )
                )

        if not unsupported:
            return {
                "key": "attestation_support",
                "code": "attestation_support.ok",
                "params": {},
                "status": "ok",
                "title": "OSP attestations are supported by the packet",
                "detail": "",
                "fix": "",
            }

        return {
            "key": "attestation_support",
            "code": "attestation_support.unsupported",
            "params": {"clauses": [clause_code for clause_code, _ in unsupported]},
            "status": "warning",
            "title": "An OSP attestation is not supported by the rest of the packet",
            "detail": (
                "A reviewer cross-checks each attestation against the document that should "
                "corroborate it: " + "; ".join(sentence for _, sentence in unsupported) + "."
            ),
            "fix": (
                "Add the missing entries, or change the answer — an attestation the packet "
                "itself contradicts reads as a noncompliance."
            ),
        }

    def _plan_being_filed(self):
        """The plan this card is talking about — the one that will be FILED, not the one in force.

        This card's heading is "Before your certifier packet", and the packet is generated from
        the plan the operator is preparing. Reading the ACTIVE plan instead looks right and is
        subtly wrong: a farm mid-renewal has an active v3 and a draft v4, and an operator fixing
        v4 would watch the warning refuse to clear because it was counting v3. Caught on the
        pilot, where the two differ by exactly the material added this morning (v4: 8 unmatched,
        v3: 9).

        Superseded and withdrawn versions are history, never the filing.
        """
        return next((plan for plan in self.plans if plan.status in ("draft", "active", "submitted")), None)

    def _check_unmatched_materials(self):
        """Products the records show were applied, with no matching entry on the plan.

        The packet already states this on the materials page. Saying it here is the point: the
        operator finds out BEFORE they generate the document, when adding the material is a
        thirty-second job, instead of reading it in a PDF they were about to send.

        A WARNING, never a blocker, and the wording matters. UNMATCHED IS NOT UNAPPROVED — a
        brand name and the National List substance that covers it read differently, so some of
        these are already accounted for. Calling them violations would invent a compliance
        finding out of a naming difference.
        """
        from certifications.services.plan_materials import unmatched_logged_materials

        osp = self._plan_being_filed()
        if osp is None:
            return {
                "key": "unmatched_materials",
                "code": "unmatched_materials.not_applicable",
                "params": {},
                "status": "ok",
                "title": "",
                "detail": "",
                "fix": "",
            }
        unmatched = unmatched_logged_materials(osp)
        if not unmatched:
            return {
                "key": "unmatched_materials",
                "code": "unmatched_materials.ok",
                "params": {},
                "status": "ok",
                "title": "Logged inputs match your materials list",
                "detail": "",
                "fix": "",
            }
        shown = ", ".join(unmatched[:5]) + (f", and {len(unmatched) - 5} more" if len(unmatched) > 5 else "")
        return {
            "key": "unmatched_materials",
            "code": "unmatched_materials.unlisted",
            # The product names are a LIST, and `overflow` is a NUMBER. `shown` below joins them
            # with an English ", and N more" for the packet; a client that received only that
            # string could not write the same sentence in Spanish.
            "params": {
                "count": len(unmatched),
                "products": list(unmatched[:5]),
                "overflow": max(len(unmatched) - 5, 0),
            },
            "status": "warning",
            "title": f"{len(unmatched)} logged product(s) are not on your materials list",
            "detail": (
                f"Your records show these were applied: {shown}. Your certifier's materials form "
                "asks for everything in use. A brand name and the substance entry that covers it "
                "can read differently, so some may already be accounted for — check each one."
            ),
            "fix": (
                "Open Organic System Plan \u2192 Materials: confirm each name against its listing under "
                "Logged names not on the plan, and add anything genuinely missing."
            ),
        }

    def _check_parcel_maps(self):
        """A map is an ATTACHMENT both CCOF and WSDA require, not a question.

        CCOF reviews it before inspecting a new parcel; WSDA asks for one with every site
        application. Trazo draws a boundary schematic, but that cannot carry roads, landmarks,
        block identifiers or the other operation areas CCOF lists — so a parcel with neither a
        recorded boundary nor an uploaded map ships a section E that says so.
        """
        from certifications.services.osp_module_pdf import parcel_map_documents

        parcels = list(self.establishment.parcels.all())
        if not parcels:
            return {
                "key": "parcel_maps",
                "code": "parcel_maps.not_applicable",
                "params": {},
                "status": "ok",
                "title": "",
                "detail": "",
                "fix": "",
            }
        without = [p for p in parcels if not p.polygon and not parcel_map_documents(p)]
        if not without:
            return {
                "key": "parcel_maps",
                "code": "parcel_maps.ok",
                "params": {},
                "status": "ok",
                "title": "Every parcel has a map or a recorded boundary",
                "detail": "",
                "fix": "",
            }
        shown_parcels = [(p.name or f"Parcel {p.pk}") for p in without[:4]]
        names = ", ".join(shown_parcels)
        more = f", and {len(without) - 4} more" if len(without) > 4 else ""
        return {
            "key": "parcel_maps",
            "code": "parcel_maps.missing",
            "params": {
                "count": len(without),
                "parcels": shown_parcels,
                "overflow": max(len(without) - 4, 0),
            },
            "status": "warning",
            "title": f"{len(without)} parcel(s) have no map",
            "detail": (
                f"{names}{more}. CCOF reviews the parcel map before inspecting a new parcel and "
                "WSDA asks for one with every site application, so a parcel with no boundary and "
                "no attached map leaves that section blank."
            ),
            "fix": "Draw the boundary on the parcel page, or attach your own map in section E.",
        }

    def _check_handler_certificates(self):
        """An off-farm handler's certificate must be current — and dated.

        `cert_is_current` is TRI-STATE: None means no effective date is recorded, which is an
        ASK, not a pass and not a failure. The packet prints it that way; this must too, or the
        card would report absence as compliance.
        """
        from certifications.models import PostHarvestFacility

        facilities = list(PostHarvestFacility.objects.filter(establishment=self.establishment))
        if not facilities:
            return {
                "key": "handler_certificates",
                "code": "handler_certificates.not_applicable",
                "params": {},
                "status": "ok",
                "title": "",
                "detail": "",
                "fix": "",
            }
        stale = [f for f in facilities if f.cert_is_current is False]
        undated = [f for f in facilities if f.cert_is_current is None]
        if not stale and not undated:
            return {
                "key": "handler_certificates",
                "code": "handler_certificates.ok",
                "params": {},
                "status": "ok",
                "title": "Handler certificates are current",
                "detail": "",
                "fix": "",
            }
        parts = []
        if stale:
            parts.append("expired or older than 15 months: " + ", ".join(f.name for f in stale[:3]))
        if undated:
            parts.append("no certificate date recorded: " + ", ".join(f.name for f in undated[:3]))
        return {
            "key": "handler_certificates",
            "code": "handler_certificates.attention",
            # Two independent problems under one count, so the client needs both lists
            # separately: "expired" and "never dated" are not the same ask.
            "params": {
                "count": len(stale) + len(undated),
                "stale": [f.name for f in stale[:3]],
                "stale_overflow": max(len(stale) - 3, 0),
                "undated": [f.name for f in undated[:3]],
                "undated_overflow": max(len(undated) - 3, 0),
            },
            "status": "warning",
            "title": f"{len(stale) + len(undated)} handler certificate(s) need attention",
            "detail": (
                "Once your crop leaves the farm the audit trail runs through the handler's "
                "records, so your certifier asks for their current organic certificate \u2014 " + "; ".join(parts) + "."
            ),
            "fix": "Update the facility on a production's post-harvest section.",
        }

    def _check_has_records(self):
        """An empty dossier wastes the reviewer's time and the farmer's credibility."""
        from history.models import History

        has_any = History.objects.filter(parcel__establishment=self.establishment).exists()
        if not has_any:
            return {
                "key": "records",
                "code": "records.none",
                "params": {},
                "status": "blocker",
                "title": "This operation has no production records",
                "detail": "There is nothing for a certifier to review.",
                "fix": "Start a production and log the season's events.",
            }
        return {
            "key": "records",
            "code": "records.ok",
            "params": {},
            "status": "ok",
            "title": "Production records present",
            "detail": "",
            "fix": "",
        }
