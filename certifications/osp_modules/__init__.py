"""
Guided OSP module registry.

One entry per Common-OSP-style module. The registry is served to the frontend by the
`module-definitions` viewset action and consumed by the completion validator (WS-2.2), the
narrative compiler (WS-2.3), and the per-module PDF renderer (WS-2.6) — one source of truth.

CONTENT_VERSION stamps every saved module response (`definition_version`) so a certifier can
always know which questionnaire text an answer was given against. Bump it on ANY content
change to a shipped module — question wording changes silently reinterpreting old answers is
the failure mode this guards against.

Module keys are permanent identifiers (stored in module_responses); never rename one.
"""

from certifications.models import OSP_SECTION_KEYS

from .g3_0_seeds import G3_0_SEEDS
from .g4_0_rotation_soil import G4_0_ROTATION_SOIL
from .g8_0_record_keeping import G8_0_RECORD_KEEPING
from .schema import Module, serialize_module, validate_module

CONTENT_VERSION = "2026.08.1"

# Wizard/list order follows the Common OSP grower taxonomy. Pilot scope (WS-2.1):
# the three modules with the strongest existing evidence bindings. The remaining
# crop/wild-crop modules land in WS-2.7 — teardown §7 documents their section maps.
MODULE_REGISTRY: tuple = (
    G3_0_SEEDS,
    G4_0_ROTATION_SOIL,
    G8_0_RECORD_KEEPING,
)

MODULES_BY_KEY = {m.key: m for m in MODULE_REGISTRY}


def registry_errors() -> list:
    """Definition errors across the whole registry (test suite asserts this is empty)."""
    errors = []
    seen = set()
    for module in MODULE_REGISTRY:
        if module.key in seen:
            errors.append(f"duplicate module key '{module.key}'")
        seen.add(module.key)
        errors.extend(validate_module(module, OSP_SECTION_KEYS))
    return errors


def serialize_registry() -> dict:
    return {
        "content_version": CONTENT_VERSION,
        "modules": [serialize_module(m) for m in MODULE_REGISTRY],
    }


__all__ = [
    "CONTENT_VERSION",
    "MODULE_REGISTRY",
    "MODULES_BY_KEY",
    "Module",
    "registry_errors",
    "serialize_registry",
]
