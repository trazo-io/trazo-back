"""Canonical US state resolution.

Before this module every state-keyed lookup rolled its own normalization, and
three of them fell back to `"CA"` when the answer was unknown — so a Florida
farm with `state="Florida"` (not `"FL"`) was silently costed with California
irrigation depth, California precipitation and California USDA benchmarks, and
the audit trail then recorded `regional_adjustments_applied=True` for it.

Two rules follow from that, and both are load-bearing:

1. **Unknown resolves to `None`, never to a state.** A missing state means
   "use national defaults and say so", not "assume the biggest customer's
   state". A wrong-but-confident number on a document a grower is judged by is
   worse than an honest national one.
2. **Matching is strict — exact 2-letter code or exact full name.** No prefix
   or fuzzy matching: `"Baja California"` is not California, and a lookup that
   guesses reintroduces exactly the bug this module exists to remove. Legacy
   rows that fail to normalize are surfaced by
   `manage.py audit_state_values` for a human to fix, not guessed at here.

Territories are included because they file under USDA/EPA rules; the set is
kept in sync with `trazo-app/src/hooks/useMeasurementSystem.ts`.
"""

US_STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
    "PR": "Puerto Rico",
    "VI": "US Virgin Islands",
    "GU": "Guam",
    "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}

US_STATE_ABBREVS = {name.lower(): code for code, name in US_STATE_NAMES.items()}

# For admin/serializer ChoiceField use. Deliberately NOT attached to the model
# fields — see USStateFieldMixin in common.validators for why.
US_STATE_CHOICES = sorted(US_STATE_NAMES.items(), key=lambda pair: pair[1])


def normalize_state(value):
    """Return the canonical 2-letter code for `value`, or None if unresolvable.

    Accepts a code in any case with surrounding whitespace ("ca", " CA ") or an
    exact full name ("California", "california"). Everything else — including
    blank, None, and near-misses like "Calif" or "Baja California" — returns
    None so the caller falls back to national defaults instead of guessing.
    """
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    upper = text.upper()
    if upper in US_STATE_NAMES:
        return upper

    return US_STATE_ABBREVS.get(text.lower())


def resolve_establishment_state(establishment):
    """Return an establishment's canonical state code, or None."""
    if establishment is None:
        return None
    return normalize_state(getattr(establishment, "state", None))


def resolve_event_state(event):
    """Walk event → history → parcel → establishment for a state code.

    Best-effort by design: returns None on any missing link rather than
    raising. Callers use the state to pick regional factors or to gate a
    state-specific surface, and in both cases "unknown" is a safe answer while
    an exception mid-calculation is not.
    """
    if event is None:
        return None
    try:
        establishment = event.history.parcel.establishment
    except AttributeError:
        return None
    return resolve_establishment_state(establishment)


def event_is_in_state(event, code):
    """True when `event`'s farm resolves to state `code` (e.g. "CA")."""
    return resolve_event_state(event) == normalize_state(code)
