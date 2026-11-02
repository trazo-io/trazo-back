"""
Which module PDFs a renewal packet carries: all of them (the default), or only the changed ones.

Oregon Tilth's OSP Update Form Step 4 asks the operation to "list updated OSP sections and
attach" them. The full packet attaches every module, so a reviewer who asked for the updated
sections sifts the whole ZIP for them. A changed-sections packet attaches only the module PDFs
whose answers differ between the two plan versions the year's annual update moved between, read
by `plan_version_changes.changed_module_keys`, the same comparison 02s prints.

What a changed-sections packet still carries, whatever changed:

  * every generated document (00 cover, 01 plan, 02 annual update, 02s, the year's revisions,
    03, 04, 05, 06). They are the renewal itself and the pages that say what the packet holds;
  * every Parcel Application. Land is kept with the operation, not with a plan version, so the
    comparison cannot see a parcel edit, and leaving a parcel out would be a guess;
  * the workbooks and every operator file. They are read from the operation's records, not
    from a plan version, so the comparison says nothing about them either.

Only module PDFs are left out, and each one left out is named on the cover, and wherever 04 or 06
would point at it, as unchanged since the prior version and not in this packet.

A module with an embedded panel is never left out (review of back #261). The panels (the
post-harvest facility table, the § 11 record types, the approved inputs and the logged products
not on them) render from the operation's current records, not from the version's stored answers,
so a facility added mid-year changes the PDF without changing an answer the comparison reads.
Such a module is carried and listed on the cover under that reason, never as "the same in both".
Every embed counts: the rule reads `question.embed`, so a new panel is carried by default.

Every file the packet carries is named by a document it carries. A handler's certificate is named
by the facility table, which is in a module now always carried; a file uploaded for a left-out
module's question is named on the cover, beside that module. A packet that
cannot be compared is refused, never built as a full packet under the changed-sections name.

Whether a certifying agent accepts a packet without the unchanged sections is the agent's
decision. This module only builds what the operation asked for and says what it left out.
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass

FULL = "full"
CHANGED = "changed"
SCOPES = (FULL, CHANGED)


class PacketScopeUnavailable(Exception):
    """The changed-sections packet cannot be built for this plan version, with the reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PacketModule:
    key: str
    label: str
    path: str


@dataclass(frozen=True)
class PacketScope:
    scope: str = FULL
    prior_version: int | None = None
    new_version: int | None = None
    #: (key, label, path) of each module PDF the packet carries because its answers changed.
    included: tuple = ()
    #: Modules whose PDF renders the operation's current records (an embedded panel): carried
    #: whatever the comparison says, because the comparison cannot see those records.
    live: tuple = ()
    #: The module PDFs left out because their answers are the same in both versions.
    omitted: tuple = ()
    #: § 205.201(a) section labels whose operator-written narrative or confirmations changed (in 01).
    narratives: tuple = ()

    @property
    def changed_only(self) -> bool:
        return self.scope == CHANGED

    def carries_module(self, key: str) -> bool:
        return not self.changed_only or key in {m.key for m in self.included + self.live}

    def omitted_note(self) -> str:
        return f"unchanged since plan v{self.prior_version}, not in this packet"


FULL_SCOPE = PacketScope()


def _modules(keys) -> tuple:
    from certifications.services.packet_coverage import _module_label, _module_location

    return tuple(PacketModule(key, _module_label(key), _module_location(key)) for key in keys)


def renders_live_records(module) -> bool:
    """True when a module's PDF embeds a panel read from the operation's records, not its answers."""
    return any(question.embed for page in module.pages for question in page.questions)


def files_for_omitted(scope, manifest) -> list:
    """(module, [zip paths]) for each left-out module with files the packet carries for its questions.

    Uploads are not compared between versions and travel as in the full packet; the module PDF that
    would name them is not in this packet, so the cover names them instead.
    """
    if manifest is None or not scope.changed_only:
        return []
    out = []
    for module in scope.omitted:
        paths = [
            e.zip_path for e in manifest.attached() if (e.requirement or "").startswith(f"{module.key}.") and e.zip_path
        ]
        if paths:
            out.append((module, sorted(set(paths))))
    return out


