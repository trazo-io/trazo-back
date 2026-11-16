"""Build Coldwater Bench Orchard, the orchard specimen: a Washington apple and pear farm under WSDA.

Why this exists
---------------
The overall review of 2026-11 found that no seeded farm looks like the grower Trazo sells to.
Calapooia Bend is blueberries and vegetables under a fictional certifier; the walnut showcase is a
California nut farm. No orchard packet had been read for WSDA or CCOF, and the spray record has
since gained the columns an orchard uses every week: the block table's orchard columns, "not on
the source record", wind and temperature, carrier, apparatus plate, applicator contacts and
profiles, tank mixes, the Washington export (back #391, #395, #399, #404, #408, #413). This farm
holds all of them, so every future packet read starts from an orchard.

Where the data comes from
-------------------------
The rehearsal kit, `documentation/gtm-v3/rehearsal/`: Dan Tollefsen's spray sheet
(`spray-and-field-log-2026.csv`), Karen's binder page, his email, and the answer key's fourteen
traps. Every date, block, product, rate, carrier volume, acreage and bin count below is the
sheet's. Where the sheet is silent the record is silent too, and the Washington export names the
blank: no spray carries an EPA number, a REI, a PHI or a total amount, because the sheet gives
rates and none of those.

The traps are kept as the kit sets them, because a specimen that hides them shows a better farm
than the records support:
  * the "mid May" first Cyd-X cover has no date, so it is NOT recorded (never pick a date);
  * the duplicated June 3 Surround row is ONE record;
  * the neighbor's June 15 Roundup is a possible drift incident on Block 1, never an input;
  * Block 3 is 21.6 acres (the FSA figure the sheet itself uses on April 10), its seller's last
    prohibited spray is "fall 2022 I think" with no affidavit on file, and whether it is on the
    certificate is left unanswered;
  * the compost has no feedstock or process sheet, and Block 4 got none;
  * the calcium chloride is a foliar spray for bitter pit on Honeycrisp;
  * the Entrust "6 oz" and the second cover's "3oz" have no unit basis, so no rate is stored;
  * the stand sales ("~30 bins") have no number and are not recorded; Block 3 is still picking.

Additions the kit does not hold, each made so the specimen shows a record column, and each said here:
  * wind, temperature, start and stop time and the apparatus line come from the applicator's
    field card for most sprays. The May 29 second cover has no card: its time and concentration
    are marked "not on the source record", and its wind and temperature are blank;
  * one tank mix (Entrust SC with an OMRI-listed spreader-sticker on Blocks 1 and 2, June 12),
    written through the tank-mix service the API uses, because the sheet has no tank row;
  * Block 5, a young block bought in late 2024 from a fictional seller whose affidavit dates a
    glyphosate application on 2024-10-15, so one parcel is in transition with a dated prohibited
    input inside the 36 months;
  * rootstocks on the crop table, an applicator license for Dan, and "DK" read as Dan (Dan K.
    Tollefsen), so the sheet's initials resolve to the profile the records copy from.

Honesty constraints
-------------------
Nobody real (back #386): the company, people, packer, seller and nursery are fictional; phones are
555-01xx; streets and parcel numbers say "Sample". The plan names WSDA as its certifying agent
because that is the path this specimen exists to read, but no WSDA certificate, letter or number is
fabricated: the certificate row is the operator's self-reported statement with no number, and no
document claims to be from the department. The block outlines sit on upland ground well away from
Manson's orchards; land ownership could not be checked against OpenStreetMap when this was written
(the Overpass API was unreachable), so the outlines must never be read as anyone's property.

The establishment is `is_demo=True`, so every packet, export, workbook and PDF built from it is
stamped a specimen (`common/specimen.py`).

Usage
-----
    poetry run python manage.py seed_coldwater_bench --owner-email you@example.com
    poetry run python manage.py seed_coldwater_bench --owner-email you@example.com --rebuild
"""

from __future__ import annotations

import math
import os
import uuid
from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from company.models import Establishment
from history.constants import CHEMICAL_EVENT_TYPE
from history.models import ChemicalEvent, GeneralEvent, Production, ProductionEvent, SalesRecord, SoilManagementEvent
from product.models import Parcel, ParcelCropHistory, ParcelPlannedCrop, Product
from users.models import User

from .seed_calapooia_bend import Command as CalapooiaCommand
from .seed_showcase_walnut_farm import _load_osp_answers, _module_entry

OSP_ANSWERS_PATH = os.path.join(os.path.dirname(__file__), "_coldwater_bench_osp_answers.json")

FARM_NAME = "Coldwater Bench Orchard"
COMPANY_NAME = "Coldwater Bench Orchard LLC"
AGENT_NAME = "Washington State Department of Agriculture"
SEASON_YEAR = 2026
ACRES_PER_HECTARE = 2.47105381467

#: Fixed so a reseed derives the same group ids (the API mints them client side).
UUID_NAMESPACE = uuid.UUID("6f1d3c52-0b1e-4d55-9a57-0c01dbe0b0b5")

ADDRESS = {"street": "100 Sample Bench Rd", "city": "Manson", "state": "WA", "zip": "98831", "country": "USA"}
FULL_ADDRESS = f"{ADDRESS['street']}, {ADDRESS['city']}, {ADDRESS['state']} {ADDRESS['zip']}"
FARM_PHONE = "(509) 555-0147"
FARM_EMAIL = "karen@coldwaterbench.example"

DAN = {
    "full_name": "Dan Tollefsen",
    "license_number": "SAMPLE-55501",
    "license_state": "WA",
    "address": FULL_ADDRESS,
    "phone": FARM_PHONE,
}
RAFA = {
    "full_name": "Rafael Ibarra",
    "license_number": "",
    "license_state": "",
    "address": "",
    "phone": "(509) 555-0163",
}
CREW = "Orchard crew"

#: The apparatus line on the field card. A tractor-drawn air-blast sprayer carries no plate, and the
#: card says so rather than leaving the box empty (the column holds 20 characters).
NO_PLATE = "None (farm tractor)"

PACKER = "Sample Bench Packing Co."

