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
    Endpoint: /api/versioner/v1/full/{date}/title-7.json (with subtitle-B,
    chapter I, subchapter M, part 205 implicit; we filter by regex below).

Usage:
    poetry run python manage.py sync_national_list_ecfr
    poetry run python manage.py sync_national_list_ecfr --date 2026-04-15
"""

import hashlib
from datetime import date as _date

from django.core.management.base import BaseCommand

import requests

from certifications.models import NationalListRevision

ECFR_BASE = "https://www.ecfr.gov/api/versioner/v1/full"
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

    Best-effort string-slice. eCFR's XML uses <DIV8 N="§ 205.601" TYPE="SECTION">
    for section nodes; we find that opening tag and walk to the matching
    closing tag. On any failure, we return the full body — hashing the whole
    document still detects regulation change (it just can't attribute it).
    """
    open_marker = f'N="§ {section}"'
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


class Command(BaseCommand):
    help = "Fetch the current § 205.601 / § 205.602 text from eCFR and store a hashed revision."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="ISO date to query (YYYY-MM-DD). Defaults to today (UTC).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch + hash but do not persist.",
        )

    def handle(self, *args, **opts):
        on_date = opts.get("date") or _date.today().isoformat()
        dry_run = opts.get("dry_run")

        url = _endpoint(on_date)
        self.stdout.write(f"→ Fetching Subpart G (§ 205.601 + § 205.602) from {url}")
        try:
            resp = requests.get(url, timeout=TIMEOUT, headers={"Accept": "application/xml"})
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"  network error: {e}"))
            return

        if resp.status_code != 200:
            self.stderr.write(self.style.ERROR(f"  HTTP {resp.status_code} — skipping sync (will retry next run)"))
            return

        body = resp.text or ""
        byte_len = len(body.encode("utf-8"))

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
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠ {section} CHANGED since {previous.fetched_at.isoformat()}: "
                        f"prev={previous.content_hash[:12]} now={content_hash[:12]}. "
                        "Review seed_national_list.py and update the committed list."
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS(f"  ✓ {section} unchanged (hash={content_hash[:12]})"))
