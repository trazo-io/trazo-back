"""
Loader and validator for the certifier conformance registers.

The register (`documentation/compliance/certifiers/<certifier>/`) is the source of truth for any
statement Trazo makes about alignment with a certifying agent's own OSP forms: one YAML file per
form, one row per numbered question, table column or checkbox group on that form.

One folder per certifier, all the same shape — `forms/`, `scope.yaml`, `unmapped/`. CCOF and WSDA
are overlays of the same federal content (7 CFR 205.201), so a second certifier is registered as a
DELTA against the first: rows that ask the same obligation cite the same Trazo questions, and only
what a certifier asks differently, or additionally, is fresh analysis. Two independent full audits
of one product will disagree about it — that is not a hypothetical, it is what the
cited-vs-unmapped guard was written to catch after two passes described the same nine questions
contradictorily.

It is data rather than prose for one reason: prose about a questionnaire goes stale the first time
the questionnaire changes, and nothing tells you. Everything here exists so that
`test_ccof_conformance_register.py` can fail when the register and `MODULE_REGISTRY` disagree — in
BOTH directions:

  forward   every `module_key.question_key` the register cites must exist today. Catches a
            register row pointing at a question that was renamed or deleted.
  reverse   every question of a module whose form is marked `register_status: complete` must be
            cited by the register or listed in `unmapped/<module_key>.yaml` with a reason. Catches
            a question added to a mapped module without anyone deciding what CCOF asks about it.

`form.trazo_module` takes one module key or a list. A list is how a form claims content Trazo
splits differently from CCOF — G6.2 Storage, for instance, answers its facility-pest questions out
of the separate G9.0 module.

Reverse coverage is deliberately scoped to *complete* forms so the register can be built one form
at a time without the guard failing the build meanwhile.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# certifications/services/certifier_register.py -> services -> certifications -> trazo-back
#
# ⚠️ This was `parents[3]`, i.e. the directory ABOVE this repository, with the comment
# "certifications -> trazo-back -> repo root". There is no such root: ~/dev/trazo is an
# ordinary folder, not a git repository, and it is not part of the Docker build context
# either (Dockerfile is WORKDIR /app + COPY . .). So in production `parents[3]` resolved to
# "/" and REGISTER_DIR pointed at /documentation/compliance/certifiers, which does not exist.
#
# The register was therefore ABSENT from every built image. It failed silently rather than
# loudly — `certifiers()` returns [] on a missing directory, and the packet's coverage page
# is designed to degrade instead of crash — so the certifier packet has been shipping without
# the section that names the forms Trazo does NOT generate. The honesty section is the one
# that goes missing.
#
# Found 2026-09-07 by the first CI run this repository ever completed: the same absence made
# `test_the_page_names_the_forms_trazo_does_not_generate` fail on a runner while passing on a
# laptop, where ~/dev/trazo/documentation happened to sit beside the checkout.
#
# The register is a RUNTIME FIXTURE read by application code, not documentation. It now lives
# inside this repository, so it is versioned with the code that reads it and is present in the
# image. `.dockerignore` excludes *.md but not *.yaml, so the form definitions are copied.
REGISTER_DIR = Path(__file__).resolve().parents[2] / "documentation" / "compliance" / "certifiers"


def certifiers() -> list[str]:
    """Certifier keys, alphabetical.

    A certifier counts as registered once it has at least one form file — an empty `forms/`
    directory is the normal state while a new certifier is being built out, and it must not break
    the guards or the generated statement for the certifiers already registered.
    """
    if not REGISTER_DIR.is_dir():
        return []
    return sorted(p.name for p in REGISTER_DIR.iterdir() if any((p / "forms").glob("*.yaml")))


def forms_dir(certifier: str) -> Path:
    return REGISTER_DIR / certifier / "forms"


def unmapped_dir(certifier: str) -> Path:
    return REGISTER_DIR / certifier / "unmapped"


def scope_path(certifier: str) -> Path:
    return REGISTER_DIR / certifier / "scope.yaml"


STATUSES = ("covered", "partial", "not_covered", "out_of_scope")
SEVERITIES = ("P0", "P1", "P2", "P3")
REGISTER_STATUSES = ("complete", "draft")
DISPOSITIONS = ("decision", "gap")

# Rows that are not `covered` owe the reader a statement of what is missing; anything short of
# `out_of_scope` also owes a fix, because "we know and we are not doing it" is a decision that
# belongs in `reason`, not an empty column.
_REQUIRED_WHEN = {
    "partial": ("severity", "gap", "fix"),
    "not_covered": ("severity", "gap", "fix"),
    "out_of_scope": ("reason",),
}

# `code` is deliberately NOT required: the Parcel Application, the Grower Materials Application and
# the Certification Contract carry no G-number on CCOF's own paper, and forcing a placeholder into
# the field would print a code in the statement that a reviewer cannot look up.
_FORM_REQUIRED = ("title", "document_id", "revision", "url", "retrieved", "register_status")


@dataclass
class Item:
    ref: str
    asks: str
    status: str
    severity: str | None = None
    gap: str | None = None
    fix: str | None = None
    reason: str | None = None
    #: Where the answer to this form question lives in Trazo.
    questions: tuple[str, ...] = ()
    #: Existing Trazo answers that INDICATE this form applies — not where it is answered. A form
    #: Trazo cannot answer at all still has triggers, and conflating the two made one question read
    #: as both `covered` (by the form that answers it) and `not_covered` (by the form it triggers).
    triggered_by: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    prints: str = ""
    root_cause: str = ""

    @property
    def is_gap(self) -> bool:
        return self.status in ("partial", "not_covered")


@dataclass
class Form:
    path: Path
    code: str
    title: str
    document_id: str
    revision: str
    url: str
    retrieved: datetime.date | str
    pdf: str = ""
    nop_cites: tuple[str, ...] = ()
    guide_trigger: str = ""
    required_of_every_grower: bool = False
    trazo_modules: tuple[str, ...] = ()
    register_status: str = "complete"
    certifier: str = ""
    items: list[Item] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.code} {self.title}".strip() if self.code else self.title


def _as_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def load_forms(certifier: str | None = None) -> list[Form]:
    """Parse every form file for one certifier, or for all of them.

    Raises ValueError with a path-prefixed message on a schema fault.
    """
    if certifier is None:
        out: list[Form] = []
        for key in certifiers():
            out.extend(load_forms(key))
        if not out:
            raise ValueError(f"No certifier register holds any form file: {REGISTER_DIR}")
        return out

    directory = forms_dir(certifier)
    if not directory.is_dir():
        raise ValueError(f"Certifier register directory is missing: {directory}")

    forms: list[Form] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        meta = raw.get("form") or {}
        where = path.name

        missing = [k for k in _FORM_REQUIRED if not meta.get(k)]
        if missing:
            raise ValueError(f"{where}: form is missing required key(s): {', '.join(missing)}")

        # No default. `complete` claims every question of the mapped modules is accounted for, and
        # a file that merely FORGOT the field would make that claim silently — which is exactly
        # what happened while WSDA was being registered.
        register_status = meta.get("register_status")
        if register_status not in REGISTER_STATUSES:
            raise ValueError(f"{where}: register_status must be one of {REGISTER_STATUSES}")

        items: list[Item] = []
        seen_refs: set[str] = set()
        for raw_item in raw.get("items") or []:
            ref = str(raw_item.get("ref", "")).strip()
            if not ref:
                raise ValueError(f"{where}: an item has no `ref`")
            if ref in seen_refs:
                raise ValueError(f"{where}: duplicate item ref {ref!r}")
            seen_refs.add(ref)

            status = raw_item.get("status")
            if status not in STATUSES:
                raise ValueError(f"{where} [{ref}]: status must be one of {STATUSES}, got {status!r}")

            for key in _REQUIRED_WHEN.get(status, ()):
                if not raw_item.get(key):
                    raise ValueError(f"{where} [{ref}]: status {status!r} requires `{key}`")

            # One defect usually breaks several CCOF questions: the materials list that cannot hold
            # compost fails three questions on two forms. Without a shared root cause the register
            # reads as seventeen problems when it is ten, and a burn-down built from it would
            # mis-count the work. Required on blockers only — that is where the count gets quoted.
            if raw_item.get("status") != "covered" and raw_item.get("severity") == "P0":
                if not str(raw_item.get("root_cause") or "").strip():
                    raise ValueError(
                        f"{where} [{ref}]: a P0 row needs a `root_cause` slug so blockers that share "
                        "one defect are counted once"
                    )

            severity = raw_item.get("severity")
            if severity is not None and severity not in SEVERITIES:
                raise ValueError(f"{where} [{ref}]: severity must be one of {SEVERITIES}")
            if status == "covered" and severity:
                raise ValueError(f"{where} [{ref}]: a covered row must not carry a severity")

            if not str(raw_item.get("asks", "")).strip():
                raise ValueError(f"{where} [{ref}]: `asks` must state what the CCOF form asks")

            trazo = raw_item.get("trazo") or {}
            items.append(
                Item(
                    ref=ref,
                    asks=str(raw_item["asks"]).strip(),
                    status=status,
                    severity=severity,
                    gap=raw_item.get("gap"),
                    fix=raw_item.get("fix"),
                    reason=raw_item.get("reason"),
                    questions=_as_tuple(trazo.get("questions")),
                    triggered_by=_as_tuple(trazo.get("triggered_by")),
                    models=_as_tuple(trazo.get("models")),
                    prints=str(trazo.get("prints") or ""),
                    root_cause=str(raw_item.get("root_cause") or ""),
                )
            )

        if not items:
            raise ValueError(f"{where}: form has no items")

        forms.append(
            Form(
                path=path,
                code=str(meta.get("code") or ""),
                title=str(meta["title"]),
                document_id=str(meta["document_id"]),
                revision=str(meta["revision"]),
                url=str(meta["url"]),
                retrieved=meta["retrieved"],
                pdf=str(meta.get("pdf") or ""),
                nop_cites=_as_tuple(meta.get("nop_cites")),
                guide_trigger=str(meta.get("guide_trigger") or ""),
                required_of_every_grower=bool(meta.get("required_of_every_grower")),
                trazo_modules=_as_tuple(meta.get("trazo_module")),
                register_status=register_status,
                certifier=certifier,
                items=items,
            )
        )

    if not forms:
        raise ValueError(f"Certifier register holds no form files: {directory}")
    return forms


def load_unmapped(certifier: str | None = None) -> dict[str, str]:
    """`module_key.question_key` -> reason it has no CCOF counterpart.

    One file per module (`unmapped/<module_key>.yaml`) so that work on different CCOF forms never
    edits the same file.
    """
    if certifier is None:
        merged: dict[str, str] = {}
        for key in certifiers():
            merged.update(load_unmapped(key))
        return merged

    directory = unmapped_dir(certifier)
    if not directory.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        for key, reason in (raw.get("questions") or {}).items():
            if not str(reason or "").strip():
                raise ValueError(f"{path.name}: {key} needs a reason, not an empty value")
            if not str(key).startswith(f"{path.stem}."):
                raise ValueError(
                    f"{path.name}: {key} belongs in {str(key).split('.')[0]}.yaml — "
                    "one file per module keeps parallel edits from colliding"
                )
            out[str(key)] = str(reason).strip()
    return out


def live_modules() -> tuple:
    """Every OSP module a farm actually answers.

    `MODULE_REGISTRY` is the farm-wide list; the Parcel Application is deliberately NOT in it
    because it is answered once per parcel and is served by its own branch of the module endpoint.
    Leaving it out here would exempt the largest CCOF form from every guard below — which is what
    happened on the first pass, and the register's 36 Parcel Application rows carried no validated
    citation at all until this was fixed.
    """
    from certifications.osp_modules import MODULE_REGISTRY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION

    return tuple(MODULE_REGISTRY) + (PARCEL_APPLICATION,)


def live_question_keys() -> set[str]:
    """Every `module_key.question_key` a farm can answer, farm-wide and per-parcel."""
    return {
        f"{module.key}.{question.key}"
        for module in live_modules()
        for page in module.pages
        for question in page.questions
    }


def cited_question_keys(forms: list[Form]) -> set[str]:
    """Questions the register says ANSWER a form question — the reverse-coverage sense."""
    return {key for form in forms for item in form.items for key in item.questions}


def referenced_question_keys(forms: list[Form]) -> set[str]:
    """Every question key the register names, answering or triggering.

    Both must exist in the live registry; only `questions` counts as coverage.
    """
    return cited_question_keys(forms) | {key for form in forms for item in form.items for key in item.triggered_by}


def summarize(forms: list[Form]) -> dict:
    """Counts for the generated statement. No ratio that reads as a self-assigned grade."""
    by_status = {status: 0 for status in STATUSES}
    by_severity = {severity: 0 for severity in SEVERITIES}
    for form in forms:
        for item in form.items:
            by_status[item.status] += 1
            if item.severity:
                by_severity[item.severity] += 1
    return {
        "forms": len(forms),
        "items": sum(len(f.items) for f in forms),
        "by_status": by_status,
        "by_severity": by_severity,
        "complete_forms": sum(1 for f in forms if f.register_status == "complete"),
    }


@dataclass
class ScopeEntry:
    """A certifier's form Trazo does not register, and why.

    `decision` and `gap` are kept apart deliberately: a decision is an answer, a gap is a debt. A
    file that let them blur would be the thing it exists to prevent — an absence presented as a
    choice.

    `certifier` is load-bearing, not bookkeeping: the renewal packet's coverage page is addressed
    to ONE agent, and `load_scope()` with no argument returns every registered agent's entries.
    Without this field the page had no way to tell them apart, so a CCOF packet listed WSDA's
    AGR 2180/2523/2524 among the forms "this packet does not cover".
    """

    form: str
    disposition: str
    reason: str
    document_id: str = ""
    triggered_from: str = ""
    certifier: str = ""


def load_scope(certifier: str | None = None) -> list[ScopeEntry]:
    if certifier is None:
        out: list[ScopeEntry] = []
        for key in certifiers():
            out.extend(load_scope(key))
        return out

    path = scope_path(certifier)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    entries: list[ScopeEntry] = []
    for item in raw.get("forms") or []:
        form = str(item.get("form", "")).strip()
        if not form:
            raise ValueError(f"{certifier}/scope.yaml: an entry has no `form`")
        disposition = item.get("disposition")
        if disposition not in DISPOSITIONS:
            raise ValueError(f"{certifier}/scope.yaml [{form}]: disposition must be one of {DISPOSITIONS}")
        reason = str(item.get("reason", "")).strip()
        if not reason:
            raise ValueError(f"{certifier}/scope.yaml [{form}]: an excluded form needs a stated reason")
        if disposition == "gap" and not str(item.get("triggered_from", "")).strip():
            raise ValueError(
                f"{certifier}/scope.yaml [{form}]: a gap must say where it is triggered from, "
                "otherwise it cannot be prioritised against anything"
            )
        entries.append(
            ScopeEntry(
                form=form,
                disposition=disposition,
                reason=reason,
                document_id=str(item.get("document_id") or ""),
                triggered_from=str(item.get("triggered_from") or ""),
                certifier=certifier,
            )
        )
    return entries


def blockers_by_root_cause(forms: list[Form]) -> dict[str, list[tuple[Form, Item]]]:
    """P0 rows grouped by the defect behind them — the burn-down view.

    The count that matters is DEFECTS, not rows: fixing the materials-list model closes four rows
    across two certifiers at once. Do not hard-code either number here — an earlier version of this
    docstring said "seventeen rows across ten defects" and was still saying it after two rounds of
    fixes and a second certifier. `summarize()` derives both.
    """
    grouped: dict[str, list[tuple[Form, Item]]] = {}
    for form in forms:
        for item in form.items:
            if item.severity == "P0":
                grouped.setdefault(item.root_cause or item.ref, []).append((form, item))
    return dict(sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])))


def cross_certifier_conflicts(forms: list[Form]) -> dict[str, dict[str, list[str]]]:
    """Trazo questions two certifiers describe incompatibly.

    CCOF and WSDA overlay the same federal content, so most of their questions ask the same
    obligation of the same Trazo question. `covered` for one certifier and `not_covered` for
    another is therefore a contradiction about the product, not a difference between the forms:
    either the fact is capturable and printable or it is not.

    `partial` alongside `covered` is NOT a conflict — one certifier legitimately asks for more
    depth than another, and flattening that would push people to overstate the weaker one.

    Returns {question_key: {status: [where it is claimed]}} for the conflicting questions only.
    """
    seen: dict[str, dict[str, list[str]]] = {}
    for form in forms:
        for item in form.items:
            for key in item.questions:
                where = f"{form.certifier}:{form.code or form.title} {item.ref}"
                seen.setdefault(key, {}).setdefault(item.status, []).append(where)

    return {key: statuses for key, statuses in seen.items() if "covered" in statuses and "not_covered" in statuses}


def question_keys_hidden_in_models(forms: list[Form]) -> list[str]:
    """`trazo.models` entries that are really `module_key.question_key` citations.

    `models` is free text and `cited_question_keys()` reads only `questions`, so a real question
    key parked in `models` is validated by nothing and counts toward no coverage. THIRTEEN rows
    did exactly that when this guard first ran — an adversarial re-read had spotted three, which
    is the usual relationship between reading and checking. Several carried a parenthetical
    explaining why the key was not in `questions`: they were dodging the cited-vs-unmapped guard,
    which at the time compared the two ACROSS certifiers and so called a legitimate WSDA citation
    a contradiction. That guard is scoped per certifier now, which removes the reason to hide
    anything; this closes the hiding place.

    Found 2026-08-28: `broken_model_references()` skips any ref containing a space, and every one
    of these carried its excuse inline. Each comma-separated segment is checked, because the rows
    that did this joined two keys in one string.
    """
    live = live_question_keys()
    hidden: list[str] = []
    for form in forms:
        for item in form.items:
            for raw in item.models:
                for segment in raw.split("(")[0].split(","):
                    candidate = segment.strip().rstrip(".")
                    if candidate in live and candidate not in item.questions:
                        hidden.append(f"{form.certifier}:{form.code or form.document_id} {item.ref} -> {candidate}")
    return hidden


def broken_model_references(forms: list[Form]) -> list[str]:
    """`trazo.models` entries that name a Django field or property which does not exist.

    Unlike `trazo.questions`, this field is free text — it has to be, because a location is
    sometimes a service module, a frontend component or a workbook rather than a model attribute.
    That freedom let fabricated names in: seven register rows cited cleanout fields on
    `history.EquipmentEvent`, which records equipment name, type, fuel and hours and has no
    cleaning fields at all. The fields were real, on `history.ProductionEvent` — so the rows
    described the product from the wrong model, under the defect that tops the roadmap.

    Only strict `app.Model.field` / `app.models.Model.field` refs are checked. Anything with a
    space, a slash or fewer than three segments is prose or a non-Django location and is skipped
    rather than guessed at; a trailing "(note)" is stripped first. Properties count as fields —
    `PostHarvestFacility.cert_is_current` is a computed tri-state, not a column.
    """
    from django.apps import apps

    broken: list[str] = []
    for form in forms:
        for item in form.items:
            for raw in item.models:
                ref = raw.split("(")[0].strip().rstrip(".")
                if " " in ref or "/" in ref:
                    continue
                parts = [p for p in ref.split(".") if p != "models"]
                if len(parts) != 3 or not parts[1][:1].isupper():
                    continue
                app_label, model_name, attr = parts
                try:
                    model = apps.get_model(app_label, model_name)
                except Exception:  # noqa: BLE001 — an unknown app/model is not necessarily ours
                    continue
                names = {f.name for f in model._meta.get_fields()}
                names |= {getattr(f, "attname", "") for f in model._meta.get_fields()}
                if attr not in names and not hasattr(model, attr):
                    broken.append(f"{form.certifier}:{form.code or form.document_id} {item.ref} -> {ref}")
    return broken
