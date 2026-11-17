"""How each restriction on a plan material is met, as the operator states it (T18, Phase 5 slice 2b).

THE RULES (Oscar, 2026-10-02)
-----------------------------
* A statement is bound to one material on one plan version and one identified restriction. A material
  may carry several restrictions.
* Restriction text is either regulation text Trazo holds (a § 205.602 condition of use, or a § 205.601
  annotation held verbatim in `national_list_citations.ANNOTATIONS`, with its citation, its effective
  date and when Trazo read it), WSDA's own annotation for a WSDA-listed product (`WSDAMaterial.annotation`,
  with the list's edition date; 2026-11-17), or text the operator transcribed from a source
  (label, OMRI or WSDA listing, certifier letter...), printed as "Restriction transcribed by the
  operator; not independently verified by Trazo." Verified wording never says the restriction applies
  to this material or use. A WSDA annotation is WSDA's own condition on that product, so it is printed
  as WSDA's words for that product number, with no applicability caveat; it still says nothing about
  whether the use meets it.
* Trazo holds no OMRI restriction wording (OMRI's terms are an open question, 2026-10-14), so an OMRI
  product's restriction is always transcribed by the operator from the listing.
* "How it is met" is the operator's statement, attributed and dated. It is never a compliance result.
* A material with no restriction on record reads "restriction not documented", never "no
  restrictions".
* History is kept: a change supersedes. A statement whose material, restriction text or plan version
  has since changed is shown as needing review.
* A statement approves nothing, classifies nothing and clears no finding.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from certifications.models import PlanMaterialRestrictionStatement as PRS

TRANSCRIBED_LABEL = "Restriction transcribed by the operator; not independently verified by Trazo."
NOT_DOCUMENTED = "Restriction not documented in Trazo."
APPLICABILITY_NOT_ESTABLISHED = "Whether it applies to this material and use is not established by Trazo."
#: How a WSDA annotation is attributed wherever it prints: WSDA's words, as Trazo copied them from the list.
WSDA_WORDS = "WSDA's words, transcribed by Trazo"

CURRENT = "current"
NEEDS_REVIEW = "needs_review"

_KIND_BY_SOURCE = {"OMRI": PRS.MATERIAL_OMRI, "WSDA": PRS.MATERIAL_WSDA}


class RestrictionError(Exception):
    def __init__(self, message, status_code=400, field=None):
        super().__init__(message)
        self.status_code = status_code
        self.field = field


def material_ref(material) -> tuple:
    """(kind, id, name) for a `plan_materials` row. A folded row is filed under its catalog."""
    from certifications.services.plan_materials import NONSYNTHETIC_SOURCE

    if material.source in ("National List", NONSYNTHETIC_SOURCE) and material.source_id:
        return PRS.MATERIAL_NATIONAL_LIST, material.source_id, material.name
    if material.source in _KIND_BY_SOURCE and material.source_id:
        return _KIND_BY_SOURCE[material.source], material.source_id, material.name
    if material.entry_id:
        return PRS.MATERIAL_PLAN_ENTRY, material.entry_id, material.name
    return None, None, material.name


def plan_material_refs(osp) -> list:
    from certifications.services.plan_materials import plan_materials

    out = []
    for material in plan_materials(osp):
        kind, mid, name = material_ref(material)
        if kind:
            out.append((kind, mid, name))
    return out


def _linked_substance(osp, kind, mid):
    """The National List row a material is, or names, if any."""
    from certifications.models import NationalListSubstance, PlanMaterialEntry

    if kind == PRS.MATERIAL_NATIONAL_LIST:
        return NationalListSubstance.objects.filter(pk=mid).first()
    if kind == PRS.MATERIAL_PLAN_ENTRY:
        entry = PlanMaterialEntry.objects.filter(pk=mid, osp=osp).first()
        return getattr(entry, "national_list_substance", None)
    return None


def _linked_wsda(osp, kind, mid):
    """The WSDA listing a material is, or that the operator's entry links, if any."""
    from certifications.models import PlanMaterialEntry, WSDAMaterial

    if kind == PRS.MATERIAL_WSDA:
        return WSDAMaterial.objects.filter(pk=mid).first()
    if kind == PRS.MATERIAL_PLAN_ENTRY:
        entry = PlanMaterialEntry.objects.filter(pk=mid, osp=osp).select_related("wsda_material").first()
        return getattr(entry, "wsda_material", None)
    return None


