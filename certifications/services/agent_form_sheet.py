"""
A copy sheet for the agent's own renewal form: every line of it, in its order, with what Trazo holds
to copy and what only the operator can answer.

The 02s supplement already routes every question of the agent's renewal form, but it is written for
the reviewer: register wording, one long crosswalk, inside the ZIP. The operator fills the agent's
form on their own, often on the agent's website, and needs the same facts in the form's order with
the values to copy beside them.

What this may and may not do (same red line as the plan itself, § 205.201(a)):
  * it names values Trazo holds for the operator to copy, each from a named record;
  * where Trazo can hold a value the operator has not given it (a Client ID, a contact), the row
    says so and names the field, so the operator fills it once and it is there next year;
  * it says plainly which questions are the operator's alone (an election, a commitment to the agent,
    a signature) and never pre-answers one: no box is ticked here;
  * it repeats the form's own instructions as notes, so nothing on the form is only on the form;
  * it reproduces none of the agent's form. Rows carry the form's step numbers and keys, and the
    client words them.

Only Oregon Tilth for now: its OSP Update Form (Rev. 2024/09/20) is mapped item by item in the
register, and `test_agent_form_sheet_and_sales_period` holds every line of the form to a row here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

#: Agents with a copy sheet. Kept apart from the Step 4 list on purpose: a copy sheet needs every
#: step of the agent's form mapped, not just one.
SHEET_AGENTS = frozenset({"otco"})

#: What a row asks of the operator.
#:   value         Trazo holds it: copy `value`.
#:   not_recorded  Trazo has a place for it and it is empty; `extra.edit` names the field when the
#:                 operator can fill it from the sheet.
#:   not_in_trazo  Trazo keeps no such record; `extra.where` says where the operator finds it.
#:   yours         the operator's election, commitment or signature on the agent's form.
#:   note          an instruction the agent's form gives; nothing to answer.
KINDS = ("value", "not_recorded", "not_in_trazo", "yours", "note")

#: The agent's own submission details, as its form prints them (OSP Update Form Rev. 2024/09/20,
#: header and Step 6; the renewal dates from tilth.org/certification/clients/renew, read
#: 2026-10-22). Facts about the agent, not about the operation, so they are not in the register.
SUBMISSION = {
    "otco": {
        "renewal_dates": ["01-01", "04-01"],
        "online_url": "https://tilth.org/renew",
        "fee_schedule_url": "https://tilth.org/feeschedule",
        "fee_schedule_url_es": "https://esp.tilth.org/certificacion/tarifas-de-certificacion/",
        "email": "organic@tilth.org",
        "mail": "Oregon Tilth, PO Box 368, Corvallis, OR 97339",
        "forms_url": "https://tilth.org/certification",
        "forms_url_es": "https://esp.tilth.org/certificacion/formatos/",
        "osp_portal_url": "https://myotco.org/Login.aspx",
        "phone": "(503) 378-0690",
    }
}


#: Every item of the agent's form, by its register inventory ref, and the sheet rows that answer it.
#: `test_every_line_of_the_form_has_a_row` holds this to `otco/inventory/OSP-Update-Form.yaml` in
#: both directions, so a revised form with a new item fails until the sheet has a row for it.
#: "header" is the form's own preamble, which the inventory does not list as an item.
FORM_ITEM_ROWS = {
    "otco": {
        "header": ("renewal_deadline", "submit_with_fees"),
        "Step 1 (business name, client ID, DBA)": ("business_name", "client_id", "dba"),
        "Step 1 (primary contact)": ("contact_name", "contact_email", "contact_phone"),
        "Step 1 (public contact)": ("public_email", "public_phone"),
        "Step 1 (contact change form)": ("contact_change_form",),
        "Step 2 (continue or withdraw)": ("continue_or_withdraw",),
        "Step 3 (services)": ("services", "international_addendum"),
        "Step 3 (scopes)": ("scopes",),
        "Step 3 (production partners)": ("production_partners",),
        "Step 4 (OSP updates and changes)": ("osp_changes", "notices_sent", "new_land", "submit_changes_early"),
        "5-1": ("attest_true",),
        "5-2": ("authority_to_bind",),
        "5-3": ("agent_manuals",),
        "5-4": ("standards_and_policies",),
        "5-5": ("terms_and_conditions",),
        "Step 5 (electronic signature consent)": ("electronic_signature",),
        "Step 5 (signature, date, title)": ("signature",),
        "Step 6 (gross organic sales and period)": ("gross_sales", "sales_period"),
        "Step 6 (payment included)": ("payment",),
        "Step 6 (billing contact)": ("billing_contact",),
        "Step 6 (comments)": ("comments",),
    }
}


@dataclass(frozen=True)
class SheetRow:
    step: str
    item: str
    kind: str
    value: object = None
    #: Where the value comes from, for the operator to check it: "company", "establishment", "plan",
    #: "plan_author", "filing", "sales_records", "parcels", "notices".
    source: str = ""
    extra: dict = field(default_factory=dict)


def _edit(target: str, field_name: str, **more) -> dict:
    """The field the operator can fill from the sheet: `target` is "establishment" or "company"."""
    return {"edit": {"target": target, "field": field_name, **more}}


def _value_or_edit(step, item, value, source, target, field_name, **extra) -> SheetRow:
    if value not in (None, "", [], {}):
        return SheetRow(step, item, "value", value, source, extra)
    return SheetRow(step, item, "not_recorded", None, "", {**extra, **_edit(target, field_name)})


def _scopes(osp) -> list[dict]:
    """The scopes the operator ticked on the operation profile, with both languages' labels."""
    from certifications.osp_modules import MODULES_BY_KEY

    module = MODULES_BY_KEY.get("certification_contract")
    answers = (((osp.module_responses or {}).get("modules") or {}).get("certification_contract") or {}).get(
        "answers"
    ) or {}
    picked = (answers.get("contract_scopes") or {}).get("value") or []
    if not module or not picked:
        return []
    options = {}
    for page in module.pages:
        for question in page.questions:
            if question.key == "contract_scopes":
                options = {o.value: dict(o.label) for o in question.options}
    return [{"key": key, "label": options.get(key, {"en": key, "es": key})} for key in picked]


