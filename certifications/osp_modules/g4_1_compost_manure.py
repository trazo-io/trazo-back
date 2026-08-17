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
            title=text("A. What you apply", "A. Qué aplica"),
            questions=(
                Question(
                    key="materials_applied",
                    kind="checkbox_group",
                    prefill=Prefill(source="manure_compost_evidence"),
                    label=text(
                        "Which compost, manure, or animal-based soil inputs do you apply?",
                        "¿Qué insumos de compost, estiércol o de origen animal aplica?",
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
            title=text("B. Raw manure", "B. Estiércol crudo"),
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
            visible_when=(Condition("materials_applied", "includes", "raw_manure"),),
            questions=(
                Question(
                    key="raw_manure_interval_rule",
                    kind="radio",
                    label=text(
                        "Which application rule applies to your raw manure use?",
                        "¿Qué regla de aplicación corresponde al uso de estiércol crudo?",
                    ),
                    coaching=text(
                        "Choose the rule that matches how the manure is actually used — it "
                        "sets the minimum number of days between application and harvest.",
                        "Elija la regla que corresponde al uso real del estiércol — determina "
                        "el número mínimo de días entre la aplicación y la cosecha.",
                    ),
                    nop_cite="§ 205.203(c)(1)",
                    compiles_to=CompileRule(template="Raw manure is applied with {answer}."),
                    options=(
                        Option(
                            "non_food_crop",
                            text(
                                "Applied only to land growing crops not intended for human "
                                "consumption (no waiting interval required)",
                                "Aplicado solo en tierra que produce cultivos no destinados al "
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
                    ),
                ),
                Question(
                    key="raw_manure_timing_detail",
                    kind="text",
                    label=text(
                        "Describe your typical raw manure application timing",
                        "Describa el momento típico de aplicación de estiércol crudo",
                    ),
                    coaching=text(
                        "Note the crop, the season you apply, and how many days before harvest "
                        "— Trazo's soil and input events carry the application and harvest "
                        "dates that prove this interval.",
                        "Indique el cultivo, la temporada de aplicación y cuántos días antes de "
                        "la cosecha — los eventos de suelo e insumos de Trazo registran las "
                        "fechas de aplicación y cosecha que demuestran este intervalo.",
                    ),
                    nop_cite="§ 205.203(c)(1)",
                    compiles_to=CompileRule(template="Typical raw manure application timing: {answer}."),
                ),
                Question(
                    key="raw_manure_water_risk",
                    kind="textarea",
                    label=text(
                        "How do you prevent raw manure from contaminating water sources " "(runoff, wells, waterways)?",
                        "¿Cómo evita que el estiércol crudo contamine fuentes de agua " "(escorrentía, pozos, cauces)?",
                    ),
                    required=False,
                    visible_when=(Condition(question="materials_applied", op="includes", value="raw_manure"),),
                    compiles_to=CompileRule(template="Raw manure water-contamination prevention: {answer}."),
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
                    "El vermicompost y el compost comprado se rigen por el mismo estándar. Si "
                    "un proceso de vermicompostaje no alcanza estos umbrales de "
                    "tiempo/temperatura y la materia prima incluye estiércol animal, se trata "
                    "como estiércol crudo y aplica la regla de intervalo de la página "
                    "anterior. Para el compost comprado, la documentación del proveedor "
                    "sustituye sus propios registros de producción.",
                ),
            ),
            visible_when=(
                Condition(
                    "materials_applied",
                    "includes_any",
                    ("on_farm_compost", "vermicompost", "purchased_compost"),
                ),
            ),
            questions=(
                Question(
                    key="compost_method",
                    kind="radio",
                    label=text(
                        "Which compost production method do you use?",
                        "¿Qué método de producción de compost utiliza?",
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
                    ),
                ),
                Question(
                    key="compost_initial_cn_ratio",
                    kind="text",
                    label=text(
                        "What was the initial carbon:nitrogen (C:N) ratio of your feedstock?",
                        "¿Cuál fue la relación carbono:nitrógeno (C:N) inicial de su materia " "prima?",
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
                    visible_when=(Condition("materials_applied", "includes_any", ("on_farm_compost", "vermicompost")),),
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
                        "¿Conserva registros de temperatura de cada lote de compost?",
                    ),
                    coaching=text(
                        "Temperature logs are the certifier's evidence that a batch met the "
                        "time/temperature standard — keep one dated log per batch with "
                        "readings through the full holding period.",
                        "Los registros de temperatura son la evidencia del certificador de que "
                        "un lote cumplió el estándar de tiempo/temperatura — conserve un "
                        "registro fechado por lote con lecturas durante todo el período de "
                        "retención.",
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
                        "¿Conserva la documentación del proveedor (descripción del proceso y/o "
                        "análisis) del compost comprado?",
                    ),
                    coaching=text(
                        "Ask the supplier for a written description of their composting "
                        "process (feedstocks, C:N ratio, time/temperature record) or a lab "
                        "analysis, so the certifier can confirm the product meets § 205.2 "
                        "without inspecting the supplier's site.",
                        "Solicite al proveedor una descripción escrita de su proceso de "
                        "compostaje (materia prima, relación C:N, registro de "
                        "tiempo/temperatura) o un análisis de laboratorio, para que el "
                        "certificador pueda confirmar que el producto cumple con § 205.2 sin "
                        "inspeccionar el sitio del proveedor.",
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
                        "Adjunte la descripción del proceso o el análisis de laboratorio de su "
                        "proveedor de compost.",
                    ),
                    nop_cite="§ 205.203(c)(2)",
                    visible_when=(
                        Condition("materials_applied", "includes", "purchased_compost"),
                        Condition("purchased_compost_documentation", "truthy"),
                    ),
                ),
            ),
        ),
    ),
)