def wsda_list_restriction(osp, kind, mid) -> Optional[dict]:
    """WSDA's own annotation for this material's WSDA listing, or None.

    None when the material has no WSDA listing, when WSDA prints NONE for it (stored as "") and when the
    annotation was never transcribed (NULL). NONE is not offered as a restriction and is never printed as
    "no restrictions": the label can still restrict use, and that stays "restriction not documented"."""
    from certifications.services.registry_identifiers import wsda_identifier_label

    material = _linked_wsda(osp, kind, mid)
    text = " ".join((getattr(material, "annotation", None) or "").split())
    if material is None or not text:
        return None
    return {
        "key": f"wsda:{material.pk}",
        "material": material,
        "text": text,
        # "WSDA Product #3376"; a row with no real product number is still WSDA's listing.
        "citation": wsda_identifier_label(material.wsda_id) or "WSDA listing",
        "effective_date": material.list_effective_date,
        "read_at": material.updated_at,
        "source_url": material.source_url or "",
    }


def _wsda_source(citation, effective_date) -> str:
    edition = effective_date.isoformat() if effective_date else "edition date not held"
    return f"WSDA annotation, {citation} (Organic Input Material List of {edition}, {WSDA_WORDS})"


def regulation_restriction(osp, kind, mid) -> Optional[dict]:
    """The restriction Trazo holds as REGULATION wording for this material, or None.

    A § 205.602 condition of use counts: those notes are the rule's own words (migration 0039). Of the
    § 205.601 notes, only the rows `national_list_citations.ANNOTATIONS` holds verbatim count, cited to
    the paragraph whose text it is (migration 0071). Every other § 205.601 note is descriptive (one is
    a label term), so it is never offered as regulation text."""
    from certifications.services.national_list_citations import held_annotation

    substance = _linked_substance(osp, kind, mid)
    if substance is None:
        return None
    held = held_annotation(substance)
    if held is None and not getattr(substance, "is_conditionally_permitted", False):
        return None
    text = (substance.restriction_notes or "").strip()
    if not text:
        return None
    citation = f"§ {substance.cfr_section}{held[0]}" if held else substance.citation
    return {
        "key": f"nl:{substance.pk}",
        "substance": substance,
        "text": text,
        "citation": citation,
        "effective_date": substance.effective_date,
        "read_at": substance.updated_at,
    }


def _transcribed_key(text, source_type, identifier) -> str:
    canonical = "|".join([" ".join(text.split()).lower(), source_type, " ".join(identifier.split()).lower()])
    return "t:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:40]


def statement_state(statement, osp) -> str:
    """CURRENT, or NEEDS_REVIEW when its plan, material or restriction text has changed since."""
    if statement.osp_id != osp.pk:
        return NEEDS_REVIEW
    refs = {(k, i): n for k, i, n in plan_material_refs(osp)}
    name = refs.get((statement.material_kind, statement.material_id))
    if name is None or " ".join(name.split()).lower() != " ".join(statement.material_name.split()).lower():
        return NEEDS_REVIEW
    if statement.restriction_source == PRS.SOURCE_REGULATION:
        held = regulation_restriction(osp, statement.material_kind, statement.material_id)
        if held is None or held["key"] != statement.restriction_key or held["text"] != statement.restriction_text:
            return NEEDS_REVIEW
    if statement.restriction_source == PRS.SOURCE_WSDA_LIST:
        # A new WSDA edition that rewords or drops the annotation puts the answer back in front of the
        # operator: they answered the old words.
        held = wsda_list_restriction(osp, statement.material_kind, statement.material_id)
        if held is None or held["key"] != statement.restriction_key or held["text"] != statement.restriction_text:
            return NEEDS_REVIEW
    return CURRENT


