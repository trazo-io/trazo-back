"""
A copy sheet for the agent's own renewal form: what Trazo holds to copy, and what only the operator
can answer.

The 02s supplement already routes every question of the agent's renewal form, but it is written for
the reviewer: register wording, one long crosswalk, inside the ZIP. The operator fills the agent's
form on their own, often on the agent's website, and needs the same facts in the form's order with
the values to copy beside them.

What this may and may not do (same red line as the plan itself, § 205.201(a)):
  * it names values Trazo holds for the operator to copy, each from a named record;
  * it says plainly which questions are the operator's alone (an election, a commitment to the agent,
    a signature) and never pre-answers one: no box is ticked here;
  * it reproduces none of the agent's form. Rows carry the form's step numbers and keys, and the
    client words them.

Only Oregon Tilth for now: its OSP Update Form (Rev. 2024/09/20) is mapped item by item in the
register. Rows are machine keys, so the client renders them in the operator's language.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

#: Agents with a copy sheet. Kept apart from the Step 4 list on purpose: a copy sheet needs every
#: step of the agent's form mapped, not just one.
SHEET_AGENTS = frozenset({"otco"})

#: What a row asks of the operator.
#:   value         Trazo holds it: copy `value`.
#:   not_recorded  Trazo has a place for it and it is empty.
#:   not_in_trazo  Trazo keeps no such record; `extra.where` says where the operator finds it.
#:   yours         the operator's election, commitment or signature on the agent's form.
KINDS = ("value", "not_recorded", "not_in_trazo", "yours")


@dataclass(frozen=True)
class SheetRow:
    step: str
    item: str
    kind: str
    value: object = None
    #: Where the value comes from, for the operator to check it: "company", "establishment", "plan",
    #: "filing", "sales_records", "parcels".
    source: str = ""
    extra: dict = field(default_factory=dict)


def _contact(osp):
    est = osp.establishment
    company = getattr(est, "company", None)
    name = (est.contact_person or "").strip()
    email = est.contact_email or est.email or getattr(company, "contact_email", None) or ""
    phone = est.phone or est.contact_phone or getattr(company, "contact_phone", None) or ""
    return name, email, phone


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


def _value_row(step, item, value, source, **extra) -> SheetRow:
    present = value not in (None, "", [], {})
    return SheetRow(step, item, "value" if present else "not_recorded", value if present else None, source, extra)


def agent_form_sheet(osp) -> dict | None:
    """The copy sheet for this plan's agent, or None when Trazo has none for that agent."""
    from certifications.services.annual_update_filing import renewal_packet_filing
    from certifications.services.packet_coverage import changed_sections, packet_agent, packet_certifier
    from certifications.services.renewal_sales import organic_sales_subtotal

    agent, own = packet_certifier(osp)
    if not own or agent not in SHEET_AGENTS:
        return None
    company = getattr(osp.establishment, "company", None)
    name, email, phone = _contact(osp)
    filing = renewal_packet_filing(osp)

    rows = [
        _value_row("1", "business_name", getattr(company, "name", "") or "", "company"),
        _value_row("1", "dba", getattr(company, "tradename", "") or "", "company"),
        # The certificate number on file is a different identifier from OTCO's Client ID.
        SheetRow("1", "client_id", "not_in_trazo", extra={"where": "agent_certificate_and_letters"}),
        _value_row("1", "contact_name", name, "establishment"),
        _value_row("1", "contact_email", email, "establishment"),
        _value_row("1", "contact_phone", phone, "establishment"),
        SheetRow("1", "public_contact", "yours"),
        SheetRow("2", "continue_or_withdraw", "yours"),
        SheetRow("3", "services", "yours"),
        _value_row("3", "scopes", _scopes(osp), "plan"),
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

    rows.append(SheetRow("5", "agreement_and_signature", "yours"))

    if filing is None:
        rows.append(SheetRow("6", "gross_sales", "not_recorded", extra={"reason": "no_filing"}))
    else:
        sales = organic_sales_subtotal(osp.establishment, filing)
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
    rows += [SheetRow("6", "payment", "yours"), SheetRow("6", "billing_contact", "yours")]

    return {
        "agent": agent,
        "agent_name": packet_agent(osp).name or agent.upper(),
        "form": _renewal_form(agent),
        "plan_version": osp.version_number,
        "filing_id": getattr(filing, "id", None),
        "rows": [asdict(row) for row in rows],
    }
