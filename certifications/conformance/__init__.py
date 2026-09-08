"""Clause-level conformance mapping for the binding organic regulations.

See `binding_clauses.py` for what this is and, more importantly, what it is not.
"""

from .binding_clauses import (  # noqa: F401
    BINDING_CLAUSES,
    CORPUS_CFR_PATH,
    CORPUS_HANDBOOK_DIR,
    IN_SCOPE_SECTIONS,
    OUT_OF_SCOPE_SECTIONS,
    Disposition,
    clause_by_id,
    clauses_for_section,
)
