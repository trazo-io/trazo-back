"""
G4.0 — Rotation & Soil Management.

Sources: 7 CFR 205.203 (soil fertility and crop nutrient management practice standard),
205.205 (crop rotation practice standard), 205.2 (definitions). Perennial systems satisfy
§ 205.205 through practices "in lieu of" rotation (alley cropping, intercropping, hedgerows) —
load-bearing for Trazo's orchard ICP, so that path is first-class here, not a footnote.

Evidence sources: SoilManagementEvent (CC cover crop, TI tillage, CO composting, OM organic
matter, ST soil test) feed the prefill suggestions.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Prefill, Question, text

G4_0_ROTATION_SOIL = Module(
    key="g4_0_rotation_soil",
    code="G4.0",
    title=text("Rotation & Soil Management", "Rotación y manejo del suelo"),
    nop_cites=("§ 205.203", "§ 205.205", "§ 205.2"),
    education=(
        text(
            "Crop nutrients and soil fertility must be managed through rotations, cover "
            "crops, and applied plant and animal materials, managed so they do not "
            "contaminate crops, soil, or water (§ 205.203). Tillage and cultivation must "
            "maintain or improve the physical, chemical, and biological condition of the "
            "soil and minimize erosion (§ 205.203(a)).",
            "Los nutrientes y la fertilidad del suelo deben manejarse mediante rotaciones, "
            "cultivos de cobertura y materiales vegetales y animales aplicados, manejados "
            "de modo que no contaminen cultivos, suelo o agua (§ 205.203). La labranza y el "
            "cultivo deben mantener o mejorar la condición física, química y biológica del "
            "suelo y minimizar la erosión (§ 205.203(a)).",
        ),
    ),
    allows_not_applicable=False,
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_rotation",
            title=text("A. Crop rotation (or practices in lieu)", "A. Rotación de cultivos (o prácticas equivalentes)"),
            education=(
                text(
                    "Annual systems: describe the planned sequence of plant families, cover "
                    "crops, and fallow periods, and the length of the full rotation. "
                    "Perennial and container systems: § 205.205 is met through practices "
                    "that introduce biological diversity in lieu of rotation — ground "
                    "covers, alley cropping, intercropping, hedgerows.",
                    "Sistemas anuales: describa la secuencia planificada de familias "
                    "vegetales, cultivos de cobertura y períodos de barbecho, y la duración "
                    "de la rotación completa. Sistemas perennes y en contenedor: § 205.205 "
                    "se cumple con prácticas que introducen diversidad biológica en lugar "
                    "de rotación — coberturas, cultivos en callejones, intercultivos, "
                    "cercos vivos.",
                ),
            ),
            questions=(
                Question(
                    key="system_type",
                    kind="checkbox_group",
                    label=text(
                        "Which cropping systems does this operation run?",
                        "¿Qué sistemas de cultivo tiene esta operación?",
                    ),
                    nop_cite="§ 205.205",
                    options=(
                        Option("annual", text("Annual crops", "Cultivos anuales")),
                        Option(
                            "perennial",
                            text("Perennial crops (orchard, vineyard)", "Cultivos perennes (huerto, viñedo)"),
                        ),
                        Option(
                            "container",
                            text("Container or greenhouse production", "Producción en contenedor o invernadero"),
                        ),
                    ),
                ),
                Question(
                    key="rotation_plan",
                    kind="textarea",
                    label=text(
                        "Describe your crop rotation plan for annual crops",
                        "Describa su plan de rotación para cultivos anuales",
                    ),
                    coaching=text(
                        "Include the sequence of plant families, cover crops and fallow "
                        "periods, the length of each stage, and the total time to complete "
                        "the rotation.",
                        "Incluya la secuencia de familias vegetales, cultivos de cobertura y "
                        "barbechos, la duración de cada etapa y el tiempo total de la "
                        "rotación.",
                    ),
                    nop_cite="§ 205.205",
                    visible_when=(Condition("system_type", "includes", "annual"),),
                    compiles_to=CompileRule(template="Crop rotation plan (annual crops): {answer}"),
                ),
                Question(
                    key="in_lieu_practices",
                    kind="checkbox_group",
                    label=text(
                        "Practices that introduce biological diversity in lieu of rotation "
                        "(perennial / container systems)",
                        "Prácticas que introducen diversidad biológica en lugar de rotación "
                        "(sistemas perennes / en contenedor)",
                    ),
                    nop_cite="§ 205.205",
                    prefill=Prefill(source="cover_crop_evidence"),
                    visible_when=(Condition("system_type", "includes", "perennial"),),
                    compiles_to=CompileRule(template="Biological diversity in lieu of rotation: {answer}."),
                    options=(
                        Option(
                            "ground_cover",
                            text("Permanent or seasonal ground cover", "Cobertura permanente o estacional"),
                        ),
                        Option("cover_crops", text("Cover crops between rows", "Cultivos de cobertura entre hileras")),
                        Option(
                            "alley_cropping",
                            text("Alley cropping / intercropping", "Cultivo en callejones / intercultivo"),
                        ),
                        Option(
                            "hedgerows",
                            text("Hedgerows or insectary plantings", "Cercos vivos o plantaciones insectarias"),
                        ),
                        Option(
                            "short_term_rotation",
                            text(
                                "Rotation plan for short-term perennials",
                                "Plan de rotación para perennes de ciclo corto",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describa abajo)")),
                    ),
                ),
                Question(
                    key="in_lieu_other",
                    kind="text",
                    label=text("Describe the other practice", "Describa la otra práctica"),
                    visible_when=(Condition("in_lieu_practices", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional diversity practice: {answer}."),
                ),
            ),
        ),
        ModulePage(
            key="b_fertility",
            title=text("B. Soil fertility & nutrient management", "B. Fertilidad del suelo y manejo de nutrientes"),
            questions=(
                Question(
                    key="fertility_components",
                    kind="checkbox_group",
                    label=text(
                        "Major components of your soil fertility and crop nutrient plan",
                        "Componentes principales de su plan de fertilidad y nutrición",
                    ),
                    nop_cite="§ 205.203(b)-(c)",
                    prefill=Prefill(source="soil_amendment_evidence"),
                    compiles_to=CompileRule(template="Soil fertility is managed through: {answer}."),
                    options=(
                        Option(
                            "crop_residue",
                            text("Incorporation of crop residue", "Incorporación de residuos de cosecha"),
                        ),
                        Option(
                            "cover_crops", text("Cover crops / green manures", "Cultivos de cobertura / abonos verdes")
                        ),
                        Option("compost", text("Compost", "Compost")),
                        Option("manure", text("Manure (see module G4.1)", "Estiércol (ver módulo G4.1)")),
                        Option(
                            "mined_minerals",
                            text("Mined minerals (gypsum, limestone)", "Minerales extraídos (yeso, caliza)"),
                        ),
                        Option(
                            "blended_fertilizers",
                            text("Blended or foliar fertilizers", "Fertilizantes mezclados o foliares"),
                        ),
                        Option(
                            "plant_materials", text("Plant materials / mulches", "Materiales vegetales / coberturas")
                        ),
                        Option("inoculants", text("Soil inoculants", "Inoculantes de suelo")),
                        Option(
                            "fertigation",
                            text(
                                "Side-dress or drip (fertigation) applications",
                                "Aplicaciones laterales o por goteo (fertirrigación)",
                            ),
                        ),
                        Option("rotation", text("Crop rotation", "Rotación de cultivos")),
                    ),
                ),
                Question(
                    key="fertility_inputs_listed",
                    kind="boolean",
                    label=text(
                        "Are all fertility materials you apply included on your OSP inputs " "list?",
                        "¿Todos los materiales de fertilidad que aplica están en su lista de " "insumos del OSP?",
                    ),
                    nop_cite="§ 205.201(a)(2)",
                    compiles_to=CompileRule(
                        template="All fertility materials on the OSP inputs list: {answer}.",
                        section_key="inputs_list",
                    ),
                ),
                Question(
                    key="tillage_practices",
                    kind="textarea",
                    label=text(
                        "Describe your tillage and cultivation practices in season order",
                        "Describa sus prácticas de labranza y cultivo en orden de temporada",
                    ),
                    coaching=text(
                        "Explain how each practice maintains or improves soil condition and "
                        "minimizes erosion (§ 205.203(a)).",
                        "Explique cómo cada práctica mantiene o mejora la condición del "
                        "suelo y minimiza la erosión (§ 205.203(a)).",
                    ),
                    nop_cite="§ 205.203(a)",
                    prefill=Prefill(source="tillage_evidence"),
                    compiles_to=CompileRule(template="Tillage and cultivation practices: {answer}"),
                ),
            ),
        ),
        ModulePage(
            key="c_monitoring",
            title=text("C. Monitoring", "C. Monitoreo"),
            questions=(
                Question(
                    key="fertility_monitoring",
                    kind="checkbox_group",
                    label=text(
                        "How do you monitor the effectiveness of your fertility plan?",
                        "¿Cómo monitorea la eficacia de su plan de fertilidad?",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(
                        template="Fertility effectiveness monitored via: {answer}.",
                        section_key="monitoring_plan",
                    ),
                    options=(
                        Option("soil_tests", text("Soil tests", "Análisis de suelo")),
                        Option("tissue_tests", text("Leaf / tissue tests", "Análisis foliar / de tejido")),
                        Option(
                            "organic_matter", text("Soil organic matter tracking", "Seguimiento de materia orgánica")
                        ),
                        Option(
                            "crop_observation",
                            text("Crop health and yield observation", "Observación de sanidad y rendimiento"),
                        ),
                        Option(
                            "no_testing",
                            text("No laboratory testing performed", "No se realizan análisis de laboratorio"),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="monitoring_frequency",
                    kind="radio",
                    label=text("How often is monitoring performed?", "¿Con qué frecuencia monitorea?"),
                    visible_when=(
                        Condition("fertility_monitoring", "truthy"),
                        Condition("fertility_monitoring", "not_includes", "no_testing"),
                    ),
                    compiles_to=CompileRule(
                        template="Monitoring frequency: {answer}.",
                        section_key="monitoring_plan",
                    ),
                    options=(
                        Option("annually", text("Annually", "Anualmente")),
                        Option("seasonally", text("Each season", "Cada temporada")),
                        Option("monthly", text("Monthly", "Mensualmente")),
                        Option("as_needed", text("As needed", "Según necesidad")),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="d_erosion",
            title=text("D. Erosion control", "D. Control de erosión"),
            questions=(
                Question(
                    key="erosion_practices",
                    kind="checkbox_group",
                    label=text(
                        "Practices used to prevent or minimize erosion",
                        "Prácticas para prevenir o minimizar la erosión",
                    ),
                    nop_cite="§ 205.203(a)",
                    compiles_to=CompileRule(template="Erosion is controlled through: {answer}."),
                    options=(
                        Option(
                            "no_erosion",
                            text(
                                "Not applicable — no erosion risk on these parcels",
                                "No aplica — sin riesgo de erosión en estas parcelas",
                            ),
                            exclusive=True,
                        ),
                        Option(
                            "permanent_cover",
                            text("No-till or permanent cover", "Labranza cero o cobertura permanente"),
                        ),
                        Option("cover_cropping", text("Cover cropping", "Cultivos de cobertura")),
                        Option("contour", text("Contour farming or terraces", "Cultivo en contorno o terrazas")),
                        Option(
                            "conservation_tillage",
                            text("Conservation (minimum) tillage", "Labranza de conservación (mínima)"),
                        ),
                        Option("micro_irrigation", text("Micro-irrigation management", "Manejo de microirrigación")),
                        Option("windbreaks", text("Windbreaks", "Cortavientos")),
                    ),
                ),
            ),
        ),
    ),
)
