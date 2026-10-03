"""Names worth reviewing together (OSP alignment T18, Phase 5 slice 3).

Deterministic candidates, computed on read and never stored. A suggestion is a prompt for the operator
to look, nothing more: it records no decision, clears no drift finding, changes no workbook row and
claims no identity, classification or approval. Only an operator decision (`material_identity`) can
say two names are one product.

Three kinds, each from data Trazo already holds:

* ``shared_brand``: the logged name and a product on the plan start with the same distinctive word
  ("Neptune's Harvest Fish Fertilizer 2-3-1" and "Neptune's Harvest Organic Fish Fertilizer 2-4-1"),
  the plan product's name read after any leading words of its own manufacturer ("Serenade Opti" and
  "Bayer Serenade Opti ...", Bayer CropScience), or with the logged name's first two words appearing
  together after a leading brand word ("Surround WP" in "NovaSource Surround WP ..."). Two products of
  one maker never pair on the maker's name alone.
  A generic first word ("Organic", "Liquid", "Copper") pairs nothing: two products sharing only a
  generic word are not paired. Different numbers are reported, never resolved.
* ``plan_answer_names``: for sanitizers, a plan answer about handling or sanitation names a catalog
  product other than the one logged ("Tsunami 100" in G6.4, "SaniDate 5.0" on the records). When
  that product's catalog subtype is a substance the plan approves, the substance is named too.
* ``suggested_substance_on_plan``: a logged chemical whose slice 1 National List suggestion (a
  partial-name hit, never a classification) points at a substance the plan approves.
"""

from __future__ import annotations

import re

from certifications.services.material_identity import formulation_differs, name_key

#: First words that say what a product is, not whose it is. Pairing on them would pair unrelated
#: products ("Organic Fish Emulsion" with "Organic Neem Oil").
GENERIC_LEADS = frozenset(
    """
    organic natural pure liquid dry super premium bio biological plant garden plus ultra pro the
    a an all fish kelp seaweed neem copper sulfur sulphur lime potassium calcium magnesium iron zinc
    nitrogen phosphate potash compost manure humic fulvic oil soap acid hydrogen peracetic
    peroxyacetic chlorine sodium insecticidal horticultural mineral rock blood bone feather
    gypsum dolomite sul
    purpose raised bed grade solution potting mix soil fertilizer fertilizers fertilizante concentrate
    powder granular granulated pellet pellets formula blend food insect
    """.split()
)

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _lead(name) -> str:
    words = _WORD.findall((name or "").lower().replace("’", "'"))
    return words[0] if words else ""


def _distinctive(word) -> bool:
    return len(word) >= 3 and not word.isdigit() and word not in GENERIC_LEADS


def _words(name) -> list:
    return _WORD.findall((name or "").lower().replace("\u2019", "'"))


def _product_lead(target) -> tuple:
    """(first distinctive word of the product's own name, whether a maker's prefix was set aside).

    A catalog name often starts with its maker ("Bayer Serenade Opti ...", "NovaSource Surround WP
    ..."). Leading words that are part of the catalog's own manufacturer field are set aside, so the
    product name is compared, not the maker (run 6, R6-02). Two products of one maker are therefore
    never paired on the maker's name."""
    words = _words(target["name"])
    maker = set(_words(target.get("manufacturer", "")))
    skipped = 0
    while skipped < len(words) - 1 and words[skipped] in maker:
        skipped += 1
    return (words[skipped] if words else ""), skipped > 0


def _phrase_after_prefix(logged_words, target_words) -> bool:
    """The logged name's first two words, the first distinctive, appear together later in the plan
    product's name: "Surround WP ..." in "NovaSource Surround WP ...", where the catalog's manufacturer
    field ("Tessenderlo Kerley Inc.") does not carry the brand prefix (run 6, R6-02)."""
    if len(logged_words) < 2 or not _distinctive(logged_words[0]):
        return False
    first, second = logged_words[0], logged_words[1]
    return any(target_words[k] == first and target_words[k + 1] == second for k in range(1, len(target_words) - 1))


def _strip_maker(words, maker) -> list:
    """`words` without the leading ones that are part of the maker's name."""
    k = 0
    while k < len(words) - 1 and words[k] in maker:
        k += 1
    return words[k:]


def _phrase_after_shared_maker(logged_words, target) -> bool:
    """Both names start with the plan product's maker: "Down To Earth Feather Meal" and "Down to Earth
    All Natural Fertilizers Feather Meal" (run 6b, R6b-01).

    The maker is set aside on both, then the words both names still share at the start (a product
    line: "Plant Health", "All Natural"), so a shared line never pairs two products of it (review of
    back #107; a sweep of the OMRI list found "Acadian Plant Health Alga-Plex" paired with "... SEAROOT").
    What remains of the logged name must then start with a two-word phrase found in what remains of the
    plan name, not both words generic. A logged name that is the whole start of the plan name (a form or
    size suffix, "... Frass 3-3-2" and "... Frass 3-3-2 Powder") also pairs."""
    maker = set(_words(target.get("manufacturer", "")))
    if not maker:
        return False
    logged_rest = _strip_maker(logged_words, maker)
    target_rest = _strip_maker(_words(target["name"]), maker)
    if len(logged_rest) == len(logged_words):
        return False
    common = 0
    while common < min(len(logged_rest), len(target_rest)) and logged_rest[common] == target_rest[common]:
        common += 1
    if common == len(logged_rest):
        # The whole logged name starts the plan name (a form or size suffix), but not when what is left
        # after the maker is only generic words: "<Maker> All Natural" names no product (re-review of
        # back #107).
        return common >= 2 and any(w not in GENERIC_LEADS and not w.isdigit() for w in logged_rest)
    rest, target_tail = logged_rest[common:], target_rest[common:]
    if len(rest) < 2 or len(rest[0]) < 3 or rest[0].isdigit() or rest[1].isdigit():
        return False
    if rest[0] in GENERIC_LEADS and rest[1] in GENERIC_LEADS:
        return False
    return any(target_tail[k] == rest[0] and target_tail[k + 1] == rest[1] for k in range(len(target_tail) - 1))


