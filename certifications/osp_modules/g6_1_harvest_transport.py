"""
G6.1 — Harvest & Transport.

Sources: 7 CFR 205.272 (commingling and contact with prohibited substance prevention practice
standard), 205.103 (recordkeeping by certified operations). Topic order follows the public
Common OSP grower template; all wording authored for Trazo.

Three pages:

A. Who harvests — the operation's own crew, a custom-hired harvester, or the buyer. A
   custom-hired harvester brings equipment from other operations onto organic fields, so that
   branch adds an equipment-cleanout check and asks how the operator is instructed.
B. Containers & handling — what touches the product at harvest, whether those containers are
   new, dedicated, or cleaned before use, the narrower case of reusing a container that once
   held a prohibited substance (§ 205.272(b)(2)), and whether the packaging itself CONTAINS a
   synthetic fungicide, preservative, or fumigant (§ 205.272(b)(1) — a flat prohibition, and a
   supplier question rather than a practice the operator can describe from memory).
C. Transport & lot identity — who moves product off the operation, whether transport units are
   inspected clean, and the lot identification that lets § 205.103(b)(2) records trace a load
   back to its field and harvest date. When the operation does not control the transport leg
   itself (a commercial carrier or the buyer picks up), it records what that carrier or
   handler provides in return.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text

G6_1_HARVEST_TRANSPORT = Module(
    key="g6_1_harvest_transport",
    code="G6.1",
    title=text("Harvest & Transport", "Cosecha y transporte"),
    nop_cites=("§ 205.272", "§ 205.103"),
    education=(
        text(
            "Management practices must prevent organic product from commingling with "
            "nonorganic product and from contacting prohibited substances at every step "
            "between harvest and sale. Containers, bins, harvest equipment, and transport "
            "units must be clean, dedicated to organic use, or otherwise protected from "
            "contamination whenever they touch organic product (§ 205.272).",
            "Las prácticas de manejo deben evitar que el producto orgánico se mezcle con "
            "producto no orgánico y que entre en contacto con sustancias prohibidas en cada "
            "paso entre la cosecha y la venta. Los contenedores, cajones, el equipo de "
            "cosecha y las unidades de transporte deben estar limpios, dedicados al uso "
            "orgánico o protegidos de otra manera contra la contaminación cada vez que tocan "
            "producto orgánico (§ 205.272).",
        ),
    ),
    allows_not_applicable=False,
    default_section_key="commingling_barriers",
    pages=(
        ModulePage(
            key="a_who_harvests",
            title=text("A. Who harvests", "A. Quién cosecha"),
            education=(
                text(
                    "Whoever physically harvests the crop — the operation's own crew, a "
                    "custom-hired operator, or the buyer — is handling organic product. A "
                    "custom harvester's equipment is a contamination pathway if it was just "
                    "used on nonorganic or prohibited-substance-treated land.",
                    "Quien cosecha físicamente el cultivo — el personal propio de la "
                    "operación, un operador contratado o el comprador — está manejando "
                    "producto orgánico. El equipo de un cosechador contratado es una vía de "
                    "contaminación si acaba de usarse en tierra no orgánica o tratada con "
                    "sustancias prohibidas.",
                ),
            ),
            questions=(
                Question(
                    key="who_harvests",
                    kind="radio",
                    label=text("Who harvests this crop?", "¿Quién cosecha este cultivo?"),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(template="Harvest is performed by: {answer}."),
                    options=(
                        Option("own_crew", text("Our own crew", "Nuestro propio personal")),
                        Option(
                            "custom_harvester",
                            text(
                                "Custom-hired harvester",
                                "Cosechador contratado (servicio externo)",
                            ),
                        ),
                        Option("buyer_harvests", text("Buyer harvests", "El comprador cosecha")),
                    ),
                ),
                Question(
                    key="custom_harvester_cleanout_verified",
                    kind="boolean",
                    label=text(
                        "Has equipment cleanout been verified before the custom harvester's "
                        "equipment enters your organic fields?",
                        "¿Se ha verificado la limpieza del equipo antes de que el equipo del "
                        "cosechador contratado ingrese a sus campos orgánicos?",
                    ),
                    coaching=text(
                        "Trazo's Equipment Cleanout activities are the per-pass evidence — "
                        "link each harvest operation to the cleaning that preceded it.",
                        "Las actividades de Limpieza de Equipo de Trazo son la evidencia de "
                        "cada pase — vincule cada operación de cosecha con la limpieza que la "
                        "precedió.",
                    ),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("who_harvests", "eq", "custom_harvester"),),
                    compiles_to=CompileRule(
                        template="Equipment cleanout verified before the custom harvester enters organic fields: {answer}."
                    ),
                ),
                Question(
                    key="custom_harvester_instructions",
                    kind="textarea",
                    label=text(
                        "Describe how the custom-hired harvester is instructed to maintain " "organic integrity",
                        "Describa cómo se instruye al cosechador contratado para mantener la " "integridad orgánica",
                    ),
                    visible_when=(Condition("who_harvests", "eq", "custom_harvester"),),
                    compiles_to=CompileRule(template="Instructions given to the custom harvest operator: {answer}"),
                ),
                Question(
                    key="custom_harvester_records",
                    kind="checkbox_group",
                    label=text(
                        "Which harvest records does the custom harvester provide for each pass?",
                        "¿Qué registros de cosecha entrega el cosechador contratado por cada pasada?",
                    ),
                    coaching=text(
                        "An uncertified harvester's records must still let your certifier "
                        "trace the harvest: date, quantity, crop, and parcel.",
                        "Los registros de un cosechador no certificado igual deben permitir "
                        "al certificador rastrear la cosecha: fecha, cantidad, cultivo y parcela.",
                    ),
                    required=False,
                    visible_when=(Condition("who_harvests", "eq", "custom_harvester"),),
                    nop_cite="§ 205.103(b)",
                    compiles_to=CompileRule(template="Custom-harvester records provided per pass: {answer}."),
                    options=(
                        Option("harvest_date", text("Harvest date", "Fecha de cosecha")),
                        Option("quantity", text("Quantity harvested", "Cantidad cosechada")),
                        Option("crop_variety", text("Crop and variety", "Cultivo y variedad")),
                        Option("parcel_field", text("Parcel / field identity", "Identidad de parcela / campo")),
                        Option(
                            "weigh_tickets",
                            text("Weigh tickets or receiving records", "Tickets de pesaje o registros de recepción"),
                        ),
                        Option(
                            "none_yet",
                            text("No records provided yet — being arranged", "Aún no entrega registros — en gestión"),
                            exclusive=True,
                        ),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_containers",
            title=text("B. Containers & handling", "B. Contenedores y manejo"),
            education=(
                text(
                    "Every container, bin, or trailer that touches the crop after harvest "
                    "must be new, dedicated to organic use, or cleaned before that use. A "
                    "container that once held a prohibited substance may be reused only after "
                    "it has been thoroughly cleaned and poses no risk of contact "
                    "(§ 205.272(b)(2)).",
                    "Todo contenedor, cajón o remolque que toque el cultivo después de la "
                    "cosecha debe ser nuevo, estar dedicado al uso orgánico o haberse "
                    "limpiado antes de ese uso. Un contenedor que alguna vez contuvo una "
                    "sustancia prohibida solo puede reutilizarse después de una limpieza "
                    "a fondo que no deje riesgo de contacto (§ 205.272(b)(2)).",
                ),
            ),
            questions=(
                Question(
                    key="container_types",
                    kind="checkbox_group",
                    label=text(
                        "What containers or bins hold the product at harvest?",
                        "¿Qué contenedores o cajones sostienen el producto en la cosecha?",
                    ),
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(template="Containers and bins used at harvest: {answer}."),
                    options=(
                        Option("field_bins", text("Field bins", "Bins de campo")),
                        Option("totes", text("Totes", "Totes (contenedores grandes)")),
                        Option("buckets", text("Buckets", "Baldes")),
                        Option("bulk_trailers", text("Bulk trailers", "Remolques a granel")),
                        Option(
                            "reusable_lugs",
                            text("Reusable lugs", "Cajas reutilizables (lugs)"),
                        ),
                        Option(
                            "single_use_cartons",
                            text("Single-use cartons", "Cartones desechables (un solo uso)"),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describa abajo)")),
                    ),
                ),
                Question(
                    key="container_types_other",
                    kind="text",
                    label=text(
                        "Describe the other container type",
                        "Describa el otro tipo de contenedor",
                    ),
                    visible_when=(Condition("container_types", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional container type used: {answer}."),
                ),
                # 🔴 This was ONE boolean — "are these containers new, dedicated to organic use,
                # OR cleaned before each use?" — answered once across every container type
                # ticked above, and compiled as an affirmative covering all three predicates. On
                # the pilot a single "Yes" spoke for reusable lugs, single-use cartons and totes
                # while the description substantiated only the lugs: the plan asserted more than
                # the operator had said. WSDA J5 asks exactly this as a four-way checkbox, and
                # CCOF G6.1 B1 as a per-item table.
                #
                # The old key is deliberately NOT reused. A stored `True` does not say WHICH
                # safeguard applies — that missing information IS the defect — so migration 0036
                # clears it rather than guessing, and the question reads as unanswered until the
                # operator says which. (`_module_status` recomputes against the current
                # questionnaire, so those plans correctly show as in progress again.)
                Question(
                    key="container_safeguards",
                    kind="checkbox_group",
                    label=text(
                        "How do you keep harvest containers from contaminating organic crops?",
                        "\u00bfC\u00f3mo evita que los contenedores de cosecha contaminen los cultivos "
                        "org\u00e1nicos?",
                    ),
                    coaching=text(
                        "Tick every safeguard you rely on. If different container types are "
                        "handled differently — new cartons but reused lugs — say so in the "
                        "description below, because your certifier reads this as a statement "
                        "about every container named above.",
                        "Marque cada salvaguarda en la que se apoya. Si distintos tipos de "
                        "contenedor se manejan de forma diferente \u2014 cartones nuevos pero cajas "
                        "reutilizadas \u2014 ind\u00edquelo en la descripci\u00f3n de abajo, porque su "
                        "certificador lo lee como una afirmaci\u00f3n sobre todos los contenedores "
                        "nombrados arriba.",
                    ),
                    nop_cite="\u00a7 205.272(a)",
                    compiles_to=CompileRule(template="Harvest-container safeguards used: {answer}."),
                    options=(
                        Option(
                            "cleaned_prior",
                            text("Cleaned prior to use", "Se limpian antes de usarse"),
                        ),
                        Option(
                            "lined_prior",
                            text("Lined prior to use", "Se forran antes de usarse"),
                        ),
                        Option(
                            "only_new",
                            text("Only new containers are used", "Solo se usan contenedores nuevos"),
                        ),
                        Option(
                            "organic_only",
                            text(
                                "Dedicated to organic product only",
                                "Dedicados \u00fanicamente a producto org\u00e1nico",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="containers_cleaning_method",
                    kind="textarea",
                    label=text(
                        "Describe the cleaning or lining method, and which container types it " "applies to",
                        "Describa el m\u00e9todo de limpieza o forrado, y a qu\u00e9 tipos de contenedor " "se aplica",
                    ),
                    visible_when=(Condition("container_safeguards", "includes_any", ["cleaned_prior", "lined_prior"]),),
                    compiles_to=CompileRule(template="Container cleaning or lining method: {answer}"),
                ),
                Question(
                    key="containers_reused_from_prohibited",
                    kind="boolean",
                    label=text(
                        "Have you ever reused a container, bin, or bulk trailer that "
                        "previously held a prohibited substance (pesticide, fertilizer, "
                        "fuel, or another nonorganic-only material) for organic product?",
                        "¿Alguna vez ha reutilizado para producto orgánico un contenedor, "
                        "cajón o remolque a granel que antes contuvo una sustancia prohibida "
                        "(pesticida, fertilizante, combustible u otro material exclusivamente "
                        "no orgánico)?",
                    ),
                    coaching=text(
                        "§ 205.272(b)(2) forbids reusing a container for organic product "
                        "when the reuse would compromise its organic integrity. The clause "
                        "allows exactly one route back: the container must have been "
                        "THOROUGHLY CLEANED and pose no risk of contact. A liner or other "
                        "barrier over an uncleaned container is not an alternative to that.",
                        "El § 205.272(b)(2) prohíbe reutilizar un contenedor para producto "
                        "orgánico cuando la reutilización comprometa su integridad orgánica. "
                        "La norma permite una sola vía: el contenedor debe haberse LIMPIADO A "
                        "FONDO y no presentar riesgo de contacto. Un forro u otra barrera "
                        "sobre un contenedor sin limpiar no sustituye esa limpieza.",
                    ),
                    # (b)(1) is the packaging-COMPOSITION prohibition, asked separately below;
                    # (b)(2) is REUSE, which is what this question is about. The two were
                    # conflated here, so the module cited a clause it did not implement while
                    # the clause it did implement went uncited.
                    nop_cite="§ 205.272(b)(2)",
                    compiles_to=CompileRule(
                        template=(
                            "Containers that previously held a prohibited substance are ever "
                            "reused for organic product: {answer}."
                        )
                    ),
                ),
                Question(
                    key="containers_reused_barrier",
                    kind="textarea",
                    label=text(
                        "How is the container thoroughly cleaned before reuse, and how do you "
                        "confirm it poses no risk of contact?",
                        "¿Cómo se limpia a fondo el contenedor antes de reutilizarlo, y cómo "
                        "confirma que no presenta riesgo de contacto?",
                    ),
                    visible_when=(Condition("containers_reused_from_prohibited", "truthy"),),
                    compiles_to=CompileRule(template="Cleaning verified before reuse: {answer}"),
                ),
                # § 205.272(b)(1) — the packaging-COMPOSITION prohibition. Distinct from
                # reuse above: this one is about what the container is MADE WITH, and it is
                # a flat prohibition, not a practice to describe. A grower cannot answer it
                # from memory of their own operation — it is a supplier question, which is
                # why the middle option exists.
                Question(
                    key="packaging_free_of_prohibited",
                    kind="radio",
                    label=text(
                        "Are your packaging materials, storage containers, and bins free of "
                        "synthetic fungicides, preservatives, and fumigants?",
                        "¿Sus materiales de empaque, contenedores de almacenamiento y cajones "
                        "están libres de fungicidas, conservantes y fumigantes sintéticos?",
                    ),
                    coaching=text(
                        "§ 205.272(b)(1) prohibits outright the use of packaging materials, "
                        "storage containers, or bins that CONTAIN a synthetic fungicide, "
                        "preservative, or fumigant — treated wooden bins and fungicide-"
                        "impregnated liners are the usual cases. This is a supplier question: "
                        "if you have not confirmed it in writing, say so rather than guessing. "
                        "An unconfirmed answer is a task for your certifier review; a wrong "
                        "'yes' is a misstatement in your organic system plan.",
                        "El § 205.272(b)(1) prohíbe de plano el uso de materiales de empaque, "
                        "contenedores de almacenamiento o cajones que CONTENGAN un fungicida, "
                        "conservante o fumigante sintético — los cajones de madera tratada y "
                        "los forros impregnados con fungicida son los casos habituales. Esta "
                        "es una pregunta para su proveedor: si no lo ha confirmado por "
                        "escrito, indíquelo en lugar de suponer. Una respuesta sin confirmar "
                        "es una tarea para la revisión de su certificadora; un 'sí' erróneo es "
                        "una declaración falsa en su plan orgánico.",
                    ),
                    nop_cite="§ 205.272(b)(1)",
                    options=(
                        Option(
                            "confirmed",
                            text(
                                "Yes — confirmed with the supplier or from product documentation",
                                "Sí — confirmado con el proveedor o mediante documentación del producto",
                            ),
                        ),
                        Option(
                            "unconfirmed",
                            text(
                                "Believed free of them, but not yet confirmed in writing",
                                "Se cree que están libres, pero aún no se ha confirmado por escrito",
                            ),
                        ),
                        Option(
                            "no",
                            text(
                                "No — some packaging or containers contain one of these",
                                "No — algún empaque o contenedor contiene alguno de estos",
                            ),
                        ),
                    ),
                    compiles_to=CompileRule(
                        template=(
                            "Packaging materials, storage containers, and bins free of "
                            "synthetic fungicides, preservatives, and fumigants: {answer}."
                        )
                    ),
                ),
                Question(
                    key="packaging_prohibited_detail",
                    kind="textarea",
                    label=text(
                        "Which packaging or containers, and what is your plan to replace or " "confirm them?",
                        "¿Qué empaques o contenedores, y cuál es su plan para reemplazarlos o " "confirmarlos?",
                    ),
                    visible_when=(Condition("packaging_free_of_prohibited", "one_of", ["unconfirmed", "no"]),),
                    compiles_to=CompileRule(template="Packaging awaiting confirmation or replacement: {answer}"),
                ),
            ),
        ),
        ModulePage(
            key="c_transport",
            title=text("C. Transport & lot identity", "C. Transporte e identidad de lote"),
            education=(
                text(
                    "Transport is the last point where organic product can be contaminated "
                    "or lose its identity before sale. Whoever drives it off the operation, "
                    "the unit must be clean and the load must carry the lot identification "
                    "that ties it back to the field and harvest date.",
                    "El transporte es el último punto donde el producto orgánico puede "
                    "contaminarse o perder su identidad antes de la venta. Sin importar quién "
                    "lo transporte fuera de la operación, la unidad debe estar limpia y la "
                    "carga debe llevar la identificación de lote que la vincule con el campo "
                    "y la fecha de cosecha.",
                ),
            ),
            questions=(
                Question(
                    key="who_transports",
                    kind="radio",
                    label=text(
                        "Who transports this product off the operation?",
                        "¿Quién transporta este producto fuera de la operación?",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(template="Product is transported off the operation by: {answer}."),
                    options=(
                        Option("own_vehicles", text("Our own vehicles", "Nuestros propios vehículos")),
                        Option("commercial_carrier", text("Commercial carrier", "Transportista comercial")),
                        Option(
                            "buyer_pickup",
                            text("Buyer pickup", "Recolección por el comprador"),
                        ),
                    ),
                ),
                Question(
                    key="transport_units_inspected_clean",
                    kind="boolean",
                    label=text(
                        "Are transport units inspected clean before loading organic product?",
                        "¿Se inspeccionan las unidades de transporte para verificar que estén "
                        "limpias antes de cargar producto orgánico?",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="Transport units are inspected clean before loading organic product: {answer}."
                    ),
                ),
                Question(
                    key="lot_identification_on_every_load",
                    kind="boolean",
                    label=text(
                        "Does every load leave with lot identification tying it to the field " "and harvest date?",
                        "¿Toda carga sale con una identificación de lote que la vincula con "
                        "el campo y la fecha de cosecha?",
                    ),
                    coaching=text(
                        "Trazo lot tags carry the parcel and harvest date automatically — "
                        "§ 205.103(b)(2) requires records that track product from the field "
                        "to the point of sale.",
                        "Las etiquetas de lote de Trazo llevan automáticamente la parcela y "
                        "la fecha de cosecha — el § 205.103(b)(2) exige registros que "
                        "rastreen el producto desde el campo hasta el punto de venta.",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(
                        template=(
                            "Every load leaves the operation with lot identification tying it "
                            "to the field and harvest date: {answer}."
                        )
                    ),
                ),
                Question(
                    key="non_own_transport_records",
                    kind="textarea",
                    label=text(
                        "What records does the carrier or handler provide for each load?",
                        "¿Qué registros proporciona el transportista o manejador por cada " "carga?",
                    ),
                    coaching=text(
                        "For example, a clean-truck affidavit or a bill of lading that "
                        "carries the lot identification.",
                        "Por ejemplo, una declaración jurada de camión limpio o una guía de "
                        "embarque (bill of lading) que lleve la identificación de lote.",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("who_transports", "one_of", ["commercial_carrier", "buyer_pickup"]),),
                    compiles_to=CompileRule(
                        template="Records provided by the carrier or handler transporting product off the operation: {answer}"
                    ),
                ),
            ),
        ),
        ModulePage(
            key="d_off_farm_handling",
            title=text("D. Off-farm handling", "D. Manejo fuera de la finca"),
            education=(
                text(
                    "If anyone off your operation hulls, dries, packs, conditions or "
                    "otherwise handles your crop, the certifier needs to know who they are "
                    "and whether they are certified — because from that point the audit "
                    "trail runs through their records, not yours. Answering \u201cno\u201d here is a "
                    "complete answer; leaving it blank is not, because a reviewer cannot "
                    "tell the difference between \u201cnobody handles our crop\u201d and "
                    "\u201cnot filled in yet\u201d.",
                    "Si alguien fuera de su operaci\u00f3n descascara, seca, empaca, acondiciona o "
                    "de otro modo manipula su cultivo, el certificador necesita saber qui\u00e9n es "
                    "y si est\u00e1 certificado, porque desde ese punto el rastro de auditor\u00eda pasa "
                    "por sus registros y no por los suyos. Responder \u201cno\u201d aqu\u00ed es una "
                    "respuesta completa; dejarlo en blanco no lo es, porque quien revisa no "
                    "puede distinguir entre \u201cnadie manipula nuestro cultivo\u201d y \u201ca\u00fan no se "
                    "ha completado\u201d.",
                ),
            ),
            questions=(
                Question(
                    key="handled_by_another_operation",
                    kind="radio",
                    label=text(
                        "Is your organic crop handled off the farm by another operation?",
                        "\u00bfSu cultivo org\u00e1nico es manipulado fuera de la finca por otra " "operaci\u00f3n?",
                    ),
                    nop_cite="\u00a7 205.272(a)",
                    compiles_to=CompileRule(template="Off-farm handling of this operation's organic crop: {answer}."),
                    options=(
                        Option(
                            "no",
                            text(
                                "No \u2014 nobody off this operation handles our crop",
                                "No \u2014 nadie fuera de esta operaci\u00f3n manipula nuestro cultivo",
                            ),
                        ),
                        Option(
                            "yes_certified",
                            text(
                                "Yes \u2014 by a certified organic operation",
                                "S\u00ed \u2014 por una operaci\u00f3n org\u00e1nica certificada",
                            ),
                        ),
                        Option(
                            "yes_uncertified",
                            text(
                                "Yes \u2014 by an operation that is not certified",
                                "S\u00ed \u2014 por una operaci\u00f3n que no est\u00e1 certificada",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="off_farm_handler_table",
                    kind="info",
                    required=False,
                    embed="post_harvest_facilities",
                    label=text(
                        "Handlers on file for this operation",
                        "Manejadores registrados para esta operaci\u00f3n",
                    ),
                    coaching=text(
                        "These are the facilities recorded on your farm profile. Each one "
                        "prints here with its address and its organic certificate, so the "
                        "reviewer sees the same handler in the plan and in the records.",
                        "Estas son las instalaciones registradas en el perfil de su finca. "
                        "Cada una aparece aqu\u00ed con su direcci\u00f3n y su certificado org\u00e1nico, "
                        "para que quien revisa vea el mismo manejador en el plan y en los "
                        "registros.",
                    ),
                    nop_cite="\u00a7 205.272(a)",
                    visible_when=(
                        Condition("handled_by_another_operation", "one_of", ["yes_certified", "yes_uncertified"]),
                    ),
                ),
                Question(
                    key="uncertified_handler_records",
                    kind="textarea",
                    label=text(
                        "What records does that operation provide to preserve your product's " "organic identity?",
                        "\u00bfQu\u00e9 registros proporciona esa operaci\u00f3n para preservar la "
                        "identidad org\u00e1nica de su producto?",
                    ),
                    coaching=text(
                        "An uncertified operation handling your crop needs records proving "
                        "identity preservation \u2014 lot tags, logs showing physical or timing "
                        "separation from nonorganic product, and cleaning records for the "
                        "equipment and space used.",
                        "Una operaci\u00f3n no certificada que manipula su cultivo necesita "
                        "registros que demuestren la preservaci\u00f3n de la identidad \u2014 "
                        "etiquetas de lote, bit\u00e1coras que muestren separaci\u00f3n f\u00edsica o "
                        "temporal del producto no org\u00e1nico, y registros de limpieza del "
                        "equipo y el espacio utilizados.",
                    ),
                    nop_cite="\u00a7 205.103",
                    visible_when=(Condition("handled_by_another_operation", "one_of", ["yes_uncertified"]),),
                    compiles_to=CompileRule(
                        template="Records provided by the uncertified operation handling this crop: {answer}"
                    ),
                ),
            ),
        ),
    ),
)