def changed_only_scope(osp) -> PacketScope:
    """The changed-sections scope for a packet built from `osp`, or `PacketScopeUnavailable`.

    The two versions are the ones the year's annual update moved between
    (`renewal_packet_filing`), the same pair 02s compares, so the cover and 02s never disagree
    about what changed.
    """
    from certifications.osp_modules import MODULE_REGISTRY
    from certifications.services.annual_update_filing import renewal_packet_filing
    from certifications.services.osp_pdf_snapshot import SECTION_LABELS
    from certifications.services.plan_version_changes import changed_module_keys, changed_section_keys

    filing = renewal_packet_filing(osp)
    if filing is None:
        raise PacketScopeUnavailable(
            "no_filing",
            "No annual update links this plan version to an earlier one, so there are no two plan versions "
            "to compare. Build the full packet, or record the annual update first.",
        )
    prior, new = filing.prior_osp, filing.new_osp
    if new is None:
        raise PacketScopeUnavailable(
            "no_new_version",
            f"The year's annual update did not create a new plan version; it is recorded against plan "
            f"v{prior.version_number}. There is no second version to compare, so build the full packet.",
        )
    if new.pk != osp.pk:
        raise PacketScopeUnavailable(
            "newer_version",
            f"The year's annual update moves from plan v{prior.version_number} to v{new.version_number}. "
            f"Build the changed-sections packet from plan v{new.version_number}, whose module files hold "
            "the changed answers.",
        )

    changed = set(changed_module_keys(prior, new))
    narratives = tuple(
        "§ 205.201" + " ".join(SECTION_LABELS.get(key, ("", key))) for key in changed_section_keys(prior, new)
    )
    if not changed and not narratives:
        raise PacketScopeUnavailable(
            "no_changes",
            f"No module answer and no § 205.201(a) narrative differs between plan v{prior.version_number} and "
            f"v{new.version_number}, so a changed-sections packet would attach no plan section. Build the "
            "full packet.",
        )
    keys = [m.key for m in MODULE_REGISTRY]
    live = {m.key for m in MODULE_REGISTRY if renders_live_records(m)} - changed
    return PacketScope(
        scope=CHANGED,
        prior_version=prior.version_number,
        new_version=new.version_number,
        included=_modules(k for k in keys if k in changed),
        live=_modules(k for k in keys if k in live),
        omitted=_modules(k for k in keys if k not in changed and k not in live),
        narratives=narratives,
    )


def scope_preview(osp) -> dict:
    """What a changed-sections packet built from `osp` would carry, or why it cannot be built."""
    try:
        scope = changed_only_scope(osp)
    except PacketScopeUnavailable as exc:
        return {"available": False, "code": exc.code, "reason": exc.message}

    def rows(modules):
        return [{"key": m.key, "label": m.label, "file": m.path} for m in modules]

    return {
        "available": True,
        "code": "",
        "reason": "",
        "prior_version": scope.prior_version,
        "new_version": scope.new_version,
        "included": rows(scope.included),
        "live": rows(scope.live),
        "omitted": rows(scope.omitted),
        "narratives": list(scope.narratives),
    }


_SCOPE: contextvars.ContextVar = contextvars.ContextVar("packet_scope", default=FULL_SCOPE)


def current_scope() -> PacketScope:
    return _SCOPE.get()


@contextlib.contextmanager
def scoped(scope: PacketScope | None):
    """The scope of the packet being built, for the pages that name module files (04, 06)."""
    token = _SCOPE.set(scope or FULL_SCOPE)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def mark_omitted(text: str) -> str:
    """`text` with every module file this packet leaves out marked as such, where it is named."""
    scope = current_scope()
    if not scope.changed_only or not text:
        return text
    note = f" ({scope.omitted_note()})"
    for module in scope.omitted:
        if module.path and module.path in text:
            text = text.replace(module.path, module.path + note)
    return text
