# Certifier validation question — DRAFT for Oscar to send

**Status: not sent.** Draft only. Nothing here goes out without you sending it.

**Attach TWO files** (this folder), zipped or as separate attachments:
1. `sample-certifier-packet.pdf` — **30 pages, 1.5 MB, regenerated 2026-08-15**
2. `sample-lot-tag.pdf` — 1 page, the § 205.307 nonretail container tag

⚠️ **The lot tag is not optional.** Q2 asks the reviewer to critique the container label, and
the packet states in its own words that "Label artifacts … are **not embedded in this export**."
Sending the packet alone asks them to assess something they cannot see.

### Aligned against CCOF's own checklist, 2026-08-15
Source: [Organic Grower Inspection Preparation Checklist](https://www.ccof.org/wp-content/uploads/2025/05/Farm_Inspection_Prep_Checklist.pdf)
(rev. 01/29/25) — the authoritative list of what a CCOF inspector asks a grower for, and a
better alignment target for the PACKET than the Common OSP template (which governs the PLAN).
Note it also says *"CCOF has gone digital! Most inspectors do not carry a hard copy of your
OSP"* — another reason the OSP renewal ZIP is not the artifact to send here.

Four defects were found and fixed by that comparison:
- **Lot tag truncated the certifying agent.** `organic_line[:40]` sliced by character count, so
  a real CCOF grower's tag printed `Certified organic by California Certifie`. Now width-fitted
  via `stringWidth` with wrapping. Guarded by `test_long_certifier_and_farm_names_print_in_full`
  — the old test used the 4-character alias "CCOF", which fits inside the slice.
- **The 50x yield fix was incomplete.** It corrected `History.production_amount` and stopped, so
  the harvest event still read *"Total yield: 11,200 lbs"* beside a 606,270 lb summary, and
  `quantity_sold` / `sold_to` still held pre-scaling values naming a different buyer.
  Canonical figures now live in `_solana_verde_base.py`; `audit_sample_farm` cross-checks them.
- **§ 205.301 labeling category was blank**, so the packet printed "Not recorded" on the exact
  line CCOF's SOE guidance requires on audit-trail documents.
- **The packet contradicted itself on transport** — 14 documented shipments followed by
  "Clean-Transport Affidavit on File: No" from the legacy lot-level field.

**Remaining REVIEW flags: 9** (was 11). Still unpopulated on the demo, by choice: buffer-zone /
adjoining-land record, CDFA state registration, water-source analysis, 2026 annual update,
one OMRI input absent from the OSP material list, and two reused photos. Q3 is the ninth.
Generated from production 496, **Solana Verde Organic Ranch (DEMO)** — 25 events, 15 photos,
lot `SVR-2026-HA-001`, finished 2026-04-14. The farm name carries "(DEMO)" on the page, and
there are no real growers in the system.

⚠️ **Yield corrected 2026-08-13 before any send.** The demo recorded **11,199 lb from 85
acres — 132 lb/acre**, ~50x below any commercial California Hass orchard. Everything around it
was excellent (real OMRI products, real EPA Reg 352-662, the real anthracnose pathogen, a real
distributor as buyer) and the mass balance reconciled exactly — **it reconciled on an impossible
number.** Structural checks cannot catch that. Scaled to 275,000 kg (7,994 kg/ha ≈ 7,132
lb/acre) with sales held at the same 94.5% ratio.

**Before ANY send or resend, run this with the file you are actually attaching:**

```
poetry run python manage.py audit_sample_farm --production 496 \
  --packet documentation/reference/usda-recordkeeping/sample-certifier-packet.pdf
```

Checks yield-per-hectare against crop sanity bands, sold-vs-harvested, sale-before-harvest
dates, the DO-NOT-SUBMIT banner, and — via `--packet` — that the FILE on disk is not a stale
export that disagrees with current data. Without `--packet` it only audits a freshly built
packet, which can pass while the attachment is old. Verified to catch all five defect classes.

⚠️ **Fixture chosen deliberately, 2026-08-13.** The previous attachment was a walnut production
with **2 events and 0 photos**, an input-traceability GAP, a sale dated BEFORE its harvest, and
53 post-finalization edits (test artifacts). A reviewer opening it would have learned nothing
except that the account was empty. Two other candidates (579, 289) carry the
**[NON-COMPLIANT DOSSIER — DO NOT SUBMIT TO CERTIFIER]** banner and must never be sent.
**Re-verify the artifact before any resend:** no DO-NOT-SUBMIT banner, no real operator email,
and the (DEMO) label present.

The packet's REVIEW flags are the tool working on deliberately incomplete demo data — photo
reuse across events, an OMRI input missing from the OSP material list, no water test. One of
them ("no purchase quantity is recorded on any chemical event") is question 3 below, which is
convenient: the reviewer can see the exact gap the question is about.

**Why this exists.** Every verdict in the P1–P5 audit is desk work: regulation text, code, and a
rendered artifact. Not one is a certifier saying they would accept the packet. That is the
largest remaining unknown and no further self-audit reduces it. USDA's own buffer-crop form
supplies the opening verbatim: *"Always check with your certifier to agree on what constitutes
sufficient documentation — before harvest season arrives."*

**Who.** CCOF is the natural first ask — they hold the OID-matched certificate in the test
fixture, and they anchor the November renewal window. Khalsa (`sdskhalsa@ucdavis.edu`) is the
warm grower-connector if a colder approach stalls.

### Where to send it (checked 2026-08-13)

| Address | Use | Provenance |
|---|---|---|
| **`inbox@ccof.org`** | ✅ **Send here.** CCOF's general certification inbox — a technical recordkeeping question is exactly what it is for. Open with "I'm not a client yet" so it routes to a reviewer rather than an account. | CCOF's own NOPB47 OSP form prints "send to inbox@ccof.org" (recorded in the QO teardown, `TRAZO-QO-PARITY-PLAN-2026-08-08.md`) |
| ⛔ `toppmentorship@ccof.org` (Molly Nakahara) | **Do NOT use.** Already **double-touched** — emailed Jun 26 and again Jun 29 — and under a standing no-further-contact rule until she replies. A third touch on a different topic reads as pestering. | `gtm-outreach-schedule-2026-06-27` |
| `sdskhalsa@ucdavis.edu` (UC Davis) | Fallback only, if `inbox@` goes unanswered ~2 weeks. Warm connector — ask for an introduction to a reviewer, not for the answer itself. | `gtm-programs-grants-eligibility-2026-06-29` |

No named CCOF reviewer's direct address is recorded anywhere in the repo, and I have not
invented one. Jesse Beckett Parr (Chief Program Officer) is noted as the escalation path but
with no address on file — escalate only if `inbox@` stalls, and look the address up rather
than guessing it.

For `[name]`: use the reviewer's name if a person replies first; otherwise "Hello" — a wrong
guessed name on a first contact is worse than none.

⚠️ **This is yours to send.** I do not send email on your behalf.

**Timing.** This is a technical question, not prospecting, so it does not touch the cold-outreach
freeze that runs to ~Sep 15. Send whenever. Async text only — no call ask.

**Keep it short.** A reviewer who opens this should be able to answer in five minutes without
opening the PDF, and in fifteen with it. Resist adding more questions; three is already at the
limit of what gets answered.

---

## Draft message

> **Subject:** Quick technical question on §205.103 recordkeeping output — 3 specifics
>
> Hi [name],
>
> I'm a software engineer building Trazo, an organic recordkeeping tool for specialty-crop
> growers. I'm not selling anything here — I'd value a reviewer's read on whether what we
> produce is actually usable at inspection.
>
> I've attached two files generated from a demo avocado production (no real grower data): a
> 30-page recordkeeping packet, and the one-page nonretail container tag it produces. The
> packet compiles the grower's activity records into a §205.103 audit trail — input
> applications with purchase traceability, harvest, sales, per-shipment transport, and a
> mass-balance summary.
>
> I worked from your Organic Grower Inspection Preparation Checklist, which is why the three
> questions below are the ones I couldn't answer from it.
>
> **1. In/Out Mass Balance.** Your checklist says this "may require ending and starting
> inventories," depending on the product. We reconcile harvest yield against quantity sold and
> show the balance, but we don't produce a dated in/out ledger per storage location. For a
> grower who sources nothing and just stores and ships their own crop in bulk, does the
> reconciliation satisfy that audit, or do you expect the dated inventories?
>
> **2. Nonretail container tags.** The second attachment is what we print. Two things: does it
> carry what you'd expect under §205.307(a), and since labels need CCOF approval before use —
> is a generated tag like this approved once as a template, or does each season's version need
> resubmitting?
>
> **3. Input purchase quantities.** Growers frequently leave purchase quantity blank, so the
> input side of the mass balance can't close — the packet flags it on page 26. Your checklist
> asks for input receipts at inspection. Is a missing purchase quantity a note, or a finding?
>
> Anything in the packet that would draw a question from you is useful to know, even if it's
> not on that list. And if there's a format you'd rather receive records in, I'd rather build to
> that than to my own guess.
>
> Thanks either way,
> Oscar

---

## What to do with the answer

- **Q1 decides ship-list item 8.** If reconciliation is accepted, the storage ledger drops out of
  Tier 2 and `lot_identity_maintained` can stay a documented attestation. If dated movements are
  expected, it moves up and gets scoped properly.
- **Q2 validates the Tier 0 lot-tag work** against someone who inspects containers, rather than
  against my reading of §205.307(a).
- **Q3 sets the priority of ship-list item 9** (input-side mass balance degrading silently).

Record the reply in this folder and update `usda-alignment-p5-ship-list.md` — a certifier's answer
outranks every desk verdict in that document.
