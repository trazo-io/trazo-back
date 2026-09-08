"""
Fetch the live text of § 205.601 + § 205.602 from the eCFR API and store a
hashed revision snapshot. Drift-detect vs. the previous snapshot so a human
can update the committed seed list when NOSB sunset cycles publish changes.

Why this command exists:

    `seed_national_list.py` hardcodes the § 205.601/602 list of substances
    as Python data. NOSB sunset reviews run every 5 years (most recent
    material sunset: Fall 2024), and interim Final Rule amendments happen
    outside that cycle. Without a scheduled check, our hardcoded list silently
    falls behind the regulation we claim to enforce.

    This command is **not** a parser — it does NOT attempt to reconcile
    upstream JSON into our NationalListSubstance rows (the eCFR schema is
    large and changes periodically, and a bad parse would silently corrupt
    compliance claims). Instead, it does three things:

      1. Fetches the canonical text via eCFR API v1
         (https://www.ecfr.gov/developers/documentation/api/v1).
      2. Hashes the response; compares to the latest revision stored locally.
      3. If the hash changed, emits a loud warning: "upstream has changed,
         the committed seed_national_list.py list should be reviewed."

    This gives us a timestamped audit trail proving Trazo checks the live
    regulation on a schedule, and a tripwire that humans update the seed
    when the regulation changes.

Source:
    eCFR API v1 — https://www.ecfr.gov/developers/documentation/api/v1
    Endpoint: /api/versioner/v1/full/{date}/title-7.xml?chapter=I&subchapter=M
              &part=205&subpart=G
    The {date} is resolved from /api/versioner/v1/titles.json, never from the clock —
    see the note on ECFR_TITLES.

Signalling (2026-09-06):
    A failed fetch RAISES CommandError and a successful one RETURNS "changed" or
    "unchanged". It used to write the failure to stderr and `return` — which the
    orchestrator does not capture, so a 404 was recorded as
    `IngestionRun(status="unchanged", ran_at=now)` and printed on the certifier
    packet as a catalog synced today. A caller must be able to tell the two apart
    without reading prose.

Usage:
    poetry run python manage.py sync_national_list_ecfr
    poetry run python manage.py sync_national_list_ecfr --date 2026-04-15
"""

import hashlib

from django.core.management.base import BaseCommand, CommandError

import requests

from certifications.models import NationalListRevision

ECFR_BASE = "https://www.ecfr.gov/api/versioner/v1/full"
ECFR_TITLES = "https://www.ecfr.gov/api/versioner/v1/titles.json"
TITLE = 7

# ⛔ The versioner serves an ISSUE DATE, not "now". eCFR publishes Title 7 on its own
# cadence and 404s any date past the one it has imported: on 2026-09-07 the newest issue
# was 2026-09-01 (current through 2026-09-03), so every date after that returned 404.
# This command defaulted to `date.today()`, which means it failed on every day that is
# not an issue day — it had been failing in production continuously, and the orchestrator
# reports the failure but exits 0, so nothing escalated. The date now comes from eCFR's
# own titles index.
#
# ⛔ The full-text endpoint also REQUIRES a compression-capable request and answers 406
# ("This endpoint requires response compression") without one. `requests` sends a usable
# Accept-Encoding by default; it is set explicitly here so a future header change cannot
# remove it silently.
REQUEST_HEADERS = {
    "Accept": "application/xml",
    "Accept-Encoding": "gzip, deflate",
}
# § 205.601 (synthetics allowed in crops) and § 205.602 (prohibited) both live
# in Subpart G of Part 205. The eCFR versioner endpoint's finest-grained XML
# scope is subpart-level; section-level filtering returns 404. We fetch
# Subpart G once per sync and store per-section "revision" rows keyed to the
# same underlying subpart XML — the hash still drifts when either 601 or 602
# text changes, which is the compliance signal we need.
SUBPART = "G"
SECTIONS = ("205.601", "205.602")
TIMEOUT = 30


def _slice_section_xml(xml_body: str, section: str) -> str:
    """Return just the XML slice for the given § section within Subpart G.

    Best-effort string-slice. eCFR's XML uses <DIV8 N="205.601" TYPE="SECTION">
    for section nodes (no "§ " inside the N attribute — verified against the
    live API 2026-08-09; the old '§ '-prefixed marker never matched, so both
    sections silently hashed the full Subpart G document and drift could not
    be attributed). We find the opening tag and walk to the matching closing
    tag. On any failure, we return the full body — hashing the whole document
    still detects regulation change (it just can't attribute it).
    """
    open_marker = f'N="{section}"'
    start = xml_body.find(open_marker)
    if start == -1:
        return xml_body
    # Walk back to the DIV8 open tag that owns this N attribute.
    tag_start = xml_body.rfind("<DIV8", 0, start)
    if tag_start == -1:
        return xml_body
    # Find the closing </DIV8> for this section.
    tag_end = xml_body.find("</DIV8>", start)
    if tag_end == -1:
        return xml_body[tag_start:]
    return xml_body[tag_start : tag_end + len("</DIV8>")]


