"""
Rebuild `certifications/data/omri_seed.csv` from OMRI's free Crop Products List PDF.

⚠️ THIS IS A MAINTAINER TOOL, NOT A DEPLOY STEP. It needs `pdftotext` (poppler) and the
   PDF, neither of which exists on the App Platform dyno. The pipeline is:

       maintainer machine:  build_omri_seed_csv  ->  omri_seed.csv  ->  commit
       production:          seed_omri_minimal (reads the committed CSV)

   Production never parses a PDF. It reads a reviewed, diffable CSV, which is the whole
   point: a parser regression shows up in a pull request rather than in a farmer's plan.

Why the catalogue was 55 rows until now
---------------------------------------
`seed_omri_minimal` and `OMRIProduct` both already record that the "OMRI is paid, so the
list must be hand-typed" premise was FALSE. The list is a free public download. Nobody
refilled the CSV after that was learned, so search reached 55 of the ~9,200 products OMRI
publishes — about one in every 168. A grower typing a real, currently-listed product got
"no match" and fell through to an operator-entered row, losing the third-party listing they
had actually earned.

Source
------
https://www.omri.org/sites/default/files/opl_pdf/CropByProduct-NOP-EN.pdf
The companion CropByCompany-NOP-EN.pdf is the same data keyed by company; this command
reads the by-product edition because the by-product ordering is what search resolves.

⛔ Crop products ONLY. OMRI publishes separate Livestock and Processing lists. A livestock
   or handling product is not in this file and must not be seeded from it.

How the parse works, and why it refuses to guess
------------------------------------------------
Each printed entry has a fixed shape inside one of three columns:

    <product name, wrapping over 1-4 lines> (<omri code>) [footnote flags l n o]
    <company, wrapping over 1-2 lines>
    <OMRI generic-material class, wrapping over 1-4 lines> (CF|CP|CT)

The code and the trailing class marker are unambiguous anchors, so name and class fall out
directly. The company/class boundary does NOT, because both sides wrap. It is resolved in
three passes, each one evidence-driven:

    1. The 83% of entries whose tail is exactly two lines are unambiguous: company, class.
       Their second lines become the class vocabulary (~289 distinct phrases).
    2. Longer tails are split at the first position whose trailing join is in that
       vocabulary, or shares its opening words with a vocabulary entry.
    3. What is left is split at the first position whose trailing join is shared by at
       least three DIFFERENT preceding texts. A phrase that appears under many companies
       is a class; a company name is not. (This is what resolves the "Anaerobic Digestate,
       from manure feedstock" family, which never once prints on a single line.)

⛔ An entry that survives all three passes keeps `manufacturer` EMPTY. It does not get the
   most-likely company. A wrong company on an OMRI row is a false attribution of a
   third-party listing — the exact class of invention this codebase keeps deleting — and
   an empty field is merely unknown. One row in 9,229 lands here.

⛔ `listing_expiration_date` is written EMPTY for every row. It is not in the PDF (OMRI
   prints it only on the per-product certificate), and a blank means UNKNOWN, never
   "current". Do not backfill it with anything derived.

Usage
-----
    poetry run python manage.py build_omri_seed_csv --pdf /path/to/CropByProduct-NOP-EN.pdf
    poetry run python manage.py build_omri_seed_csv --pdf … --edition-date 2026-09-05
    poetry run python manage.py build_omri_seed_csv --pdf … --dry-run

Then review the CSV diff, commit it, deploy, and run `seed_omri_minimal` (or
`refresh_organic_input_catalogs`) in production.
"""

import collections
import csv
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from django.core.management.base import BaseCommand, CommandError

from certifications.services.omri_verifier import looks_like_omri_code

_XHTML = "{http://www.w3.org/1999/xhtml}"

_OUT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "omri_seed.csv",
)

SOURCE_URL = "https://www.omri.org/sites/default/files/opl_pdf/CropByProduct-NOP-EN.pdf"

CSV_COLUMNS = [
    "omri_id",
    "product_name",
    "manufacturer",
    "category",
    "listing_expiration_date",
    "list_edition_date",
    "source_url",
]

# OMRI's own class codes, printed in the legend on the list's first page.
CLASS_TO_CATEGORY = {
    "CF": "crop-fertilizer",  # Crop Fertilizers and Soil Amendments
    "CP": "crop-pest-control",  # Crop Pest, Weed, and Disease Control
    "CT": "crop-management-tool",  # Crop Management Tools and Production Aids
}

