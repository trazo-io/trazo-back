"""The certifying agents a grower can pick, spelled the way the Organic Integrity Database spells them.

WHY THIS MODULE EXISTS
----------------------
🔴 2026-09-10, WSDA desk read. The operation's certifying agent was typed as free text in two
places (the farm profile's certification row and the plan's activation gate) and matched against
an alias table that knew three agents. A first-year applicant had nowhere to state an agent at
all. Anything the table did not know, "OCI" for Organic Certifiers or a typo of "Oregon Tilth",
silently produced a packet numbered to CCOF's forms. On the October send list that was 62% of
the operations: OCI alone is 152 of 791 send rows, second only to WSDA.

A picker cannot fix that by itself, since Trazo still carries only three agents' form numbering.
What it fixes is the other half: the agent is stated once, spelled one way, and the grower is told
before submitting whether the packet will be numbered to their agent's forms.

The list and the resolver are the same data, so the picker cannot offer a spelling that resolves
to nothing, and a register folder cannot exist without an entry here
(`test_certifying_agent_picker.py`).

SOURCE
------
`name` is the Organic Integrity Database spelling, taken from the certifier column of
`documentation/gtm-v3/named-list-2026-09-v4.csv` (an Integrity DB snapshot): every agent on that
list, plus CCOF, which the list excludes by design. 2026-09-11: plus the six US-based agents the
2026-08-01 snapshot shows certifying US operations that the send list happened not to reach (Where
Food Comes From 1,394 · NOFA-NY 892 · Natural Food Certifiers 502 · Idaho 229 · Americert 130 ·
Perry Johnson 34). Foreign agents certifying a handful of US operations are left to "Other". It is what gets stored and printed, so a
reviewer reads their own agency's name as the USDA spells it. An agent that is not here is still
accepted as typed text ("Other"). It resolves to no slug, and the packet says so.

⛔ Matching is exact after normalisation, never fuzzy. A near-miss that reads "Organic Certifiers"
as some other agent would renumber a whole packet for the wrong reviewer. Short names are listed
only where they are unambiguous: "ODA" is Oregon's and Oklahoma's, "CDA" is Colorado's, and
"MDA" is three states, so none of them is an alias.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CertifyingAgent:
    #: Stable key. For an agent with a form register it IS the register folder
    #: (`documentation/compliance/certifiers/<slug>/`); a test holds the two together.
    slug: str
    #: Organic Integrity Database spelling. Stored, printed and offered in the picker.
    name: str
    #: What growers call it, shown beside the name only where the name does not already say it.
    short_name: str = ""
    #: Other spellings that mean this agent and nothing else (certificates, letterheads).
    aliases: tuple[str, ...] = ()
    #: The renewal date(s) the agent sets, as "MM-DD", from its own published pages. One date is every
    #: operation's; several means the agent assigns one per operation, which the operation records
    #: (`Establishment.certifier_renewal_date`). Empty where Trazo has not read it.
    renewal_dates: tuple[str, ...] = ()


AGENTS: tuple[CertifyingAgent, ...] = (
    # Renewal: "complete and submit this contract AND pay your invoice by January 1"
    # (ccof.org/payments; ccof.org/news/ccof-annual-certification-renewal-2027, read 2026-11-04).
    CertifyingAgent(
        "ccof",
        "CCOF Certification Services, LLC",
        "CCOF",
        ("ccof certification services", "california certified organic farmers"),
        ("01-01",),
    ),
    CertifyingAgent(
        "wsda",
        "Washington State Department of Agriculture",
        "WSDA",
        (
            "wsda organic program",
            "washington state dept of agriculture",
            "washington department of agriculture",
            "washington state department of agriculture organic program",
        ),
        # "renew your application by March 1 each year" (agr.wa.gov new-applicant-info; WAC
        # 16-157-251, read 2026-11-04).
        ("03-01",),
    ),
    # Certificates read "Oregon Tilth Certified Organic (OTCO)"; growers say "Oregon Tilth".
    # "you will be assigned a January 1st (most common) or April 1st renewal date, regardless of the
    # issue date listed on your certificate" (Fee Schedule rev. 2026/01/01, Renewal date assignment).
    CertifyingAgent(
        "otco",
        "Oregon Tilth Certified Organic",
        "OTCO",
        ("oregon tilth", "oregon tilth inc", "oregon tilth certified organic otco"),
        ("01-01", "04-01"),
    ),
    CertifyingAgent("oci", "Organic Certifiers, Inc.", "OCI"),
    CertifyingAgent("mofga", "MOFGA Certification Services, LLC - MCS", "", ("mofga certification services",)),
    CertifyingAgent("qcs", "Quality Certification Services", "QCS"),
    CertifyingAgent("pco", "Pennsylvania Certified Organic", "PCO"),
    CertifyingAgent("baystate", "Baystate Organic Certifiers"),
    CertifyingAgent("primus", "Primus Auditing Operations"),
    CertifyingAgent("oregon_da", "Oregon Department of Agriculture"),
    CertifyingAgent("oeffa", "Ohio Ecological Food and Farm Association", "OEFFA"),
    CertifyingAgent("colorado_da", "Colorado Department of Agriculture"),
    CertifyingAgent("qima", "QIMA (formerly IBD Certifications)", "", ("qima", "ibd certifications")),
    CertifyingAgent("mosa", "Midwest Organic Services Association, Inc.", "MOSA"),
    CertifyingAgent("onmark", "OnMark Certification Services"),
    CertifyingAgent("qai", "Quality Assurance International", "QAI"),
    CertifyingAgent("goa", "Global Organic Alliance, Inc", "", ("global organic alliance",)),
    CertifyingAgent("maryland_da", "Maryland Department of Agriculture"),
    CertifyingAgent("vof", "Vermont Organic Farmers, LLC", "VOF"),
    CertifyingAgent("ocia", "Organic Crop Improvement Association", "OCIA"),
    CertifyingAgent("texas_da", "Texas Department of Agriculture"),
    CertifyingAgent("iowa_da", "Iowa Department of Agriculture and Land Stewardship"),
    CertifyingAgent("kentucky_da", "Kentucky Department of Agriculture"),
    CertifyingAgent("mcco", "Monterey County Certified Organics", "MCCO"),
    CertifyingAgent("onecert", "OneCert, Inc."),
    CertifyingAgent("clemson", "Clemson University"),
    CertifyingAgent("moca", "Marin Organic Certified Agriculture", "MOCA"),
    CertifyingAgent("ecocert", "Ecocert SAS (formerly Ecocert SA)", "", ("ecocert",)),
    CertifyingAgent("nics", "Nature’s International Certification Services", "NICS"),
    CertifyingAgent("scs", "SCS Global Services, Inc."),
    CertifyingAgent("georgia_cia", "Georgia Crop Improvement Association"),
    CertifyingAgent("procert", "Pro-Cert Organic Systems, Ltd."),
    CertifyingAgent("utah_da", "Utah Department of Agriculture and Food"),
    CertifyingAgent("mcia", "Minnesota Crop Improvement Association"),
    CertifyingAgent("montana_da", "Montana Department of Agriculture"),
    CertifyingAgent("oklahoma_da", "Oklahoma Department of Agriculture, Food and Forestry"),
    CertifyingAgent("wfcf", "Where Food Comes From Organic", "WFCF"),
    CertifyingAgent("nofany", "NOFA-NY Certified Organic, LLC", "", ("nofa ny", "nofa ny certified organic")),
    CertifyingAgent("nfc", "Natural Food Certifiers", "NFC"),
    CertifyingAgent("idaho_da", "Idaho State Department of Agriculture"),
    CertifyingAgent("americert", "Americert International"),
    CertifyingAgent("pjr", "Perry Johnson Registrars Food Safety, Inc."),
)


def normalize_agent_name(name) -> str:
    """Lowercase, drop punctuation (apostrophes vanish, other marks become spaces), collapse spaces.

    Nothing cleverer. "Nature’s" and "Natures" must meet, and so must "Inc." and "Inc".
    """
    text = re.sub(r"['’]", "", str(name or "").lower())
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _index() -> dict[str, CertifyingAgent]:
    index: dict[str, CertifyingAgent] = {}
    for agent in AGENTS:
        for spelling in (agent.name, agent.short_name, *agent.aliases):
            key = normalize_agent_name(spelling)
            if key:
                index[key] = agent
    return index


_BY_SPELLING = _index()


def agent_for_name(name) -> CertifyingAgent | None:
    """The agent a typed or stored name means, or None. Exact after normalisation, never fuzzy."""
    return _BY_SPELLING.get(normalize_agent_name(name))


def agent_by_slug(slug) -> CertifyingAgent | None:
    """The agent with this slug, or None."""
    return next((agent for agent in AGENTS if agent.slug == slug), None)
