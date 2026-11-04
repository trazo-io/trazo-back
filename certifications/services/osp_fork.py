"""Open next year's plan as a draft copy of this one.

Moved out of `OrganicSystemPlanViewSet.new_version` (2026-10-01) so the demo seeder forks a plan
through the same code the operator's "start next version" button runs. A seeder that cloned the
plan its own way would demonstrate a renewal the product does not perform.
"""

from __future__ import annotations

from django.db import transaction


def fork_plan(source, user):
    """Clone `source` into a new draft with version_number = max + 1 and return it."""
    from certifications.models import OrganicSystemPlan
    from certifications.services.common_osp_records import mark_carried_forward

    with transaction.atomic():
        last = (
            OrganicSystemPlan.objects.select_for_update()
            .filter(establishment=source.establishment)
            .order_by("-version_number")
            .first()
        )
        next_version = (last.version_number + 1) if last else 1
        clone = OrganicSystemPlan.objects.create(
            establishment=source.establishment,
            certification=source.certification,
            version_number=next_version,
            previous_version=source,
            status="draft",
            # § 11 confirmations ride inside `sections`, so a verbatim clone re-dated last
            # year's attestation as this year's. `mark_carried_forward` keeps the answers
            # (the operator did make them) and marks them carried until re-stated — see the
            # service docstring. It also deep-copies, which `sections=source.sections` did
            # not: both rows held the SAME dict object.
            sections=mark_carried_forward(source.sections, source.version_number),
            # Next season starts guided from last year's answers (Appendix A §h.5).
            module_responses=source.module_responses,
            certifier_template_name=source.certifier_template_name,
            certifier_template_url=source.certifier_template_url,
            # Next year's plan goes to the same agent unless the operator says otherwise.
            certifier_name=source.certifier_name,
            created_by=user,
        )
        # 2026-08-21 — the clone copied `sections` and `module_responses` and stopped
        # there, so the approved-inputs registry did NOT come across: v2 opened with an
        # empty materials list while v1 held eight verified entries. The dialog promises
        # "copies every answer across", and the registry is an answer — the operator
        # searched each product against OMRI / WSDA / the National List and accepted the
        # match. Losing it is worse than an inconvenience: the § 205.201(a)(2) narrative is
        # compiled from this list, the audit dossier reports "No approved-inputs list is on
        # file for this operation" against a plan that had one, and an operator who submits
        # the new version has filed a plan with no materials list at all — a § 205.201(a)(2)
        # deficiency the tool created. Found on a pilot renewal: v1 4 OMRI / 2 National List
        # / 2 WSDA, v2 zero of each.
        #
        # M2M, so this must happen after create(). The change log is deliberately NOT
        # copied: it is the audit trail of edits made to THAT version (§ 205.400(f)(1)),
        # and the new version starts its own.
        clone.approved_national_list_substances.set(source.approved_national_list_substances.all())
        clone.approved_omri_products.set(source.approved_omri_products.all())
        clone.approved_wsda_materials.set(source.approved_wsda_materials.all())
        # 2026-09-07 — the fourth source, missed when it shipped a week after the fix
        # above. `PlanMaterialEntry` holds exactly the materials no catalog can supply
        # (CCOF ORGB41 §A: compost, manure, gypsum, limestone), so a renewal cloned from
        # last year's plan lost precisely the rows the operator had to type by hand — the
        # ones hardest to notice missing and most laborious to re-enter.
        #
        # Rows, not an M2M: each is copied rather than shared, so editing next year's plan
        # cannot rewrite what was filed last year. `id`/`osp` are dropped and everything
        # else — including the catalog FKs and `certifier_letter_reference` a basis depends
        # on — travels, or `listing_statement` would come out saying less than it should.
        from certifications.models import PlanMaterialEntry

        carried = []
        for entry in source.plan_material_entries.all():
            carried.append(
                PlanMaterialEntry(
                    osp=clone,
                    product_name=entry.product_name,
                    manufacturer=entry.manufacturer,
                    category=entry.category,
                    reason_for_use=entry.reason_for_use,
                    status=entry.status,
                    listing_basis=entry.listing_basis,
                    omri_product=entry.omri_product,
                    wsda_material=entry.wsda_material,
                    national_list_substance=entry.national_list_substance,
                    certifier_letter_reference=entry.certifier_letter_reference,
                    notes=entry.notes,
                    # The agent's review travels: last year's approved list is what WSDA's
                    # "approved for them in the previous year" and CCOF's additions and removals
                    # are measured against.
                    agent_review=entry.agent_review,
                    agent_review_date=entry.agent_review_date,
                    agent_review_reference=entry.agent_review_reference,
                    agent_review_agent=entry.agent_review_agent,
                    agent_review_use=entry.agent_review_use,
                    # The person filing THIS version, not the original author — the row is
                    # genuinely created today, and attributing it to whoever typed it last
                    # year would put a false name on a new record.
                    created_by=user,
                )
            )
        if carried:
            PlanMaterialEntry.objects.bulk_create(carried)
        # 2026-09-07 — the fifth thing the clone forgot, and the one that emptied a
        # document: the § 205.406(a) filing this renewal is being made under. See
        # `certifications/services/annual_update_linking.py` for the invariant and for the
        # other half of it, which runs when the filing is written after the fork.
        from certifications.services.annual_update_linking import carry_open_filing

        carry_open_filing(source, clone)
    return clone
