"""
Seed the National List of Allowed and Prohibited Substances.

Source: 7 CFR 205.601 (synthetics allowed, crops) and 205.602 (nonsynthetics prohibited, crops).
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


class Command(BaseCommand):
    help = "Seed the National List of Allowed and Prohibited Substances (7 CFR 205.601/205.602)."

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
