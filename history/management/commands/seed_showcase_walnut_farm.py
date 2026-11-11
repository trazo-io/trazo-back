"""Put ONE farm into the state the product is actually sold on — for screenshots.

Why this exists
---------------
The landing hero (`trazo-landing/components/hero.tsx`, `/images/app-screenshot-v2.jpg`) is a
photograph of the real farm dashboard. On 2026-08-15 that photograph showed a farm with two
events, zero photos, `0/1 inputs have supplier`, a draft OSP and six open findings under a
headline promising "records already assembled". The screenshot argued against the page it was
selling. Nothing was wrong with the product — the DEMO DATA was the weakest state the product
can render.

So this command builds the state a real October customer is in, on real product code paths:

  * Blue Oak Orchards — a certified-organic Chandler walnut operation at Winters, Yolo County
    (the ICP: mid-size CA wholesale orchard, certification years 5+),
  * a CLOSED prior season whose 16 CFR-cited record checks all pass — the green
    "Ready for your certifier / Nothing outstanding" state of `CertifierReadinessCard`,
  * a CURRENT season in progress, so the farm is alive rather than archived,
  * three dated rows in `CertifierDeadlinesStrip`: the § 205.406 annual update started but not
    submitted, the organic certificate, and the CDFA State Organic Program renewal.

NOTHING here is a UI change and nothing bypasses a check. Every PASS is earned by the same
`AuditExportService.compliance_snapshot_rows()` the certifier packet prints, against records
written through the ordinary models. If a check fails after a code change, this seeder starts
failing too — which is the point: the screenshot cannot drift away from the product.

Honesty constraints held here on purpose
----------------------------------------
* The certifier is FICTIONAL ("Pacific Slope Organic Certifiers"). No real accredited agent is
  named as certifying a farm that does not exist.
* Photographs come only from the vetted pool in `create_demo_user.DEMO_IMAGES` and are attached
  only to an operation each one actually depicts. See `prune_misleading_demo_photos`: a photo of
  an operation that did not happen is worse than no photo.
* The input program is a real organic walnut program (copper for blight, pheromone mating
  disruption, spinosad at hull split, fish fertigation) with real OMRI/National List entries.
* The closed season is the PRIOR crop year. California Chandler walnuts are harvested mid-
  September to October, so a 2026 season cannot be finished in August — dating one that way to
  get a fresher number on a screenshot would be the same class of lie this file exists to undo.
  Once the real harvest window closes, `--close-current` rolls the current season shut.
* DEMO THE CURRENT SEASON, not the closed one. Every record here is created at seed time and
  `auditlog` stamps the real wall-clock time — correctly, and it must not be forged, because
  that log is what the packet's Record Change History offers as proof the records were not
  fabricated. On the closed season that yields events dated last autumn with entries stamped
  today, which reads to a certifier as one back-entered batch. The current season is in
  progress, its events run to today, and entries sit naturally against them. The command
  prints which production to open.

Usage
-----
    poetry run python manage.py seed_showcase_walnut_farm
    poetry run python manage.py seed_showcase_walnut_farm --establishment 160
    poetry run python manage.py seed_showcase_walnut_farm --close-current   # after harvest
    poetry run python manage.py seed_showcase_walnut_farm --with-open-items # landing hero, Nov 2026
    poetry run python manage.py seed_showcase_walnut_farm --verify-only

`--with-open-items` is the state the landing hero has shown since 2026-11-11, on purpose: a
readiness card that is all green tells a grower nothing about what Trazo catches. It finishes
North Block's current season with the shaker wash-down never logged (§ 205.272: the harvester
came off conventional ground with no cleaning record), keeps East Block's season underway, and
puts the company on the comped Pilot plan. Every finding the card then shows is computed by the
product from those records; the two "not on your materials list" items need no help, because
the drift detector really does not find Kocide 3000-O or Entrust SC on the plan.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from carbon.models import CropType
from certifications.models import (
    Certification,
    NationalListSubstance,
    OMRIProduct,
    OrganicSystemPlan,
    OSPAnnualUpdate,
    StateOrganicRegistration,
    WSDAMaterial,
)
from common.models import Gallery, GalleryImage
from company.models import Establishment
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    GeneralEvent,
    History,
    HistoryScan,
    PestManagementEvent,
    ProductionEvent,
    SalesRecord,
    SoilManagementEvent,
    WeatherEvent,
)
from product.models import Product
from subscriptions.models import Plan, Subscription

from .create_demo_user import DEMO_IMAGES

DEFAULT_ESTABLISHMENT_ID = 160

# Farm identity. Fictional, and deliberately a LANDSCAPE name rather than a family name: a
# family name we invent can collide with a real operation, a native tree cannot.
#
# The blue oak is the signature tree of the interior Coast Range and the Sacramento Valley
# floor, and the Blue Ridge is the ridge on the valley's west side above Winters — real
# walnut ground, twenty minutes from Davis.
#
# It replaced "Putah Creek Ranch" (2026-08-15). The creek is real and its name comes from the
# Patwin "puta toi", but the landing hero this screenshot sits under promises records "in
# English or Spanish", and to a Spanish-speaking reader the first word is one letter off an
# obscenity. A marketing image does not get to explain its own etymology. The word is gone
# from the farm name AND from the description for the same reason.
FARM_NAME = "Blue Oak Orchards"
COMPANY_NAME = "Blue Oak Walnut Co."
# Lot prefix. "BOO" is what the initials give you; on a consumer page reading
# "Lot BOO-2025-EB-01" that is a punchline, so the lot code stops at two letters.
LOT_PREFIX = "BO"

# Kept under ~150 characters on purpose: the farm-profile card clamps at 4 lines and a longer
# description cuts mid-word, which reads as sloppy in a marketing screenshot.
FARM_DESCRIPTION = (
    "Third-generation family orchard at the foot of the Blue Ridge, west of Winters. "
    "27.9 acres of certified-organic Chandler walnuts."
)

CERTIFIER_NAME = "Pacific Slope Organic Certifiers"
# Businesses are obviously fictional ("Sample ..."). The handler was "Cache Creek Nut Company,
# receiving scale, Woodland CA", one word off a real Woodland nut processor; a demo packet gets
# forwarded, and every invented invoice and certificate date would have sat on that name.
HANDLER_NAME = "Sample Valley Hulling Co."
INPUT_SUPPLIER = "Sample Ag Supply, Woodland CA"
NURSERY_SUPPLIER = "Sample Nursery Co."
FARM_MANAGER = "Paula Rivas"
CROP_CONSULTANT = "D. Okafor, PCA #48213"

ACRES_PER_HECTARE = 2.47105381467

# What a REAL photo of this farm would show, per operation. Drop files named after these keys
# into --photo-dir ("copper-spray.jpg", "harvest-1.jpg", "harvest-2.jpg" …) and they are
# attached to every matching event, in both seasons, ahead of any stock image.
#
# This exists because the "Documentation depth" check wants 10+ photos on the season and stock
# libraries do not carry California nut-orchard operations: searches for a walnut orchard
# return cherry and apple orchards, "orchard sprayer" returns row-crop booms, and the one
# sprayer image in the shared demo pool turned out to be a liquid-manure tanker. A real photo
# from the block is the only honest way to fill these.
PHOTO_SLOTS = {
    "pruning": "Dormant pruning / shredding prunings",
    "amendment": "Spreading the fertility material (spreader, or the meal in hand)",
    "soil-test": "Pulling soil cores",
    "replant": "Planting a replacement tree",
    "fertigation": "Injecting fish fertilizer / the injection rig",
    "trap-set": "Hanging a codling-moth or NOW trap",
    "mating-disruption": "Hanging pheromone dispensers in the canopy",
    "copper-spray": "Air-blast sprayer applying copper in the row",
    "scouting": "Walking the block, inspecting the canopy",
    "beneficial-release": "Releasing beneficials",
    "mowing": "Mowing the orchard floor",
    "irrigation": "Micro-sprinkler running under the trees",
    "trap-read": "Reading a trap card",
    "hull-split": "Green walnuts at hull split",
    "hull-split-spray": "The hull-split spray pass",
    "equipment-cleaning": "Washing the shaker / sweeper before it enters organic ground",
    "floor-prep": "Floor mowed and rolled before shaking",
    "harvest": "Shaking or sweeping the crop",
    "hulling": "Delivery, hulling or drying",
    "delivery": "The load leaving for the handler",
    "records-review": "Closing the season’s records",
}
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

# Farm and block photography. Both were opened and LOOKED AT before being used here — the
# whole reason this file exists is a screenshot that did not match its own claims.
#   ORCHARD_ROW  — tree row over a grassed floor, species not identifiable. Matches the OSP's
#                  resident-vegetation floor and claims nothing about the crop.
#   WALNUT_TREE  — green walnuts in husk on the branch. Crop-true, no operation implied.
# Deliberately NOT used: every "walnut orchard" stock result that is actually a cherry, apple
# or almond orchard, and the citrus and avocado images that were on these parcels before.
ORCHARD_ROW_PHOTO = (
    "https://images.pexels.com/photos/16953951/pexels-photo-16953951/"
    "free-photo-of-large-summer-orchard.jpeg?auto=compress&cs=tinysrgb&w=1200"
)
WALNUT_TREE_PHOTO = (
    "https://images.pexels.com/photos/34415592/pexels-photo-34415592/"
    "free-photo-of-close-up-of-green-walnuts-on-tree-branch.jpeg?auto=compress&cs=tinysrgb&w=1200"
)
FARM_PHOTO = ORCHARD_ROW_PHOTO


# Two blocks, both fully documented: the readiness card scopes to one production, but a farm
# whose OTHER block is half-empty falls apart the moment anyone clicks Parcels.
# Field geometry, in the valley west of Winters. Small rectangles at the real coordinates of
# the ground the farm description names — enough for the packet's field map to render and for
# the § 205.202(c) boundary record to have something to attach to.
def _block_polygon(lon, lat, w=0.0062, h=0.0040):
    """A closed rectangle in GeoJSON ring order, west edge first."""
    return [[lon, lat], [lon + w, lat], [lon + w, lat + h], [lon, lat + h], [lon, lat]]


BLOCKS = [
    {
        "parcel_name": "North Block",
        "acres": Decimal("15.4"),
        "trees": 1240,
        "code": "NB",
        "photo": WALNUT_TREE_PHOTO,
        "polygon": _block_polygon(-121.9871, 38.5402),
        # § 205.202(c): a boundary record per side. The east side adjoins conventional row-crop
        # ground, which is why those two rows are managed as buffer and never sold as organic —
        # the same fact the OSP's commingling section states in prose.
        "buffers": [
            {
                "direction": "North",
                "adjoining_land_use": "Certified organic walnut orchard (same operation)",
                "buffer_width_m": 0,
                "drift_risk": "Low",
                "prevention": "No buffer required — organic on both sides",
            },
            {
                "direction": "East",
                "adjoining_land_use": "Conventional row crop (tomatoes)",
                "buffer_width_m": 15,
                "drift_risk": "Medium",
                "prevention": "Two buffer rows harvested separately and never sold as organic; annual neighbour-notification letter on file (§ 205.400(f)(1))",
            },
            {
                "direction": "South",
                "adjoining_land_use": "County Road 96",
                "buffer_width_m": 8,
                "drift_risk": "Low",
                "prevention": "Roadside hedgerow; no applications from the road side",
            },
            {
                "direction": "West",
                "adjoining_land_use": "Certified organic walnut orchard (same operation)",
                "buffer_width_m": 0,
                "drift_risk": "Low",
                "prevention": "No buffer required — organic on both sides",
            },
        ],
        # Days this block's whole program runs behind the base schedule. Nobody irrigates two
        # blocks on the same day and writes the same sentence about both: with a shared
        # schedule the activity log printed every row TWICE, identical except for the parcel
        # name, which reads as a duplicate-entry bug rather than as a farm. The North Block is
        # the base; the East Block is worked a few days later, the way a two-block operation
        # with one crew and one sprayer actually runs.
        "day_shift": 0,
    },
    {
        "parcel_name": "East Block",
        "acres": Decimal("12.5"),
        "trees": 1005,
        "code": "EB",
        "photo": ORCHARD_ROW_PHOTO,
        "polygon": _block_polygon(-121.9795, 38.5361),
        "buffers": [
            {
                "direction": "North",
                "adjoining_land_use": "Certified organic walnut orchard (same operation)",
                "buffer_width_m": 0,
                "drift_risk": "Low",
                "prevention": "No buffer required — organic on both sides",
            },
            {
                "direction": "East",
                "adjoining_land_use": "Conventional row crop (tomatoes)",
                "buffer_width_m": 15,
                "drift_risk": "Medium",
                "prevention": "Two buffer rows harvested separately and never sold as organic; annual neighbour-notification letter on file (§ 205.400(f)(1))",
            },
            {
                "direction": "South",
                "adjoining_land_use": "County Road 96",
                "buffer_width_m": 8,
                "drift_risk": "Low",
                "prevention": "Roadside hedgerow; no applications from the road side",
            },
            {
                "direction": "West",
                "adjoining_land_use": "Certified organic walnut orchard (same operation)",
                "buffer_width_m": 0,
                "drift_risk": "Low",
                "prevention": "No buffer required — organic on both sides",
            },
        ],
        "day_shift": 3,
    },
]

# The § 205.201(a)(2) approved-inputs registry. Every entry MUST be named in the inputs_list
# narrative below or the OSP row drops to REVIEW with an "(a)(2) gap" — that coupling is the
# product feature, so the seeder honours it rather than working around it.
NL_SUBSTANCES = [
    "Copper hydroxide",
    "Pheromones",
    "Spinosad",
    "Liquid fish products",
]
# Names must match certifications/data/omri_seed.csv BYTE FOR BYTE — the lookup below is
# `product_name__in`, so a near-miss silently drops the material off the plan's approved list.
# All three re-checked 2026-09-06 against the OMRI Crop Products List (September 5, 2026).
OMRI_PRODUCTS = [
    "Kocide 3000-O Fungicide/Bactericide Dry Flowable",
    "Entrust SC Naturalyte Insect Control",
    "Neptune's Harvest Organic Fish & Seaweed Fertilizer 2-3-1",
]
# WSDA-listed fertility material. Kept as its own list because the OSP registry holds three
# catalogs and the drift detector clears an amendment on a match in ANY of them.
# ⛔ "Feather Meal 13-0-0 / Down To Earth Distributors" stood here and is NOT on the WSDA
# Organic Input Material List — searching the March 06, 2026 edition for "down to earth"
# returns nothing. The real WSDA-registered feather meals are Darling's and Marion Ag's.
WSDA_MATERIALS = [
    "Nature Safe 13-0-0 Feather Meal Fertilizer",  # WSDA Product #2948, Darling Ingredients Inc.
]

INPUTS_NARRATIVE = """Approved inputs for this operation, by purpose (7 CFR 205.201(a)(2)).