# `(dow-2900)`, tolerating the line break the three-column layout puts inside a code.
#
# LOWERCASE ONLY, and that is load-bearing rather than sloppy: OMRI prints every product
# code lowercase, and the September 5, 2026 edition contains exactly ONE uppercase
# code-shaped token in 229 pages — "(LON-16)", a manufacturer's SKU printed inside the
# name of *Life-Line Organics Nitrogen 16-0-0 (LON-16) (llb-22989)*. Matching case-
# insensitively made that entry look like it carried two codes, and it was dropped. A
# case-sensitive pattern reads the SKU as part of the name, which is what it is.
CODE_RE = re.compile(r"\(\s*([a-z]{2,6})\s*-\s*(\d{1,7})\s*\)")
CLASS_END_RE = re.compile(r"\((CF|CP|CT)\)\s*$")
# Footnote markers OMRI prints after a product name: l = restricted, n/o = annotations.
TRAILING_FLAGS_RE = re.compile(r"(?:\s+[lno])+\s*$")
LEADING_FLAGS_RE = re.compile(r"^(?:\s*[lno]\b)+")
ONLY_FLAGS_RE = re.compile(r"^[lno\s]+$")
# The page number printed on its own line. See `_entries` for why it is dropped there
# rather than in FURNITURE_HEAD_RE.
PAGE_NUMBER_RE = re.compile(r"\d{1,4}")
# Page furniture, matched against a BLOCK'S FIRST LINE only. Each of these is a whole
# poppler block: the running head, the section headings, the class-code legend and the
# front-matter blurb. Anchoring on the first line is deliberate — an earlier version
# tested every line against a looser pattern (including a bare `[A-Z]{1,2}:` and a bare
# number), which condemned 54 legitimate product blocks whose company or class line
# happened to match, merged their neighbours into two-code entries, and silently cost
# the catalogue 54 rows. Furniture is recognised by how a block STARTS, nothing else.
FURNITURE_HEAD_RE = re.compile(
    r"^\s*(?:"
    r"OMRI Products List"
    r"|OMRI has determined"
    r"|PRODUCTS"
    r"|Crop Products"
    r"|Class Codes"
    r"|C[FPT]:\s"
    r")"
)

# A trailing phrase shared by at least this many distinct preceding texts is a class,
# not a company. Three is enough to exclude a company with two similarly named products.
_CLASS_OWNER_THRESHOLD = 3


def _column_cuts(page):
    """x-positions separating the page's three columns, measured from this page.

    Measured rather than hardcoded: the gaps sit near x=200 and x=390 on every page
    sampled, but a future edition that re-flows the columns should re-flow the parse
    with it instead of silently splitting entries down the middle.
    """
    starts = sorted({round(float(b.get("xMin"))) for b in page.iter(_XHTML + "block")})
    cuts, prev = [], None
    for x in starts:
        if prev is not None and x - prev > 20:
            cuts.append((prev + x) / 2.0)
        prev = x
    return cuts[:2] or [223.0, 415.0]


def _column_of(x, cuts):
    for index, cut in enumerate(cuts):
        if x < cut:
            return index
    return len(cuts)


def _is_furniture_block(block_lines):
    """True for the page furniture: running head, section titles, legend, front-matter blurb.

    Judged per BLOCK from its FIRST line, and both halves of that matter. The blurb and the
    legend are each ONE block whose interior lines read like ordinary prose ("National
    Organic Program (NOP) standards,", "Aids"), so a line-by-line filter leaves those
    orphans in the buffer and the first real entry swallows them — tta-20918 came out with
    a 223-character "product name" made of the legend plus the actual product. Matching any
    line instead over-corrects and eats real entries; see FURNITURE_HEAD_RE.
    """
    return bool(block_lines) and bool(FURNITURE_HEAD_RE.match(block_lines[0]))


def _lines(xml_path):
    """Every printed line, in reading order: column by column, top to bottom."""
    root = ET.parse(xml_path).getroot()
    for page in root.iter(_XHTML + "page"):
        cuts = _column_cuts(page)
        buckets = collections.defaultdict(list)
        for block in page.iter(_XHTML + "block"):
            x, y = float(block.get("xMin")), float(block.get("yMin"))
            text = [
                " ".join((word.text or "") for word in line.findall(_XHTML + "word"))
                for line in block.findall(_XHTML + "line")
            ]
            if _is_furniture_block(text):
                continue
            buckets[_column_of(x, cuts)].append((y, text))
        for column in sorted(buckets):
            for _, block_lines in sorted(buckets[column], key=lambda pair: pair[0]):
                for line in block_lines:
                    yield line


