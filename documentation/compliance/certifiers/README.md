# Certifier conformance registers

**What this is.** A per-question record of how Trazo lines up against a certifying agent's own OSP
forms — the source of truth behind any statement we make about alignment. One folder per certifier,
all the same shape:

```
certifiers/
  CONFORMANCE.md          generated — never edit
  ccof/                   California Certified Organic Farmers (private ACA)
    forms/*.yaml          one file per CCOF form, one row per numbered question
    scope.yaml            forms we do not register, and why
    unmapped/*.yaml       Trazo questions this certifier's forms do not ask
  wsda/                   Washington State Dept. of Agriculture (state ACA)
    ...same shape
  otco/                   Oregon Tilth Certified Organic (private ACA, Corvallis OR)
    ...same shape — registered 2026-09-09 as a delta, see Provenance
```

A certifier counts as registered once it has at least one form file. An empty `forms/` directory is
the normal state while a new certifier is being built out and must not break the guards.

## The delta rule — read this before adding a certifier

CCOF and WSDA are both **overlays of the same federal content** (7 CFR 205.201 / the USDA Common
OSP). Their forms differ in packaging, not in the obligations underneath: CCOF asks weed, pest and
disease on one form with a practice matrix, WSDA splits them into sections F, G and H; CCOF buries
production equipment inside G6.0 C, WSDA gives it section I.

So a second certifier is registered as a **delta**, never as a fresh audit:

- where a form question asks an obligation already registered, **reuse the existing verdict** —
  same `trazo.questions`, same `status`, same `severity`, same `root_cause` — restating it in that
  certifier's terms;
- **fresh analysis only** for what the certifier asks that the others do not, and for places where
  a different split changes the answer.

This is not laziness. Two independent passes over one product *disagree about it*: that already
happened inside a single register, where nine questions were cited by one form and simultaneously
declared to have no counterpart by another. Each half passed its own check; only the intersection
found it. `cross_certifier_conflicts()` is the multi-certifier version of that guard, and it fails
the build when one certifier's register calls a Trazo question `covered` while another calls it
`not_covered`. (`partial` beside `covered` is *not* a conflict — one form legitimately asks for more
depth than another, and collapsing that would push people to overstate the weaker one.)

## Why it is data and not prose

A hand-written alignment document is stale the first time a module changes. These registers are
checked by `trazo-back/certifications/tests/test_certifier_conformance_register.py`, which fails
when they drift from the live OSP registry in either direction:

- every `module_key.question_key` named must exist in the shipped registry;
- every question of a module whose form is marked `register_status: complete` must be cited by that
  certifier's register **or** listed in its `unmapped/<module_key>.yaml` with a reason.

The human-readable statement is **generated**, never hand-typed:

```bash
cd trazo-back && poetry run python manage.py certifier_conformance          # writes CONFORMANCE.md
cd trazo-back && poetry run python manage.py certifier_conformance --check  # CI: fails if stale
```

## Register audience

Internal and honest: it states real gaps, with severity, including blockers. The certifier-facing
subset is the packet's coverage page (below) — never a second maintained document, because two
documents describing one product is how they drift apart.

## Row schema

```yaml
- ref: B1                    # the certifier's OWN numbering — not ours
  asks: "How do you monitor the effectiveness of your soil fertility plan?"
  status: partial            # covered | partial | not_covered | out_of_scope
  severity: P1               # required unless `covered`; P0..P3
  root_cause: some-slug      # required on every P0, so blockers sharing one defect count once
  trazo:
    questions: [g4_0_rotation_soil.fertility_monitoring]   # where the answer LIVES (validated)
    triggered_by: [g3_0_seeds.seedlings_used]              # answers that INDICATE the form applies
    models: [product.Parcel.soil_type]                     # optional, free text
    prints: "modules/G4_0.pdf §C; narrative § 205.201(a)(1)"
  gap: "What is missing, stated as a fact."                # required unless `covered`
  fix: "The minimal change."                               # required unless `covered`/`out_of_scope`
  reason: "Why we deliberately do not do this."            # required iff `out_of_scope`
```

`questions` and `triggered_by` are different claims and must not be conflated: a form Trazo cannot
answer at all still has triggers. Mixing them made one question read as both `covered` (by the form
that answers it) and `not_covered` (by the form it merely triggers).

**Severity** is about what a reviewer does with it, not about effort:
`P0` the packet is bounced or asserts something untrue · `P1` a request for information ·
`P2` noticed, tolerated · `P3` cosmetic.

## The packet's coverage page

`04-coverage-and-scope.pdf` in every renewal packet is generated from these registers
(`certifications/services/packet_coverage.py`). It maps form codes to the files in the ZIP, names
the forms Trazo does not generate with the reason from `scope.yaml`, states that the producer
authors the plan under § 205.201(a), and lists the modules this plan has still to finish.

Two rules that page must keep, both guarded in `certifications/tests/test_packet_coverage_page.py`:

- **Registered and generated are different axes.** W2.0 has no register entry yet but ships in
  every packet; a first cut listed it under "forms Trazo does not generate" while the ZIP contained
  it. `_PACKET_LOCATION` — not the register — is the truth about the ZIP.
- **No internal language.** Severities, `root_cause` slugs and gap notes stay here. "P0" is a
  sentence about our backlog, not about a farm's plan.

## Four traps this register has already fallen into