Disease control: Kocide 3000-O Fungicide/Bactericide Dry Flowable (copper hydroxide,
§ 205.601(i)(2)) is the only material applied against walnut blight (Xanthomonas arboricola
pv. juglandis). It is applied at 3.5 lb/acre by air-blast sprayer on a maximum of two spring
passes, timed to the UC IPM blight model at early catkin and again at 40% leaf-out. Copper is
tracked against the annual load limit and is never applied after hull split.

Insect control: codling moth and navel orangeworm are managed first by mating disruption —
Pheromones (§ 205.601(f)) hung at 200 dispensers/acre before the first flight — and by winter
mummy-nut sanitation. A material is applied only when trap counts and the degree-day model put
the block over threshold, in which case Entrust SC Naturalyte Insect Control (spinosad, nonsynthetic —
no National List entry) is applied once at hull split at 6 fl oz/acre. No other insecticide is used.

Fertility: Nature Safe 13-0-0 Feather Meal Fertilizer broadcast at 400 lb/acre in February,
plus two fertigation
passes of Neptune's Harvest Organic Fish & Seaweed Fertilizer 2-3-1 (Liquid fish products,
§ 205.601(j)(7)) at 4 gal/acre through the micro-sprinkler set. Shredded prunings and the
resident orchard floor return the rest. Rates follow the March soil test and the July leaf
analysis; no soluble synthetic nitrogen is used on any block.

Every material above is verified against the National List and its OMRI listing before purchase
and again before first use. Each application is logged the same day with product, rate, area,
applicator and target, and each entry links to its supplier invoice and lot number so an
inspector can reconcile quantity purchased against quantity applied for any lot in the season."""

# The other five § 205.201(a) sections. Each must clear the dossier's 400-character material
# floor AND `looks_like_padding` — repeated filler counts as empty (2026-08-04).
SECTION_NARRATIVES = {
    "practices_procedures": """Production practices for 27.9 acres of Chandler walnuts on Paradox
rootstock, planted 1998 and 2004 at 26 x 22 ft spacing across the North and East blocks.

Orchard floor: a resident-vegetation and seeded-legume floor is mowed three to five times a
season rather than sprayed; berms are managed mechanically with a Weed Badger and by hand around
young replants. Prunings are shredded in place each February and returned to the floor as the
first fertility input of the year.

Fertility: Nature Safe 13-0-0 Feather Meal Fertilizer at 400 lb/acre in February, two
fish-fertigation passes during
shell hardening, and shredded prunings returned to the floor. Rates are set from the March soil test and the July leaf
analysis; both labs are named in the recordkeeping section.

Irrigation: micro-sprinkler on a well and district blend, scheduled from CIMIS ET0 and pressure
chambers, typically eight to eleven sets of 3.5 acre-inches between May and September.

Pest management follows the § 205.206 hierarchy: sanitation and mating disruption first,
biological control second, and an approved material only on a documented threshold.

Harvest is mechanical shake-and-sweep in late September, delivered the same day to the handler
named in the sales records.""",
    "recordkeeping_description": """Every field operation is entered in Trazo the day it happens,
from the phone in the cab, in English or Spanish. Each record carries date, block, area, operator,
equipment, materials with rate and lot, and the target or purpose. Photographs are attached at the
point of work for compost, spray and harvest operations.

Input purchases are recorded with supplier, invoice number, purchase date, lot number and quantity
purchased, so quantity applied can be reconciled against quantity bought for every material in the
season. Harvest weight comes off the handler's certified scale and the weigh ticket number is
stored on the harvest record.

Lot identity runs from the block to the delivery: each production carries a lot ID that appears on
the harvest record, the bill of lading and the handler invoice, giving one-step-forward and
one-step-back trace under § 205.103(b)(2).

Records are retained for five years (§ 205.103(b)(4)). The operator reviews the season's records
before each certifier submission and corrects gaps the same week they are found. Soil, leaf and
water lab reports are filed against the activity record they support.""",
    "monitoring_plan": """Monitoring is scheduled, not incidental, and each observation is written
down whether or not it triggers an action.

Pest: pheromone traps for codling moth and navel orangeworm are hung before first flight and read
weekly by the crop consultant; counts feed the UC IPM degree-day model. Blocks are walked on a
randomized ten-tree transect every two weeks from April through September for blight, aphid,
mite and beneficial populations. An action threshold and the reasoning behind it are recorded
before any material is applied.

Soil and water: a full soil test each March, a July leaf analysis, and an annual irrigation-water
test. Results are attached to the block record and drive the following season's fertility plan.

Practice integrity: buffer rows along the county road are inspected each spring, equipment shared
with neighbouring conventional ground is cleaned and logged before it enters organic blocks, and
the operator verifies every material against the approved-inputs list before purchase.

Findings that need action are closed out in the same season and the correction is recorded against
the original observation.""",
    "commingling_barriers": """The operation is 100% certified organic — there is no parallel
conventional production of the same crop, which removes the largest commingling risk.

Buffer: the two rows along County Road 96 and the shared eastern property line are treated as
buffer, harvested separately, and never sold, labelled or represented as organic. Buffer
disposition is recorded on the harvest record.

Equipment: the shaker and sweeper are shared with a neighbouring conventional operation during
harvest. Before any shared machine enters an organic block it is pressure-washed and inspected,
and the cleaning is logged with date, method, materials and the person who performed it. The
harvest record links to the cleaning record that covers it.

Storage and transport: nuts move from the block to the handler the same day in clean, dedicated
trailers; the bill of lading carries the lot ID and the organic identification. No product is
stored alongside non-organic product at any point, and the handler holds its own organic
certificate, which is on file.""",
    "additional_certifier_info": """Land history: both blocks have been managed organically without
prohibited materials since 2019 and were certified organic effective 2021-04-01; the 36-month
transition under § 205.202(b) closed before the first certified harvest. Field maps, APNs and
section-township-range for each block are attached to the parcel records.

Adjoining land: the north and west boundaries are organic orchard; the county road runs along the
south side, and the east boundary adjoins conventional row-crop ground, which is why the two east
rows are managed as buffer.

Fraud prevention: the § 205.201(a)(3) plan is on file and reviewed annually; it covers supplier
verification, input receipt inspection, lot reconciliation at delivery and the annual records
review before submission.