def _entries(xml_path):
    """Group lines into entries. An entry ends at the line carrying the class marker."""
    buffer = []
    for raw in _lines(xml_path):
        line = raw.strip()
        if not line:
            continue
        # The printed PAGE NUMBER is its own line and is not matched by FURNITURE_HEAD_RE
        # (a bare number was removed from that pattern because testing it against EVERY
        # line condemned 54 real product blocks). Landing at the START of a buffer, it
        # became the first words of the next entry's name: 228 of 9,230 rows shipped as
        # "150 Neptune's Harvest Soluble Seaweed Powder", "100 Genera", "20 Ant Out®
        # Botanical Insecticide" — one per page, sequential 1..228, verified against the
        # certificates at omri.org/mfg/<letters>/certificate/<number> (2026-09-18).
        # Dropping it only when the buffer is EMPTY is the narrow version: a digits-only
        # line mid-entry is left alone, and names that legitimately start with a number
        # ("480 g/L Spinosad SC", "20 Mule Team Borax Solubor") carry the digits on the
        # same line as the rest of the name, so they never match this at all.
        if not buffer and PAGE_NUMBER_RE.fullmatch(line):
            continue
        buffer.append(line)
        if CLASS_END_RE.search(line):
            yield buffer
            buffer = []


def _split_at_code(buffer):
    """(name, tail_lines) for one entry, or None when the code is not unambiguous."""
    joined = " ".join(buffer)
    if len(CODE_RE.findall(joined)) != 1:
        return None
    match = CODE_RE.search(joined)

    # Which physical line does the code end on, and at what offset?
    consumed, end_index, offset = 0, 0, 0
    for index, line in enumerate(buffer):
        boundary = consumed + len(line) + (1 if index else 0)
        if match.end() <= boundary:
            end_index = index
            offset = match.end() - (consumed + (1 if index else 0))
            break
        consumed = boundary

    name = TRAILING_FLAGS_RE.sub("", joined[: match.start()]).strip(" -–—")
    tail = [buffer[end_index][offset:].strip()] + buffer[end_index + 1 :]
    tail = [LEADING_FLAGS_RE.sub("", line).strip() for line in tail]
    tail = [line for line in tail if line and not ONLY_FLAGS_RE.match(line)]
    code = f"{match.group(1).lower()}-{match.group(2)}"
    return code, name, tail


def _resolve(records, vocabulary):
    """Split each record's tail into manufacturer + class. Returns the unresolved count."""
    heads = {phrase.split(" ")[0] for phrase in vocabulary}
    heads |= {" ".join(phrase.split(" ")[:2]) for phrase in vocabulary}
    unresolved = 0
    for record in records:
        tail = record["tail"]
        if len(tail) == 1:
            record["manufacturer"], record["klass"] = "", tail[0]
            continue
        if len(tail) == 2:
            record["manufacturer"], record["klass"] = tail[0], tail[1]
            continue
        cut = None
        for index in range(1, len(tail)):
            candidate = " ".join(tail[index:])
            if (
                candidate in vocabulary
                or " ".join(candidate.split(" ")[:2]) in heads
                or candidate.split(" ")[0] in heads
            ):
                cut = index
                break
        if cut is None:
            record["manufacturer"], record["klass"] = "", " ".join(tail)
            unresolved += 1
        else:
            record["manufacturer"] = " ".join(tail[:cut])
            record["klass"] = " ".join(tail[cut:])
    return unresolved


def _resolve_by_shared_tail(records):
    """Pass 3: a trailing phrase printed under many different companies is a class."""
    owners = collections.defaultdict(set)
    for record in records:
        tail = record["tail"]
        for index in range(1, len(tail)):
            owners[" ".join(tail[index:])].add(" ".join(tail[:index]))

    resolved = 0
    for record in records:
        if record["manufacturer"]:
            continue
        tail = record["tail"]
        for index in range(1, len(tail)):
            candidate = " ".join(tail[index:])
            if len(owners[candidate]) >= _CLASS_OWNER_THRESHOLD:
                record["manufacturer"] = " ".join(tail[:index])
                record["klass"] = candidate
                resolved += 1
                break
    return resolved


