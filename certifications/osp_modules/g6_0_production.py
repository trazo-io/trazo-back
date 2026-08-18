"""
G6.0 — Organic Production & Split Operations.

Sources: 7 CFR 205.202(c) (land requirements — distinct boundaries and buffer zones),
205.201(a)(5) (organic system plan — management practices and physical barriers that prevent
commingling of organic and non-organic products and contact with prohibited substances),
205.2 (definitions: split operation), 205.400(f)(1) (immediate notification of a known or
suspected prohibited-substance application or drift event). Topic order follows the public
Common OSP grower template; all wording authored for Trazo.

Scope: this module is the operation-wide split-operation and drift-prevention STRATEGY.
Per-parcel buffer geometry — adjoining land use, buffer width, and drift risk for each
border — is recorded on that parcel's Parcel Application (`parcel_application.py`, page D);
this module does not repeat it.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text

G6_0_PRODUCTION = Module(
    key="g6_0_production",
    code="G6.0",
    title=text("Organic Production & Split Operations", "Producción orgánica y operaciones divididas"),
    nop_cites=("§ 205.202(c)", "§ 205.201(a)", "§ 205.272(a)"),
    education=(
        text(
            "Field or farm parcels under organic management must have distinct, defined "
            "boundaries and buffer zones sufficient to prevent contact with a prohibited "
            "substance applied on adjoining land — and any crop grown in a buffer zone can "
            "never be sold, labeled, or represented as organic (§ 205.202(c)). Where organic "
            "and conventional production share one operation, the organic system plan must "
            "describe the management practices and physical barriers that keep them from "
            "commingling (§ 205.201(a)(5)).",
            "Las parcelas bajo manejo orgánico deben tener límites definidos y zonas de "
            "amortiguamiento suficientes para prevenir el contacto con una sustancia "
            "prohibida aplicada en tierras colindantes — y el cultivo que crece en una zona "
            "de amortiguamiento nunca puede venderse, etiquetarse ni representarse como "
            "orgánico (§ 205.202(c)). Cuando la producción orgánica y la convencional "
            "comparten una misma operación, el plan del sistema orgánico debe describir las "
            "prácticas de manejo y las barreras físicas que evitan que se mezclen "
            "(§ 205.201(a)(5)).",
        ),
    ),
    allows_not_applicable=False,
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_operation_type",
            title=text("A. Operation type", "A. Tipo de operación"),
            education=(
                text(
                    "A split operation produces or handles both organic and non-organic "
                    "products; the plan must show how the two are kept apart at every step "
                    "(§ 205.201(a)(5)).",
                    "Una operación dividida produce o maneja productos orgánicos y no "
                    "orgánicos a la vez; el plan debe mostrar cómo se mantienen separados en "
                    "cada etapa (§ 205.201(a)(5)).",
                ),
            ),
            questions=(
                Question(
                    key="split_operation",
                    kind="boolean",
                    label=text(
                        "Does this operation produce or handle both organic and "
                        "conventional (non-organic) crops or products under the same "
                        "management?",
                        "¿Esta operación produce o maneja cultivos o productos orgánicos y "
                        "convencionales (no orgánicos) bajo el mismo manejo?",
                    ),
                    coaching=text(
                        'A "split operation" is one where organic and non-organic '
                        "production or handling take place at the same operation, whether "
                        "on the same parcels or different ones (§ 205.2). Answer yes even "
                        "if the conventional share is small.",
                        'Una "operación dividida" (split operation) es aquella donde la '
                        "producción o el manejo orgánico y no orgánico ocurren en la misma "
                        "operación, sea en las mismas parcelas o en otras distintas "
                        "(§ 205.2). Responda que sí aunque la parte convencional sea "
                        "pequeña.",
                    ),
                    nop_cite="§ 205.201(a)(5)",
                    compiles_to=CompileRule(
                        template=(
                            "Split operation (organic and conventional production under "
                            "the same management): {answer}."
                        ),
                        # § 205.201(a)(5) — commingling and contact prevention.
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="split_operation_separation",
                    kind="textarea",
                    label=text(
                        "How are organic and conventional production kept separate?",
                        "¿Cómo se mantienen separadas la producción orgánica y la " "convencional?",
                    ),
                    coaching=text(
                        "Describe the equipment, storage, and recordkeeping separation — "
                        "dedicated or cleaned-between-uses equipment, separate or clearly "
                        "labeled storage areas, and records that identify every lot as "
                        "organic or conventional (§ 205.201(a)(5)).",
                        "Describa la separación de equipo, almacenamiento y registros — "
                        "equipo dedicado o limpiado entre usos, áreas de almacenamiento "
                        "separadas o claramente rotuladas, y registros que identifiquen "
                        "cada lote como orgánico o convencional (§ 205.201(a)(5)).",
                    ),
                    nop_cite="§ 205.201(a)(5)",
                    visible_when=(Condition(question="split_operation", op="truthy"),),
                    compiles_to=CompileRule(
                        template="Separation between organic and conventional production: {answer}",
                        # § 205.201(a)(5) — commingling and contact prevention.
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="parallel_production",
                    kind="boolean",
                    label=text(
                        "Do you grow the SAME crop or variety under both organic and "
                        "conventional management (parallel production)?",
                        "¿Cultiva el MISMO cultivo o variedad bajo manejo orgánico y "
                        "convencional a la vez (producción paralela)?",
                    ),
                    coaching=text(
                        "Parallel production raises the risk of commingling because organic "
                        "and conventional harvests of the same crop can look identical. "
                        "Certifiers scrutinize how each lot stays distinguishable from field "
                        "to sale.",
                        "La producción paralela aumenta el riesgo de mezcla porque las "
                        "cosechas orgánica y convencional del mismo cultivo pueden verse "
                        "idénticas. El certificador revisa con atención cómo cada lote se "
                        "mantiene distinguible desde el campo hasta la venta.",
                    ),
                    nop_cite="§ 205.201(a)(5)",
                    compiles_to=CompileRule(
                        template="Parallel production (same crop grown organic and conventional): {answer}.",
                        # § 205.201(a)(5) — commingling and contact prevention.
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="parallel_production_distinction",
                    kind="textarea",
                    label=text(
                        "How are organic and conventional lots of the same crop " "distinguished at harvest and sale?",
                        "¿Cómo se distinguen en la cosecha y la venta los lotes orgánicos y "
                        "convencionales del mismo cultivo?",
                    ),
                    coaching=text(
                        "Identify field or block markers, separate harvest containers or "
                        "lot tags, harvest sequencing (organic first), and how sales records "
                        "carry the organic identification through to the buyer.",
                        "Identifique marcadores de campo o bloque, contenedores de cosecha o "
                        "etiquetas de lote separados, el orden de cosecha (orgánico "
                        "primero) y cómo los registros de venta llevan la identificación "
                        "orgánica hasta el comprador.",
                    ),
                    nop_cite="§ 205.201(a)(5)",
                    visible_when=(Condition(question="parallel_production", op="truthy"),),
                    compiles_to=CompileRule(
                        template=(
                            "Distinction between parallel organic and conventional lots "
                            "at harvest and sale: {answer}"
                        )
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_buffer_strategy",
            title=text("B. Buffer & separation strategy", "B. Amortiguamiento y estrategia de separación"),
            education=(
                text(
                    "Field or farm parcels under organic management must have distinct, "
                    "defined boundaries and buffer zones sufficient to prevent the "
                    "unintended application of a prohibited substance to the crop, or "
                    "contact with a prohibited substance applied on adjoining land that is "
                    "not organically managed (§ 205.202(c)). Any crop grown in a buffer zone "
                    "may never be sold, labeled, or represented as organic. The exact buffer "
                    "width and layout for each border is recorded on that parcel's Parcel "
                    "Application — this page documents the strategy you apply across the "
                    "operation.",
                    "Las parcelas bajo manejo orgánico deben tener límites definidos y zonas "
                    "de amortiguamiento suficientes para prevenir la aplicación involuntaria "
                    "de una sustancia prohibida al cultivo, o el contacto con una sustancia "
                    "prohibida aplicada en tierras colindantes que no están bajo manejo "
                    "orgánico (§ 205.202(c)). El cultivo que crece en una zona de "
                    "amortiguamiento nunca puede venderse, etiquetarse ni representarse como "
                    "orgánico. El ancho y trazado exacto del amortiguamiento de cada límite "
                    "se registra en la Solicitud de Parcela correspondiente — esta página "
                    "documenta la estrategia que aplica en toda la operación.",
                ),
            ),
            questions=(
                Question(
                    key="buffer_strategies",
                    kind="checkbox_group",
                    label=text(
                        "Buffer and separation strategies used across the operation",
                        "Estrategias de amortiguamiento y separación usadas en la operación",
                    ),
                    coaching=text(
                        "Select every strategy this operation uses across its parcels. "
                        "Buffer-zone crop — whether harvested or left standing — can never "
                        "be sold, labeled, or represented as organic (§ 205.202(c)).",
                        "Seleccione cada estrategia que la operación usa en sus parcelas. El "
                        "cultivo de la zona de amortiguamiento — cosechado o dejado en pie — "
                        "nunca puede venderse, etiquetarse ni representarse como orgánico "
                        "(§ 205.202(c)).",
                    ),
                    nop_cite="§ 205.202(c)",
                    compiles_to=CompileRule(
                        template="Buffer and separation strategies used across the operation: {answer}.",
                        # § 205.201(a)(5) — commingling and contact prevention.
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "buffer_containers_marked",
                            text(
                                "Buffer-crop containers marked or kept separate — never marked organic",
                                "Contenedores del cultivo de amortiguamiento marcados o separados — nunca marcados como orgánicos",
                            ),
                        ),
                        Option(
                            "buffer_stored_separately",
                            text(
                                "Buffer harvest stored apart from organic product",
                                "Cosecha del amortiguamiento almacenada aparte del producto orgánico",
                            ),
                        ),
                        Option(
                            "buffer_harvested_different_time",
                            text(
                                "Buffer rows harvested at a different time than the organic crop",
                                "Hileras de amortiguamiento cosechadas en un momento distinto al cultivo orgánico",
                            ),
                        ),
                        Option(
                            "buffer_sold_different_buyer",
                            text(
                                "Buffer crop sold to a different buyer than the organic crop",
                                "Cultivo del amortiguamiento vendido a un comprador distinto",
                            ),
                        ),
                        Option(
                            "buffer_separate_records",
                            text(
                                "Separate harvest and sales records kept for buffer crop",
                                "Registros separados de cosecha y venta para el cultivo del amortiguamiento",
                            ),
                        ),
                        Option(
                            "buffer_areas_flagged",
                            text(
                                "Buffer areas flagged or marked in the field",
                                "Áreas de amortiguamiento señalizadas o marcadas en el campo",
                            ),
                        ),
                        Option(
                            "buffer_strips",
                            text(
                                "Maintained buffer strips (vegetation or fallow ground kept " "along the border)",
                                "Franjas de amortiguamiento mantenidas (vegetación o terreno "
                                "en barbecho a lo largo del límite)",
                            ),
                        ),
                        Option(
                            "hedgerows_windbreaks",
                            text("Hedgerows or windbreaks", "Cercos vivos o cortavientos"),
                        ),
                        Option(
                            "roads_waterways",
                            text(
                                "Roads, waterways, or other natural features used as barriers",
                                "Caminos, cursos de agua u otros accidentes naturales usados " "como barrera",
                            ),
                        ),
                        Option(
                            "physical_barriers",
                            text(
                                "Fences, ditches, or berms as physical barriers",
                                "Cercas, zanjas o terraplenes como barreras físicas",
                            ),
                        ),
                        Option(
                            "harvest_buffer_as_conventional",
                            text(
                                "Harvest buffer rows separately and sell as conventional " "(not organic)",
                                "Cosecha por separado de las hileras de amortiguamiento y "
                                "venta como convencional (no orgánico)",
                            ),
                        ),
                        Option(
                            "do_not_harvest_buffer",
                            text(
                                "Buffer rows are left unharvested",
                                "Las hileras de amortiguamiento se dejan sin cosechar",
                            ),
                        ),
                        Option(
                            "physical_distance",
                            text(
                                "Physical distance or isolation from conventional fields",
                                "Distancia física o aislamiento respecto a campos " "convencionales",
                            ),
                        ),
                        Option(
                            "no_adjoining_conventional",
                            text(
                                "No adjoining conventional land — no buffer needed",
                                "No hay tierra convencional colindante — no se necesita " "amortiguamiento",
                            ),
                            exclusive=True,
                        ),
                        Option("other", text("Other (describe below)", "Otra (describa abajo)")),
                    ),
                ),
                Question(
                    key="buffer_strategy_other",
                    kind="text",
                    label=text(
                        "Describe the other buffer or separation strategy",
                        "Describa la otra estrategia de amortiguamiento o separación",
                    ),
                    visible_when=(Condition(question="buffer_strategies", op="includes", value="other"),),
                    compiles_to=CompileRule(template="Additional buffer or separation strategy: {answer}."),
                ),
            ),
        ),
        ModulePage(
            key="c_drift_safeguards",
            title=text("C. Drift safeguards", "C. Salvaguardas contra la deriva"),
            education=(
                text(
                    "Drift of a prohibited substance from adjoining land does not "
                    "automatically decertify the affected crop, but the operation must show "
                    "it took reasonable precautions and responded appropriately if contact "
                    "occurred. Select the safeguards this operation practices to prevent and "
                    "detect drift.",
                    "La deriva de una sustancia prohibida desde tierras colindantes no "
                    "descertifica automáticamente el cultivo afectado, pero la operación "
                    "debe demostrar que tomó precauciones razonables y respondió "
                    "apropiadamente si ocurrió contacto. Seleccione las salvaguardas que "
                    "esta operación practica para prevenir y detectar la deriva.",
                ),
            ),
            questions=(
                Question(
                    key="drift_safeguards",
                    kind="checkbox_group",
                    label=text(
                        "Drift-prevention safeguards in place",
                        "Salvaguardas de prevención de deriva vigentes",
                    ),
                    coaching=text(
                        "These are standard certifier-recognized drift-prevention "
                        "practices, in addition to the physical buffers recorded on your "
                        "Parcel Applications. Select every safeguard this operation "
                        "practices.",
                        "Estas son prácticas de prevención de deriva reconocidas "
                        "habitualmente por los certificadores, además de los "
                        "amortiguamientos físicos registrados en sus Solicitudes de "
                        "Parcela. Seleccione cada salvaguarda que practica esta operación.",
                    ),
                    nop_cite="§ 205.202(c)",
                    compiles_to=CompileRule(
                        template="Drift-prevention safeguards in place: {answer}.",
                        # § 205.201(a)(5) — commingling and contact prevention.
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "self_managed_adjacent",
                            text(
                                "I manage the adjoining land myself — no third-party spray risk",
                                "Yo mismo manejo la tierra colindante — sin riesgo de aspersión de terceros",
                            ),
                        ),
                        Option(
                            "written_notification",
                            text(
                                "Written notification to neighboring landowners or "
                                "operators about the organic operation's location and "
                                "boundaries",
                                "Notificación escrita a los propietarios u operadores "
                                "vecinos sobre la ubicación y los límites de la operación "
                                "orgánica",
                            ),
                        ),
                        Option(
                            "no_spray_agreements",
                            text(
                                "No-spray or advance-notice agreements with neighboring " "operators",
                                "Acuerdos de no fumigación o de aviso previo con " "operadores vecinos",
                            ),
                        ),
                        Option(
                            "roadside_utility_registration",
                            text(
                                "Roadside or utility right-of-way no-spray registration",
                                "Registro de no fumigación en banquinas de caminos o "
                                "servidumbres de servicios públicos",
                            ),
                        ),
                        Option(
                            "sensitive_crop_registry",
                            text(
                                "Listed on DriftWatch or a state sensitive-crop registry",
                                "Inscripción en DriftWatch o en un registro estatal de " "cultivos sensibles",
                            ),
                        ),
                        Option(
                            "boundary_signage",
                            text(
                                "Boundary signage marking the organic operation",
                                "Señalización de límites que marca la operación orgánica",
                            ),
                        ),
                        Option(
                            "monitor_adjoining_activity",
                            text(
                                "Routine monitoring of adjoining land for spray activity or " "land-use changes",
                                "Monitoreo rutinario de las tierras colindantes por "
                                "actividad de fumigación o cambios de uso",
                            ),
                        ),
                        Option(
                            "wind_awareness",
                            text(
                                "Awareness of wind conditions when neighbors are known to " "spray",
                                "Atención a las condiciones del viento cuando se sabe que " "los vecinos van a fumigar",
                            ),
                        ),
                        Option(
                            "complaint_procedure",
                            text(
                                "Documented procedure for logging suspected drift or " "contact incidents",
                                "Procedimiento documentado para registrar incidentes "
                                "sospechados de deriva o contacto",
                            ),
                        ),
                        Option(
                            "buffer_harvest_exclusion",
                            text(
                                "Buffer-zone crop excluded from the organic harvest (see "
                                "Buffer & separation strategy above)",
                                "Cultivo de la zona de amortiguamiento excluido de la "
                                "cosecha orgánica (ver Amortiguamiento y estrategia de "
                                "separación arriba)",
                            ),
                        ),
                        Option(
                            "residue_testing",
                            text(
                                "Residue testing when drift or contact is suspected",
                                "Análisis de residuos cuando se sospecha deriva o contacto",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describa abajo)")),
                    ),
                ),
                Question(
                    key="drift_safeguards_other",
                    kind="text",
                    label=text(
                        "Describe the other drift safeguard",
                        "Describa la otra salvaguarda contra la deriva",
                    ),
                    visible_when=(Condition(question="drift_safeguards", op="includes", value="other"),),
                    compiles_to=CompileRule(template="Additional drift safeguard: {answer}."),
                ),
                Question(
                    key="drift_response_procedure",
                    kind="textarea",
                    label=text(
                        "If you suspect drift or contact with a prohibited substance has " "occurred, what do you do?",
                        "Si sospecha que ocurrió deriva o contacto con una sustancia " "prohibida, ¿qué hace?",
                    ),
                    coaching=text(
                        "§ 205.400(f)(1) requires immediately notifying your certifying "
                        "agent of a known or suspected prohibited-substance application or "
                        "drift event. Describe your notification timeline, who you contact, "
                        "and how you document the incident and any resulting testing or "
                        "corrective action — Trazo's Change Notification log "
                        '("Prohibited-substance application/drift" category) can record '
                        "the notification itself.",
                        "El § 205.400(f)(1) exige notificar de inmediato a su agencia "
                        "certificadora ante un evento conocido o sospechado de aplicación o "
                        "deriva de una sustancia prohibida. Describa su plazo de "
                        "notificación, a quién contacta y cómo documenta el incidente y "
                        "cualquier análisis o acción correctiva resultante — el registro de "
                        "Notificación de Cambios de Trazo (categoría "
                        '"Prohibited-substance application/drift") puede registrar la '
                        "notificación misma.",
                    ),
                    nop_cite="§ 205.400(f)(1)",
                    compiles_to=CompileRule(
                        template=(
                            "Response procedure when drift or contact with a prohibited "
                            "substance is suspected: {answer}"
                        ),
                        # § 205.201(a)(5) — commingling and contact prevention.
                        section_key="commingling_barriers",
                    ),
                ),
            ),
        ),
        # § 205.201(a)(5) names two things a plan must describe: the barriers that prevent
        # COMMINGLING of product, and the barriers that prevent CONTACT with prohibited
        # substances. Pages A-C cover the first and the drift half of the second. Where the
        # prohibited substances physically sit — the barn shelf above the organic bins — had
        # no home anywhere in the product, and it is the first thing an inspector walks to on
        # a split operation.
        #
        # NOT gated on `split_operation`: a wholly organic farm still keeps diesel, treated
        # lumber, and shop cleaners, and § 205.272(a) applies to those exactly as it does to
        # a conventional block's fertilizer.
        ModulePage(
            key="d_prohibited_material_storage",
            title=text(
                "D. Where prohibited materials are kept",
                "D. Dónde se guardan los materiales prohibidos",
            ),
            education=(
                text(
                    "§ 205.201(a)(5) requires your plan to describe the physical barriers "
                    "that keep organic production and product away from prohibited "
                    "substances, and § 205.272(a) restates the same duty as a practice "
                    "standard. Materials count even when they are never applied to organic "
                    "ground — conventional fertilizer held for a leased block, shop "
                    "solvents, treated lumber, and fuel additives are all in scope. Describe "
                    "where they live and what separates them.",
                    "El § 205.201(a)(5) exige que su plan describa las barreras físicas que "
                    "mantienen la producción y el producto orgánico alejados de las "
                    "sustancias prohibidas, y el § 205.272(a) reitera el mismo deber como "
                    "norma de práctica. Los materiales cuentan aunque nunca se apliquen en "
                    "terreno orgánico — fertilizante convencional guardado para un lote "
                    "arrendado, solventes de taller, madera tratada y aditivos de "
                    "combustible están todos incluidos. Describa dónde se guardan y qué los "
                    "separa.",
                ),
            ),
            questions=(
                Question(
                    key="prohibited_materials_on_site",
                    kind="boolean",
                    label=text(
                        "Are any materials prohibited in organic production kept anywhere on " "this operation?",
                        "¿Se guarda en algún lugar de esta operación algún material prohibido "
                        "en la producción orgánica?",
                    ),
                    coaching=text(
                        "Includes conventional fertilizers and pesticides, treated lumber, "
                        "nonorganic cleaners and sanitizers, and fuel or shop chemicals — "
                        "whether or not they are ever used on organic ground.",
                        "Incluye fertilizantes y pesticidas convencionales, madera tratada, "
                        "limpiadores y desinfectantes no orgánicos, y combustible o químicos "
                        "de taller — se usen o no en terreno orgánico.",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="Materials prohibited in organic production are kept on site: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="prohibited_materials_storage",
                    kind="checkbox_group",
                    label=text(
                        "How are those materials stored and kept away from organic product, " "inputs, and equipment?",
                        "¿Cómo se almacenan esos materiales y se mantienen alejados del "
                        "producto, insumos y equipo orgánicos?",
                    ),
                    nop_cite="§ 205.201(a)(5)",
                    visible_when=(Condition("prohibited_materials_on_site", "truthy"),),
                    options=(
                        Option(
                            "separate_building",
                            text(
                                "In a separate building or shed from organic product and inputs",
                                "En un edificio o galpón separado del producto e insumos orgánicos",
                            ),
                        ),
                        Option(
                            "locked_or_enclosed",
                            text(
                                "In a locked or enclosed cabinet, cage, or room",
                                "En un gabinete, jaula o sala cerrada con llave",
                            ),
                        ),
                        Option(
                            "labeled_dedicated_area",
                            text(
                                "In a labeled, dedicated area within a shared building",
                                "En un área rotulada y dedicada dentro de un edificio compartido",
                            ),
                        ),
                        Option(
                            "physically_below",
                            text(
                                "Stored below organic materials so a spill or leak cannot reach them",
                                "Almacenados por debajo de los materiales orgánicos para que un "
                                "derrame o fuga no pueda alcanzarlos",
                            ),
                        ),
                        Option(
                            "secondary_containment",
                            text(
                                "In secondary containment (bunded pallet, spill tray, sealed drum)",
                                "En contención secundaria (pallet de retención, bandeja "
                                "antiderrames, tambor sellado)",
                            ),
                        ),
                        Option(
                            "dedicated_equipment",
                            text(
                                "Handled with dedicated equipment that never touches organic product",
                                "Manipulados con equipo dedicado que nunca toca producto orgánico",
                            ),
                        ),
                        Option(
                            "off_site",
                            text(
                                "Stored off site, not on this operation's premises",
                                "Almacenados fuera del sitio, no en las instalaciones de esta operación",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describa abajo)")),
                    ),
                    compiles_to=CompileRule(
                        template="Prohibited materials are stored and separated as follows: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="prohibited_materials_storage_other",
                    kind="text",
                    label=text(
                        "Describe the other storage or separation measure",
                        "Describa la otra medida de almacenamiento o separación",
                    ),
                    visible_when=(Condition("prohibited_materials_storage", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Additional prohibited-material separation measure: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
            ),
        ),
    ),
)
