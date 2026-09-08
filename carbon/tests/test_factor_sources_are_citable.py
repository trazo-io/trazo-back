"""
Every emission factor that claims publication must name a document someone can open.

## Why this exists

`verified_emission_factors.py` already states the rule in prose — an entry marked
`PROVENANCE_PUBLISHED` is one whose `source` "resolves to a document a certifier could look up",
and naming an agency instead of a publication is called out there as the failure mode. Prose did
not hold it. On 2026-09-07 two factors were found sitting as PUBLISHED under

    source="EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)"

The Hub publishes fuel combustion factors. It contains no fertilizer manufacturing factors at
all, so `phosphorus_fertilizer` (1.19 kg CO2/kg P2O5) and `potassium_fertilizer` (0.65 kg CO2/kg
K2O) cited a document that does not say what they claimed. That attribution had propagated to
`documentation/reference/emission-factors.md`, to the guard tests, and to the **public methodology
page on the marketing site**, where it appeared in a column headed "Source" — the fabricated
attribution that `.claude/rules/compliance.md` puts first on its checklist, and a
substantiation failure under 16 CFR 260.2 for a company whose product is transparency.
(260.2, not 260.6: 260.6 governs certifications and seals. The defect here is claiming an
agency said something it did not — see compliance.md for the 260.4 / 260.6 split.)

The same sweep found the electricity factor at 0.39 kg CO2/kWh under a citation
("eGRID2023 Summary Tables, 767.2 lbs/MWh + 5.12% T&D") whose own arithmetic gives 0.366. Nobody
had done the multiplication since the value was written.

So: one place decides whether a factor may present itself as published, and it is a test rather
than a habit. This is the same shape as `history/tests/test_anonymous_endpoint_inventory.py` —
an allowlist that must be edited deliberately, where the edit is the review.

## What it does not do

It cannot check that a number is CORRECT. A human still has to open the document and do the
arithmetic. What it makes impossible is the specific move that actually happened twice: a factor
acquiring the appearance of an agency citation without anyone having opened the agency's page.
"""

from __future__ import annotations

import datetime
import re

from django.test import SimpleTestCase

from carbon.services.verified_emission_factors import (
    PROVENANCE_INTERNAL_ESTIMATE,
    PROVENANCE_PUBLISHED,
    PROVENANCE_UNVERIFIED,
    EmissionFactor,
    VerifiedEmissionFactors,
)

#: Sources a human has opened. A factor may only call itself PUBLISHED if its `source` string is
#: one of these, exactly. Exactness is the point: a reworded citation is a new claim and should
#: come back through this list, which is where someone is obliged to check it again.
#:
#: Adding a line here is a statement that you opened the document and the factor is in it.
CITABLE_SOURCES = {
    # --- US federal -----------------------------------------------------------------------
    # https://www.epa.gov/climateleadership/ghg-emission-factors-hub — fuel combustion ONLY.
    # ⛔ This publication contains no fertilizer, no fugitive-refrigerant and no agricultural
    #    process factors. See `test_no_fertilizer_factor_cites_the_fuel_combustion_tables`.
    "EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)",
    "EPA 40 CFR Part 98 Table C-1",
    "EPA 40 CFR Part 98 Table C-1 (0.138 mmBtu/gal × 73.96 kg CO₂/mmBtu)",
    "EPA 40 CFR Part 98 Table C-1 (0.125 mmBtu/gal × 70.22 kg CO₂/mmBtu)",
    "EPA 40 CFR Part 98 Table C-1 (0.091 mmBtu/gal × 62.87 kg CO₂/mmBtu)",
    "EPA 40 CFR Part 98 Table C-1 (0.001026 mmBtu/scf × 53.06 kg CO₂/mmBtu)",
    "EPA 40 CFR Part 98 + IPCC 2006/2019 Guidelines Direct N2O (EF1=1%)",
    # https://www.epa.gov/egrid/summary-data — U.S. row of the Summary Tables, Revision 2,
    # released 2025-06-12: CO2 767.2, CO2e 770.9 lb/MWh, grid gross loss 4.2%.
    # Checked 2026-09-07; eGRID2023 was still the current edition, eGRID2024 "next planned".
    "EPA eGRID2023 Summary Tables rev.2 (U.S. 770.9 lb CO2e/MWh, 4.2% grid gross loss)",
    # --- International bodies -------------------------------------------------------------
    "IPCC 2019 Refinement Vol.4 Ch.11 Tables 11.1 & 11.3 "
    "(EF1 0.010, EF4 0.010, EF5 0.011, FracGASM 0.21, FracLEACH-(H) 0.24); GWP100 265 (IPCC AR5)",
    # --- National grid operators (annual published intensity) ------------------------------
    "MIEM/DNE Balance Energético Nacional (BEN) 2024 — Factor de emisión de CO2 del SIN " "(FE_SIN 6.263 tCO2/GWh)",
    "ONS Brazil 2023 (~80% hydro)",
    "XM Colombia 2023 (~70% hydro)",
    "COES Peru 2023 (~60% hydro)",
    "CEN Chile 2023",
    "CAMMESA Argentina 2023",
    "CENACE Mexico 2023",
    # --- Named peer-reviewed literature ----------------------------------------------------
    "Audsley et al. 2009, range 5.1-19 kg; cross-validated Hillier et al. 2009",
    "Lal 2004 (6.3±2.7 kg), Audsley et al. 2009 (18-27 kg); Hillier et al. 2009",
    "Lal 2004 (3.9±2.2 kg), agricultural LCA studies",
    # --- A published equation rather than a published number --------------------------------
    "Irrigation pumping-energy equation (kWh/AF = 1.0241 × TDH / OPE) at 200 ft lift, 20 psi, 70% OPE",
}