@transaction.atomic
def record_statement(osp, user, data) -> PRS:
    """Validate and store one statement. Raises RestrictionError (400/404/409); writes nothing then."""
    kind = data.get("material_kind")
    try:
        mid = int(data.get("material_id"))
    except (TypeError, ValueError):
        raise RestrictionError("Choose the material on this plan.", field="material_id")
    refs = {(k, i): n for k, i, n in plan_material_refs(osp)}
    if (kind, mid) not in refs:
        raise RestrictionError("That material is not on this plan.", status_code=404, field="material_id")
    material_name = refs[(kind, mid)]
    how_met = (data.get("how_met") or "").strip()
    if not how_met:
        raise RestrictionError("Say how the restriction is met.", field="how_met")

    source = data.get("restriction_source")
    fields = {}
    if source == PRS.SOURCE_REGULATION:
        held = regulation_restriction(osp, kind, mid)
        if held is None:
            raise RestrictionError(
                "Trazo holds no regulation wording for this material's restriction. Transcribe it from its source.",
                field="restriction_source",
            )
        fields = {
            "restriction_key": held["key"],
            "restriction_text": held["text"],
            "national_list_substance": held["substance"],
            "citation": held["citation"],
            "source_effective_date": held["effective_date"],
            "source_read_at": held["read_at"],
        }
    elif source == PRS.SOURCE_WSDA_LIST:
        held = wsda_list_restriction(osp, kind, mid)
        if held is None:
            raise RestrictionError(
                "Trazo holds no WSDA annotation for this material. Transcribe the restriction from its source.",
                field="restriction_source",
            )
        fields = {
            "restriction_key": held["key"],
            "restriction_text": held["text"],
            "citation": held["citation"],
            "source_effective_date": held["effective_date"],
            "source_read_at": held["read_at"],
        }
    elif source == PRS.SOURCE_TRANSCRIBED:
        text = (data.get("restriction_text") or "").strip()
        source_type = data.get("source_type") or ""
        if not text:
            raise RestrictionError("Copy the restriction's wording from its source.", field="restriction_text")
        if source_type not in dict(PRS.DOC_CHOICES):
            raise RestrictionError("Say what kind of source the wording comes from.", field="source_type")
        identifier = (data.get("source_identifier") or "").strip()
        attachment = None
        if data.get("attachment"):
            from documents.models import GeneratedDocument

            try:
                attachment_id = int(data.get("attachment"))
            except (TypeError, ValueError):
                raise RestrictionError("Choose a document from this operation.", field="attachment")
            attachment = GeneratedDocument.objects.filter(
                pk=attachment_id, establishment_id=osp.establishment_id
            ).first()
            if attachment is None:
                raise RestrictionError("That document is not on this operation.", status_code=404, field="attachment")
        fields = {
            "restriction_key": _transcribed_key(text, source_type, identifier),
            "restriction_text": text,
            "source_type": source_type,
            "source_identifier": identifier,
            "source_locator": (data.get("source_locator") or "").strip(),
            "source_reference": (data.get("source_reference") or "").strip(),
            "attachment": attachment,
        }
    else:
        raise RestrictionError("Choose where the restriction's wording comes from.", field="restriction_source")

    existing = (
        PRS.objects.select_for_update()
        .filter(
            osp=osp,
            material_kind=kind,
            material_id=mid,
            restriction_key=fields["restriction_key"],
            superseded_at__isnull=True,
        )
        .first()
    )
    supersedes = data.get("supersedes")
    if supersedes is not None:
        try:
            supersedes = int(supersedes)
        except (TypeError, ValueError):
            raise RestrictionError("Name the statement this one replaces.", field="supersedes")
    if existing is not None and supersedes != existing.pk:
        raise RestrictionError(
            "A current statement already covers this restriction. Supersede it explicitly.",
            status_code=409,
            field="supersedes",
        )
    if existing is None and supersedes is not None:
        raise RestrictionError("There is no current statement to supersede.", status_code=409, field="supersedes")
    now = timezone.now()
    if existing is not None:
        existing.superseded_at = now
        existing.save(update_fields=["superseded_at"])
    name = ""
    if user is not None and getattr(user, "is_authenticated", False):
        name = (user.get_full_name() or "").strip() or (getattr(user, "email", "") or "")
    try:
        with transaction.atomic():
            return PRS.objects.create(
                osp=osp,
                material_kind=kind,
                material_id=mid,
                material_name=material_name,
                restriction_source=source,
                how_met=how_met,
                stated_by=user if getattr(user, "is_authenticated", False) else None,
                stated_by_name=name,
                stated_at=now,
                supersedes=existing,
                **fields,
            )
    except IntegrityError:
        raise RestrictionError(
            "Another statement was recorded at the same time. Reload and review it.", status_code=409
        )


