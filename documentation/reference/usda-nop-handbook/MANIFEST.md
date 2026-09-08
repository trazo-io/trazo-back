# NOP Handbook — Frozen Reference (Layer 3: Guidance)

**Purpose.** Freeze the crop-relevant sections of USDA's National Organic Program Handbook so
Trazo can cite certifier expectations by file + line instead of from memory or a live URL.

**Retrieved:** 2026-08-15
**Index page:** https://www.ams.usda.gov/rules-regulations/organic/handbook
(AMS returns HTTP 403 to non-browser agents; the index was read via `r.jina.ai`, and the PDFs
download over `curl` with a browser User-Agent. The document list on that page is rendered
client-side, so the direct-PDF path `sites/default/files/media/<number>.pdf` was probed by
number — note there is **no `NOP-` prefix** on the source URL, only on our stored filename.)

---

## 🔴 The caveat that governs every use of this corpus

**This is guidance, not law.** AMS says so itself on the Handbook index page, verbatim:

> "It is important to note that the National Organic Program (NOP) Handbook is non-binding and
> any citation issued needs to reference the USDA organic regulations."

And in the page's own disclaimer:

> "The contents of this web page do not have the force and effect of law and are not meant to
> bind the public in any way."

So the discipline is the same one the crop-forms corpus already enforces, one layer down:

- SAFE: "certifiers look for…", "USDA guidance describes…", "NOP 5029 § 4.2 recommends…"
- UNSAFE: "USDA requires three suppliers", "NOP 5029 mandates…", anything that presents a
  Handbook expectation as a legal requirement
- **A product may COACH toward guidance. It must not BLOCK on guidance as though it were law.**

The binding requirement is always the CFR. See
`trazo-back/certifications/conformance/binding_clauses.py`, which maps 7 CFR 205.103, 205.201
and 205.202–205.206 clause by clause and is the only layer that carries legal force.

---

## Why this corpus exists — the "NOP 5029" problem it solves

Trazo's Planting form, its certifier packet and its demo seeder all cited **"NOP 5029"** for a
three-supplier seed-search requirement. The 2026-08 records audit flagged that citation as
unsupported, because the string "NOP 5029" appeared **nowhere in the frozen corpus** — it was
being cited from a live URL, which the corpus discipline forbids precisely because nobody can
review it later.

The document is now frozen, and it does say it. `txt/NOP-5029.txt`, § 4.2 b.1:

> "Evidence of efforts made to source organic seed, including documentation of contact with
> **three or more** seed or planting stock sources to ascertain the availability of equivalent
> organic seed or planting stock. Sources should include companies that offer organic seeds
> and planting stock."

**Both halves of the earlier product decision are now supported by a citable source:**

1. The three-source expectation is real and officially published — it was not invented, and
   coaching growers toward it is well-founded.
2. It is **not** law. § 205.204 sets no numeric count, and this Handbook is non-binding by
   AMS's own statement. So the hard save-block below three suppliers was correctly removed;
   the save now blocks at ZERO documented suppliers (a genuine § 205.204(a)(1) gap) and
   coaches above that.

§ 4.4.3 of the same document is the reason the expectation has teeth in practice:
*"Certifying agents shall verify the commercial availability requirements…"* — an ACA checks
it, which is exactly why a product should surface it without pretending it is statutory.

---

## Scope boundary

The Handbook contains many more guidance and instruction documents. Six are frozen here; the
rest are excluded on the same ICP grounds the crop-forms corpus uses — Trazo serves wholesale
tree-nut and orchard crop operations, so livestock, feed, pasture and processor guidance can
only ever produce `N/A-scope` rows.

**Probed and deliberately NOT frozen** (recorded so the omission is visible, not silent):

| Doc | Title | Why excluded |
|---|---|---|
| NOP 5008 | Reassessed Inert Ingredients | Pesticide formulation chemistry; Trazo records the product, not its inerts |
| NOP 5014 | Certification of Organic Yeast | Handling/processing scope |
| NOP 5027 | The Use of Kelp in Organic Livestock Feed | Livestock scope |
| NOP 5030 | Evaluating Allowed Ingredients … Organic Livestock Feed | Livestock scope |
| NOP 5022 | Wild Crop Harvesting | § 205.207 wild-crop scope. The ICP is cultivated orchards; a wild-crop operation harvests from land it does not plant, which is a different practice standard entirely |
| NOP 5032 | Products in the "Made with Organic ***" Labeling Category | Processed-product labeling category; the ICP sells raw crops as "organic"/"100 percent organic". Revisit if a handling scope is ever added |

