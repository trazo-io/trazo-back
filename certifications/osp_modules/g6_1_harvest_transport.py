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
                # Checkbox since 2026.10.25: WSDA AGR 2121 §J1 and CCOF G6.1 A1 both say "all that
                # apply" (an own crew and a custom harvester on the same orchard is ordinary). The
                # stored single answers were wrapped in a list by migration, never remapped.
                Question(
                    key="who_harvests",
                    kind="checkbox_group",
                    label=text(
                        "Who harvests this crop? Check all that apply.",
                        "¿Quién cosecha este cultivo? Marca todas las que correspondan.",
                    ),
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
                        Option(
                            "buyer_harvests",
                            text("Buyer or customer harvests", "El comprador o cliente cosecha"),
                        ),
                        Option(
                            "processor_harvests",
                            text("Processor or packer harvests", "El procesador o empacador cosecha"),
                        ),
                        Option("other_harvester", text("Other", "Otro")),
                        Option(
                            "sold_standing",
                            text(
                                "The buyer of the standing crop, or whoever the buyer hires "
                                "(we sell it in the field and do not harvest)",
                                "El comprador del cultivo en pie, o quien el comprador contrate "
                                "(lo vendemos en el campo y no cosechamos)",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="who_harvests_other",
                    kind="text",
                    label=text("Who else harvests?", "¿Quién más cosecha?"),
                    visible_when=(Condition("who_harvests", "includes", "other_harvester"),),
                    compiles_to=CompileRule(template="Harvest is also performed by: {answer}."),
                ),
                # CCOF G6.1 A1 asks a crop sold "in the field" to be described too; `sold_standing` is
                # exclusive, so it can never open `who_harvests_other`.
                Question(
                    key="sold_standing_details",
                    kind="textarea",
                    label=text(
                        "Describe the sale: who buys the standing crop, and who harvests and hauls it?",
                        "Describe la venta: ¿quién compra el cultivo en pie, y quién lo cosecha y lo transporta?",
                    ),
                    visible_when=(Condition("who_harvests", "includes", "sold_standing"),),
                    compiles_to=CompileRule(template="Crop sold standing in the field: {answer}."),
                ),
                Question(
                    key="custom_harvester_cleanout_verified",
                    kind="boolean",
                    label=text(
                        "Has equipment cleanout been verified before the custom harvester's "
                        "equipment enters your organic fields?",
                        "¿Se ha verificado la limpieza del equipo antes de que el equipo del cosechador contratado "
                        "ingrese a tus campos orgánicos?",
                    ),
                    coaching=text(
                        "Trazo's Equipment Cleanout activities are the per-pass evidence — "
                        "link each harvest operation to the cleaning that preceded it.",
                        "Las actividades de Limpieza de Equipo de Trazo son la evidencia de cada pase — vincula "
                        "cada operación de cosecha con la limpieza que la precedió.",
                    ),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("who_harvests", "includes", "custom_harvester"),),
                    compiles_to=CompileRule(
                        template="Equipment cleanout verified before the custom harvester enters organic fields: {answer}."
                    ),
                ),
                Question(
                    key="custom_harvester_instructions",
                    kind="textarea",
                    label=text(
                        "Describe how the custom-hired harvester is instructed to maintain " "organic integrity",
                        "Describe cómo se instruye al cosechador contratado para mantener la integridad orgánica",
                    ),
                    visible_when=(Condition("who_harvests", "includes", "custom_harvester"),),
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
                    visible_when=(Condition("who_harvests", "includes", "custom_harvester"),),
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
                # WSDA AGR 2121 §J3.
                Question(
                    key="harvest_method",
                    kind="checkbox_group",
                    label=text(
                        "How is the crop harvested? Check all that apply.",
                        "¿Cómo se cosecha el cultivo? Marca todas las que correspondan.",
                    ),
                    required=False,
                    compiles_to=CompileRule(template="Harvest method: {answer}."),
                    options=(
                        Option("by_hand", text("By hand", "A mano")),
                        Option("mechanical", text("Mechanical", "Mecánica")),
                        Option("other", text("Other", "Otra")),
                    ),
                ),
                # WSDA AGR 2121 §J2, asked of every operation (not only a custom harvester's):
                # every harvest leaves records the certifier traces, whoever picks.
                Question(
                    key="harvest_records_kept",
                    kind="checkbox_group",
                    label=text(
                        "Which harvest records are kept for each harvest?",
                        "¿Qué registros de cosecha se guardan de cada cosecha?",
                    ),
                    required=False,
                    nop_cite="§ 205.103(b)",
                    visible_when=(Condition("who_harvests", "not_includes", "sold_standing"),),
                    compiles_to=CompileRule(template="Harvest records kept for each harvest: {answer}."),
                    options=(
                        Option("harvest_date", text("Harvest date", "Fecha de cosecha")),
                        Option("quantity", text("Quantity harvested", "Cantidad cosechada")),
                        Option("crop_variety", text("Crop and variety", "Cultivo y variedad")),
                        Option("parcel_field", text("Parcel, field or block", "Parcela, campo o cuartel")),
                        Option("lot_number", text("Harvest lot number", "Número de lote de cosecha")),
                        Option(
                            "weigh_tickets",
                            text("Weigh tickets or receiving records", "Tickets de pesaje o registros de recepción"),
                        ),
                        Option("other", text("Other", "Otros")),
                    ),
                ),
                # CCOF G6.1 A3: who generates the records of harvest and transport done by others.
                Question(
                    key="harvest_transport_records_source",
                    kind="checkbox_group",
                    label=text(
                        "Who generates the harvest and transport records? Check all that apply.",
                        "¿Quién genera los registros de cosecha y transporte? Marca todas las que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.103(b)",
                    compiles_to=CompileRule(template="Harvest and transport records are generated by: {answer}."),
                    options=(
                        Option("we_generate", text("We generate them", "Los generamos nosotros")),
                        Option(
                            "contractor_provides",
                            text(
                                "The harvester or carrier provides them to us",
                                "El cosechador o transportista nos los entrega",
                            ),
                        ),
                        Option(
                            "handler_obtains",
                            text(
                                "Our organic handler or buyer obtains them",
                                "Nuestro manipulador orgánico o comprador los obtiene",
                            ),
                        ),
                        Option("other", text("Other", "Otro")),
                        Option(
                            "not_applicable",
                            text(
                                "Not applicable: no one else harvests or transports our crop",
                                "No aplica: nadie más cosecha ni transporta nuestro cultivo",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                # WSDA AGR 2121 §I3, I3a: production work done for the operation by others.
                Question(
                    key="third_party_activities",
                    kind="checkbox_group",
                    label=text(
                        "Which production work do other companies do for you? Check all that apply.",
                        "¿Qué trabajos de producción hacen otras empresas por ti? Marca todos los que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(template="Production work done for the operation by others: {answer}."),
                    options=(
                        Option("harvest", text("Custom harvest", "Cosecha contratada")),
                        Option("planting", text("Custom planting", "Plantación contratada")),
                        Option(
                            "material_application",
                            text("Material application", "Aplicación de insumos"),
                        ),
                        Option("pest_control", text("Pest control", "Control de plagas")),
                        Option("transport", text("Transportation", "Transporte")),
                        Option("other", text("Other", "Otro")),
                        Option("none", text("None", "Ninguno"), exclusive=True),
                    ),
                ),
                # WSDA AGR 2121 §I3b.
                Question(
                    key="third_party_equipment_controls",
                    kind="checkbox_group",
                    label=text(
                        "How do you keep their equipment from contaminating your organic crops? Check all that apply.",
                        "¿Cómo evitas que su equipo contamine tus cultivos orgánicos? Marca todas las que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.272(a)",
                    visible_when=(
                        Condition(
                            "third_party_activities",
                            "includes_any",
                            ["harvest", "planting", "material_application", "pest_control", "transport", "other"],
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Controls on equipment others bring onto the operation: {answer}."
                    ),
                    options=(
                        Option("inspect", text("We inspect it before use", "Lo inspeccionamos antes de usarlo")),
                        Option("cleaned", text("It is cleaned before use", "Se limpia antes de usarlo")),
                        Option(
                            "review_records",
                            text("We review their cleaning records", "Revisamos sus registros de limpieza"),
                        ),
                        Option(
                            "sop", text("They follow our written procedure", "Siguen nuestro procedimiento escrito")
                        ),
                        Option(
                            "dedicated",
                            text(
                                "Their equipment is dedicated to organic use",
                                "Su equipo es exclusivo para uso orgánico",
                            ),
                        ),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                # WSDA AGR 2121 §I3c.
                Question(
                    key="third_party_cleaning_documentation",
                    kind="checkbox_group",
                    label=text(
                        "What documentation do you keep of their equipment cleaning?",
                        "¿Qué documentación guardas de la limpieza de su equipo?",
                    ),
                    required=False,
                    nop_cite="§ 205.103",
                    visible_when=(
                        Condition(
                            "third_party_activities",
                            "includes_any",
                            ["harvest", "planting", "material_application", "pest_control", "transport", "other"],
                        ),
                    ),
                    compiles_to=CompileRule(template="Documentation kept of others' equipment cleaning: {answer}."),
                    options=(
                        Option(
                            "affidavits", text("Clean equipment affidavits", "Declaraciones juradas de equipo limpio")
                        ),
                        Option("cleanout_records", text("Clean-out records", "Registros de limpieza")),
                        Option("sop", text("A written cleaning procedure", "Un procedimiento escrito de limpieza")),
                        Option("other", text("Other", "Otra")),
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
                        # Retired 2026.10.25: WSDA §J4 and §J8 separate wooden from plastic bins (only
                        # a non-dedicated WOODEN bin raises J8). An answer of only this reads as given
                        # and asks the operator to say which.
                        Option("field_bins", text("Field bins", "Bins de campo"), retired=True),
                        Option("wooden_bins", text("Wooden bins", "Bins de madera")),
                        Option("plastic_bins", text("Plastic bins", "Bins de plástico")),
                        Option("picking_bags", text("Picking bags", "Bolsas de cosecha")),
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
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="container_types_other",
                    kind="text",
                    label=text(
                        "Describe the other container type",
                        "Describe el otro tipo de contenedor",
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
                        "¿Cómo evitas que los contenedores de cosecha contaminen los cultivos orgánicos?",
                    ),
                    coaching=text(
                        "Tick every safeguard you rely on. If different container types are "
                        "handled differently — new cartons but reused lugs — say so in the "
                        "description below, because your certifier reads this as a statement "
                        "about every container named above.",
                        "Marca cada salvaguarda en la que te apoyas. Si distintos tipos de contenedor se manejan de "
                        "forma diferente — cartones nuevos pero cajas reutilizadas — indícalo en la descripción de "
                        "abajo, porque tu certificador lo lee como una afirmación sobre todos los contenedores "
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
                        "Describe el método de limpieza o forrado, y a qué tipos de contenedor se aplica",
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
                        "¿Cómo se limpia a fondo el contenedor antes de reutilizarlo, y cómo confirmas que no "
                        "presenta riesgo de contacto?",
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
                        "¿Tus materiales de empaque, contenedores de almacenamiento y cajones están libres de "
                        "fungicidas, conservantes y fumigantes sintéticos?",
                    ),
                    coaching=text(
                        "§ 205.272(b)(1) prohibits outright the use of packaging materials, "
                        "storage containers, or bins that CONTAIN a synthetic fungicide, "
                        "preservative, or fumigant — treated wooden bins and fungicide-"
                        "impregnated liners are the usual cases. This is a supplier question: "
                        "if you have not confirmed it in writing, say so rather than guessing. "
                        "An unconfirmed answer is a task for your certifier review; a wrong "
                        "'yes' is a misstatement in your organic system plan.",
                        "El § 205.272(b)(1) prohíbe de plano el uso de materiales de empaque, contenedores de "
                        "almacenamiento o cajones que CONTENGAN un fungicida, conservante o fumigante sintético — "
                        "los cajones de madera tratada y los forros impregnados con fungicida son los casos "
                        "habituales. Esta es una pregunta para tu proveedor: si no lo has confirmado por escrito, indícalo en lugar de suponer. Una respuesta sin confirmar es una tarea para la revisión de "
                        "tu certificadora; un 'sí' erróneo es una declaración falsa en tu plan orgánico.",
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
                        "¿Qué empaques o contenedores, y cuál es tu plan para reemplazarlos o confirmarlos?",
                    ),
                    visible_when=(Condition("packaging_free_of_prohibited", "one_of", ["unconfirmed", "no"]),),
                    compiles_to=CompileRule(template="Packaging awaiting confirmation or replacement: {answer}"),
                ),
                # WSDA AGR 2121 §J6 (and §L16 for packaging).
                Question(
                    key="harvest_container_material",
                    kind="checkbox_group",
                    label=text(
                        "What are your harvest containers made of? Check all that apply.",
                        "¿De qué material son tus contenedores de cosecha? Marca todos los que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(template="Harvest container materials: {answer}."),
                    options=(
                        Option("plastic", text("Plastic", "Plástico")),
                        Option("metal", text("Metal", "Metal")),
                        Option("cloth", text("Cloth", "Tela")),
                        Option("wood", text("Wood", "Madera")),
                        Option("cardboard", text("Cardboard", "Cartón")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                # WSDA AGR 2121 §J5a / §J7b: the records that show containers were cleaned.
                Question(
                    key="container_cleaning_records",
                    kind="checkbox_group",
                    label=text(
                        "What records show your harvest containers are cleaned? Check all that apply.",
                        "¿Qué registros muestran que tus contenedores de cosecha se limpian? Marca todos los que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.103",
                    visible_when=(Condition("container_safeguards", "includes", "cleaned_prior"),),
                    compiles_to=CompileRule(template="Records that show harvest containers are cleaned: {answer}."),
                    options=(
                        Option(
                            "cleaning_logs",
                            text("Cleaning logs", "Registros de limpieza"),
                            evidence="harvest_bin_cleanouts",
                        ),
                        Option(
                            "sop_attached",
                            text("A written procedure (attached below)", "Un procedimiento escrito (adjunto abajo)"),
                            requires_upload="container_cleaning_sop_upload",
                        ),
                        Option("other", text("Other", "Otros")),
                    ),
                ),
                Question(
                    key="container_cleaning_sop_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach your container cleaning procedure",
                        "Adjunta tu procedimiento de limpieza de contenedores",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("container_cleaning_records", "includes", "sop_attached"),),
                ),
                # WSDA AGR 2121 §J7.
                Question(
                    key="harvest_containers_stamped_organic",
                    kind="radio",
                    label=text(
                        "Are your harvest containers permanently and clearly stamped organic?",
                        "¿Tus contenedores de cosecha están marcados como orgánicos de forma permanente y clara?",
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(
                        template="Harvest containers permanently and clearly stamped organic: {answer}."
                    ),
                    options=(
                        Option("all", text("All of them", "Todos")),
                        Option("some", text("Some of them", "Algunos")),
                        Option("none", text("None", "Ninguno")),
                    ),
                ),
                # WSDA AGR 2121 §J7a and §L17; OTCO C7 7.9-5 / 7.9-6 (reused packaging). A NEW question:
                # `containers_reused_from_prohibited` keeps its § 205.272(b)(2) meaning and answers.
                Question(
                    key="unstamped_container_safeguards",
                    kind="checkbox_group",
                    label=text(
                        "How are containers that are not stamped organic kept from contaminating the crop? "
                        "Check all that apply.",
                        "¿Cómo evitas que los contenedores no marcados como orgánicos contaminen el cultivo? "
                        "Marca todas las que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                    visible_when=(Condition("harvest_containers_stamped_organic", "one_of", ["some", "none"]),),
                    compiles_to=CompileRule(template="Safeguards for containers not stamped organic: {answer}."),
                    options=(
                        Option(
                            "cleaned_after_nonorganic",
                            text(
                                "Plastic, metal or cloth containers are cleaned after non-organic use",
                                "Los de plástico, metal o tela se limpian después de un uso no orgánico",
                            ),
                        ),
                        Option(
                            "cardboard_not_exposed",
                            text(
                                "Cardboard was never exposed to non-organic product or prohibited substances",
                                "El cartón nunca estuvo expuesto a producto no orgánico ni a sustancias prohibidas",
                            ),
                        ),
                        Option(
                            "wood_fully_lined",
                            text("Wooden containers are fully lined", "Los de madera van totalmente forrados"),
                        ),
                        Option("new_only", text("Only new containers are used", "Solo se usan contenedores nuevos")),
                        Option("other", text("Other", "Otra")),
                    ),
                ),
                # WSDA AGR 2121 §J8 (§ 205.272(b)(2)): a tree fruit grower receiving non-dedicated
                # wooden bins from a packer or processor.
                Question(
                    key="receives_nondedicated_wood_bins",
                    kind="boolean",
                    label=text(
                        "Do you receive wooden bins from a packer or processor that are also used for "
                        "non-organic fruit?",
                        "¿Recibes bins de madera de un empacador o procesador que también se usan para "
                        "fruta no orgánica?",
                    ),
                    required=False,
                    nop_cite="§ 205.272(b)(2)",
                    visible_when=(Condition("container_types", "includes", "wooden_bins"),),
                    compiles_to=CompileRule(
                        template="Wooden bins also used for non-organic fruit are received from a packer or processor: {answer}."
                    ),
                ),
                # WSDA §J8a. The grower cannot see the packer's dump tank, so this is asked as what is
                # known, never as a required Yes.
                Question(
                    key="handler_bin_practice",
                    kind="radio",
                    label=text(
                        "Do those bins never enter the packer's dump tank, and are they fully lined "
                        "before organic fruit goes in?",
                        "¿Esos bins nunca entran al tanque de vaciado del empacador, y se forran por "
                        "completo antes de poner fruta orgánica?",
                    ),
                    required=False,
                    nop_cite="§ 205.272(b)(2)",
                    visible_when=(Condition("receives_nondedicated_wood_bins", "truthy"),),
                    compiles_to=CompileRule(
                        template="Non-dedicated wooden bins never enter the packer's dump tank and are fully lined: {answer}."
                    ),
                    options=(
                        Option(
                            "confirmed",
                            text(
                                "Yes, confirmed in writing by the packer or processor",
                                "Sí, confirmado por escrito por el empacador o procesador",
                            ),
                        ),
                        Option(
                            "unconfirmed",
                            text(
                                "We believe so, but it is not confirmed in writing",
                                "Creemos que sí, pero no está confirmado por escrito",
                            ),
                            review=(
                                "The operator believes these non-dedicated wooden bins stay out of the "
                                "packer's dump tank and are fully lined, but has no written confirmation "
                                "from the packer or processor (§ 205.272(b)(2))."
                            ),
                        ),
                        Option(
                            "no",
                            text("No", "No"),
                            review=(
                                "Non-dedicated wooden bins that enter a dump tank or are not fully lined "
                                "can carry residues from non-organic fruit (§ 205.272(b)(2))."
                            ),
                        ),
                    ),
                ),
                # WSDA §J8b.
                Question(
                    key="handler_bin_documentation_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach the packer's or processor's documentation of how the bins are handled",
                        "Adjunta la documentación del empacador o procesador sobre cómo se manejan los bins",
                    ),
                    nop_cite="§ 205.272(b)(2)",
                    visible_when=(Condition("receives_nondedicated_wood_bins", "truthy"),),
                ),
                # An inspector's question on no registered form: empty bins stacked in or beside an
                # orchard between seasons are exposed to drift from neighbouring sprays.
                Question(
                    key="empty_bin_storage",
                    kind="textarea",
                    label=text(
                        "Where are empty bins kept between harvests, and how are they protected from "
                        "drift or contamination?",
                        "¿Dónde se guardan los bins vacíos entre cosechas, y cómo se protegen de la "
                        "deriva o la contaminación?",
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                    visible_when=(
                        Condition("container_types", "includes_any", ["wooden_bins", "plastic_bins", "field_bins"]),
                    ),
                    compiles_to=CompileRule(template="Empty bins between harvests: {answer}"),
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
                # Checkbox since 2026.10.25: WSDA AGR 2121 §J10 and CCOF G6.1 A2 both say "all that
                # apply". Stored single answers were wrapped in a list by migration.
                Question(
                    key="who_transports",
                    kind="checkbox_group",
                    label=text(
                        "Who transports this product off the operation? Check all that apply.",
                        "¿Quién transporta este producto fuera de la operación? Marca todas las que correspondan.",
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
                        Option("broker", text("A broker arranges it", "Un corredor lo organiza")),
                        Option(
                            "warehouse_packer",
                            text("Warehouse or packer", "Almacén o empacador"),
                        ),
                        Option("other_transporter", text("Other", "Otro")),
                    ),
                ),
                Question(
                    key="who_transports_other",
                    kind="text",
                    label=text("Who else transports it?", "¿Quién más lo transporta?"),
                    visible_when=(Condition("who_transports", "includes", "other_transporter"),),
                    compiles_to=CompileRule(template="Product is also transported by: {answer}."),
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
                    visible_when=(
                        Condition(
                            "who_transports",
                            "includes_any",
                            ["commercial_carrier", "buyer_pickup", "broker", "warehouse_packer", "other_transporter"],
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Records provided by the carrier or handler transporting product off the operation: {answer}"
                    ),
                ),
                # CCOF G6.1 A2: a carrier that packs, sorts, opens or labels needs certification or an
                # Exempt Handler Affidavit.
                Question(
                    key="carrier_handles_beyond_transport",
                    kind="boolean",
                    label=text(
                        "Does any carrier do more than move the load, such as pack, repack, treat, sort, open, "
                        "enclose or label it?",
                        "¿Algún transportista hace algo más que mover la carga, como empacar, reempacar, tratar, "
                        "clasificar, abrir, envolver o etiquetar?",
                    ),
                    required=False,
                    nop_cite="§ 205.101(f)",
                    visible_when=(
                        Condition(
                            "who_transports",
                            "includes_any",
                            ["commercial_carrier", "broker", "warehouse_packer", "other_transporter"],
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="A carrier does more than move the load (packs, sorts, opens, labels or similar): {answer}."
                    ),
                ),
                # WSDA AGR 2121 §J9.
                Question(
                    key="transport_container_types",
                    kind="checkbox_group",
                    label=text(
                        "How is the crop transported? Check all that apply.",
                        "¿Cómo se transporta el cultivo? Marca todas las que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(template="The crop is transported in: {answer}."),
                    options=(
                        Option("bins_totes", text("Bins or totes", "Bins o totes")),
                        Option("bulk_trailer", text("Bulk trailer", "Remolque a granel")),
                        Option("cardboard_boxes", text("Cardboard boxes", "Cajas de cartón")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                # WSDA AGR 2121 §J11.
                Question(
                    key="transport_unit_cleaning_documentation",
                    kind="checkbox_group",
                    label=text(
                        "How do you show transport units are clean before loose or bulk organic product is "
                        "loaded? Check all that apply.",
                        "¿Cómo demuestras que las unidades de transporte están limpias antes de cargar producto "
                        "orgánico suelto o a granel? Marca todas las que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="Evidence that transport units are clean before loading: {answer}."
                    ),
                    options=(
                        Option(
                            "cleanout_records",
                            text("Clean-out records", "Registros de limpieza"),
                            evidence="transport_vehicle_cleanouts",
                        ),
                        Option(
                            "clean_truck_affidavits",
                            text(
                                "Clean truck or equipment affidavits", "Declaraciones juradas de camión o equipo limpio"
                            ),
                            evidence="clean_transport_affidavits",
                        ),
                        Option("other", text("Other", "Otra")),
                        Option(
                            "packaged_only",
                            text(
                                "Not applicable: only packaged product is shipped",
                                "No aplica: solo se envía producto empacado",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                # WSDA AGR 2121 §J12 / §J12a.
                Question(
                    key="transport_shared_with_noncertified",
                    kind="boolean",
                    label=text(
                        "Is organic product ever shipped in the same transport unit as non-organic product?",
                        "¿Alguna vez se envía producto orgánico en la misma unidad de transporte que producto "
                        "no orgánico?",
                    ),
                    required=False,
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="Organic product shipped in the same transport unit as non-organic product: {answer}."
                    ),
                ),
                Question(
                    key="shared_transport_segregation",
                    kind="checkbox_group",
                    label=text(
                        "How is organic product kept separate in a shared unit? Check all that apply.",
                        "¿Cómo se mantiene separado el producto orgánico en una unidad compartida? Marca todas "
                        "las que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("transport_shared_with_noncertified", "truthy"),),
                    compiles_to=CompileRule(template="Separation in a shared transport unit: {answer}."),
                    options=(
                        Option(
                            "sealed_impermeable",
                            text(
                                "Organic product is sealed in impermeable containers",
                                "El producto orgánico va sellado en contenedores impermeables",
                            ),
                        ),
                        Option("separate_area", text("A separate area of the unit", "Un área separada de la unidad")),
                        Option(
                            "separate_pallets", text("Separate, labeled pallets", "Tarimas separadas y etiquetadas")
                        ),
                        Option("other", text("Other", "Otra")),
                    ),
                ),
                # WSDA AGR 2121 §J13: the first stop before the buyer (a hydrocooler, cold storage or
                # consolidation point). WSDA's AGR 2519 form itself is out of scope; the fact is here.
                Question(
                    key="first_stop_before_buyer",
                    kind="checkbox_group",
                    label=text(
                        "Before the buyer, does the crop go anywhere else? Check all that apply.",
                        "Antes de llegar al comprador, ¿el cultivo pasa por otro lugar? Marca todos los que "
                        "correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(template="Before the buyer, the crop goes to: {answer}."),
                    options=(
                        Option(
                            "hydrocooler",
                            text("A hydrocooler or cooling facility", "Un hidroenfriador o centro de enfriamiento"),
                        ),
                        Option("cold_storage", text("Cold storage", "Almacenamiento en frío")),
                        Option("consolidation", text("A consolidation point", "Un punto de consolidación")),
                        Option("other", text("Other", "Otro")),
                        Option(
                            "none",
                            text("No, it goes straight to the buyer", "No, va directo al comprador"),
                            exclusive=True,
                        ),
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
                    "Si alguien fuera de tu operación descascara, seca, empaca, acondiciona o de otro modo manipula "
                    "tu cultivo, el certificador necesita saber quién es y si está certificado, porque desde ese "
                    "punto el rastro de auditoría pasa por sus registros y no por los tuyos. Responder “no” aquí es "
                    "una respuesta completa; dejarlo en blanco no lo es, porque quien revisa no puede distinguir "
                    "entre “nadie manipula nuestro cultivo” y “aún no se ha completado”.",
                ),
            ),
            questions=(
                Question(
                    key="handled_by_another_operation",
                    kind="radio",
                    label=text(
                        "Is your organic crop handled off the farm by another operation?",
                        "¿Tu cultivo orgánico es manipulado fuera de la finca por otra operación?",
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
                            "yes_ownership_transfers",
                            text(
                                "Yes \u2014 but ownership of the crop transfers to that operation "
                                "before or upon delivery",
                                "S\u00ed \u2014 pero la propiedad del cultivo pasa a esa operaci\u00f3n "
                                "antes de la entrega o al entregarlo",
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
                        "Estas son las instalaciones registradas en el perfil de tu finca. Cada una aparece aquí "
                        "con su dirección y su certificado orgánico, para que quien revisa vea el mismo manejador "
                        "en el plan y en los registros.",
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
                        "¿Qué registros proporciona esa operación para preservar la identidad orgánica de tu "
                        "producto?",
                    ),
                    coaching=text(
                        "An uncertified operation handling your crop needs records proving "
                        "identity preservation \u2014 lot tags, logs showing physical or timing "
                        "separation from nonorganic product, and cleaning records for the "
                        "equipment and space used.",
                        "Una operación no certificada que manipula tu cultivo necesita registros que demuestren la "
                        "preservación de la identidad — etiquetas de lote, bitácoras que muestren separación física "
                        "o temporal del producto no orgánico, y registros de limpieza del equipo y el espacio "
                        "utilizados.",
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