#: Blocks west to east on the bench, Block 1 against the north fence. Outlines are drawn to the
#: block's acreage so a measured outline agrees with the acres on the record.
#: Centre of the bench. Upland ground north-west of Manson, away from the town's orchards (see the
#: module notes: ownership not verified).
BENCH_CENTRE = (48.0500, -120.3000)
BLOCKS = [
    {
        "key": "B1",
        "name": "Block 1 Gala",
        "block": "1",
        "acres": Decimal("12.5"),
        "offset": (0.0016, -0.0050),
        "crop": "Apples",
        "variety": "Gala",
        "rootstock": "M.9 T337",
        "year_planted": 2012,
        "bearing": "bearing",
        "began": date(2012, 3, 1),
        "apn": "SAMPLE-CB-01",
        "description": "Gala planted 2012 on drip from the farm well. The north fence runs along a neighbor's "
        "conventional cherries, behind a 25 ft grass strip and a poplar row.",
    },
    {
        "key": "B2",
        "name": "Block 2 Gala",
        "block": "2",
        "acres": Decimal("8.0"),
        "offset": (-0.0012, -0.0058),
        "crop": "Apples",
        "variety": "Gala",
        "rootstock": "M.9 T337",
        "year_planted": 2016,
        "bearing": "bearing",
        "began": date(2012, 3, 1),
        "apn": "SAMPLE-CB-02",
        "description": "Gala planted 2016 on drip from the farm well.",
    },
    {
        "key": "B3",
        "name": "Block 3 Honeycrisp",
        "block": "3",
        "acres": Decimal("21.6"),
        "offset": (0.0004, 0.0012),
        "crop": "Apples",
        "variety": "Honeycrisp",
        "rootstock": "G.41",
        "year_planted": 2019,
        "bearing": "bearing",
        "began": date(2023, 3, 1),
        "apn": "SAMPLE-CB-03",
        "description": "Honeycrisp planted 2019 by the previous owner; bought in 2023. 21.6 acres on the FSA map "
        "(the farm has also called it 22). Drip from the farm well.",
    },
    {
        "key": "B4",
        "name": "Block 4 d'Anjou",
        "block": "4",
        "acres": Decimal("6.3"),
        "offset": (-0.0020, 0.0070),
        "crop": "Pears",
        "variety": "d'Anjou",
        "rootstock": "",
        "year_planted": None,
        "bearing": "bearing",
        "began": date(2012, 3, 1),
        "apn": "SAMPLE-CB-04",
        "description": "An old block of d'Anjou pears. Irrigated from the district ditch, not the well.",
    },
    {
        "key": "B5",
        "name": "Block 5 Honeycrisp (transition)",
        "block": "5",
        "acres": Decimal("4.0"),
        "offset": (0.0030, 0.0080),
        "crop": "Apples",
        "variety": "Honeycrisp",
        "rootstock": "G.41",
        "year_planted": 2023,
        "bearing": "non_bearing",
        "began": date(2024, 11, 1),
        "apn": "SAMPLE-CB-05",
        "description": "Young Honeycrisp, not yet bearing, bought in November 2024 from a conventional neighbor. "
        "In transition: the seller's last prohibited application was glyphosate on 2024-10-15.",
    },
]

#: Catalogue rows this farm's records cite, by the publisher's own identifier. Read from the
#: committed catalogue CSVs when the database has not loaded them, never authored here.
CATALOG = {
    "wsda": {"Entrust SC": "2072", "Surround WP": "275"},
    "omri": {"Cyd-X": "ttc-3084", "Brandt Organics SKH Sticker Extender": "cle-5439"},
}


def _dt(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=dt_tz.utc)


def _hectares(acres: Decimal) -> float:
    return round(float(acres) / ACRES_PER_HECTARE, 4)


