"""
Seed the National List of Allowed and Prohibited Substances.

Source: 7 CFR 205.601 (synthetics allowed, crops) and 205.602 (nonsynthetics prohibited, crops),
plus the § 205.605(b) sanitizers a crop operation uses in post-harvest handling.
Data extracted from the eCFR canonical text as of 2026-04-13.

Run after every NOSB sunset cycle (~every 2 years) to pick up amendments.

    poetry run python manage.py seed_national_list
    poetry run python manage.py seed_national_list --reset
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from certifications.models import NationalListSubstance


def _normalize(name: str) -> str:
    """Lowercase + strip + collapse whitespace for fuzzy matching keys."""
    return re.sub(r"\s+", " ", name.strip().lower())


# 7 CFR 205.601 — Synthetic substances allowed for use in organic CROP production.
# Each entry: (subsection, category, substance_name, restriction_notes)
SECTION_601_ALLOWED = [
    # (a) Algicides, disinfectants, and sanitizers
    ("a", "sanitizer", "Ethanol", None),
    ("a", "sanitizer", "Isopropanol", None),
    (
        "a",
        "sanitizer",
        "Calcium hypochlorite",
        "Residual chlorine in direct crop contact must not exceed SDWA maximum residual disinfectant limit.",
    ),
    (
        "a",
        "sanitizer",
        "Chlorine dioxide",
        "Residual chlorine in direct crop contact must not exceed SDWA maximum residual disinfectant limit.",
    ),
    ("a", "sanitizer", "Hypochlorous acid (from electrolyzed water)", "Same SDWA chlorine limit applies."),
    ("a", "sanitizer", "Potassium hypochlorite", "Irrigation water only; SDWA chlorine limit applies."),
    ("a", "sanitizer", "Sodium hypochlorite", "Same SDWA chlorine limit applies."),
    ("a", "sanitizer", "Copper sulfate (algicide)", "Aquatic rice only; one application per field per 24 months."),
    ("a", "sanitizer", "Hydrogen peroxide", None),
    ("a", "sanitizer", "Ozone gas", "Irrigation system cleaning only."),
    ("a", "sanitizer", "Peracetic acid", "Equipment, seed, and asexual plant material disinfection only."),
    ("a", "sanitizer", "Soap-based algicide/demossers", None),
    ("a", "sanitizer", "Sodium carbonate peroxyhydrate", "Per EPA label for food crops."),
    # (b) Herbicides and weed barriers
    ("b", "herbicide", "Soap-based herbicides", "Farmstead and ornamental crops only."),
    ("b", "herbicide", "Newspaper or recycled paper mulch", "No glossy or colored inks."),
    ("b", "herbicide", "Plastic mulch (petroleum-based, non-PVC)", None),
    (
        "b",
        "herbicide",
        "Biodegradable biobased mulch film",
        "Must not contain organisms or feedstock from excluded methods.",
    ),
    # (c) Compost feedstocks
    ("c", "compost_feedstock", "Newspaper or recycled paper", "No glossy or colored inks."),
    # (d) Animal repellents
    ("d", "repellent", "Ammonium soaps", "Large animals only; no direct soil or crop contact."),
    # (e) Insecticides (including acaricides / mite control)
    ("e", "insecticide", "Ammonium carbonate", "Insect trap bait only; no direct crop or soil contact."),
    ("e", "insecticide", "Aqueous potassium silicate", "Silica source must be naturally occurring sand."),
    ("e", "insecticide", "Boric acid", "Structural pest control only; no contact with organic crops or food."),
    (
        "e",
        "insecticide",
        "Copper sulfate (insecticide)",
        "Tadpole shrimp control in aquatic rice; one application per field per 24 months.",
    ),
    ("e", "insecticide", "Elemental sulfur", None),
    ("e", "insecticide", "Lime sulfur", "Including calcium polysulfide."),
    ("e", "insecticide", "Horticultural oils", "Narrow range only; dormant, suffocating, and summer applications."),
    ("e", "insecticide", "Insecticidal soaps", None),
    ("e", "insecticide", "Sticky traps/barriers", None),
    ("e", "insecticide", "Sucrose octanoate esters", "Per approved labeling."),
    # Added 2026-04-14: broader coverage for commonly-used OMRI-listed inputs.
    (
        "e",
        "insecticide",
        "Spinosad",
        "Natural fermentation product of Saccharopolyspora spinosa. Restricted to 3 applications/year per EPA label.",
    ),
    ("e", "insecticide", "Microbial products (Bacillus thuringiensis, etc.)", "Nontoxigenic strains only."),
    ("e", "insecticide", "Pheromone traps", None),
    (
        "e",
        "insecticide",
        "d-Limonene",
        "NOSB-recommended for organic use. Natural citrus extract; also used as § 205.601(b) herbicide.",
    ),
    # (f) Insect management
    ("f", "pheromone", "Pheromones", None),
    # (g) Rodenticides
    ("g", "rodenticide", "Vitamin D3", None),
    # (h) Slug or snail bait
    ("h", "molluscicide", "Ferric phosphate", None),
    # (i) Crop disease control
    ("i", "disease_control", "Copper hydroxide", "Minimize soil accumulation; not for herbicide use."),
    ("i", "disease_control", "Copper oxide", "Minimize soil accumulation; not for herbicide use."),
    ("i", "disease_control", "Copper oxychloride", "Minimize soil accumulation; not for herbicide use."),
    ("i", "disease_control", "Copper sulfate (fungicide)", "Minimize soil accumulation."),
    ("i", "disease_control", "Hydrated lime", None),
    ("i", "disease_control", "Peracetic acid (fire blight)", "Fire blight control only."),
    ("i", "disease_control", "Potassium bicarbonate", None),
    ("i", "disease_control", "Polyoxin D zinc salt", None),
    (
        "i",
        "disease_control",
        "Hydrogen peroxide",
        "Same as § 205.601(a) sanitizer use; allowed for plant disease control.",
    ),
    # (j) Crop or soil amendments
    (
        "j",
        "amendment",
        "Aquatic plant extracts (non-hydrolyzed)",
        "Extraction limited to potassium or sodium hydroxide.",
    ),
    ("j", "amendment", "Humic acids", "Naturally occurring; water and alkali extracts only."),
    ("j", "amendment", "Lignin sulfonate", "Chelating agent, dust suppressant."),
    ("j", "amendment", "Magnesium oxide", "Viscosity control for clay suspension agents for humates only."),
    ("j", "amendment", "Magnesium sulfate", "Documented soil deficiency required."),
    (
        "j",
        "amendment",
        "Soluble boron products",
        "Micronutrient deficiency must be documented by soil or tissue testing.",
    ),
    (
        "j",
        "amendment",
        "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt (sulfates, carbonates, oxides, silicates)",
        "Micronutrient deficiency documentation required.",
    ),
    (
        "j",
        "amendment",
        "Liquid fish products",
        "pH adjustable with sulfuric, citric, or phosphoric acid (minimum needed to reach pH 3.5).",
    ),
    ("j", "amendment", "Vitamins C and E", None),
    ("j", "amendment", "Squid byproducts", "Food waste processing only; pH adjustable with acids to pH 3.5."),
    ("j", "amendment", "Sulfurous acid", "On-farm generation using 99% purity elemental sulfur."),
    # (k) Plant growth regulators
    ("k", "plant_growth_regulator", "Ethylene gas", "Pineapple flowering regulation only."),
    (
        "k",
        "plant_growth_regulator",
        "Fatty alcohols (C6, C8, C10, C12)",
        "Sucker control in organic tobacco production only.",
    ),
    # (l) Floating agents in postharvest handling
    ("l", "postharvest", "Sodium silicate", "Tree fruit and fiber processing only."),
    # (m) Synthetic inert ingredients
    ("m", "inert", "EPA List 4 inerts (Minimal Concern)", None),
    ("m", "inert", "EPA List 3 inerts (Unknown Toxicity)", "Passive pheromone dispensers only."),
    # (n) Seed preparations
    ("n", "seed_preparation", "Hydrogen chloride", "Cotton seed delinting for planting only."),
    # (o) Production aids
    (
        "o",
        "production_aid",
        "Microcrystalline cheesewax",
        "Log-grown mushroom production; no ethylene-propylene co-polymer or synthetic colors.",
    ),
    (
        "o",
        "production_aid",
        "Paper-based crop planting aids",
        "Virgin or recycled paper without glossy or colored inks.",
    ),
]

# 🔴 The KIND of every annotation is declared per section, never guessed from the prose.
# A § 205.601/§ 205.602 note states a condition under which the CFR PERMITS the substance; a
# § 205.105 note explains why the substance is banned and permits nothing. Both are prose in
# `restriction_notes`, so only this declaration separates "calcium chloride for bitter pit is
# allowed" from "glyphosate is a synthetic herbicide". See NationalListSubstance.annotation_kind.
ANNOTATION_BY_SECTION = {
    "205.601": NationalListSubstance.ANNOTATION_CONDITION,
    "205.602": NationalListSubstance.ANNOTATION_CONDITION,
    "205.105": NationalListSubstance.ANNOTATION_RATIONALE,
    "205.605": NationalListSubstance.ANNOTATION_CONDITION,
}

# 7 CFR 205.605(b) — synthetic substances allowed in organic HANDLING, limited to the sanitizers a crop
# operation meets in post-harvest wash and rinse water and on food contact surfaces. Text verified
# against the eCFR versioner, Title 7 issue of 2026-09-04 (2026-09-10). § 205.601(a) lists sanitizers
# for crop PRODUCTION — equipment, irrigation, seed — so a flume sanitizer that could only be attached
# from § 205.601 printed on the packet under the wrong section (OTCO desk read, 2026-09-10).
# (b)(12) "Chlorine materials" is one entry with four named materials under one annotation.
# ⛔ Mirrored in migration 0038, which is what puts them in production (start.sh runs only
# `migrate`). Kept here too because a migration never runs twice: after `--reset`, which deletes
# every row, the handling rows would otherwise be gone for good.
# `test_the_seeder_and_the_migration_agree` pins the two.
CHLORINE_605 = (
    "disinfecting and sanitizing food contact surfaces, equipment and facilities may be used "
    "up to maximum labeled rates. Chlorine materials in water used in direct crop or food "
    "contact are permitted at levels approved by the FDA or EPA for such purpose, provided "
    "the use is followed by a rinse with potable water at or below the maximum residual "
    "disinfectant limit for the chlorine material under the Safe Drinking Water Act. Chlorine "
    "in water used as an ingredient in organic food handling must not exceed the maximum "
    "residual disinfectant limit for the chlorine material under the Safe Drinking Water Act."
)
SECTION_605_ALLOWED = [
    (
        "b",
        "sanitizer",
        "Acidified sodium chlorite",
        "Secondary direct antimicrobial food treatment and indirect food contact surface sanitizing. Acidified with citric acid only.",
    ),
    ("b", "sanitizer", "Calcium hypochlorite", CHLORINE_605),
    ("b", "sanitizer", "Chlorine dioxide", CHLORINE_605),
    ("b", "sanitizer", "Hypochlorous acid (generated from electrolyzed water)", CHLORINE_605),
    ("b", "sanitizer", "Sodium hypochlorite", CHLORINE_605),
    ("b", "sanitizer", "Hydrogen peroxide", None),
    ("b", "sanitizer", "Ozone", None),
    (
        "b",
        "sanitizer",
        "Peracetic acid/Peroxyacetic acid",
        "For use in wash and/or rinse water according to FDA limitations. For use as a sanitizer on food contact surfaces.",
    ),
]


# 7 CFR 205.602 — Nonsynthetic substances PROHIBITED for use in organic crop production.
SECTION_602_PROHIBITED = [
    (None, "prohibited", "Ash from manure burning", None),
    (None, "prohibited", "Arsenic", None),
    (
        None,
        "prohibited",
        "Calcium chloride (brine process)",
        "Allowed only as foliar spray for calcium uptake disorders.",
    ),
    (None, "prohibited", "Lead salts", None),
    (None, "prohibited", "Potassium chloride", "Permitted from mined sources under certain conditions."),
    (None, "prohibited", "Rotenone", None),
    (None, "prohibited", "Sodium fluoaluminate (mined)", None),
    (None, "prohibited", "Sodium nitrate", "Restricted to 20% of total nitrogen requirement."),
    (None, "prohibited", "Strychnine", None),
    (None, "prohibited", "Tobacco dust (nicotine sulfate)", None),
]


# 7 CFR 205.105 — Substances & methods EXCLUDED from organic crop production, plus
# the curated NOP 5034-2 "Appendix of Prohibited Materials" of common synthetic
# crop inputs that are prohibited because they are synthetic and NOT listed on
# § 205.601 (§ 205.105(a)). Seeding these as positive "prohibited" rows lets the
# audit export fire the hard-disqualification path when a farmer logs one, instead
# of treating a known-prohibited synthetic as merely "unresolved / no match".
# Each entry: (subsection of § 205.105, category, substance_name, notes)
SECTION_105_PROHIBITED = [
    # (a) synthetic substances not on § 205.601 — common prohibited crop pesticides
    ("a", "herbicide", "Glyphosate", "Synthetic herbicide; not on § 205.601 (NOP 5034-2)."),
    ("a", "herbicide", "2,4-D", "Synthetic herbicide; not on § 205.601 (NOP 5034-2)."),
    ("a", "herbicide", "Atrazine", "Synthetic herbicide; not on § 205.601 (NOP 5034-2)."),
    ("a", "herbicide", "Paraquat", "Synthetic herbicide; not on § 205.601 (NOP 5034-2)."),
    ("a", "herbicide", "Dicamba", "Synthetic herbicide; not on § 205.601 (NOP 5034-2)."),
    ("a", "insecticide", "Chlorpyrifos", "Synthetic insecticide; not on § 205.601 (NOP 5034-2)."),
    ("a", "insecticide", "Carbaryl", "Synthetic insecticide; not on § 205.601 (NOP 5034-2)."),
    ("a", "insecticide", "Imidacloprid", "Neonicotinoid; not on § 205.601 (NOP 5034-2)."),
    ("a", "insecticide", "Malathion", "Synthetic insecticide; not on § 205.601 (NOP 5034-2)."),
    ("a", "fungicide", "Captan", "Synthetic fungicide; not on § 205.601 (NOP 5034-2)."),
    ("a", "fungicide", "Mancozeb", "Synthetic fungicide; not on § 205.601 (NOP 5034-2)."),
    ("a", "fungicide", "Chlorothalonil", "Synthetic fungicide; not on § 205.601 (NOP 5034-2)."),
    ("a", "fumigant", "Methyl bromide", "Synthetic fumigant; not on § 205.601 (NOP 5034-2)."),
    ("a", "fumigant", "Metam sodium", "Synthetic fumigant; not on § 205.601 (NOP 5034-2)."),
    ("a", "fumigant", "Chloropicrin", "Synthetic fumigant; not on § 205.601 (NOP 5034-2)."),
    ("a", "fumigant", "1,3-Dichloropropene", "Synthetic fumigant (Telone); not on § 205.601 (NOP 5034-2)."),
    ("a", "fertilizer", "Urea (synthetic)", "Synthetic nitrogen fertilizer; not on § 205.601."),
    ("a", "fertilizer", "Ammonium nitrate", "Synthetic nitrogen fertilizer; not on § 205.601."),
    ("a", "fertilizer", "Anhydrous ammonia", "Synthetic nitrogen fertilizer; not on § 205.601."),
    ("a", "fertilizer", "Diammonium phosphate", "Synthetic fertilizer (DAP); not on § 205.601."),
    # § 205.105 paragraph letters, verified against the frozen CFR corpus 2026-08-18:
    #   (a) synthetic  (b) nonsynthetic per .602/.604  (c) nonagricultural in processed
    #   (d) nonorganic agricultural in processed  (e) EXCLUDED METHODS
    #   (f) IONIZING RADIATION  (g) SEWAGE SLUDGE
    # The three rows below were seeded as (d)/(e)/(f) — every one shifted a letter early, so
    # operator-facing prohibited-substance rationales named the wrong clause. (d) is the
    # processed-product nonorganic-ingredient paragraph, not genetic engineering.
    # (e) excluded methods — genetic engineering
    ("e", "prohibited_method", "Genetically engineered / excluded-method inputs", "Prohibited under § 205.105(e)."),
    # (f) ionizing radiation
    ("f", "prohibited_method", "Ionizing radiation (irradiation)", "Prohibited under § 205.105(f)."),
    # (g) sewage sludge
    ("g", "amendment", "Sewage sludge (biosolids)", "Prohibited under § 205.105(g)."),
]


class Command(BaseCommand):
    help = "Seed the National List of Allowed and Prohibited Substances (7 CFR 205.601/205.602/205.105)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing entries before seeding (idempotent refresh).",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts.get("reset"):
            deleted, _ = NationalListSubstance.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing entries"))

        created = 0
        updated = 0

        for subsection, category, name, notes in SECTION_601_ALLOWED:
            _, was_created = NationalListSubstance.objects.update_or_create(
                substance_name_normalized=_normalize(name),
                cfr_section="205.601",
                defaults=dict(
                    substance_name=name,
                    subsection=subsection,
                    category=category,
                    status="allowed",
                    restriction_notes=notes,
                    annotation_kind=(
                        ANNOTATION_BY_SECTION["205.601"] if notes else NationalListSubstance.ANNOTATION_NONE
                    ),
                ),
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        for subsection, category, name, notes in SECTION_602_PROHIBITED:
            _, was_created = NationalListSubstance.objects.update_or_create(
                substance_name_normalized=_normalize(name),
                cfr_section="205.602",
                defaults=dict(
                    substance_name=name,
                    subsection=subsection,
                    category=category,
                    status="prohibited",
                    restriction_notes=notes,
                    annotation_kind=(
                        ANNOTATION_BY_SECTION["205.602"] if notes else NationalListSubstance.ANNOTATION_NONE
                    ),
                ),
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        for subsection, category, name, notes in SECTION_605_ALLOWED:
            _, was_created = NationalListSubstance.objects.update_or_create(
                substance_name_normalized=_normalize(name),
                cfr_section="205.605",
                defaults=dict(
                    substance_name=name,
                    subsection=subsection,
                    category=category,
                    status="allowed",
                    restriction_notes=notes,
                    annotation_kind=(
                        ANNOTATION_BY_SECTION["205.605"] if notes else NationalListSubstance.ANNOTATION_NONE
                    ),
                ),
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        # § 205.105 excluded substances/methods + NOP 5034-2 Appendix of Prohibited Materials
        for subsection, category, name, notes in SECTION_105_PROHIBITED:
            _, was_created = NationalListSubstance.objects.update_or_create(
                substance_name_normalized=_normalize(name),
                cfr_section="205.105",
                defaults=dict(
                    substance_name=name,
                    subsection=subsection,
                    category=category,
                    status="prohibited",
                    restriction_notes=notes,
                    annotation_kind=(
                        ANNOTATION_BY_SECTION["205.105"] if notes else NationalListSubstance.ANNOTATION_NONE
                    ),
                ),
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        self.stdout.write(
            self.style.SUCCESS(
                f"National List seeded: {created} created, {updated} updated. "
                f"Total rows: {NationalListSubstance.objects.count()}"
            )
        )