#: Factors whose origin we cannot establish. Being here is not a parking space — it is a
#: statement that the number is in use while its source is unknown, which is a thing someone
#: should be uncomfortable reading. Each entry carries why.
#:
#: An unverified factor must not be quoted, and must not appear with a source in any
#: certifier-facing or consumer-facing surface.
UNVERIFIED_REGISTER = {
    # Empty, and it should normally stay empty. PROVENANCE_UNVERIFIED is a landing state for a
    # factor whose origin we genuinely cannot establish — it is not a resting place, and the
    # tests below make it impossible to occupy silently.
    #
    # It was occupied for one day. phosphorus_fertilizer and potassium_fertilizer were moved here
    # on 2026-09-07 when their EPA attribution was found to be false, then moved on to
    # PROVENANCE_INTERNAL_ESTIMATE once the decision was made: hold both values at the
    # conservative end of the published range and say so, rather than adopt European production
    # figures for US farms — which would have swapped an unsourced number for a mis-scoped one
    # and moved the estimate DOWN. See documentation/reference/emission-factors.md.
}

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _all_factors() -> dict[tuple[str, str], EmissionFactor]:
    """Every `EmissionFactor` reachable from the registry class, by (container, key).

    Walked by reflection rather than from a hand-kept list, so a factor added to a new dict is
    covered the moment it exists. A guard you have to remember to extend is one you will forget
    to extend on the day it matters.
    """
    found: dict[tuple[str, str], EmissionFactor] = {}
    for attr in dir(VerifiedEmissionFactors):
        if attr.startswith("__"):
            continue
        try:
            container = getattr(VerifiedEmissionFactors, attr)
        except Exception:  # noqa: BLE001 — properties that need an instance
            continue
        if not isinstance(container, dict):
            continue
        for key, value in container.items():
            if isinstance(value, EmissionFactor):
                found[(attr, str(key))] = value
            elif isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, EmissionFactor):
                        found[(attr, f"{key}.{sub_key}")] = sub_value
    return found


