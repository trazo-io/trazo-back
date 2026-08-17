"""Sanity-check a demo/sample production before its packet is sent to anyone.

WHY (2026-08-13): the packet queued for a certifier reported a season yield of **11,199 lb from
85 acres — 132 lb/acre**, roughly 50x below any commercial California Hass orchard. Everything
else in that packet was excellent: real OMRI products, a real EPA registration number, the real
avocado anthracnose pathogen, a real distributor as buyer, and a mass balance that reconciled to
the gram. The one wrong number was the headline one, and it is the first thing a reviewer who
works with avocado growers would check.

Structural checks did not catch it. The packet was internally consistent — yield, sales and
balance all agreed with each other. They agreed on an impossible number.

So this command asks a different question: **is the record PLAUSIBLE**, not merely consistent.

    poetry run python manage.py audit_sample_farm --production 496

⚠️ The yield bands below are ORDER-OF-MAGNITUDE sanity bands for catching 10x-100x data errors.
They are deliberately wide and are NOT agronomic authority — a real orchard can sit outside them
for legitimate reasons (young trees, alternate bearing, partial harvest, hail). A flag here means
"look at this", never "this is wrong".
"""

import re

from django.core.management.base import BaseCommand

#: crop keyword -> (low, high) kg per hectare. Wide on purpose; see the docstring.
YIELD_BANDS_KG_PER_HA = {
    "avocado": (3_000, 15_000),
    "walnut": (1_500, 8_000),
    "almond": (1_000, 5_000),
    "pistachio": (1_000, 6_000),
    "orange": (15_000, 60_000),
    "citrus": (15_000, 60_000),
    "lemon": (15_000, 60_000),
    "apple": (15_000, 70_000),
    "grape": (5_000, 30_000),
    "olive": (2_000, 15_000),
    "tomato": (20_000, 120_000),
    "lettuce": (15_000, 60_000),
    "strawberry": (20_000, 80_000),
}

HA_PER_ACRE = 0.404686


