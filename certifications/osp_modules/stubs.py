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
                        Option(
                            "pest_treatment_nonfumigation",
                            text(
                                "Fumigation-free pest treatment (e.g., freezing)",
                                "Tratamiento de plagas sin fumigación (p. ej., congelado)",
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
                        "the handling operation.",
                        "Enumera cada paso en el orden en que ocurre — por ejemplo: cosecha → traslado al galpón de "
                        "descascarado → descascarado → secado → almacenamiento a granel → selección manual → "
                        "empacado → cámara fría → envío. Esta lista de pasos es el diagrama de flujo que tu "
                        "certificador espera ver para la operación de manejo.",
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
                        template_false="Only inputs allowed in organic handling are used, whatever the crop's status.",
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
    ),
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
                        "Adjunta el contrato de certificación firmado / acuerdo de cliente.",
                    ),
                    required=False,
                ),
            ),
        ),
    ),
)