**An exclusion is not an absence.** `scope.yaml` lists forms we do not register. When a question
turns up that only an excluded form asks, the honest row says *why* there is no counterpart —
"CCOF asks this on the Global Market Access Application, which `ccof/scope.yaml` excludes as export-
programme enrolment" — never a bare "CCOF does not ask this". The first version of the WSDA
international-trade rows read as a finding about CCOF's forms when it was a finding about our own
scope decision.

**`covered` for the wrong reason.** Nine of 56 `covered` rows failed an adversarial re-read, none
of them because a question key was wrong: every key resolved. They failed on *aim* and *artifact* —
a topic-adjacent question cited while the right one sat uncited (a buffer-zone question answering a
harvest-commingling ask), a closed enum with no `other` against a form that offers one, a citation
naming an artifact that does not print the fact. The worst shape is a row whose `asks` was written
from Trazo's capability rather than the form's text; one said so out loud — "echoed in Trazo's own
G3.0 module" — and was deleted. If the `asks` had to be bent to fit, the row is not `covered`.

**A free-text field is a hiding place.** `trazo.models` is prose by necessity, and thirteen rows
used it to park real `module_key.question_key` citations — validated by nothing, counted by no
coverage check. They were dodging a guard that was itself wrong at the time. Fixing the guard did
not empty the hiding place; `question_keys_hidden_in_models()` does.

**One register's silence is not evidence about another's.** The single largest defect found while
completing WSDA was nine rows across §F, §G and §H that read `not_covered` and each gave the same
reason: `monitoring_scope`, `monitoring_frequency` and `monitoring_records` "cannot be cited without
contradicting their CCOF-unmapped status". WSDA asks about monitoring nine times — three questions,
once each for the weed, pest and disease plans — and CCOF asks about it never. The register was
reporting three fields that exist, are required and print as absent from the product, because a
different certifying agent had no question for them. An earlier note made the mirror-image error in
the other direction, quoting CCOF's arithmetic to call a WSDA form complete. The delta rule above
says to reuse a VERDICT about the product; it never licensed importing a conclusion about what a
form asks. `cross_certifier_conflicts` catches the `covered`-vs-`not_covered` version of this, and
it caught one during that same pass — but it cannot see a row that quietly declines to cite.

## Rules for editing

- `ref` and `asks` describe **the certifier's form**. Never reword them to match what Trazo happens
  to ask — that is how a register stops being a comparison.
- `status: covered` means the fact is capturable **and reaches an artifact a certifier reads**.
  Captured but never printed is `partial`.
- Closing a gap = flip the row in the same change that ships the fix. The register is the burn-down.
- When a form is revised, update `form.revision` and `form.retrieved`, then re-read the diff. The
  stamp is in the footer (CCOF `ORGB45, V1, R7, 9/21/2021`; WSDA `AGR 2121 (R 02/25)`).

## Provenance

**OTCO (2026-09-09).** Forms read from `tilth.org/help-center/blank-forms-all/` — the 2025 Crop
OSP ZIP (`CROP-OSP-Oregon-Tilth-2025.zip`: O1, OFPP, A1, C1–C14, W1, plus the Updates & Additions
folder: CAF, Contact Change, Crop Input Verification, FACT-04, IS, Land Transfer) and the renewal
page's OSP Update Form. OTCO publishes Word files, not PDFs; `revision` is the `rev. YYYY/MM/DD`
stamp in each file's footer (most 2025/08/27; C11/C5/C6/C9 2023/09/14; C12 2023/12/18; C2
2024/06/05; FACT-04 2022/09/01; Update Form 2024/09/20), never the 2015 date in the upload path.
OTCO gives its sections a code and no separate document number, so `document_id` equals `code`
(C2, C7, FACT-04, …); forms without a code use their published title. Two OTCO-specific shapes
worth knowing before editing: **C2 is filed once and never re-filed** — annual acreage and crop
changes travel on FACT-04, which is the artifact a renewal reviewer actually opens; and **the OSP
Update Form is OTCO's renewal application** (Step 4: confirm the plan is current, or list the
updated sections and attach), which is why it is registered `draft` with no module on exactly the
reasoning of WSDA's AGR 2516 — its substance prints in 02-annual-update.pdf and
03-change-notifications.pdf, and (complete, no module) would make the coverage page call it absent.
Registered as a delta against both earlier registers; five parallel passes each owned disjoint
`unmapped/` files, and a standalone validator replayed the guards per file before the suite ran.


CCOF forms retrieved from ccof.org 2026-08-27; WSDA forms from agr.wa.gov 2026-08-28 (URLs and
revision stamps in each file). The CCOF register was built from a field-by-field audit run against
the Calapooia Bend pilot farm using the real generated packet, workbooks and dossiers — see
`documentation/competitive/CCOF-FORM-PARITY-2026-08-27.md`. WSDA was registered as a delta against
it.

Seventeen of WSDA's 18 draft form entries were completed on 2026-09-08, taking the register to 40 of
41 forms `complete` — every module a WSDA form declares is now inside the reverse-coverage check on
the WSDA side as well as CCOF's. The eighteenth, AGR 2516 Site Update, is deliberately still draft:
it declares no module, so `complete` would assert nothing, and `packet_coverage` reads (complete, no
module) as "Trazo does not generate this form" — a claim the packet would contradict, since the
substance of a site update prints in 02-annual-update.pdf and 03-change-notifications.pdf. Its file
header carries the reasoning. 93 questions
were resolved: 58 cited against a WSDA question, 35 recorded in `wsda/unmapped/` with the reason
that agent does not ask them. Twelve rows moved from `not_covered` to `partial` because the field
they said was missing existed; six of the twelve shared a single cause — see the fourth trap above.
No row moved the other way.
