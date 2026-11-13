"""Every door onto a certifier document must be gated — including the one added next month.

Three of the doors are exercised over HTTP in `test_starter_bounded_by_outputs.py`. This test
covers the failure that live tests structurally cannot: a SEVENTH export endpoint appearing later,
in a different app, wired by somebody who did not know the gate existed. That is not hypothetical
— it is what happened while this change was being written. The per-production audit export, the
PUR export and the OSP packet were found by reading the views; the operation-wide dossier
(`company/views.py`) and the OSP module PDFs (`certifications/views.py`) were found only by
enumerating the URLconf, and the module PDFs are the components of the packet, so gating the ZIP
alone would have left the whole artifact reassemblable one download at a time.

The check walks the real URLconf rather than a hand-written list of files, so a route registered
anywhere in the project is seen. Each match must be classified: gated, or exempt with a stated
reason. "I did not think about it" is not a category — an unclassified export route fails.
"""

import ast
import inspect
import textwrap

from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver

# Route-name fragments that mean "this hands the operator a document". Matched against the URL
# NAME, which is stable across router prefixes.
#
# `attachment` and `workbook` were added 2026-08-15 after this test MISSED a real door. The four
# Common OSP attachment workbooks stream as .xlsx from `establishment-osps-attachments` — an
# artifact named on the price list — and the route is called "attachments", which matched none of
# the original five words. A hint list is a guess about naming; when it is wrong the test passes
# while a paid artifact ships free, so it errs wide from here and lets the exemption list carry
# the judgement.
DOCUMENT_ROUTE_HINTS = (
    "export",
    "packet",
    "pdf",
    "dossier",
    "download",
    "attachment",
    "workbook",
)

# Django's own admin generates `<app>_<model>_add|change|delete|changelist|history` for every
# registered model, so widening the hints above swept in ~15 admin routes for models whose names
# contain "attachment" or "report". They are staff-only behind admin auth, they are not the
# product's export surface, and listing each one in EXEMPT_ROUTES would bury the four real
# exemptions in noise. Skipped as a class, by namespace, rather than one at a time.
ADMIN_ROUTE_SUFFIXES = ("_add", "_change", "_delete", "_changelist", "_history")

# Routes that match a hint and are deliberately NOT behind the compliance gate. Every entry states
# why, because an exemption list without reasons decays into a list of things somebody once
# silenced.
EXEMPT_ROUTES = {
    # The farm's own data, never withheld from the farm. A QR code is printed on cases and
    # already in the world; the consumer page it points at is deliberately unlimited,
    # not paywalled, and it is the surface that makes a grower want the paid tier at all.
    "histories-download-qr-code": "consumer QR code — the farm's own, and the demonstration that sells the tier",
    "parcel-histories-download-qr-code": "same route under the nested router",
    # Retrieval of documents ALREADY filed. Every generator that files one is gated, so nothing
    # new lands here for a Starter farm — and refusing a farm its own stored file would be
    # withholding data rather than withholding an artifact.
    "establishment-documents-download": "re-download of an already-filed document, not a new one",
    # Certifier-side, reached only with a token the farm minted — and minting IS gated. A link
    # issued while the farm was on Compliance keeps working if it later lapses to Starter, which
    # is correct: the farm paid for that share, the certifier may be mid-review, and the farm can
    # revoke it (revocation is deliberately NOT gated — see CertifierAccessLinkViewSet).
    "certifier_review_dossier": "certifier holds the token; link creation is what carries the gate",
    "certifier_review_dossier_status": (
        "progress of a build the token's dossier route started; status and progress only, the "
        "document streams from certifier_review_dossier"
    ),
    # Background builds (documents/services/export_jobs.py). The POST that STARTS a build is
    # gated like the inline export it replaces; the status poll returns no document, and the
    # file itself is fetched through establishment-documents-download above.
    "company-establishments-export-job": "status of a build the gated export-jobs POST accepted; no document",
    # Billing.
    "invoice-download": "the customer's own invoice",
    # Support-ticket attachments: files the USER uploaded to their own ticket, surfaced by the
    # widened `attachment` hint. Nothing to do with certifier documents — gating them would mean
    # a farm on the free tier could not attach a screenshot to a help request, which is the
    # opposite of what a paywall on artifacts is for.
    "supportattachment-list": "files the user uploaded to their own support ticket",
    "supportattachment-detail": "same, single record",
    # Raw § 205.103 records as CSV. Deliberately free on every tier, and the docstring on
    # RecordsExportViewSet says so: record ownership is the product's answer to every grower
    # who watched their last tool shut down with their data inside (COG Pro). The
    # certifier-SHAPED artifacts — packet, dossier, audit PDF — are what Compliance buys, and
    # those stay gated. The farm's own rows never are. Contract pinned separately by
    # history/tests/test_records_export.py.
    "establishment-records-export-list": "the farm's own raw records — free by design, never a paid artifact",
}

# What the gate is called. Asserted by NAME so a rename cannot quietly empty this test.
GATE_FUNCTION = "require_compliance_exports"


