"""
G3.0b — Perennial Planting Stock.

Sources: 7 CFR 205.204(a)(1) and (a)(4) (seeds and planting stock practice standard),
205.105 (excluded methods), 205.103 (recordkeeping). Federal Common OSP Crop & Wild Crop,
Section 4 "Seeds, Seedlings, and Planting Stock" — question 6 is the one every orchard and
vineyard answers, and it was previously a free-text stub here.

The distinction this module has to keep straight, because operators routinely conflate them:

  * § 205.204(a)(4) governs selling the PLANTING STOCK ITSELF as organic — nonorganic stock
    must be maintained under organic management for at least one year first.
  * The CROP harvested from that stock is governed by the land requirement (§ 205.202, 36
    months free of prohibited substances), not by this rule.

An almond grower who plants nonorganic nursery trees on compliant land can sell the nuts as
organic; they cannot sell the trees as organic until a year of organic management has passed.
Getting this backwards in either direction is a finding, so the questions and the coaching
text separate the two explicitly.

G3.0 already asks whether organic or nonorganic planting stock is used at all, and covers seed
GMO and treatment verification. This module deliberately does not repeat those — it deepens the
perennial-specific establishment record: what was planted, where it came from, and the
one-year clock.

Question keys `planting_stock_description` and `planting_stock_upload` are carried over from the
stub this replaces so any answer already stored against them still resolves.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text

G3_2_PLANTING_STOCK = Module(
    key="g3_2_planting_stock",
    # G3.0b — a Trazo display code. The real Common OSP G3.2 is Mushroom Production.
    code="G3.0b",
    title=text("Perennial Planting Stock", "Material de plantación perenne"),
    nop_cites=("§ 205.204(a)(1)", "§ 205.204(a)(4)", "§ 205.105", "§ 205.103"),
    education=(
        text(
            "Organic planting stock must be used when it is commercially available. "
            "Nonorganic perennial planting stock may be used when an organic equivalent "
            "cannot be sourced in the variety, rootstock, quantity, or quality you need — "
            "but you must be able to show the search you did before buying it "
            "(§ 205.204(a)(1)).",
            "Debe usarse material de plantación orgánico cuando esté comercialmente disponible. Puede usarse "
            "material de plantación perenne no orgánico cuando no se consiga un equivalente orgánico en la "
            "variedad, portainjerto, cantidad o calidad que necesitas — pero debes poder demostrar la búsqueda que "
            "hiciste antes de comprarlo (§ 205.204(a)(1)).",
        ),
        text(
            "Two different clocks apply, and they are often confused. Selling the PLANTING "
            "STOCK itself as organic requires at least one year of organic management first "
            "(§ 205.204(a)(4)). Selling the CROP those plants produce as organic depends on "
            "the land requirement instead — 36 months free of prohibited substances "
            "(§ 205.202). Trees bought nonorganic and planted on compliant land can bear an "
            "organic crop; the trees themselves are not organic stock until the year has "
            "passed.",
            "Aplican dos plazos distintos, y con frecuencia se confunden. Vender el MATERIAL "
            "DE PLANTACIÓN como orgánico requiere primero al menos un año de manejo orgánico "
            "(§ 205.204(a)(4)). Vender como orgánico el CULTIVO que producen esas plantas "
            "depende en cambio del requisito de la tierra — 36 meses libre de sustancias "
            "prohibidas (§ 205.202). Los árboles comprados como no orgánicos y plantados en "
            "tierra conforme pueden dar un cultivo orgánico; los árboles mismos no son "
            "material orgánico hasta que pase el año.",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — no perennial planting stock has been established or replaced " "during this plan period.",
        "No aplica — no se ha establecido ni reemplazado material de plantación perenne "
        "durante este período del plan.",
    ),
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_establishment",
            title=text("A. What was planted", "A. Qué se plantó"),
            education=(
                text(
                    "Include new blocks, interplants, and replacement trees or vines. "
                    "Replants into an existing organic block still count as planting stock "
                    "entering your operation.",
                    "Incluye bloques nuevos, plantas intercaladas y árboles o vides de reemplazo. Los replantes en "
                    "un bloque orgánico existente también cuentan como material de plantación que entra a tu "
                    "operación.",
                ),
            ),
            questions=(
                Question(
                    key="stock_types_established",
                    kind="checkbox_group",
                    label=text(
                        "What forms of perennial planting stock has your operation established?",
                        "¿Qué formas de material de plantación perenne ha establecido tu operación?",
                    ),
                    nop_cite="§ 205.204",
                    compiles_to=CompileRule(template="Perennial planting stock established: {answer}."),
                    options=(
                        Option("bare_root", text("Bare-root trees or vines", "Árboles o vides a raíz desnuda")),
                        Option(
                            "containerized",
                            text("Containerized trees or vines", "Árboles o vides en contenedor"),
                        ),
                        Option("rootstock", text("Rootstock for grafting", "Portainjertos para injertar")),
                        Option(
                            "cuttings_scions",
                            text("Cuttings, whips, or scions", "Estacas, varetas o púas de injerto"),
                        ),
                        Option(
                            "crowns_divisions",
                            text("Crowns, sets, or divisions", "Coronas, bulbos o divisiones"),
                        ),
                    ),
                ),
                Question(
                    key="stock_organic_status",
                    kind="radio",
                    label=text(
                        "What is the organic status of the planting stock you established?",
                        "¿Cuál es el estado orgánico del material de plantación que estableció?",
                    ),
                    nop_cite="§ 205.204(a)",
                    compiles_to=CompileRule(template="Organic status of planting stock established: {answer}."),
                    options=(
                        Option(
                            "all_organic",
                            text("All certified organic", "Todo certificado orgánico"),
                        ),
                        Option(
                            "mixed",
                            text(
                                "Some certified organic, some nonorganic",
                                "Parte certificado orgánico, parte no orgánico",
                            ),
                        ),
                        Option("all_nonorganic", text("All nonorganic", "Todo no orgánico")),
                    ),
                ),
                Question(
                    key="planting_stock_description",
                    kind="textarea",
                    label=text(
                        "Where did the stock come from, and where and when was it planted?",
                        "¿De dónde vino el material, y dónde y cuándo se plantó?",
                    ),
                    coaching=text(
                        "Name the nursery or supplier for each lot, the species, variety and "
                        "rootstock, the parcel or block it went into, and the planting date. "
                        "An inspector traces a tree in the field back to an invoice through "
                        "exactly these details.",
                        "Nombra el vivero o proveedor de cada lote, la especie, variedad y portainjerto, la parcela "
                        "o bloque donde se plantó, y la fecha de plantación. Un inspector rastrea un árbol en el "
                        "campo hasta una factura precisamente con estos datos.",
                    ),
                    nop_cite="§ 205.103",
                    compiles_to=CompileRule(template="Planting stock sources and planting record: {answer}"),
                ),
                Question(
                    key="suppliers_on_supplier_list",
                    kind="boolean",
                    label=text(
                        "Are all planting stock suppliers entered on your Supplier List?",
                        "¿Todos los proveedores de material de plantación están en tu Lista de Proveedores?",
                    ),
                    coaching=text(
                        "The Common OSP requires every supplier of seeds, seedlings, and "
                        "planting stock on the Supplier List attachment, with the certifier "
                        "named for certified suppliers.",
                        "El Common OSP requiere que todo proveedor de semillas, plántulas y "
                        "material de plantación esté en el adjunto Lista de Proveedores, con el "
                        "certificador nombrado para los proveedores certificados.",
                    ),
                    nop_cite="§ 205.103",
                    compiles_to=CompileRule(template="Planting stock suppliers listed on the Supplier List: {answer}."),
                ),
                Question(
                    # WSDA AGR 2121 C1; OTCO C3 3.1-5 (contract) and 3.2-2 (farm-grown stock).
                    key="stock_source",
                    kind="checkbox_group",
                    label=text(
                        "Where does your planting stock come from?",
                        "¿De dónde proviene tu material de plantación?",
                    ),
                    required=False,
                    nop_cite="§ 205.204",
                    compiles_to=CompileRule(template="Planting stock sources: {answer}."),
                    options=(
                        Option("nursery", text("A nursery", "Un vivero")),
                        Option(
                            "produce_own",
                            text(
                                "We propagate our own (cuttings, scion wood, divisions)",
                                "La propagamos nosotros (estacas, púas, divisiones)",
                            ),
                        ),
                        Option(
                            "contract_provided",
                            text(
                                "Another operation produces it for us under contract",
                                "Otra operación la produce para nosotros bajo contrato",
                            ),
                        ),
                        Option("other", text("Other", "Otra")),
                    ),
                ),
                Question(
                    # OTCO C3 3.1-5a.
                    key="contract_stock_input_documentation",
                    kind="boolean",
                    label=text(
                        "Do you collect documentation that the contracted planting stock was produced with "
                        "inputs allowed in organic production?",
                        "¿Reúnes documentación de que el material de plantación contratado se produjo con insumos "
                        "permitidos en la producción orgánica?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    visible_when=(Condition("stock_source", "includes", "contract_provided"),),
                    compiles_to=CompileRule(
                        template="Documentation collected that contracted planting stock was produced with allowed "
                        "inputs: {answer}."
                    ),
                ),
                Question(
                    # WSDA AGR 2121 C2a (the verification half; the records half is §D).
                    key="organic_stock_verification_method",
                    kind="textarea",
                    label=text(
                        "How do you verify that the organic planting stock you buy is certified organic?",
                        "¿Cómo verificas que el material de plantación orgánico que compras está certificado?",
                    ),
                    coaching=text(
                        "For example: the nursery's organic certificate checked in the USDA Organic Integrity "
                        "Database before the order ships, and the invoice naming the stock as certified organic.",
                        "Por ejemplo: el certificado orgánico del vivero revisado en la base de datos USDA Organic "
                        "Integrity antes del envío, y la factura que nombra el material como orgánico certificado.",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    visible_when=(Condition("stock_organic_status", "one_of", ["all_organic", "mixed"]),),
                    compiles_to=CompileRule(template="How certified organic planting stock is verified: {answer}"),
                ),
                Question(
                    # WSDA AGR 2121 C2b: treatment disclosure for ORGANIC stock (§B asks it of nonorganic stock).
                    key="organic_stock_treatments",
                    kind="radio",
                    label=text(
                        "Was the organic planting stock treated with any substance before planting, by your farm, "
                        "the supplier or a third party?",
                        "¿El material de plantación orgánico recibió algún tratamiento antes de plantarse, por tu "
                        "finca, el proveedor o un tercero?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    visible_when=(Condition("stock_organic_status", "one_of", ["all_organic", "mixed"]),),
                    compiles_to=CompileRule(template="Treatment of organic planting stock before planting: {answer}."),
                    options=(
                        Option("none", text("No", "No")),
                        Option(
                            "treated_listed",
                            text(
                                "Yes — the treatment materials are on our OSP inputs list",
                                "Sí — los materiales del tratamiento están en nuestra lista de insumos del OSP",
                            ),
                        ),
                        Option(
                            "unknown",
                            text("Not yet confirmed with the supplier", "Todavía no confirmado con el proveedor"),
                        ),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_nonorganic_justification",
            title=text(
                "B. Using nonorganic stock",
                "B. Uso de material no orgánico",
            ),
            visible_when=(Condition("stock_organic_status", "one_of", ["mixed", "all_nonorganic"]),),
            education=(
                # CCOF G3.0 A3a(i): stock that arrives bearing flower buds (containerized blueberries,
                # strawberry plugs, raspberry canes) is often cropped the season it is planted.
                text(
                    "Some certifying agents ask how growth that was already on nonorganic "
                    "stock when it arrived is kept out of the first organic harvest. Stock delivered with flower "
                    "buds or fruit is the common case.",
                    "Algunos certificadores preguntan cómo se mantiene fuera de la primera "
                    "cosecha orgánica el crecimiento que el material no orgánico ya traía al llegar. El caso común "
                    "es el material entregado con botones florales o fruta.",
                ),
                text(
                    "Nonorganic planting stock is allowed only when an organic equivalent is "
                    "not commercially available. Commercial availability covers form, quality "
                    "and quantity — an organic rootstock that exists but cannot be supplied in "
                    "the quantity or timeframe your planting requires is not commercially "
                    "available to you, provided you can show the search.",
                    "El material de plantación no orgánico se permite solo cuando no hay un equivalente orgánico "
                    "comercialmente disponible. La disponibilidad comercial cubre forma, calidad y cantidad — un "
                    "portainjerto orgánico que existe pero no puede suministrarse en la cantidad o el plazo que tu "
                    "plantación requiere no está comercialmente disponible para ti, siempre que puedas demostrar la "
                    "búsqueda.",
                ),
            ),
            questions=(
                Question(
                    key="nonorganic_stock_justification",
                    kind="checkbox_group",
                    label=text(
                        "Why was organic planting stock not commercially available?",
                        "¿Por qué no estaba comercialmente disponible el material de plantación " "orgánico?",
                    ),
                    nop_cite="§ 205.204(a)(1)",
                    compiles_to=CompileRule(
                        template="Justification for nonorganic perennial planting stock: {answer}."
                    ),
                    options=(
                        Option(
                            "variety_unavailable",
                            text(
                                "The variety or cultivar is not offered organically",
                                "La variedad o cultivar no se ofrece de forma orgánica",
                            ),
                        ),
                        Option(
                            "rootstock_unavailable",
                            text(
                                "The required rootstock is not offered organically",
                                "El portainjerto requerido no se ofrece de forma orgánica",
                            ),
                        ),
                        Option(
                            "quantity",
                            text(
                                "Not available in the quantity needed",
                                "No disponible en la cantidad necesaria",
                            ),
                        ),
                        Option(
                            "timing",
                            text(
                                "Not available in time for the planting window",
                                "No disponible a tiempo para la ventana de plantación",
                            ),
                        ),
                        Option(
                            "certified_disease_free",
                            text(
                                "Certified disease-free or virus-tested stock was required",
                                "Se requería material certificado libre de enfermedades o " "virus-testado",
                            ),
                        ),
                        Option(
                            "quality",
                            text(
                                "Available organic stock did not meet quality or size grade",
                                "El material orgánico disponible no cumplía la calidad o el " "calibre",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="nonorganic_stock_justification_other",
                    kind="text",
                    label=text("Describe the other reason", "Describe la otra razón"),
                    visible_when=(Condition("nonorganic_stock_justification", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional justification: {answer}"),
                ),
                Question(
                    key="stock_search_records",
                    kind="checkbox_group",
                    label=text(
                        "What records show the search you did before buying nonorganic stock?",
                        "¿Qué registros demuestran la búsqueda que hiciste antes de comprar " "material no orgánico?",
                    ),
                    coaching=text(
                        "Certifiers generally expect contact with at least three sources. Keep "
                        "the supplier name, the date, and what they said — a quote showing the "
                        "organic option was unavailable is stronger than a note saying you "
                        "looked.",
                        "Los certificadores generalmente esperan contacto con al menos tres fuentes. Conserva el "
                        "nombre del proveedor, la fecha y lo que respondieron — una cotización que muestre que la "
                        "opción orgánica no estaba disponible es más sólida que una nota diciendo que buscaste.",
                    ),
                    nop_cite="§ 205.204(a)(1)",
                    compiles_to=CompileRule(template="Commercial availability search records kept: {answer}."),
                    options=(
                        Option(
                            "nursery_quotes",
                            text("Nursery quotes or order confirmations", "Cotizaciones o confirmaciones de vivero"),
                        ),
                        Option("emails", text("Emails with suppliers", "Correos con proveedores")),
                        Option(
                            "phone_log", text("Phone log of suppliers contacted", "Bitácora de llamadas a proveedores")
                        ),
                        Option(
                            "catalog_screenshots",
                            text(
                                "Catalog pages or website screenshots showing availability",
                                "Páginas de catálogo o capturas del sitio web que muestran la " "disponibilidad",
                            ),
                        ),
                        Option(
                            "certifier_form",
                            text(
                                "Certifier's commercial availability form",
                                "Formulario de disponibilidad comercial del certificador",
                            ),
                        ),
                        Option(
                            "none_yet",
                            text(
                                "No search records kept yet",
                                "Todavía no se conservan registros de búsqueda",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    # CCOF G3.0 A3a.
                    key="nonorganic_stock_for_organic_crop",
                    kind="radio",
                    label=text(
                        "Do you plant nonorganic stock to grow a crop you harvest and sell as organic?",
                        "¿Plantas material no orgánico para producir un cultivo que cosechas y vendes como "
                        "orgánico?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)(1)",
                    compiles_to=CompileRule(
                        template="Nonorganic planting stock used to produce a crop sold as organic: {answer}."
                    ),
                    options=(Option("no", text("No", "No")), Option("yes", text("Yes", "Sí"))),
                ),
                Question(
                    # CCOF G3.0 A3a(i).
                    key="first_organic_harvest_handling",
                    kind="checkbox_group",
                    label=text(
                        "How do you make sure the growth you harvest as organic grew under organic management?",
                        "¿Cómo te aseguras de que lo que cosechas como orgánico creció bajo manejo orgánico?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    visible_when=(Condition("nonorganic_stock_for_organic_crop", "eq", "yes"),),
                    compiles_to=CompileRule(
                        template="Handling of growth from nonorganic stock before the first organic harvest: {answer}."
                    ),
                    options=(
                        Option(
                            "no_first_season_harvest",
                            text(
                                "No crop is harvested for organic sale in the first season",
                                "No se cosecha para venta orgánica en la primera temporada",
                            ),
                        ),
                        Option(
                            "remove_nonorganic_growth",
                            text(
                                "Flowers, fruit or other growth present at planting are removed",
                                "Se retiran las flores, frutos u otro crecimiento presente al plantar",
                            ),
                        ),
                        Option(
                            "sell_first_harvest_nonorganic",
                            text(
                                "The first harvest is sold as nonorganic",
                                "La primera cosecha se vende como no orgánica",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="first_organic_harvest_handling_other",
                    kind="textarea",
                    label=text("Describe it", "Descríbelo"),
                    required=False,
                    visible_when=(Condition("first_organic_harvest_handling", "includes", "other"),),
                    compiles_to=CompileRule(template="Other handling before the first organic harvest: {answer}"),
                ),
                Question(
                    # WSDA AGR 2121 C3a; CCOF G3.0 B2 (stock side).
                    key="stock_search_method",
                    kind="checkbox_group",
                    label=text(
                        "How do you determine that equivalent organic planting stock is not available?",
                        "¿Cómo determinas que no hay material de plantación orgánico equivalente disponible?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)(1)",
                    compiles_to=CompileRule(template="How organic planting stock availability is searched: {answer}."),
                    options=(
                        Option(
                            "three_suppliers",
                            text(
                                "We check with at least three suppliers of certified organic planting or grafting "
                                "stock",
                                "Consultamos al menos a tres proveedores de material de plantación o de injerto "
                                "orgánico certificado",
                            ),
                        ),
                        Option(
                            "third_party_searches",
                            text(
                                "Another party searches for us (a nursery under contract, a broker) and checks at "
                                "least three suppliers",
                                "Otra parte busca por nosotros (un vivero bajo contrato, un corredor) y consulta al "
                                "menos a tres proveedores",
                            ),
                        ),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                Question(
                    key="stock_search_process",
                    kind="textarea",
                    label=text(
                        "Describe the search: which suppliers, when, and what they could not supply",
                        "Describe la búsqueda: qué proveedores, cuándo y qué no pudieron suministrar",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)(1)",
                    compiles_to=CompileRule(template="Search for organic planting stock: {answer}"),
                ),
                Question(
                    # CCOF G3.0 C1 (stock half); WSDA AGR 2121 C3b; OTCO C3 3.4-1. G3.0 §C asks it only of seed.
                    key="stock_gmo_documentation",
                    kind="checkbox_group",
                    label=text(
                        "How do you document that nonorganic planting stock is not genetically modified?",
                        "¿Cómo documentas que el material de plantación no orgánico no es genéticamente modificado?",
                    ),
                    required=False,
                    nop_cite="§ 205.105(e)",
                    compiles_to=CompileRule(
                        template="Non-GMO status of nonorganic planting stock documented via: {answer}."
                    ),
                    options=(
                        Option(
                            "not_available_as_gmo",
                            text(
                                "The variety or rootstock is not available in a genetically modified form",
                                "La variedad o el portainjerto no existe en forma genéticamente modificada",
                            ),
                        ),
                        Option(
                            "supplier_statement",
                            text("Non-GMO statement from the supplier", "Declaración no-OGM del proveedor"),
                        ),
                        Option("catalog", text("Catalog or label statement", "Declaración en catálogo o etiqueta")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                Question(
                    key="stock_treatments",
                    kind="radio",
                    label=text(
                        "Was the nonorganic stock treated with any substance before or at delivery?",
                        "¿El material no orgánico recibió algún tratamiento antes o al momento de " "la entrega?",
                    ),
                    coaching=text(
                        "Nursery stock is frequently shipped with a fungicide dip, wax, root "
                        "gel, or growth regulator. Ask the nursery in writing — "
                        '"none that I know of" is not a record.',
                        "El material de vivero se envía con frecuencia con un baño fungicida, cera, gel radicular o "
                        'regulador de crecimiento. Pregunta al vivero por escrito — "ninguno que yo sepa" no es '
                        "un registro.",
                    ),
                    nop_cite="§ 205.204(a)",
                    compiles_to=CompileRule(template="Treatment of nonorganic planting stock: {answer}."),
                    options=(
                        Option(
                            "none_confirmed",
                            text(
                                "No — confirmed in writing by the nursery",
                                "No — confirmado por escrito por el vivero",
                            ),
                        ),
                        Option(
                            "treated_listed",
                            text(
                                "Yes — the treatment materials are on our OSP inputs list",
                                "Sí — los materiales del tratamiento están en nuestra lista de " "insumos del OSP",
                            ),
                        ),
                        Option(
                            "unknown",
                            text(
                                "Not yet confirmed with the nursery",
                                "Todavía no confirmado con el vivero",
                            ),
                        ),
                    ),
                ),
                Question(
                    # WSDA AGR 2121 C3c: "by your farm, supplier, or a third party".
                    key="stock_treatment_applied_by",
                    kind="checkbox_group",
                    label=text("Who applied the treatment?", "¿Quién aplicó el tratamiento?"),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    visible_when=(Condition("stock_treatments", "eq", "treated_listed"),),
                    compiles_to=CompileRule(template="Treatment of nonorganic planting stock applied by: {answer}."),
                    options=(
                        Option("farm", text("This farm", "Esta finca")),
                        Option("supplier", text("The nursery or supplier", "El vivero o proveedor")),
                        Option("third_party", text("A third party", "Un tercero")),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="c_one_year_rule",
            title=text(
                "C. Selling planting stock as organic",
                "C. Venta de material de plantación como orgánico",
            ),
            education=(
                text(
                    "This page is only about selling the plants themselves. If you sell only "
                    "the crop — nuts, fruit, or grapes — and never sell trees, vines, "
                    "rootstock, or cuttings, answer that you do not sell planting stock and "
                    "the one-year rule does not apply to you.",
                    "Esta página trata únicamente de vender las plantas mismas. Si vendes solo el cultivo — nueces, "
                    "fruta o uvas — y nunca vendes árboles, vides, portainjertos o estacas, responde que no vendes "
                    "material de plantación y la regla de un año no te aplica.",
                ),
            ),
            questions=(
                Question(
                    key="stock_sold_as_organic",
                    kind="radio",
                    label=text(
                        "Does your operation sell, or plan to sell, perennial planting stock as " "organic?",
                        "¿Tu operación vende, o planea vender, material de plantación perenne como orgánico?",
                    ),
                    nop_cite="§ 205.204(a)(4)",
                    compiles_to=CompileRule(template="Perennial planting stock sold as organic: {answer}."),
                    options=(
                        Option(
                            "not_sold",
                            text(
                                "No — we sell only the harvested crop, never the plants",
                                "No — vendemos solo el cultivo cosechado, nunca las plantas",
                            ),
                        ),
                        Option(
                            "sold_organic_stock",
                            text(
                                "Yes — planting stock is sold or represented as organic",
                                "Sí — el material de plantación se vende o se representa como " "orgánico",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="organic_management_start_date",
                    kind="date",
                    label=text(
                        "When did organic management of that planting stock begin?",
                        "¿Cuándo comenzó el manejo orgánico de ese material de plantación?",
                    ),
                    coaching=text(
                        "The stock must be under continuous organic management for at least 12 "
                        "months from this date before it may be sold or labeled as organic.",
                        "El material debe estar bajo manejo orgánico continuo por al menos 12 "
                        "meses desde esta fecha antes de poder venderse o etiquetarse como "
                        "orgánico.",
                    ),
                    nop_cite="§ 205.204(a)(4)",
                    visible_when=(Condition("stock_sold_as_organic", "eq", "sold_organic_stock"),),
                    compiles_to=CompileRule(
                        template="Organic management of planting stock sold as organic began: {answer}."
                    ),
                ),
                Question(
                    key="twelve_month_attestation",
                    kind="boolean",
                    label=text(
                        "Do you confirm that no planting stock is sold or labeled as organic "
                        "until it has been under organic management for at least 12 months?",
                        "¿Confirmas que ningún material de plantación se vende ni se etiqueta como orgánico hasta "
                        "haber estado bajo manejo orgánico por al menos 12 meses?",
                    ),
                    nop_cite="§ 205.204(a)(4)",
                    visible_when=(Condition("stock_sold_as_organic", "eq", "sold_organic_stock"),),
                    compiles_to=CompileRule(
                        template="Operator confirms the § 205.204(a)(4) 12-month management "
                        "period before planting stock is sold as organic: {answer}."
                    ),
                ),
                Question(
                    # WSDA AGR 2121 C4a (records half).
                    key="twelve_month_records_description",
                    kind="textarea",
                    label=text(
                        "Which records show the 12 months of organic management?",
                        "¿Qué registros muestran los 12 meses de manejo orgánico?",
                    ),
                    required=False,
                    nop_cite="§ 205.103",
                    visible_when=(Condition("stock_sold_as_organic", "eq", "sold_organic_stock"),),
                    compiles_to=CompileRule(template="Records of the 12-month organic management period: {answer}"),
                ),
                Question(
                    # WSDA AGR 2121 C4b.
                    key="resold_stock_labeling_description",
                    kind="textarea",
                    label=text(
                        "How is the planting stock you sell labeled or represented as organic?",
                        "¿Cómo se etiqueta o se presenta como orgánico el material de plantación que vendes?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)(4)",
                    visible_when=(Condition("stock_sold_as_organic", "eq", "sold_organic_stock"),),
                    compiles_to=CompileRule(
                        template="How planting stock sold as organic is labeled or represented: {answer}"
                    ),
                ),
            ),
        ),
        ModulePage(
            key="d_records",
            title=text("D. Records", "D. Registros"),
            questions=(
                Question(
                    key="stock_records_kept",
                    kind="checkbox_group",
                    label=text(
                        "Which planting stock records do you keep on file?",
                        "¿Qué registros de material de plantación conservas en archivo?",
                    ),
                    nop_cite="§ 205.103",
                    compiles_to=CompileRule(template="Planting stock records kept: {answer}."),
                    options=(
                        Option("invoices", text("Nursery invoices or receipts", "Facturas o recibos de vivero")),
                        Option(
                            "organic_certificates",
                            text(
                                "Organic certificates for certified suppliers",
                                "Certificados orgánicos de proveedores certificados",
                            ),
                        ),
                        Option(
                            "variety_tags",
                            text(
                                "Variety and rootstock tags or labels",
                                "Etiquetas de variedad y portainjerto",
                            ),
                        ),
                        Option(
                            "phytosanitary",
                            text(
                                "Phytosanitary or nursery inspection certificates",
                                "Certificados fitosanitarios o de inspección de vivero",
                            ),
                        ),
                        Option(
                            "planting_map",
                            text(
                                "Planting map showing which block each lot went into",
                                "Mapa de plantación que muestra en qué bloque entró cada lote",
                            ),
                        ),
                        Option(
                            "treatment_statements",
                            text(
                                "Written nursery statements about treatments applied",
                                "Declaraciones escritas del vivero sobre tratamientos aplicados",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="planting_stock_upload",
                    kind="upload",
                    label=text(
                        "Attach invoices, supplier certificates, or commercial availability " "search records",
                        "Adjunta facturas, certificados de proveedor o registros de búsqueda de disponibilidad "
                        "comercial",
                    ),
                    required=False,
                ),
                Question(
                    # WSDA AGR 2121 C5: "Optional space for additional information".
                    key="planting_stock_additional_notes",
                    kind="textarea",
                    label=text(
                        "Anything else about your planting stock the certifier should know",
                        "Cualquier otra cosa sobre tu material de plantación que el certificador deba saber",
                    ),
                    required=False,
                    compiles_to=CompileRule(template="Additional information on planting stock: {answer}"),
                ),
            ),
        ),
    ),
)
