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

Oregon Tilth (OSP Update Form, Rev. 2024/09/20), CCOF (Annual Renewal Contract, and the Crop Update
ORGB88 when crops change) and WSDA (Renewal Fee Form AGR 2521, and Site Update Information AGR 2516):
each form is mapped item by item in the register, and `test_agent_form_sheet_and_sales_period` holds
every line of every form to a row here, both ways.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

from certifications.certifying_agents import agent_by_slug

#: Agents with a copy sheet. Kept apart from the Step 4 list on purpose: a copy sheet needs every
#: step of the agent's form mapped, not just one.
SHEET_AGENTS = frozenset({"otco", "ccof", "wsda"})

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
        # The registry's own dates, so the two cannot disagree.
        "renewal_dates": list(agent_by_slug("otco").renewal_dates),
        "online_url": "https://tilth.org/renew",
        "fee_schedule_url": "https://tilth.org/feeschedule",
        "fee_schedule_url_es": "https://esp.tilth.org/certificacion/tarifas-de-certificacion/",
        "email": "organic@tilth.org",
        "mail": "Oregon Tilth, PO Box 368, Corvallis, OR 97339",
        "forms_url": "https://tilth.org/certification",
        "forms_url_es": "https://esp.tilth.org/certificacion/formatos/",
        "osp_portal_url": "https://myotco.org/Login.aspx",
        "phone": "(503) 378-0690",
    },
    # The Annual Renewal Contract's own page (ccof.org/payments) and the 2027 renewal notice
    # (ccof.org/news/ccof-annual-certification-renewal-2027), read 2026-11-04: "complete the short
    # renewal contract and pay your annual certification fee by January 1 either online
    # (www.ccof.org/renew), through MyCCOF, by mail, or by phone"; "February 15: Last day to withdraw
    # from certification without accruing 2027 certification fees. An overdue notice and $150 late fee
    # may be issued". The Program Manual (October 2026): "Updates must be approved prior to
    # implementation."
    "ccof": {
        "due": "01-01",
        "withdraw_by": "02-15",
        "late_fee": "150",
        "online_url": "https://www.ccof.org/renew",
        "portal": "MyCCOF",
        "osp_update_email": "inbox@ccof.org",
        "mail": "CCOF, 877 Cedar Street, Suite 248, Santa Cruz, CA 95060",
        "phone": "(831) 423-2263",
    },
    # AGR 2521 (R 05/26) and AGR 2516 (R 01/20) as published, read 2026-11-04: "A renewal fee is due
    # with your renewal application by March 1"; "Late fee ($100 for each month after March 1)"; "You
    # are encouraged to submit your application packet and forms by email to organic@agr.wa.gov;
    # however your fee form and check must be sent hardcopy. Make checks payable to: WSDA Organic
    # Program, PO Box 42591 (US mail), 1111 Washington St SE (Private courier), Olympia, WA 98504-2560".
    # WSDA sends the renewal application and fee form itself, and the fee form it sends is not
    # always the published edition (WSDA, 2026-10-26).
    "wsda": {
        "due": "03-01",
        "late_fee_per_month": "100",
        "email": "organic@agr.wa.gov",
        "check_payable_to": "WSDA Organic Program",
        "mail": "PO Box 42591, Olympia, WA 98504-2560",
        "courier": "1111 Washington St SE, Olympia, WA 98504-2560",
        "phone": "(360) 902-1805",
        "url": "https://agr.wa.gov/organic",
    },
}