def statement_lines(statement) -> list:
    """What a document prints for one statement: the restriction as what it is, then the operator's words."""
    if statement.restriction_source == PRS.SOURCE_REGULATION:
        when = statement.source_effective_date.isoformat() if statement.source_effective_date else "date not held"
        read = statement.source_read_at.date().isoformat() if statement.source_read_at else "not recorded"
        restriction = (
            f"Restriction, {statement.citation} (regulation wording held by Trazo, effective {when}, read {read}): "
            f'"{statement.restriction_text}" {APPLICABILITY_NOT_ESTABLISHED}'
        )
    elif statement.restriction_source == PRS.SOURCE_WSDA_LIST:
        restriction = (
            f"{_wsda_source(statement.citation, statement.source_effective_date)}: " f'"{statement.restriction_text}"'
        )
    else:
        source = dict(PRS.DOC_CHOICES).get(statement.source_type, statement.source_type)
        where = ", ".join(x for x in (statement.source_identifier, statement.source_locator) if x)
        restriction = (
            f"Restriction from {source}"
            + (f" ({where})" if where else "")
            + f': "{statement.restriction_text}" {TRANSCRIBED_LABEL}'
        )
    when = statement.stated_at.date().isoformat() if statement.stated_at else ""
    who = statement.stated_by_name or "the operator"
    met = (
        f'How it is met, as stated by {who} on {when}: "{statement.how_met}" '
        "(the operator's statement, not a compliance finding)."
    )
    return [restriction, met]


def earlier_version_statements(osp, kind, mid) -> list:
    """Current statements for this material recorded on ANOTHER plan version of the operation. A
    statement belongs to its plan version; on this one it is context to restate, never an answer
    (review of back #99)."""
    return list(
        PRS.objects.filter(
            osp__establishment_id=osp.establishment_id,
            material_kind=kind,
            material_id=mid,
            superseded_at__isnull=True,
        )
        .exclude(osp=osp)
        .select_related("osp")
        .order_by("stated_at", "id")
    )


def operator_how_met(osp, kind, mid) -> str:
    """How the operator states the material's restrictions are met, in the operator's own words: the
    current statements on this plan that are still in good standing, joined. "" when there are none.

    For a document that asks the operator the question itself (WSDA AGR 2196: "How you ensure this
    material meets any organic restrictions or requirements"). Never the regulation wording Trazo holds,
    nor a review note: those are Trazo's, and that column is the operator's (review of back #294).
    """
    if osp is None or not kind:
        return ""
    statements = PRS.objects.filter(osp=osp, material_kind=kind, material_id=mid, superseded_at__isnull=True).order_by(
        "stated_at", "id"
    )
    return "; ".join(
        s.how_met.strip() for s in statements if (s.how_met or "").strip() and statement_state(s, osp) == CURRENT
    )


