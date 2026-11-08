"""
G4.1 — Compost & Manure.

Sources: 7 CFR 205.203(c) (soil fertility and crop nutrient management — the raw-manure and
composted-material provisions) and 205.2 (definitions: "Compost"). G4.0 (Rotation & Soil
Management) lists "Manure (see module G4.1)" among its fertility components; this module is
where manure and compost use get the § 205.203(c)(1)-(2) detail: the raw-manure interval rule,
and the compost time/temperature/C:N standard for material produced on-farm, purchased, or
vermicomposted.

No prefill sources are wired in v1 — unlike G3.0/G4.0, this module does not surface suggested
answers from existing SoilManagementEvent records.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Prefill, Question, text

G4_1_COMPOST_MANURE = Module(
    key="g4_1_compost_manure",
    code="G4.1",
    title=text("Compost & Manure", "Compost y estiércol"),
    nop_cites=("§ 205.203(c)", "§ 205.2"),
    education=(
        text(
            "Raw animal manure applied on organically managed land must either be composted "
            "to the standard below, or incorporated into the soil at least 120 days before "
            "harvest of a crop whose edible portion contacts the soil, or at least 90 days "
            "before harvest when it does not. Compost — whether produced on the farm, "
            "purchased, or vermicomposted — must meet a defined carbon:nitrogen ratio and a "
            "time/temperature standard (§ 205.203(c), § 205.2).",
            "El estiércol animal crudo aplicado en tierra de manejo orgánico debe compostarse "
            "según el estándar siguiente, o incorporarse al suelo al menos 120 días antes de "
            "la cosecha de un cultivo cuya porción comestible tiene contacto con el suelo, o "
            "al menos 90 días antes cuando no lo tiene. El compost — producido en la finca, "
            "comprado o mediante vermicompostaje — debe cumplir una relación carbono:nitrógeno "
            "definida y un estándar de tiempo/temperatura (§ 205.203(c), § 205.2).",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — no manure, compost, or animal-based soil inputs are used at this " "operation.",
        "No aplica — esta operación no usa estiércol, compost ni insumos de suelo de origen " "animal.",
    ),
    default_section_key="inputs_list",
    pages=(
        ModulePage(
            key="a_materials",
            title=text("A. What you apply", "A. Qué aplicas"),
            questions=(
                Question(
                    key="materials_applied",
                    kind="checkbox_group",
                    prefill=Prefill(source="manure_compost_evidence"),
                    label=text(
                        "Which compost, manure, or animal-based soil inputs do you apply?",
                        "¿Qué insumos de compost, estiércol o de origen animal aplicas?",
                    ),
                    coaching=text(
                        "Processed manure products means manure that has been pelleted, "
                        "heat-treated, or otherwise processed by a manufacturer — for example, "
                        "commercial pelleted poultry manure — rather than applied raw or "
                        "composted on this operation.",
                        "Productos de estiércol procesado significa estiércol peletizado, "
                        "tratado con calor u otro proceso por un fabricante — por ejemplo, "
                        "estiércol de aves peletizado comercial — en lugar de aplicarse crudo o "
                        "compostado en esta operación.",
                    ),
                    nop_cite="§ 205.203(c)",
                    compiles_to=CompileRule(template="Compost and manure materials applied: {answer}."),
                    options=(
                        Option(
                            "raw_manure",
                            text("Raw (uncomposted) animal manure", "Estiércol animal crudo (sin compostar)"),
                        ),
                        Option(
                            "on_farm_compost",
                            text("Compost produced on this farm", "Compost producido en esta finca"),
                        ),
                        Option(
                            "purchased_compost",
                            text("Purchased or off-farm compost", "Compost comprado o de fuera de la finca"),
                        ),
                        Option(
                            "processed_manure",
                            text(
                                "Processed manure products (pelleted, heat-treated, or " "otherwise processed)",
                                "Productos de estiércol procesado (peletizado, tratado con " "calor u otro proceso)",
                            ),
                        ),
                        Option(
                            "compost_tea",
                            text("Compost tea or other liquid extracts", "Té de compost u otros extractos líquidos"),
                        ),
                        Option(
                            "vermicompost",
                            text("Vermicompost (worm castings)", "Vermicompost (humus de lombriz)"),
                        ),
                        # CCOF G4.1 B1; WSDA AGR 2121 E12. A grazed orchard told G5.0 it grazes and told
                        # this module "none of these", so the § 205.203(c)(1) interval never printed.
                        Option(
                            "planned_grazing",
                            text(
                                "Planned grazing of animals in organic crop areas",
                                "Pastoreo planificado de animales en áreas de cultivo orgánico",
                            ),
                        ),
                        Option(
                            "none",
                            text("None of these are used", "No se usa ninguno de estos"),
                            exclusive=True,
                        ),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_raw_manure",
            title=text("B. Raw manure and planned grazing", "B. Estiércol crudo y pastoreo planificado"),
            education=(
                text(
                    "Raw animal manure must either be composted, or incorporated into the soil "
                    "with enough time for pathogens to die off before harvest: at least 120 "
                    "days when the edible portion of the crop contacts the soil, or at least "
                    "90 days when it does not. No waiting interval applies when raw manure is "
                    "used only on land growing crops not intended for human consumption "
                    "(§ 205.203(c)(1)).",
                    "El estiércol animal crudo debe compostarse, o incorporarse al suelo con "
                    "tiempo suficiente para que los patógenos mueran antes de la cosecha: al "
                    "menos 120 días cuando la porción comestible del cultivo tiene contacto con "
                    "el suelo, o al menos 90 días cuando no lo tiene. No aplica ningún "
                    "intervalo de espera cuando el estiércol crudo se usa solo en tierra que "
                    "produce cultivos no destinados al consumo humano (§ 205.203(c)(1)).",
                ),
            ),
            visible_when=(Condition("materials_applied", "includes_any", ("raw_manure", "planned_grazing")),),
            questions=(
                Question(
                    # A checkbox group since 2026.11.02 (migration 0060 wraps stored answers): CCOF G4.1 B2,
                    # OTCO C4 4.3-4 and WSDA AGR 2121 D13a say "all that apply", and a farm with root crops
                    # and tree fruit applies both rules.
                    key="raw_manure_interval_rule",
                    kind="checkbox_group",
                    label=text(
                        "Which application rules apply to your raw manure use and planned grazing? Check all "
                        "that apply.",
                        "¿Qué reglas de aplicación corresponden a tu uso de estiércol crudo y al pastoreo "
                        "planificado? Marca todas las que correspondan.",
                    ),
                    coaching=text(
                        "Check each rule that matches how manure is applied or animals graze on your land. Each "
                        "one sets the minimum number of days between application and harvest for those crops.",
                        "Marca cada regla que corresponde a cómo se aplica el estiércol o pastorean los animales "
                        "en tu tierra. Cada una fija el número mínimo de días entre la aplicación y la cosecha "
                        "de esos cultivos.",
                    ),
                    nop_cite="§ 205.203(c)(1)",
                    compiles_to=CompileRule(template="Raw manure and planned grazing follow: {answer}."),
                    options=(
                        Option(
                            "non_food_crop",
                            text(
                                "Applied to land growing crops not intended for human "
                                "consumption (no waiting interval required)",
                                "Aplicado en tierra que produce cultivos no destinados al "
                                "consumo humano (no requiere intervalo de espera)",
                            ),
                        ),
                        Option(
                            "contact_120_days",
                            text(
                                "Incorporated into the soil at least 120 days before harvest of "
                                "a crop whose edible portion contacts the soil",
                                "Incorporado al suelo al menos 120 días antes de la cosecha de "
                                "un cultivo cuya porción comestible tiene contacto con el suelo",
                            ),
                        ),
                        Option(
                            "no_contact_90_days",
                            text(
                                "Incorporated into the soil at least 90 days before harvest of "
                                "a crop whose edible portion does not contact the soil",
                                "Incorporado al suelo al menos 90 días antes de la cosecha de "
                                "un cultivo cuya porción comestible no tiene contacto con el "
                                "suelo",
                            ),
                        ),
                        # OTCO C4 4.3-4, third box.
                        Option(
                            "processed_meets_5006",
                            text(
                                "Manure is processed or pelleted to the NOP 5006 time, temperature and moisture "
                                "standard",
                                "El estiércol se procesa o pelletiza según el estándar de tiempo, temperatura y "
                                "humedad de NOP 5006",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="raw_manure_timing_detail",
                    kind="text",
                    label=text(
                        "Describe your typical raw manure application timing",
                        "Describe el momento típico de aplicación de estiércol crudo",
                    ),
                    coaching=text(
                        "Note the crop, the season you apply, and how many days before harvest "
                        "— Trazo's soil and input events carry the application and harvest "
                        "dates that prove this interval.",
                        "Indica el cultivo, la temporada de aplicación y cuántos días antes de la cosecha — los "
                        "eventos de suelo e insumos de Trazo registran las fechas de aplicación y cosecha que "
                        "demuestran este intervalo.",
                    ),
                    nop_cite="§ 205.203(c)(1)",
                    # Applied manure only: a grazing-only farm opens this page and has no application timing
                    # to describe (review of back #254).
                    visible_when=(Condition("materials_applied", "includes", "raw_manure"),),
                    compiles_to=CompileRule(template="Typical raw manure application timing: {answer}."),
                ),
                Question(
                    key="raw_manure_source",
                    kind="radio",
                    label=text(
                        "Where does the raw manure come from?",
                        "¿De dónde proviene el estiércol crudo?",
                    ),
                    coaching=text(
                        "Manure bought in or hauled from another operation may have been treated "
                        "with a prohibited substance before it reached you. Say where it comes "
                        "from; a purchased source is asked for a label or supplier statement below.",
                        "El estiércol comprado o traído de otra operación puede haber sido tratado con una "
                        "sustancia prohibida antes de llegar a ti. Indica su origen; para una fuente comprada se "
                        "pide abajo una etiqueta o declaración del proveedor.",
                    ),
                    nop_cite="§ 205.203(c)(1)",
                    visible_when=(Condition(question="materials_applied", op="includes", value="raw_manure"),),
                    compiles_to=CompileRule(template="Raw manure source: {answer}."),
                    options=(
                        Option(
                            "own_operation",
                            text(
                                "Produced by livestock on this operation",
                                "Producido por el ganado de esta operación",
                            ),
                        ),
                        Option(
                            "off_farm",
                            text(
                                "Purchased or brought in from another operation",
                                "Comprado o traído de otra operación",
                            ),
                        ),
                        Option(
                            "both",
                            text(
                                "Both — some produced here, some brought in",
                                "Ambos — una parte producida aquí y otra traída de fuera",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="raw_manure_supplier_statement",
                    kind="boolean",
                    label=text(
                        "For manure brought in from off the operation, is a product label or "
                        "supplier statement on file confirming it has not been treated with "
                        "prohibited substances?",
                        "Para el estiércol traído de fuera de la operación, ¿tienes archivada una etiqueta del "
                        "producto o una declaración del proveedor que confirme que no fue tratado con sustancias "
                        "prohibidas?",
                    ),
                    nop_cite="§ 205.105",
                    visible_when=(
                        Condition(question="materials_applied", op="includes", value="raw_manure"),
                        Condition(question="raw_manure_source", op="one_of", value=["off_farm", "both"]),
                    ),
                    compiles_to=CompileRule(
                        template="Supplier statement that off-farm manure is untreated on file: {answer}."
                    ),
                ),
                Question(
                    key="raw_manure_water_risk",
                    kind="textarea",
                    label=text(
                        "How do you prevent raw manure, applied or from grazing animals, from contaminating water "
                        "sources (runoff, wells, waterways)?",
                        "¿Cómo evitas que el estiércol crudo, aplicado o de animales en pastoreo, contamine fuentes "
                        "de agua (escorrentía, pozos, cauces)?",
                    ),
                    # Required since 2026.11.02: CCOF G4.1 B3 and OTCO C4 4.3-5 require an answer, and
                    # § 205.203(c) applies to grazing as much as to applied manure.
                    nop_cite="§ 205.203(c)",
                    visible_when=(
                        Condition(
                            question="materials_applied", op="includes_any", value=["raw_manure", "planned_grazing"]
                        ),
                    ),
                    compiles_to=CompileRule(template="Raw manure water-contamination prevention: {answer}."),
                ),
                Question(
                    # OTCO C4 4.3-2: the label or supplier statement itself, not only that it is on file.
                    key="raw_manure_supplier_statement_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach the product label or supplier statement",
                        "Adjunta la etiqueta del producto o la declaración del proveedor",
                    ),
                    nop_cite="§ 205.203(c)(1)",
                    visible_when=(
                        Condition(question="materials_applied", op="includes", value="raw_manure"),
                        Condition(question="raw_manure_supplier_statement", op="truthy"),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="c_compost_practice",
            title=text("C. Compost practice", "C. Práctica de compostaje"),
            education=(
                text(
                    "Compost must start with plant and animal materials combined at an initial "
                    "C:N (carbon:nitrogen) ratio between 25:1 and 40:1. The pile must then "
                    "reach 131-170°F and hold that range for 3 days under an in-vessel or "
                    "static aerated system, or for 15 days with at least 5 turnings under a "
                    "windrow system (§ 205.203(c)(2)).",
                    "El compost debe iniciarse combinando materiales vegetales y animales con "
                    "una relación C:N (carbono:nitrógeno) inicial entre 25:1 y 40:1. La pila "
                    "debe luego alcanzar 131-170°F y mantener ese rango durante 3 días en un "
                    "sistema en recipiente cerrado o pila estática aireada, o durante 15 días "
                    "con al menos 5 volteos en un sistema de hileras (§ 205.203(c)(2)).",
                ),
                text(
                    "Vermicompost and purchased compost are held to the same standard. If a "
                    "vermicomposting process does not reach these time/temperature thresholds "
                    "and the feedstock includes animal manure, it is treated as raw manure and "
                    "the interval rule on the previous page applies instead. For purchased "
                    "compost, the supplier's documentation stands in for your own production "
                    "records.",
                    "El vermicompost y el compost comprado se rigen por el mismo estándar. Si un proceso de "
                    "vermicompostaje no alcanza estos umbrales de tiempo/temperatura y la materia prima incluye "
                    "estiércol animal, se trata como estiércol crudo y aplica la regla de intervalo de la página "
                    "anterior. Para el compost comprado, la documentación del proveedor sustituye tus propios "
                    "registros de producción.",
                ),
            ),
            visible_when=(
                Condition(
                    "materials_applied",
                    "includes_any",
                    ("on_farm_compost", "vermicompost", "purchased_compost", "compost_tea"),
                ),
            ),
            questions=(
                Question(
                    key="compost_method",
                    kind="radio",
                    label=text(
                        "Which compost production method do you use?",
                        "¿Qué método de producción de compost utilizas?",
                    ),
                    coaching=text(
                        "If the compost meets none of these standards, choose the last option and also mark raw "
                        "manure on page A, so the raw-manure questions open.",
                        "Si el compost no cumple ninguno de estos estándares, elige la última opción y marca "
                        "también estiércol crudo en la página A, para que se abran las preguntas de estiércol crudo.",
                    ),
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(Condition("materials_applied", "includes_any", ("on_farm_compost", "vermicompost")),),
                    compiles_to=CompileRule(template="On-farm compost is produced by {answer}."),
                    options=(
                        Option("windrow", text("Windrow system", "Sistema de hileras (windrow)")),
                        Option("static_aerated", text("Static aerated pile", "Pila estática aireada")),
                        Option(
                            "in_vessel",
                            text("In-vessel system", "Sistema en recipiente cerrado (in-vessel)"),
                        ),
                        Option(
                            "vermicompost",
                            text("Vermicomposting (worm-based)", "Vermicompostaje (a base de lombrices)"),
                        ),
                        Option(
                            "does_not_meet",
                            text(
                                "a process that meets none of these standards, so the compost is treated as raw manure",
                                "un proceso que no cumple ninguno de estos estándares, así que el compost se trata "
                                "como estiércol crudo",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="compost_initial_cn_ratio",
                    kind="text",
                    label=text(
                        "What was the initial carbon:nitrogen (C:N) ratio of your feedstock?",
                        "¿Cuál fue la relación carbono:nitrógeno (C:N) inicial de tu materia prima?",
                    ),
                    coaching=text(
                        "Compost must start with a C:N ratio between 25:1 and 40:1 (§ 205.203(c)(2)).",
                        "El compost debe iniciar con una relación C:N entre 25:1 y 40:1 " "(§ 205.203(c)(2)).",
                    ),
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(Condition("materials_applied", "includes_any", ("on_farm_compost", "vermicompost")),),
                    compiles_to=CompileRule(template="Initial C:N ratio of compost feedstock: {answer}."),
                ),
                Question(
                    key="compost_temp_and_days",
                    kind="text",
                    label=text(
                        "What temperature range did the compost reach, and for how many days?",
                        "¿Qué rango de temperatura alcanzó el compost y durante cuántos días?",
                    ),
                    coaching=text(
                        "The pile must hold 131-170°F for 3 days (in-vessel or static aerated) "
                        "or for 15 days (windrow) (§ 205.203(c)(2)).",
                        "La pila debe mantenerse entre 131-170°F durante 3 días (en recipiente "
                        "cerrado o pila estática aireada) o durante 15 días (hileras) "
                        "(§ 205.203(c)(2)).",
                    ),
                    nop_cite="§ 205.203(c)(2)",
                    # Asked of the thermophilic methods only (OTCO C4 4.4-3): vermicompost is judged on
                    # aerobic conditions and moisture, and a process meeting no standard is raw manure.
                    visible_when=(
                        Condition("materials_applied", "includes_any", ("on_farm_compost", "vermicompost")),
                        Condition("compost_method", "one_of", ("windrow", "static_aerated", "in_vessel")),
                    ),
                    compiles_to=CompileRule(template="Compost temperature range and days held: {answer}."),
                ),
                Question(
                    key="compost_turnings",
                    kind="text",
                    label=text(
                        "How many times was the windrow turned during the 15-day period?",
                        "¿Cuántas veces se volteó la hilera durante el período de 15 días?",
                    ),
                    coaching=text(
                        "Windrow compost requires a minimum of 5 turnings during the 15-day "
                        "heating period (§ 205.203(c)(2)).",
                        "El compost en hileras requiere un mínimo de 5 volteos durante el "
                        "período de calentamiento de 15 días (§ 205.203(c)(2)).",
                    ),
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(
                        Condition("materials_applied", "includes_any", ("on_farm_compost", "vermicompost")),
                        Condition("compost_method", "eq", "windrow"),
                    ),
                    compiles_to=CompileRule(template="Number of windrow turnings: {answer}."),
                ),
                Question(
                    key="vermicompost_moisture",
                    kind="text",
                    label=text(
                        "Vermicompost: moisture content maintained (aerobic, 70–90%)",
                        "Vermicompostaje: contenido de humedad mantenido (aeróbico, 70–90%)",
                    ),
                    coaching=text(
                        "Worm-based systems are judged on aerobic conditions and moisture, "
                        "not thermophilic temperature.",
                        "Los sistemas con lombrices se evalúan por condiciones aeróbicas y "
                        "humedad, no por temperatura termófila.",
                    ),
                    required=False,
                    visible_when=(Condition(question="materials_applied", op="includes", value="vermicompost"),),
                    compiles_to=CompileRule(template="Vermicompost moisture management: {answer}."),
                ),
                Question(
                    key="compost_temp_logs_kept",
                    kind="boolean",
                    label=text(
                        "Do you keep temperature logs for each compost batch?",
                        "¿Conservas registros de temperatura de cada lote de compost?",
                    ),
                    coaching=text(
                        "Temperature logs are the certifier's evidence that a batch met the "
                        "time/temperature standard — keep one dated log per batch with "
                        "readings through the full holding period.",
                        "Los registros de temperatura son la evidencia del certificador de que un lote cumplió el "
                        "estándar de tiempo/temperatura — conserva un registro fechado por lote con lecturas "
                        "durante todo el período de retención.",
                    ),
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(Condition("materials_applied", "includes_any", ("on_farm_compost", "vermicompost")),),
                    compiles_to=CompileRule(template="Temperature logs kept for each compost batch: {answer}."),
                ),
                Question(
                    key="purchased_compost_documentation",
                    kind="boolean",
                    label=text(
                        "Do you keep supplier documentation (process description and/or "
                        "analysis) for purchased compost on file?",
                        "¿Conservas la documentación del proveedor (descripción del proceso y/o análisis) del "
                        "compost comprado?",
                    ),
                    coaching=text(
                        "Ask the supplier for a written description of their composting "
                        "process (feedstocks, C:N ratio, time/temperature record) or a lab "
                        "analysis, so the certifier can confirm the product meets § 205.2 "
                        "without inspecting the supplier's site.",
                        "Solicita al proveedor una descripción escrita de su proceso de compostaje (materia prima, "
                        "relación C:N, registro de tiempo/temperatura) o un análisis de laboratorio, para que el "
                        "certificador pueda confirmar que el producto cumple con § 205.2 sin inspeccionar el sitio "
                        "del proveedor.",
                    ),
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(Condition("materials_applied", "includes", "purchased_compost"),),
                    compiles_to=CompileRule(template="Supplier documentation on file for purchased compost: {answer}."),
                ),
                Question(
                    key="purchased_compost_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Upload supplier documentation",
                        "Adjuntar documentación del proveedor",
                    ),
                    coaching=text(
                        "Attach the process description or lab analysis from your compost " "supplier.",
                        "Adjunta la descripción del proceso o el análisis de laboratorio de tu proveedor de "
                        "compost.",
                    ),
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(
                        Condition("materials_applied", "includes", "purchased_compost"),
                        Condition("purchased_compost_documentation", "truthy"),
                    ),
                ),
                Question(
                    # OTCO C4 4.4-1 ("does / does not contain manure"); CCOF G4.0 A2's compost split.
                    key="compost_contains_manure",
                    kind="radio",
                    label=text(
                        "Does the compost you make contain manure or other animal materials?",
                        "¿El compost que produces contiene estiércol u otros materiales animales?",
                    ),
                    required=False,
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(Condition("materials_applied", "includes", "on_farm_compost"),),
                    compiles_to=CompileRule(template="Compost made on this farm contains manure: {answer}."),
                    options=(
                        Option(
                            "contains_manure",
                            text(
                                "Yes, it contains manure or animal materials",
                                "Sí, contiene estiércol o materiales animales",
                            ),
                        ),
                        Option(
                            "plant_materials_only", text("No, plant materials only", "No, solo materiales vegetales")
                        ),
                    ),
                ),
                Question(
                    # CCOF G4.1 A2 (what you PRODUCE); WSDA AGR 2121 D7.
                    key="compost_tea_made_on_farm",
                    kind="boolean",
                    label=text(
                        "Do you make the compost tea or liquid extract yourself?",
                        "¿Produces tú mismo el té de compost o extracto líquido?",
                    ),
                    required=False,
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(Condition("materials_applied", "includes", "compost_tea"),),
                    compiles_to=CompileRule(template="Compost tea made on this farm: {answer}."),
                ),
                Question(
                    # CCOF G4.1 A2; WSDA AGR 2121 D10.
                    key="vermicompost_made_on_farm",
                    kind="boolean",
                    label=text("Do you make the vermicompost yourself?", "¿Produces tú mismo el vermicompost?"),
                    required=False,
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(Condition("materials_applied", "includes", "vermicompost"),),
                    compiles_to=CompileRule(template="Vermicompost made on this farm: {answer}."),
                ),
                Question(
                    # CCOF G4.1 A2a; OTCO C4 4.4-2; WSDA AGR 2121 D8 and D11.
                    key="compost_feedstocks",
                    kind="checkbox_group",
                    label=text(
                        "Which feedstocks go into the compost, compost tea or vermicompost you make?",
                        "¿Qué materias primas usas en el compost, té de compost o vermicompost que produces?",
                    ),
                    required=False,
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(
                        Condition(
                            "materials_applied", "includes_any", ("on_farm_compost", "vermicompost", "compost_tea")
                        ),
                    ),
                    compiles_to=CompileRule(template="Compost feedstocks: {answer}."),
                    options=(
                        Option(
                            "manure_animal",
                            text("Manure or other animal materials", "Estiércol u otros materiales animales"),
                        ),
                        Option("plant_materials", text("Plant materials", "Materiales vegetales")),
                        Option(
                            "recycled_paper",
                            text(
                                "Newspaper or other recycled paper without glossy or colored ink",
                                "Periódico u otro papel reciclado sin tinta brillante o de color",
                            ),
                        ),
                        Option("other", text("Other", "Otra")),
                    ),
                ),
                Question(
                    key="compost_feedstocks_detail",
                    kind="textarea",
                    label=text(
                        "List the ingredients of each product you make (one list per compost, tea or vermicompost)",
                        "Lista los ingredientes de cada producto que elaboras (una lista por compost, té o "
                        "vermicompost)",
                    ),
                    required=False,
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(
                        Condition(
                            "materials_applied", "includes_any", ("on_farm_compost", "vermicompost", "compost_tea")
                        ),
                    ),
                    compiles_to=CompileRule(template="Compost ingredients: {answer}"),
                ),
                Question(
                    # OTCO C4 4.4-4 names three logs and asks where they are kept.
                    key="compost_logs_kept",
                    kind="checkbox_group",
                    label=text(
                        "Besides the temperature log, which composting logs do you keep?",
                        "Además del registro de temperatura, ¿qué registros de compostaje conservas?",
                    ),
                    required=False,
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(
                        Condition(
                            "materials_applied", "includes_any", ("on_farm_compost", "vermicompost", "compost_tea")
                        ),
                    ),
                    compiles_to=CompileRule(template="Composting logs kept besides temperature: {answer}."),
                    options=(
                        Option("turning", text("Turning log", "Registro de volteos")),
                        Option("moisture", text("Moisture log", "Registro de humedad")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                Question(
                    key="compost_logs_location",
                    kind="text",
                    label=text("Where are the logs kept?", "¿Dónde se guardan los registros?"),
                    required=False,
                    visible_when=(
                        Condition(
                            "materials_applied", "includes_any", ("on_farm_compost", "vermicompost", "compost_tea")
                        ),
                    ),
                    compiles_to=CompileRule(template="Composting logs are kept: {answer}."),
                ),
                Question(
                    # WSDA AGR 2121 D9: the gate before its time-and-temperature question.
                    key="compost_applied_inside_interval",
                    kind="boolean",
                    label=text(
                        "Do you apply compost you make that contains manure to crops for human consumption less "
                        "than 90 or 120 days before harvest?",
                        "¿Aplicas compost que produces y que contiene estiércol a cultivos para consumo humano "
                        "menos de 90 o 120 días antes de la cosecha?",
                    ),
                    required=False,
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(Condition("materials_applied", "includes", "on_farm_compost"),),
                    compiles_to=CompileRule(
                        template="Compost containing manure applied less than 90 or 120 days before harvest: {answer}."
                    ),
                ),
                Question(
                    # CCOF G4.1 A2c; WSDA AGR 2121 D12a.
                    key="vermicompost_conditions_met",
                    kind="radio",
                    label=text(
                        "For vermicompost containing manure: are aerobic conditions and 70 to 90% moisture kept, "
                        "and does it run long enough that the finished product does not contaminate crops, soil "
                        "or water?",
                        "Para vermicompost con estiércol: ¿se mantienen condiciones aeróbicas y 70 a 90% de "
                        "humedad, y dura lo suficiente para que el producto final no contamine cultivos, suelo o "
                        "agua?",
                    ),
                    coaching=text(
                        "If you answer No, also mark raw manure on page A, so the raw-manure questions open.",
                        "Si respondes No, marca también estiércol crudo en la página A, para que se abran las "
                        "preguntas de estiércol crudo.",
                    ),
                    required=False,
                    nop_cite="§ 205.203(c)",
                    visible_when=(Condition("materials_applied", "includes", "vermicompost"),),
                    compiles_to=CompileRule(
                        template="Vermicompost containing manure, its conditions and production records: {answer}."
                    ),
                    options=(
                        Option(
                            "no_manure",
                            text(
                                "Not applicable: our vermicompost contains no manure",
                                "No aplica: nuestro vermicompost no contiene estiércol",
                            ),
                        ),
                        Option(
                            "conditions_met",
                            text(
                                "Yes, and production records and any test results are kept",
                                "Sí, y se conservan registros de producción y resultados de análisis",
                            ),
                        ),
                        Option(
                            "does_not_meet",
                            text(
                                "No, so the vermicompost is treated as raw manure",
                                "No, así que el vermicompost se trata como estiércol crudo",
                            ),
                        ),
                    ),
                ),
                Question(
                    # WSDA AGR 2121 D12.
                    key="vermicompost_applied_inside_interval",
                    kind="boolean",
                    label=text(
                        "Do you apply vermicompost you make that contains manure to crops for human consumption "
                        "less than 90 or 120 days before harvest?",
                        "¿Aplicas vermicompost que produces y que contiene estiércol a cultivos para consumo "
                        "humano menos de 90 o 120 días antes de la cosecha?",
                    ),
                    required=False,
                    nop_cite="§ 205.203(c)",
                    visible_when=(Condition("materials_applied", "includes", "vermicompost"),),
                    compiles_to=CompileRule(
                        template="Vermicompost containing manure applied less than 90 or 120 days before harvest: "
                        "{answer}."
                    ),
                ),
            ),
        ),
        ModulePage(
            # WSDA AGR 2121 D14: "Optional space for additional information".
            key="d_notes",
            title=text("D. Additional information", "D. Información adicional"),
            questions=(
                Question(
                    key="soil_fertility_additional_notes",
                    kind="textarea",
                    label=text(
                        "Anything else about your soil fertility, compost or manure the certifier should know",
                        "Cualquier otra cosa sobre la fertilidad del suelo, el compost o el estiércol que el "
                        "certificador deba saber",
                    ),
                    required=False,
                    compiles_to=CompileRule(
                        template="Additional information on soil fertility, compost and manure: {answer}"
                    ),
                ),
            ),
        ),
    ),
)