#: Every item of each of the agent's forms, by its register inventory ref, and the sheet rows that
#: answer it, by the form's file stem. `test_every_line_of_the_form_has_a_row` holds this to each
#: `<agent>/inventory/<stem>.yaml` in both directions, so a revised form with a new item fails until
#: the sheet has a row for it. "header" is the form's own preamble, which the inventory does not list
#: as an item. Several refs may share a row: CCOF's eight contract terms are one agreement, accepted
#: once.
FORM_ITEM_ROWS = {
    "otco": {
        "OSP-Update-Form": {
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
        },
    },
    "ccof": {
        "Annual-Renewal-Contract": {
            "header": ("ccof_due", "ccof_changes_approved_first"),
            "Step 1: Request Renewal": ("ccof_continue_or_surrender",),
            "Step 2: OSP Update Information": ("ccof_osp_update",),
            "Operation Name": ("operation_name",),
            "Client Code": ("client_code",),
            "Name": ("submitter_name",),
            "Email": ("submitter_email",),
            "Please enter any comments or questions": ("comments",),
            "Date I No Longer Need Certification (Surrender Request Date)": ("surrender_date",),
            "Reason for surrender": ("surrender_reason",),
            "1": ("ccof_terms",),
            "2": ("ccof_terms",),
            "3": ("ccof_terms",),
            "4": ("ccof_terms",),
            "5": ("ccof_terms",),
            "6": ("ccof_terms",),
            "7": ("ccof_terms",),
            "8": ("ccof_terms",),
            "CCOF's Terms of Use and Privacy Policy": ("ccof_accept_terms",),
            "Note (new certificates)": ("ccof_new_certificates",),
        },
        "Crop-Update-ORGB88": {
            "Instructions (each certified parcel)": ("crop_update_when",),
            "Instructions (Client Profile Addendum)": ("crop_update_when",),
            "Instructions (only listed crops)": ("crop_update_when",),
            "Instructions (Excel version)": ("crop_update_when",),
            "Operation Name": ("crop_update_operation_name",),
            "Date": ("crop_update_date",),
            "Table (CCOF Parcel #, crops, acres)": ("crop_update_parcels",),
        },
    },
    "wsda": {
        "2521-renewal-fee": {
            "header": ("wsda_due", "wsda_send"),
            "Header (business, contact, certificate)": (
                "business_name",
                "contact_name",
                "contact_email",
                "cert_no",
                "contact_phone",
            ),
            "1": ("wsda_gross_income",),
            "2": ("wsda_renewal_fee",),
            "3": ("wsda_late_fee",),
            "4": ("wsda_how_sent",),
            "4a": ("wsda_sent_date",),
        },
        "2516-site-update": {
            "Instructions (changes per site)": ("site_changes",),
            "Table (site, name, changes)": ("site_changes",),
            "Instructions (acreage removed)": ("acreage_removed",),
        },
    },
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


def _form_meta(agent: str, stem: str) -> dict:
    """One of the agent's forms as the register names it, by file stem; blanks if unreadable.

    A form the agent sends with its renewal names no edition: the copy it sends is not always the
    one it published (WSDA, 2026-10-26), the same rule the renewal supplement keeps.
    """
    from certifications.services.packet_coverage import _load_forms

    forms, _loaded = _load_forms(agent)
    form = next((f for f in forms if f.path.stem == stem), None)
    if form is None:
        return {"title": "", "document_id": "", "revision": "", "url": "", "stem": stem, "sent_with_renewal": False}
    return {
        "title": form.title,
        "document_id": form.document_id,
        "revision": "" if form.sent_with_renewal else form.revision,
        "url": form.url,
        "stem": stem,
        # The app labels the link as an earlier published copy, so the operator fills in the one the
        # agent sent, as 02s already says (review of #282).
        "sent_with_renewal": bool(form.sent_with_renewal),
    }


def _contact_name_row(step, ctx) -> SheetRow:
    return _value_or_edit(
        step,
        "contact_name",
        ctx["responsible_person"],
        "establishment" if ctx["responsible_person_is_named"] else "plan_author",
        "establishment",
        "contact_person",
    )


def _land_rows(osp) -> tuple[list[dict], list]:
    """The parcels the agent's crop or site update asks about (`renewal_land_table`), and the ones
    filed elsewhere with the reason."""
    from certifications.services.renewal_land_table import land_table

    table = land_table(osp)
    if table is None:
        return [], []
    rows = [
        {
            "number": row.number,
            "name": row.name,
            "acres": round(row.acres, 2) if row.acres else None,
            "planned": row.planned,
            "crops": [{"year": year, "text": text} for year, text in row.crops],
        }
        for row in table.rows
    ]
    return rows, [list(pair) for pair in table.excluded]


def _ccof_rows(osp, filing, ctx, submission, company, client_id) -> list[SheetRow]:
    """CCOF's Annual Renewal Contract (its web form, gform_5) and, when crops change, the Crop Update."""
    signer = (getattr(filing, "signer_name", "") or "").strip() if filing else ""
    name = getattr(company, "name", "") or ""
    parcels, excluded = _land_rows(osp)
    rows = [
        SheetRow("0", "ccof_due", "note", extra=submission),
        SheetRow("0", "ccof_changes_approved_first", "note", extra=submission),
        SheetRow("1", "ccof_continue_or_surrender", "yours", extra=submission),
        # The form's two-way election, with CCOF's own consequence: "If this contract is submitted and
        # no updates are indicated CCOF will assume that no changes have occurred". What the year's
        # filing records is shown beside it; the box is the operator's.
        SheetRow(
            "2",
            "ccof_osp_update",
            "yours",
            extra={
                "has_filing": filing is not None,
                "additions": len(filing.additions or []) if filing else 0,
                "deletions": len(filing.deletions or []) if filing else 0,
                "application_info_changes": bool(filing and (filing.application_info_changes or "").strip()),
                **submission,
            },
        ),
        _value_or_edit("details", "operation_name", name, "company", "company", "name"),
        (
            SheetRow(
                "details",
                "client_code",
                "value",
                client_id,
                "establishment",
                _edit("establishment", "certifier_client_id", agent="ccof"),
            )
            if client_id
            else SheetRow(
                "details",
                "client_code",
                "not_recorded",
                extra={
                    "where": "agent_certificate_and_letters",
                    **_edit("establishment", "certifier_client_id", agent="ccof"),
                },
            )
        ),
        # The person submitting the contract: the year's signer when there is one, else the person
        # the cover names.
        (
            SheetRow("details", "submitter_name", "value", signer, "filing")
            if signer
            else _contact_name_row("details", ctx)
        ),
        _value_or_edit("details", "submitter_email", ctx["email"], "establishment", "establishment", "contact_email"),
        SheetRow("details", "comments", "yours"),
        SheetRow("details", "surrender_date", "yours"),
        SheetRow("details", "surrender_reason", "yours"),
        SheetRow("terms", "ccof_terms", "yours"),
        SheetRow("terms", "ccof_accept_terms", "yours"),
        SheetRow("terms", "ccof_new_certificates", "note"),
        SheetRow("orgb88", "crop_update_when", "note", extra=submission),
        _value_or_edit("orgb88", "crop_update_operation_name", name, "company", "company", "name"),
        SheetRow("orgb88", "crop_update_date", "yours"),
        SheetRow(
            "orgb88",
            "crop_update_parcels",
            "value" if parcels else "not_recorded",
            parcels or None,
            "parcels",
            {"excluded": excluded},
        ),
    ]
    # `submitter_name` from the cover's person carries that row's own item key.
    return [replace(row, item="submitter_name") if row.item == "contact_name" else row for row in rows]


def _wsda_rows(osp, filing, ctx, submission, company) -> list[SheetRow]:
    """WSDA's Renewal Fee Form (AGR 2521) and Site Update Information (AGR 2516). The renewal
    application itself WSDA sends and does not publish, so it has no rows."""
    from datetime import date

    from certifications.certifying_agents import agent_for_name
    from certifications.services.operation_certificate import certificate_of_record
    from certifications.services.renewal_sales import organic_sales_between

    est = osp.establishment
    certificate = certificate_of_record(est.id)
    held = agent_for_name(certificate.agent)
    cert_no = certificate.number if certificate.number and held is not None and held.slug == "wsda" else ""
    contact_phone = (getattr(est, "contact_phone", "") or "").strip() or ctx["phone"]
    parcels, excluded = _land_rows(osp)

    # Item 1 is "Gross annual income received in the last calendar year": money received, from the
    # operation's books. Trazo's subtotal is sales DATED in that year, so it is shown as a cross-check
    # beside the line the operator fills, never as the figure (renewal audit, 2026-11-04).
    if filing is None:
        income = SheetRow("2521", "wsda_gross_income", "yours", extra={"reason": "no_filing"})
    else:
        year = filing.reporting_year - 1
        sales = organic_sales_between(est, date(year, 1, 1), date(year, 12, 31))
        income = SheetRow(
            "2521",
            "wsda_gross_income",
            "yours",
            extra={
                "year": year,
                "subtotal": str(sales.total) if sales.complete else None,
                "n_sales": sales.n_sales,
                "n_unpriced": sales.n_sales - sales.n_priced,
                **({"reason": "period_not_over"} if sales.running else {}),
            },
        )
    return [
        SheetRow("0", "wsda_due", "note", extra=submission),
        SheetRow("0", "wsda_send", "note", extra=submission),
        _value_or_edit("2521", "business_name", getattr(company, "name", "") or "", "company", "company", "name"),
        _contact_name_row("2521", ctx),
        _value_or_edit("2521", "contact_email", ctx["email"], "establishment", "establishment", "contact_email"),
        (
            SheetRow("2521", "cert_no", "value", cert_no, "certificate")
            if cert_no
            else SheetRow("2521", "cert_no", "not_recorded", extra={"where": "agent_certificate"})
        ),
        _value_or_edit("2521", "contact_phone", contact_phone, "establishment", "establishment", "contact_phone"),
        income,
        SheetRow("2521", "wsda_renewal_fee", "yours"),
        SheetRow("2521", "wsda_late_fee", "yours", extra=submission),
        SheetRow("2521", "wsda_how_sent", "yours", extra=submission),
        SheetRow("2521", "wsda_sent_date", "yours"),
        SheetRow(
            "2516",
            "site_changes",
            "value" if parcels else "not_recorded",
            parcels or None,
            "parcels",
            {"excluded": excluded},
        ),
        SheetRow("2516", "acreage_removed", "note"),
    ]


def agent_form_sheet(osp) -> dict | None:
    """The copy sheet for this plan's agent, or None when Trazo has none for that agent."""
    from certifications.services.annual_update_filing import renewal_packet_filing
    from certifications.services.osp_module_pdf import _renewal_context
    from certifications.services.packet_coverage import changed_sections, packet_certifier
    from certifications.services.plan_version_changes import plan_reference_date
    from certifications.services.renewal_sales import agent_sales_period, organic_sales_subtotal

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
    email = ctx["email"]
    contact_phone = (getattr(est, "contact_phone", "") or "").strip() or ctx["phone"]
    client_id = est.certifier_client_id if est.certifier_client_id_agent == agent else ""
    if agent in ("ccof", "wsda"):
        stems = list(FORM_ITEM_ROWS[agent])
        rows = (
            _ccof_rows(osp, filing, ctx, submission, company, client_id)
            if agent == "ccof"
            else _wsda_rows(osp, filing, ctx, submission, company)
        )
        return _sheet(osp, agent, [_form_meta(agent, stem) for stem in stems], filing, rows)
    # The renewal date this agent assigned the operation, recorded from its letters; never inferred.
    renewal_date = est.certifier_renewal_date if est.certifier_renewal_date_agent == agent else ""
    renewal_edit = _edit(
        "establishment", "certifier_renewal_date", agent=agent, options=list(submission["renewal_dates"])
    )

    rows = [
        # Header: "submit this completed form AND your certification fees ... before your established
        # renewal deadline date".
        # Which of the agent's dates is this operation's decides the 12 months of sales it asks for
        # (Step 6), so Trazo keeps it once the operator records it (2026-11-04).
        (
            SheetRow("0", "renewal_deadline", "value", renewal_date, "establishment", {**submission, **renewal_edit})
            if renewal_date
            else SheetRow(
                "0", "renewal_deadline", "not_recorded", extra={"where": "agent_letters", **submission, **renewal_edit}
            )
        ),
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
        # OTCO asks the PRIMARY CONTACT's phone. The cover's "Phone" is the operation's main phone
        # (`Establishment.phone` first), which need not be the contact's, so this row reads the
        # contact's own number first (renewal audit, 2026-11-04).
        _value_or_edit("1", "contact_phone", contact_phone, "establishment", "establishment", "contact_phone"),
        SheetRow("1", "public_email", "yours", extra={"same_as_above": bool(email)}),
        SheetRow("1", "public_phone", "yours", extra={"same_as_above": bool(contact_phone)}),
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
        published = agent_sales_period(agent, renewal_date, filing.reporting_year) if renewal_date else None
        published_extra = (
            {
                "published_start": published[0].isoformat(),
                "published_end": published[1].isoformat(),
                "renewal_date": renewal_date,
            }
            if published
            else {}
        )
        if not sales.stated and published != (sales.start, sales.end):
            # The agent asks for its own 12 months, which for a January 1 renewal run October to
            # September. The calendar year the filing falls back to is the wrong period for that
            # cohort, or an unknown one while no renewal date is recorded, so no figure is offered
            # until the operator sets the period. For an April 1 renewal the fallback IS the agent's
            # period, and its figure is given (review of #281).
            rows.append(
                SheetRow(
                    "6",
                    "gross_sales",
                    "not_recorded",
                    None,
                    "sales_records",
                    {"reason": "period_not_stated", **published_extra},
                )
            )
        else:
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
                        **published_extra,
                        **({"reason": "period_not_over", "as_of": sales.as_of.isoformat()} if sales.running else {}),
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
                {**published_extra} if sales.stated else {"where": "annual_update", **published_extra},
            )
        )
    rows += [
        SheetRow("6", "payment", "yours", extra=submission),
        SheetRow("6", "billing_contact", "yours", extra={"same_as_above": bool(ctx["responsible_person"])}),
        SheetRow("6", "comments", "yours"),
    ]

    return _sheet(osp, agent, [_form_meta(agent, stem) for stem in FORM_ITEM_ROWS[agent]], filing, rows)


def _sheet(osp, agent, forms, filing, rows) -> dict:
    from certifications.services.packet_coverage import packet_agent

    est = osp.establishment
    return {
        "agent": agent,
        "agent_name": packet_agent(osp).name or agent.upper(),
        # The first form is the one the sheet is named after; `forms` lists every form it covers.
        "form": forms[0],
        "forms": forms,
        "plan_version": osp.version_number,
        "filing_id": getattr(filing, "id", None),
        "establishment_id": est.id,
        "company_id": getattr(getattr(est, "company", None), "id", None),
        "rows": [asdict(row) for row in rows],
    }
