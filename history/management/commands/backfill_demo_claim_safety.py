"""
In-place claim-safety backfill for the two published DEMO fixtures.

WHY THIS EXISTS INSTEAD OF `--reset`
------------------------------------
The demo seeders (`create_organic_pilot_farm`, `create_demo_user`) were hardened so
a fictional farm no longer carries real accredited certifiers, real suppliers, a real
inspector's name, resolvable certificate identifiers, or a fabricated on-chain proof.
Re-running them with `--reset` in production would apply those fixes — but it deletes
and recreates the History rows, which mints a NEW `public_id`. Every consumer URL
already handed to a prospect would 404.

This command applies the same corrections to the EXISTING rows, so `public_id` — and
therefore every link already sent — survives untouched.

WHAT IT CORRECTS
  * Real certifying bodies / suppliers / inspector replaced with invented ones
    (Certification.certifier_name, BusinessEvent.verified_certifier_name, all event
    descriptions, extra_data text, and the six OSP narrative sections).
  * Resolvable identifiers -> DEMO-* (certificate numbers; a 13-digit GLOBALG.A.P.
    GGN is publicly searchable, which is worse than a merely fake number).
  * "(DEMO)" marker on company + establishment names, so the disclosure rides into the
    consumer hero, the JSON-LD, and any screenshot or forward.
  * `Establishment.is_demo` set — the flag `common/specimen.py` reads to stamp every export
    and, since 2026-08-30, the consumer product page. The name suffix alone is read only by a
    human who is already looking; the flag is what every automated surface asks.
  * Fabricated blockchain proof removed. `blockchain_verified` is the explicitly UNSAFE
    wording in .claude/rules/compliance.md (SAFE: "blockchain-recorded"), and the seeded
    Polygon transaction hash resolves to nothing on-chain.
  * production_method -> organic where a farm holds an active USDA Organic cert but the
    production defaulted to "conventional" (contradiction on the consumer page).
  * Expired/imminently-expiring demo certificates pushed out, so the published page does
    not silently lose its organic block.
  * cover_image_url set where missing (seeders build History() directly, so the
    models.py auto-derive path never runs and the hero would be blank).
  * Coarse coordinates + approximate parcel disclosure — a demo must not resolve to a
    real field boundary.

Idempotent: safe to run repeatedly. Matches fixtures by OLD *or* NEW name.

Usage:
    poetry run python manage.py backfill_demo_claim_safety             # dry run (default)
    poetry run python manage.py backfill_demo_claim_safety --apply     # write
    poetry run python manage.py backfill_demo_claim_safety --apply --fixture solana
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from certifications.models import Certification, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from product.models import Parcel

# --------------------------------------------------------------------------- #
# Text substitutions. Longest keys first: nested substrings (CCOF inside        #
# CCOF-2024-4287, OGC inside "Organically Grown Company (OGC)") must resolve    #
# before their short forms or the short rule corrupts the long one.            #
# --------------------------------------------------------------------------- #
TEXT_REPLACEMENTS = [
    # -- certificate identifiers ------------------------------------------- #
    ("CCOF-2024-4287", "DEMO-ORG-0000"),
    ("CCOF-BN-2024-1183", "DEMO-NUR-0002"),
    ("CCOF-019845", "DEMO-ORG-0001"),
    ("BBV-2024-0891", "DEMO-POL-0000"),
    ("GGN-4052852100014-ALM-2025", "DEMO-GGP-0003"),
    ("GGN-4052852100014-2025", "DEMO-GGP-0002"),
    ("GGN-4052852-001", "DEMO-GGP-0001"),
    # -- real certifying bodies + programs ---------------------------------- #
    ("CCOF (California Certified Organic Farmers)", "Pacific Slope Organic Certifiers (DEMO)"),
    ("Xerces Society", "Pollinator Habitat Alliance (DEMO)"),
    ("Bee Better Certified", "Pollinator Friendly Certified"),
    ("Bee Better", "Pollinator Friendly"),
    ("SCS Global Services", "Coast Range Assurance Services (DEMO)"),
    ("CCOF", "PSOC"),
    # -- real inspector ------------------------------------------------------ #
    ("Sarah Chen", "R. Alvarez"),
    # -- real suppliers / buyers --------------------------------------------- #
    ("Organically Grown Company (OGC)", "Pacific Organic Distributors (POD)"),
    ("Organically Grown Company", "Pacific Organic Distributors"),
    ("Wilbur-Ellis", "Coastline Ag Supply"),
    ("Cal-West Ag Supply", "Fallbrook Farm Supply"),
    ("Brokaw Nursery", "Saticoy Grove Nursery"),
    ("Valley Stables", "Hillside Equestrian Center"),
    ("INFRA retailers", "independent natural retailers"),
    ("OGC", "POD"),
]

# CarbonHeroSection.tsx and TrustSummaryHeader.tsx both render
# `certifierName.split(' (')[0]`, so whatever precedes the first " (" IS the consumer-visible
# certifier. The DEMO marker has to live there or it is silently stripped off the most
# prominent claim on the page.
#
# The prefix was "DEMO Certifier (…)" until 2026-08-01, which read on the event card as an
# organisation literally named "DEMO Certifier" — and at 90 characters it wrapped to two lines
# in a Key Details box. "DEMO · <name>" keeps the marker in the split-surviving position, reads
# as a marker rather than a company, and is short enough for the hero's one-line clamp. The
# disclosure itself is unchanged: shortening a compliance string for looks is not a trade worth
# making.
_DEMO_CERTIFIERS = (
    "Pacific Slope Organic Certifiers",
    "Coast Range Assurance Services",
    "Pollinator Habitat Alliance",
)
CERTIFIER_FIELD_VALUES = {}
for _org in _DEMO_CERTIFIERS:
    _long = f"DEMO · {_org} (sample data, not an accredited agent)"
    # What scrub() produces from a real certifier name…
    CERTIFIER_FIELD_VALUES[f"{_org} (DEMO)"] = _long
    # …and the previous long form, so re-running this command MIGRATES rows already backfilled
    # rather than leaving two demo-certifier formats live at once.
    CERTIFIER_FIELD_VALUES[f"DEMO Certifier ({_org} — sample data, not an accredited agent)"] = _long
    # The em-dash form shipped earlier today; migrate it too.
    CERTIFIER_FIELD_VALUES[f"DEMO — {_org} (sample data, not an accredited agent)"] = _long

DEMO_DISCLOSURE = "DEMONSTRATION DATASET — invented operation, people, certifiers, and records. "

EVENT_MODELS = (
    WeatherEvent,
    ChemicalEvent,
    ProductionEvent,
    GeneralEvent,
    EquipmentEvent,
    SoilManagementEvent,
    PestManagementEvent,
    BusinessEvent,
)

# Free-text / identity fields on events that can carry a real third party's name.
EVENT_TEXT_FIELDS = ("name", "description", "observation", "performed_by")

FIXTURES = {
    "solana": {
        "company_names": ["Solana Verde Farms LLC", "Solana Verde Farms LLC (DEMO)"],
        "establishment_names": ["Solana Verde Organic Ranch", "Solana Verde Organic Ranch (DEMO)"],
        "latitude": 33.38,
        "longitude": -117.25,
        # Hero per crop; matched on the production's product name, lowercased.
        "heroes": {"avocado": "https://images.unsplash.com/photo-1726177551991-270f9e79b65e?w=1600&q=80"},
        "cert_min_expiry": date(2027, 4, 1),
    },
    "coastal": {
        "company_names": ["Coastal Valleys Ranch", "Coastal Valleys Ranch (DEMO)"],
        "establishment_names": ["Coastal Valleys Farm", "Coastal Valleys Farm (DEMO)"],
        "latitude": 34.34,
        "longitude": -119.29,
        "heroes": {
            "avocado": "https://images.unsplash.com/photo-1726177551991-270f9e79b65e?w=1600&q=80",
            "orange": "https://images.unsplash.com/photo-1528582654826-585a71fcf7f4?w=1600&q=80",
            "almond": "https://images.unsplash.com/photo-1773076088491-d6223773da0c?w=1600&q=80",
        },
        # Both demo certs had already expired or were days from expiring, which drops the
        # organic block off the published page.
        "cert_min_expiry": date(2028, 5, 31),
    },
}


def scrub(value):
    """Apply every text replacement to a string. Non-strings pass through unchanged."""
    if not isinstance(value, str):
        return value
    for old, new in TEXT_REPLACEMENTS:
        value = value.replace(old, new)
    return value


def scrub_json(value):
    """Recursively scrub strings inside dict/list JSON payloads (extra_data, OSP sections)."""
    if isinstance(value, dict):
        return {k: scrub_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_json(v) for v in value]
    return scrub(value)


class Command(BaseCommand):
    help = "Apply demo claim-safety corrections in place, preserving every production's public_id."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without this the command reports what it WOULD change and rolls back.",
        )
        parser.add_argument(
            "--fixture",
            choices=sorted(FIXTURES) + ["all"],
            default="all",
            help="Limit to one demo fixture (default: all).",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        chosen = sorted(FIXTURES) if options["fixture"] == "all" else [options["fixture"]]

        if not apply_changes:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be written. Re-run with --apply.\n"))

        try:
            with transaction.atomic():
                total = 0
                for key in chosen:
                    total += self._backfill(key, FIXTURES[key])
                if not apply_changes:
                    raise _DryRun(total)
        except _DryRun as done:
            self.stdout.write(self.style.WARNING(f"\nDRY RUN complete — {done.total} change(s) pending. Rolled back."))
            return

        self.stdout.write(
            self.style.SUCCESS("\nApplied. public_id values were NOT touched — existing links still work.")
        )

    # ------------------------------------------------------------------ #

    def _backfill(self, key, cfg):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {key} ==="))
        # Repeated `--reset` runs leave duplicate fixture companies behind, and any one
        # of them may be the row a published URL points at. Process EVERY match — a
        # .first() here would silently skip the live one.
        companies = list(Company.objects.filter(name__in=cfg["company_names"]).order_by("id"))
        if not companies:
            self.stdout.write(self.style.WARNING("  fixture not present in this database — skipped"))
            return 0
        if len(companies) > 1:
            self.stdout.write(f"  {len(companies)} duplicate fixture companies found — processing all")

        changes = 0
        for company in companies:
            changes += self._fix_company(company)

            establishments = Establishment.objects.filter(
                company=company, name__in=cfg["establishment_names"]
            ) or Establishment.objects.filter(company=company)
            for est in establishments:
                changes += self._fix_establishment(est, cfg)
                changes += self._fix_certifications(est, cfg)
                changes += self._fix_osp(est)
                for parcel in Parcel.objects.filter(establishment=est):
                    changes += self._fix_parcel(parcel)
                    for history in History.objects.filter(parcel=parcel):
                        changes += self._fix_history(history, cfg)
                        changes += self._fix_events(history)

        self.stdout.write(f"  {changes} field(s) changed")
        return changes

    def _save(self, obj, fields, label):
        obj.save(update_fields=fields)
        self.stdout.write(f"    {label}: {', '.join(fields)}")

    def _fix_company(self, company):
        fields = []
        for attr in ("name", "tradename", "description", "certifications", "sustainability_commitment"):
            current = getattr(company, attr, None)
            new = scrub(current)
            if attr == "name" and new and "(DEMO)" not in new:
                new = f"{new} (DEMO)"
            if attr == "description" and new and not new.startswith("DEMONSTRATION DATASET"):
                new = DEMO_DISCLOSURE + new
            if new != current:
                setattr(company, attr, new)
                fields.append(attr)
        if fields:
            self._save(company, fields, f"Company #{company.id}")
        return len(fields)

    def _fix_establishment(self, est, cfg):
        fields = []
        for attr in ("name", "description"):
            current = getattr(est, attr, None)
            new = scrub(current)
            if attr == "name" and new and "(DEMO)" not in new:
                new = f"{new} (DEMO)"
            if attr == "description" and new and not new.startswith("DEMONSTRATION DATASET"):
                new = DEMO_DISCLOSURE + new
            if new != current:
                setattr(est, attr, new)
                fields.append(attr)
        # A demo operation must not resolve to a real address to ~11 m.
        for attr, target in (("latitude", cfg["latitude"]), ("longitude", cfg["longitude"])):
            if getattr(est, attr, None) is not None and float(getattr(est, attr)) != target:
                setattr(est, attr, target)
                fields.append(attr)
        # 🔴 2026-08-30 — THE FLAG, not just the name.
        #
        # This command has been appending "(DEMO)" to fixture names since 2026-08-01 and never
        # set `is_demo`. The seeders do set it (`_solana_verde_base.py`), but they are
        # create-only — which is the whole reason this file exists — so every fixture row that
        # predates that line carried the marker in its NAME and False in the FLAG.
        #
        # Measured locally on 2026-08-30: 4 of 65 establishments had `is_demo=True`, and
        # neither Solana Verde nor Coastal Valleys was among them, both of them already
        # renamed "(DEMO)" by this very command.
        #
        # That flag is now load-bearing. `common/specimen.py` reads it to decide whether an
        # exported packet, CSV, OSP module, workbook or PUR filing is stamped, and since
        # 2026-08-30 whether the consumer product page carries its provenance mark. A name
        # suffix is read by a human who is already looking; the flag is what every automated
        # surface asks. Marking the name and not the flag meant the fixtures announced
        # themselves in the one place nothing checks.
        #
        # Set only for rows this command has positively identified as a FIXTURE by name — the
        # asymmetry `common/specimen.py` documents holds here too, and flipping this on a real
        # operation would stamp SPECIMEN across a legitimate grower's records.
        if not est.is_demo:
            est.is_demo = True
            fields.append("is_demo")
        if fields:
            self._save(est, fields, f"Establishment #{est.id}")
        return len(fields)

    def _fix_certifications(self, est, cfg):
        changed = 0
        for cert in Certification.objects.filter(establishment=est):
            fields = []
            for attr in ("certification_number", "certifier_name", "certification_scope"):
                current = getattr(cert, attr, None)
                new = scrub(current)
                # The certifier FIELD needs the split-surviving long form.
                if attr == "certifier_name":
                    new = CERTIFIER_FIELD_VALUES.get(new, new)
                if new != current:
                    setattr(cert, attr, new)
                    fields.append(attr)
            if cert.expiry_date and cert.expiry_date < cfg["cert_min_expiry"]:
                cert.expiry_date = cfg["cert_min_expiry"]
                fields.append("expiry_date")
            if fields:
                self._save(cert, fields, f"Certification #{cert.id}")
                changed += len(fields)
        return changed

    def _fix_osp(self, est):
        changed = 0
        for osp in OrganicSystemPlan.objects.filter(establishment=est):
            new_sections = scrub_json(osp.sections)
            if new_sections != osp.sections:
                osp.sections = new_sections
                self._save(osp, ["sections"], f"OSP #{osp.id}")
                changed += 1
        return changed

    def _fix_parcel(self, parcel):
        fields = []
        for attr in ("name", "description", "certification_type", "address", "contact_person"):
            current = getattr(parcel, attr, None)
            new = scrub(current)
            if new != current:
                setattr(parcel, attr, new)
                fields.append(attr)
        # "exact" pins a demo parcel to a real field boundary on the consumer map.
        if getattr(parcel, "location_disclosure_level", None) == "exact":
            parcel.location_disclosure_level = "approximate"
            fields.append("location_disclosure_level")
        if fields:
            self._save(parcel, fields, f"Parcel #{parcel.id}")
        return len(fields)

    def _fix_history(self, history, cfg):
        fields = []
        for attr in ("name", "description", "sold_to", "destination", "lot_id"):
            current = getattr(history, attr, None)
            new = scrub(current)
            if new != current:
                setattr(history, attr, new)
                fields.append(attr)

        # Strip the fabricated on-chain proof: an invented Polygon tx hash resolves to
        # nothing, and "blockchain_verified" is UNSAFE wording on a public page.
        extra = history.extra_data or {}
        if isinstance(extra, dict):
            fabricated = {
                "blockchain_transaction",
                "blockchain_hash",
                "smart_contract_address",
                "verification_timestamp",
                "blockchain_network",
            }
            if fabricated & set(extra) or extra.get("blockchain_verified") or extra.get("blockchain_enabled"):
                cleaned = {k: v for k, v in scrub_json(extra).items() if k not in fabricated}
                cleaned["blockchain_enabled"] = False
                cleaned["blockchain_verified"] = False
                if cleaned != extra:
                    history.extra_data = cleaned
                    fields.append("extra_data")

        # An organic-certified establishment showing a "conventional" production is a
        # contradiction on the consumer page.
        establishment = history.parcel.establishment if history.parcel else None
        if establishment and (history.production_method or "").lower() in ("", "conventional"):
            if Certification.objects.filter(
                establishment=establishment,
                certification_type="usda_organic",
            ).exists():
                history.production_method = "organic"
                fields.append("production_method")

        # cover_image_url is only auto-derived on the API creation path, so a seeded
        # production has a blank consumer hero until it is set explicitly.
        if not history.cover_image_url:
            product_name = (history.product.name if history.product else "").lower()
            hero = next((url for crop, url in cfg["heroes"].items() if crop in product_name), None)
            if hero:
                history.cover_image_url = hero
                fields.append("cover_image_url")

        if fields:
            self._save(history, fields, f"History #{history.id} ({history.public_id})")
        return len(fields)

    def _fix_events(self, history):
        changed = 0
        for model in EVENT_MODELS:
            for event in model.objects.filter(history=history):
                fields = []
                for attr in EVENT_TEXT_FIELDS:
                    if not hasattr(event, attr):
                        continue
                    current = getattr(event, attr)
                    new = scrub(current)
                    if new != current:
                        setattr(event, attr, new)
                        fields.append(attr)
                # BusinessEvent carries the certifier identity that the post_save signal
                # copies back onto Certification — scrub it or the real name returns.
                for attr in ("verified_certifier_name", "certificate_number", "seed_supplier_name", "supplier_name"):
                    if not hasattr(event, attr):
                        continue
                    current = getattr(event, attr)
                    new = scrub(current)
                    if attr == "verified_certifier_name":
                        new = CERTIFIER_FIELD_VALUES.get(new, new)
                    if new != current:
                        setattr(event, attr, new)
                        fields.append(attr)
                extra = getattr(event, "extra_data", None)
                if isinstance(extra, (dict, list)):
                    new_extra = scrub_json(extra)
                    if new_extra != extra:
                        event.extra_data = new_extra
                        fields.append("extra_data")
                if fields:
                    self._save(event, fields, f"{model.__name__} #{event.id}")
                    changed += len(fields)
        return changed


class _DryRun(Exception):
    """Rolls the transaction back at the end of a dry run."""

    def __init__(self, total):
        self.total = total
        super().__init__(total)
