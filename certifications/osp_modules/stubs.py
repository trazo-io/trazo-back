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

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text


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
    nop_cites=("§ 205.204(a)(2)",),
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
            questions=_describe_and_attach(
                "seedlings",
                text(
                    "Describe where annual seedlings come from (own greenhouse, certified "
                    "supplier) and how their organic status is documented.",
                    "Describa de dónde provienen las plántulas anuales (invernadero propio, "
                    "proveedor certificado) y cómo se documenta su estado orgánico.",
                ),
                text(
                    "Attach supplier organic certificates for purchased seedlings.",
                    "Adjunte certificados orgánicos del proveedor para plántulas compradas.",
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
                    "Describa el área designada de recolección silvestre, su historial de "
                    "36 meses y cómo se protege la sostenibilidad de la cosecha.",
                ),
                text(
                    "Attach a map of the designated area and any landowner statements.",
                    "Adjunte un mapa del área designada y declaraciones del propietario si " "las hay.",
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
# handler-certification status (§ 205.101(b) — see the module education below).
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
            "handler's job. An operation that handles only its own crop, and never receives "
            "product from another grower, may be exempt from a separate handler certification "
            "(§ 205.101(b)), but that possible exemption does not remove the requirement to "
            "describe those on-farm handling steps in this system plan. Confirm your operation's "
            "certification scope with your certifying agent — do not assume exempt status without "
            "that confirmation.",
            "Lavar, descascarar, pelar, secar, seleccionar, clasificar, enfriar y empacar su propio "
            "cultivo son actividades de manejo bajo la normativa orgánica — no solo tarea de un "
            "manejador aparte. Una operación que maneja únicamente su propio cultivo, y nunca "
            "recibe producto de otro productor, puede estar exenta de una certificación de "
            "manejador separada (§ 205.101(b)), pero esa posible exención no elimina el requisito "
            "de describir esos pasos de manejo en la finca dentro de este plan de sistema. Confirme "
            "el alcance de la certificación de su operación con su agente certificador — no asuma "
            "la condición de exento sin esa confirmación.",
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
            title=text("A. Does your operation handle?", "A. ¿Su operación realiza manejo?"),
            questions=(
                Question(
                    key="handling_activities",
                    kind="checkbox_group",
                    label=text(
                        "Which on-farm handling steps does your operation perform on this crop?",
                        "¿Qué pasos de manejo realiza su operación en la finca para este cultivo?",
                    ),
                    coaching=text(
                        "Include every step performed on your own property, even a quick rinse, "
                        "hand-sort, or size grading — these all count as handling. If a packer or "
                        "processor off your property does this work instead, describe that "
                        "relationship in Sales & Supplier Verification (G6.5), not here.",
                        "Incluya cada paso realizado en su propia finca, incluso un enjuague "
                        "rápido, una selección manual o una clasificación por tamaño — todos "
                        "cuentan como manejo. Si un empacador o procesador fuera de su finca hace "
                        "este trabajo en su lugar, describa esa relación en Ventas y Verificación "
                        "de Proveedores (G6.5), no aquí.",
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
                        Option(
                            "pest_treatment_nonfumigation",
                            text(
                                "Fumigation-free pest treatment (e.g., freezing)",
                                "Tratamiento de plagas sin fumigación (p. ej., congelado)",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describa abajo)")),
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
                    label=text("Describe the other handling step", "Describa el otro paso de manejo"),
                    visible_when=(Condition("handling_activities", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional on-farm handling step: {answer}."),
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
                Question(
                    key="own_products_only",
                    kind="radio",
                    label=text(
                        "Do you handle only your own crop, or also product from other growers?",
                        "¿Maneja únicamente su propio cultivo, o también producto de otros productores?",
                    ),
                    coaching=text(
                        "Custom-handling means running someone else's certified organic crop "
                        "through your equipment for a fee — common where a walnut huller or "
                        "almond huller serves several neighboring orchards. It does not include "
                        "buying their crop outright once it is already harvested and sold to you.",
                        "Manejo por encargo significa procesar en su equipo el cultivo orgánico "
                        "certificado de otra persona a cambio de un pago — común cuando un "
                        "descascarador de nueces o almendras atiende a varias huertas vecinas. No "
                        "incluye comprarles el cultivo una vez que ya se lo vendieron cosechado.",
                    ),
                    nop_cite="§ 205.101(b)",
                    compiles_to=CompileRule(template="On-farm handling covers: {answer}."),
                    options=(
                        Option("own", text("Only our own crop", "Únicamente nuestro propio cultivo")),
                        Option(
                            "also_neighbors_custom",
                            text(
                                "Also custom-handles product for other growers",
                                "También maneja por encargo producto de otros productores",
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
                        "Describa cómo se mantiene separado el producto de otro productor del "
                        "suyo, y qué registros conserva para sus lotes",
                    ),
                    coaching=text(
                        "Custom-handling another operation's crop makes you a handler for their "
                        "product too — Strengthening Organic Enforcement expects the same lot "
                        "separation, labeling, and traceable records you keep for your own crop.",
                        "Manejar el cultivo de otra operación por encargo lo convierte también en "
                        "manejador de ese producto — la normativa de Fortalecimiento de la "
                        "Aplicación Orgánica espera la misma separación de lotes, etiquetado y "
                        "registros trazables que mantiene para su propio cultivo.",
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
                        "Describa los edificios, plataformas o equipo usados para el manejo",
                    ),
                    coaching=text(
                        "Include every space product passes through — a wash pad, a hulling "
                        "shed, a drying yard, a cooler — and note whether the space or equipment "
                        "is shared with a nonorganic operation.",
                        "Incluya cada espacio por el que pasa el producto — una plataforma de "
                        "lavado, un galpón de descascarado, un patio de secado, una cámara fría — "
                        "e indique si el espacio o equipo se comparte con una operación no "
                        "orgánica.",
                    ),
                    nop_cite="§ 205.270",
                    compiles_to=CompileRule(
                        template="Buildings, pads, and equipment used for on-farm handling: {answer}"
                    ),
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
                    "sanitizing on the National List, used within its labeled limits (§ 205.605).",
                    "La separación física — equipo dedicado, limpieza entre corridas, días de "
                    "procesamiento de un solo producto — es la primera línea de defensa contra la "
                    "mezcla y el contacto con sustancias prohibidas en una instalación de manejo "
                    "(§ 205.272). Cuando el agua entra en contacto con el producto orgánico para "
                    "lavado o enfriado, cualquier sanitizante que se le agregue debe ser una de las "
                    "sustancias permitidas para sanitización en contacto con alimentos de la Lista "
                    "Nacional, usada dentro de sus límites indicados en la etiqueta (§ 205.605).",
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
                        "Escriba su proceso de manejo en orden, desde la cosecha hasta el envío",
                    ),
                    coaching=text(
                        "List each step as it happens — for example: harvest → haul to hulling "
                        "shed → hull → dry → bulk storage → hand-sort → pack → cold storage → "
                        "ship. This step list is the flow chart your certifier expects to see for "
                        "the handling operation.",
                        "Enumere cada paso en el orden en que ocurre — por ejemplo: cosecha → "
                        "traslado al galpón de descascarado → descascarado → secado → "
                        "almacenamiento a granel → selección manual → empacado → cámara fría → "
                        "envío. Esta lista de pasos es el diagrama de flujo que su certificador "
                        "espera ver para la operación de manejo.",
                    ),
                    nop_cite="§ 205.201(a)(1)",
                    compiles_to=CompileRule(
                        template="On-farm handling process, in order from harvest to shipment: {answer}"
                    ),
                ),
                Question(
                    key="uses_water",
                    kind="boolean",
                    label=text(
                        "Does any step use water — washing, rinsing, or hydrocooling?",
                        "¿Algún paso usa agua — lavado, enjuague o hidroenfriado?",
                    ),
                    nop_cite="§ 205.272(b)",
                    visible_when=(Condition("handling_activities", "includes_any", ("washing", "cooling")),),
                    compiles_to=CompileRule(template="Water used in washing, rinsing, or hydrocooling: {answer}."),
                ),
                Question(
                    key="water_source_sanitizer",
                    kind="textarea",
                    label=text(
                        "Describe the water source and any sanitizer added to it",
                        "Describa la fuente de agua y cualquier sanitizante que se le agregue",
                    ),
                    coaching=text(
                        "Note the source (well, municipal, pond) and, if a sanitizer is added, "
                        "the product name, concentration, and how residual levels are checked. "
                        "Only substances allowed for food-contact sanitizing on the National List "
                        "may be used, within their labeled limits (§ 205.605).",
                        "Indique la fuente (pozo, red municipal, estanque) y, si se agrega un "
                        "sanitizante, el nombre del producto, la concentración y cómo se verifican "
                        "los niveles residuales. Solo pueden usarse sustancias permitidas para "
                        "sanitización en contacto con alimentos de la Lista Nacional, dentro de "
                        "sus límites indicados en la etiqueta (§ 205.605).",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("uses_water", "truthy"),),
                    compiles_to=CompileRule(
                        template="Water source and sanitizer used in handling: {answer}",
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
                        "Las garantías vagas no son una barrera que un certificador pueda "
                        "verificar — enumere lo que realmente existe: equipo dedicado, una "
                        "bitácora de limpieza o una instalación que nunca toca producto no "
                        "orgánico.",
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
                        Option("other", text("Other (describe below)", "Otro (describa abajo)")),
                    ),
                ),
                Question(
                    key="commingling_controls_other",
                    kind="text",
                    label=text("Describe the other control", "Describa el otro control"),
                    visible_when=(Condition("commingling_controls", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Additional commingling control used: {answer}.",
                        section_key="commingling_barriers",
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
                        "¿Qué registros de manejo mantiene su operación?",
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
                Question(
                    key="facility_docs",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach a site map, process flow chart, or handling SOPs, if you have them",
                        "Adjunte un mapa del sitio, diagrama de flujo del proceso, o procedimientos "
                        "(SOP) de manejo, si los tiene",
                    ),
                    coaching=text(
                        "Not required to complete this module, but a site map or flow chart is "
                        "exactly what a certifier asks for first at an on-site handling review.",
                        "No es obligatorio para completar este módulo, pero un mapa del sitio o "
                        "diagrama de flujo es justo lo primero que pide un certificador en una "
                        "revisión de manejo en sitio.",
                    ),
                    nop_cite="§ 205.103",
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
            "La normativa de Fortalecimiento de la Aplicación Orgánica espera que cada "
            "operación conozca su cadena de suministro: verifique certificados de "
            "cualquiera a quien compre o revenda producto orgánico, y mantenga registros "
            "de venta que vinculen cada lote vendido con sus registros de cosecha.",
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
                        "Describa sus canales de venta (mayorista, directo, empacadora).",
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
                        "¿Compra o revende producto orgánico de terceros?",
                    ),
                    coaching=text(
                        "If yes, § 205.201(a)(3) expects you to describe how you verify their "
                        "organic certificate and guard against organic fraud.",
                        "Si es así, § 205.201(a)(3) espera que describa cómo verifica su "
                        "certificado orgánico y previene el fraude orgánico.",
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
                        "¿Cómo verifica los certificados orgánicos de esos proveedores, y con " "qué frecuencia?",
                    ),
                    coaching=text(
                        "Name the check and its frequency — e.g. 'certificate requested at "
                        "first purchase and re-checked each season against the USDA Organic "
                        "Integrity Database'.",
                        "Nombre la verificación y su frecuencia — ej. 'certificado solicitado "
                        "en la primera compra y revisado cada temporada contra la base USDA "
                        "Organic Integrity'.",
                    ),
                    required=True,
                    nop_cite="§ 205.201(a)(3)",
                    visible_when=(Condition("sales_soe_supplier_verification", "eq", "yes"),),
                    compiles_to=CompileRule(template="Supplier certificate verification: {answer}."),
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
                        "Adjunte un registro de venta de muestra que muestre la identificación de lote.",
                    ),
                    required=False,
                ),
            ),
        ),
    ),
)


CERTIFICATION_CONTRACT = Module(
    key="certification_contract",
    code="",
    title=text("Certification Contract", "Contrato de certificación"),
    nop_cites=("§ 205.401",),
    education=(
        text(
            "Your certifier's application asks for the legal identity behind the "
            "operation — legal name, business structure, addresses, and contacts. Trazo "
            "keeps a copy of the signed contract with your records so renewal starts "
            "from paper you already have.",
            "La solicitud de su certificador pide la identidad legal de la operación — "
            "razón social, estructura, direcciones y contactos. Trazo guarda una copia "
            "del contrato firmado con sus registros para que la renovación parta de "
            "papeles que ya tiene.",
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
                        "Razón social, estructura del negocio y cualquier diferencia de "
                        "nombre entre el certificado y sus documentos de venta.",
                    ),
                    coaching=text(
                        "Name mismatches between the certificate and an invoice are one of "
                        "the commonest audit findings — state them here rather than leaving "
                        "the inspector to discover them.",
                        "Las diferencias de nombre entre el certificado y una factura son uno "
                        "de los hallazgos de auditoría más comunes — indíquelas aquí en lugar "
                        "de dejar que el inspector las descubra.",
                    ),
                    required=True,
                    nop_cite="§ 205.401",
                    compiles_to=CompileRule(template="Legal identity and naming: {answer}."),
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
                    ),
                ),
                Question(
                    key="contract_upload",
                    kind="upload",
                    label=text(
                        "Attach the signed certification contract / client agreement.",
                        "Adjunte el contrato de certificación firmado / acuerdo de cliente.",
                    ),
                    required=False,
                ),
            ),
        ),
    ),
)