class Command(BaseCommand):
    help = "Plausibility-check a sample/demo production before its packet is shared externally."

    def add_arguments(self, parser):
        parser.add_argument("--production", type=int, required=True, help="History id")
        parser.add_argument(
            "--packet",
            help=(
                "Path to the PDF you are actually going to attach. Without this the command "
                "only checks a FRESHLY BUILT packet — which can pass while the file on disk is "
                "a stale export from before the data was corrected."
            ),
        )

    def handle(self, *args, **options):
        from history.models import History, ProductionEvent, SalesRecord

        try:
            history = History.objects.select_related("parcel", "product", "crop_type").get(id=options["production"])
        except History.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"No production with id {options['production']}"))
            return

        findings = []
        notes = []

        crop = (
            getattr(history.crop_type, "name", None) or getattr(history.product, "name", None) or history.name or ""
        ).lower()
        parcel = history.parcel
        area_ha = float(parcel.area) if parcel and parcel.area else None

        # --- 1. Yield plausibility, the check this command exists for -------------------
        yield_kg = float(history.production_amount or 0)
        if not yield_kg:
            findings.append("No production_amount recorded — the mass balance has no top line.")
        elif not area_ha:
            notes.append("Parcel area unknown; cannot check yield per hectare.")
        else:
            per_ha = yield_kg / area_ha
            band = next((b for k, b in YIELD_BANDS_KG_PER_HA.items() if k in crop), None)
            per_acre_lb = per_ha * HA_PER_ACRE * 2.20462
            if band is None:
                notes.append(f"No yield band for crop {crop!r}; {per_ha:,.0f} kg/ha ({per_acre_lb:,.0f} lb/acre).")
            elif per_ha < band[0]:
                findings.append(
                    f"Yield {per_ha:,.0f} kg/ha ({per_acre_lb:,.0f} lb/acre) is BELOW the {crop} sanity band "
                    f"{band[0]:,}-{band[1]:,} kg/ha. A reviewer who works with this crop will notice."
                )
            elif per_ha > band[1]:
                findings.append(
                    f"Yield {per_ha:,.0f} kg/ha ({per_acre_lb:,.0f} lb/acre) is ABOVE the {crop} sanity band "
                    f"{band[0]:,}-{band[1]:,} kg/ha."
                )
            else:
                notes.append(f"Yield {per_ha:,.0f} kg/ha ({per_acre_lb:,.0f} lb/acre) — within the {crop} band.")

        # --- 2. Mass balance: sold must not exceed harvested ---------------------------
        sales = list(SalesRecord.objects.filter(production=history))
        sold = sum(float(s.quantity or 0) for s in sales)
        if yield_kg and sold > yield_kg:
            findings.append(f"Quantity sold ({sold:,.0f}) EXCEEDS harvest yield ({yield_kg:,.0f}).")
        elif yield_kg:
            notes.append(f"Sold {sold:,.0f} of {yield_kg:,.0f} ({sold / yield_kg * 100:.1f}%).")

        # --- 2b. The SAME fact stated twice must agree -----------------------------------
        # Added 2026-08-15. The 50x yield fix corrected History.production_amount and the
        # sales rows and stopped there, so the packet went on printing "Total yield: 11,200
        # lbs" inside the harvest event beside a 606,270 lb summary, and History.quantity_sold
        # kept the pre-scaling 5,080 kg while the itemized rows said 260,000. Both survived
        # the original gate because it only ever compared the headline number to the area.
        # CCOF's Production Verification Audit ("estimated production/yield capacity vs.
        # actual production/sales") is exactly the review that opens on such a gap.
        harvest_events = list(ProductionEvent.objects.filter(history=history, type="HA"))
        event_yield = sum(float(e.yield_quantity or 0) for e in harvest_events)
        if event_yield and yield_kg and abs(event_yield - yield_kg) / yield_kg > 0.01:
            findings.append(
                f"Harvest event yield ({event_yield:,.0f}) disagrees with the production total "
                f"({yield_kg:,.0f}) — the packet prints both."
            )

        legacy_sold = float(history.quantity_sold or 0)
        if legacy_sold and sold and abs(legacy_sold - sold) / max(sold, 1) > 0.01:
            findings.append(
                f"History.quantity_sold ({legacy_sold:,.0f}) disagrees with the sum of the "
                f"itemized sales rows ({sold:,.0f}). Both are printed."
            )

        buyers = {(s.buyer_name or "").strip() for s in sales if (s.buyer_name or "").strip()}
        legacy_buyer = (history.sold_to or "").strip()
        if legacy_buyer and buyers and legacy_buyer not in buyers:
            findings.append(
                f"History.sold_to is {legacy_buyer!r} but the sales rows name "
                f"{', '.join(sorted(buyers))} — two different buyers for one lot."
            )

        # A narrative is not a field, so nothing else cross-checks it. Only the harvest
        # event's own prose is checked against its own number: that is the self-contradiction
        # case, and it stays quiet on prose that talks about something else.
        for event in harvest_events:
            text = event.description or ""
            quoted = [
                float(m.group(1).replace(",", "")) * (0.453592 if m.group(2).lower().startswith("lb") else 1.0)
                for m in re.finditer(r"([\d,]+(?:\.\d+)?)\s*(kg|kgs|lb|lbs)\b", text, re.I)
            ]
            own = float(event.yield_quantity or 0)
            if own and quoted and not any(abs(q - own) / own <= 0.02 for q in quoted):
                findings.append(
                    f"Harvest event #{event.id} records {own:,.0f} kg but its description quotes "
                    f"only {', '.join(f'{q:,.0f} kg-equiv' for q in quoted)} — the prose "
                    f"contradicts the field on the same record."
                )

        # --- 2c. CCOF grower inspection checklist, sales-side ----------------------------
        # "products must be identified as organic on external audit trail documents" and
        # "Cleaning logs: ... crop harvest & transport equipment". A blank here is a real
        # gap on the demo, not a design question, so it should never ship silently.
        missing_label = [s.invoice_number or s.id for s in sales if not s.organic_label_category]
        if missing_label:
            findings.append(
                f"{len(missing_label)} sale(s) carry no § 205.301 labeling category; the packet "
                f"prints 'Not recorded' on the line CCOF's SOE guidance requires."
            )
        missing_transport = [s.invoice_number or s.id for s in sales if not s.clean_transport_method]
        if missing_transport:
            findings.append(
                f"{len(missing_transport)} shipment(s) document no transport-cleaning method "
                f"(CCOF asks for clean-out records on harvest & transport equipment)."
            )

        # --- 3. Date coherence — the sale-before-harvest error seen on the old fixture --
        harvests = [e.date for e in ProductionEvent.objects.filter(history=history, type="HA") if e.date]
        first_harvest = min(harvests).date() if harvests else None
        for s in sales:
            if s.sale_date and first_harvest and s.sale_date < first_harvest:
                findings.append(
                    f"Sale {s.invoice_number or s.id} dated {s.sale_date} is BEFORE the first harvest "
                    f"({first_harvest}) — product cannot be sold before it is harvested."
                )
        if history.finish_date and first_harvest and first_harvest > history.finish_date.date():
            findings.append("A harvest event is dated after the production finish date.")

        # --- 4. Does the packet even build, and is it sendable? ------------------------
        try:
            import io

            from pdfminer.high_level import extract_text

            from history.services.audit_export_service import AuditExportService

            data = AuditExportService(history, certification_type="organic").generate_pdf(strict_ofpp=False).getvalue()
            flat = re.sub(r"\s+", " ", extract_text(io.BytesIO(data)))
            if "DO NOT SUBMIT" in flat or "NON-COMPLIANT DOSSIER" in flat:
                findings.append("Packet carries the DO-NOT-SUBMIT banner — never share this externally.")
            notes.append(f"Packet builds: {len(data):,} bytes.")

            # --- 5. Is the FILE you are attaching the packet this data produces? -------
            # Everything above audits a freshly built packet. The thing that actually gets
            # emailed is a file on disk, and the two drift the moment data is corrected
            # without re-exporting. Compare the substantive figures, not bytes: every export
            # stamps its own generation date, so byte equality is never true.
            packet_path = options.get("packet")
            if packet_path:
                import os

                if not os.path.isfile(packet_path):
                    findings.append(f"--packet path does not exist: {packet_path}")
                else:
                    disk = re.sub(r"\s+", " ", extract_text(packet_path))

                    def figures(text):
                        out = {}
                        for label in ("Harvest Yield", "Quantity Sold"):
                            m = re.search(label + r"[^\[]*\[([\d,]+) kg\]", text)
                            out[label] = m.group(1) if m else None
                        m = re.search(r"Lot ID\s+(\S+)", text)
                        out["Lot ID"] = m.group(1) if m else None
                        return out

                    on_disk, freshly_built = figures(disk), figures(flat)
                    drifted = [k for k in freshly_built if on_disk.get(k) != freshly_built[k]]
                    if drifted:
                        findings.append(
                            "The file you are about to attach is STALE — it disagrees with the "
                            f"current data on: {', '.join(drifted)}. Re-export before sending."
                        )
                    else:
                        notes.append(f"Attachment matches current data ({os.path.basename(packet_path)}).")
                    for banner in ("DO NOT SUBMIT", "NON-COMPLIANT DOSSIER"):
                        if banner in disk:
                            findings.append(f"The FILE on disk carries the {banner} banner.")
        except Exception as exc:  # noqa: BLE001 — an audit tool must report, not crash
            findings.append(f"Packet failed to build: {exc}")

        # --- report -------------------------------------------------------------------
        self.stdout.write(f"\nSample farm audit — {history.name} (id {history.id})")
        self.stdout.write(f"  crop={crop!r} parcel={getattr(parcel, 'name', '?')} area={area_ha} ha\n")
        for n in notes:
            self.stdout.write(f"  · {n}")
        if findings:
            self.stdout.write(self.style.ERROR(f"\n{len(findings)} finding(s) — do NOT share until resolved:"))
            for f in findings:
                self.stdout.write(self.style.ERROR(f"  ✗ {f}"))
        else:
            self.stdout.write(self.style.SUCCESS("\nNo plausibility findings. Safe to share."))