def _endpoint(on_date: str) -> str:
    # Versioner XML for Title 7 → Chapter I → Subchapter M → Part 205 → Subpart G.
    return f"{ECFR_BASE}/{on_date}/title-7.xml" "?chapter=I" "&subchapter=M" "&part=205" f"&subpart={SUBPART}"


def _latest_issue_date() -> str:
    """The newest date eCFR will actually serve for Title 7.

    Asked of eCFR rather than assumed, because the alternative — today's date — is wrong
    on most days and fails closed with a 404. `latest_issue_date` is the date the title's
    text last changed, which is also what makes a stored snapshot's date mean something:
    re-running on a quiet day re-reads the same issue and the hash holds steady, instead
    of stamping a new date on identical text.
    """
    try:
        resp = requests.get(ECFR_TITLES, timeout=TIMEOUT, headers=REQUEST_HEADERS)
    except requests.RequestException as e:
        raise CommandError(f"eCFR titles index unreachable: {e}") from e
    if resp.status_code != 200:
        raise CommandError(f"eCFR titles index returned HTTP {resp.status_code} for {ECFR_TITLES}")
    for title in (resp.json() or {}).get("titles", []):
        if title.get("number") == TITLE:
            issued = title.get("latest_issue_date")
            if not issued:
                raise CommandError(f"eCFR titles index carries no latest_issue_date for title {TITLE}")
            return issued
    raise CommandError(f"eCFR titles index does not list title {TITLE}")


class Command(BaseCommand):
    help = "Fetch the current § 205.601 / § 205.602 text from eCFR and store a hashed revision."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help=(
                "ISO date to query (YYYY-MM-DD). Defaults to the newest issue date eCFR "
                "publishes for title 7 — NOT today, which the API 404s on most days."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch + hash but do not persist.",
        )

    def handle(self, *args, **opts):
        on_date = opts.get("date") or _latest_issue_date()
        dry_run = opts.get("dry_run")

        url = _endpoint(on_date)
        self.stdout.write(f"→ Fetching Subpart G (§ 205.601 + § 205.602) from {url}")
        try:
            resp = requests.get(url, timeout=TIMEOUT, headers=REQUEST_HEADERS)
        except requests.RequestException as e:
            # CommandError, not a stderr line: the orchestrator captures stdout only,
            # so a written-and-returned failure was indistinguishable from a clean run.
            raise CommandError(f"eCFR network error: {e}") from e

        if resp.status_code != 200:
            raise CommandError(f"eCFR returned HTTP {resp.status_code} for {url} — no snapshot stored")

        body = resp.text or ""
        byte_len = len(body.encode("utf-8"))
        any_change = False

        # Per-section slicing: Subpart G contains both §§ 205.601 and 205.602 in
        # the same XML document. We extract each section's slice by XML tag
        # boundary so hash drift is attributable to the right section.
        for section in SECTIONS:
            slice_body = _slice_section_xml(body, section)
            content_hash = hashlib.sha256(slice_body.encode("utf-8")).hexdigest()

            previous = NationalListRevision.objects.filter(cfr_section=section).order_by("-fetched_at").first()
            change_detected = previous is None or previous.content_hash != content_hash

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [dry-run] {section}: hash={content_hash[:12]} "
                        f"bytes={len(slice_body.encode('utf-8'))} "
                        f"changed={change_detected} (not persisted)"
                    )
                )
                continue

            NationalListRevision.objects.create(
                cfr_section=section,
                source_url=url,
                content_hash=content_hash,
                response_bytes=byte_len,
                raw_json={"xml_preview": slice_body[:4000], "query_date": on_date},
                change_detected=change_detected,
            )

            if change_detected and previous is not None:
                any_change = True
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠ {section} CHANGED since {previous.fetched_at.isoformat()}: "
                        f"prev={previous.content_hash[:12]} now={content_hash[:12]}. "
                        "Review seed_national_list.py and update the committed list."
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS(f"  ✓ {section} unchanged (hash={content_hash[:12]})"))

        if dry_run:
            return "dry-run"
        # Return value, not a word scraped out of stdout — the orchestrator reads this.
        return "changed" if any_change else "unchanged"