def _polygon(acres: Decimal, offset) -> dict:
    """A rectangle twice as wide as it is tall whose area is the block's acreage."""
    lat0, lon0 = BENCH_CENTRE[0] + offset[0], BENCH_CENTRE[1] + offset[1]
    square_m = float(acres) * 4046.8564224
    height_m = math.sqrt(square_m / 2)
    width_m = 2 * height_m
    dlat = height_m / 111_320 / 2
    dlon = width_m / (111_320 * math.cos(math.radians(lat0))) / 2
    ring = [
        [round(lon0 - dlon, 6), round(lat0 + dlat, 6)],
        [round(lon0 + dlon, 6), round(lat0 + dlat, 6)],
        [round(lon0 + dlon, 6), round(lat0 - dlat, 6)],
        [round(lon0 - dlon, 6), round(lat0 - dlat, 6)],
        [round(lon0 - dlon, 6), round(lat0 + dlat, 6)],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


class _SeedRequest:
    """The request a serializer's context expects, standing for the operator's own session."""

    def __init__(self, user):
        self.user = user

    def build_absolute_uri(self, location=""):
        return location


class Command(BaseCommand):
    help = "Build the Coldwater Bench Orchard specimen (WA apples and pears, WSDA) and its 2026 season."

    def add_arguments(self, parser):
        parser.add_argument(
            "--owner-email",
            required=True,
            help="Existing user who will own the company and be credited as the operator.",
        )
        parser.add_argument(
            "--rebuild",
            action="store_true",
            help="Delete an existing Coldwater Bench specimen first. Without this the command refuses "
            "rather than creating a second copy.",
        )

    # ------------------------------------------------------------------
    @transaction.atomic
    def handle(self, *args, **options):
        owner = User.objects.filter(email=options["owner_email"]).first()
        if owner is None:
            raise CommandError(f"No user with email {options['owner_email']!r}.")
        self.owner = owner

        existing = Establishment.objects.filter(name=FARM_NAME)
        # Same guard as seed_calapooia_bend: --rebuild deletes a farm, so it only ever touches one
        # this command created (is_demo=True). A real operation with the name is refused outright.
        real = existing.filter(is_demo=False)
        if real.exists():
            raise CommandError(
                f"Refusing to touch {FARM_NAME!r}: establishment(s) {', '.join(str(e.pk) for e in real)} "
                "exist with is_demo=False. This command only creates and replaces demo farms."
            )
        existing = existing.filter(is_demo=True)
        if existing.exists():
            if not options["rebuild"]:
                raise CommandError(
                    f"{FARM_NAME!r} already exists (id {', '.join(str(e.pk) for e in existing)}). "
                    "Pass --rebuild to replace it."
                )
            for est in existing:
                self.stdout.write(f"  removing existing demo establishment {est.pk}")
                CalapooiaCommand._teardown(est)
                est.delete()

        # The company is found by name and its applicator profiles are replaced below, so a company of
        # that name holding a real farm is refused rather than written into.
        if Establishment.objects.filter(company__name=COMPANY_NAME, is_demo=False).exists():
            raise CommandError(f"Refusing to touch {COMPANY_NAME!r}: it holds an establishment with is_demo=False.")

        # The company, the owner's membership and the comped Pilot plan: the same three things
        # seed_calapooia_bend sets up, by the same method (its docstring says why each matters).
        company, membership = CalapooiaCommand._company(self, {"company": {"name": COMPANY_NAME}}, owner)
        self._company_profile(company)
        applicators = self._applicators(company)
        est = self._establishment(company)
        self._certification(est)
        self._contacts(est)
        packer = self._packer(est)
        self._equipment(est)
        catalog = self._catalog_rows()
        parcels = self._parcels(est)
        seasons = self._seasons(parcels, packer)
        counts = self._season_records(parcels, seasons, applicators, catalog)
        osp = self._osp(est, catalog)
        self._finish_and_seal(seasons)

        self.stdout.write(
            self.style.SUCCESS(
                f"Coldwater Bench built: establishment {est.pk}, {len(parcels)} parcels, {len(seasons)} seasons, "
                f"{counts['sprays']} spray records ({counts['tank_lines']} in one tank), "
                f"{counts['other']} other records, {counts['sales']} sale, OSP v{osp.version_number} "
                f"filed with {osp.certifier_name}, is_demo={est.is_demo}"
            )
        )
        self.stdout.write(f"  company      : {company.name} (#{company.pk})")
        self.stdout.write(f"  access       : {owner.email} as {membership.get_role_display()}")

    # ------------------------------------------------------------------ operation
    def _company_profile(self, company):
        company.tradename = FARM_NAME
        company.address = ADDRESS["street"]
        company.city = ADDRESS["city"]
        company.state = ADDRESS["state"]
        company.zip_code = ADDRESS["zip"]
        company.country = ADDRESS["country"]
        company.legal_structure = "llc"
        company.contact_email = FARM_EMAIL
        company.contact_phone = FARM_PHONE
        company.primary_commodities = "Apples, pears"
        company.save()

    def _applicators(self, company):
        """Dan, the licensed applicator, and Rafa, a crew member who sprays without a license.

        The company outlives a --rebuild (it is found by name), so its profiles are replaced here
        rather than added to. A record copies the profile's text at save; nothing links back.
        """
        Applicator = apps.get_model("company", "Applicator")
        Applicator.objects.filter(company=company).delete()
        return {
            "dan": Applicator.objects.create(company=company, **DAN),
            "rafa": Applicator.objects.create(company=company, **RAFA),
        }

    def _establishment(self, company):
        centre_lat, centre_lon = BENCH_CENTRE
        return Establishment.objects.create(
            company=company,
            # Never inherited from anything: the flag that marks every export a specimen.
            is_demo=True,
            name=FARM_NAME,
            address=ADDRESS["street"],
            city=ADDRESS["city"],
            state=ADDRESS["state"],
            zip_code=ADDRESS["zip"],
            country=ADDRESS["country"],
            zone="Bench above the north shore of Lake Chelan, Chelan County",
            latitude=centre_lat,
            longitude=centre_lon,
            contact_person="Karen Tollefsen",
            contact_phone=FARM_PHONE,
            contact_email=FARM_EMAIL,
            email=FARM_EMAIL,
            phone=FARM_PHONE,
            description="Family apple and pear orchard above Manson: Gala, Honeycrisp and d'Anjou on four bearing "
            "blocks and one young block in transition. Dan sprays, with Rafa; Karen keeps the records. "
            "All fruit goes in bins to the packer except a few bins sold at the farm stand.",
            type="crop_farm",
            establishment_type="crop_farm",
            farming_method="organic",
            total_acreage=float(sum(b["acres"] for b in BLOCKS)),
            crops_grown=["Apples", "Pears"],
            water_sources=["Farm well (drip on Blocks 1, 2, 3 and 5)", "Irrigation district ditch (Block 4)"],
            irrigation_methods=["Drip"],
            certifier_renewal_date="03-01",
            certifier_renewal_date_agent="wsda",
            has_split_operation=False,
        )

    def _certification(self, est):
        """The operator's own statement that the farm is certified. Self-reported, no number.

        No certificate number, letter or copy is made up for a real agency (module notes): the
        number stays blank and the packet names it.
        """
        Certification = apps.get_model("certifications", "Certification")
        Certification.objects.create(
            establishment=est,
            certification_type="usda_organic",
            certifier_name=AGENT_NAME,
            certification_number="",
            certification_scope="crops",
            certified_items=["Apples", "Pears"],
            verification_status="self_reported",
            notes="Specimen farm: the certificate number and copy are not on file. No certificate exists for this "
            "fictional operation.",
        )

    def _contacts(self, est):
        OperationContact = apps.get_model("certifications", "OperationContact")
        OperationContact.objects.create(
            establishment=est,
            created_by=self.owner,
            name="Dan Tollefsen",
            title="Owner and manager",
            phone=FARM_PHONE,
            is_legally_responsible=True,
            is_authorized_representative=True,
            is_responsibly_connected=True,
            connection="manager",
        )
        OperationContact.objects.create(
            establishment=est,
            created_by=self.owner,
            name="Karen Tollefsen",
            title="Records and office",
            phone=FARM_PHONE,
            email=FARM_EMAIL,
            is_primary_contact=True,
            is_billing_contact=True,
            is_responsibly_connected=True,
            connection="manager",
        )

    def _packer(self, est):
        """The packer that collects, stores, packs and sells the fruit. Fictional.

        Its certificate number, certifier and dates are not in the binder, so they stay blank.
        """
        PHF = apps.get_model("certifications", "PostHarvestFacility")
        return PHF.objects.create(
            establishment=est,
            name=PACKER,
            facility_type="packer",
            role="both",
            operated_by="another_operation",
            city="Manson",
            state="WA",
            country="USA",
            verification_status="self_reported",
            products_detail="Apples (Gala, Honeycrisp) and d'Anjou pears, received in field bins.",
            notes="Collects full bins at the orchard with its own truck. A copy of its organic certificate is not "
            "yet in the binder.",
            created_by=self.owner,
        )

    def _equipment(self, est):
        Equipment = apps.get_model("certifications", "ProductionEquipment")
        for row in (
            {
                "name": "Tow-behind air-blast sprayer, 500 gal",
                "use": "application",
                "cleaning_method": "Rinsed with well water at the shop after each spray; the rinse is sprayed out on "
                "the block just treated.",
                "cleaning_materials": "Well water only",
            },
            {
                "name": "Orchard tractor",
                "use": "other",
                "cleaning_method": "Works only this orchard; washed down at the end of the season.",
                "cleaning_materials": "Well water only",
            },
            {
                "name": "Bin trailer",
                "use": "harvest",
                "cleaning_method": "Swept out before the first pick.",
                "cleaning_materials": "None",
            },
        ):
            Equipment.objects.create(
                establishment=est, created_by=self.owner, dedicated_organic=True, ownership="own", **row
            )

    def _catalog_rows(self):
        """The OMRI and WSDA rows the records name, created from the committed catalogue CSVs when the
        database has none (a CI or fresh database). Never authored: the row is the publisher's."""
        import csv

        from certifications.services.omri_verifier import looks_like_omri_code
        from certifications.services.registry_identifiers import is_real_wsda_product_number

        WSDA = apps.get_model("certifications", "WSDAMaterial")
        OMRI = apps.get_model("certifications", "OMRIProduct")
        data_dir = os.path.join(apps.get_app_config("certifications").path, "data")
        out = {}
        for source, model, id_field, name_field, filename, check in (
            ("wsda", WSDA, "wsda_id", "brand_name", "wsda_seed.csv", is_real_wsda_product_number),
            ("omri", OMRI, "omri_id", "product_name", "omri_seed.csv", looks_like_omri_code),
        ):
            wanted = CATALOG[source]
            with open(os.path.join(data_dir, filename), encoding="utf-8") as fh:
                published = {row[id_field]: row for row in csv.DictReader(fh)}
            for label, ident in wanted.items():
                if not check(ident) or ident not in published:
                    raise CommandError(f"{source} identifier {ident!r} for {label} is not in {filename}.")
                obj = model.objects.filter(**{id_field: ident}).first()
                if obj is None:
                    row = published[ident]
                    fields = {f.name for f in model._meta.fields}
                    obj = model.objects.create(**{k: v for k, v in row.items() if k in fields and v != ""})
                out[label] = obj
        return out

    # ------------------------------------------------------------------ land
    def _parcels(self, est):
        Affidavit = apps.get_model("certifications", "LandownerAffidavit")
        parcels = {}
        for block in BLOCKS:
            answers = {
                "county": "Chelan",
                "site_tenure": "own",
                "livestock_present": "none",
                "treated_lumber_present": False,
                "container_production": False,
                "acres_to_certify": str(block["acres"]),
                "treated_seed_planted": "no",
                "location_same_as_operation": "yes",
                # Steel posts and conduit carry the trellis wires; no treated wood on any block.
                "treated_lumber_noncontact_present": False,
            }
            if block["key"] in ("B1", "B2", "B4"):
                answers.update(
                    {
                        "currently_certified": "yes",
                        "prior_certifier_name": AGENT_NAME,
                        "certified_operation_name": COMPANY_NAME,
                        "full_prior_site_area": "entire",
                        "planned_crops": f"{block['crop']} ({block['variety']}) on the whole block; the planting continues.",
                        "no_lapse_attested": True,
                    }
                )
            if block["key"] == "B1":
                answers["no_adjoining_prohibited"] = False
            if block["key"] in ("B2", "B4"):
                # Inner blocks: own blocks, the farm road and the shop on every side.
                answers["no_adjoining_prohibited"] = True
            if block["key"] == "B5":
                answers.update(
                    {
                        "currently_certified": "no",
                        "certification_status_requested": "organic",
                        "expected_first_organic_harvest": "2027-10-16",
                        "dlpm_none_within_tenure": True,
                        "no_inputs_within_tenure": True,
                    }
                )
            # Block 3: certification status deliberately unanswered (the kit's biggest open question).
            buffers = []
            if block["key"] == "B1":
                buffers.append(
                    {
                        "direction": "North",
                        "adjoining_land_use": "Neighbor's conventional cherry orchard",
                        "adjacent_is_organic": False,
                        "buffer_type": "Grass strip and a poplar row",
                        "buffer_width_ft": 25.0,
                        "buffer_width_m": 7.6,
                        "crop_grown_in_buffer": "",
                        "drift_risk": "medium",
                        "neighbor_notified": False,
                        "neighbor_notification_date": None,
                        "prevention": "25 ft grass strip and the poplar row; no fruit trees in the strip.",
                        "prohibited_use_last_date": None,
                    }
                )
            if block["key"] == "B5":
                buffers.append(
                    {
                        "direction": "North",
                        "adjoining_land_use": "The seller's conventional apple orchard (Sample Ridge Orchard Co.)",
                        "adjacent_is_organic": False,
                        "buffer_type": "Mowed grass strip",
                        "buffer_width_ft": 30.0,
                        "buffer_width_m": 9.1,
                        "crop_grown_in_buffer": "",
                        "drift_risk": "medium",
                        "neighbor_notified": False,
                        "neighbor_notification_date": None,
                        "prevention": "30 ft mowed strip with no trees in it, kept when the block was bought.",
                        "prohibited_use_last_date": None,
                    }
                )
            parcel = Parcel.objects.create(
                establishment=est,
                name=block["name"],
                description=block["description"],
                area=_hectares(block["acres"]),
                polygon=_polygon(block["acres"], block["offset"]),
                map_metadata={
                    "center": {
                        "lat": BENCH_CENTRE[0] + block["offset"][0],
                        "lng": BENCH_CENTRE[1] + block["offset"][1],
                    },
                    "source": "operator-drawn",
                    "zoom": 16,
                },
                buffer_zones=buffers or None,
                application_answers=answers,
                apn=block["apn"],
                address=f"{FULL_ADDRESS} (Block {block['block']})",
                date_began_managing=block["began"],
                treated_lumber_present=False,
                certified=block["key"] in ("B1", "B2", "B4"),
            )
            ParcelPlannedCrop.objects.create(
                parcel=parcel,
                crop=block["crop"],
                variety=block["variety"],
                acres=block["acres"],
                block_name=block["block"],
                rootstock=block["rootstock"],
                year_planted=block["year_planted"],
                bearing_status=block["bearing"],
                expected_harvest=None if block["bearing"] == "non_bearing" else self._expected_harvest(block),
            )
            self._land_history(parcel, block)
            if block["key"] == "B5":
                Affidavit.objects.create(
                    parcel=parcel,
                    farm_name="Sample Ridge Orchard Co.",
                    field_name="North parcel (now Block 5)",
                    field_acres=float(block["acres"]),
                    signer_role="prior_manager",
                    previous_manager_name="Sample Ridge Orchard Co.",
                    previous_manager_address="200 Sample Ridge Rd, Manson, WA 98831",
                    previous_manager_phone="(509) 555-0188",
                    landowner_name="Sample Ridge Orchard Co.",
                    management_period_start=date(2023, 4, 1),
                    management_period_end=date(2024, 10, 31),
                    no_materials_applied=False,
                    yearly_history=[
                        {
                            "year": 2024,
                            "crop": "Apples (Honeycrisp), young trees, not bearing",
                            "inputs": "Glyphosate (tree-row weed control)",
                            "manufacturer": "",
                            "date_applied": "2024-10-15",
                        }
                    ],
                    last_prohibited_date=date(2024, 10, 15),
                    attestation_text="The block was farmed conventionally until sold. The last prohibited material, "
                    "glyphosate along the tree rows, was applied on 2024-10-15.",
                    previous_manager_signed_date=date(2024, 11, 1),
                    notes="Specimen affidavit from a fictional seller. The signed copy is not uploaded.",
                    created_by=self.owner,
                )
            self._map(est, parcel, block, buffers, answers)
            parcels[block["key"]] = parcel
        return parcels

    def _map(self, est, parcel, block, buffers, answers):
        """The block map an operator uploads with a site application, drawn from the parcel's own row
        the way seed_calapooia_bend draws its maps, and stamped SPECIMEN like every file of this farm."""
        from documents.services.filing import file_document

        from .seed_calapooia_bend import _specimen_map_pdf

        status = {
            "B1": "certified organic",
            "B2": "certified organic",
            "B4": "certified organic",
            "B3": "certification status to confirm",
            "B5": "in transition",
        }[block["key"]]
        content = _specimen_map_pdf(
            {
                "name": parcel.name,
                "area": parcel.area,
                "apn": parcel.apn,
                "section_township_range": "",
                "buffer_zones": buffers,
                "application_answers": answers,
            },
            county="Chelan County, WA",
            status=status,
        )
        file_document(
            establishment=est,
            source="upload",
            folder="organic_system_plan",
            title=f"{parcel.name} block map (specimen)",
            filename=f"coldwater-bench-block-{block['block']}-map-specimen.pdf",
            content=content,
            content_type="application/pdf",
            linked_section="parcel_application_map",
            parcel=parcel,
            created_by=self.owner,
        )

    @staticmethod
    def _expected_harvest(block):
        return {"Gala": date(2026, 8, 20), "Honeycrisp": date(2026, 9, 20), "d'Anjou": date(2026, 9, 10)}[
            block["variety"]
        ]

    @staticmethod
    def _land_history(parcel, block):
        """The 36 months a reviewer reads, as the binder states them. Earlier inputs are not on paper,
        so the substance columns of the farm's own organic years stay empty."""
        crop = f"{block['crop']} ({block['variety']})"
        rows = []
        if block["key"] in ("B1", "B2", "B4"):
            rows = [
                dict(
                    year=y, crop_grown=crop, production_method="organic", notes="Managed organically by this operation."
                )
                for y in (2023, 2024, 2025)
            ]
        elif block["key"] == "B3":
            rows = [
                dict(
                    year=2022,
                    crop_grown=crop,
                    production_method="conventional",
                    last_prohibited_substance="Not known: the previous owner's spray records are not on file",
                    notes="Bought from the previous owner in 2023. Dan recalls their last prohibited spray as fall "
                    "2022; no date or declaration is on file.",
                ),
                *[
                    dict(
                        year=y,
                        crop_grown=crop,
                        production_method="organic",
                        notes="Managed organically by this operation.",
                    )
                    for y in (2023, 2024, 2025)
                ],
            ]
        elif block["key"] == "B5":
            rows = [
                dict(
                    year=2024,
                    crop_grown=f"{crop}, young trees, not bearing",
                    production_method="conventional",
                    last_prohibited_substance="Glyphosate",
                    date_last_prohibited=date(2024, 10, 15),
                    notes="Farmed by the seller until November 2024 (affidavit on file).",
                ),
                dict(
                    year=2025,
                    crop_grown=f"{crop}, young trees, not bearing",
                    production_method="transitional",
                    notes="First full year under this operation. No prohibited material applied.",
                ),
            ]
        for row in rows:
            ParcelCropHistory.objects.create(parcel=parcel, **row)

    def _seasons(self, parcels, packer):
        CropType = apps.get_model("carbon", "CropType")
        seasons = {}
        for block in BLOCKS:
            if block["bearing"] != "bearing":
                continue
            crop_type = CropType.objects.filter(slug=block["crop"].lower()).first()
            if crop_type is None:
                raise CommandError(
                    f"CropType {block['crop']!r} missing. Run `populate_usda_crop_types --crops-only` first."
                )
            product, _ = Product.objects.get_or_create(name=block["crop"])
            history = Production.objects.create(
                parcel=parcels[block["key"]],
                product=product,
                crop_type=crop_type,
                name=f"{SEASON_YEAR} {block['variety']}, Block {block['block']}",
                type="OR",
                production_method="organic",
                start_date=_dt(SEASON_YEAR, 1, 1),
                expected_harvest=_dt(*self._expected_harvest(block).timetuple()[:3]),
                operator=self.owner,
                description=f"{block['variety']} on Block {block['block']}, {block['acres']} acres.",
                extra_data={"production_method": "organic", "created_via": "seed_coldwater_bench"},
                age_of_plants=f"Planted {block['year_planted']}" if block["year_planted"] else "",
            )
            history.post_harvest_facilities.set([packer])
            parcel = parcels[block["key"]]
            parcel.current_history = history
            parcel.save(update_fields=["current_history"])
            seasons[block["key"]] = history
        return seasons

    # ------------------------------------------------------------------ records
    def _season_records(self, parcels, seasons, applicators, catalog):
        """The 2026 sheet, row by row. Sprays go through the API's serializer and multi-target or
        tank-mix contract; everything else is written as the API's create would leave it."""
        self._parcel_rows = parcels
        self._seasons_by_key = seasons
        self._applicators = applicators
        counts = {"sprays": 0, "tank_lines": 0, "other": 0, "sales": 0}
        acres = {b["key"]: b["acres"] for b in BLOCKS}
        dan, rafa = self._copy_from(applicators["dan"]), self._copy_from(applicators["rafa"])
        bearing = ["B1", "B2", "B3", "B4"]

        def card(start, stop, wind_from, mph, temp_f):
            """What the applicator's field card holds: times, wind and temperature, the apparatus."""
            return {
                "application_start": start,
                "application_end": stop,
                "wind_from": wind_from,
                "wind_speed_mph": mph,
                "air_temperature_f": temp_f,
                "apparatus_license_plate": NO_PLATE,
            }

        sprays = [
            # 3/14 All, dormant lime sulfur, 10 gal/100 at 200 gpa, DK. Brand not on the sheet or the
            # binder ("2 drums bought Feb").
            dict(
                key="lime-sulfur",
                blocks=bearing,
                when="2026-03-14T07:30:00",
                body={
                    "type": "FU",
                    "commercial_name": "Lime sulfur",
                    "concentration": "10 gal per 100 gal water",
                    "carrier_volume": "200",
                    "carrier_volume_unit": "gal_per_acre",
                    "target_pest_disease": "Dormant spray",
                    "application_method": "air_blast",
                    "organic_approved": "unverified",
                    "private_note": "Dormant spray, all blocks. Two drums bought in February; brand not on the sheet.",
                    **dan,
                    **card("2026-03-14T07:30:00", "2026-03-14T13:00:00", "S", "3", "44"),
                },
            ),
            # 3/28 Blocks 1+2, Kocide 3000-O, 2 lb/ac at 100 gpa, DK. Left over from last year.
            dict(
                key="kocide",
                blocks=["B1", "B2"],
                when="2026-03-28T08:00:00",
                body={
                    "type": "FU",
                    "commercial_name": "Kocide 3000-O",
                    "application_rate": "2",
                    "application_rate_unit": "lb_ac",
                    "carrier_volume": "100",
                    "carrier_volume_unit": "gal_per_acre",
                    "target_pest_disease": "Copper",
                    "application_method": "air_blast",
                    "organic_approved": "omri_listed",
                    "private_note": "Copper on the two Gala blocks. Product left over from last year (3 bags).",
                    **dan,
                    **card("2026-03-28T08:00:00", "2026-03-28T10:30:00", "W", "4", "48"),
                },
            ),
            # 4/2 All, JMS Stylet-Oil 1%, water "150" with no unit, Rafa, delayed dormant.
            dict(
                key="oil-delayed-dormant",
                blocks=bearing,
                when="2026-04-02T07:00:00",
                body={
                    "type": "PE",
                    "commercial_name": "JMS Stylet-Oil",
                    "concentration": "1%",
                    "target_pest_disease": "Delayed dormant oil",
                    "application_method": "air_blast",
                    "organic_approved": "unverified",
                    "private_note": "Delayed dormant. Water on the sheet is '150' with no unit, so no carrier is "
                    "recorded. Which Stylet-Oil label (organic or not) is not on the sheet.",
                    **rafa,
                    **card("2026-04-02T07:00:00", "2026-04-02T14:30:00", "SW", "5", "51"),
                },
            ),
            # Apr 10 Block 3, Isomate CM Flex II, 400/ac, crew. Apr 11 Blocks 1, 2, 4.
            dict(
                key="isomate-b3",
                blocks=["B3"],
                when="2026-04-10",
                body=self._dispensers("Block 3 (21.6 acres per the FSA map; the farm also says 22)."),
            ),
            dict(
                key="isomate-b124",
                blocks=["B1", "B2", "B4"],
                when="2026-04-11",
                body=self._dispensers(
                    "Blocks 1, 2 and 4 (the sheet's 27.2 acres for these blocks does not add up "
                    "to the blocks' 26.8)."
                ),
            ),
            # 4/22 Block 4, fish emulsion, 5 gal/ac, DK. Brand not on the sheet.
            dict(
                key="fish",
                blocks=["B4"],
                when="2026-04-22T09:00:00",
                body={
                    "type": "FE",
                    "commercial_name": "Fish emulsion",
                    "application_rate": "5",
                    "application_rate_unit": "gal_ac",
                    "target_pest_disease": "Fertilizer",
                    "application_method": "ground_spray",
                    "organic_approved": "unverified",
                    "private_note": "Fertilizer on the pears. Brand not on the sheet.",
                    **dan,
                },
            ),
            # 5/20 Block 2, Entrust SC "6 oz", water "100", Rafa, "thrips?".
            dict(
                key="entrust-b2",
                blocks=["B2"],
                when="2026-05-20T06:30:00",
                body={
                    "type": "PE",
                    "commercial_name": "Entrust SC",
                    "target_pest_disease": "Thrips (suspected)",
                    "application_method": "air_blast",
                    "organic_approved": "wsda_listed",
                    "wsda_material": catalog["Entrust SC"].pk,
                    "private_note": "The sheet says '6 oz' with no unit basis (per acre or per 100 gal not stated), and "
                    "water '100' with no unit; neither is recorded as a number.",
                    **rafa,
                    **card("2026-05-20T06:30:00", "2026-05-20T08:00:00", "calm", "0", "58"),
                },
            ),
            # 5/29 All, 2nd cover, Cyd-X "3oz", no water, Rafa. No field card: time and
            # concentration are not on the source record.
            dict(
                key="cydx-2nd-cover",
                blocks=bearing,
                when="2026-05-29",
                body={
                    "type": "PE",
                    "commercial_name": "Cyd-X",
                    "time_not_recorded": True,
                    "concentration_not_recorded": True,
                    "target_pest_disease": "Codling moth, second cover",
                    "application_method": "air_blast",
                    "organic_approved": "omri_listed",
                    "omri_product": catalog["Cyd-X"].pk,
                    # Binder: "4/30 Cyd-X 6 cases from co-op - inv 88213 (in truck?)". The invoice
                    # itself is not on file, so no receipt is attached.
                    "supplier_name": "Co-op",
                    "purchase_date": "2026-04-30",
                    "purchase_invoice": "88213",
                    "private_note": "Second cover. The sheet says '3oz' with no basis and no water. The first cover "
                    "('mid May') has no date and is not recorded.",
                    **rafa,
                },
            ),
            # 6/3 Block 1, Surround WP 25 lb/ac at 100 gpa, DK, sunburn. The sheet has this row
            # twice ("dup? entered twice"): one record.
            dict(
                key="surround",
                blocks=["B1"],
                when="2026-06-03T06:00:00",
                body={
                    "type": "PE",
                    "commercial_name": "Surround WP",
                    "application_rate": "25",
                    "application_rate_unit": "lb_ac",
                    "carrier_volume": "100",
                    "carrier_volume_unit": "gal_per_acre",
                    "target_pest_disease": "Sunburn",
                    "application_purpose": "other",
                    "application_method": "air_blast",
                    "organic_approved": "wsda_listed",
                    "wsda_material": catalog["Surround WP"].pk,
                    "private_note": "Sunburn protection. The sheet lists this spray twice; it is one application.",
                    **dan,
                    **card("2026-06-03T06:00:00", "2026-06-03T09:30:00", "N", "2", "66"),
                },
            ),
            # 6/24 and 7/8 Block 3, calcium chloride for bitter pit, Rafa. Hardware store, 12 bags.
            dict(
                key="cacl2-june",
                blocks=["B3"],
                when="2026-06-24T06:00:00",
                body=self._calcium("200", rafa, card("2026-06-24T06:00:00", "2026-06-24T11:00:00", "NW", "4", "70")),
            ),
            dict(
                key="cacl2-july",
                blocks=["B3"],
                when="2026-07-08T05:30:00",
                body=self._calcium(None, rafa, card("2026-07-08T05:30:00", "2026-07-08T10:30:00", "W", "3", "74")),
            ),
            # 7/21 Block 2, JMS Stylet-Oil 1% at 150 gpa, DK, mites.
            dict(
                key="oil-mites",
                blocks=["B2"],
                when="2026-07-21T05:30:00",
                body={
                    "type": "PE",
                    "commercial_name": "JMS Stylet-Oil",
                    "concentration": "1%",
                    "carrier_volume": "150",
                    "carrier_volume_unit": "gal_per_acre",
                    "target_pest_disease": "Mites",
                    "application_method": "air_blast",
                    "organic_approved": "unverified",
                    "private_note": "Mites on Block 2.",
                    **dan,
                    **card("2026-07-21T05:30:00", "2026-07-21T07:30:00", "calm", "0", "68"),
                },
            ),
        ]
        for spray in sprays:
            counts["sprays"] += len(self._write_spray(spray, acres))

        tank = self._write_tank(dan, card, catalog, acres)
        counts["sprays"] += len(tank)
        counts["tank_lines"] = len(tank)

        counts["other"] += self._other_records(parcels, seasons, acres)
        counts["sales"] += self._sale(seasons)
        return counts

    @staticmethod
    def _copy_from(profile) -> dict:
        """What the spray form copies from an applicator profile onto the record at save."""
        return {
            "applicator_name": profile.full_name,
            "applicator_certification": profile.license_number,
            "applicator_address": profile.address,
            "applicator_phone": profile.phone,
            "performed_by": profile.full_name,
        }

    @staticmethod
    def _dispensers(observation):
        return {
            "type": "PE",
            "commercial_name": "Isomate CM Flex II",
            # The rehearsal sheet gives a date and no clock time for the dispenser rows.
            "time_not_recorded": True,
            "volume_unit": "dispensers",
            "target_pest_disease": "Codling moth (mating disruption)",
            "application_method": "hand_dispenser",
            "organic_approved": "unverified",
            "performed_by": CREW,
            "private_note": f"Dispensers hung at 400 per acre, {observation} Two boxes bought; the receipt is in "
            "Karen's email.",
        }

    @staticmethod
    def _calcium(carrier, applicator, card):
        body = {
            "type": "FE",
            "commercial_name": "Calcium chloride",
            # Binder: "Calcium chloride - hardware store, 12 bags". The store is not named.
            "supplier_name": "Hardware store",
            "concentration": "4 lb per 100 gal water",
            "target_pest_disease": "Bitter pit (Honeycrisp)",
            "application_purpose": "soil_fertility",
            "application_method": "foliar",
            "organic_approved": "unverified",
            "private_note": "Foliar calcium for bitter pit on Honeycrisp. Bought at a hardware store (12 bags); "
            "the bag label is not on file.",
            **applicator,
            **card,
        }
        if carrier:
            body.update({"carrier_volume": carrier, "carrier_volume_unit": "gal_per_acre"})
        else:
            body["private_note"] += " Water on the sheet is '200' with no unit."
        return body

    def _target(self, key, acres):
        block = next(b for b in BLOCKS if b["key"] == key)
        return {
            "parcel": self._parcel_rows[key].pk,
            "history": self._seasons_by_key[key].pk,
            "area_treated": str(acres[key]),
            "block_id": block["block"],
        }

    def _serializer_for(self, body, history):
        from history.serializers import UpdateChemicalEventSerializer

        serializer = UpdateChemicalEventSerializer(
            data={**body, "history": history.pk}, context={"request": _SeedRequest(self.owner)}
        )
        if not serializer.is_valid():
            raise CommandError(f"Spray record refused by the API's serializer: {serializer.errors}")
        return serializer.validated_data

    def _write_spray(self, spray, acres):
        """One product, one or more blocks: the multi-target contract (`multi_target.check_envelope`)
        when there are several blocks, the single-record body when there is one."""
        from history.services import multi_target

        shared = {**spray["body"], "date": spray["when"], "area_unit": "acres"}
        targets = [self._target(key, acres) for key in spray["blocks"]]
        group = None
        if len(targets) > 1:
            group = uuid.uuid5(UUID_NAMESPACE, f"spray-{spray['key']}")
            shared, targets = multi_target.check_envelope(
                {**shared, "event_type": CHEMICAL_EVENT_TYPE, "application_group": str(group), "targets": targets},
                CHEMICAL_EVENT_TYPE,
            )
        records = []
        for target in targets:
            history = Production.objects.get(pk=target["history"])
            fields = {k: v for k, v in target.items() if k not in multi_target.TARGET_ADDRESS_KEYS}
            validated = self._serializer_for({**shared, **fields}, history)
            extra = {"application_group": group} if group else {}
            records.append(self._create(ChemicalEvent, history, validated, extra))
        return records

    def _write_tank(self, dan, card, catalog, acres):
        """June 12, Blocks 1 and 2: Entrust SC with a spreader-sticker, one tank. A specimen addition
        (the sheet has no tank row), written through `history/services/tank_mix.py` exactly as the
        API's `_create_tank_mix` does: one full record per product and per block."""
        from history.services import tank_mix

        request = {
            "event_type": CHEMICAL_EVENT_TYPE,
            "tank_mix_group": str(uuid.uuid5(UUID_NAMESPACE, "tank-entrust-june")),
            "date": "2026-06-12T05:45:00",
            "area_unit": "acres",
            "application_method": "air_blast",
            "carrier_volume": "100",
            "carrier_volume_unit": "gal_per_acre",
            "observation": "One tank of Entrust SC with a spreader-sticker on the two Gala blocks, for codling moth "
            "first generation.",
            "private_note": "Specimen addition: the rehearsal sheet has no tank row.",
            **dan,
            **card("2026-06-12T05:45:00", "2026-06-12T08:15:00", "NW", "3", "62"),
            "products": [
                {
                    "tank_mix_role": "product",
                    "type": "PE",
                    "commercial_name": "Entrust SC",
                    "application_rate": "6",
                    "application_rate_unit": "fl_oz_ac",
                    "target_pest_disease": "Codling moth, first generation",
                    "organic_approved": "wsda_listed",
                    "wsda_material": catalog["Entrust SC"].pk,
                },
                {
                    "tank_mix_role": "adjuvant",
                    "type": "PE",
                    "commercial_name": "Brandt Organics SKH Sticker Extender",
                    "target_pest_disease": "Spreader-sticker for the Entrust",
                    "organic_approved": "omri_listed",
                    "omri_product": catalog["Brandt Organics SKH Sticker Extender"].pk,
                },
            ],
            "targets": [self._target("B1", acres), self._target("B2", acres)],
        }
        tank = tank_mix.check_tank_envelope(request, CHEMICAL_EVENT_TYPE)
        several = len(tank.targets) > 1
        records = []
        for index, line, body in tank_mix.record_bodies(tank):
            history = Production.objects.get(pk=tank.targets[index]["history"])
            validated = self._serializer_for(body, history)
            extra = {"tank_mix_group": tank.tank_id, "tank_mix_line": line.number, "tank_mix_role": line.role}
            if several:
                extra["application_group"] = tank_mix.line_application_group(tank.tank_id, line.number)
            records.append(self._create(ChemicalEvent, history, validated, extra))
        return records

    def _create(self, model, history, validated, extra=None):
        """What the API's write path does with a validated body (`EventViewSet._write_resolved`)."""
        data = dict(validated)
        data.pop("history", None)
        data.pop("created_by", None)
        data.pop("_validation_warning", None)
        return model.objects.create(
            history=history, index=self._next_index(history), created_by=self.owner, **(extra or {}), **data
        )

    @staticmethod
    def _next_index(history):
        from history.views import EventViewSet

        return EventViewSet._next_event_index(history)

    def _other_records(self, parcels, seasons, acres):
        """Compost, the neighbor's spraying, irrigation and the harvest, as the sheet has them."""
        n = 0
        # 7/15 compost "from the county place", 5 ton/ac, crew. Block 4 not done (spreader broke),
        # so Blocks 1 to 3 only. No feedstock or process sheet: the organic basis stays unconfirmed.
        # The amount applied is the sheet's rate times the block's acres, and says so. The 240-ton
        # delivery is ONE purchase for the three blocks, so it sits on Block 1's record alone: the
        # mass balance reads purchases per record, and 240 on each would print 720 bought.
        for key in ("B1", "B2", "B3"):
            block_acres = Decimal(str(acres[key]))
            applied = (block_acres * 5).normalize()
            fields = {
                "type": "OM",
                "date": _dt(2026, 7, 15, 8),
                "description": "Compost spread along the tree rows",
                "amendment_type": "compost",
                "amendment_product_name": "Compost from the county yard",
                "amendment_organic_approved": "unverified",
                "amendment_amount": f"{applied:f} (5 tons per acre on {block_acres.normalize():f} acres)",
                "amendment_amount_numeric": applied,
                "amendment_amount_unit": "tons",
                "area_covered": acres[key],
                "area_unit": "acres",
                "block_id": next(b["block"] for b in BLOCKS if b["key"] == key),
                "performed_by": CREW,
                "observation": "Compost at 5 tons per acre along the tree rows.",
                "private_note": "5 tons per acre as on the sheet. 240 tons came from the county yard in one "
                "delivery for Blocks 1 to 3 (recorded on Block 1's record); the feedstock and process sheet has "
                "been asked for and is not yet on file. Block 4 was not done after the spreader broke.",
            }
            if key == "B1":
                fields["amendment_quantity_purchased"] = Decimal("240")
                fields["amendment_quantity_purchased_unit"] = "tons"
            self._create(SoilManagementEvent, seasons[key], fields)
            n += 1
        # 6/15 neighbor's crew sprayed Roundup along the north fence. Not our application.
        self._create(
            GeneralEvent,
            seasons["B1"],
            {
                "name": "Neighbor sprayed along the north fence",
                "date": _dt(2026, 6, 15, 12),
                "description": "The neighbor's crew sprayed Roundup with a backpack sprayer along the north fence. Not "
                "our application. Not known whether any drifted across the 25 ft buffer.",
                "observation": "Possible drift from the neighbor's side of the north fence. Not our application.",
                "is_contamination_incident": True,
                "contamination_source": "spray_drift",
                "certifier_notified": False,
                "performed_by": "Dan Tollefsen",
            },
        )
        n += 1
        # 8/2 Block 1 irrigation, DK: "set drip timers 6h".
        self._create(
            ProductionEvent,
            seasons["B1"],
            {
                "type": "IR",
                "date": _dt(2026, 8, 2, 7),
                "description": "Set the drip timers to 6 hours",
                "observation": "Drip timers set to 6 hours on Block 1.",
                "performed_by": "Dan Tollefsen",
            },
        )
        n += 1
        # Harvests. Block 3 (Honeycrisp, 9/23) is still picking with no bin count: no harvest record.
        for key, day, bins, variety in (
            ("B1", date(2026, 8, 19), 212, "Gala"),
            ("B2", date(2026, 9, 2), 118, "Gala"),
            ("B4", date(2026, 9, 10), 64, "d'Anjou"),
        ):
            block = next(b for b in BLOCKS if b["key"] == key)
            self._create(
                ProductionEvent,
                seasons[key],
                {
                    "type": "HA",
                    "date": _dt(day.year, day.month, day.day, 7),
                    "description": f"Harvest {variety}, Block {block['block']}",
                    "variety": variety,
                    "yield_quantity": Decimal(bins),
                    "yield_unit": "bins",
                    "amount_determination": "estimated",
                    "area_covered": acres[key],
                    "harvest_lot_code": self._lot(key),
                    "harvest_destination": "handler",
                    "performed_by": CREW,
                    "observation": f"{bins} bins off Block {block['block']}, collected by the packer.",
                },
            )
            n += 1
        return n

    @staticmethod
    def _lot(key):
        block = next(b for b in BLOCKS if b["key"] == key)
        variety = {"Gala": "GALA", "Honeycrisp": "HC", "d'Anjou": "ANJOU"}[block["variety"]]
        return f"CB-26-B{block['block']}-{variety}"

    def _sale(self, seasons):
        """The pears: "all to the packer", so all 64 bins. The settlement is not in the binder, so no
        invoice number or amount. The Gala stand sales have no number and are not recorded."""
        history = seasons["B4"]
        harvest = ProductionEvent.objects.get(history=history, type="HA")
        sale = SalesRecord.objects.create(
            production=history,
            sale_date=date(2026, 9, 10),
            buyer_name=PACKER,
            destination=f"{PACKER}, Manson WA",
            quantity=Decimal("64"),
            quantity_unit="bins",
            organic_on_invoice=True,
            organic_label_category="organic",
            carrier_name=f"{PACKER} (collects at the orchard)",
            transport_notes="All 64 bins of d'Anjou to the packer. Settlement sheet not yet received.",
        )
        sale.harvest_events.set([harvest])
        return 1

    # ------------------------------------------------------------------ plan
    def _osp(self, est, catalog):
        """The plan filed with WSDA: every module answered from `_coldwater_bench_osp_answers.json`
        (checked against the live questionnaire), the materials list, and the § 11 record types.

        A draft: the farm is moving onto Trazo in its first year, so this plan is a working copy, not
        the one on file with the agent, and the packet says so. Switching `certifier_name` to
        "CCOF Certification Services, LLC" is how the CCOF packet is built (the plan page's picker
        writes the same field).
        """
        from certifications.osp_modules import MODULE_REGISTRY
        from certifications.services.common_osp_records import CONFIRMATIONS_KEY
        from certifications.services.common_osp_records import OSP_SECTION_KEY as RECORDS_SECTION
        from certifications.services.osp_module_compiler import compile_modules_to_sections

        OSP = apps.get_model("certifications", "OrganicSystemPlan")
        PME = apps.get_model("certifications", "PlanMaterialEntry")
        NLS = apps.get_model("certifications", "NationalListSubstance")

        answers = _load_osp_answers(OSP_ANSWERS_PATH)
        # The answers are written after the records they describe, as an operator writes a plan from
        # the season: a fixed date earlier than the seed run made every record read as "added after
        # the plan's answers" on the cover's plan review.
        answered_at = timezone.now().isoformat()
        osp = OSP.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            certifier_name=AGENT_NAME,
            created_by=self.owner,
        )
        osp.module_responses = {
            "schema_version": 1,
            "modules": {m.key: _module_entry(m.key, answers, answered_at, self.owner) for m in MODULE_REGISTRY},
            "parcel_modules": {},
        }
        sections = dict(osp.sections or {})
        records = dict(sections.get(RECORDS_SECTION) or {})
        # The operator's § 11 statements, as fixture data credited to no user: on a real operation only
        # the operator's own action writes them (`common_osp_records.confirm`, never from a seeder).
        records[CONFIRMATIONS_KEY] = {
            key: {"confirmed": True, "confirmed_at": answered_at, "confirmed_by": None}
            for key in answers.get("common_osp_records") or []
        }
        sections[RECORDS_SECTION] = records
        osp.sections = sections
        osp.save()

        def substance(name):
            return NLS.objects.filter(substance_name=name).first()

        materials = [
            (
                "Lime sulfur",
                "pest_disease_weed",
                "Dormant disease control, all blocks.",
                "national_list",
                {"national_list_substance": substance("Lime sulfur")},
            ),
            (
                "Kocide 3000-O",
                "pest_disease_weed",
                "Copper before bud break on the Gala blocks.",
                "national_list",
                {"national_list_substance": substance("Copper hydroxide")},
            ),
            (
                "JMS Stylet-Oil",
                "pest_disease_weed",
                "Delayed dormant oil; summer mites.",
                "national_list",
                {"national_list_substance": substance("Horticultural oils")},
            ),
            (
                "Isomate CM Flex II",
                "pest_disease_weed",
                "Codling moth mating disruption.",
                "national_list",
                {"national_list_substance": substance("Pheromones"), "facility_material_type": "pheromones"},
            ),
            (
                "Cyd-X",
                "pest_disease_weed",
                "Codling moth granulovirus covers.",
                "omri",
                {"omri_product": catalog["Cyd-X"]},
            ),
            (
                "Entrust SC",
                "pest_disease_weed",
                "Thrips and codling moth when scouting finds them.",
                "wsda",
                {"wsda_material": catalog["Entrust SC"]},
            ),
            (
                "Brandt Organics SKH Sticker Extender",
                "production_aid",
                "Spreader-sticker in the Entrust tank.",
                "omri",
                {"omri_product": catalog["Brandt Organics SKH Sticker Extender"]},
            ),
            (
                "Surround WP",
                "pest_disease_weed",
                "Sunburn protection on Gala.",
                "wsda",
                {"wsda_material": catalog["Surround WP"]},
            ),
            (
                "Calcium chloride",
                "fertilizer_amendment",
                "Foliar spray for bitter pit on Honeycrisp.",
                "national_list",
                {"national_list_substance": substance("Calcium chloride (brine process)")},
            ),
            (
                "Fish emulsion",
                "fertilizer_amendment",
                "Nitrogen for the pears in spring.",
                "national_list",
                {"national_list_substance": substance("Liquid fish products")},
            ),
            (
                "Compost from the county yard",
                "fertilizer_amendment",
                "Fertility along the tree rows.",
                "none_unlisted",
                {},
            ),
        ]
        for name, category, reason, basis, links in materials:
            PME.objects.create(
                osp=osp,
                created_by=self.owner,
                product_name=name,
                category=category,
                reason_for_use=reason,
                listing_basis=basis,
                status="in_use",
                **{k: v for k, v in links.items() if v is not None},
            )
        osp.approved_wsda_materials.set([catalog["Entrust SC"], catalog["Surround WP"]])
        osp.approved_omri_products.set([catalog["Cyd-X"], catalog["Brandt Organics SKH Sticker Extender"]])
        osp.approved_national_list_substances.set(
            [
                s
                for s in (
                    substance(n)
                    for n in (
                        "Lime sulfur",
                        "Copper hydroxide",
                        "Horticultural oils",
                        "Pheromones",
                        "Liquid fish products",
                    )
                )
                if s is not None
            ]
        )
        compile_modules_to_sections(osp)
        osp.save()
        return osp

    # ------------------------------------------------------------------ close
    def _finish_and_seal(self, seasons):
        """Close the three blocks whose picking is done, then seal them over the rows just written.
        Block 3 (Honeycrisp) is still picking and stays open (answer key, trap 12)."""
        from history.seals import seal

        for key, day, bins in (
            ("B1", date(2026, 8, 19), 212),
            ("B2", date(2026, 9, 2), 118),
            ("B4", date(2026, 9, 10), 64),
        ):
            history = seasons[key]
            history.finish(
                {
                    "finish_date": _dt(day.year, day.month, day.day, 18),
                    "production_amount": bins,
                    "lot_id": self._lot(key),
                    "production_unit": "bins",
                    "harvest_method": "manual",
                    # The buyer page is not published: nothing in the brief asks for a public page.
                    "published": False,
                },
                images=None,
            )
            parcel = history.parcel
            parcel.current_history = None
            parcel.save(update_fields=["current_history"])
        for key in ("B1", "B2", "B4"):
            seal(Production.objects.get(pk=seasons[key].pk))