class FactorSourceCitabilityTests(SimpleTestCase):
    def test_the_walk_actually_found_the_registry(self):
        """A guard that reads nothing passes for the wrong reason."""
        factors = _all_factors()
        self.assertGreater(len(factors), 40, "reflection walk found almost nothing — did the registry move?")
        self.assertIn(("EPA_CHEMICAL_FACTORS", "nitrogen_fertilizer"), factors)
        self.assertIn(("EPA_ELECTRICITY_FACTORS", "electricity_us_avg"), factors)

    def test_every_factor_states_a_source_and_a_review_date(self):
        for (container, key), factor in sorted(_all_factors().items()):
            with self.subTest(factor=f"{container}.{key}"):
                self.assertTrue(factor.source.strip(), "empty source")
                self.assertTrue(
                    _ISO_DATE.match(factor.last_updated or ""),
                    f"last_updated must be YYYY-MM-DD, got {factor.last_updated!r}",
                )
                self.assertLessEqual(
                    datetime.date.fromisoformat(factor.last_updated),
                    datetime.date.today(),
                    "last_updated is in the future",
                )

    def test_a_published_factor_cites_a_source_someone_has_opened(self):
        """The whole point. A novel citation string fails until a human adds it to the list."""
        offenders = [
            f"{container}.{key} -> {factor.source!r}"
            for (container, key), factor in sorted(_all_factors().items())
            if factor.provenance == PROVENANCE_PUBLISHED and factor.source not in CITABLE_SOURCES
        ]
        self.assertEqual(
            offenders,
            [],
            "These factors claim PROVENANCE_PUBLISHED with a source that is not in "
            "CITABLE_SOURCES. Open the document, confirm the number is in it, then add the exact "
            "string to CITABLE_SOURCES with the URL in a comment. If you cannot find it in the "
            "document, the factor is not published:\n  " + "\n  ".join(offenders),
        )

    def test_no_fertilizer_factor_cites_the_fuel_combustion_tables(self):
        """The specific fabrication that happened, made permanent.

        40 CFR Part 98 and the Emission Factors Hub are fuel combustion. A nutrient
        manufacturing factor cannot come from either, however plausible the string looks.
        `nitrogen_fertilizer` is the one legitimate near-miss: it cites Part 98 *and* IPCC,
        because its N2O field component genuinely is IPCC's, so it is matched on the exact
        combined string rather than excluded by hand.
        """
        forbidden = ("40 CFR Part 98", "Emission Factors Hub")
        allowed_nitrogen = "EPA 40 CFR Part 98 + IPCC 2006/2019 Guidelines Direct N2O (EF1=1%)"
        offenders = []
        for (container, key), factor in sorted(_all_factors().items()):
            nutrient_unit = any(token in factor.unit for token in ("_kg_N", "P2O5", "K2O"))
            if "fertilizer" not in key and not nutrient_unit:
                continue
            if factor.source == allowed_nitrogen:
                continue
            if any(token in factor.source for token in forbidden):
                offenders.append(f"{container}.{key} -> {factor.source!r}")
        self.assertEqual(
            offenders,
            [],
            "A fertilizer factor is citing EPA's fuel combustion tables, which carry no "
            "fertilizer manufacturing factors:\n  " + "\n  ".join(offenders),
        )

    def test_only_a_published_factor_may_wear_an_allowlisted_citation(self):
        """Closes the obvious way around this file.

        `test_a_published_factor_cites_a_source_someone_has_opened` only inspects factors marked
        PUBLISHED, so the cheap dodge is to keep the citation and downgrade the label: set
        `provenance=PROVENANCE_INTERNAL_ESTIMATE` and leave
        `source="EPA eGRID2023 Summary Tables rev.2 (...)"` in place. Nothing would have caught
        it, and `source` is not private — it is emitted verbatim as `data_sources` in the carbon
        API payloads, so the string is what a reader sees.

        This is deliberately narrow. Roughly half the registry is INTERNAL_ESTIMATE with a source
        that names an agency but no document ("USDA NRCS Irrigation Energy Guidelines"), and the
        module docstring already calls that out and accepts it: the provenance FIELD carries the
        honesty there. What is not acceptable is an internal estimate wearing one of the exact
        strings this file certifies as a full publication claim.
        """
        offenders = [
            f"{container}.{key} -> {factor.provenance} with {factor.source!r}"
            for (container, key), factor in sorted(_all_factors().items())
            if factor.source in CITABLE_SOURCES and factor.provenance != PROVENANCE_PUBLISHED
        ]
        self.assertEqual(
            offenders,
            [],
            "A factor carries a citation from CITABLE_SOURCES while declaring it is not "
            "published. Either it is published and should say so, or the citation is not its "
            "source and should be reworded:\n  " + "\n  ".join(offenders),
        )

    def test_unverified_factors_are_all_registered_with_a_reason(self):
        unverified = {key for key, factor in _all_factors().items() if factor.provenance == PROVENANCE_UNVERIFIED}
        unregistered = sorted(f"{c}.{k}" for c, k in unverified - set(UNVERIFIED_REGISTER))
        self.assertEqual(
            unregistered,
            [],
            "A factor is marked UNVERIFIED without saying why. Add it to UNVERIFIED_REGISTER "
            "with the reason, or give it a real source:\n  " + "\n  ".join(unregistered),
        )

        stale = sorted(f"{c}.{k}" for c, k in set(UNVERIFIED_REGISTER) - unverified)
        self.assertEqual(
            stale,
            [],
            "UNVERIFIED_REGISTER names factors that are no longer unverified (or no longer "
            "exist). If one was re-sourced, delete its entry here in the same change:\n  " + "\n  ".join(stale),
        )

        for entry, reason in UNVERIFIED_REGISTER.items():
            with self.subTest(factor=entry):
                self.assertGreater(len(reason.strip()), 40, "the reason must be a sentence, not a shrug")

    def test_an_unverified_factor_never_reports_itself_as_published(self):
        for (container, key), factor in sorted(_all_factors().items()):
            if factor.provenance != PROVENANCE_UNVERIFIED:
                continue
            with self.subTest(factor=f"{container}.{key}"):
                self.assertFalse(
                    factor.is_published,
                    "is_published is what surfaces read to decide whether to show a citation",
                )

    def test_provenance_is_one_of_the_three_states(self):
        allowed = {PROVENANCE_PUBLISHED, PROVENANCE_INTERNAL_ESTIMATE, PROVENANCE_UNVERIFIED}
        for (container, key), factor in sorted(_all_factors().items()):
            with self.subTest(factor=f"{container}.{key}"):
                self.assertIn(factor.provenance, allowed)

    def test_the_us_electricity_factor_matches_its_published_derivation(self):
        """Arithmetic, done here, because nobody did it for the value this replaced.

        eGRID2023 Summary Tables rev.2, U.S. row: 770.9 lb CO2e/MWh, grid gross loss 4.2%.
        The predecessor (0.39) was EPA's Equivalencies Calculator figure — eGRID2022 data and a
        5.12% loss rate — carried under a citation naming eGRID2023, which does not produce it.
        """
        lb_to_kg = 0.45359237
        expected = (770.9 * lb_to_kg / 1000) / (1 - 0.042)

        factor = _all_factors()[("EPA_ELECTRICITY_FACTORS", "electricity_us_avg")]
        self.assertAlmostEqual(factor.value, expected, places=3)
        self.assertAlmostEqual(factor.value, 0.365, places=3)

        # The country entry and the irrigation-pump entry are the same grid, so they must not
        # drift from it — the factor was declared in four separate places before this.
        # (`EQUIPMENT_CONSUMPTION.irrigation_pump` is a different thing entirely: 3.5 kWh per
        # 1000 gallons, a consumption rate, not an emission factor.)
        self.assertEqual(_all_factors()[("COUNTRY_ELECTRICITY_FACTORS", "US")].value, factor.value)
        self.assertEqual(_all_factors()[("PRODUCTION_FACTORS", "irrigation_pump")].value, factor.value)

    def test_every_kwh_grid_factor_in_the_registry_is_the_same_number(self):
        """The electricity factor was declared four times and corrected once. Catch the next one.

        Any factor whose unit is per-kWh and whose source is the eGRID citation must carry the
        eGRID value. A copy that gets missed during an update is exactly how 0.39 survived in
        `carbon/views.py` as a bare `ELECTRICITY_FACTOR = 0.39` while the registry moved.
        """
        egrid_source = "EPA eGRID2023 Summary Tables rev.2 (U.S. 770.9 lb CO2e/MWh, 4.2% grid gross loss)"
        values = {
            f"{container}.{key}": factor.value
            for (container, key), factor in _all_factors().items()
            if factor.source == egrid_source
        }
        self.assertGreaterEqual(len(values), 3, "expected the US grid factor in at least three places")
        self.assertEqual(
            set(values.values()),
            {0.365},
            f"US grid factor copies disagree: {values}",
        )
