"""Dry-run, apply and restore for commands that rewrite stored production data (run 8).

The production safety rule, in one place so every command follows it the same way:

1. Dry run by default. The command computes, for every row it would change, the values before
   and after and the reason, and writes them to a JSON report. Nothing is saved.
2. `--apply` re-computes (never trusts an old report), saves the changes in one transaction and
   records a `DataOperationLog` row with the report's SHA-256 and counts.
3. A second dry run must report zero changes: the operation is idempotent.
4. `--restore <report>` puts every row's "before" values back, in one transaction, and logs it.
   `--restore log:<id>` does the same from the report text stored on that apply's
   `DataOperationLog` row, for when the file is gone (a production container's disk does not
   survive a deploy).

The applied report is the only record of what an apply changed (for a deletion, the only copy of
the rows). So `run` never writes over a report whose SHA-256 matches a logged apply, and
`restore` accepts only such a report, unchanged since it was applied (review of back #123: the
documented sequence reused one path, and the verification dry run erased the applied report).

A command supplies `plan()` (the list of changes) and `write(model_label, pk, values)`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

from django.core.management.base import CommandError
from django.db import transaction


class ReportError(CommandError):
    """A report path that would lose, or was never, the record of an apply."""


@dataclass
class RowChange:
    model: str
    pk: Any
    before: Dict[str, Any]
    after: Dict[str, Any]
    reason: str = ""


@dataclass
class Report:
    operation: str
    changes: List[RowChange] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {"operation": self.operation, "changes": [asdict(c) for c in self.changes]},
            indent=1,
            sort_keys=True,
            default=str,
        )

    @property
    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {"rows": len(self.changes)}
        for c in self.changes:
            key = f"{c.model}:{c.before.get('_label', '')}->{c.after.get('_label', '')}".rstrip(":->")
            out[key] = out.get(key, 0) + 1
        return out


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _applied_log(operation: str, text: str):
    from common.models import DataOperationLog

    return (
        DataOperationLog.objects.filter(
            operation=operation, action=DataOperationLog.ACTION_APPLY, report_sha256=sha256_text(text)
        )
        .order_by("-pk")
        .first()
    )


def _guard_overwrite(report_path: str) -> None:
    path = Path(report_path)
    if not path.exists():
        return
    text = path.read_text()
    try:
        operation = json.loads(text).get("operation", "")
    except ValueError:
        return
    if _applied_log(operation, text) is not None:
        raise ReportError(
            f"{report_path} is the report of an applied operation and is what --restore reads. "
            "Write this run's report to a new path."
        )


def _strip(values: Dict[str, Any]) -> Dict[str, Any]:
    """Report-only keys start with an underscore and are never written."""
    return {k: v for k, v in values.items() if not k.startswith("_")}


def run(
    *,
    operation: str,
    plan: Callable[[], Iterable[RowChange]],
    write: Callable[[str, Any, Dict[str, Any]], None],
    report_path: str,
    apply: bool = False,
    run_by: str = "",
) -> Report:
    """Compute the changes, write the report, and save them only when `apply` is set."""
    from common.models import DataOperationLog

    _guard_overwrite(report_path)
    report = Report(operation=operation, changes=list(plan()))
    text = report.to_json()
    Path(report_path).write_text(text)
    if apply and report.changes:
        with transaction.atomic():
            for c in report.changes:
                write(c.model, c.pk, _strip(c.after))
            DataOperationLog.objects.create(
                operation=operation,
                action=DataOperationLog.ACTION_APPLY,
                report_sha256=sha256_text(text),
                counts=report.counts,
                run_by=run_by,
                report=text,
            )
    return report


LOG_PREFIX = "log:"


def _read_report(report_path: str) -> str:
    """The report text, from a file or, for `log:<id>`, from that applied log row."""
    from common.models import DataOperationLog

    if not report_path.startswith(LOG_PREFIX):
        return Path(report_path).read_text()
    raw_id = report_path[len(LOG_PREFIX) :]
    try:
        log = DataOperationLog.objects.get(pk=int(raw_id), action=DataOperationLog.ACTION_APPLY)
    except (ValueError, DataOperationLog.DoesNotExist):
        raise ReportError(f"{report_path}: no applied DataOperationLog row with that id. Nothing was restored.")
    if not log.report:
        # Not necessarily legacy: an apply logged before 2026-11-04 has no stored report, and so
        # does a row some command logged directly instead of through `run()` (the pilot operator
        # and review-fixture commands hash an in-memory dict and write no report anywhere).
        raise ReportError(
            f"{report_path}: that apply row stores no report text, so there is nothing to restore "
            "from it. It was logged before reports were stored (2026-11-04) or by a command that "
            "does not keep one; use the report file if that command wrote one."
        )
    return log.report


def restore(
    *,
    operation: str,
    report_path: str,
    write: Callable[[str, Any, Dict[str, Any]], None],
    run_by: str = "",
) -> Report:
    """Put back every row's "before" values from a report written by `run` for `operation`.

    `operation` is the CALLER's operation. The hash guard below only proves the report is one
    that was applied; it cannot say which command applied it, because the operation it checks is
    read from the report itself. Without this check a mistyped `--restore log:<id>` (or a report
    file from a sibling command) passed every guard and was written through the caller's `write`,
    which for two certification commands is the same unchecked `update(**values)` on the same
    column (review of back #287).
    """
    from common.models import DataOperationLog

    text = _read_report(report_path)
    data = json.loads(text)
    if data.get("operation") != operation:
        raise ReportError(
            f"{report_path} is a report of {data.get('operation')!r}, not of {operation!r}. " "Nothing was restored."
        )
    if _applied_log(data.get("operation", ""), text) is None:
        raise ReportError(
            f"{report_path} does not match any applied run of this operation (a dry-run report, "
            "or one changed since it was applied). Nothing was restored."
        )
    report = Report(operation=data["operation"], changes=[RowChange(**c) for c in data["changes"]])
    # The restore moves each row after -> before, so its log counts the reverse transitions
    # (review of back #119: logging the report's own counts recorded the opposite of what ran).
    reverse = Report(
        operation=report.operation,
        changes=[RowChange(c.model, c.pk, before=c.after, after=c.before, reason=c.reason) for c in report.changes],
    )
    with transaction.atomic():
        for c in report.changes:
            write(c.model, c.pk, _strip(c.before))
        DataOperationLog.objects.create(
            operation=report.operation,
            action=DataOperationLog.ACTION_RESTORE,
            report_sha256=sha256_text(text),
            counts=reverse.counts,
            run_by=run_by,
            report=text,
        )
    return report
