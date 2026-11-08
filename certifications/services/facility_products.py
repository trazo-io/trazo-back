"""The product rows of a facility, as the module PDF prints them (CCOF G6.1 C2, OTCO C7 7.10-2).

CCOF asks, per finished product: category, detail, packaging form and the certified operation where it
is handled or processed, plus the manufacturer's ingredient statement for each multi-ingredient product.
OTCO asks: type, detail, organic label claim, label or brand name, the operation doing the processing and
its certifier. The facility line above the table carries the operation and its certifier; each row here
carries the rest, in the operator's words. A blank column prints "Not stated", never a default.
"""

NOT_STATED = "Not stated"

HEADER = ("Product", "Packaging form", "Organic label claim", "Label or brand", "Ingredients")
WIDTHS = (2.0, 1.0, 1.3, 1.3, 1.0)

MISSING_STATEMENT = "[REVIEW] Multi-ingredient product with no manufacturer's ingredient statement on file in Trazo."


def ingredient_statement_source(product) -> str:
    """One key per stored file: a statement named on two products ships once."""
    return f"doc:{product.ingredient_statement_document_id}"


def ingredient_statement_label(product) -> str:
    return f"Ingredient statement for {product.category} ({product.facility.name})"


def ingredient_statement_path(product) -> str:
    from certifications.services.packet_attachments import _ext, safe_title

    doc = product.ingredient_statement_document
    facility = product.facility
    return (
        f"handlers/{facility.pk}-{safe_title(facility.name, 'handler')}-ingredients-"
        f"{safe_title(product.category, 'product')}-{product.pk}{_ext(doc.file.name)}"
    )


def products_of(facility) -> list:
    """The facility's rows, in the order they were entered. Reads the prefetch when there is one."""
    return list(facility.products.all())


def product_cells(product) -> list:
    """The table's columns for one row, each a list of lines."""
    name = [product.category] + ([product.detail] if product.detail else [])
    ingredients = {"yes": "Multi-ingredient", "no": "Single ingredient"}.get(product.multi_ingredient, NOT_STATED)
    return [
        name,
        [product.get_packaging_form_display() if product.packaging_form else NOT_STATED],
        [product.get_label_claim_display() if product.label_claim else NOT_STATED],
        [product.brand_name or NOT_STATED],
        [ingredients],
    ]


def product_notes(product, manifest) -> list:
    """The lines under a row: where a multi-ingredient product's ingredient statement is, or that it is not."""
    from certifications.services.packet_attachments import state_words

    if product.multi_ingredient != "yes":
        return []
    if not product.ingredient_statement_document_id:
        return [MISSING_STATEMENT]
    entries = manifest.for_source(ingredient_statement_source(product)) if manifest else []
    if entries:
        return [state_words(entries[0])]
    return ["Ingredient statement: a copy is held in Trazo; it is not included in this document."]
