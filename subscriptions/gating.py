"""The one place that decides whether a company may produce a compliance document.

Starter is bounded by its OUTPUT, not by how much it can log (see migration 0014). That decision
is only real if it is ENFORCED — a `compliance_exports` flag that merely dresses a pricing page is
a price list, not a plan. Everything a farm hands to somebody else routes through here:

  * the OSP renewal packet          `certifications.views` OSPViewSet.packet
  * its component module PDFs       `certifications.views` OSPViewSet.module_pdf
  * the Common OSP workbooks        `certifications.views` OSPViewSet.attachments (download only)
  * the per-production audit export `history.views` audit_export + audit_export_by_uuid
  * the operation-wide dossier      `company.views` operation_audit_export
  * the California PUR export       `history.views` pur_export
  * the Washington spray records    `history.views` wa_spray_records_export (WAC 16-228-1320)
  * the tokenized certifier link    `certifications.views` CertifierAccessLinkViewSet (CREATE only)

Three of the first seven were found only by walking the URLconf, not by reading views: the
operation-wide dossier lives in a different app, the module PDFs are the packet's components (so
gating the ZIP alone left it reassemblable one download at a time), and the workbooks stream from
a route named "attachments". `subscriptions/tests/test_compliance_export_door_inventory.py` is
what makes the next door fail loudly instead of shipping free.

WHY A FUNCTION AND NOT A DRF PERMISSION CLASS
---------------------------------------------
The company has to come from the OBJECT being exported, never from `user.get_active_company()`.
A user who works in two companies has one "active" company and it is not necessarily the one that
owns the production, establishment or OSP in the request — resolving the plan from the session
would let a Compliance farm's subscription authorise a Starter farm's export, or refuse a valid
one. Every call site below already has the owning object in hand by the time it needs the check,
so the check takes the company explicitly and cannot be pointed at the wrong one by accident.

(`HasFeaturePermission` in permissions.py is not usable for this: it takes a constructor argument,
and DRF instantiates whatever is in `permission_classes` itself. It has no call sites.)

WHAT IS DELIBERATELY *NOT* GATED
--------------------------------
Logging, parcels, productions, photos, voice, templates, and the consumer/buyer QR page. The buyer
page is deliberately unlimited on every plan (the `monthly_scan_limit` key was deleted
2026-08-25: it was never enforced, and the buyer page is the surface that makes a grower want the
paid tier — capping it would remove the demonstration and strand QR codes already printed on
cases). The farm's own data is never withheld from the farm.
"""

from rest_framework.exceptions import PermissionDenied

# The Plan.features key. One spelling, imported — never re-typed at a call site, because a typo in
# a feature name reads as False and silently opens the gate for everyone.
COMPLIANCE_EXPORTS = "compliance_exports"


class ComplianceExportRequired(PermissionDenied):
    """403 raised when a plan does not include the certifier documents.

    Distinct class so a call site can let it through untouched while still handling ordinary
    permission failures, and so the frontend can branch on `code` to show an upgrade prompt
    instead of the generic "you do not have access" message — the two mean opposite things:
    one is "this is not yours", the other is "this IS yours, and here is how to take it out".
    """

    # Worded as CONTINUED ACCESS, not portability. It used to end "your records stay yours;
    # upgrading is what lets you export them", which a farmer reasonably reads as "otherwise my
    # data is trapped".
    #
    # ⚠️ UPDATED 2026-09-08. This comment used to justify that retraction with "Trazo has no plain
    # data export at all", which stopped being true on 2026-08-25: the free, ungated records export
    # shipped (`.../records-export/`, a ZIP of raw CSVs, pinned by
    # `history/tests/test_records_export.test_no_compliance_gate_in_the_view` and listed in the door
    # inventory as "free by design"). The stale half of the sentence is what kept the landing
    # pricing page answering "a one-click export of your whole account is not built yet" three
    # weeks after it was built, while the FAQ on the same site answered "yes, on every plan".
    #
    # So the message now says BOTH halves, which is the whole distinction this exception exists to
    # draw: the raw records are free and always were yours; the certifier ARTEFACTS are the paid
    # thing. Refusing a paid artefact while implying the data behind it is hostage was the defect.
    default_detail = (
        "Certifier documents (the OSP renewal packet and workbooks, the audit exports, the CA PUR "
        "export, the Washington spray records and the certifier review link) are part of the "
        "Compliance plan. Keep logging for free, and export your own records as CSV at any time on "
        "any plan; what Compliance adds is the certifier-ready paperwork built from them."
    )
    default_code = "compliance_exports_required"


def company_has_compliance_exports(company) -> bool:
    """True when `company` may generate compliance documents. Fails closed on None."""
    if company is None:
        return False
    return bool(company.has_feature(COMPLIANCE_EXPORTS))


def require_compliance_exports(company, user=None):
    """Raise `ComplianceExportRequired` unless `company` may generate compliance documents.

    `user` is optional and only widens the gate for staff: support and I need to be able to
    reproduce a farmer's packet from their own data without moving them onto another plan. It is
    NOT an ownership check — the caller has already established that this user may act on this
    company before it gets here.
    """
    if user is not None and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
        return
    if not company_has_compliance_exports(company):
        raise ComplianceExportRequired()