def material_restriction_text(osp, kind, mid) -> str:
    """The printed restriction lines for one material on this plan: current statements, a held
    regulation restriction with no statement, or "restriction not documented"."""
    if osp is None or not kind:
        return NOT_DOCUMENTED
    statements = list(
        PRS.objects.filter(osp=osp, material_kind=kind, material_id=mid, superseded_at__isnull=True).order_by(
            "stated_at", "id"
        )
    )
    parts = []
    for statement in statements:
        lines = statement_lines(statement)
        if statement_state(statement, osp) == NEEDS_REVIEW:
            lines.append("[REVIEW] The material, its restriction or the plan has changed since this was stated.")
        parts.extend(lines)
    held = regulation_restriction(osp, kind, mid)
    if held is not None and not any(s.restriction_key == held["key"] for s in statements):
        parts.append(
            f"Restriction, {held['citation']} (regulation wording held by Trazo): \"{held['text']}\" "
            f"{APPLICABILITY_NOT_ESTABLISHED} How it is met: not stated."
        )
    wsda = wsda_list_restriction(osp, kind, mid)
    # Matched on the words too: a new WSDA edition keeps the key and rewords the annotation, and the
    # statement under [REVIEW] answers the old words, so the current ones print as not yet answered.
    if wsda is not None and not any(
        s.restriction_key == wsda["key"] and s.restriction_text == wsda["text"] for s in statements
    ):
        parts.append(
            f"{_wsda_source(wsda['citation'], wsda['effective_date'])}: \"{wsda['text']}\" How it is met: not stated."
        )
    if not statements:
        versions = sorted({s.osp.version_number for s in earlier_version_statements(osp, kind, mid)})
        if versions:
            listed = ", ".join(str(v) for v in versions)
            parts.append(
                f"[REVIEW] A restriction statement recorded on plan version {listed} is on file; "
                "it is not carried to this version until the operator states it again."
            )
    return " ".join(parts) if parts else NOT_DOCUMENTED


@transaction.atomic
def withdraw_statement(osp, user, data) -> PRS:
    """Withdraw a current statement entered by mistake (a mistyped restriction cannot be corrected by
    Replace, which keeps the restriction). Closed with the reason and who withdrew it; kept in the
    history; nothing replaces it."""
    try:
        statement_id = int(data.get("withdraw"))
    except (TypeError, ValueError):
        raise RestrictionError("Name the statement to withdraw.", field="withdraw")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise RestrictionError("Say why the statement is withdrawn.", field="reason")
    statement = PRS.objects.select_for_update().filter(pk=statement_id, osp=osp, superseded_at__isnull=True).first()
    if statement is None:
        raise RestrictionError("There is no current statement with that id on this plan.", status_code=404)
    who = user if getattr(user, "is_authenticated", False) else None
    name = ""
    if who is not None:
        name = (who.get_full_name() or "").strip() or (getattr(who, "email", "") or "")
    now = timezone.now()
    statement.superseded_at = now
    statement.withdrawn_at = now
    statement.withdrawal_reason = reason
    statement.withdrawn_by = who
    statement.withdrawn_by_name = name
    statement.save(
        update_fields=["superseded_at", "withdrawn_at", "withdrawal_reason", "withdrawn_by", "withdrawn_by_name"]
    )
    return statement