def _renewal_form(agent: str) -> dict:
    """The agent's renewal application as the register names it, or blanks if the register is unreadable."""
    from certifications.services.packet_coverage import _load_forms

    forms, _loaded = _load_forms(agent)
    form = next((f for f in forms if f.renewal_role == "annual_renewal"), None)
    if form is None:
        return {"title": "", "document_id": "", "revision": "", "url": ""}
    return {"title": form.title, "document_id": form.document_id, "revision": form.revision, "url": form.url}


def _notices_since(osp, since) -> list[dict]:
    """The § 205.400(f) notices on file for this plan's lineage, dated on or after `since`."""
    from certifications.services.osp_module_pdf import lineage_change_notifications

    rows = []
    for notice in lineage_change_notifications(osp):
        if since is not None and notice.date_notified and notice.date_notified < since:
            continue
        rows.append(
            {
                "date": notice.date_notified.isoformat() if notice.date_notified else None,
                "category": notice.change_category,
                "category_label": notice.get_change_category_display(),
            }
        )
    return rows


def agent_form_sheet(osp) -> dict | None:
    """The copy sheet for this plan's agent, or None when Trazo has none for that agent."""
    from certifications.services.annual_update_filing import renewal_packet_filing
    from certifications.services.osp_module_pdf import _renewal_context
    from certifications.services.packet_coverage import changed_sections, packet_agent, packet_certifier
    from certifications.services.plan_version_changes import plan_reference_date
    from certifications.services.renewal_sales import organic_sales_subtotal

    agent, own = packet_certifier(osp)
    if not own or agent not in SHEET_AGENTS:
        return None
    est = osp.establishment
    company = getattr(est, "company", None)
    # The same responsible person, address and phone the packet's cover prints, so the sheet and
    # 00-cover cannot name two different people for one operation.
    ctx = _renewal_context(osp)
    filing = ctx["filing"] or renewal_packet_filing(osp)
    submission = SUBMISSION[agent]
    email = est.contact_email or est.email or getattr(company, "contact_email", None) or ""
    client_id = est.certifier_client_id if est.certifier_client_id_agent == agent else ""

    rows = [
        # Header: "submit this completed form AND your certification fees ... before your established
        # renewal deadline date".
        SheetRow("0", "renewal_deadline", "not_in_trazo", extra={"where": "agent_letters", **submission}),
        SheetRow("0", "submit_with_fees", "note", extra=submission),
        # Step 1
        _value_or_edit("1", "business_name", getattr(company, "name", "") or "", "company", "company", "name"),
        (
            SheetRow(
                "1",
                "client_id",
                "value",
                client_id,
                "establishment",
                _edit("establishment", "certifier_client_id", agent=agent),
            )
            if client_id
            else SheetRow(
                "1",
                "client_id",
                "not_recorded",
                extra={
                    "where": "agent_certificate_and_letters",
                    **_edit("establishment", "certifier_client_id", agent=agent),
                },
            )
        ),
        _value_or_edit("1", "dba", getattr(company, "tradename", "") or "", "company", "company", "tradename"),
        _value_or_edit(
            "1",
            "contact_name",
            ctx["responsible_person"],
            "establishment" if ctx["responsible_person_is_named"] else "plan_author",
            "establishment",
            "contact_person",
        ),
        _value_or_edit("1", "contact_email", email, "establishment", "establishment", "contact_email"),
        _value_or_edit("1", "contact_phone", ctx["phone"], "establishment", "establishment", "contact_phone"),
        SheetRow("1", "public_email", "yours", extra={"same_as_above": bool(email)}),
        SheetRow("1", "public_phone", "yours", extra={"same_as_above": bool(ctx["phone"])}),
        SheetRow(
            "1",
            "contact_change_form",
            "note",
            extra={
                "application_info_changes": bool(filing and (filing.application_info_changes or "").strip()),
                **submission,
            },
        ),
        # Step 2
        SheetRow("2", "continue_or_withdraw", "yours"),
        # Step 3
        SheetRow("3", "services", "yours"),
        SheetRow("3", "international_addendum", "note"),
        (
            SheetRow("3", "scopes", "value", _scopes(osp), "plan")
            if _scopes(osp)
            else SheetRow("3", "scopes", "not_recorded", extra={"where": "operation_profile"})
        ),
        SheetRow("3", "production_partners", "yours"),
    ]
    step4 = changed_sections(osp)
    if step4 is None or step4.state != "compared":
        rows.append(
            SheetRow(
                "4",
                "osp_changes",
                "yours",
                extra={
                    "state": step4.state if step4 else "no_filing",
                    "prior_version": step4.prior_version if step4 else None,
                    "new_version": step4.new_version if step4 else None,
                },
            )
        )
        since = plan_reference_date(filing.prior_osp)[0] if filing else None
    else:
        sections = [{"label": label, "files": list(files)} for label, files in step4.forms]
        sections += [{"label": label, "files": [path]} for label, path in step4.unmapped + step4.narratives]
        rows.append(
            SheetRow(
                "4",
                "osp_changes",
                "value",
                sections,
                "plan",
                {"prior_version": step4.prior_version, "new_version": step4.new_version},
            )
        )
        since = step4.since
    # The form's first Step 4 option ends "OR: I have already provided OTCO with information regarding
    # changes". The notices already sent are on file, so they are listed.
    notices = _notices_since(osp, since)
    rows.append(
        SheetRow(
            "4",
            "notices_sent",
            "value" if notices else "not_recorded",
            notices or None,
            "notices",
            {"since": since.isoformat() if since else None},
        )
    )
    if step4 is not None and step4.state == "compared":
        rows.append(
            SheetRow(
                "4",
                "new_land",
                "value" if step4.parcels_begun else "not_recorded",
                list(step4.parcels_begun) or None,
                "parcels",
                {
                    "since": step4.since.isoformat() if step4.since else None,
                    "since_basis": step4.since_basis,
                    "unstated": list(step4.parcels_unstated),
                    "parcel_forms": list(step4.parcel_forms),
                },
            )
        )
    else:
        # The row is always there: the form names new land whatever the comparison could do. Without
        # a second plan version there is no date to count from (review of back #218).
        rows.append(
            SheetRow(
                "4",
                "new_land",
                "not_recorded",
                extra={"reason": step4.state if step4 else "no_filing"},
            )
        )
    rows.append(SheetRow("4", "submit_changes_early", "note", extra=submission))

    # Step 5: each statement the operator makes on the agent's form, as the form numbers them.
    rows += [
        SheetRow("5", "attest_true", "yours"),
        SheetRow("5", "authority_to_bind", "yours"),
        SheetRow("5", "agent_manuals", "yours"),
        SheetRow("5", "standards_and_policies", "yours"),
        SheetRow("5", "terms_and_conditions", "yours"),
        SheetRow("5", "electronic_signature", "yours"),
    ]
    signer_name = (getattr(filing, "signer_name", "") or "").strip() if filing else ""
    signer_title = (getattr(filing, "signer_title", "") or "").strip() if filing else ""
    if signer_name:
        rows.append(SheetRow("5", "signature", "value", {"name": signer_name, "title": signer_title}, "filing"))
    else:
        rows.append(SheetRow("5", "signature", "yours", extra={"suggested_name": ctx["responsible_person"] or None}))

    # Step 6
    if filing is None:
        rows.append(SheetRow("6", "gross_sales", "not_recorded", extra={"reason": "no_filing"}))
        rows.append(SheetRow("6", "sales_period", "not_recorded", extra={"where": "annual_update"}))
    else:
        sales = organic_sales_subtotal(est, filing)
        rows.append(
            SheetRow(
                "6",
                "gross_sales",
                "value" if sales.complete else "not_recorded",
                str(sales.total) if sales.complete else None,
                "sales_records",
                {
                    "period_start": sales.start.isoformat(),
                    "period_end": sales.end.isoformat(),
                    "period_stated": sales.stated,
                    "n_sales": sales.n_sales,
                    "n_unpriced": sales.n_sales - sales.n_priced,
                },
            )
        )
        rows.append(
            SheetRow(
                "6",
                "sales_period",
                "value" if sales.stated else "not_recorded",
                {"start": sales.start.isoformat(), "end": sales.end.isoformat()} if sales.stated else None,
                "filing" if sales.stated else "",
                {} if sales.stated else {"where": "annual_update"},
            )
        )
    rows += [
        SheetRow("6", "payment", "yours", extra=submission),
        SheetRow("6", "billing_contact", "yours", extra={"same_as_above": bool(ctx["responsible_person"])}),
        SheetRow("6", "comments", "yours"),
    ]

    return {
        "agent": agent,
        "agent_name": packet_agent(osp).name or agent.upper(),
        "form": _renewal_form(agent),
        "plan_version": osp.version_number,
        "filing_id": getattr(filing, "id", None),
        "establishment_id": est.id,
        "company_id": getattr(company, "id", None),
        "rows": [asdict(row) for row in rows],
    }
