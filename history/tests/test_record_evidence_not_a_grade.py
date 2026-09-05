"""An event's evidence level states what the record CONTAINS. It is never a grade.

Found 2026-09-02 while reading the buyer page's event card as an outside reviewer.

``verification_level`` was a five-rung trust ladder — ``self_reported`` (trustScore 50) →
``photo_documented`` (65) → ``photo_verified`` (80) → ``data_verified`` (85) → ``certified``
(100) — computed independently in THREE places with three different answers:

* ``history.serializers.EventSerializer.get_verification_level`` (producer),
* ``history.serializers.PublicHistorySerializer._get_verification_level_for_event`` (the
  anonymous QR payload, called from eight places),
* ``carbon.services.timeline_service.TimelineService._calculate_verification_level``.

The frontend carried the percentages as data (``verificationTierHelpers.ts`` exported a
``trustScore`` per rung and a ``formatVerificationDisplay()`` printing "Photo Documented
(80% Trust)") and coloured the rungs gray → teal → blue → green-with-a-tick →
purple-with-a-star.

That is a self-assigned sustainability grade, which is exactly what EU ECGT 2024/825
(effective 2026-09-27) bans and what FTC 16 CFR 260.6 treats as an unqualified general claim.
It is the same artefact as the transparency score and the carbon letter grade, both already
withheld from consumers (see ``test_consumer_carbon_grade_removed``); this one survived two
sweeps because it was expressed as a BADGE rather than as a number.

Two rungs were worse than merely self-graded. ``data_verified`` and ``certified`` were awarded
for ``extra_data["blockchain_verified"]`` — so a per-event tier could print a blockchain claim
(a green tick, or a purple "Blockchain-Recorded" star) while ``BLOCKCHAIN_ENABLED`` is False
and the add-on is withdrawn, without ever asking ``may_claim_blockchain``. A surface that
decides locally is the defect ``claim_authority`` exists to prevent.

``photo_verified`` was a third problem: it claimed GPS metadata "verifies" an event, when it
records where a CAMERA was, and it rendered the SAME words as the rung below it in a DIFFERENT
colour — the grade the words refused to state, moved into the palette.

What is left is two states, both descriptions rather than judgements, decided in one place.

WHERE THE CHIP GOES (2026-09-02, second pass)
---------------------------------------------
Retiring the ladder left a neutral "Grower record" chip, and it was first placed the way the
ladder had been placed: on every event, on all three surfaces. That was wrong, and in one case
worse than what it replaced.

"Every record here is the grower's own" is a DISCLOSURE about a whole surface. A disclosure
belongs ONCE, at the level it applies to — which the buyer page already does, at the top, in
``TrustSummaryHeader``: "Practice records are farmer-reported, not independently audited."
Repeating it per card does not make it more conspicuous; it makes it wallpaper.

A QUALIFIER is a different thing: it belongs next to the specific claim it qualifies. FTC
16 CFR 260.6 wants a qualification clear and conspicuous NEAR THE CLAIM. Exactly one kind of
card asserts something a third party did — a certification or audit event, whose body reads
"An outside body reviewed this operation against a written standard" — so that is the one card
that carries the chip.

On the PRODUCER timeline it is neither: every row there is the grower's by construction, so
the chip was identical on every row (zero information) and its tooltip addressed a shopper.
The ladder it replaced at least varied per row, which is why a constant chip was a regression.
It is gone from that surface entirely.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from history.services.claim_authority import (
    EVIDENCE_PHOTO_DOCUMENTED,
    EVIDENCE_SELF_REPORTED,
    RETIRED_EVIDENCE_LEVELS,
    record_evidence_level,
)

_REPO = Path(__file__).resolve().parents[3]
BACKEND = _REPO / "trazo-back"
APP = _REPO / "trazo-app"

#: Every module that decides what an event's record contains. Each must ASK the authority.
EVIDENCE_SOURCES = (
    BACKEND / "history" / "serializers.py",
    BACKEND / "carbon" / "services" / "timeline_service.py",
)

#: `return "photo_verified"` / `return 'data_verified'` and friends. Deliberately anchored on
#: RETURN: `"certified"` is also a legitimate dict KEY in timeline_service (it mirrors the
#: model's own `certified` boolean), and a grep for the bare word would flag that forever and
#: teach the next reader to ignore this test.
_RETURNS_A_RETIRED_RUNG = re.compile(r"""return\s+["'](?:%s)["']""" % "|".join(sorted(RETIRED_EVIDENCE_LEVELS)))


class RecordEvidenceIsTwoStatesTests(SimpleTestCase):
    def test_only_two_values_are_reachable(self):
        reachable = {
            record_evidence_level(has_photos=photos, photos_flagged=flagged)
            for photos in (True, False)
            for flagged in (True, False)
        }
        self.assertEqual(
            reachable,
            {EVIDENCE_SELF_REPORTED, EVIDENCE_PHOTO_DOCUMENTED},
            "record_evidence_level grew a rung — a third value is a grade again",
        )

    def test_photos_that_all_failed_content_review_add_nothing(self):
        self.assertEqual(
            record_evidence_level(has_photos=True, photos_flagged=True),
            EVIDENCE_SELF_REPORTED,
        )

    def test_an_unscanned_photo_still_counts(self):
        # Absence of a Vision verdict is not a flag. Failing closed here would silently
        # downgrade every event uploaded while the scanner is unavailable.
        self.assertEqual(
            record_evidence_level(has_photos=True),
            EVIDENCE_PHOTO_DOCUMENTED,
        )


class NoSurfaceRevivesTheLadderTests(SimpleTestCase):
    def test_no_module_returns_a_retired_rung(self):
        for path in EVIDENCE_SOURCES:
            hits = _RETURNS_A_RETIRED_RUNG.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(
                hits,
                [],
                f"{path.relative_to(_REPO)} returns a retired evidence rung {hits}. "
                "The ladder was removed on 2026-09-02 — ask "
                "claim_authority.record_evidence_level instead.",
            )

    def test_every_evidence_source_asks_the_authority(self):
        for path in EVIDENCE_SOURCES:
            self.assertIn(
                "record_evidence_level",
                path.read_text(encoding="utf-8"),
                f"{path.relative_to(_REPO)} computes an evidence level without asking the "
                "authority. Three independent copies with three answers is how this "
                "defect lasted as long as it did.",
            )


class BlockchainCannotPromoteAnEventTests(SimpleTestCase):
    def test_the_public_payload_ignores_a_blockchain_flag(self):
        """``blockchain_verified=True`` must not upgrade an event.

        The argument is still accepted (eight call sites pass it) and must stay inert. Whether
        a production may say anything about blockchain is ``may_claim_blockchain``'s decision,
        made once for the production — not a per-event tier that routes around it.
        """
        from history.serializers import PublicHistorySerializer

        level = PublicHistorySerializer._get_verification_level_for_event(
            PublicHistorySerializer(),
            event=object(),
            has_photos=False,
            blockchain_verified=True,
        )
        self.assertEqual(level, EVIDENCE_SELF_REPORTED)


class ProvenanceChipGoesWhereAClaimNeedsQualifyingTests(SimpleTestCase):
    """The chip qualifies a claim; it is not a per-row disclosure.

    See the WHERE THE CHIP GOES note above. Guarded because the failure is invisible on the
    surface: a chip that is present everywhere and a chip that is present correctly look
    identical on the one card where it belongs.
    """

    CARD = APP / "src" / "components" / "Events" / "ConsumerEventCard.tsx"
    MODAL = APP / "src" / "components" / "Events" / "EnhancedEventDetailModal.tsx"
    TIMELINE_ROW = APP / "src" / "components" / "Tables" / "EnhancedTimelineRow.tsx"
    TRUST_HEADER = APP / "src" / "components" / "QR" / "TrustSummaryHeader.tsx"

    def test_the_producer_timeline_does_not_render_it(self):
        source = self.TIMELINE_ROW.read_text(encoding="utf-8")
        self.assertNotIn(
            "getRecordProvenance(",
            source,
            "EnhancedTimelineRow renders the provenance chip again. Every row on the "
            "grower's own timeline is the grower's own record, so the chip is identical on "
            "all of them and its tooltip is addressed to a shopper.",
        )

    def test_both_consumer_surfaces_gate_it_on_a_third_party_claim(self):
        for path in (self.CARD, self.MODAL):
            source = path.read_text(encoding="utf-8")
            self.assertIn(
                "getRecordProvenance(",
                source,
                f"{path.name} no longer renders the provenance chip at all. A certification "
                "or audit card asserts that an outside body reviewed the operation, and "
                "eventDescriptions.ts writes that line relying on the qualifier alongside.",
            )
            self.assertIn(
                "event_type === 7",
                source,
                f"{path.name} renders the provenance chip without gating it on a "
                "third-party-claim event. Ungated, it is a disclosure repeated per card — "
                "the page already carries that once, in TrustSummaryHeader.",
            )

    def test_the_page_level_disclosure_still_exists(self):
        """The per-card gate is only defensible because the page says it once, up top.

        If this line is ever removed, the narrow gate above stops being 'said once elsewhere'
        and becomes 'not said at all'.
        """
        self.assertIn(
            "consumer.trust.ftcDisclaimer",
            self.TRUST_HEADER.read_text(encoding="utf-8"),
            "TrustSummaryHeader no longer carries the page-level farmer-reported "
            "disclosure. The event cards were narrowed on the assumption that it does.",
        )


class FrontendMirrorsTheDecisionTests(SimpleTestCase):
    """The card must not re-grade what the server refused to grade.

    Six of the nine defects in the 2026-08-20 two-farm sweep were "fixed on the audited
    surface, alive on its sibling". This ladder had three sibling surfaces —
    ``ConsumerEventCard``, ``EnhancedEventDetailModal`` (also consumer: the buyer page's
    mobile journey opens it) and ``EnhancedTimelineRow`` (producer) — so the frontend half is
    guarded here rather than assumed.
    """

    HELPER = APP / "src" / "utils" / "verificationTierHelpers.ts"
    LOCALES = (
        APP / "src" / "i18n" / "lang" / "en-US.json",
        APP / "src" / "i18n" / "lang" / "es-419.json",
    )

    #: A DECLARATION, not a mention. Both names appear in the module note that explains why
    #: they are gone, and a test that forbids naming the thing it removed makes the removal
    #: undocumentable.
    _DECLARES_A_GRADE = re.compile(
        r"(?:^|\n)\s*(?:export\s+)?(?:function\s+formatVerificationDisplay\b" r"|trustScore\s*[:?]\s*(?:number|\d))"
    )

    def test_the_helper_declares_no_trust_score_and_no_grade_formatter(self):
        source = self.HELPER.read_text(encoding="utf-8")
        hit = self._DECLARES_A_GRADE.search(source)
        self.assertIsNone(
            hit,
            "verificationTierHelpers.ts declares a trust score or a grade formatter again "
            f"({hit.group(0).strip() if hit else ''!r}). The percentages ARE the grade, "
            "whether or not any component renders them today.",
        )

    def test_the_tier_labels_are_gone_from_both_locales(self):
        import json

        for path in self.LOCALES:
            keys = json.loads(path.read_text(encoding="utf-8"))
            revived = sorted(k for k in keys if k.startswith("consumer.eventCard.tier"))
            self.assertEqual(
                revived,
                [],
                f"{path.name} still ships tier labels {revived}.",
            )
            for required in (
                "consumer.eventCard.provenance.label",
                "consumer.eventCard.provenance.tooltip",
            ):
                self.assertIn(
                    required,
                    keys,
                    f"{path.name} is missing {required} — a missing key renders the English "
                    "fallback, and English on an English page looks correct.",
                )