def withdrawn_statement_lines(osp) -> list:
    """One line per restriction statement withdrawn on this plan version, oldest first, for the packet
    (run 6c). A withdrawn statement documents nothing; the line says what it stated."""
    lines = []
    for st in PRS.objects.filter(osp=osp, withdrawn_at__isnull=False).order_by("withdrawn_at", "id"):
        stated = st.stated_at.date().isoformat() if st.stated_at else "date not recorded"
        regulation = st.restriction_source == PRS.SOURCE_REGULATION
        wsda = st.restriction_source == PRS.SOURCE_WSDA_LIST
        origin = (
            st.citation if regulation else f"WSDA annotation, {st.citation}" if wsda else "transcribed by the operator"
        )
        # The same qualifier `statement_lines` prints: withdrawn wording is still never a claim that it
        # applies, or that Trazo verified it (review of back #109).
        qualifier = APPLICABILITY_NOT_ESTABLISHED if regulation else f"({WSDA_WORDS}.)" if wsda else TRANSCRIBED_LABEL
        lines.append(
            f'Restriction statement for {st.material_name} ({origin}): "{st.restriction_text}" {qualifier} Stated by '
            f"{st.stated_by_name or 'the operator'} on {stated}; withdrawn on {st.withdrawn_at.date().isoformat()} "
            f"by {st.withdrawn_by_name or 'the operator'}, reason: \"{st.withdrawal_reason.rstrip('. ')}\". "
            "This statement no longer documents the restriction or how it is met."
        )
    return lines


def _statement_json(statement, osp) -> dict:
    return {
        "id": statement.pk,
        "material_kind": statement.material_kind,
        "material_id": statement.material_id,
        "material_name": statement.material_name,
        "restriction_source": statement.restriction_source,
        "restriction_text": statement.restriction_text,
        "citation": statement.citation,
        "source_type": statement.source_type,
        "source_identifier": statement.source_identifier,
        "source_locator": statement.source_locator,
        "source_reference": statement.source_reference,
        "attachment": statement.attachment_id,
        "how_met": statement.how_met,
        "stated_by_name": statement.stated_by_name,
        "stated_at": statement.stated_at.isoformat() if statement.stated_at else None,
        "plan_version": getattr(statement.osp, "version_number", None),
        "plan_id": statement.osp_id,
        "supersedes": statement.supersedes_id,
        "superseded_at": statement.superseded_at.isoformat() if statement.superseded_at else None,
        "withdrawn_at": statement.withdrawn_at.isoformat() if statement.withdrawn_at else None,
        "withdrawal_reason": statement.withdrawal_reason,
        "withdrawn_by_name": statement.withdrawn_by_name,
        "state": (
            statement_state(statement, osp)
            if statement.superseded_at is None
            else ("withdrawn" if statement.withdrawn_at else "superseded")
        ),
        "printed": statement_lines(statement),
    }


def restrictions_view(osp) -> list:
    out = []
    for kind, mid, name in plan_material_refs(osp):
        held = regulation_restriction(osp, kind, mid)
        wsda = wsda_list_restriction(osp, kind, mid)
        # This plan version only, matching `material_restriction_text` and the workbook (review of
        # back #99). Other versions' statements are listed apart, for review.
        history = list(PRS.objects.filter(osp=osp, material_kind=kind, material_id=mid).order_by("stated_at", "id"))
        out.append(
            {
                "material_kind": kind,
                "material_id": mid,
                "material_name": name,
                "regulation_restriction": (
                    {"key": held["key"], "text": held["text"], "citation": held["citation"]} if held else None
                ),
                # WSDA's annotation for the material's WSDA listing, with the list's edition date.
                "wsda_list_restriction": (
                    {
                        "key": wsda["key"],
                        "text": wsda["text"],
                        "citation": wsda["citation"],
                        "edition": wsda["effective_date"].isoformat() if wsda["effective_date"] else None,
                        "source_url": wsda["source_url"],
                    }
                    if wsda
                    else None
                ),
                "statements": [_statement_json(s, osp) for s in history if s.superseded_at is None],
                "history": [_statement_json(s, osp) for s in history],
                "earlier_versions": [_statement_json(s, osp) for s in earlier_version_statements(osp, kind, mid)],
                "printed": material_restriction_text(osp, kind, mid),
            }
        )
    return out