Contact for this operation is the farm manager, who is also the person who enters the records.
The operation has no split or parallel production, no handling of purchased organic product, and
no imported inputs.""",
}


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _dt(year, month, day, hour=8):
    return datetime(year, month, day, hour, 0, tzinfo=dt_tz.utc)


def _gallery_from_urls(urls):
    """A Gallery holding `urls`, or None when the list is empty."""
    urls = [u for u in urls if u]
    if not urls:
        return None
    gallery = Gallery.objects.create()
    for url in urls:
        GalleryImage.objects.create(gallery=gallery, image_url=url)
    return gallery


def _gallery_from_files(photo_dir, key):
    """Gallery built from the operator's OWN photographs for `key`, or None if there are none.

    Matches `<key>.jpg` and `<key>-2.jpg` style names. Saved through the ImageField so the file
    is copied into MEDIA_ROOT and served like any uploaded photo — no S3 round-trip in dev.
    """
    if not photo_dir:
        return None
    try:
        names = sorted(os.listdir(photo_dir))
    except OSError:
        return None
    matches = [
        n
        for n in names
        if os.path.splitext(n)[1].lower() in PHOTO_EXTENSIONS
        and (os.path.splitext(n)[0].lower() == key or os.path.splitext(n)[0].lower().startswith(f"{key}-"))
    ]
    if not matches:
        return None
    gallery = Gallery.objects.create()
    for name in matches:
        with open(os.path.join(photo_dir, name), "rb") as fh:
            image = GalleryImage(gallery=gallery)
            image.image.save(name, File(fh), save=True)
    return gallery


def _album(image_key):
    """Gallery holding the vetted demo photo for `image_key`, or None if the pool has none."""
    return _gallery_from_urls(DEMO_IMAGES.get(image_key) or [])


OSP_ANSWERS_PATH = os.path.join(os.path.dirname(__file__), "_blue_oak_osp_answers.json")


def _load_osp_answers() -> dict:
    """Blue Oak's module answers, checked against the questionnaire as it stands today.

    Fails the seed, naming the module and question, when a module has no entry, a required
    question is unanswered, a choice is not one of the options, or an answer names a question that
    no longer exists. A content change to a module therefore breaks this seeder until the fixture
    answers it, which is the point: the screenshot cannot drift from the product.
    """
    import json

    from certifications.osp_modules import MODULE_REGISTRY
    from certifications.osp_modules.conditions import invalid_choice_answers, missing_required, validate_answer_keys

    with open(OSP_ANSWERS_PATH, encoding="utf-8") as fh:
        fixture = json.load(fh)
    problems = []
    for module in MODULE_REGISTRY:
        spec = fixture.get(module.key)
        if spec is None:
            problems.append(f"{module.key}: no entry")
            continue
        answers = spec.get("answers") or {}
        not_applicable = bool(spec.get("not_applicable"))
        if not_applicable and not module.allows_not_applicable:
            problems.append(f"{module.key}: marked not applicable, which this module does not allow")
        for key in missing_required(module, answers, not_applicable):
            problems.append(f"{module.key}.{key}: required and unanswered")
        for key, value in invalid_choice_answers(module, answers).items():
            problems.append(f"{module.key}.{key}: {value!r} is not one of the options")
        for key in validate_answer_keys(module, answers):
            problems.append(f"{module.key}.{key}: no such question")
    from certifications.services.common_osp_records import RECORD_TYPES_BY_KEY

    for key in fixture.get("common_osp_records") or []:
        if key not in RECORD_TYPES_BY_KEY:
            problems.append(f"common_osp_records.{key}: no such record type")
        elif RECORD_TYPES_BY_KEY[key].free_text:
            problems.append(f"common_osp_records.{key}: a free-text row needs a label; not supported here")
    if problems:
        raise CommandError(f"{os.path.basename(OSP_ANSWERS_PATH)} is out of step:\n  " + "\n  ".join(problems))
    return fixture


def _module_entry(module_key: str, fixture: dict, answered_at: str, user) -> dict:
    """One `module_responses["modules"]` entry in the shape the module save path writes."""
    from certifications.osp_modules import CONTENT_VERSION

    spec = fixture[module_key]
    not_applicable = bool(spec.get("not_applicable"))
    return {
        "status": "not_applicable" if not_applicable else "completed",
        "answers": {key: {"at": answered_at, "value": value} for key, value in (spec.get("answers") or {}).items()},
        "completed_at": answered_at,
        "completed_by": user.id,
        "not_applicable": not_applicable,
        "na_attestation": {"at": answered_at, "by": user.id} if not_applicable else None,
        "definition_version": CONTENT_VERSION,
    }


def _q(value, places="0.01"):
    return Decimal(value).quantize(Decimal(places))


class Command(BaseCommand):
    help = "Seed the showcase organic walnut farm used for landing-page screenshots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--establishment",
            type=int,
            default=DEFAULT_ESTABLISHMENT_ID,
            help=f"Establishment id to rebuild (default {DEFAULT_ESTABLISHMENT_ID}).",
        )
        parser.add_argument(
            "--close-current",
            action="store_true",
            help="Finish, publish and sell the current-year season too (run after real harvest).",
        )
        parser.add_argument(
            "--with-open-items",
            action="store_true",
            help=(
                "The state the November 2026 landing hero shows: North Block's current season "
                "finished with its shaker wash-down never logged (a § 205.272 finding), East "
                "Block's still underway, and the company on the comped Pilot plan."
            ),
        )
        parser.add_argument(
            "--photo-dir",
            type=str,
            default=None,
            help=(
                "Directory of REAL photographs of this operation, named after the PHOTO_SLOTS "
                "keys (copper-spray.jpg, harvest-1.jpg …). Used ahead of any stock image."
            ),
        )
        parser.add_argument(
            "--verify-only",
            action="store_true",
            help="Do not write. Print the readiness verdict for the farm as it stands.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        est_id = options["establishment"]
        try:
            est = Establishment.objects.select_related("company").get(id=est_id)
        except Establishment.DoesNotExist as exc:
            raise CommandError(f"Establishment {est_id} not found.") from exc

        if options["verify_only"]:
            self._verify(est)
            return

        # This command REBUILDS an existing establishment row out of invented seasons, blocks
        # and spray records — it is the landing page's showcase farm, not an operation. The
        # row pre-exists, so unlike the other seeders there is no create() to carry the flag;
        # set it here or the showcase exports as though it were somebody's real records.
        if not est.is_demo:
            est.is_demo = True
            est.save(update_fields=["is_demo"])

        self.photo_dir = options.get("photo_dir")
        if self.photo_dir and not os.path.isdir(self.photo_dir):
            raise CommandError(f"--photo-dir {self.photo_dir} is not a directory.")
        self.photo_slots_used = set()

        user = self._pick_operator(est)
        today = timezone.localdate()
        current_year = today.year
        prior_year = current_year - 1

        self.stdout.write(self.style.MIGRATE_HEADING(f"Showcase farm: {est.name} (id {est.id})"))

        with_open_items = options["with_open_items"]

        self._seed_farm_profile(est)
        self._seed_subscription(est, pilot=with_open_items)
        self._seed_certifications(est, prior_year)
        osp = self._seed_osp(est, user)
        # Two filings: the year the closed season covers (submitted, as it would be by now)
        # and the current one (started, not submitted). Without the first, the packet flags
        # "no annual update is on file for the year this production covers".
        self._seed_annual_update(est, osp, user, prior_year, submitted=True)
        self._seed_annual_update(est, osp, user, current_year)

        parcels = self._resolve_parcels(est)
        product = self._resolve_product()
        crop = CropType.objects.filter(slug="walnuts").first()

        History.objects.filter(parcel__establishment=est).delete()
        self.stdout.write("  Cleared previous productions on this farm.")

        close_current = options["close_current"]
        total_events = 0
        for index, (block, parcel) in enumerate(zip(BLOCKS, parcels)):
            self._seed_parcel_profile(parcel, block)

            closed = self._create_production(parcel, block, prior_year, product, crop, user, finished=True)
            total_events += self._seed_season(closed, user, block, prior_year, cutoff=None, photos=True)
            self._seed_sale(closed, block, prior_year)

            # --with-open-items: the first block is finished in Trazo and the second is still
            # being wrapped up, which is where a two-block orchard is in November.
            finish_current = close_current or (with_open_items and index == 0)
            # ...and the finished one is the season the readiness card reviews, so that is where
            # the wash-down goes unlogged.
            log_wash_down = not (with_open_items and index == 0)
            cutoff = None if finish_current else today
            current = self._create_production(parcel, block, current_year, product, crop, user, finished=finish_current)
            total_events += self._seed_season(
                current, user, block, current_year, cutoff=cutoff, photos=True, log_wash_down=log_wash_down
            )
            if finish_current:
                self._seed_sale(current, block, current_year)

            # The parcel card reads this to show what is growing right now. A finished season is
            # not growing: `Parcel.finish_history_record` nulls the pointer when a grower finishes
            # one, and writing it here anyway printed "Season underway" on a block whose season
            # had closed.
            parcel.current_history = None if finish_current else current
            parcel.save(update_fields=["current_history"])

            state = "finished" if finish_current else "in progress"
            self.stdout.write(f"  {block['parcel_name']}: {prior_year} closed + {current_year} {state}.")

        self._seed_scans(est)
        self.stdout.write(self.style.SUCCESS(f"  {total_events} events written."))
        self._report_photo_slots()
        self._verify(est)

    # ------------------------------------------------------------------ farm level

    def _pick_operator(self, est):
        from users.models import WorksIn

        works_in = WorksIn.objects.filter(company=est.company).select_related("user").first()
        if works_in is None:
            raise CommandError(f"No user is attached to company {est.company_id}; cannot attribute records.")
        return works_in.user

    def _seed_farm_profile(self, est):
        est.name = FARM_NAME
        if est.company.name != COMPANY_NAME:
            est.company.name = COMPANY_NAME
            est.company.save(update_fields=["name"])
        est.description = FARM_DESCRIPTION
        # "organic", NOT "Certified Organic".
        #
        # `farming_method` is a free-text CharField describing the PRACTICE. Seeding a
        # certification NAME into it made the audit export print "Farming Method: Certified
        # Organic" in Farm Overview, several pages above the Active Certification Summary
        # that actually substantiates the claim — an unearned second assertion of status, on
        # the one farm we show certifiers. `_farming_method_phrase` now labels any
        # non-practice term as operator-entered, so leaving it would have printed a caveat on
        # the showcase packet. The real claim belongs to the certification record, which
        # `_seed_certifications` writes.
        est.farming_method = "organic"
        est.city = est.city or "Winters"
        est.state = est.state or "CA"
        est.country = est.country or "United States"
        est.zone = est.zone or "Yolo County"
        est.zip_code = est.zip_code or "95694"
        # Farm Overview printed five of nine rows as "(not provided)" / "—" on the flagship
        # demo packet: country, all three contacts, GPS, total acreage and year established.
        # A certifier reading that sees an operation that has not filled in its own header —
        # exactly the impression a recordkeeping product must not give. Every value below is
        # consistent with the rest of the fixture (Winters CA, the two blocks' acreage, and
        # the planting years named in the OSP narrative).
        est.contact_person = est.contact_person or FARM_MANAGER
        est.contact_phone = est.contact_phone or "(530) 795-4180"
        est.contact_email = est.contact_email or "paula@blueoakwalnut.example"
        est.email = est.email or "paula@blueoakwalnut.example"
        est.phone = est.phone or "(530) 795-4180"
        # Orchard centroid near Winters, Yolo County — the same coordinates the parcel
        # geometry is drawn around, so the Field Map and the Farm Overview agree.
        est.latitude = est.latitude if est.latitude is not None else 38.5381
        est.longitude = est.longitude if est.longitude is not None else -121.9764
        # Sum of the two blocks, and the figure the OSP (a)(1) narrative already states.
        est.total_acreage = est.total_acreage or float(sum(b["acres"] for b in BLOCKS))
        # The OSP narrative says the blocks were planted 1998 and 2004; the operation dates
        # from the earlier planting.
        est.year_established = est.year_established or 1998
        # § 205.201(a)(3): the plan itself is authored in OSP module G2.0 below; the profile
        # flags mirror it so the OFPP row cites a date rather than a filename guess.
        est.fraud_prevention_plan_uploaded = True
        est.fraud_prevention_plan_date = date(timezone.localdate().year, 1, 20)
        est.fraud_prevention_plan_document = "ofpp/blue-oak-fraud-prevention-plan.pdf"
        est.ofpp_responsible_person = FARM_MANAGER
        # The farm-profile card reads `establishment.album.images.first()`. On this farm that
        # first image was the OFPP **PDF**, which is why the card rendered an empty grey box.
        est.album = _gallery_from_urls([FARM_PHOTO])
        est.save()
        self.stdout.write("  Farm profile, photo + OFPP flags set.")

    def _seed_subscription(self, est, pilot=False):
        """Compliance plan, so no usage meter reads 'over limit' in the shot.

        A Starter company with two parcels and four productions renders red usage meters and an
        upsell banner directly under the headline — true to the plan limits, wrong for a
        screenshot of the plan we sell.

        `pilot`: the comped Pilot plan, which is where a design-partner farm actually is in
        November 2026. It has the same certifier exports. With one farm and nothing to add, the
        farm home draws no farm-switcher row; on Compliance the row holds a "Farm limit" lock.
        """
        slug = "pilot" if pilot else "compliance-yearly"
        plan = Plan.objects.filter(slug=slug).first()
        if plan is None:
            self.stdout.write(self.style.WARNING(f"  {slug} plan missing (run create_plans), skipped."))
            return
        now = timezone.now()
        Subscription.objects.update_or_create(
            company=est.company,
            defaults={
                "plan": plan,
                "status": "active",
                "current_period_start": now - timedelta(days=45),
                "current_period_end": now + timedelta(days=320),
                "cancel_at_period_end": False,
                "trial_end": None,
            },
        )
        self.stdout.write(f"  Subscription: {plan.name}.")

    def _seed_certifications(self, est, prior_year):
        """One organic certificate, expiring inside the deadline strip's 120-day horizon.

        Land requirements (§ 205.202) reads `verification_status == "verified"` with an
        effective date at or before the production start — that is what turns the row from
        "confirm the 36-month transition" into "certified organic since <date>".
        """
        Certification.objects.filter(establishment=est).exclude(certification_type="usda_organic").delete()
        today = timezone.localdate()
        Certification.objects.update_or_create(
            establishment=est,
            certification_type="usda_organic",
            defaults={
                "certification_number": "PSOC-CA-11482",
                "certifier_name": CERTIFIER_NAME,
                "effective_date": date(2021, 4, 1),
                "expiry_date": today + timedelta(days=77),
                "certification_scope": "Crops — tree nuts",
                "certified_items": ["Chandler Walnut"],
                # SELF-REPORTED, not verified, and deliberately so.
                #
                # An earlier cut of this seeder set verification_status="verified" with
                # verification_source="usda_organic_integrity" to make the § 205.202
                # land-requirements check pass. That put "Verified via USDA Organic Integrity
                # Database" on the public QR page of a farm that does not exist and therefore
                # cannot be in the OID — a fabricated third-party verification on the exact
                # surface the compliance rules were written for, and on an image about to be
                # published as marketing.
                #
                # A grower's own record of their certificate IS legitimate data; the product's
                # job is to label it Self-Reported until an OID cross-reference confirms it.
                # Showing that on the demo farm is the honest state AND the better argument:
                # Trazo does not rubber-stamp a claim it cannot check. The cost is that the
                # readiness card carries a second open item (Land requirements → REVIEW,
                # "confirm the 36-month transition in OSP (a)(6)"), which is a real, fixable
                # finding rather than a bought green tick.
                "verification_status": "self_reported",
                "verification_source": "",
                "usda_operation_name": "",
                "last_verified_at": None,
            },
        )
        StateOrganicRegistration.objects.update_or_create(
            establishment=est,
            state="CA",
            defaults={
                "program_name": "CDFA State Organic Program",
                "operation_type": "producer",
                "status": "registered",
                "registration_number": "CDFA-SOP-2026-3391",
                "county": "Yolo",
                "commodities": ["Walnuts"],
                "registration_date": date(2021, 4, 12),
                "renewal_date": today + timedelta(days=62),
            },
        )
        self.stdout.write("  Organic certificate + CDFA registration dated for the deadline strip.")

    def _seed_osp(self, est, user):
        """The § 205.201 plan: six filled sections, every module answered, and a registry the
        narrative names.

        EVERY version is filled, not just the newest. A plan whose status is "submitted" with
        2 of 19 modules answered is not a state an operation can actually be in — you cannot
        attest to a plan you have not answered — and the OSP page focuses a version of its own
        choosing, so a half-empty older version renders as the farm's plan. Newest version is
        the active one; anything older is superseded by it.
        """
        from certifications.osp_modules import MODULE_REGISTRY

        plans = list(OrganicSystemPlan.objects.filter(establishment=est).order_by("version_number"))
        if not plans:
            plans = [OrganicSystemPlan.objects.create(establishment=est, version_number=1, created_by=user)]

        answers_fixture = _load_osp_answers()
        for index, plan in enumerate(plans):
            is_newest = index == len(plans) - 1

            sections = plan.sections if isinstance(plan.sections, dict) else {}
            sections["inputs_list"] = {"narrative": INPUTS_NARRATIVE}
            for key, narrative in SECTION_NARRATIVES.items():
                sections[key] = {"narrative": narrative}
            plan.sections = sections

            plan.status = "active" if is_newest else "superseded"
            plan.effective_date = date(timezone.localdate().year, 1, 20)
            plan.submitted_at = plan.submitted_at or timezone.now() - timedelta(days=200)
            plan.approved_at = plan.approved_at or timezone.now() - timedelta(days=180)
            plan.approval_certifier_name = CERTIFIER_NAME

            # Every registered module ANSWERED, from `_blue_oak_osp_answers.json`. G2.0 in
            # particular IS the fraud-prevention plan when completed (2026-08-09); leaving it
            # unanswered puts a blocker on the readiness card no matter what the farm-profile flag
            # says.
            #
            # This loop used to stamp `completed_at` over an EMPTY answers dict. The answers the
            # screenshots showed existed only in database copies, and the OSP page now counts
            # required answers, so the farm read "8 of 20 modules have every answer" (2026-11-11).
            # The answers are dated a little before the plan was filed, which is when a grower
            # writes them; that date is also what "Check the plan against your records" measures
            # change from.
            answered_at = (plan.submitted_at - timedelta(days=10)).isoformat()

            # The Common OSP § 11 record types the farm keeps. G8.0's records attestation stands
            # on this list: answered Yes over an empty list, the module reports "in progress" (the
            # attestation gate), which is what it did here before this list was seeded. These are
            # the demo operator's statements, like every attestation in the answers file; on a
            # real operation only the operator's own action writes them
            # (`common_osp_records.confirm`). The narratives loop above replaced this section, so
            # it is written after it.
            from certifications.services.common_osp_records import CONFIRMATIONS_KEY
            from certifications.services.common_osp_records import OSP_SECTION_KEY as RECORDS_SECTION

            records_section = dict(plan.sections.get(RECORDS_SECTION) or {})
            records_section[CONFIRMATIONS_KEY] = {
                key: {"confirmed": True, "confirmed_at": answered_at, "confirmed_by": user.id}
                for key in answers_fixture.get("common_osp_records") or []
            }
            plan.sections[RECORDS_SECTION] = records_section

            responses = plan.module_responses or {}
            modules = responses.get("modules") or {}
            for definition in MODULE_REGISTRY:
                modules[definition.key] = _module_entry(definition.key, answers_fixture, answered_at, user)
            responses["modules"] = modules
            plan.module_responses = responses
            plan.save()

        osp = plans[-1]

        osp.approved_national_list_substances.set(
            NationalListSubstance.objects.filter(substance_name__in=NL_SUBSTANCES)
        )
        osp.approved_omri_products.set(OMRIProduct.objects.filter(product_name__in=OMRI_PRODUCTS))
        osp.approved_wsda_materials.set(WSDAMaterial.objects.filter(brand_name__in=WSDA_MATERIALS))

        missing = set(NL_SUBSTANCES) - set(
            osp.approved_national_list_substances.values_list("substance_name", flat=True)
        )
        if missing:
            self.stdout.write(self.style.WARNING(f"  National List rows not seeded, skipped: {sorted(missing)}"))
        self.stdout.write(
            f"  OSP v{osp.version_number} active ({len(plans)} version(s), all modules answered) — 6 sections, "
            f"{osp.approved_national_list_substances.count() + osp.approved_omri_products.count()} approved inputs."
        )
        return osp

    def _seed_annual_update(self, est, osp, user, year, submitted=False):
        """§ 205.406 continuation for the current year — started, not yet submitted.

        This is the orange row the whole October story hangs on: the filing is drafted from the
        season's records and waiting on the operator's signature.
        """
        OSPAnnualUpdate.objects.filter(prior_osp__establishment=est, reporting_year=year).delete()
        OSPAnnualUpdate.objects.create(
            prior_osp=osp,
            reporting_year=year,
            changes_summary=(
                "No change to crops, blocks or acreage. Fertility program unchanged. "
                "Replanted 24 Chandler on Paradox rootstock in the North Block; nursery "
                "certificate on file. Added a second copper pass in the spring blight window "
                "on the East Block. No new materials and no deletions to the approved-inputs "
                "list."
            ),
            additions=[
                {"section": "practices_procedures", "field": "planting", "new": "24 replant trees, North Block"}
            ],
            deletions=[],
            sections_unchanged_attestation={key: True for key in SECTION_NARRATIVES if key != "practices_procedures"},
            submitted_at=(timezone.now() - timedelta(days=300)) if submitted else None,
            created_by=user,
        )
        self.stdout.write(
            f"  § 205.406 annual update {year}: {'submitted' if submitted else 'started, not submitted'}."
        )

    # ------------------------------------------------------------------ parcels

    def _resolve_parcels(self, est):
        from product.models import Parcel

        parcels = []
        for block in BLOCKS:
            parcel = (
                Parcel.objects.filter(establishment=est, name=block["parcel_name"]).first()
                or Parcel.objects.filter(establishment=est).exclude(name__in=[b["parcel_name"] for b in BLOCKS]).first()
            )
            if parcel is None:
                parcel = Parcel.objects.create(establishment=est, name=block["parcel_name"])
            parcels.append(parcel)
        return parcels

    def _seed_parcel_profile(self, parcel, block):
        # This object was read BEFORE the productions were deleted, so it still carries the
        # old `current_history_id`. Saving it as-is writes that dead id back and the deferred
        # FK fails at COMMIT, after every insert has already run.
        parcel.current_history = None
        parcel.name = block["parcel_name"]
        # `Parcel.area` is HECTARES (product/models.py:23) and every surface converts to acres
        # for display. Storing the acre figure here printed "38.1 ac" for a 15.4-acre block.
        parcel.area = float(block["acres"]) / ACRES_PER_HECTARE
        parcel.description = (
            f"{block['trees']} Chandler walnuts on Paradox rootstock, 26 x 22 ft spacing, "
            f"micro-sprinkler irrigated. Certified organic."
        )
        # Replaced, not filled-in-if-missing: the album already on these parcels held a
        # supermarket avocado display and a vineyard, on a walnut farm.
        parcel.album = _gallery_from_urls([block["photo"]])
        # Closes the two red [REVIEW] flags the certifier packet printed for this farm: the
        # field map had no geometry to draw, and § 205.202(c) had no boundary record to verify.
        if block.get("polygon"):
            parcel.polygon = {"type": "Polygon", "coordinates": [block["polygon"]]}
        if block.get("buffers"):
            parcel.buffer_zones = block["buffers"]
        parcel.save()

    def _resolve_product(self):
        product = Product.objects.filter(name="Chandler Walnut").first()
        if product is None:
            product = Product.objects.filter(name="Walnuts").first()
        if product is None:
            product = Product.objects.create(name="Chandler Walnut")
        return product

    # ------------------------------------------------------------------ productions

    def _create_production(self, parcel, block, year, product, crop, user, finished):
        """One block-season. `lot_id` is only assigned once the lot physically exists."""
        history = History.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            operator=user,
            name=f"Chandler Walnuts {year} — {block['parcel_name']}",
            type="OR",
            start_date=_dt(year, 2, 3),
            expected_harvest=_dt(year, 9, 25),
            # Closed AFTER the last thing that happens in the season, not before it. At
            # Oct 12 the delivery (Oct 14) and the records review (Oct 20) both fell after
            # finalization, and the packet correctly flagged an edit past the close date —
            # a chronology error in the fixture, not a product defect.
            finish_date=_dt(year, 10, 22, 17) if finished else None,
            published=finished,
            production_method="organic",
            is_outdoor=True,
            number_of_plants=str(block["trees"]),
            age_of_plants="21 years",
            description=(
                f"{year} crop year on the {block['parcel_name']} — {block['acres']} acres of "
                "certified-organic Chandler walnuts, shaken and delivered in-shell."
            ),
            cover_image_url=WALNUT_TREE_PHOTO,
            **(
                {
                    "lot_id": f"{LOT_PREFIX}-{year}-{block['code']}-01",
                    "production_amount": float(block["acres"] * Decimal("4200")),
                    "production_unit": "lb",
                    "quality_grade": "grade_a",
                    "harvest_method": "mechanical",
                    "retention_until": date(year + 5, 12, 31),
                }
                if finished
                else {}
            ),
        )
        return history

    def _seed_scans(self, est):
        """QR scans on the published seasons — the buyer-page half of "one entry, two outputs".

        Written as ordinary `HistoryScan` rows so `HistoryScan.objects.counted()` — the one
        definition of a scan total, which billing also reads — counts them: not duplicates, bot
        score 0. `date` is `auto_now_add`, so the backdating is a second write.
        """
        published = list(History.objects.filter(parcel__establishment=est, published=True).order_by("id"))
        if not published:
            return

        HistoryScan.objects.filter(history__parcel__establishment=est).delete()
        now = timezone.now()
        total = 0
        newest = max(published, key=lambda production: (production.finish_date, production.id))
        for production in published:
            # A handful of scans on the lot that shipped most recently, and none on the rest.
            # This farm sells in-shell to one handler, so the people scanning are a buyer's
            # receiving and QA staff, not shoppers. It used to be 97 scans a month (179 across four
            # lots), a volume no wholesale lot sees, printed under the farm name on the landing
            # hero. Deterministic, so every run produces the same screenshot.
            days_ago = [2, 5, 9, 16, 23, 27] if production.id == newest.id else []
            scans = [now - timedelta(days=day, hours=3) for day in days_ago]
            # One at a time, not bulk_create: `claim_token` is minted in `HistoryScan.save()`,
            # which bulk_create skips, and the blank tokens then collide on a unique index.
            for i, when in enumerate(scans):
                row = HistoryScan.objects.create(
                    history=production,
                    is_duplicate=False,
                    bot_score=0.0,
                    consent_given=True,
                    country_code="US",
                    region="California",
                    session_hash=f"showcase-{production.id}-{i}",
                )
                HistoryScan.objects.filter(pk=row.pk).update(date=when)
            # `.update()`, not `instance.save()`: a model save fires the audit trail, and the
            # packet then reports "N edit(s) recorded after production was finalized" — telling
            # an inspector to review corrective-action context for what is really a scan
            # counter. Analytics counters are not record edits and must not look like them.
            History.objects.filter(pk=production.pk).update(
                public_views=len(scans), unique_visitors=int(len(scans) * 0.72)
            )
            total += len(scans)

        self.stdout.write(f"  {total} QR scans across {len(published)} published seasons.")

    def _seed_sale(self, production, block, year):
        """§ 205.103 sales row: buyer, lot, invoice and the organic identification on it."""
        SalesRecord.objects.filter(production=production).delete()
        SalesRecord.objects.create(
            production=production,
            sale_date=date(year, 10, 14),
            buyer_name=HANDLER_NAME,
            quantity=block["acres"] * Decimal("4200"),
            quantity_unit="lb",
            invoice_number=f"SVH-{year}-{block['code']}-0118",
            organic_on_invoice=True,
            organic_label_category="100_percent_organic",
            bill_of_lading=f"BOL-{year}-{block['code']}-4471",
            carrier_name=f"{FARM_NAME} (own truck)",
            destination=f"{HANDLER_NAME} — receiving scale, Woodland CA",
            # § 205.272: a load with transport details but no clean-transport record is a
            # packet finding. On a farm hauling its own crop the honest answer is the trailer's
            # own history plus the pre-load inspection.
            clean_transport_method="dedicated_organic",
            transport_cleaning_method="swept",
            prior_products_transported="Organic in-shell walnuts (same operation, prior load)",
            vehicle_id="CA-7Y41882",
            transport_inspected_free_of="Inspected clean and dry before loading — no residue, no commingling risk",
        )

    # ------------------------------------------------------------------ the season

    def _seed_season(self, production, user, block, year, cutoff, photos, log_wash_down=True):
        """One organic Chandler walnut season, in the order it actually happens.

        `cutoff` truncates the program at today's date for a season still under way — the
        current season shows what has happened, not what is planned.
        """
        acres = block["acres"]
        area_str = f"{acres}"
        state = {"index": 0, "count": 0}

        shift = timedelta(days=int(block.get("day_shift", 0)))

        def add(model, when, album_key=None, photo_url=None, photo_key=None, **fields):
            when = when + shift
            if cutoff is not None and when.date() > cutoff:
                return None
            album = None
            if photos:
                # Operator's own photograph first; a vetted stock image only where it genuinely
                # depicts this operation; otherwise no photo at all. A photo of an operation
                # that did not happen is worse than none — see prune_misleading_demo_photos.
                album = _gallery_from_files(self.photo_dir, photo_key) if photo_key else None
                if album is not None:
                    self.photo_slots_used.add(photo_key)
                elif photo_url:
                    album = _gallery_from_urls([photo_url])
                elif album_key:
                    album = _album(album_key)
            obj = model.objects.create(
                history=production,
                index=state["index"],
                date=when,
                created_by=user,
                album=album,
                **fields,
            )
            state["index"] += 1
            state["count"] += 1
            return obj

        # --- February: dormant work -------------------------------------------------
        add(
            ProductionEvent,
            _dt(year, 2, 6, 7),
            photo_key="pruning",
            album_key="pruning",
            type=ProductionEvent.PRUNING,
            name="Dormant pruning and brush shredding",
            description=(
                f"Dormant pruning across the {block['parcel_name']}: scaffold thinning for light "
                "penetration and removal of blight-cankered wood. Prunings shredded in place and "
                "returned to the orchard floor."
            ),
            performed_by=f"{FARM_MANAGER} + 4-person crew",
            area_covered=acres,
            area_unit="acres",
            fuel_consumed=_q(acres * Decimal("1.6")),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_hours=_q(acres * Decimal("0.9")),
            equipment_type="tractor",
            production_efficiency="normal",
            observation="Cankered wood removed and hauled out of the block before bud break.",
        )

        # The February fertility pass is a CATALOG material, not farm compost, and that is a
        # finding this seeder surfaced rather than designed around. The drift detector
        # (§ 205.400(f)(2)) resolves a soil amendment by name against the OSP's approved
        # registry — OMRI, WSDA or National List. On-farm or bulk compost is on none of those
        # catalogs, so every compost application flags "not in active OSP approved inputs",
        # correctly by the rule and unhelpfully in practice. Until the registry can hold a
        # nonsynthetic the operator makes themselves, the honest showcase uses a listed
        # material. See the note left with this work.
        add(
            SoilManagementEvent,
            _dt(year, 2, 18, 8),
            photo_key="amendment",
            album_key="organic_matter",
            type=SoilManagementEvent.ORGANIC_MATTER,
            name="Feather meal — 400 lb/acre",
            description=(
                "Nature Safe 13-0-0 Feather Meal Fertilizer broadcast at 400 lb/acre down both sides "
                "of the tree row "
                "as the season's base nitrogen, ahead of bud break. Supplier tag and invoice on "
                "file; the material is on the OSP approved-inputs list."
            ),
            performed_by=f"{FARM_MANAGER} + spreader operator",
            area_covered=acres,
            area_unit="acres",
            amendment_type="Feather Meal",
            amendment_product_name="Nature Safe 13-0-0 Feather Meal Fertilizer",
            amendment_amount=str(int(acres * 400)),
            amendment_amount_numeric=_q(acres * 400),
            amendment_amount_unit="lbs",
            amendment_nitrogen_percentage=_q("13.00"),
            amendment_organic_approved="omri_listed",
            fuel_consumed=_q(acres * Decimal("1.1")),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_hours=_q(acres * Decimal("0.5")),
            equipment_used="John Deere 6110M with side-discharge spreader",
            soil_moisture="moist",
            extra_data={
                "application_rate_lb_acre": 400,
                "n_applied_lb_acre": 52,
                "supplier_lot": f"FM-{year}-0142",
            },
        )

        # --- March: baselines and the first fertility pass ----------------------------
        add(
            SoilManagementEvent,
            _dt(year, 3, 4, 9),
            photo_key="soil-test",
            album_key="soil_test",
            type=SoilManagementEvent.SOIL_TEST,
            name="Annual soil test",
            description=(
                "Composite soil samples, 12 cores per block at 0-12 in and 12-24 in. "
                "Lab: A&L Western Laboratories, Modesto."
            ),
            performed_by="A&L Western Laboratories",
            soil_ph=_q("6.90"),
            organic_matter_percentage=_q("3.10"),
            soil_texture="clay_loam",
            area_covered=acres,
            area_unit="acres",
            working_depth=_q("24.00"),
            depth_unit="inches",
            test_results={
                "ph": 6.9,
                "organic_matter_pct": 3.1,
                "nitrate_n_ppm": 14,
                "phosphorus_ppm": 26,
                "potassium_ppm": 240,
                "zinc_ppm": 1.8,
                "boron_ppm": 0.6,
                "lab": "A&L Western Laboratories",
            },
            extra_data={"cores_per_block": 12, "report_number": f"AL-{year}-88{block['code']}"},
        )

        add(
            ProductionEvent,
            _dt(year, 3, 12, 7),
            photo_key="replant",
            album_key="planting",
            type=ProductionEvent.PLANTING,
            name="Replant — 24 Chandler on Paradox rootstock",
            description=(
                "Replanted 24 trees in the 1998 planting where blackline losses opened gaps. "
                "Nursery organic-compliance statement and invoice on file."
            ),
            performed_by=f"{FARM_MANAGER} + 2-person crew",
            area_covered=_q("0.60"),
            area_unit="acres",
            yield_quantity=_q("24.00"),
            yield_unit="plants",
            seeds_source="commercial",
            seed_supplier_name=NURSERY_SUPPLIER,
            seed_purchase_date=date(year, 2, 24),
            seed_purchase_invoice=f"SGN-{year}-2210",
            seed_lot_number=f"CHD-{year}-PX-07",
            seed_certification_status="non_organic_untreated",
            seed_treatment="None — untreated nursery stock",
            # § 205.204(a)(1) permits non-organic planting stock only when the § 205.2
            # commercial-availability test fails. The ground is structured; the search log
            # is the evidence for it.
            seed_nonavailability_reason="none_offered",
            seed_search_attempts=[
                {
                    "supplier_name": NURSERY_SUPPLIER,
                    "date_contacted": f"{year}-02-10",
                    "result": "Not offered organically — conventional Paradox rootstock only",
                    "notes": "Chandler scion on Paradox; no certified-organic nursery stock offered",
                },
                {
                    "supplier_name": "Winters Tree Nursery",
                    "date_contacted": f"{year}-02-11",
                    "result": "Not offered organically",
                    "notes": "No certified-organic walnut nursery stock in any variety",
                },
                {
                    "supplier_name": "Sacramento Rootstock Co.",
                    "date_contacted": f"{year}-02-12",
                    "result": "Not offered organically",
                    "notes": "Confirmed by phone; no organic program for walnut rootstock",
                },
            ],
            production_efficiency="normal",
        )

        add(
            ChemicalEvent,
            _dt(year, 3, 20, 6),
            photo_key="fertigation",
            type=ChemicalEvent.FERTILIZER,
            chemical_subtype="organic_fertilizer",
            name="Fertigation #1 — fish fertilizer",
            description=(
                "First fertigation pass of the season through the micro-sprinkler set: "
                "Neptune's Harvest Fish & Seaweed 2-3-1 at 4 gal/acre, injected over a "
                "4-hour run."
            ),
            performed_by=FARM_MANAGER,
            commercial_name="Neptune's Harvest Organic Fish & Seaweed Fertilizer 2-3-1",
            concentration="2-3-1",
            volume=str(int(acres * 4)),
            volume_numeric=_q(acres * 4),
            volume_unit="gal",
            area=area_str,
            area_numeric=acres,
            area_unit="acres",
            way_of_application="fertigation",
            application_method_structured="drip",
            application_timing="Pre-leaf-out, soil at field capacity",
            weather_conditions="Calm, 62 °F, no wind",
            application_purpose="Early-season nitrogen",
            organic_approved="omri_listed",
            nitrogen_source="organic",
            nitrogen_percentage=_q("2.00"),
            phosphorus_percentage=_q("3.00"),
            potassium_percentage=_q("1.00"),
            is_fertigation=True,
            applicator_name=FARM_MANAGER,
            supplier_name=INPUT_SUPPLIER,
            purchase_date=date(year, 3, 10),
            purchase_invoice=f"YAS-{year}-4417",
            quantity_purchased=_q(acres * 4 + 20),
            quantity_purchased_unit="gal",
            chemical_lot_number=f"NH{year}-0412",
            extra_data={"rate_gal_acre": 4, "injection_hours": 4},
        )

        # --- April/May: blight window and mating disruption ---------------------------
        add(
            PestManagementEvent,
            _dt(year, 3, 28, 8),
            photo_key="trap-set",
            type=PestManagementEvent.TRAP_MONITORING,
            description=(
                "Pheromone traps hung ahead of first flight: 4 codling moth and 4 navel "
                "orangeworm egg traps per block, read weekly by the crop consultant."
            ),
            performed_by=CROP_CONSULTANT,
            pest_species="Codling moth (Cydia pomonella); navel orangeworm (Amyelois transitella)",
            pest_pressure_level="Low",
            trap_type="Pheromone wing trap",
            trap_count=8,
            pest_catch_count=0,
            action_threshold_met=False,
            identified_by="crop_consultant",
            identification_method="Weekly trap counts against the UC IPM degree-day model",
            area_covered=acres,
            area_unit="acres",
            ipm_strategy=(
                "Monitoring first: traps set before biofix, counts logged weekly and run through "
                "the UC IPM degree-day model. No material is applied on calendar date — only on a "
                "documented threshold (§ 205.206(a))."
            ),
            extra_data={"biofix_set": False, "traps_per_block": 8},
        )

        add(
            PestManagementEvent,
            _dt(year, 4, 2, 7),
            photo_key="mating-disruption",
            type=PestManagementEvent.IPM_IMPLEMENTATION,
            description=(
                "Pheromone mating-disruption dispensers hung at 200 per acre before first flight, "
                "in the upper third of the canopy. Primary codling moth control for the season."
            ),
            performed_by=f"{FARM_MANAGER} + 3-person crew",
            pest_species="Codling moth (Cydia pomonella)",
            pest_pressure_level="Low",
            action_threshold_met=False,
            identified_by="crop_consultant",
            identification_method="Trap counts and degree-day model, weekly",
            beneficial_insects_used="no",
            area_covered=acres,
            area_unit="acres",
            ipm_strategy=(
                "Prevention before intervention (§ 205.206(a)): mating disruption plus winter "
                "mummy-nut sanitation carry the block. Pheromones are National List allowed "
                "(§ 205.601(f)) and are listed on the OSP approved inputs."
            ),
            extra_data={"dispensers_per_acre": 200, "product": "Pheromone dispenser, twist-tie"},
        )

        add(
            ChemicalEvent,
            _dt(year, 4, 15, 6),
            photo_key="copper-spray",
            type=ChemicalEvent.FUNGICIDE,
            chemical_subtype="copper_fungicide",
            name="Copper #1 — walnut blight (early catkin)",
            description=(
                "First blight pass at early catkin, timed to the UC IPM Xanthocast model after "
                "0.4 in of rain. Kocide 3000-O at 3.5 lb/acre by air-blast, 100 gal water/acre."
            ),
            performed_by=FARM_MANAGER,
            commercial_name="Kocide 3000-O",
            manufacturer="Certis USA",
            concentration="46.1% copper hydroxide",
            volume=str(_q(acres * Decimal("3.5"))),
            volume_numeric=_q(acres * Decimal("3.5")),
            volume_unit="lbs",
            area=area_str,
            area_numeric=acres,
            area_unit="acres",
            way_of_application="air_blast",
            application_method_structured="air_blast",
            application_timing="Early catkin, 6:00-9:00 am, before wind pick-up",
            weather_conditions="Calm, 55 °F, 78% RH, no rain forecast 24 h",
            target_pest_disease="Walnut blight (Xanthomonas arboricola pv. juglandis)",
            application_purpose="Blight protectant",
            organic_approved="omri_listed",
            applicator_name=FARM_MANAGER,
            rei_hours=48,
            phi_days=0,
            supplier_name=INPUT_SUPPLIER,
            purchase_date=date(year, 3, 30),
            purchase_invoice=f"YAS-{year}-4602",
            quantity_purchased=_q(acres * Decimal("7.5")),
            quantity_purchased_unit="lbs",
            chemical_lot_number=f"KC{year}-1188",
            national_list_substance=NationalListSubstance.objects.filter(substance_name="Copper hydroxide").first(),
            extra_data={"rate_lb_acre": 3.5, "water_gal_acre": 100, "model": "UC IPM Xanthocast"},
        )

        add(
            PestManagementEvent,
            _dt(year, 4, 24, 8),
            photo_key="scouting",
            type=PestManagementEvent.SCOUTING,
            description=(
                "Ten-tree randomized transect. Blight strikes on 2% of catkins, walnut aphid "
                "below threshold with parasitism visible (Trioxys pallidus mummies present)."
            ),
            performed_by=CROP_CONSULTANT,
            pest_species="Walnut aphid (Chromaphis juglandicola)",
            pest_pressure_level="Low",
            monitoring_count=10,
            monitoring_unit="trees",
            damage_percentage=_q("2.00"),
            action_threshold_met=False,
            identified_by="crop_consultant",
            identification_method="Visual inspection, 10x hand lens, UC IPM walnut guidelines",
            threshold_rationale=(
                "Walnut aphid at 4 per leaflet against a 15-per-leaflet treatment threshold, with "
                "Trioxys pallidus parasitism established. No material warranted."
            ),
            area_covered=acres,
            area_unit="acres",
            ipm_strategy=(
                "Biological control first: the Trioxys pallidus population is left to do the work "
                "and is monitored rather than sprayed over."
            ),
            extra_data={"aphids_per_leaflet": 4, "threshold": 15},
        )

        add(
            ChemicalEvent,
            _dt(year, 5, 2, 6),
            photo_key="copper-spray",
            type=ChemicalEvent.FUNGICIDE,
            chemical_subtype="copper_fungicide",
            name="Copper #2 — walnut blight (40% leaf-out)",
            description=(
                "Second and final blight pass at 40% leaf-out following a wet front. Kocide "
                "3000-O at 3.5 lb/acre by air-blast. Season copper load recorded."
            ),
            performed_by=FARM_MANAGER,
            commercial_name="Kocide 3000-O",
            manufacturer="Certis USA",
            concentration="46.1% copper hydroxide",
            volume=str(_q(acres * Decimal("3.5"))),
            volume_numeric=_q(acres * Decimal("3.5")),
            volume_unit="lbs",
            area=area_str,
            area_numeric=acres,
            area_unit="acres",
            way_of_application="air_blast",
            application_method_structured="air_blast",
            application_timing="40% leaf-out, early morning",
            weather_conditions="Calm, 58 °F, overcast after 0.6 in rain",
            target_pest_disease="Walnut blight (Xanthomonas arboricola pv. juglandis)",
            application_purpose="Blight protectant",
            organic_approved="omri_listed",
            applicator_name=FARM_MANAGER,
            rei_hours=48,
            phi_days=0,
            supplier_name=INPUT_SUPPLIER,
            purchase_date=date(year, 3, 30),
            purchase_invoice=f"YAS-{year}-4602",
            quantity_purchased=_q(acres * Decimal("7.5")),
            quantity_purchased_unit="lbs",
            chemical_lot_number=f"KC{year}-1188",
            national_list_substance=NationalListSubstance.objects.filter(substance_name="Copper hydroxide").first(),
            extra_data={"rate_lb_acre": 3.5, "season_copper_lb_acre_total": 7.0},
        )

        add(
            ProductionEvent,
            _dt(year, 5, 9, 6),
            photo_key="irrigation",
            type=ProductionEvent.IRRIGATION,
            name="First irrigation set",
            description=(
                "Season's first set: 3.5 acre-inches through micro-sprinkler, scheduled off CIMIS "
                "ET0 and a pressure-chamber reading of -6.5 bar."
            ),
            performed_by=FARM_MANAGER,
            area_covered=acres,
            area_unit="acres",
            water_source="well_groundwater",
            irrigation_method="micro_sprinkler",
            irrigation_depth=_q("3.50"),
            irrigation_depth_unit="inches",
            electricity_source="grid",
            pump_depth_ft=210,
            equipment_hours=_q("11.00"),
            fuel_type="electric",
            production_efficiency="high",
            # The season's water-source analysis rides on the first set. Certifiers ask for it
            # (CCOF water-source analysis; FSMA Produce Safety Rule, 21 CFR 112) and the packet
            # flags its absence.
            water_test_date=date(year, 4, 28),
            water_test_lab="A&L Western Laboratories, Modesto CA",
            water_test_results={
                "sample_date": f"{year}-04-28",
                "source": "Well, 210 ft",
                "generic_e_coli_cfu_100ml": 0,
                "total_coliform_cfu_100ml": 1,
                "nitrate_n_ppm": 3.4,
                "ph": 7.2,
                "electrical_conductivity_dS_m": 0.6,
                "meets_21_cfr_112_44": True,
            },
            observation="Distribution uniformity checked at four heads; 92%.",
        )

        add(
            PestManagementEvent,
            _dt(year, 5, 21, 7),
            photo_key="beneficial-release",
            album_key="beneficial_insects",
            type=PestManagementEvent.BENEFICIAL_RELEASE,
            description=(
                "Trichogramma platneri released at 100,000 per acre against codling moth eggs, "
                "timed to the second flight. Insectary certificate of analysis on file."
            ),
            performed_by=f"{FARM_MANAGER} + crew",
            beneficial_species="Trichogramma platneri",
            release_quantity=f"{int(acres * 100000):,}",
            beneficial_supplier="Sierra Insectary Co.",
            beneficial_lot_number=f"TP-{year}-0521",
            beneficial_organic_approved="yes",
            beneficial_insects_used="yes",
            pest_species="Codling moth (Cydia pomonella)",
            pest_pressure_level="Low",
            action_threshold_met=False,
            identified_by="crop_consultant",
            identification_method="Degree-day model, second flight biofix",
            area_covered=acres,
            area_unit="acres",
            ipm_strategy=(
                "Biological control layered on mating disruption before any material is "
                "considered, per the § 205.206(a) hierarchy."
            ),
            extra_data={"release_rate_per_acre": 100000},
        )

        # --- June/July: floor, water, heat --------------------------------------------
        add(
            ProductionEvent,
            _dt(year, 6, 4, 6),
            photo_key="mowing",
            photo_url=ORCHARD_ROW_PHOTO,
            type=ProductionEvent.MOWING,
            name="Orchard floor mowing",
            description=(
                "Resident vegetation and seeded legume mowed and left in place; berms cleaned "
                "mechanically around the replants. No herbicide is used on this operation."
            ),
            performed_by=FARM_MANAGER,
            area_covered=acres,
            area_unit="acres",
            fuel_consumed=_q(acres * Decimal("0.9")),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_hours=_q(acres * Decimal("0.35")),
            equipment_type="tractor",
            production_efficiency="normal",
        )

        add(
            ProductionEvent,
            _dt(year, 6, 18, 5),
            photo_key="irrigation",
            type=ProductionEvent.IRRIGATION,
            name="Irrigation set — shell hardening",
            description="3.5 acre-inches, micro-sprinkler, ET0-scheduled through shell hardening.",
            performed_by=FARM_MANAGER,
            area_covered=acres,
            area_unit="acres",
            water_source="well_groundwater",
            irrigation_method="micro_sprinkler",
            irrigation_depth=_q("3.50"),
            irrigation_depth_unit="inches",
            electricity_source="grid",
            pump_depth_ft=210,
            equipment_hours=_q("11.00"),
            fuel_type="electric",
            production_efficiency="high",
        )

        add(
            PestManagementEvent,
            _dt(year, 6, 26, 8),
            photo_key="trap-read",
            type=PestManagementEvent.SCOUTING,
            description=(
                "Navel orangeworm egg traps read; mummy count from winter sanitation confirms "
                "under 2 mummies per tree across the block."
            ),
            performed_by=CROP_CONSULTANT,
            pest_species="Navel orangeworm (Amyelois transitella)",
            pest_pressure_level="Low",
            monitoring_count=10,
            monitoring_unit="trees",
            trap_count=4,
            pest_catch_count=6,
            action_threshold_met=False,
            identified_by="crop_consultant",
            identification_method="Egg-trap counts plus in-field mummy survey",
            threshold_rationale=(
                "Egg trap catch of 6 over two weeks with sanitation at under 2 mummies/tree keeps "
                "the block below the hull-split treatment threshold."
            ),
            area_covered=acres,
            area_unit="acres",
            ipm_strategy=(
                "Sanitation is the primary NOW control; trap data decides whether a hull-split "
                "material is justified at all."
            ),
            extra_data={"mummies_per_tree": 1.6},
        )

        add(
            ChemicalEvent,
            _dt(year, 7, 6, 6),
            photo_key="fertigation",
            type=ChemicalEvent.FERTILIZER,
            chemical_subtype="organic_fertilizer",
            name="Fertigation #2 — fish fertilizer",
            description=(
                "Second fertigation pass following the July leaf analysis: Neptune's Harvest "
                "Fish & Seaweed 2-3-1 at 4 gal/acre through the micro-sprinkler set."
            ),
            performed_by=FARM_MANAGER,
            commercial_name="Neptune's Harvest Organic Fish & Seaweed Fertilizer 2-3-1",
            concentration="2-3-1",
            volume=str(int(acres * 4)),
            volume_numeric=_q(acres * 4),
            volume_unit="gal",
            area=area_str,
            area_numeric=acres,
            area_unit="acres",
            way_of_application="fertigation",
            application_method_structured="drip",
            application_timing="Kernel fill, injected mid-set",
            weather_conditions="Clear, 88 °F, calm",
            application_purpose="Kernel fill nutrition",
            organic_approved="omri_listed",
            nitrogen_source="organic",
            nitrogen_percentage=_q("2.00"),
            phosphorus_percentage=_q("3.00"),
            potassium_percentage=_q("1.00"),
            is_fertigation=True,
            applicator_name=FARM_MANAGER,
            supplier_name=INPUT_SUPPLIER,
            purchase_date=date(year, 6, 28),
            purchase_invoice=f"YAS-{year}-5130",
            quantity_purchased=_q(acres * 4 + 15),
            quantity_purchased_unit="gal",
            chemical_lot_number=f"NH{year}-0663",
            extra_data={"rate_gal_acre": 4, "leaf_analysis_n_pct": 2.4},
        )

        add(
            WeatherEvent,
            _dt(year, 7, 17, 15),
            type=WeatherEvent.HIGH_TEMPERATURE,
            description=(
                "Three-day heat event, 106-109 °F. Irrigation set moved forward two days and "
                "run at night to hold kernel quality; no sunburn damage recorded on assessment."
            ),
            observation="Peak 109 °F on 18 July. Set advanced, night run 22:00-06:00.",
            extra_data={"peak_temp_f": 109, "days": 3, "action": "irrigation set advanced"},
        )

        add(
            ProductionEvent,
            _dt(year, 7, 24, 5),
            photo_key="irrigation",
            type=ProductionEvent.IRRIGATION,
            name="Irrigation set — post-heat recovery",
            description="3.5 acre-inches run overnight after the heat event, micro-sprinkler.",
            performed_by=FARM_MANAGER,
            area_covered=acres,
            area_unit="acres",
            water_source="well_groundwater",
            irrigation_method="micro_sprinkler",
            irrigation_depth=_q("3.50"),
            irrigation_depth_unit="inches",
            electricity_source="grid",
            pump_depth_ft=210,
            equipment_hours=_q("11.00"),
            fuel_type="electric",
            production_efficiency="high",
        )

        # --- August: hull split -------------------------------------------------------
        add(
            PestManagementEvent,
            _dt(year, 8, 1, 7),
            photo_key="hull-split",
            # Green walnuts in husk — literally what a hull-split assessment looks at.
            photo_url=WALNUT_TREE_PHOTO,
            type=PestManagementEvent.THRESHOLD_ASSESSMENT,
            description=(
                "Hull split at 15%. NOW egg-trap catch rose to 22 over the prior week, above the "
                "hull-split treatment threshold for the block."
            ),
            performed_by=CROP_CONSULTANT,
            pest_species="Navel orangeworm (Amyelois transitella)",
            pest_pressure_level="Moderate",
            trap_count=4,
            pest_catch_count=22,
            action_threshold_met=True,
            identified_by="crop_consultant",
            identification_method="Egg-trap counts, hull-split survey on 25 trees",
            threshold_rationale=(
                "Egg-trap catch of 22 per week at 15% hull split exceeds the UC IPM treatment "
                "threshold for navel orangeworm. Sanitation and mating disruption are already in "
                "place and cannot be increased inside the window, so a single approved material "
                "is justified at hull split (§ 205.206(e))."
            ),
            area_covered=acres,
            area_unit="acres",
            ipm_strategy=(
                "Material only after the preventive tiers are exhausted and the threshold is "
                "documented; one application, timed to hull split."
            ),
            extra_data={"hull_split_pct": 15, "egg_trap_catch": 22, "threshold": 20},
        )

        add(
            ChemicalEvent,
            _dt(year, 8, 4, 6),
            photo_key="hull-split-spray",
            type=ChemicalEvent.PESTICIDE,
            chemical_subtype="biological_pesticide",
            name="Spinosad at hull split",
            description=(
                "Single hull-split application against navel orangeworm: Entrust SC at 6 fl "
                "oz/acre by air-blast, 100 gal water/acre, on the documented threshold from "
                "1 August."
            ),
            performed_by=FARM_MANAGER,
            commercial_name="Entrust SC",
            manufacturer="Corteva Agriscience",
            concentration="22.5% spinosad",
            volume=str(_q(acres * 6)),
            volume_numeric=_q(acres * 6),
            volume_unit="oz",
            area=area_str,
            area_numeric=acres,
            area_unit="acres",
            way_of_application="air_blast",
            application_method_structured="air_blast",
            application_timing="15% hull split, 5:30-8:00 am",
            weather_conditions="Calm, 71 °F, no wind, applied before bee flight",
            target_pest_disease="Navel orangeworm (Amyelois transitella)",
            application_purpose="Hull-split NOW control",
            organic_approved="omri_listed",
            applicator_name=FARM_MANAGER,
            rei_hours=4,
            phi_days=1,
            supplier_name=INPUT_SUPPLIER,
            purchase_date=date(year, 7, 27),
            purchase_invoice=f"YAS-{year}-5288",
            quantity_purchased=_q(acres * 6 + 32),
            quantity_purchased_unit="oz",
            chemical_lot_number=f"EN{year}-0774",
            national_list_substance=NationalListSubstance.objects.filter(substance_name="Spinosad").first(),
            extra_data={"rate_floz_acre": 6, "water_gal_acre": 100},
        )

        add(
            ProductionEvent,
            _dt(year, 8, 12, 5),
            photo_key="irrigation",
            type=ProductionEvent.IRRIGATION,
            name="Irrigation set — pre-harvest",
            description="Final full set before the pre-harvest dry-down, 3.5 acre-inches.",
            performed_by=FARM_MANAGER,
            area_covered=acres,
            area_unit="acres",
            water_source="well_groundwater",
            irrigation_method="micro_sprinkler",
            irrigation_depth=_q("3.50"),
            irrigation_depth_unit="inches",
            electricity_source="grid",
            pump_depth_ft=210,
            equipment_hours=_q("11.00"),
            fuel_type="electric",
            production_efficiency="high",
        )

        # --- September/October: harvest and delivery ----------------------------------
        add(
            ProductionEvent,
            _dt(year, 9, 5, 7),
            photo_key="floor-prep",
            type=ProductionEvent.MOWING,
            name="Pre-harvest floor preparation",
            description=(
                "Floor mowed tight and rolled ahead of shaking so the sweeper picks up clean. "
                "Block walked and mapped for shake order."
            ),
            performed_by=FARM_MANAGER,
            area_covered=acres,
            area_unit="acres",
            fuel_consumed=_q(acres * Decimal("1.0")),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_hours=_q(acres * Decimal("0.4")),
            equipment_type="tractor",
            production_efficiency="normal",
        )

        # `log_wash_down=False` (--with-open-items) is the season where nobody logged the wash-down:
        # the shaker still came off conventional ground, so the harvest keeps
        # `shared_with_conventional` and the readiness card reports § 205.272 as missing.
        cleaning = None
        if log_wash_down:
            cleaning = add(
                ProductionEvent,
                _dt(year, 9, 20, 7),
                photo_key="equipment-cleaning",
                type=ProductionEvent.EQUIPMENT_MAINTENANCE,
                name="Shaker and sweeper cleaning before harvest",
                description=(
                    "Shaker and sweeper are shared with a neighbouring conventional operation. Both "
                    "were pressure-washed, scrubbed and inspected before entering organic ground, per "
                    "SOP-CLEAN-002 (§ 205.272). Cleaning photographed and logged."
                ),
                performed_by=FARM_MANAGER,
                equipment_type="harvester",
                equipment_operation_type="CL",
                equipment_hours=_q("2.50"),
                cleaning_date=date(year, 9, 20),
                cleaning_asset_class="equipment",
                cleaning_method="Pressure wash, manual scrub of contact surfaces, visual inspection",
                cleaning_materials_used="Potable water; no sanitizer required for dry nut contact surfaces",
                cleaned_by=f"{FARM_MANAGER} (farm manager)",
                cleaning_protocol_reference="SOP-CLEAN-002 (§ 205.272)",
                shared_with_conventional=True,
                production_efficiency="normal",
            )

        harvest = add(
            ProductionEvent,
            _dt(year, 9, 26, 6),
            photo_key="harvest",
            type=ProductionEvent.HARVESTING,
            name="Harvest — shake and sweep",
            description=(
                f"Mechanical shake and sweep across {acres} acres. Nuts hauled the same day to "
                "the handler; weight from the handler's certified scale."
            ),
            performed_by=f"{FARM_MANAGER} + harvest crew (6)",
            area_covered=acres,
            area_unit="acres",
            yield_quantity=_q(acres * Decimal("4200")),
            yield_unit="lbs",
            harvest_quality_grade="grade_a",
            amount_determination="scale_verified",
            harvest_destination="sold_direct",
            buffer_disposition="not_harvested",
            harvest_contract_number=f"SVH-{year}-DA-118",
            shared_with_conventional=True,
            equipment_cleaning_event=cleaning,
            fuel_consumed=_q(acres * Decimal("3.4")),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_hours=_q(acres * Decimal("1.2")),
            equipment_type="harvester",
            production_efficiency="high",
            observation="Moisture at delivery 8.2%. Weigh ticket attached to the lot record.",
            extra_data={"yield_lb_acre": 4200, "moisture_pct_at_delivery": 8.2},
        )
        if harvest is not None and cleaning is None and log_wash_down:
            # Only reachable on a truncated season, where neither event exists. Guard kept so a
            # future cutoff change cannot silently produce a shared-equipment harvest with no
            # cleaning link. That is a § 205.272 finding, and it is only ever produced on
            # purpose, by --with-open-items.
            harvest.shared_with_conventional = False
            harvest.save(update_fields=["shared_with_conventional"])

        add(
            ProductionEvent,
            _dt(year, 9, 27, 9),
            photo_key="hulling",
            type=ProductionEvent.POST_HARVEST_PROCESSING,
            name="Hulling and drying",
            description=(
                "Hulled and dried at the handler's facility under the lot ID for this block. "
                "Dried to 8% moisture; handler holds its own organic certificate."
            ),
            performed_by=HANDLER_NAME,
            area_covered=acres,
            area_unit="acres",
            storage_location=f"{HANDLER_NAME} — dryer bank 3",
            production_efficiency="high",
            extra_data={"target_moisture_pct": 8.0},
        )

        add(
            BusinessEvent,
            _dt(year, 10, 14, 11),
            photo_key="delivery",
            type=BusinessEvent.COMPLIANCE,
            name="Delivery to handler",
            business_type="compliance",
            description=(
                f"In-shell delivery to {HANDLER_NAME} against the season contract. Bill of "
                "lading, purchase order and invoice all carry the lot ID and identify the "
                "product as organic (§ 205.103(b)(2))."
            ),
            performed_by=FARM_MANAGER,
            observation="Weigh ticket, BOL and handler invoice filed against this lot.",
            extra_data={
                "buyer": HANDLER_NAME,
                "organic_on_invoice": True,
                "bill_of_lading": f"BOL-{year}-{block['code']}-4471",
            },
        )

        add(
            GeneralEvent,
            _dt(year, 10, 20, 10),
            photo_key="records-review",
            name="Season records review",
            description=(
                "End-of-season records review before the certifier submission: input purchases "
                "reconciled against applications, lot IDs traced from block to handler invoice, "
                "and the year's monitoring records checked for gaps."
            ),
            performed_by=FARM_MANAGER,
            activity_type="recordkeeping",
            activity_name="Pre-submission records review",
            duration="3 hours",
            people_involved=2,
            observation="No gaps found. Copper load, threshold records and cleaning logs complete.",
        )

        return state["count"]

    def _report_photo_slots(self):
        """Say plainly which operations still have no photograph of their own.

        The "Documentation depth" check wants 10+ photos on the season. Every empty slot below
        is one a real photo from the block would fill — and the only kind of photo that can
        fill it honestly.
        """
        missing = [k for k in PHOTO_SLOTS if k not in self.photo_slots_used]
        if not missing:
            self.stdout.write(self.style.SUCCESS("  Every photo slot filled from --photo-dir."))
            return
        if self.photo_dir:
            self.stdout.write(f"  Filled from --photo-dir: {sorted(self.photo_slots_used) or 'none'}")
        self.stdout.write("  Photo slots still empty (drop <key>.jpg into --photo-dir):")
        for key in missing:
            self.stdout.write(f"    {key:<20} {PHOTO_SLOTS[key]}")

    # ------------------------------------------------------------------ verification

    def _print_demo_guidance(self, est):
        """Say which season to open in a demo, and why it is not the closed one.

        The readiness card below reports the CLOSED season, because that is the one with a
        complete packet — finish date, lot, sale, mass balance. But it is the wrong season to
        walk a prospect through, and the reason is the audit trail.

        Every record this command writes is created NOW. `auditlog` stamps each LogEntry with
        the real wall-clock time, which is correct and must not be forged — that log is the
        artifact the packet's Record Change History section offers as proof the records were
        not fabricated, and back-dating it to look contemporaneous would falsify exactly the
        thing it exists to prove. On the CLOSED (prior-year) season that produces a packet
        whose events are dated last autumn and whose entries are all stamped today: to a
        certifier that reads as a season back-entered in one sitting.

        The CURRENT season does not have that problem in the same way. It is in progress, its
        events run up to today, and records entered now sit naturally against them — which is
        also the true story of any operation that adopts recordkeeping software mid-season.

        So: demo the current season. Export the closed one only to show what a finished
        packet contains, and say out loud that it is seeded historical data.
        """
        current_year = timezone.localdate().year
        current = (
            History.objects.filter(parcel__establishment=est, start_date__year=current_year)
            .order_by("-start_date")
            .first()
        )
        if current is None:
            return
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Demo this season"))
        self.stdout.write(f"  {current.name} (id {current.id}, public_id {current.public_id})")
        if current.finish_date is None:
            self.stdout.write(
                "  In progress, events run to today, and its entry timestamps sit naturally against them."
            )
        else:
            # --close-current or --with-open-items closed it, so "in progress" would be a false
            # claim about the very artifact this note exists to keep honest.
            self.stdout.write(
                "  Closed this crop year. Its events are recent, so the entry "
                "timestamps still read far more naturally than the prior season's."
            )
        self.stdout.write(
            self.style.WARNING(
                "  The closed season below has a fuller packet but every record was entered "
                "today, so its Record Change History reads as one back-entered batch. Show it "
                "for packet CONTENT, not as a live audit trail."
            )
        )

    def _verify(self, est):
        """Print exactly what the dashboard card will show. No separate implementation."""
        from history.services.audit_export_service import AuditExportService
        from history.services.operation_readiness_service import OperationReadinessService

        production = (
            History.objects.filter(parcel__establishment=est, published=True, finish_date__isnull=False)
            .order_by("-finish_date")
            .first()
            or History.objects.filter(parcel__establishment=est).order_by("-start_date").first()
        )
        if production is None:
            self.stdout.write(self.style.ERROR("  No production on this farm."))
            return

        self._print_demo_guidance(est)

        rows = AuditExportService(production, certification_type="organic").compliance_snapshot_rows()
        findings = [r for r in rows if r["status"] != "PASS"]
        operation = OperationReadinessService(est).evaluate()
        op_items = (operation["blockers"] + operation["warnings"]) if operation["applicable"] else []

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Readiness card — {production.name}"))
        self.stdout.write(f"  {len(rows)} record checks, {len(findings) + len(op_items)} open")
        for item in op_items:
            self.stdout.write(self.style.WARNING(f"  OPERATION {item['status']}: {item['title']}"))
        for row in findings:
            self.stdout.write(self.style.WARNING(f"  SEASON {row['status']}: {row['label']} — {row['detail'][:90]}"))
        if not findings and not op_items:
            self.stdout.write(self.style.SUCCESS("  Nothing outstanding — every check passes."))
