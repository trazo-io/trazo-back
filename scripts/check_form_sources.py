"""Is every certifier form in the register still the file the agent publishes today?

    python scripts/check_form_sources.py            # report, exit 1 on any change
    python scripts/check_form_sources.py --json     # the same, machine-readable

WHY THIS EXISTS
---------------
The register (`documentation/compliance/certifiers/<agent>/inventory/*.yaml`) records, for every
form, the official URL it was downloaded from and the sha256 of that file. Nothing compared the
two after the day of download. On 2026-10-10 CCOF re-published every form it has under new codes
(NOPBxx to ORGBxx), one with a new revision and three with wording changed under an unchanged
revision stamp, and the register kept pointing at URLs that now answer "Page not found". It was
found two weeks later, by hand.

This fetches each recorded URL and compares the bytes with the recorded hash. When the URL no
longer serves the file, it reads the form's landing page (`form.url` in `forms/<form>.yaml`) and
hashes every PDF or DOCX linked there, so a file that only MOVED is told apart from one that
CHANGED. A changed file is a new edition: re-run `manage.py extract_form_inventory` on it and
review the diff against the register.

Captured web forms (`.html` sources) carry the capture date in their bytes, so a hash says
nothing about them. They are listed as not checked; re-capture them with `capture_web_form`.

Standard library plus PyYAML, no Django: it runs on a bare runner on a schedule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

REGISTER = Path(__file__).resolve().parent.parent / "documentation" / "compliance" / "certifiers"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
_LINKED_FILE = re.compile(r"""href=["']([^"']+\.(?:pdf|docx))(?:\?[^"']*)?["']""", re.IGNORECASE)

UNCHANGED = "unchanged"  # the recorded URL serves the recorded file
MOVED = "moved"  # the recorded file is published at another URL linked from the landing page
CHANGED = "changed"  # the agent publishes a different file: a new edition, or a new upload of it
UNREACHABLE = "unreachable"  # neither the URL nor the landing page could be read
NOT_CHECKED = "not_checked"  # a captured web form: its bytes change with every capture

#: States that need a person.
NEEDS_REVIEW = (MOVED, CHANGED, UNREACHABLE)

#: (status, body). Status 0 means the request itself failed.
Fetch = Callable[[str], tuple]


@dataclass
class Result:
    agent: str
    form: str
    state: str
    url: str
    detail: str = ""
    candidates: list = field(default_factory=list)


def _is_web(url: str) -> bool:
    """http or https only. urllib also opens file:// and ftp://, and links come from live third-party HTML."""
    return urllib.parse.urlparse(url).scheme in ("http", "https")


def fetch(url: str) -> tuple:
    if not _is_web(url):
        return 0, b""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _is_document(body: bytes) -> bool:
    """A PDF or a DOCX (zip), never an HTML "Page not found" served with status 200."""
    return body.startswith(b"%PDF") or body.startswith(b"PK")


def _landing_url(agent_dir: Path, form: str) -> str:
    path = agent_dir / "forms" / f"{form}.yaml"
    if not path.is_file():
        return ""
    return str(((yaml.safe_load(path.read_text()) or {}).get("form") or {}).get("url") or "")


def _is_file_url(url: str) -> bool:
    return urllib.parse.urlparse(url).path.lower().endswith((".pdf", ".docx"))


def _agent_index(agent_dir: Path) -> str:
    """The agent's forms page: the landing page most of its forms name, for a form that names none of its own.

    WSDA AGR 2521's `form.url` is the PDF itself (review of back #222), so without this a moved 2521 could
    only ever read as unreachable.
    """
    pages: dict = {}
    for path in (agent_dir / "forms").glob("*.yaml"):
        url = str(((yaml.safe_load(path.read_text()) or {}).get("form") or {}).get("url") or "")
        if url and not _is_file_url(url):
            pages[url] = pages.get(url, 0) + 1
    return max(sorted(pages), key=pages.get) if pages else ""


def check_form(agent: str, form: str, source: dict, landing: str, get: Fetch = fetch) -> Result:
    url, expected = str(source.get("url") or ""), str(source.get("sha256") or "")
    if str(source.get("file") or "").lower().endswith(".html"):
        return Result(agent, form, NOT_CHECKED, url, "captured web form; re-capture with capture_web_form")
    status, body = get(url)
    if status == 200 and _is_document(body):
        if _sha(body) == expected:
            return Result(agent, form, UNCHANGED, url)
        return Result(agent, form, CHANGED, url, "the recorded URL now serves a different file")
    direct = f"the recorded URL answered {status or 'nothing'}" + ("" if status != 200 else " with no document")
    if not landing or landing == url:
        return Result(agent, form, UNREACHABLE, url, direct)
    page_status, page = get(landing)
    if page_status != 200:
        return Result(agent, form, UNREACHABLE, url, f"{direct}; the landing page answered {page_status or 'nothing'}")
    links = sorted(
        link
        for link in {
            urllib.parse.urljoin(landing, href) for href in _LINKED_FILE.findall(page.decode("utf-8", "replace"))
        }
        if _is_web(link)
    )
    for link in links:
        link_status, linked = get(link)
        if link_status == 200 and _sha(linked) == expected:
            return Result(agent, form, MOVED, url, f"{direct}; the same file is now at {link}", [link])
    return Result(agent, form, CHANGED, url, f"{direct}; no file linked from {landing} is the recorded one", links)


def check_register(register: Path = REGISTER, get: Fetch = fetch) -> list[Result]:
    results = []
    for agent_dir in sorted(p for p in register.iterdir() if (p / "inventory").is_dir()):
        index = _agent_index(agent_dir)
        for path in sorted((agent_dir / "inventory").glob("*.yaml")):
            source = (yaml.safe_load(path.read_text()) or {}).get("source") or {}
            landing = _landing_url(agent_dir, path.stem)
            if not landing or landing == source.get("url") or _is_file_url(landing):
                landing = index
            results.append(check_form(agent_dir.name, path.stem, source, landing, get))
    return results


def report(results: list[Result]) -> str:
    lines = ["| Agent | Form | State | Detail |", "|---|---|---|---|"]
    for r in sorted(results, key=lambda r: (r.state not in NEEDS_REVIEW, r.agent, r.form)):
        lines.append(f"| {r.agent} | {r.form} | {r.state} | {r.detail} |")
    counts = {state: sum(1 for r in results if r.state == state) for state in (UNCHANGED, *NEEDS_REVIEW, NOT_CHECKED)}
    summary = ", ".join(f"{n} {state}" for state, n in counts.items() if n)
    return f"{len(results)} registered forms: {summary}\n\n" + "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    results = check_register()
    print(json.dumps([asdict(r) for r in results], indent=2) if args.json else report(results))
    return 1 if any(r.state in NEEDS_REVIEW for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