**Probe coverage.** Every number from **5000 to 5038 inclusive** was requested at
`sites/default/files/media/<n>.pdf`; twelve returned 200 and the rest 404 (not published at
that path). Stated precisely because the first pass skipped five numbers while claiming a
range — and one of the skipped numbers, NOP 5022, turned out to exist. A provenance document
that overstates its own coverage is the failure this corpus discipline exists to prevent.

Beyond 5038 was not probed, and the Handbook additionally contains 2000-series instructions
addressed to certifying agents rather than to operations, which are out of scope for a
producer-facing product. Both are stated limits, not clean bills of health.

---

## Sources

| File | Pages | SHA-256 | Source URL |
|---|---|---|---|
| `pdf/NOP-5006.pdf` | 3 | `1e08d0e9b321532523131691a9c3ea36b68bdc38b320bb7e784f813a18deb144` | https://www.ams.usda.gov/sites/default/files/media/5006.pdf |
| `pdf/NOP-5012.pdf` | 3 | `271e87f9213191886d982c75e3530e9f4a0442379b7be56b3c4b1132f5488f1e` | https://www.ams.usda.gov/sites/default/files/media/5012.pdf |
| `pdf/NOP-5021.pdf` | 4 | `4aa6f882bed8637302af607751f46ac93335349c6a79ac7990bc7223dae5022b` | https://www.ams.usda.gov/sites/default/files/media/5021.pdf |
| `pdf/NOP-5025.pdf` | 4 | `32d88ecb2fcd1e394178376055789358a81a7506ff02b4a3dd773d73e059c04f` | https://www.ams.usda.gov/sites/default/files/media/5025.pdf |
| `pdf/NOP-5026.pdf` | 5 | `90fc5f860505f3b07a73da54410b427d1180eb03d7e3c7681a0feb3ef085bac2` | https://www.ams.usda.gov/sites/default/files/media/5026.pdf |
| `pdf/NOP-5029.pdf` | 6 | `dd411b29515cb96c1d24e02d3dfd4de7cadc609558209df8974fe4b0aff8c6df` | https://www.ams.usda.gov/sites/default/files/media/5029.pdf |

`txt/*.txt` are `pdftotext -layout` renderings. The PDF hashes are the provenance; the text
files are derived artifacts.

---

## What each document governs, and where Trazo touches it

| Doc | Effective | Subject | Binding clause it interprets | Trazo surface |
|---|---|---|---|---|
| **NOP 5029** | 2013-03-04 | Seeds, Annual Seedlings, and Planting Stock | § 205.204 | Planting/Transplant seed block: search rows, non-availability ground, treatment basis |
| **NOP 5021** | 2011-07-22 | Compost and Vermicompost in Organic Crop Production | § 205.203(c)(2) | Soil amendment events: C:N ratio, temperature log, method, turn count |
| **NOP 5006** | 2011-07-22 | Processed Animal Manures in Organic Crop Production | § 205.203(c)(1) | Raw-manure harvest interval validation (90/120-day) |
| **NOP 5025** | 2011-07-22 | Commingling and Contamination Prevention | § 205.201(a)(5), § 205.272 | Shared-equipment flag, cleaning link, buffer disposition, transport records |
| **NOP 5026** | **2024-03-20** | The Use of Chlorine Materials in Organic Production and Handling | § 205.605, § 205.272 | Post-harvest wash-water sanitizer fields (name, ppm applied, residual at discharge) |
| **NOP 5012** | 2011-07-22 | Approval of Liquid Fertilizers for Use in Organic Production | § 205.203(d), § 205.601 | Input application organic-approval basis |

⚠️ **Note the effective dates.** Five of the six predate SOE (88 FR 3621/3622, Jan. 19 2023) by
more than a decade. Only NOP 5026 has been revised since. Guidance written in 2011 cannot
describe supplier verification or organic fraud prevention, so — exactly as with the 2011 crop
forms — **matching this guidance is not the same as meeting the current regulation.**

## Re-pull

Re-run before the December verdict gate and diff the hashes. AMS revises guidance without
changing the URL; NOP 5026's 2024 effective date is the proof that these do move.
