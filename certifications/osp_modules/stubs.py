"""
N/A-able stub modules (WS-2.7, plan #25).

Each ships the full shell — title, citations, education, N/A attestation, and a
minimal describe-or-attach page — so the module list is complete for every
operation and an operation that DOES have the activity records it now instead
of hitting a wall. Depth (checkbox batteries, branching) arrives when pilot
operations actually need these topics.

G6.4 Handling (below) has already graduated to full depth — see the comment
above its definition. The rest remain describe-and-attach stubs.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Prefill, Question, text


def _describe_and_attach(prefix: str, describe_label, upload_label) -> tuple:
    return (
        Question(
            key=f"{prefix}_description",
            kind="textarea",
            label=describe_label,
            required=False,
        ),
        Question(
            key=f"{prefix}_upload",
            kind="upload",
            label=upload_label,
            required=False,
        ),
    )


G3_1_SEEDLINGS = Module(
    key="g3_1_seedlings",
    # G3.0a, not G3.1: in the published Common OSP, G3.1 is Container & Greenhouse
    # and G3.2 is Mushroom Production. Seedlings and planting stock are subtopics of
    # G3.0 Seeds & Planting Stock, so these two modules display as G3.0a/G3.0b.
    # Keys are storage identifiers and deliberately unchanged — module_responses
    # entries are keyed by `key`, never by display code.
    code="G3.0a",
    title=text("Annual Seedlings", "Plántulas anuales"),
    # (a)(3), not (a)(2): (a)(2) is TREATED seed and planting stock; nonorganic annual seedlings
    # are allowed only under a temporary variance, which is (a)(3) — as the education text below
    # already said (eCFR, 2026-09-11).
    nop_cites=("§ 205.204(a)(3)",),
    education=(
        text(
            "Annual seedlings must be organically produced. A nonorganic annual seedling "
            "may only be used with a temporary variance granted after a declared natural "
            "disaster — commercial unavailability is not an allowance for seedlings.",
            "Las plántulas anuales deben producirse orgánicamente. Una plántula anual no "
            "orgánica solo puede usarse con una variación temporal tras un desastre "
            "natural declarado — la no disponibilidad comercial no es una excepción para "
            "plántulas.",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — no purchased or produced annual seedlings are used.",
        "No aplica — no se usan plántulas anuales compradas ni producidas.",
    ),
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_seedlings",
            title=text("A. Seedling sources", "A. Origen de las plántulas"),
            questions=(
                Question(
                    # CCOF G3.0 A2, OTCO C3 3.1-2 and WSDA 2121-B 1/1a ask for the organic
                    # certificate of EACH supplier of purchased seedlings. The panel is read from the
                    # transplant records and the supplier register, never typed here, and the packet
                    # carries the copy it names under suppliers/.
                    key="seedling_suppliers_panel",
                    kind="info",
                    embed="seedling_suppliers",
                    required=False,
                    label=text(
                        "Suppliers named on your transplant purchases",
                        "Proveedores indicados en tus compras de trasplantes",
                    ),
                    coaching=text(
                        "Listed from your transplant records. Add each supplier and a copy of its "
                        "organic certificate in the supplier register on your farm profile; the plan "
                        "shows whether the copy on file covers your latest purchase.",
                        "Se listan a partir de tus registros de trasplante. Agrega cada proveedor y una "
                        "copia de su certificado orgánico en el registro de proveedores del perfil de tu "
                        "finca; el plan muestra si la copia guardada cubre tu última compra.",
                    ),
                ),
            )
            + _describe_and_attach(
                "seedlings",
                text(
                    "Describe where annual seedlings come from (own greenhouse, certified "
                    "supplier) and how their organic status is documented.",
                    "Describe de dónde provienen las plántulas anuales (invernadero propio, proveedor certificado) "
                    "y cómo se documenta su estado orgánico.",
                ),
                # Not the supplier certificates any more (2026.11.06): those are filed per supplier in
                # the register and shown by the panel above, tied to the purchases they cover. A
                # certificate attached here is tied to no supplier, so the old label sent growers to
                # the one place the coverage page cannot credit.
                text(
                    "Other seedling documents, if you keep any (for example a purchase agreement). Each "
                    "supplier's certificate copy goes in the supplier register, so the panel above shows it.",
                    "Otros documentos de las plántulas, si los tienes (por ejemplo, un acuerdo de compra). La "
                    "copia del certificado de cada proveedor va en el registro de proveedores, para que el panel "
                    "de arriba la muestre.",
                ),
            )
            + (
                Question(
                    # WSDA AGR 2121 B2a: every area used to grow seedlings is visited at inspection.
                    key="seedlings_grown_on_site",
                    kind="radio",
                    label=text(
                        "If you produce your own seedlings, where are they grown?",
                        "Si produces tus propias plántulas, ¿dónde se cultivan?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    compiles_to=CompileRule(template="Seedlings produced by the operation are grown: {answer}."),
                    options=(
                        Option(
                            "on_site",
                            text(
                                "Within the boundary of our certified site",
                                "Dentro del límite de nuestro sitio certificado",
                            ),
                        ),
                        Option(
                            "off_site",
                            text(
                                "At another location (named below)",
                                "En otra ubicación (indicada abajo)",
                            ),
                        ),
                        Option("not_produced", text("We do not produce seedlings", "No producimos plántulas")),
                    ),
                ),
                Question(
                    # OTCO C3 3.2-1 "location of growing facility (must be certified organic)".
                    key="seedling_growing_location",
                    kind="textarea",
                    label=text(
                        "Where is each growing facility (greenhouse, nursery bed, propagation house)?",
                        "¿Dónde está cada instalación de cultivo (invernadero, cama de vivero, casa de "
                        "propagación)?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    visible_when=(Condition("seedlings_grown_on_site", "one_of", ["on_site", "off_site"]),),
                    compiles_to=CompileRule(template="Seedling growing facilities: {answer}"),
                ),
                Question(
                    key="seedling_facility_certified",
                    kind="boolean",
                    label=text(
                        "Is every facility where your seedlings are grown covered by an organic certificate?",
                        "¿Toda instalación donde se cultivan tus plántulas está cubierta por un certificado "
                        "orgánico?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    visible_when=(Condition("seedlings_grown_on_site", "one_of", ["on_site", "off_site"]),),
                    compiles_to=CompileRule(
                        template="Every seedling growing facility is covered by an organic certificate: {answer}."
                    ),
                ),
                Question(
                    # WSDA AGR 2121 B3.
                    key="seedlings_sold_as_organic",
                    kind="boolean",
                    label=text(
                        "Do you sell annual seedlings as organic?",
                        "¿Vendes plántulas anuales como orgánicas?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    compiles_to=CompileRule(template="Annual seedlings sold as organic: {answer}."),
                ),
                Question(
                    # WSDA AGR 2121 B3a.
                    key="seedlings_labeling_description",
                    kind="textarea",
                    label=text(
                        "How are the seedlings you sell labeled or represented as organic?",
                        "¿Cómo se etiquetan o se presentan como orgánicas las plántulas que vendes?",
                    ),
                    required=False,
                    nop_cite="§ 205.300",
                    visible_when=(Condition("seedlings_sold_as_organic", "truthy"),),
                    compiles_to=CompileRule(
                        template="How seedlings sold as organic are labeled or represented: {answer}"
                    ),
                ),
            ),
        ),
    ),
)


W2_0_WILD_CROP = Module(
    key="w2_0_wild_crop",
    code="W2.0",
    title=text("Wild Crop Harvesting", "Recolección de cultivos silvestres"),
    nop_cites=("§ 205.207",),
    education=(
        text(
            "Wild crops must come from a designated area that has had no prohibited "
            "substances applied for 36 months, and harvesting must not be destructive "
            "to the environment or the sustainability of the crop.",
            "Los cultivos silvestres deben provenir de un área designada sin sustancias "
            "prohibidas por 36 meses, y la recolección no debe ser destructiva para el "
            "ambiente ni para la sostenibilidad del cultivo.",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — no wild crops are harvested.",
        "No aplica — no se recolectan cultivos silvestres.",
    ),
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_wild",
            title=text("A. Wild harvest area", "A. Área de recolección silvestre"),
            questions=_describe_and_attach(
                "wild_crop",
                text(
                    "Describe the designated wild-harvest area, its 36-month history, and "
                    "how harvest sustainability is protected.",
                    "Describe el área designada de recolección silvestre, su historial de 36 meses y cómo se "
                    "protege la sostenibilidad de la cosecha.",
                ),
                text(
                    "Attach a map of the designated area and any landowner statements.",
                    "Adjunta un mapa del área designada y declaraciones del propietario si las hay.",
                ),
            ),
        ),
    ),
)


# G6.4 graduated from the thin describe-and-attach stub pattern above (WS-2.7) to
# full depth: pilot-readiness audit finding "G6.4 stub — needs applicability gate,
# site description, products handled, process flow." On-farm hulling/drying (nuts)
# and washing/packing (fruit) are "handling" under 7 CFR 205.270 / 205.272 even
# when the operator never receives another grower's product — this module collects
# that description for the OSP; it does not determine the operation's separate
# handler-certification status (§ 205.100(a) — see the module education below).
#
# Four pages: (A) an applicability gate, so an operation that ships everything
# field-run skips the rest of the module; (B) what is handled, for whom, and
# where; (C) the process flow plus the commingling / contact-prevention controls
# in place, including the narrower water-and-sanitizer case; (D) the records the
# operation actually keeps. Kept in this file rather than split into its own
# module file — fully self-contained below, a split is a pure file move later.
G6_4_HANDLING = Module(
    key="g6_4_handling",
    code="G6.4",
    title=text("On-Farm Handling", "Manejo en la finca"),
    nop_cites=("§ 205.270", "§ 205.272", "§ 205.103"),
    education=(
        text(
            "Washing, hulling, shelling, drying, sorting, grading, cooling, and packing your own "
            "crop are all handling activities under the organic regulations — not just a separate "
            "handler's job. Certification covers each operation OR PORTION of an operation that "
            "produces or handles (§ 205.100(a)), so handling your own crop is normally scoped "
            "inside your existing certification rather than certified as a separate handler "
            "operation — but that is your certifying agent's determination, not an exemption you "
            "can claim. Either way it does not remove the requirement to describe those on-farm "
            "handling steps in this system plan. Confirm your operation's certification scope "
            "with your certifying agent.",
            "Lavar, descascarar, pelar, secar, seleccionar, clasificar, enfriar y empacar tu propio cultivo son "
            "actividades de manejo bajo la normativa orgánica — no solo tarea de un manejador aparte. La "
            "certificación cubre cada operación O PARTE de una operación que produce o maneja (§ 205.100(a)), así "
            "que manejar tu propio cultivo normalmente queda dentro del alcance de tu certificación actual en lugar "
            "de certificarse como una operación de manejador aparte — pero eso lo determina tu agente certificador, "
            "no es una exención que puedas invocar. En cualquier caso, no elimina el requisito de describir esos "
            "pasos de manejo en la finca dentro de este plan de sistema. Confirma el alcance de la certificación de "
            "tu operación con tu agente certificador.",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — this operation performs no on-farm handling; everything is sold "
        "field-run, exactly as harvested.",
        "No aplica — esta operación no realiza manejo en la finca; todo se vende tal como se "
        "cosecha, directamente del campo.",
    ),
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_activities",
            title=text("A. Does your operation handle?", "A. ¿Tu operación realiza manejo?"),
            questions=(
                Question(
                    key="handling_activities",
                    kind="checkbox_group",
                    label=text(
                        "Which on-farm handling steps does your operation perform on this crop?",
                        "¿Qué pasos de manejo realiza tu operación en la finca para este cultivo?",
                    ),
                    coaching=text(
                        "Include every step performed on your own property, even a quick rinse, "
                        "hand-sort, or size grading — these all count as handling. If a packer or "
                        "processor off your property does this work instead, describe that "
                        "relationship in Sales & Supplier Verification (G6.5), not here.",
                        "Incluye cada paso realizado en tu propia finca, incluso un enjuague rápido, una selección "
                        "manual o una clasificación por tamaño — todos cuentan como manejo. Si un empacador o "
                        "procesador fuera de tu finca hace este trabajo en tu lugar, describe esa relación en "
                        "Ventas y Verificación de Proveedores (G6.5), no aquí.",
                    ),
                    nop_cite="§ 205.270",
                    compiles_to=CompileRule(template="On-farm handling activities performed: {answer}."),
                    options=(
                        Option("washing", text("Washing / rinsing", "Lavado / enjuague")),
                        Option("hulling_shelling", text("Hulling / shelling", "Descascarado / pelado")),
                        Option("drying", text("Drying / dehydrating", "Secado / deshidratado")),
                        Option(
                            "sorting_grading",
                            text("Sorting, grading, or sizing", "Selección, clasificación o calibrado"),
                        ),
                        Option(
                            "packing",
                            text(
                                "Packing into consumer or nonretail containers",
                                "Empacado en envases de consumidor o no minoristas",
                            ),
                        ),
                        Option("cooling", text("Cooling / hydrocooling", "Enfriado / hidroenfriado")),
                        # OTCO C7 7.3-1 (2026.11.30): the processing steps its list names that had no option. Cutting,
                        # cooking, mixing and fermenting are the steps OTCO and CCOF route toward handling
                        # certification, so they print by name rather than under "other".
                        Option("freezing", text("Freezing", "Congelado")),
                        Option("cutting", text("Cutting", "Cortado")),
                        Option("cooking", text("Cooking", "Cocción")),
                        Option("mixing", text("Mixing", "Mezclado")),
                        Option("fermenting", text("Fermenting", "Fermentado")),
                        Option("seed_cleaning", text("Seed cleaning", "Limpieza de semilla")),
                        Option(
                            "pest_treatment_nonfumigation",
                            text(
                                # Freezing is its own option since 2026.11.30; the example is dropped so it is not
                                # named twice (review of back #366).
                                "Fumigation-free pest treatment",
                                "Tratamiento de plagas sin fumigación",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                        Option(
                            "no_onfarm_handling",
                            text(
                                "None — product leaves the farm exactly as harvested (sold field-run)",
                                "Ninguno — el producto sale de la finca tal como se cosechó (venta directa del campo)",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="handling_activities_other",
                    kind="text",
                    label=text("Describe the other handling step", "Describe el otro paso de manejo"),
                    visible_when=(Condition("handling_activities", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional on-farm handling step: {answer}."),
                ),
                # CCOF G6.4's applicability gate ("does not apply if you are handling both organic and nonorganic
                # products, making multi-ingredient products, operating a multi-farm CSA, or performing complex
                # handling"), OTCO C7 7.3-2 (ingredients from off the farm) and 7.3-3 (non-organic product processed
                # at this facility), WSDA AGR 2121 L 3 (handling both certified and non-certified crops). Each one
                # ticked prints a [REVIEW]: it is a certification-scope fact the agent acts on (2026.11.30).
                Question(
                    key="simple_handling_disqualifiers",
                    kind="checkbox_group",
                    label=text(
                        "Does any of this apply to your on-farm handling? Check all that apply.",
                        "¿Algo de esto aplica a tu manejo en la finca? Marca todo lo que corresponda.",
                    ),
                    required=False,
                    nop_cite="§ 205.100(a)",
                    visible_when=(
                        Condition(
                            "handling_activities",
                            "includes_any",
                            [
                                "washing",
                                "hulling_shelling",
                                "drying",
                                "sorting_grading",
                                "packing",
                                "cooling",
                                "freezing",
                                "cutting",
                                "cooking",
                                "mixing",
                                "fermenting",
                                "seed_cleaning",
                                "pest_treatment_nonfumigation",
                                "other",
                            ],
                        ),
                    ),
                    compiles_to=CompileRule(template="On-farm handling scope: {answer}."),
                    options=(
                        Option(
                            "nonorganic_handled_here",
                            text(
                                "Non-organic product is also handled or processed at this facility",
                                "También se maneja o procesa producto no orgánico en esta instalación",
                            ),
                            review="Non-organic product is also handled at this facility; the certifying agent decides whether this needs a handling certification or the agent's handler forms.",
                        ),
                        Option(
                            "off_farm_ingredients",
                            text(
                                "Products made here contain ingredients from off the farm (other than salt)",
                                "Los productos hechos aquí contienen ingredientes de fuera de la finca (que no sean sal)",
                            ),
                            review="Products made here contain ingredients from off the farm; the certifying agent decides whether this needs a handling certification or the agent's handler forms.",
                        ),
                        Option(
                            "multi_ingredient_products",
                            text(
                                "Multi-ingredient products are made here",
                                "Aquí se hacen productos de varios ingredientes",
                            ),
                            review="Multi-ingredient products are made here; the certifying agent decides whether this needs a handling certification or the agent's handler forms.",
                        ),
                        Option(
                            "multi_farm_csa",
                            text(
                                "A multi-farm CSA is operated (other farms' product is distributed)",
                                "Se opera una CSA de varias fincas (se distribuye producto de otras fincas)",
                            ),
                            review="A multi-farm CSA is operated; the certifying agent decides whether this needs a handling certification or the agent's handler forms.",
                        ),
                        Option(
                            "complex_handling",
                            text(
                                "Complex handling such as baking, brewing or extracting",
                                "Manejo complejo como hornear, elaborar bebidas o extraer",
                            ),
                            review="Complex handling (baking, brewing, extracting) is done here; the certifying agent decides whether this needs a handling certification or the agent's handler forms.",
                        ),
                        Option(
                            "none",
                            text(
                                "None of these: only my own organic crop, in simple steps",
                                "Nada de esto: solo mi propio cultivo orgánico, en pasos simples",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_products_site",
            title=text("B. Products & site", "B. Productos y sitio"),
            visible_when=(
                Condition("handling_activities", "truthy"),
                Condition("handling_activities", "not_includes", "no_onfarm_handling"),
            ),
            questions=(
                Question(
                    key="products_handled",
                    kind="text",
                    label=text(
                        "Which crops and product forms are handled here?",
                        "¿Qué cultivos y formas de producto se manejan aquí?",
                    ),
                    placeholder=text(
                        "e.g., in-shell walnuts, hulled and dried",
                        "p. ej., nueces con cáscara, descascaradas y secas",
                    ),
                    nop_cite="§ 205.270",
                    compiles_to=CompileRule(template="Crops and product forms handled on-farm: {answer}."),
                ),
                # CCOF G6.4 A2: "list, or attach a list of" the products. A supplement to products_handled, never a
                # substitute: an upload answers no required question (2026.12.20).
                Question(
                    key="products_list_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "You can also attach your own list of the organic products handled here.",
                        "También puedes adjuntar tu propia lista de los productos orgánicos que se manejan aquí.",
                    ),
                ),
                # CCOF G6.4 A4: facility pest control materials are asked once, in G9.0; the PDF says where and how far
                # G9.0 is answered (2026.12.20).
                Question(
                    key="facility_pest_pointer",
                    kind="info",
                    required=False,
                    embed="facility_pest_pointer",
                    label=text(
                        "Materials used for facility pest control at this location are answered in Facility Pest "
                        "Management (G9.0) and listed on the materials list.",
                        "Los materiales usados para el control de plagas de instalaciones en este lugar se responden en "
                        "Manejo de plagas en instalaciones (G9.0) y se listan en la lista de materiales.",
                    ),
                ),
                Question(
                    key="own_products_only",
                    kind="radio",
                    label=text(
                        "Do you handle only your own crop, or also product from other growers?",
                        "¿Manejas únicamente tu propio cultivo, o también producto de otros productores?",
                    ),
                    coaching=text(
                        "Custom-handling means running someone else's certified organic crop "
                        "through your equipment for a fee — common where a walnut huller or "
                        "almond huller serves several neighboring orchards. It does not include "
                        "buying their crop outright once it is already harvested and sold to you.",
                        "Manejo por encargo significa procesar en tu equipo el cultivo orgánico certificado de otra "
                        "persona a cambio de un pago — común cuando un descascarador de nueces o almendras atiende "
                        "a varias huertas vecinas. No incluye comprarles el cultivo una vez que ya se lo vendieron "
                        "cosechado.",
                    ),
                    # § 205.100(a) — "each operation OR PORTION of an operation that produces or
                    # handles". This was § 205.101(b) until 2026-08-18; that clause is the RETAIL
                    # ESTABLISHMENT exemption and says nothing about handling your own crop, so it
                    # printed a wrong regulatory basis into a certifier-facing packet.
                    nop_cite="§ 205.100(a)",
                    compiles_to=CompileRule(template="On-farm handling covers: {answer}."),
                    options=(
                        Option("own", text("Only our own crop", "Únicamente nuestro propio cultivo")),
                        Option(
                            "also_neighbors_custom",
                            text(
                                "Also custom-handles product for other growers",
                                "También manejas por encargo producto de otros productores",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="custom_handling_separation",
                    kind="textarea",
                    label=text(
                        "Describe how another grower's product is kept separate from yours, and "
                        "what records you keep for their lots",
                        "Describe cómo se mantiene separado el producto de otro productor del tuyo, y qué registros "
                        "conservas para esos lotes",
                    ),
                    coaching=text(
                        "Custom-handling another operation's crop makes you a handler for their "
                        "product too — Strengthening Organic Enforcement expects the same lot "
                        "separation, labeling, and traceable records you keep for your own crop.",
                        "Manejar el cultivo de otra operación por encargo te convierte también en manejador de ese "
                        "producto — la normativa de Fortalecimiento de la Aplicación Orgánica espera la misma "
                        "separación de lotes, etiquetado y registros trazables que mantienes para tu propio "
                        "cultivo.",
                    ),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("own_products_only", "eq", "also_neighbors_custom"),),
                    compiles_to=CompileRule(
                        template=(
                            "Separation and records maintained for custom-handled product from "
                            "other growers: {answer}"
                        ),
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="handling_site",
                    kind="textarea",
                    label=text(
                        "Describe the buildings, pads, or equipment used for handling",
                        "Describe los edificios, plataformas o equipo usados para el manejo",
                    ),
                    coaching=text(
                        "Include every space product passes through — a wash pad, a hulling "
                        "shed, a drying yard, a cooler — and note whether the space or equipment "
                        "is shared with a nonorganic operation.",
                        "Incluye cada espacio por el que pasa el producto — una plataforma de lavado, un galpón de "
                        "descascarado, un patio de secado, una cámara fría — e indica si el espacio o equipo se "
                        "comparte con una operación no orgánica.",
                    ),
                    nop_cite="§ 205.270",
                    compiles_to=CompileRule(
                        template="Buildings, pads, and equipment used for on-farm handling: {answer}"
                    ),
                ),
                # CCOF G6.4 A1 "Site Name & Location (full address)", OTCO C7 7.1 (name, address, city,
                # state, zip, country) and 7.2-1 (a layout per facility): the operation's own facilities,
                # one record each, the same records G6.2 lists for storage.
                Question(
                    key="on_farm_facility_table",
                    kind="info",
                    required=False,
                    embed="on_farm_facilities",
                    label=text(
                        "Your own handling and storage facilities",
                        "Tus propias instalaciones de manejo y almacenamiento",
                    ),
                    coaching=text(
                        "Add each facility you run yourself (packing shed, cooler, dry storage) with its name and "
                        "full address, and attach a layout showing the areas used for organic handling and "
                        "storage. Your own certificate covers them, so no certificate is asked.",
                        "Agrega cada instalación que operas tú (galpón de empaque, cámara fría, almacén seco) con "
                        "su nombre y dirección completa, y adjunta un plano que muestre las áreas usadas para el "
                        "manejo y almacenamiento orgánico. Tu propio certificado las cubre, así que no se pide "
                        "certificado.",
                    ),
                    nop_cite="§ 205.270",
                ),
            ),
        ),
        ModulePage(
            key="c_process_integrity",
            title=text("C. Process & integrity", "C. Proceso e integridad"),
            education=(
                text(
                    "Physical separation — dedicated equipment, cleanout between runs, "
                    "single-product processing days — is the first line of defense against "
                    "commingling and prohibited-substance contact in a handling facility "
                    "(§ 205.272). When water contacts organic product for washing or cooling, any "
                    "sanitizer added to it must be one of the substances allowed for food-contact "
                    "sanitizing on the National List, used within its labeled limits (§ 205.605). "
                    "A cleaner or sanitizer wiped onto a dry surface counts the same way, and every "
                    "one belongs on your Materials Application.",
                    "La separación física — equipo dedicado, limpieza entre corridas, días de "
                    "procesamiento de un solo producto — es la primera línea de defensa contra la "
                    "mezcla y el contacto con sustancias prohibidas en una instalación de manejo "
                    "(§ 205.272). Cuando el agua entra en contacto con el producto orgánico para "
                    "lavado o enfriado, cualquier sanitizante que se le agregue debe ser una de las "
                    "sustancias permitidas para sanitización en contacto con alimentos de la Lista "
                    "Nacional, usada dentro de sus límites indicados en la etiqueta (§ 205.605). Un "
                    "limpiador o sanitizante aplicado con paño sobre una superficie seca cuenta igual, "
                    "y cada uno debe figurar en su Solicitud de Materiales.",
                ),
            ),
            visible_when=(
                Condition("handling_activities", "truthy"),
                Condition("handling_activities", "not_includes", "no_onfarm_handling"),
            ),
            questions=(
                Question(
                    key="process_flow",
                    kind="textarea",
                    label=text(
                        "Write out your handling process in order, from harvest to shipment",
                        "Escribe tu proceso de manejo en orden, desde la cosecha hasta el envío",
                    ),
                    coaching=text(
                        "List each step as it happens — for example: harvest → haul to hulling "
                        "shed → hull → dry → bulk storage → hand-sort → pack → cold storage → "
                        "ship. This step list is the flow chart your certifier expects to see for "
                        "the handling operation. If you keep a drawn flow chart instead, attach it under Records "
                        "and documents; either one answers the request.",
                        "Enumera cada paso en el orden en que ocurre — por ejemplo: cosecha → traslado al galpón de "
                        "descascarado → descascarado → secado → almacenamiento a granel → selección manual → "
                        "empacado → cámara fría → envío. Esta lista de pasos es el diagrama de flujo que tu "
                        "certificador espera ver para la operación de manejo. Si tienes un diagrama de flujo "
                        "dibujado, adjúntalo en Registros y documentos; cualquiera de los dos responde la solicitud.",
                    ),
                    nop_cite="§ 205.201(a)(1)",
                    compiles_to=CompileRule(
                        template="On-farm handling process, in order from harvest to shipment: {answer}"
                    ),
                ),
                # --- Cleaning and sanitation of food-contact surfaces ---------------------------
                # 2026-09-12. Until this version every sanitation question sat behind the WATER gate
                # (`uses_water`, itself visible only when handling_activities included washing or
                # cooling), so an operation that wipes a sorting table with a quaternary-ammonium
                # sanitizer and never wets the crop had nowhere to say so — CCOF G6.4 B1, WSDA
                # AGR 2121 §L 4-5b and OTCO C7 7.6 all ask it of every handler. Cleaning and
                # sanitizing are asked first and unconditionally; water follows as its own block.
                Question(
                    key="food_contact_cleaning_methods",
                    kind="checkbox_group",
                    label=text(
                        "How are food-contact surfaces and equipment cleaned before organic product touches them?",
                        "¿Cómo se limpian las superficies y el equipo en contacto con alimentos antes de que "
                        "el producto orgánico los toque?",
                    ),
                    coaching=text(
                        "Tick every method in use — dry methods count. A purge (running product through "
                        "to clear the line) needs the quantity and procedure written into your process "
                        "flow so a reviewer can judge it adequate.",
                        "Marca cada método en uso — los métodos en seco también cuentan. Una purga (pasar producto "
                        "para despejar la línea) necesita la cantidad y el procedimiento escritos en tu flujo de "
                        "proceso para que un revisor pueda juzgarla adecuada.",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="Food-contact surfaces are cleaned before organic handling by: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option("sweeping", text("Sweeping", "Barrido")),
                        Option("vacuuming", text("Vacuuming", "Aspirado")),
                        Option("compressed_air", text("Compressed air", "Aire comprimido")),
                        Option("scraping", text("Scraping", "Raspado")),
                        Option("purging", text("Purging (running product through)", "Purga (pasar producto)")),
                        Option("manual_washing", text("Manual washing", "Lavado manual")),
                        Option("soap_water", text("Soap and water", "Agua y jabón")),
                        Option("steam_cleaning", text("Steam cleaning", "Limpieza con vapor")),
                        Option("sanitizing", text("Sanitizing", "Sanitización")),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                        Option(
                            "none",
                            text(
                                "No cleaning step precedes organic handling",
                                "Ningún paso de limpieza precede al manejo orgánico",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="food_contact_cleaning_methods_other",
                    kind="text",
                    label=text("Describe the other cleaning method", "Describe el otro método de limpieza"),
                    visible_when=(Condition("food_contact_cleaning_methods", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Other food-contact cleaning method: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                # WSDA AGR 2121 L 4: "equipment purge amounts and procedures attached" (2026.12.20).
                Question(
                    key="purge_procedure_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach your equipment purge procedures, with how you set purge amounts for the equipment's "
                        "capacity.",
                        "Adjunta tus procedimientos de purga del equipo, con cómo defines las cantidades de purga según "
                        "la capacidad del equipo.",
                    ),
                    visible_when=(Condition("food_contact_cleaning_methods", "includes", "purging"),),
                    nop_cite="§ 205.272(a)",
                ),
                Question(
                    key="uses_equipment_sanitizer_or_cleaner",
                    kind="boolean",
                    label=text(
                        "Do you use any sanitizer, cleaner or detergent on surfaces or equipment that "
                        "contact organic product?",
                        "¿Usas algún sanitizante, limpiador o detergente en superficies o equipo que entran en "
                        "contacto con producto orgánico?",
                    ),
                    coaching=text(
                        "Includes a dry wipe-down of a sorting table or bin, not only wash-line "
                        "sanitizers. Every product you name here must also be on your Materials "
                        "Application — a sanitizer used on a food-contact surface is a handling "
                        "input under § 205.605.",
                        "Incluye pasar un paño a una mesa de selección o a un bin, no solo los sanitizantes de la "
                        "línea de lavado. Cada producto que nombres aquí debe estar también en tu Solicitud de "
                        "Materiales — un sanitizante usado en una superficie en contacto con alimentos es un insumo "
                        "de manejo bajo § 205.605.",
                    ),
                    nop_cite="§ 205.605",
                    compiles_to=CompileRule(
                        template=(
                            "Sanitizers, cleaners or detergents used on organic food-contact surfaces or "
                            "equipment: {answer}."
                        ),
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="equipment_sanitizer_types",
                    kind="checkbox_group",
                    label=text(
                        "Which types of sanitizer or cleaner are used?",
                        "¿Qué tipos de sanitizante o limpiador se usan?",
                    ),
                    coaching=text(
                        "The types are the ones CCOF's Materials Application §E lists. A detergent, "
                        "soap or cleaner must be rinsed off; a quaternary-ammonium sanitizer must be "
                        "rinsed AND tested to zero residue before organic product touches the surface.",
                        "Los tipos son los que enumera la Solicitud de Materiales §E de CCOF. Un "
                        "detergente, jabón o limpiador debe enjuagarse; un sanitizante de amonio "
                        "cuaternario debe enjuagarse Y probarse hasta residuo cero antes de que el "
                        "producto orgánico toque la superficie.",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("uses_equipment_sanitizer_or_cleaner", "truthy"),),
                    compiles_to=CompileRule(
                        template="Sanitizer and cleaner types used on food-contact surfaces: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "detergent_soap_cleaner",
                            text(
                                "Detergent, soap or cleaner (must be rinsed)",
                                "Detergente, jabón o limpiador (debe enjuagarse)",
                            ),
                        ),
                        Option(
                            "chlorine",
                            text(
                                "Chlorine — calcium hypochlorite, chlorine dioxide, sodium hypochlorite or hypochlorous acid",
                                "Cloro — hipoclorito de calcio, dióxido de cloro, hipoclorito de sodio o ácido hipocloroso",
                            ),
                        ),
                        Option(
                            "peracetic_acid", text("Peracetic / peroxyacetic acid", "Ácido peracético / peroxiacético")
                        ),
                        Option("phosphoric_acid", text("Phosphoric acid", "Ácido fosfórico")),
                        Option(
                            "alcohol",
                            text(
                                "Alcohol — ethanol or isopropanol (air-dry or rinse)",
                                "Alcohol — etanol o isopropanol (secar al aire o enjuagar)",
                            ),
                        ),
                        Option("citric_acid", text("Citric acid", "Ácido cítrico")),
                        Option("hydrogen_peroxide", text("Hydrogen peroxide", "Peróxido de hidrógeno")),
                        Option("ozone", text("Ozone", "Ozono")),
                        Option(
                            "quaternary_ammonium",
                            text(
                                "Quaternary ammonium sanitizer (must be rinsed and tested for zero residue)",
                                "Sanitizante de amonio cuaternario (debe enjuagarse y probarse hasta residuo cero)",
                            ),
                        ),
                        Option(
                            "other_unknown",
                            text("Other or unknown (describe below)", "Otro o desconocido (describe abajo)"),
                        ),
                    ),
                ),
                Question(
                    key="equipment_sanitizer_types_rinsed",
                    kind="checkbox_group",
                    label=text(
                        "Which of these are rinsed with potable water before organic product touches the surface?",
                        "¿Cuáles de estos se enjuagan con agua potable antes de que el producto orgánico toque la superficie?",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("uses_equipment_sanitizer_or_cleaner", "truthy"),),
                    compiles_to=CompileRule(
                        template=(
                            "Of these, rinsed with potable water before organic product contacts the surface: {answer}."
                        ),
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "detergent_soap_cleaner",
                            text("Detergent, soap or cleaner", "Detergente, jabón o limpiador"),
                        ),
                        Option("chlorine", text("Chlorine", "Cloro")),
                        Option(
                            "peracetic_acid", text("Peracetic / peroxyacetic acid", "Ácido peracético / peroxiacético")
                        ),
                        Option("phosphoric_acid", text("Phosphoric acid", "Ácido fosfórico")),
                        Option("alcohol", text("Alcohol", "Alcohol")),
                        Option("citric_acid", text("Citric acid", "Ácido cítrico")),
                        Option("hydrogen_peroxide", text("Hydrogen peroxide", "Peróxido de hidrógeno")),
                        Option("ozone", text("Ozone", "Ozono")),
                        Option(
                            "quaternary_ammonium",
                            text("Quaternary ammonium sanitizer", "Sanitizante de amonio cuaternario"),
                        ),
                        Option("other_unknown", text("Other or unknown", "Otro o desconocido")),
                        Option(
                            "none_rinsed",
                            text(
                                "None is rinsed — each is allowed to evaporate or air-dry completely",
                                "Ninguno se enjuaga — cada uno se deja evaporar o secar al aire por completo",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="equipment_sanitizer_where_used",
                    kind="textarea",
                    label=text(
                        "Name each product and where it is used",
                        "Nombra cada producto y dónde se usa",
                    ),
                    coaching=text(
                        "One line per product: brand, type, and the surface or equipment — for example "
                        '"SaniDate 5.0 (peracetic acid) — wash tank and brush bed", "Quat 128 — '
                        'sorting table, rinsed and strip-tested". This is the table CCOF §E and OTCO C7 '
                        "7.6 ask for.",
                        "Una línea por producto: marca, tipo y la superficie o equipo — por ejemplo "
                        '"SaniDate 5.0 (ácido peracético) — tanque de lavado y cama de cepillos", '
                        '"Quat 128 — mesa de selección, enjuagada y probada con tira". Esta es la tabla '
                        "que piden la §E de CCOF y la 7.6 del C7 de OTCO.",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("uses_equipment_sanitizer_or_cleaner", "truthy"),),
                    compiles_to=CompileRule(
                        template="Sanitizers and cleaners by product and where each is used: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="sanitizer_residual_free_assurance",
                    kind="checkbox_group",
                    label=text(
                        "How do you make sure organic food-contact surfaces are free of sanitizer or cleaner residue?",
                        "¿Cómo te aseguras de que las superficies orgánicas en contacto con alimentos queden libres "
                        "de residuo de sanitizante o limpiador?",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("uses_equipment_sanitizer_or_cleaner", "truthy"),),
                    compiles_to=CompileRule(
                        template="Food-contact surfaces are shown free of sanitizer or cleaner residue by: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "evaporated_completely",
                            text(
                                "Chlorine materials and sanitizers are allowed to evaporate completely",
                                "Los materiales de cloro y los sanitizantes se dejan evaporar por completo",
                            ),
                        ),
                        Option(
                            "thorough_rinse",
                            text("A thorough potable-water rinse", "Un enjuague completo con agua potable"),
                        ),
                        Option("double_rinse", text("A double rinse", "Un doble enjuague")),
                        Option(
                            "residue_testing",
                            text(
                                "Residue testing — pH strips, quaternary-ammonium strips, swabs or other (describe below)",
                                "Prueba de residuo — tiras de pH, tiras de amonio cuaternario, hisopos u otro "
                                "(describe abajo)",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="sanitizer_residual_free_assurance_other",
                    kind="text",
                    label=text("Describe the other residue safeguard", "Describe la otra salvaguarda contra residuos"),
                    visible_when=(Condition("sanitizer_residual_free_assurance", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Other residue safeguard: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="sanitizer_residual_testing_protocol",
                    kind="textarea",
                    label=text(
                        "Describe the residue test: test type and range, when it is run, and how the results are kept",
                        "Describe la prueba de residuo: tipo y rango de la prueba, cuándo se realiza y cómo se "
                        "guardan los resultados",
                    ),
                    coaching=text(
                        "WSDA and OTCO ask for the strip type and its range (for example quaternary-ammonium "
                        "strips, 0–500 ppm, target 0) and where the readings go.",
                        "WSDA y OTCO piden el tipo de tira y su rango (por ejemplo tiras de amonio cuaternario, "
                        "0–500 ppm, objetivo 0) y dónde quedan las lecturas.",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("sanitizer_residual_free_assurance", "includes", "residue_testing"),),
                    compiles_to=CompileRule(
                        template="Residual-sanitizer testing protocol (test type, range, how results are kept): {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                # --- Water --------------------------------------------------------------------
                Question(
                    key="uses_water",
                    kind="boolean",
                    label=text(
                        "Does water contact organic product or clean equipment at any step — washing, rinsing, "
                        "hydrocooling, flume transport?",
                        "¿El agua entra en contacto con el producto orgánico o se usa para limpiar equipo en algún "
                        "paso — lavado, enjuague, hidroenfriado, transporte por canal (flume)?",
                    ),
                    # § 205.272(a) — the duty to prevent CONTACT with prohibited substances. Was
                    # § 205.272(b) until 2026-08-18; (b) is a closed two-item list — (b)(1)
                    # packaging containing a synthetic fungicide/preservative/fumigant and
                    # (b)(2) reuse of a contaminated container — and mentions water nowhere.
                    #
                    # Asked of every handler since 2026-09-12 — it used to hide behind
                    # handling_activities ∋ washing/cooling, so a flume or an equipment rinse
                    # never reached the question (OTCO C7 7.5-1, WSDA §L 12).
                    nop_cite="§ 205.272(a)",
                    prefill=Prefill(source="post_harvest_water_evidence"),
                    compiles_to=CompileRule(
                        template=(
                            "Water contacts product or cleans equipment in handling (washing, rinsing, "
                            "hydrocooling, flume transport): {answer}."
                        )
                    ),
                ),
                Question(
                    key="post_harvest_water_uses",
                    kind="checkbox_group",
                    label=text("What is the water used for?", "¿Para qué se usa el agua?"),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("uses_water", "truthy"),),
                    compiles_to=CompileRule(
                        template="Water is used in post-harvest handling for: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option("equipment_cleaning", text("Cleaning equipment", "Limpieza de equipo")),
                        Option("crop_washing", text("Washing or rinsing crops", "Lavado o enjuague de cultivos")),
                        Option("cooling", text("Cooling / hydrocooling", "Enfriado / hidroenfriado")),
                        Option(
                            "product_transport",
                            text(
                                "Product transport (flume, fruit floating)",
                                "Transporte de producto (canal, flotación de fruta)",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="post_harvest_water_source",
                    kind="checkbox_group",
                    label=text("Where does the water come from?", "¿De dónde proviene el agua?"),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("uses_water", "truthy"),),
                    compiles_to=CompileRule(
                        template="Post-harvest water source: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option("municipal", text("Municipal supply", "Red municipal")),
                        Option("on_site_well", text("On-site well", "Pozo en el sitio")),
                        Option(
                            "other",
                            text(
                                "Other — surface water, hauled, etc. (describe below)",
                                "Otro — agua superficial, acarreada, etc. (describe abajo)",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="water_source_sanitizer",
                    kind="textarea",
                    label=text(
                        "Describe the water: its source, any treatment, and any sanitizer added to it",
                        "Describe el agua: su fuente, cualquier tratamiento y cualquier sanitizante que se le agregue",
                    ),
                    coaching=text(
                        "Name the source (well, municipal, pond) and, if a sanitizer is added, the "
                        "product name, concentration, and how residual levels are checked. Only "
                        "substances allowed for food-contact sanitizing on the National List may be "
                        "used, within their labeled limits (§ 205.605).",
                        "Indica la fuente (pozo, red municipal, estanque) y, si se agrega un sanitizante, el nombre "
                        "del producto, la concentración y cómo se verifican los niveles residuales. Solo pueden "
                        "usarse sustancias permitidas para sanitización en contacto con alimentos de la Lista "
                        "Nacional, dentro de sus límites indicados en la etiqueta (§ 205.605).",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("uses_water", "truthy"),),
                    compiles_to=CompileRule(
                        template="Water source and sanitizer used in handling: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                # CCOF G6.1 B3: "Do you wash crops in the field?" The water questions above ask whether and why water
                # touches the crop; this asks where it is washed (2026.11.28).
                Question(
                    key="crop_wash_location",
                    kind="checkbox_group",
                    label=text("Where are crops washed?", "¿Dónde se lavan los cultivos?"),
                    required=False,
                    nop_cite="§ 205.272",
                    visible_when=(Condition("post_harvest_water_uses", "includes", "crop_washing"),),
                    compiles_to=CompileRule(
                        template="Crops are washed: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option("in_field", text("In the field", "En el campo")),
                        Option(
                            "at_facility",
                            text("At a handling or packing facility", "En una instalación de manejo o empaque"),
                        ),
                    ),
                ),
                # OTCO C7 7.5-1b: how water that is not from a municipal source is shown to be safe to drink.
                Question(
                    key="post_harvest_water_potability",
                    kind="checkbox_group",
                    label=text(
                        "The water is not only from a municipal source. How do you make sure it is safe to drink "
                        "(potable)?",
                        "El agua no viene solo de la red municipal. ¿Cómo te aseguras de que sea apta para beber "
                        "(potable)?",
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                    visible_when=(
                        Condition("uses_water", "truthy"),
                        Condition("post_harvest_water_source", "includes_any", ["on_site_well", "other"]),
                    ),
                    compiles_to=CompileRule(
                        template="How non-municipal water is shown potable: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "household_drinking_water",
                            text(
                                "The well provides drinking water for the household",
                                "El pozo da el agua para beber de la casa",
                            ),
                        ),
                        Option(
                            "tested_regularly",
                            text(
                                "The water is tested regularly for contaminants", "El agua se analiza con regularidad"
                            ),
                        ),
                        Option(
                            "treated_sdwa",
                            text(
                                "The water is treated with an approved disinfectant following the Safe Drinking Water "
                                "Act",
                                "El agua se trata con un desinfectante aprobado según la Ley de Agua Potable Segura",
                            ),
                        ),
                        Option("other", text("Other", "Otro")),
                        Option(
                            "not_shown",
                            text("Not shown potable yet", "Todavía no se demuestra que sea potable"),
                            exclusive=True,
                            # Review of back #362: the gate is any handling water from a non-municipal source, which
                            # can be equipment rinse water only, so the line says no more than that.
                            review="Handling water from a non-municipal source is not shown to be potable.",
                        ),
                    ),
                ),
                Question(
                    key="post_harvest_water_treatment_materials",
                    kind="textarea",
                    label=text(
                        "List the materials used to treat the water.",
                        "Indica los materiales que se usan para tratar el agua.",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("post_harvest_water_potability", "includes", "treated_sdwa"),),
                    compiles_to=CompileRule(
                        template="Materials used to treat the water: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="post_harvest_water_potability_other",
                    kind="textarea",
                    label=text(
                        "Describe how else the water is shown potable.",
                        "Describe de qué otra forma se demuestra que el agua es potable.",
                    ),
                    visible_when=(Condition("post_harvest_water_potability", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Water shown potable, other: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                # OTCO C7 7.5-1c.
                Question(
                    key="post_harvest_water_positive_test",
                    kind="radio",
                    label=text(
                        "Has any water test come back positive for contaminants?",
                        "¿Algún análisis del agua salió positivo para contaminantes?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("post_harvest_water_potability", "includes", "tested_regularly"),),
                    compiles_to=CompileRule(template="A water test came back positive for contaminants: {answer}."),
                    options=(
                        Option("no", text("No", "No")),
                        Option(
                            "yes",
                            text("Yes", "Sí"),
                            review="A test of the handling water came back positive for contaminants.",
                        ),
                    ),
                ),
                Question(
                    key="post_harvest_water_positive_explanation",
                    kind="textarea",
                    label=text(
                        "Explain the result and what was done about it.",
                        "Explica el resultado y lo que se hizo al respecto.",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("post_harvest_water_positive_test", "eq", "yes"),),
                    compiles_to=CompileRule(template="Positive water test and response: {answer}"),
                ),
                Question(
                    key="post_harvest_water_test_results",
                    kind="upload",
                    label=text("Water test results", "Resultados de los análisis del agua"),
                    required=False,
                    nop_cite="§ 205.272",
                    visible_when=(Condition("post_harvest_water_potability", "includes", "tested_regularly"),),
                ),
                # WSDA AGR 2121 L 14, 14a, 14b and CCOF G6.1 B3a: water treated on site (UV, carbon filtration,
                # softening, pH adjustment, reverse osmosis), and whether it still meets the Safe Drinking Water Act.
                Question(
                    key="water_treated_onsite",
                    kind="boolean",
                    label=text(
                        "Is the water treated on site (e.g. UV, carbon filtration, reverse osmosis, water softeners, "
                        "pH adjustment)?",
                        "¿El agua se trata en el sitio (p. ej. UV, filtro de carbón, ósmosis inversa, suavizadores, "
                        "ajuste de pH)?",
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                    visible_when=(Condition("uses_water", "truthy"),),
                    compiles_to=CompileRule(
                        template="Water treated on site: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="treated_water_meets_sdwa",
                    kind="radio",
                    label=text(
                        "Does the treated water still meet the Safe Drinking Water Act standards?",
                        "¿El agua tratada sigue cumpliendo las normas de la Ley de Agua Potable Segura?",
                    ),
                    coaching=text(
                        "Ask the treatment manufacturer if you are unsure. Your certifier may ask for documentation.",
                        "Pregunta al fabricante del tratamiento si tienes dudas. Tu certificadora puede pedir "
                        "documentación.",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("water_treated_onsite", "truthy"),),
                    compiles_to=CompileRule(
                        template="Treated water meets the Safe Drinking Water Act standards: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option("yes", text("Yes", "Sí")),
                        Option(
                            "not_confirmed",
                            text("Not confirmed yet", "Todavía no se confirma"),
                            review="Water treated on site is not yet confirmed to meet the Safe Drinking Water Act.",
                        ),
                        Option(
                            "no",
                            text("No", "No"),
                            review="Water treated on site does not meet the Safe Drinking Water Act standards.",
                        ),
                    ),
                ),
                Question(
                    key="water_system_management",
                    kind="textarea",
                    label=text(
                        "Describe how you manage the water system for safe drinking and quality, including how you "
                        "monitor the water.",
                        "Describe cómo manejas el sistema de agua para que sea segura para beber y de calidad, "
                        "incluido cómo vigilas el agua.",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("water_treated_onsite", "truthy"),),
                    compiles_to=CompileRule(
                        template="Water system management and monitoring: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="wash_water_additives_added",
                    kind="boolean",
                    label=text(
                        "Is anything added to water that contacts organic product — peracetic acid, hydrogen "
                        "peroxide, chlorine, a wash aid?",
                        "¿Se agrega algo al agua que entra en contacto con el producto orgánico — ácido peracético, "
                        "peróxido de hidrógeno, cloro, un auxiliar de lavado?",
                    ),
                    coaching=text(
                        "Each additive must be on your Materials Application under post-harvest contact materials.",
                        "Cada aditivo debe estar en tu Solicitud de Materiales bajo materiales de contacto "
                        "poscosecha.",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("uses_water", "truthy"),),
                    prefill=Prefill(source="post_harvest_water_evidence"),
                    compiles_to=CompileRule(
                        template="Substances are added to water that contacts organic product: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="wash_water_chlorine_added",
                    kind="boolean",
                    label=text(
                        "Is chlorine among them — sodium or calcium hypochlorite, chlorine dioxide, hypochlorous acid?",
                        "¿El cloro está entre ellos — hipoclorito de sodio o de calcio, dióxido de cloro, ácido hipocloroso?",
                    ),
                    nop_cite="§ 205.605(b)",
                    visible_when=(Condition("wash_water_additives_added", "truthy"),),
                    prefill=Prefill(source="post_harvest_water_evidence"),
                    compiles_to=CompileRule(
                        template="Chlorine materials are among the substances added to wash or flume water: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="wash_water_chlorine_final_rinse",
                    kind="radio",
                    label=text(
                        "Where water last touches the product, how is the Safe Drinking Water Act chlorine limit met?",
                        "Donde el agua toca el producto por última vez, ¿cómo se cumple el límite de cloro de la Ley de "
                        "Agua Potable Segura?",
                    ),
                    coaching=text(
                        "§ 205.605(b) allows chlorine in wash water provided residual chlorine at the last "
                        "point of product contact does not exceed the SDWA maximum residual disinfectant "
                        "limit — 4 ppm for chlorine, 0.8 ppm for chlorine dioxide.",
                        "§ 205.605(b) permite cloro en el agua de lavado siempre que el cloro residual en el "
                        "último punto de contacto con el producto no exceda el límite máximo de desinfectante "
                        "residual de la SDWA — 4 ppm para cloro, 0,8 ppm para dióxido de cloro.",
                    ),
                    nop_cite="§ 205.605(b)",
                    visible_when=(Condition("wash_water_chlorine_added", "truthy"),),
                    compiles_to=CompileRule(
                        template="Chlorine at the last point of product contact: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "water_only_rinse",
                            text("The final rinse uses water only", "El enjuague final usa solo agua"),
                        ),
                        Option(
                            "chlorine_at_or_below_sdwa",
                            text(
                                "The final rinse water carries chlorine at or below the SDWA limit (4 ppm), checked with a test",
                                "El agua del enjuague final lleva cloro en o por debajo del límite de la SDWA (4 ppm), "
                                "verificado con una prueba",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="wash_water_chlorine_final_rinse_other",
                    kind="text",
                    label=text("Describe the other practice", "Describe la otra práctica"),
                    visible_when=(Condition("wash_water_chlorine_final_rinse", "eq", "other"),),
                    compiles_to=CompileRule(
                        template="Chlorine final-rinse practice, other: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                # OTCO C7 7.4-1 and WSDA AGR 2121 L 6: the yes/no the separation list below answered only by
                # implication (2026.11.30).
                # WSDA AGR 2121 L 15a (2026.12.20).
                Question(
                    key="chlorine_rinse_monitoring",
                    kind="textarea",
                    required=False,
                    label=text(
                        "How do you check that the rinse brings chlorine on the crop to or below the Safe Drinking Water "
                        "Act limit? Say the test, where in the process you test, how often, and how the results are "
                        "recorded.",
                        "¿Cómo verificas que el enjuague deja el cloro en el cultivo en o por debajo del límite de la Ley "
                        "de Agua Potable Segura? Indica la prueba, en qué punto del proceso la haces, con qué frecuencia "
                        "y cómo registras los resultados.",
                    ),
                    nop_cite="§ 205.605(b)",
                    visible_when=(Condition("wash_water_chlorine_final_rinse", "eq", "chlorine_at_or_below_sdwa"),),
                    compiles_to=CompileRule(
                        template="How the rinse is checked for chlorine at or below the SDWA limit: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="shares_handling_area_or_equipment",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Are the handling area, food contact surfaces or packing equipment used for both organic and "
                        "non-organic crops?",
                        "¿El área de manejo, las superficies en contacto con alimentos o el equipo de empaque se usan "
                        "tanto para cultivos orgánicos como no orgánicos?",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="Handling area or equipment shared by organic and non-organic crops: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                # WSDA AGR 2121 L 6a (2026.12.20).
                Question(
                    key="cleaning_differs_by_status",
                    kind="radio",
                    required=False,
                    label=text(
                        "Do the cleaning or purging materials and procedures differ before handling non-certified crops?",
                        "¿Difieren los materiales y procedimientos de limpieza o purga antes de manejar cultivos no "
                        "certificados?",
                    ),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("shares_handling_area_or_equipment", "truthy"),),
                    compiles_to=CompileRule(
                        template="Cleaning before non-certified crops: {answer}.", section_key="commingling_barriers"
                    ),
                    options=(
                        Option(
                            "same",
                            text(
                                "The same cleaning materials and procedures are used regardless of organic status",
                                "Se usan los mismos materiales y procedimientos de limpieza sin importar el estado "
                                "orgánico",
                            ),
                        ),
                        Option("differs", text("They differ (describe below)", "Difieren (describe abajo)")),
                    ),
                ),
                Question(
                    key="cleaning_differences_detail",
                    kind="textarea",
                    label=text(
                        "Describe the differences in chemicals or procedures used before handling non-certified crops.",
                        "Describe las diferencias en químicos o procedimientos usados antes de manejar cultivos no "
                        "certificados.",
                    ),
                    visible_when=(Condition("cleaning_differs_by_status", "eq", "differs"),),
                    compiles_to=CompileRule(
                        template="Differences in cleaning before non-certified crops: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="commingling_controls",
                    kind="checkbox_group",
                    label=text(
                        "How is organic product kept separate from nonorganic product during handling?",
                        "¿Cómo se mantiene separado el producto orgánico del no orgánico durante el manejo?",
                    ),
                    coaching=text(
                        "Vague assurances are not a barrier a certifier can verify — list what is "
                        "actually in place: dedicated equipment, a cleanout log, or a facility "
                        "that never touches nonorganic product.",
                        "Las garantías vagas no son una barrera que un certificador pueda verificar — enumera lo "
                        "que realmente existe: equipo dedicado, una bitácora de limpieza o una instalación que "
                        "nunca toca producto no orgánico.",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="Commingling controls used during handling: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "dedicated_equipment",
                            text("Dedicated organic-only equipment", "Equipo dedicado exclusivamente a orgánico"),
                        ),
                        Option(
                            "cleanout_between_runs",
                            text(
                                "Equipment cleanout between runs, with records",
                                "Limpieza de equipo entre corridas, con registros",
                            ),
                        ),
                        Option(
                            "single_product_runs",
                            text(
                                "Single-product runs (one lot at a time)",
                                "Corridas de un solo producto (un lote a la vez)",
                            ),
                        ),
                        Option(
                            "organic_only_facility",
                            text(
                                "Facility handles organic product only",
                                "La instalación maneja únicamente producto orgánico",
                            ),
                        ),
                        Option(
                            "labeled_containers",
                            text(
                                "Labeled, dedicated containers throughout handling",
                                "Contenedores etiquetados y dedicados durante todo el manejo",
                            ),
                        ),
                        # OTCO C7 7.4-1's two controls that had no option (2026.11.30).
                        Option(
                            "organic_first",
                            text(
                                "Organic crops are processed before non-organic crops",
                                "Los cultivos orgánicos se procesan antes que los no orgánicos",
                            ),
                        ),
                        Option(
                            "separate_storage_areas",
                            text(
                                "Organic and non-organic crops are stored in separate areas",
                                "Los cultivos orgánicos y no orgánicos se almacenan en áreas separadas",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="commingling_controls_other",
                    kind="text",
                    label=text("Describe the other control", "Describe el otro control"),
                    visible_when=(Condition("commingling_controls", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Additional commingling control used: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                # WSDA AGR 2121 L 8, 9 and 11 (2026.11.21). Water and sanitizers were asked above; L 8 asks
                # whether ANY input is applied directly to crops after harvest, certified or not. WSDA's list
                # also names feed antibiotics and feed coccidiostats, which are livestock inputs; Trazo does
                # not serve livestock (scope.yaml), so they are not offered.
                Question(
                    key="applies_post_harvest_inputs",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Do you apply any input directly to crops after harvest, certified or not (a wax, a "
                        "sanitizer wash, a ripening or anti-sprouting agent, a packaging gas)?",
                        "¿Aplicas algún insumo directamente a los cultivos después de la cosecha, certificados o no "
                        "(una cera, un lavado sanitizante, un agente de maduración o antibrotación, un gas de "
                        "empaque)?",
                    ),
                    coaching=text(
                        "Include processing aids, such as an anti-foaming agent in the wash line. List each one on your "
                        "materials list, under post-harvest materials, with its brand and manufacturer.",
                        "Incluye los auxiliares de proceso, como un antiespumante en la línea de lavado. Anota cada uno "
                        "en tu lista de materiales, en materiales de poscosecha, con su marca y fabricante.",
                    ),
                    nop_cite="§ 205.270",
                    compiles_to=CompileRule(
                        template="Inputs are applied directly to crops after harvest ({answer}).",
                        template_false="No input is applied directly to crops after harvest.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="post_harvest_input_types",
                    kind="checkbox_group",
                    required=False,
                    visible_when=(Condition("applies_post_harvest_inputs", "eq", True),),
                    label=text(
                        "Which types of input touch the crop after harvest? Check all that apply.",
                        "¿Qué tipos de insumo tocan el cultivo después de la cosecha? Marca todas las que "
                        "correspondan.",
                    ),
                    nop_cite="§ 205.270",
                    compiles_to=CompileRule(
                        template="Types of input applied directly to crops after harvest: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option("anti_foaming", text("Anti-foaming agents", "Agentes antiespumantes")),
                        Option("anti_fungal", text("Anti-fungal agents", "Agentes antifúngicos")),
                        Option("anti_microbial", text("Anti-microbial agents", "Agentes antimicrobianos")),
                        Option("anti_ripening", text("Anti-ripening agents", "Agentes antimaduración")),
                        Option("antioxidants", text("Antioxidants", "Antioxidantes")),
                        Option("floatation", text("Floatation agents", "Agentes de flotación")),
                        Option("packaging_gases", text("Packaging gases", "Gases de empaque")),
                        Option("preservatives", text("Preservatives", "Conservantes")),
                        Option("release_agents", text("Release agents", "Agentes desmoldantes")),
                        Option("ripening", text("Ripening agents", "Agentes de maduración")),
                        Option("sanitizer_washes", text("Sanitizers or washes", "Sanitizantes o lavados")),
                        Option("sprouting_inhibitors", text("Sprouting inhibitors", "Inhibidores de brotación")),
                        Option("waxes_coatings", text("Waxes or coatings", "Ceras o recubrimientos")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                Question(
                    key="post_harvest_input_types_other",
                    kind="text",
                    required=False,
                    visible_when=(
                        Condition("applies_post_harvest_inputs", "eq", True),
                        Condition("post_harvest_input_types", "includes", "other"),
                    ),
                    label=text("Other type of input", "Otro tipo de insumo"),
                    nop_cite="§ 205.270",
                    compiles_to=CompileRule(
                        template="Other type of input applied after harvest: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="post_harvest_input_recording",
                    kind="textarea",
                    required=False,
                    visible_when=(Condition("applies_post_harvest_inputs", "eq", True),),
                    label=text(
                        "How do you record each application of those inputs, to certified and to non-certified "
                        "product?",
                        "¿Cómo registras cada aplicación de esos insumos, al producto certificado y al no "
                        "certificado?",
                    ),
                    coaching=text(
                        "For example: the packing-line log names the wax, the lot and the date for every run, and "
                        "conventional runs are logged on their own sheet.",
                        "Por ejemplo: el registro de la línea de empaque indica la cera, el lote y la fecha de cada "
                        "corrida, y las corridas convencionales se anotan en su propia hoja.",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(
                        template="How each post-harvest input application is recorded: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                # WSDA AGR 2121 L 10 and 10a (2026.11.09).
                Question(
                    key="noncertified_only_inputs_used",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Do you use any post-harvest inputs on non-certified crops that you do not use on certified "
                        "crops?",
                        "¿Usas en cultivos no certificados algún insumo de poscosecha que no usas en cultivos "
                        "certificados?",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="Some post-harvest inputs are used only on non-certified crops ({answer}).",
                        template_false="No post-harvest input is used only on non-certified crops.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="noncertified_inputs_monitoring",
                    kind="textarea",
                    required=False,
                    visible_when=(Condition("noncertified_only_inputs_used", "eq", True),),
                    label=text(
                        "How do you check that those inputs never reach certified product? Include how often you "
                        "check and any testing of product.",
                        "¿Cómo verificas que esos insumos nunca lleguen al producto certificado? Incluye con qué "
                        "frecuencia verificas y cualquier análisis del producto.",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="How certified product is kept from inputs used only on non-certified crops: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                # CCOF G6.4 C1: packaging free of prohibited substances is asked once, in G6.1; the PDF says where
                # and prints that answer (2026.12.20).
                Question(
                    key="packaging_pointer",
                    kind="info",
                    required=False,
                    embed="packaging_pointer",
                    label=text(
                        "Whether all packaging, reused packaging included, is free of prohibited substances is answered "
                        "in Harvest & Transport (G6.1).",
                        "Si todo el empaque, incluido el reutilizado, está libre de sustancias prohibidas se responde en "
                        "Cosecha y transporte (G6.1).",
                    ),
                ),
            ),
        ),
        ModulePage(
            key="d_records_docs",
            title=text("D. Records & docs", "D. Registros y documentos"),
            visible_when=(
                Condition("handling_activities", "truthy"),
                Condition("handling_activities", "not_includes", "no_onfarm_handling"),
            ),
            questions=(
                Question(
                    key="handling_records",
                    kind="checkbox_group",
                    label=text(
                        "Which handling records does your operation keep?",
                        "¿Qué registros de manejo mantiene tu operación?",
                    ),
                    coaching=text(
                        "A run log is date, lot, and quantity for each batch through the process "
                        "— a simple notebook page per run is enough. Certifiers care that records "
                        "exist and are consistent, not that they are fancy.",
                        "Una bitácora de corrida es fecha, lote y cantidad de cada tanda procesada "
                        "— una simple hoja de cuaderno por corrida es suficiente. Al certificador "
                        "le importa que los registros existan y sean consistentes, no que sean "
                        "sofisticados.",
                    ),
                    nop_cite="§ 205.103(b)",
                    compiles_to=CompileRule(
                        template="Handling records maintained: {answer}.",
                        section_key="recordkeeping_description",
                    ),
                    options=(
                        Option(
                            "run_logs",
                            text(
                                "Run logs (what was processed, when, and how much)",
                                "Bitácoras de corrida (qué se procesó, cuándo y cuánto)",
                            ),
                        ),
                        Option("cleanout_logs", text("Equipment cleanout logs", "Bitácoras de limpieza de equipo")),
                        Option(
                            "drying_temp_logs",
                            text("Drying-temperature logs", "Bitácoras de temperatura de secado"),
                        ),
                        Option(
                            "packout_weight_tickets",
                            text("Packout or weight tickets", "Tickets de empaque o de pesaje"),
                        ),
                        Option(
                            "treatment_records",
                            text(
                                "Treatment records (fumigation-free pest treatment, sanitizer use)",
                                "Registros de tratamiento (tratamiento de plagas sin fumigación, uso de sanitizante)",
                            ),
                        ),
                        Option(
                            "none_yet",
                            text("No handling records kept yet", "Aún no se mantienen registros de manejo"),
                            exclusive=True,
                        ),
                    ),
                ),
                # WSDA AGR 2121 L 7, the second half (2026.12.20).
                Question(
                    key="handling_records_linkage",
                    kind="textarea",
                    required=False,
                    label=text(
                        "How do the cleaning and purge records tie back to the production or lot records they cover?",
                        "¿Cómo se vinculan los registros de limpieza y purga con los registros de producción o de lote "
                        "que cubren?",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(
                        template="How the cleaning and purge records link to production records: {answer}",
                        section_key="recordkeeping_description",
                    ),
                ),
                Question(
                    key="facility_docs",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach a site map, process flow chart, or handling SOPs, if you have them",
                        "Adjunta un mapa del sitio, diagrama de flujo del proceso, o procedimientos (SOP) de "
                        "manejo, si los tienes",
                    ),
                    coaching=text(
                        "Not required to complete this module, but a site map or flow chart is "
                        "exactly what a certifier asks for first at an on-site handling review. A flow chart "
                        "attached here and the written steps on the process page each answer the request for a "
                        "flow chart or description.",
                        "No es obligatorio para completar este módulo, pero un mapa del sitio o "
                        "diagrama de flujo es justo lo primero que pide un certificador en una "
                        "revisión de manejo en sitio. Un diagrama adjunto aquí y los pasos escritos en la página "
                        "del proceso responden cada uno la solicitud de diagrama o descripción.",
                    ),
                    nop_cite="§ 205.103",
                ),
                # WSDA AGR 2121 L 18 (2026.12.20).
                Question(
                    key="handling_additional_notes",
                    kind="textarea",
                    required=False,
                    label=text(
                        "Anything else about your post-harvest handling (optional)",
                        "Cualquier otra información sobre tu manejo poscosecha (opcional)",
                    ),
                    compiles_to=CompileRule(template="Additional post-harvest handling information: {answer}"),
                ),
            ),
        ),
    ),
)


G6_5_SALES_SOE = Module(
    key="g6_5_sales_soe",
    code="G6.5",
    title=text(
        "Sales, Direct Marketing & Supplier Verification", "Ventas, venta directa y verificación de proveedores"
    ),
    nop_cites=("§ 205.103", "§ 205.201"),
    education=(
        text(
            "Strengthening Organic Enforcement expects every operation to know its supply "
            "chain: verify certificates of anyone whose organic product you buy or "
            "resell, and keep sales records that link every lot sold to your own harvest "
            "records.",
            "La normativa de Fortalecimiento de la Aplicación Orgánica espera que cada operación conozca su cadena "
            "de suministro: verifica certificados de cualquiera a quien compres o revendas producto orgánico, y "
            "mantén registros de venta que vinculen cada lote vendido con tus registros de cosecha.",
        ),
    ),
    allows_not_applicable=False,
    default_section_key="monitoring_plan",
    pages=(
        ModulePage(
            key="a_sales",
            title=text("A. Sales channels & supplier checks", "A. Canales de venta y verificación de proveedores"),
            # 🔴 2026-08-15 — this module used to be `_describe_and_attach`: two OPTIONAL
            # questions with no CompileRule, inside a module with allows_not_applicable=False.
            # The combination meant `missing_required()` returned [] and the module reported
            # **completed with nothing typed in it** — a green tick on the SOE supplier-
            # verification obligation, earned by silence. And with no CompileRule, even a
            # fully answered module contributed ZERO sentences to the § 205.201(a)(3)
            # narrative a certifier reads.
            questions=(
                Question(
                    key="sales_soe_channels",
                    kind="textarea",
                    label=text(
                        "Describe your sales channels (wholesale, direct, packer).",
                        "Describe tus canales de venta (mayorista, directo, empacadora).",
                    ),
                    required=True,
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(template="Sales channels: {answer}."),
                ),
                Question(
                    key="sales_soe_supplier_verification",
                    kind="radio",
                    label=text(
                        "Do you buy or resell organic product from anyone else?",
                        "¿Compras o revendes producto orgánico de terceros?",
                    ),
                    coaching=text(
                        "If yes, § 205.201(a)(3) expects you to describe how you verify their "
                        "organic certificate and guard against organic fraud.",
                        "Si es así, § 205.201(a)(3) espera que describas cómo verificas su certificado orgánico y "
                        "previenes el fraude orgánico.",
                    ),
                    required=True,
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Purchase or resale of others' organic product: {answer}."),
                    options=(
                        Option(
                            "no",
                            text(
                                "No — we sell only what we grow",
                                "No — solo vendemos lo que cultivamos",
                            ),
                        ),
                        Option(
                            "yes",
                            text(
                                "Yes — we buy in or co-market organic product",
                                "Sí — compramos o comercializamos producto orgánico de terceros",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="sales_soe_verification_method",
                    kind="textarea",
                    label=text(
                        "How do you verify those suppliers' organic certificates, and how often?",
                        "¿Cómo verificas los certificados orgánicos de esos proveedores, y con qué frecuencia?",
                    ),
                    coaching=text(
                        "Name the check and its frequency — e.g. 'certificate requested at "
                        "first purchase and re-checked each season against the USDA Organic "
                        "Integrity Database'.",
                        "Nombra la verificación y su frecuencia — ej. 'certificado solicitado en la primera compra "
                        "y revisado cada temporada contra la base USDA Organic Integrity'.",
                    ),
                    required=True,
                    nop_cite="§ 205.201(a)(3)",
                    visible_when=(Condition("sales_soe_supplier_verification", "eq", "yes"),),
                    compiles_to=CompileRule(template="Supplier certificate verification: {answer}."),
                ),
                # OTCO C12 12.2-4b: whether every document that comes with a bought-in product names it organic.
                Question(
                    key="sourced_products_identified_organic",
                    kind="boolean",
                    label=text(
                        "Does every document that comes with a product you buy in (invoice, bill of lading, "
                        "label) identify it as organic?",
                        "¿Cada documento que acompaña a un producto que compras (factura, conocimiento de "
                        "embarque, etiqueta) lo identifica como orgánico?",
                    ),
                    required=False,
                    nop_cite="§ 205.103(b)(2)",
                    visible_when=(Condition("sales_soe_supplier_verification", "eq", "yes"),),
                    compiles_to=CompileRule(
                        template="Every document received with a bought-in product identifies it as organic: {answer}."
                    ),
                ),
                Question(
                    key="sourced_products_identification_detail",
                    kind="textarea",
                    label=text(
                        "Which documents do not, and how do you keep the product's organic identity?",
                        "¿Cuáles no lo hacen, y cómo mantienes la identidad orgánica del producto?",
                    ),
                    required=False,
                    visible_when=(Condition("sourced_products_identified_organic", "eq", False),),
                    compiles_to=CompileRule(template="Where receiving paperwork does not say organic: {answer}"),
                ),
                # CCOF G6.5 A1/A2, OTCO C12 12.2-4/4a (2026.11.08): what is bought in, from whom, and the
                # copy behind each supplier, read from the supplier register.
                Question(
                    key="sourced_products_panel",
                    kind="info",
                    embed="sourced_products",
                    required=False,
                    visible_when=(Condition("sales_soe_supplier_verification", "eq", "yes"),),
                    label=text(
                        "Suppliers of the organic product you buy in",
                        "Proveedores del producto orgánico que compras",
                    ),
                    coaching=text(
                        "In the supplier register on your farm profile, add each supplier with the products you "
                        "buy from it and a copy of its organic certificate, issued within the last 15 months. "
                        "For an uncertified broker or distributor, name the certified operation it buys from and "
                        "attach the Exempt Handler Affidavit it completed.",
                        "En el registro de proveedores del perfil de tu finca, agrega cada proveedor con los "
                        "productos que le compras y una copia de su certificado orgánico, emitido en los últimos "
                        "15 meses. Para un intermediario o distribuidor no certificado, indica la operación "
                        "certificada a la que compra y adjunta la declaración jurada de manipulador exento que "
                        "completó.",
                    ),
                ),
                # CCOF G6.5 A3, its options.
                Question(
                    key="sourcing_transport_verification",
                    kind="checkbox_group",
                    required=False,
                    visible_when=(Condition("sales_soe_supplier_verification", "eq", "yes"),),
                    label=text(
                        "How do you make sure product you buy in does not contact prohibited substances on its "
                        "way to you?",
                        "¿Cómo te aseguras de que el producto que compras no tenga contacto con sustancias "
                        "prohibidas en el camino hacia ti?",
                    ),
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(
                        template="Bought-in product is kept from prohibited substances in transit by: {answer}."
                    ),
                    options=(
                        Option(
                            "cleaning_purge_logs",
                            text(
                                "Cleaning or purge logs for the transport",
                                "Registros de limpieza o purga del transporte",
                            ),
                        ),
                        Option(
                            "certified_supplier_documentation",
                            text(
                                "The certified supplier provides documentation",
                                "El proveedor certificado entrega documentación",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="sourcing_transport_verification_other",
                    kind="text",
                    required=False,
                    label=text("Describe how", "Describe cómo"),
                    visible_when=(Condition("sourcing_transport_verification", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Bought-in product is also kept from prohibited substances by: {answer}"
                    ),
                ),
                # CCOF G6.5 A4, its options (the same separation measures G6.1 asks for the crop's own transport).
                Question(
                    key="sourcing_transport_commingling",
                    kind="checkbox_group",
                    required=False,
                    visible_when=(Condition("sales_soe_supplier_verification", "eq", "yes"),),
                    label=text(
                        "How do you keep product you buy in from being mixed with non-organic product on its way "
                        "to you?",
                        "¿Cómo evitas que el producto que compras se mezcle con producto no orgánico en el camino "
                        "hacia ti?",
                    ),
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(
                        template="Bought-in product is kept from commingling in transit by: {answer}."
                    ),
                    options=(
                        Option(
                            "only_certified",
                            text(
                                "Not applicable: we source only certified organic product",
                                "No aplica: solo compramos producto orgánico certificado",
                            ),
                            exclusive=True,
                        ),
                        Option(
                            "distinctly_labeled",
                            text(
                                "Distinctly labeled or marked containers",
                                "Contenedores etiquetados o marcados de forma distinta",
                            ),
                        ),
                        Option("closed_containers", text("Closed containers", "Contenedores cerrados")),
                        Option(
                            "different_times",
                            text("Transported at different times", "Transportado en momentos distintos"),
                        ),
                        Option("visually_distinct", text("Visually distinct product", "Producto visualmente distinto")),
                        Option(
                            "separate_vehicles", text("Shipped on separate vehicles", "Enviado en vehículos separados")
                        ),
                        Option(
                            "separate_destinations",
                            text("Shipped from separate locations", "Enviado desde ubicaciones separadas"),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="sourcing_transport_commingling_other",
                    kind="text",
                    required=False,
                    label=text("Describe how", "Describe cómo"),
                    visible_when=(Condition("sourcing_transport_commingling", "includes", "other"),),
                    compiles_to=CompileRule(template="Bought-in product is also kept from commingling by: {answer}"),
                ),
                # OTCO C12 12.2-4a.
                Question(
                    key="sourced_records_link_to_certified",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("sales_soe_supplier_verification", "eq", "yes"),),
                    label=text(
                        "Do your records link the purchase and transport of every product you buy in back to the "
                        "last certified operation that handled it?",
                        "¿Tus registros vinculan la compra y el transporte de cada producto que compras con la "
                        "última operación certificada que lo manipuló?",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(
                        template="Records link each bought-in product's purchase and transport back to the last "
                        "certified operation ({answer}).",
                        template_false="The operator states that records do not yet link every bought-in product "
                        "back to the last certified operation; see the explanation.",
                    ),
                ),
                Question(
                    key="sourced_records_link_detail",
                    kind="textarea",
                    required=False,
                    visible_when=(Condition("sourced_records_link_to_certified", "eq", False),),
                    label=text("Explain which records are missing", "Explica qué registros faltan"),
                    compiles_to=CompileRule(template="Where the sourcing records do not link back: {answer}"),
                ),
                Question(
                    key="sales_soe_lot_linkage",
                    kind="textarea",
                    label=text(
                        "How does a sales record identify which harvest lot it came from?",
                        "¿Cómo identifica un registro de venta de qué lote de cosecha proviene?",
                    ),
                    coaching=text(
                        "§ 205.103(b)(2) asks that records be traceable back to the last "
                        "certified operation. For a grower selling their own crop, that is "
                        "your farm — so the link a certifier follows is sale → lot → harvest.",
                        "§ 205.103(b)(2) pide que los registros sean rastreables hasta la "
                        "última operación certificada. Para un productor que vende su propio "
                        "cultivo, esa es su finca — el vínculo es venta → lote → cosecha.",
                    ),
                    required=True,
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(template="Sale-to-lot traceability: {answer}."),
                ),
                Question(
                    key="sales_soe_upload",
                    kind="upload",
                    label=text(
                        "Attach a sample sales record showing lot identification.",
                        "Adjunta un registro de venta de muestra que muestre la identificación de lote.",
                    ),
                    required=False,
                ),
            ),
        ),
        # CCOF G6.5 B and C (ORGB35 V2, 12/31/2023). Asked as the form asks it: whether the operation sells
        # directly to consumers, each venue in the form's own columns, and how organic is told apart from
        # non-organic at those venues. Added 2026-11-17; optional at the top, so plans already finished stay
        # finished. Together with page A's sourcing answer, these are the two facts CCOF files G6.5 on.
        ModulePage(
            key="b_direct_marketing",
            title=text("B. Direct marketing", "B. Venta directa"),
            questions=(
                Question(
                    key="direct_sales",
                    kind="radio",
                    required=False,
                    label=text(
                        "Do you sell products directly to consumers (CSA, farm stand, farmers' market, u-pick, "
                        "online sales)?",
                        "¿Vendes productos directamente a consumidores (CSA, puesto en la finca, mercado de "
                        "agricultores, cosecha propia por el cliente, ventas en línea)?",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(template="Direct sales to consumers: {answer}."),
                    options=(
                        Option(
                            "no",
                            text("No sales directly to consumers", "No vendemos directamente a consumidores"),
                        ),
                        Option(
                            "yes",
                            text("Yes, we sell directly to consumers", "Sí, vendemos directamente a consumidores"),
                        ),
                    ),
                ),
                Question(
                    key="direct_sales_venues",
                    kind="checkbox_group",
                    label=text("Where do you sell directly?", "¿Dónde vendes directamente?"),
                    visible_when=(Condition("direct_sales", "eq", "yes"),),
                    compiles_to=CompileRule(template="Direct marketing venues: {answer}."),
                    options=(
                        Option("farmers_market", text("Farmers' markets", "Mercados de agricultores")),
                        Option(
                            "csa",
                            text(
                                "CSA (community supported agriculture)",
                                "CSA (agricultura sostenida por la comunidad)",
                            ),
                        ),
                        Option("farm_stand", text("Farm stand", "Puesto en la finca")),
                        Option("u_pick", text("U-pick", "Cosecha propia por el cliente (u-pick)")),
                        Option("online", text("Online or website sales", "Ventas en línea o por sitio web")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                Question(
                    key="farmers_markets_detail",
                    kind="textarea",
                    label=text(
                        "List each farmers' market: the market or its organization, its address, the day(s) you sell "
                        "there, and whether you sell non-organic products at it.",
                        "Indica cada mercado de agricultores: el mercado o su organización, su dirección, los días en "
                        "que vendes allí y si vendes productos no orgánicos en él.",
                    ),
                    coaching=text(
                        "One market per line, for example: Farmtown Farmers' Market Association, 123 Main St, "
                        "Farmtown; Monday and Saturday; no non-organic products.",
                        "Un mercado por línea, por ejemplo: Asociación del Mercado de Agricultores de Farmtown, "
                        "123 Main St, Farmtown; lunes y sábado; sin productos no orgánicos.",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    visible_when=(Condition("direct_sales_venues", "includes", "farmers_market"),),
                    compiles_to=CompileRule(
                        template="Farmers' markets (market, address, days, non-organic products sold): {answer}"
                    ),
                ),
                Question(
                    key="other_venues_detail",
                    kind="textarea",
                    label=text(
                        "List each other venue: its type, its address or website, and whether you sell non-organic "
                        "products at it.",
                        "Indica cada otro lugar de venta: su tipo, su dirección o sitio web y si vendes productos no "
                        "orgánicos en él.",
                    ),
                    coaching=text(
                        "One venue per line, for example: Online sales, www.example-ranch.com, yes.",
                        "Un lugar por línea, por ejemplo: Ventas en línea, www.example-ranch.com, sí.",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    visible_when=(
                        Condition(
                            "direct_sales_venues", "includes_any", ["csa", "farm_stand", "u_pick", "online", "other"]
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Other direct marketing venues (type, address or website, non-organic products sold): "
                        "{answer}"
                    ),
                ),
                Question(
                    key="direct_sales_venue_list_upload",
                    kind="upload",
                    required=False,
                    # A supplement to the two lists, never a substitute: an upload does not answer a required
                    # question (UNVALIDATED_KINDS), so "or attach" would leave the module incomplete for good
                    # (review of app #422).
                    label=text(
                        "You can also attach your own list of direct marketing venues.",
                        "También puedes adjuntar tu propia lista de lugares de venta directa.",
                    ),
                    visible_when=(Condition("direct_sales", "eq", "yes"),),
                ),
            ),
        ),
        ModulePage(
            key="c_direct_marketing_signage",
            title=text(
                "C. Direct marketing representation and signage",
                "C. Representación y señalización en la venta directa",
            ),
            visible_when=(Condition("direct_sales", "eq", "yes"),),
            questions=(
                Question(
                    key="direct_sales_nonorganic",
                    kind="radio",
                    label=text(
                        "Do you also sell non-organic products to consumers?",
                        "¿También vendes productos no orgánicos a consumidores?",
                    ),
                    nop_cite="§ 205.300",
                    compiles_to=CompileRule(template="Products sold directly to consumers: {answer}."),
                    options=(
                        Option(
                            "only_organic",
                            text(
                                "No, we sell only certified organic products",
                                "No, solo vendemos productos orgánicos certificados",
                            ),
                        ),
                        Option(
                            "also_nonorganic",
                            text(
                                "Yes, we also sell non-organic products", "Sí, también vendemos productos no orgánicos"
                            ),
                        ),
                    ),
                ),
                Question(
                    key="direct_sales_differentiation",
                    kind="checkbox_group",
                    label=text(
                        "How do you tell organic and non-organic products apart for consumers?",
                        "¿Cómo distingues para los consumidores los productos orgánicos de los no orgánicos?",
                    ),
                    coaching=text(
                        "Organic and non-organic products must not be commingled, and a non-organic product must not "
                        "be presented as organic.",
                        "Los productos orgánicos y no orgánicos no deben mezclarse, y un producto no orgánico no debe "
                        "presentarse como orgánico.",
                    ),
                    nop_cite="§ 205.300",
                    visible_when=(Condition("direct_sales_nonorganic", "eq", "also_nonorganic"),),
                    compiles_to=CompileRule(
                        template="How organic and non-organic products are told apart for consumers: {answer}."
                    ),
                    options=(
                        Option(
                            "ties_stickers",
                            text("Twist ties, stickers or rubber bands", "Amarres, etiquetas adhesivas o ligas"),
                        ),
                        Option(
                            "newsletter",
                            text(
                                "Newsletter or delivery list (sample attached)",
                                "Boletín o lista de entrega (muestra adjunta)",
                            ),
                            requires_upload="direct_sales_samples_upload",
                        ),
                        Option(
                            "website",
                            text(
                                "Description on the website (sample attached)",
                                "Descripción en el sitio web (muestra adjunta)",
                            ),
                            requires_upload="direct_sales_samples_upload",
                        ),
                        Option(
                            "signage",
                            text(
                                'Clear "organic" and "nonorganic" signage (photo attached)',
                                'Letreros claros de "orgánico" y "no orgánico" (foto adjunta)',
                            ),
                            requires_upload="direct_sales_samples_upload",
                        ),
                        Option(
                            "separate_areas",
                            text(
                                "Separate sales areas for organic and non-organic",
                                "Áreas de venta separadas para lo orgánico y lo no orgánico",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="direct_sales_separate_areas_detail",
                    kind="textarea",
                    label=text("Describe the separate sales areas.", "Describe las áreas de venta separadas."),
                    visible_when=(Condition("direct_sales_differentiation", "includes", "separate_areas"),),
                    compiles_to=CompileRule(template="Separate sales areas for organic and non-organic: {answer}"),
                ),
                Question(
                    key="direct_sales_differentiation_other",
                    kind="text",
                    label=text(
                        "Describe the other way they are told apart",
                        "Describe la otra forma en que se distinguen",
                    ),
                    visible_when=(Condition("direct_sales_differentiation", "includes", "other"),),
                    compiles_to=CompileRule(template="Other way organic and non-organic are told apart: {answer}"),
                ),
                Question(
                    key="direct_sales_samples_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach the samples: the newsletter or delivery list, the website description, or photos of "
                        "the signage.",
                        "Adjunta las muestras: el boletín o la lista de entrega, la descripción del sitio web o fotos de "
                        "los letreros.",
                    ),
                    visible_when=(Condition("direct_sales_nonorganic", "eq", "also_nonorganic"),),
                ),
            ),
        ),
    ),
)


def _address_questions(prefix: str, shown_when: tuple) -> tuple:
    """Street, city, state, ZIP and country as five boxes, the way CCOF's Contract and OTCO's O1 lay out every address,
    so each copies straight into the agent's own form. Shown only when the address is not "same as" another."""
    return tuple(
        Question(key=f"{prefix}_{part}", kind="text", label=label, required=False, visible_when=shown_when)
        for part, label in (
            ("street", text("Street address", "Dirección")),
            ("city", text("City", "Ciudad")),
            ("state", text("State or province", "Estado o provincia")),
            ("zip", text("ZIP or postal code", "Código postal")),
            ("country", text("Country", "País")),
        )
    )