def _iter_routes(resolver, prefix=""):
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            yield from _iter_routes(pattern, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield pattern, prefix + str(pattern.pattern)


def _handlers_for(pattern):
    """The callables a route can actually dispatch to.

    A DRF router route is one `ViewSetClass.as_view({"get": "packet", ...})` callback, so the
    method that matters is named in `callback.actions`, not in the callback itself. Reading the
    callback's own source would inspect DRF's generated `view()` wrapper and find no gate in any
    route, which is a test that passes by never looking at the code.
    """
    callback = pattern.callback
    cls = getattr(callback, "cls", None)
    actions = getattr(callback, "actions", None)
    if cls is not None and actions:
        return [getattr(cls, name) for name in set(actions.values()) if hasattr(cls, name)]
    if cls is not None:
        # `@api_view` also produces a callback with `.cls` but no `.actions`: DRF builds a
        # throwaway `WrappedAPIView` and attaches the ORIGINAL function as `get`/`post`/… .
        # `audit_export_by_uuid` is one of these, and the first draft of this helper returned the
        # generated wrapper for it — reporting a gated endpoint as ungated. Missing this in the
        # other direction is the dangerous one: had that route been the exempt-looking case, the
        # inventory would have passed while never reading the view at all.
        handlers = [getattr(cls, verb) for verb in ("get", "post", "put", "patch", "delete") if hasattr(cls, verb)]
        if handlers:
            return handlers
    # Plain function view.
    return [getattr(callback, "__wrapped__", callback)]


def _calls_gate_directly(handler) -> bool:
    """True when this function's own body contains a CALL to the gate.

    Parsed, not grepped. A substring search over the source would be satisfied by the gate's name
    appearing in a comment — `# require_compliance_exports intentionally omitted here` would mark
    the door as protected while leaving it wide open, and that is a comment somebody removing a
    gate is quite likely to write. `ast` never sees comments, and matching a `Call` node rather
    than a bare name also rejects a mention in an import list or a docstring.

    `textwrap.dedent` because `inspect.getsource` of a METHOD returns it at class indentation,
    which is a syntax error on its own.
    """
    try:
        source = textwrap.dedent(inspect.getsource(handler))
    except (OSError, TypeError):
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (getattr(func, "id", None) or getattr(func, "attr", None)) == GATE_FUNCTION:
                return True
    return False


def _mentions_gate(handler, _depth=0) -> bool:
    """Does this handler — or the real function hiding inside it — call the gate?

    The closure walk is not defensive programming, it is the only way to see an `@api_view`
    endpoint. DRF rewrites such a view into

        def handler(self, *args, **kwargs):
            return func(*args, **kwargs)

    and attaches THAT to the generated `WrappedAPIView`. Reading its source finds two lines of
    DRF plumbing, so `audit_export_by_uuid` — which does call the gate — was reported as ungated
    until the real function was pulled out of the closure cell. Depth-limited because the point is
    to see through a known two-layer wrapper, not to search the program.
    """
    if _calls_gate_directly(handler):
        return True
    if _depth >= 3:
        return False
    for cell in getattr(handler, "__closure__", None) or ():
        try:
            inner = cell.cell_contents
        except ValueError:  # cell not yet populated
            continue
        if inspect.isfunction(inner) and _mentions_gate(inner, _depth + 1):
            return True
    return False


class ComplianceExportDoorInventoryTests(SimpleTestCase):
    def test_every_document_route_is_gated_or_explicitly_exempt(self):
        unclassified = []
        for pattern, _path in _iter_routes(get_resolver()):
            name = pattern.name
            if not name or not any(hint in name for hint in DOCUMENT_ROUTE_HINTS):
                continue
            if name.endswith(ADMIN_ROUTE_SUFFIXES):
                continue
            if name in EXEMPT_ROUTES:
                continue
            if any(_mentions_gate(handler) for handler in _handlers_for(pattern)):
                continue
            unclassified.append(name)

        self.assertEqual(
            sorted(set(unclassified)),
            [],
            "These routes hand out a document and neither call "
            f"`{GATE_FUNCTION}` nor appear in EXEMPT_ROUTES: {sorted(set(unclassified))}.\n"
            "Gate it (subscriptions/gating.py) or add it to EXEMPT_ROUTES WITH A REASON. "
            "A new export door that nobody classified is how a paid artifact ships for free.",
        )

    def test_the_inspection_actually_reads_the_gated_views(self):
        """Guards the guard.

        `_handlers_for` resolving to DRF's generated `view()` wrapper — or `inspect.getsource`
        failing — would make the test above pass with every gate deleted. So assert positively
        that the walk FINDS the gate on routes known to carry it. A negative assertion that never
        proves it read something is not evidence.
        """
        gated = set()
        for pattern, _path in _iter_routes(get_resolver()):
            if not pattern.name:
                continue
            if any(_mentions_gate(handler) for handler in _handlers_for(pattern)):
                gated.add(pattern.name)

        for expected in (
            "company-establishments-operation-audit-export",
            "company-establishments-export-jobs",
            "histories-pur-export",
            "histories-wa-spray-records-export",
            "histories-audit-export",
            "audit-export-by-uuid",
            "establishment-osps-packet",
            "establishment-osps-module-pdf",
            "establishment-osps-attachments",
        ):
            self.assertIn(
                expected,
                gated,
                f"The walk did not find the gate on `{expected}`, which definitely has one. "
                "The inspection is broken, so the inventory test above proves nothing.",
            )

    def test_exempt_routes_still_exist(self):
        """An exemption for a route that has been deleted is dead weight that reads as coverage.

        It also hides the opposite mistake: a route RENAMED rather than removed drops out of the
        inventory silently, and its exemption keeps pointing at nothing.
        """
        live = {pattern.name for pattern, _ in _iter_routes(get_resolver()) if pattern.name}
        stale = sorted(name for name in EXEMPT_ROUTES if name not in live)
        self.assertEqual(stale, [], f"EXEMPT_ROUTES lists routes that no longer exist: {stale}")
