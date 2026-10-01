# Renewal forms: retrieval manifest (2026-10-01)

Phase 3 (renewal) registered the three agent renewal forms the register lacked. The originals stay
local, not committed; this file records enough to re-fetch them and prove they are the same.

## Files (retrieved 2026-10-01)

| Agent | Form | URL | sha256 | Edition |
|---|---|---|---|---|
| CCOF | Crop Update (NOPB88) | https://www.ccof.org/wp-content/uploads/2025/05/Crop-Update-NOPB88.pdf | `a1b6422a13ea092cfe102a9f9c67d17508beedf96811c16ce699f877dc6ad338` | NOPB88, V2, R1, 12/03/2024 |
| CCOF | Annual Renewal Contract (web form capture) | https://www.ccof.org/payments/ (Gravity Form `gform_5`) | `b7d4dd3135ca4491f3a1183056bac50ff9a5bc739b30f79f1c7b2e7695273459` | captured 2026-10-01 |
| WSDA | Renewal Fee Form (AGR 2521) | https://cms.agr.wa.gov/WSDAKentico/Documents/FSCS/Organic/Forms_organic/2521_Renewal_Fee_Form.pdf | `3afe3d3f572d7619754936881b2a41b0815e0e5ded5a2c010f145f892e318df6` | R 05/26 |

AUDIT.md §5 and its source table cite AGR 2521 as **R 01/24**. The edition WSDA served on
2026-10-01 is **R 05/26**; the register follows the live edition.

## How to retrieve

The two PDFs download with a browser user agent:

```bash
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/128 Safari/537.36"
curl -sSL -A "$UA" -O <url>
```

CCOF's renewal contract is a web form with no file and no revision. The page carries per-request
nonces, so the page itself hashes differently on every fetch. The capture keeps the one form and
drops what changes per request (hidden state inputs, the honeypot, the CAPTCHA), and its first
line records the URL and the capture date, which stands in for a revision:

```bash
poetry run python manage.py capture_web_form https://www.ccof.org/payments/ 5 \
    --out CCOF-Annual-Renewal-Contract.html
```

An unchanged form produces the same sha256 only on the same capture date (the date is in the
first line). To check for a changed form, capture again and compare the inventory it derives:
`manage.py extract_form_inventory ccof Annual-Renewal-Contract --source <capture>` rewrites the
inventory, and the diff is the change.

## Re-verify

```bash
poetry run python manage.py verify_form_inventory --sources <folder with the three files>
```