def shared_brand(logged_name, targets) -> list:
    lead = _lead(logged_name)
    if not _distinctive(lead):
        return []
    key = name_key(logged_name)
    logged_words = _words(logged_name)
    out = []
    for target in targets:
        if name_key(target["name"]) == key:
            continue
        product_lead, after_maker = _product_lead(target)
        if product_lead == lead:
            after_prefix = after_maker
        elif _phrase_after_prefix(logged_words, _words(target["name"])) or _phrase_after_shared_maker(
            logged_words, target
        ):
            after_prefix = True
        else:
            continue
        out.append(
            {
                "kind": "shared_brand",
                "target": target,
                "numbers_differ": formulation_differs(logged_name, target["name"]),
                #: Matched on the product's name after a leading maker or brand word in the plan's name
                #: ("Serenade Opti" in "Bayer Serenade Opti ...").
                "after_prefix": after_prefix,
            }
        )
    return out


# Where a plan states which sanitizer it uses: the handling and post-harvest modules (G6.x), and any
# question whose key says sanitizer.
def _sanitation_answer(module_key, question_key) -> bool:
    return module_key.startswith("g6") or "sanitiz" in question_key


def _answer_texts(osp):
    modules = ((getattr(osp, "module_responses", None) or {}).get("modules")) or {}
    for module_key, module in modules.items():
        for question_key, answer in ((module or {}).get("answers") or {}).items():
            value = answer.get("value") if isinstance(answer, dict) else answer
            if isinstance(value, str) and value.strip() and _sanitation_answer(module_key, question_key):
                yield module_key, question_key, value


def _catalog_names():
    """(name, catalog, id, subtype) for every catalog product whose name is specific enough to find in
    prose: a digit or two words, at least six characters."""
    from certifications.models import OMRIProduct, WSDAMaterial

    rows = [(w.brand_name, "wsda", w.pk, w.subtype or "") for w in WSDAMaterial.objects.only("brand_name", "subtype")]
    rows += [(o.product_name, "omri", o.pk, "") for o in OMRIProduct.objects.only("product_name")]
    out = []
    for name, catalog, pk, subtype in rows:
        clean = (name or "").strip()
        if len(clean) >= 6 and (any(c.isdigit() for c in clean) or len(clean.split()) >= 2):
            out.append((clean, catalog, pk, subtype))
    return out


def plan_answer_products(osp) -> list:
    """Catalog products named, by their whole name, in the plan's handling and sanitation answers."""
    texts = list(_answer_texts(osp))
    if not texts:
        return []
    lowered = [(m, q, t.lower()) for m, q, t in texts]
    found = []
    for name, catalog, pk, subtype in _catalog_names():
        needle = name.lower()
        for module_key, question_key, text in lowered:
            if needle not in text:
                continue
            if re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", text):
                found.append(
                    {
                        "module": module_key,
                        "question": question_key,
                        "product_name": name,
                        "catalog": catalog,
                        "catalog_id": pk,
                        "subtype": subtype,
                    }
                )
    return found


def _approved_substances(osp) -> dict:
    return {
        " ".join((s.substance_name or "").lower().split()): s.substance_name
        for s in osp.approved_national_list_substances.all()
    }


def plan_answer_names(logged_name, answer_products, approved) -> list:
    key = name_key(logged_name)
    out = []
    for product in answer_products:
        if name_key(product["product_name"]) == key:
            continue
        substance = approved.get(" ".join(product["subtype"].lower().split())) if product["subtype"] else None
        out.append({"kind": "plan_answer_names", **product, "approved_substance": substance or ""})
    return out


def suggested_substance_on_plan(events, approved_ids) -> list:
    """Slice 1 suggestions (partial-name hits) that point at a substance this plan approves."""
    seen = {}
    for event in events:
        suggestion = getattr(event, "national_list_suggestion", None)
        if suggestion is not None and suggestion.pk in approved_ids and suggestion.pk not in seen:
            seen[suggestion.pk] = {
                "kind": "suggested_substance_on_plan",
                "substance_id": suggestion.pk,
                "substance_name": suggestion.substance_name,
            }
    return list(seen.values())


class Suggester:
    """Per-plan caches, so a page of identities reads the catalogs once."""

    def __init__(self, osp, targets):
        self.osp = osp
        self.targets = targets
        self._answers = None
        self.approved = _approved_substances(osp)
        self.approved_ids = set(osp.approved_national_list_substances.values_list("pk", flat=True))

    def for_identity(self, source, logged_name, events) -> list:
        out = shared_brand(logged_name, self.targets)
        if source == "sanitizer":
            if self._answers is None:
                self._answers = plan_answer_products(self.osp)
            out += plan_answer_names(logged_name, self._answers, self.approved)
        if source == "chemical":
            out += suggested_substance_on_plan(events, self.approved_ids)
        return out