CERTIFICATION_CONTRACT = Module(
    key="certification_contract",
    code="",
    title=text("Operation profile", "Perfil de la operación"),
    nop_cites=("§ 205.401",),
    education=(
        text(
            "Your certifier's application asks for the legal identity behind the "
            "operation — legal name, business structure, addresses, and contacts. Trazo "
            "keeps a copy of the signed contract with your records so renewal starts "
            "from paper you already have.",
            "La solicitud de tu certificador pide la identidad legal de la operación — razón social, estructura, "
            "direcciones y contactos. Trazo guarda una copia del contrato firmado con tus registros para que la "
            "renovación parta de papeles que ya tienes.",
        ),
    ),
    allows_not_applicable=False,
    default_section_key="additional_certifier_info",
    pages=(
        ModulePage(
            key="a_contract",
            title=text("A. Contract on file", "A. Contrato archivado"),
            questions=(
                # 🔴 2026-08-15 — required + compiled.
                #
                # This module is the SOLE feeder of § 205.201(a)(6) ("additional information
                # deemed necessary by the certifying agent"). With one optional textarea and
                # no CompileRule, (a)(6) compiled to an empty string no matter what the
                # operator did — and, with allows_not_applicable=False and zero required
                # questions, the module still reported `completed`.
                Question(
                    key="contract_notes",
                    kind="textarea",
                    label=text(
                        "Legal name, business structure, and any name differences between "
                        "the certificate and your sales documents.",
                        "Razón social, estructura del negocio y cualquier diferencia de nombre entre el certificado "
                        "y tus documentos de venta.",
                    ),
                    coaching=text(
                        "Name mismatches between the certificate and an invoice are one of "
                        "the commonest audit findings — state them here rather than leaving "
                        "the inspector to discover them.",
                        "Las diferencias de nombre entre el certificado y una factura son uno "
                        "de los hallazgos de auditoría más comunes — indícalas aquí en lugar "
                        "de dejar que el inspector las descubra.",
                    ),
                    required=True,
                    nop_cite="§ 205.401",
                    compiles_to=CompileRule(template="Legal identity and naming: {answer}."),
                ),
                Question(
                    # OTCO O1 §B (B-2 to B-6) and CCOF Contract A4, C1, C2: the people the operation names to its
                    # agent, each with roles. Rows on `OperationContact`, judged by the register as answered once a
                    # primary contact and a legally responsible contact are named.
                    key="operation_contacts",
                    kind="info",
                    label=text(
                        "The people you name to your certifier, and their roles",
                        "Las personas que nombras ante tu certificador, y sus funciones",
                    ),
                    coaching=text(
                        "Include the legally responsible person, the primary contact, everyone authorized to meet "
                        "inspectors or change the plan, and every partner, officer, director, manager or owner of 10 "
                        "percent or more. One person can hold several roles.",
                        "Incluye a la persona legalmente responsable, al contacto principal, a cada persona autorizada "
                        "para reunirse con inspectores o cambiar el plan, y a cada socio, directivo, gerente o dueño "
                        "del 10 por ciento o más. Una misma persona puede tener varias funciones.",
                    ),
                    embed="operation_contacts",
                    required=False,
                    nop_cite="§ 205.2",
                ),
                Question(
                    key="contract_scopes",
                    kind="checkbox_group",
                    label=text(
                        "Which scopes is this operation certified for, or applying for?",
                        "¿Para qué alcances está certificada, o solicita, esta operación?",
                    ),
                    required=True,
                    nop_cite="§ 205.401(a)",
                    compiles_to=CompileRule(template="Certification scopes: {answer}."),
                    options=(
                        Option("crops", text("Crops", "Cultivos")),
                        Option("wild_crops", text("Wild crops", "Cultivos silvestres")),
                        Option("livestock", text("Livestock", "Ganadería")),
                        Option("handling", text("Handling / processing", "Manipulación / procesamiento")),
                        Option("transitional", text("Transitional", "En transición")),
                        Option("fungi", text("Mushrooms and other fungi", "Hongos y setas")),
                    ),
                ),
                # 2026-11-15: CCOF Contract B1, "describe or attach a summary description of your organic business
                # or plans". `contract_notes` answers naming, not this.
                Question(
                    key="organic_business_summary",
                    kind="textarea",
                    required=False,
                    label=text(
                        "Describe your organic business in a few sentences, and any plans to change it.",
                        "Describe tu negocio orgánico en pocas frases, y cualquier plan de cambiarlo.",
                    ),
                    coaching=text(
                        "What you grow or handle, on how much land and where, who buys it, and anything new for the "
                        "coming season. The details are in the rest of this plan.",
                        "Qué cultivas o manejas, en cuánta tierra y dónde, quién lo compra, y cualquier novedad para "
                        "la próxima temporada. Los detalles están en el resto de este plan.",
                    ),
                    placeholder=text(
                        "e.g. 40 acres of certified organic walnuts in Butte County, sold in-shell to one huller. "
                        "We plan to add 10 acres of almonds next year.",
                        "p. ej. 40 acres de nogales orgánicos certificados en el condado de Butte, vendidos con cáscara "
                        "a una descascaradora. Planeamos sumar 10 acres de almendros el próximo año.",
                    ),
                    nop_cite="§ 205.401(a)",
                    compiles_to=CompileRule(template="Organic operation summary: {answer}"),
                ),
                Question(
                    key="contract_upload",
                    kind="upload",
                    label=text(
                        "Attach the signed certification contract / client agreement.",
                        "Adjunta el contrato de certificación firmado / acuerdo de cliente.",
                    ),
                    required=False,
                ),
                # 2026-11-13: OTCO O1 I-B and CCOF Contract G ask the signer's name, title and the date beside the
                # signature. Trazo signs nothing: the operation signs its agency's own form and attaches it above,
                # and these two say who signed it and when, so the packet names them without opening the file.
                Question(
                    key="contract_signed_by",
                    kind="text",
                    required=False,
                    label=text(
                        "Who signed it? Name and title.",
                        "¿Quién lo firmó? Nombre y cargo.",
                    ),
                    coaching=text(
                        "Trazo does not sign for you. Sign your agency's own form, attach it above, and write who "
                        "signed it. The signer must be able to bind the operation: an owner, an officer, or "
                        "someone they appointed.",
                        "Trazo no firma por ti. Firma el formulario de tu agencia, adjúntalo arriba y escribe quién "
                        "lo firmó. Quien firma debe tener facultad para obligar a la operación: una persona "
                        "propietaria o directiva, o una persona designada para firmar.",
                    ),
                    placeholder=text("e.g. Laurel Brandt, managing member", "p. ej. Laurel Brandt, gerente"),
                ),
                Question(
                    key="contract_signed_on",
                    kind="date",
                    required=False,
                    label=text("Date it was signed", "Fecha de la firma"),
                ),
            ),
        ),
        # 2026-11-09: CCOF Certification Contract D5 to D6 and OTCO O1 D-1E, D-2 to D-7. Both forms ask the
        # same thing of "this operation or anyone responsibly connected to it", as one yes/no each, and a
        # yes is what makes their "attach the letters, describe the corrective actions" row apply.
        #
        # Optional, every question: these matter mainly to applicants and to farms with a lapse, and
        # making them required would turn every completed Operation profile back to incomplete on plans
        # already in use. Unanswered prints "Not answered (optional).", never "No".
        #
        # No `compiles_to`: adverse history is read on the operation profile PDF, not woven into the
        # § 205.201(a)(6) narrative.
        #
        # The labels say "findings" and "notice ... unresolved", not the forms' "outstanding noncompliances":
        # the packet never carries that word (`test_packet_wording_follows_records`, the no-verdict rule), and
        # the module PDF prints every label, answered or not. `truthy`, not `eq True`: the PDF words a page
        # gate from its condition, and a boolean has no options to name, so `eq True` printed "is True".
        ModulePage(
            key="b_certification_history",
            title=text("B. Certification history", "B. Historial de certificación"),
            education=(
                text(
                    "Certifiers ask whether this operation, or anyone responsibly connected to it (owners, "
                    "officers, managers, the person who signs), has held or applied for organic certification "
                    "before, and whether any of it ended badly. One answer covers all of them.",
                    "Los certificadores preguntan si esta operación, o alguien responsablemente vinculado a ella "
                    "(dueños, directivos, gerentes, quien firma), tuvo o solicitó antes una certificación orgánica, "
                    "y si alguna terminó mal. Una respuesta los cubre a todos.",
                ),
            ),
            questions=(
                Question(
                    key="history_ever_certified",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Has this operation, or anyone responsibly connected to it, ever been certified organic?",
                        "¿Esta operación, o alguien responsablemente vinculado a ella, estuvo alguna vez "
                        "certificada como orgánica?",
                    ),
                    nop_cite="§ 205.401(c)",
                ),
                Question(
                    key="history_prior_agents",
                    kind="textarea",
                    required=False,
                    visible_when=(Condition("history_ever_certified", "truthy"),),
                    label=text(
                        "Which certifying agencies, and the dates (or years) each certification was held?",
                        "¿Qué agencias certificadoras, y en qué fechas (o años) se tuvo cada certificación?",
                    ),
                    placeholder=text(
                        "e.g. Oregon Tilth, March 2015 to June 2021; CCOF since 2022",
                        "p. ej. Oregon Tilth, de marzo de 2015 a junio de 2021; CCOF desde 2022",
                    ),
                ),
                # 2026-11-15: OTCO O1 D-1 asks a currently certified operation for its most recent certificate. The
                # agency the plan is filed with issued it; another agency's certificate is asked just below. A shown
                # upload with no file reads as missing, so the yes or no comes first.
                Question(
                    key="history_certified_by_this_agency",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_ever_certified", "truthy"),),
                    label=text(
                        "Is the operation certified organic today by the agency you file this plan with?",
                        "¿La operación tiene hoy una certificación orgánica de la agencia ante la que presentas este "
                        "plan?",
                    ),
                    coaching=text(
                        "Yes for a renewal. Some agencies ask for a copy of the most recent certificate with it.",
                        "Sí, si es una renovación. Algunas agencias piden con ella una copia del certificado más "
                        "reciente.",
                    ),
                    nop_cite="§ 205.404",
                ),
                Question(
                    key="history_this_agency_certificate_upload",
                    kind="upload",
                    required=False,
                    visible_when=(Condition("history_certified_by_this_agency", "truthy"),),
                    label=text(
                        "Attach the most recent organic certificate that agency issued.",
                        "Adjunta el certificado orgánico más reciente que emitió esa agencia.",
                    ),
                ),
                # 2026-11-13: OTCO O1 D-1A, D-1B and the certificate it asks attached; CCOF Contract D4, whose
                # yes needs the certificate and a transfer form. Visibility is transitive (conditions.py), so each
                # follow-up names only the question it follows.
                Question(
                    key="history_certified_elsewhere_now",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_ever_certified", "truthy"),),
                    label=text(
                        "Is the operation certified organic today by another certifying agency, not the one you "
                        "file this plan with?",
                        "¿La operación tiene hoy una certificación orgánica de otra agencia certificadora, distinta "
                        "de aquella ante la que presentas este plan?",
                    ),
                    nop_cite="§ 205.401(c)",
                ),
                Question(
                    key="history_keeping_other_certification",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_certified_elsewhere_now", "truthy"),),
                    label=text(
                        "Will the operation keep that other certification?",
                        "¿La operación mantendrá esa otra certificación?",
                    ),
                ),
                Question(
                    key="history_current_certificate_upload",
                    kind="upload",
                    required=False,
                    visible_when=(Condition("history_certified_elsewhere_now", "truthy"),),
                    label=text(
                        "Attach the most recent certificate from that agency, and any transfer form the agency "
                        "you file with asks for.",
                        "Adjunta el certificado más reciente de esa agencia y cualquier formulario de transferencia "
                        "que pida la agencia ante la que presentas el plan.",
                    ),
                ),
                Question(
                    key="history_suspended",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_ever_certified", "truthy"),),
                    label=text(
                        "Was that certification, or the certification of any field or product, ever suspended?",
                        "¿Esa certificación, o la de algún campo o producto, fue suspendida alguna vez?",
                    ),
                    nop_cite="§ 205.662(e)",
                ),
                Question(
                    key="history_revoked",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_ever_certified", "truthy"),),
                    label=text(
                        "Was it ever revoked?",
                        "¿Fue revocada alguna vez?",
                    ),
                    nop_cite="§ 205.662(e)",
                ),
                Question(
                    key="history_surrendered_outstanding",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_ever_certified", "truthy"),),
                    label=text(
                        "Was a certification ever surrendered while the agency's findings or conditions were "
                        "still unresolved?",
                        "¿Se renunció alguna vez a una certificación con hallazgos o condiciones de la agencia "
                        "todavía sin resolver?",
                    ),
                ),
                Question(
                    key="history_outstanding_noncompliances",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_ever_certified", "truthy"),),
                    label=text(
                        "Is any notice issued by any of those agencies still unresolved?",
                        "¿Hay algún aviso emitido por alguna de esas agencias que siga sin resolver?",
                    ),
                    coaching=text(
                        "For your current agency, the Certifier inspections and notices card on the Organic "
                        "System Plan page lists each notice and whether its resolution notice is on file. It "
                        "only knows what you recorded there, so answer for every agency yourself.",
                        "Para tu agencia actual, la tarjeta Inspecciones y avisos de la certificadora en la "
                        "página del Plan del Sistema Orgánico muestra cada aviso y si tienes archivada su "
                        "resolución. Solo sabe lo que registraste ahí, así que responde tú por cada agencia.",
                    ),
                    nop_cite="§ 205.662(a)",
                ),
                Question(
                    key="history_denied",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Was an application for organic certification ever denied?",
                        "¿Alguna vez se denegó una solicitud de certificación orgánica?",
                    ),
                    nop_cite="§ 205.405",
                ),
                Question(
                    key="history_withdrew_outstanding",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Was an application for certification ever withdrawn while the agency's findings were "
                        "still unresolved?",
                        "¿Se retiró alguna vez una solicitud de certificación con hallazgos de la agencia "
                        "todavía sin resolver?",
                    ),
                    nop_cite="§ 205.401(c)",
                ),
            ),
        ),
        ModulePage(
            key="c_adverse_history",
            title=text("C. What happened", "C. Qué pasó"),
            education=(
                text(
                    "You answered yes above. Both CCOF and OTCO ask for the years and agencies, a copy of every "
                    "letter, and what you did to correct it.",
                    "Respondiste que sí arriba. CCOF y OTCO piden los años y las agencias, una copia de cada carta y "
                    "lo que hiciste para corregirlo.",
                ),
            ),
            visible_when_any=(
                Condition("history_suspended", "truthy"),
                Condition("history_revoked", "truthy"),
                Condition("history_surrendered_outstanding", "truthy"),
                Condition("history_outstanding_noncompliances", "truthy"),
                Condition("history_denied", "truthy"),
                Condition("history_withdrew_outstanding", "truthy"),
            ),
            questions=(
                Question(
                    key="history_adverse_explanation",
                    kind="textarea",
                    required=False,
                    label=text(
                        "For each yes: the year, the agency, what happened and the corrective actions taken.",
                        "Por cada sí: el año, la agencia, qué pasó y las acciones correctivas que tomaste.",
                    ),
                ),
                Question(
                    key="history_letters_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach every letter about it: notices, the suspension, revocation or denial, and any "
                        "resolution.",
                        "Adjunta cada carta al respecto: avisos, la suspensión, revocación o denegación, y "
                        "cualquier resolución.",
                    ),
                ),
                Question(
                    key="history_this_agent_records",
                    kind="info",
                    required=False,
                    label=text(
                        "Notices from your current agency that you recorded on the Certifier inspections and "
                        "notices card print in the renewal packet with their letters. Attach here the letters "
                        "from earlier agencies, and anything not on that card.",
                        "Los avisos de tu agencia actual que registraste en la tarjeta Inspecciones y avisos de "
                        "la certificadora se imprimen en el paquete de renovación con sus cartas. Adjunta aquí "
                        "las cartas de agencias anteriores y todo lo que no esté en esa tarjeta.",
                    ),
                ),
                Question(
                    key="history_not_sold_since_suspension",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_suspended", "truthy"),),
                    label=text(
                        "I affirm that no product has been sold, labeled or represented as organic since the "
                        "date of the suspension.",
                        "Afirmo que ningún producto se vendió, etiquetó ni presentó como orgánico desde la fecha "
                        "de la suspensión.",
                    ),
                ),
                Question(
                    key="history_currently_suspended",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_suspended", "truthy"),),
                    label=text(
                        "Is the operation suspended today?",
                        "¿La operación está suspendida hoy?",
                    ),
                ),
                Question(
                    key="history_request_reinstatement",
                    kind="boolean",
                    required=False,
                    visible_when=(
                        Condition("history_suspended", "truthy"),
                        Condition("history_currently_suspended", "truthy"),
                    ),
                    label=text(
                        "I request that the National Organic Program reinstate this operation's certification.",
                        "Solicito que el Programa Orgánico Nacional restablezca la certificación de esta operación.",
                    ),
                    nop_cite="§ 205.662(f)(1)",
                ),
                Question(
                    key="history_not_sold_since_revocation",
                    kind="boolean",
                    required=False,
                    visible_when=(Condition("history_revoked", "truthy"),),
                    label=text(
                        "I affirm that no product has been sold, labeled or represented as organic since the "
                        "date of the revocation.",
                        "Afirmo que ningún producto se vendió, etiquetó ni presentó como orgánico desde la fecha "
                        "de la revocación.",
                    ),
                ),
            ),
        ),
        # 2026-11-13: CCOF Certification Contract A1 to A4, A6, A7 and OTCO O1 A-1, A-3, B-1, B-7. Who the
        # operation is in law, the names it trades under, where mail and invoices go, and what may be published.
        # The farm's physical address stays on its profile (it prints on the packet cover); every address here is
        # asked as "same as" first, so nobody types one twice.
        #
        # Optional, every question, for the same reason as page B: making them required would turn every completed
        # Operation profile back to incomplete on plans already in use.
        ModulePage(
            key="d_legal_entity",
            title=text("D. Legal entity and addresses", "D. Entidad legal y direcciones"),
            education=(
                text(
                    "Certifiers ask who the operation is in law, which names it trades under, where to send mail and "
                    "invoices, and which contact details they may publish. The business name and the farm's "
                    "physical address come from the farm profile and print on the packet cover.",
                    "Los certificadores preguntan quién es la operación ante la ley, con qué nombres comercia, a "
                    "dónde enviar el correo y las facturas, y qué datos de contacto pueden publicar. La razón social "
                    "y la dirección física de la finca salen del perfil de la finca y se imprimen en la portada del "
                    "paquete.",
                ),
            ),
            questions=(
                Question(
                    key="legally_registered",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Is the operation's business name a legally registered business?",
                        "¿La razón social de la operación es un negocio registrado legalmente?",
                    ),
                    coaching=text(
                        "Each certified operation must be its own legal entity, with its own certificate.",
                        "Cada operación certificada debe ser su propia entidad legal, con su propio certificado.",
                    ),
                ),
                Question(
                    key="legal_structure",
                    kind="radio",
                    required=False,
                    label=text(
                        "What is the operation's business structure?", "¿Cuál es la estructura legal del negocio?"
                    ),
                    coaching=text(
                        "The owners, partners and officers go in the people list on page A, marked responsibly "
                        "connected.",
                        "Los dueños, socios y directivos van en la lista de personas de la página A, marcados con "
                        "vínculo responsable.",
                    ),
                    options=(
                        Option("sole_proprietorship", text("Sole proprietorship", "Empresa individual")),
                        Option("partnership", text("Partnership", "Sociedad de personas (partnership)")),
                        Option("corporation", text("Corporation", "Corporación")),
                        Option(
                            "llc", text("Limited liability company (LLC)", "Sociedad de responsabilidad limitada (LLC)")
                        ),
                        Option("other", text("Other", "Otra")),
                    ),
                ),
                Question(
                    key="legal_structure_other",
                    kind="text",
                    required=False,
                    visible_when=(Condition("legal_structure", "eq", "other"),),
                    label=text("Which structure?", "¿Qué estructura?"),
                ),
                Question(
                    key="state_of_incorporation",
                    kind="text",
                    required=False,
                    visible_when=(Condition("legal_structure", "one_of", ["corporation", "llc"]),),
                    label=text("State of incorporation or registration", "Estado donde se constituyó o registró"),
                ),
                Question(
                    key="uses_dba",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Does the operation trade under any name other than its business name (a DBA)?",
                        "¿La operación comercia con algún nombre distinto de su razón social (un DBA)?",
                    ),
                    coaching=text(
                        "A DBA goes on the organic certificate only when it is this same legal business under another "
                        "name, not a separate operation.",
                        "Un DBA va en el certificado orgánico solo si es este mismo negocio legal con otro nombre, no "
                        "una operación aparte.",
                    ),
                ),
                Question(
                    key="dba_names",
                    kind="textarea",
                    required=False,
                    visible_when=(Condition("uses_dba", "truthy"),),
                    label=text("List each DBA, one per line.", "Escribe cada DBA, uno por línea."),
                ),
                Question(
                    key="dba_registration",
                    kind="checkbox_group",
                    required=False,
                    visible_when=(Condition("uses_dba", "truthy"),),
                    label=text("Where is it registered?", "¿Dónde está registrado?"),
                    options=(
                        Option("state", text("With the state", "Ante el estado")),
                        Option("local", text("With the county or city", "Ante el condado o la ciudad")),
                        Option("not_registered", text("Not registered", "Sin registrar"), exclusive=True),
                    ),
                ),
                Question(
                    key="dba_use",
                    kind="radio",
                    required=False,
                    visible_when=(Condition("uses_dba", "truthy"),),
                    label=text(
                        "Where does the DBA appear in your records (invoices, bills of lading, labels)?",
                        "¿Dónde aparece el DBA en tus registros (facturas, conocimientos de embarque, etiquetas)?",
                    ),
                    options=(
                        Option("all", text("For all products and markets", "En todos los productos y mercados")),
                        Option(
                            "some",
                            text("Only for some products or markets", "Solo en algunos productos o mercados"),
                        ),
                        Option("none", text("It does not appear in the records", "No aparece en los registros")),
                    ),
                ),
                Question(
                    key="dba_use_detail",
                    kind="textarea",
                    required=False,
                    visible_when=(Condition("dba_use", "eq", "some"),),
                    label=text("Which products or markets?", "¿Qué productos o mercados?"),
                ),
                Question(
                    key="legal_address_is",
                    kind="radio",
                    required=False,
                    label=text(
                        "What is the registered legal business address?",
                        "¿Cuál es la dirección legal registrada del negocio?",
                    ),
                    options=(
                        Option("physical", text("The farm's physical address", "La dirección física de la finca")),
                        Option("other", text("A different address", "Otra dirección")),
                    ),
                ),
                *_address_questions("legal_address", (Condition("legal_address_is", "eq", "other"),)),
                Question(
                    key="mailing_address_is",
                    kind="radio",
                    required=False,
                    label=text(
                        "Where should certification mail go?", "¿A dónde debe llegar el correo postal de certificación?"
                    ),
                    options=(
                        Option("legal", text("The registered legal address", "La dirección legal registrada")),
                        Option("physical", text("The farm's physical address", "La dirección física de la finca")),
                        Option("other", text("A different address", "Otra dirección")),
                    ),
                ),
                *_address_questions("mailing_address", (Condition("mailing_address_is", "eq", "other"),)),
                Question(
                    key="billing_address_is",
                    kind="radio",
                    required=False,
                    label=text("Where should invoices go?", "¿A dónde deben ir las facturas?"),
                    coaching=text(
                        "The billing contact's name and email are in the people list on page A.",
                        "El nombre y el correo del contacto de facturación están en la lista de personas de la "
                        "página A.",
                    ),
                    options=(
                        Option("mailing", text("The mailing address", "La dirección postal")),
                        Option("other", text("A different address", "Otra dirección")),
                    ),
                ),
                *_address_questions("billing_address", (Condition("billing_address_is", "eq", "other"),)),
                Question(
                    key="public_contact_shared",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "Which contact details may your certifier publish?",
                        "¿Qué datos de contacto puede publicar tu certificador?",
                    ),
                    coaching=text(
                        "Certifiers list these in the USDA Organic Integrity Database and on the certificate. A "
                        "public email is listed only; your certifier writes to the primary contact.",
                        "Los certificadores los publican en la base de datos Organic Integrity del USDA y en el "
                        "certificado. Un correo público solo se publica; tu certificador escribe al contacto "
                        "principal.",
                    ),
                    options=(
                        Option("phone", text("A phone number", "Un teléfono")),
                        Option("email", text("An email address", "Un correo electrónico")),
                        Option("website", text("A website", "Un sitio web")),
                        Option("none", text("None of them", "Ninguno"), exclusive=True),
                    ),
                ),
                Question(
                    key="public_phone",
                    kind="text",
                    required=False,
                    visible_when=(Condition("public_contact_shared", "includes", "phone"),),
                    label=text("Public phone", "Teléfono público"),
                ),
                Question(
                    key="public_email",
                    kind="text",
                    required=False,
                    visible_when=(Condition("public_contact_shared", "includes", "email"),),
                    label=text("Public email", "Correo electrónico público"),
                ),
                Question(
                    key="public_website",
                    kind="text",
                    required=False,
                    visible_when=(Condition("public_contact_shared", "includes", "website"),),
                    label=text("Public website", "Sitio web público"),
                ),
            ),
        ),
        # 2026-11-13: OTCO O1 C-2, C-5 and C-6. The standards the operation asks to be assessed to, the regulators
        # that inspect it, and any negative report one of them gave. The standards list is O1's plus the two more the
        # OSP Update Form's Step 3 offers (Bee Better, GOTS), so one answer serves both. Optional, every question, as
        # on pages B and D.
        ModulePage(
            key="e_standards_regulators",
            title=text("E. Standards and regulatory agencies", "E. Normas y organismos reguladores"),
            questions=(
                Question(
                    key="standards_requested",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "Which standards do you want the operation assessed to?",
                        "¿Según qué normas quieres que se evalúe la operación?",
                    ),
                    coaching=text(
                        "An EU or Mexico assessment needs your agency's supplement form for it. Ask your agency "
                        "first: not every agency offers every standard to operations in the US.",
                        "Una evaluación para la UE o México necesita el formulario complementario de tu agencia. "
                        "Pregunta antes a tu agencia: no todas ofrecen todas las normas a operaciones en EE. UU.",
                    ),
                    options=(
                        Option(
                            "usda_nop",
                            text(
                                "USDA organic (National Organic Program)", "Orgánico USDA (Programa Orgánico Nacional)"
                            ),
                        ),
                        Option(
                            "us_canada",
                            text(
                                "US-Canada organic equivalency (product that goes to Canada)",
                                "Equivalencia orgánica entre EE. UU. y Canadá (producto que va a Canadá)",
                            ),
                        ),
                        Option("eu", text("European Union organic", "Orgánico de la Unión Europea")),
                        Option(
                            "lpo",
                            text("Mexico's organic products law (LPO)", "Ley de Productos Orgánicos de México (LPO)"),
                        ),
                        Option("salmon_safe", text("Salmon-Safe", "Salmon-Safe")),
                        Option("transitional", text("Certified transitional", "Transición certificada")),
                        Option("personal_care", text("NSF/ANSI 305 personal care", "NSF/ANSI 305 de cuidado personal")),
                        Option(
                            "grass_fed",
                            text("Grass-fed (Organic Plus Trust)", "Alimentación con pasto (Organic Plus Trust)"),
                        ),
                        Option("bee_better", text("Bee Better", "Bee Better")),
                        Option(
                            "gots",
                            text("Global Organic Textile Standard (GOTS)", "Norma Textil Orgánica Global (GOTS)"),
                        ),
                        Option("other", text("Other", "Otra")),
                    ),
                ),
                Question(
                    key="standards_requested_other",
                    kind="text",
                    required=False,
                    visible_when=(Condition("standards_requested", "includes", "other"),),
                    label=text("Which other standard?", "¿Qué otra norma?"),
                ),
                Question(
                    key="regulatory_agencies",
                    kind="textarea",
                    required=False,
                    label=text(
                        'Which regulatory agencies, if any, inspect the operation? Write "None" if none do.',
                        '¿Qué organismos reguladores, si hay alguno, inspeccionan la operación? Escribe "Ninguno" '
                        "si no hay.",
                    ),
                    placeholder=text(
                        "e.g. state department of agriculture (food safety), county agricultural commissioner, FDA",
                        "p. ej. departamento de agricultura del estado (inocuidad), comisionado agrícola del condado, FDA",
                    ),
                ),
                Question(
                    key="regulatory_negative_report",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Has any regulatory agency ever given the operation a negative inspection report? For "
                        "example the FDA, OSHA, or a state health or agriculture department.",
                        "¿Algún organismo regulador le dio alguna vez a la operación un informe de inspección "
                        "negativo? Por ejemplo la FDA, OSHA o un departamento estatal de salud o de agricultura.",
                    ),
                ),
                Question(
                    key="regulatory_reports_upload",
                    kind="upload",
                    required=False,
                    visible_when=(Condition("regulatory_negative_report", "truthy"),),
                    label=text(
                        "Attach each report with the operation's written response or corrective actions.",
                        "Adjunta cada informe con la respuesta escrita o las acciones correctivas de la operación.",
                    ),
                ),
            ),
        ),
    ),
)