class Command(BaseCommand):
    help = "Rebuild certifications/data/omri_seed.csv from OMRI's free Crop Products List PDF."

    def add_arguments(self, parser):
        parser.add_argument("--pdf", required=True, help="Path to CropByProduct-NOP-EN.pdf.")
        parser.add_argument(
            "--edition-date",
            required=True,
            help=(
                'The edition printed on the list ("Updated September 5, 2026") as YYYY-MM-DD. '
                "Required, and never inferred from the file's mtime: it is what every row's "
                "freshness is judged against."
            ),
        )
        parser.add_argument("--out", default=_OUT_FILE, help="Destination CSV (default: the committed seed file).")
        parser.add_argument("--dry-run", action="store_true", help="Report what would be written; write nothing.")

    def handle(self, *args, **opts):
        pdf_path = opts["pdf"]
        if not os.path.exists(pdf_path):
            raise CommandError(f"PDF not found: {pdf_path}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", opts["edition_date"]):
            raise CommandError("--edition-date must be YYYY-MM-DD, taken from the list's own 'Updated …' line.")
        if not shutil.which("pdftotext"):
            raise CommandError("pdftotext (poppler) is required. macOS: `brew install poppler`.")

        with tempfile.TemporaryDirectory() as tmp:
            xml_path = os.path.join(tmp, "list.xml")
            self.stdout.write("Extracting text with word positions…")
            subprocess.run(
                ["pdftotext", "-bbox-layout", pdf_path, xml_path],
                check=True,
                capture_output=True,
            )
            records, skipped = [], collections.Counter()
            for buffer in _entries(xml_path):
                parsed = _split_at_code(buffer)
                if parsed is None:
                    skipped[f"codes!=1 ({len(CODE_RE.findall(' '.join(buffer)))})"] += 1
                    continue
                code, name, tail = parsed
                if not name or not tail:
                    skipped["empty name or tail"] += 1
                    continue
                records.append({"code": code, "name": name, "tail": tail})

        vocabulary = {r["tail"][1] for r in records if len(r["tail"]) == 2}
        _resolve(records, vocabulary)
        # Feed everything the first pass resolved back in; longer classes become reachable.
        vocabulary |= {r["klass"] for r in records if r["manufacturer"]}
        unresolved = _resolve(records, vocabulary)
        unresolved -= _resolve_by_shared_tail(records)

        rows, rejected, duplicates = [], [], []
        seen = set()
        for record in records:
            if not looks_like_omri_code(record["code"]):
                rejected.append(record["code"])
                continue
            if record["code"] in seen:
                duplicates.append(record["code"])
                continue
            seen.add(record["code"])
            marker = CLASS_END_RE.search(record["klass"])
            rows.append(
                {
                    "omri_id": record["code"],
                    "product_name": record["name"],
                    "manufacturer": record["manufacturer"],
                    "category": CLASS_TO_CATEGORY.get(marker.group(1) if marker else "", ""),
                    # Not in the PDF. Blank means UNKNOWN — never "current". See the module docstring.
                    "listing_expiration_date": "",
                    "list_edition_date": opts["edition_date"],
                    "source_url": SOURCE_URL,
                }
            )
        rows.sort(key=lambda row: (row["product_name"].lower(), row["omri_id"]))

        by_category = collections.Counter(row["category"] for row in rows)
        self.stdout.write("")
        self.stdout.write(f"  entries parsed          {len(records)}")
        self.stdout.write(f"  rows written            {len(rows)}")
        self.stdout.write(f"  manufacturer unresolved {unresolved}  (left blank, never guessed)")
        for category, count in sorted(by_category.items()):
            self.stdout.write(f"    {category or '(none)':<24} {count}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"  skipped                 {dict(skipped)}"))
        if rejected:
            self.stdout.write(self.style.ERROR(f"  refused (bad code shape) {len(rejected)}: {rejected[:10]}"))
        if duplicates:
            self.stdout.write(self.style.WARNING(f"  duplicate codes dropped {len(duplicates)}: {duplicates[:10]}"))

        # Every row already in the committed catalogue must survive a rebuild. These were
        # verified against the published list by hand on 2026-09-06; if the parser cannot
        # reproduce them, the parser is wrong, not the catalogue.
        if os.path.exists(_OUT_FILE):
            with open(_OUT_FILE, newline="", encoding="utf-8") as fh:
                existing = {row["omri_id"] for row in csv.DictReader(fh) if row.get("omri_id")}
            lost = sorted(existing - seen)
            if lost:
                self.stdout.write(
                    self.style.ERROR(
                        f"  ⛔ {len(lost)} row(s) in the current CSV are absent from this parse: {lost[:10]}\n"
                        "     Either the listing lapsed (check omri.org) or the parse is broken. "
                        "Resolve before committing."
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS(f"  ✓ all {len(existing)} existing rows reproduced"))

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("\n--dry-run: nothing written."))
            return

        with open(opts["out"], "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(self.style.SUCCESS(f"\nWrote {len(rows)} rows to {opts['out']}"))
        self.stdout.write("Review the diff, commit it, then run `seed_omri_minimal` where the app runs.")
