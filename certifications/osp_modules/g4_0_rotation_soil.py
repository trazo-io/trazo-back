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

#: WSDA AGR 2121 D4a's options, with its "Soil or tissue analysis" split in two: § 205.601(j)(6) needs a
#: SOIL deficiency for magnesium sulfate, so which of the two was done matters. Both map back to WSDA's
#: single option on WSDA's coverage rows.
DEFICIENCY_VERIFICATION = (
    Option("soil_analysis", text("Soil analysis", "Análisis de suelo")),
    Option("tissue_analysis", text("Tissue analysis", "Análisis de tejido")),
    Option(
        "crop_advisor",
        text("Recommendations from a crop advisor", "Recomendaciones de un asesor de cultivos"),
    ),
    Option(
        "regional_deficiency",
        text("Documented regional deficiency", "Deficiencia regional documentada"),
    ),
    Option("visual_observation", text("Visual observation", "Observación visual")),
    Option("other", text("Other (describe below)", "Otro (describe abajo)")),
)

#: The methods § 205.601(j)(7) accepts only "as approved by the certifying agent".
NON_TEST_METHODS = ("crop_advisor", "regional_deficiency", "visual_observation", "other")

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
                    "Sistemas anuales: describe la secuencia planificada de familias vegetales, cultivos de "
                    "cobertura y períodos de barbecho, y la duración de la rotación completa. Sistemas perennes y "
                    "en contenedor: § 205.205 se cumple con prácticas que introducen diversidad biológica en lugar "
                    "de rotación — coberturas, cultivos en callejones, intercultivos, cercos vivos.",
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
                        "Describe tu plan de rotación para cultivos anuales",
                    ),
                    coaching=text(
                        "Include the sequence of plant families, cover crops and fallow "
                        "periods, the length of each stage, and the total time to complete "
                        "the rotation.",
                        "Incluye la secuencia de familias vegetales, cultivos de cobertura y barbechos, la duración "
                        "de cada etapa y el tiempo total de la rotación.",
                    ),
                    nop_cite="§ 205.205",
                    visible_when=(Condition("system_type", "includes", "annual"),),
                    compiles_to=CompileRule(template="Crop rotation plan (annual crops): {answer}"),
                ),
                # 2026-11-15: WSDA AGR 2121 E 1b asks the records kept of the rotation, apart from the plan itself.
                Question(
                    key="rotation_records_kept",
                    kind="textarea",
                    required=False,
                    label=text(
                        "What records do you keep of your crop rotation?",
                        "¿Qué registros llevas de tu rotación de cultivos?",
                    ),
                    placeholder=text(
                        "e.g. the seasons in Trazo show what was planted in each block and when; a field map for each "
                        "year",
                        "p. ej. las temporadas en Trazo muestran qué se sembró en cada bloque y cuándo; un mapa de campo "
                        "de cada año",
                    ),
                    visible_when=(Condition("system_type", "includes", "annual"),),
                    nop_cite="§ 205.205",
                    compiles_to=CompileRule(template="Records kept of the crop rotation: {answer}"),
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
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="in_lieu_other",
                    kind="text",
                    label=text("Describe the other practice", "Describe la otra práctica"),
                    visible_when=(Condition("in_lieu_practices", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional diversity practice: {answer}."),
                ),
            ),
        ),
        ModulePage(
            key="b_fertility",
            title=text("B. Soil fertility & nutrient management", "B. Fertilidad del suelo y manejo de nutrientes"),
            questions=(
                # 2026-11-15: WSDA AGR 2121 E 11 asks it as a yes or no before its nutrient water-quality list; the
                # components below include practices (rotation, fallow) that apply nothing, so they cannot say it.
                Question(
                    key="applies_fertilizers",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Do you apply fertilizers or other nutrients to the certified land?",
                        "¿Aplicas fertilizantes u otros nutrientes en la tierra certificada?",
                    ),
                    nop_cite="§ 205.203",
                    compiles_to=CompileRule(
                        template="Fertilizers or other nutrients are applied to the certified land ({answer}).",
                        template_false="No fertilizer or other nutrient is applied to the certified land.",
                    ),
                ),
                Question(
                    key="fertility_components",
                    kind="checkbox_group",
                    label=text(
                        "Major components of your soil fertility and crop nutrient plan",
                        "Componentes principales de tu plan de fertilidad y nutrición",
                    ),
                    nop_cite="§ 205.203(b)-(c)",
                    prefill=Prefill(source="soil_amendment_evidence"),
                    compiles_to=CompileRule(template="Soil fertility is managed through: {answer}."),
                    options=(
                        Option(
                            "biodynamic_preparations",
                            text("Biodynamic preparations", "Preparados biodinámicos"),
                        ),
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
                        # CCOF G4.0 A2 and WSDA AGR 2121 D2 name these; "other" lets a practice outside the
                        # list be stated instead of left out.
                        Option("compost_tea", text("Compost tea", "Té de compost")),
                        Option("fallow", text("Fallow rotations", "Rotaciones con barbecho")),
                        Option(
                            "conservation_cover",
                            text("Perennial conservation cover", "Cobertura de conservación perenne"),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="fertility_components_other",
                    kind="text",
                    label=text("Other fertility practice", "Otra práctica de fertilidad"),
                    required=False,
                    visible_when=(Condition("fertility_components", "includes", "other"),),
                    compiles_to=CompileRule(template="Other soil fertility practice: {answer}."),
                ),
                Question(
                    key="fertility_inputs_listed",
                    kind="boolean",
                    label=text(
                        "Are all fertility materials you apply included on your OSP inputs " "list?",
                        "¿Todos los materiales de fertilidad que aplicas están en tu lista de insumos del OSP?",
                    ),
                    nop_cite="§ 205.201(a)(2)",
                    compiles_to=CompileRule(
                        template="All fertility materials on the OSP inputs list: {answer}.",
                        section_key="inputs_list",
                    ),
                ),
                # WSDA AGR 2121 D4-D6a and OTCO C4 4.5-1: the National List materials allowed only under a
                # condition the grower has to meet (§ 205.601(j)(6), (j)(7); § 205.602(c), (e)). The module
                # PDF prints the rule's own words beside each answer and the plan's materials of that class
                # (certifications/services/restricted_materials.py). Options come from WSDA's form; the rule
                # is applied when the page is printed, never by narrowing what the grower can say.
                Question(
                    key="applies_deficiency_materials",
                    kind="boolean",
                    prefill=Prefill(source="deficiency_materials_evidence"),
                    label=text(
                        "Do you apply synthetic micronutrients or magnesium sulfate to manage plant or soil "
                        "deficiencies?",
                        "¿Aplicas micronutrientes sintéticos o sulfato de magnesio para corregir deficiencias de las "
                        "plantas o del suelo?",
                    ),
                    nop_cite="§ 205.601(j)(6)-(7)",
                    compiles_to=CompileRule(
                        template="Synthetic micronutrients or magnesium sulfate are applied to manage plant or soil "
                        "deficiencies.",
                        template_false="Synthetic micronutrients and magnesium sulfate are not applied.",
                        section_key="inputs_list",
                    ),
                ),
                Question(
                    key="deficiency_materials",
                    kind="checkbox_group",
                    label=text("Which of them?", "¿Cuáles?"),
                    visible_when=(Condition("applies_deficiency_materials", "truthy"),),
                    compiles_to=CompileRule(
                        template="Deficiency materials applied: {answer}.", section_key="inputs_list"
                    ),
                    options=(
                        Option(
                            "micronutrients",
                            text(
                                "Synthetic micronutrients (boron, zinc, copper, iron, manganese, molybdenum, selenium, "
                                "cobalt)",
                                "Micronutrientes sintéticos (boro, zinc, cobre, hierro, manganeso, molibdeno, selenio, "
                                "cobalto)",
                            ),
                        ),
                        Option("magnesium_sulfate", text("Magnesium sulfate", "Sulfato de magnesio")),
                    ),
                ),
                Question(
                    key="micronutrient_verification",
                    kind="checkbox_group",
                    label=text(
                        "How do you verify the micronutrient deficiency of each crop or field before you apply?",
                        "¿Cómo verificas la deficiencia de micronutrientes de cada cultivo o campo antes de aplicar?",
                    ),
                    nop_cite="§ 205.601(j)(7)",
                    visible_when=(Condition("deficiency_materials", "includes", "micronutrients"),),
                    compiles_to=CompileRule(
                        template="Micronutrient deficiency verified before application by: {answer}.",
                        section_key="inputs_list",
                    ),
                    options=DEFICIENCY_VERIFICATION,
                ),
                Question(
                    key="micronutrient_verification_other",
                    kind="text",
                    label=text("Describe the other method", "Describe el otro método"),
                    required=False,
                    visible_when=(Condition("micronutrient_verification", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Other micronutrient verification method: {answer}.", section_key="inputs_list"
                    ),
                ),
                Question(
                    key="micronutrient_method_agent_approval",
                    kind="radio",
                    label=text(
                        "Has your certifying agent approved that method?",
                        "¿Tu agencia certificadora aprobó ese método?",
                    ),
                    coaching=text(
                        "The rule accepts a method other than soil or tissue testing only as approved by the "
                        "certifying agent (§ 205.601(j)(7)).",
                        "La norma acepta un método distinto del análisis de suelo o de tejido solo si lo aprueba la "
                        "agencia certificadora (§ 205.601(j)(7)).",
                    ),
                    nop_cite="§ 205.601(j)(7)",
                    visible_when=(
                        Condition("deficiency_materials", "includes", "micronutrients"),
                        Condition("micronutrient_verification", "includes_any", list(NON_TEST_METHODS)),
                    ),
                    compiles_to=CompileRule(
                        template="Certifying agent approval of the verification method: {answer}.",
                        section_key="inputs_list",
                    ),
                    options=(
                        Option(
                            "approved_by_agent",
                            text(
                                "Approved by my certifying agent (in writing or in my approved OSP)",
                                "Aprobado por mi agencia certificadora (por escrito o en mi OSP aprobado)",
                            ),
                        ),
                        Option(
                            "for_agent_review",
                            text(
                                "Described here for my agent's approval",
                                "Lo describo aquí para que mi agencia lo apruebe",
                            ),
                            review=(
                                "§ 205.601(j)(7) accepts a method other than soil or tissue testing only as approved "
                                "by the certifying agent; the operator describes the method here for that approval."
                            ),
                        ),
                    ),
                ),
                Question(
                    key="magnesium_sulfate_verification",
                    kind="checkbox_group",
                    label=text(
                        "How do you verify the magnesium deficiency before you apply magnesium sulfate?",
                        "¿Cómo verificas la deficiencia de magnesio antes de aplicar sulfato de magnesio?",
                    ),
                    nop_cite="§ 205.601(j)(6)",
                    visible_when=(Condition("deficiency_materials", "includes", "magnesium_sulfate"),),
                    compiles_to=CompileRule(
                        template="Magnesium deficiency verified before applying magnesium sulfate by: {answer}.",
                        section_key="inputs_list",
                    ),
                    options=DEFICIENCY_VERIFICATION,
                ),
                Question(
                    key="magnesium_sulfate_verification_other",
                    kind="text",
                    label=text("Describe the other method", "Describe el otro método"),
                    required=False,
                    visible_when=(Condition("magnesium_sulfate_verification", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Other magnesium verification method: {answer}.", section_key="inputs_list"
                    ),
                ),
                Question(
                    key="applies_calcium_chloride",
                    kind="boolean",
                    prefill=Prefill(source="calcium_chloride_evidence"),
                    label=text(
                        "Do you apply calcium chloride in the field or orchard?",
                        "¿Aplicas cloruro de calcio en el campo o en el huerto?",
                    ),
                    coaching=text(
                        "A calcium chloride dip after harvest is handling, not field application.",
                        "Un baño con cloruro de calcio después de la cosecha es manejo poscosecha, no aplicación en "
                        "el campo.",
                    ),
                    nop_cite="§ 205.602(c)",
                    compiles_to=CompileRule(
                        template="Calcium chloride is applied in the field or orchard.",
                        template_false="Calcium chloride is not applied in the field or orchard.",
                        section_key="inputs_list",
                    ),
                ),
                Question(
                    key="calcium_chloride_foliar",
                    kind="boolean",
                    label=text("Is it applied as a foliar spray?", "¿Lo aplicas como aspersión foliar?"),
                    nop_cite="§ 205.602(c)",
                    visible_when=(Condition("applies_calcium_chloride", "truthy"),),
                    compiles_to=CompileRule(
                        template="Calcium chloride is applied as a foliar spray.",
                        template_false="Calcium chloride is not applied as a foliar spray.",
                        section_key="inputs_list",
                    ),
                ),
                Question(
                    key="calcium_chloride_disorder",
                    kind="text",
                    label=text(
                        "Which physiological disorder does it treat?",
                        "¿Qué trastorno fisiológico trata?",
                    ),
                    placeholder=text("e.g. bitter pit", "p. ej., bitter pit (mancha amarga)"),
                    nop_cite="§ 205.602(c)",
                    visible_when=(Condition("applies_calcium_chloride", "truthy"),),
                    compiles_to=CompileRule(
                        template="Physiological disorder calcium chloride treats: {answer}.",
                        section_key="inputs_list",
                    ),
                ),
                Question(
                    key="applies_potassium_chloride",
                    kind="boolean",
                    prefill=Prefill(source="potassium_chloride_evidence"),
                    label=text(
                        "Do you apply potassium chloride (muriate of potash)?",
                        "¿Aplicas cloruro de potasio (muriato de potasio)?",
                    ),
                    nop_cite="§ 205.602(e)",
                    compiles_to=CompileRule(
                        template="Potassium chloride is applied.",
                        template_false="Potassium chloride is not applied.",
                        section_key="inputs_list",
                    ),
                ),
                Question(
                    key="chloride_accumulation_practices",
                    kind="checkbox_group",
                    label=text(
                        "How do you keep chloride from building up in the soil?",
                        "¿Cómo evitas que el cloruro se acumule en el suelo?",
                    ),
                    nop_cite="§ 205.602(e)",
                    visible_when=(Condition("applies_potassium_chloride", "truthy"),),
                    compiles_to=CompileRule(
                        template="Chloride accumulation in the soil is kept down by: {answer}.",
                        section_key="inputs_list",
                    ),
                    options=(
                        Option(
                            "soil_chloride_tests",
                            text("Soil chloride monitored by testing", "Monitoreo del cloruro del suelo con análisis"),
                        ),
                        Option(
                            "rate_to_potassium_need",
                            text(
                                "Rate limited to the crop's potassium need",
                                "Dosis limitada a la necesidad de potasio del cultivo",
                            ),
                        ),
                        Option("split_applications", text("Split applications", "Aplicaciones divididas")),
                        Option(
                            "sensitive_blocks_avoided",
                            text("Chloride-sensitive blocks avoided", "Se evitan los bloques sensibles al cloruro"),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="chloride_accumulation_other",
                    kind="text",
                    label=text("Describe the other practice", "Describe la otra práctica"),
                    required=False,
                    visible_when=(Condition("chloride_accumulation_practices", "includes", "other"),),
                    compiles_to=CompileRule(template="Other chloride practice: {answer}.", section_key="inputs_list"),
                ),
                Question(
                    key="tillage_practices",
                    kind="textarea",
                    label=text(
                        "Describe your tillage and cultivation practices in season order",
                        "Describe tus prácticas de labranza y cultivo en orden de temporada",
                    ),
                    coaching=text(
                        "Explain how each practice maintains or improves soil condition and "
                        "minimizes erosion (§ 205.203(a)).",
                        "Explica cómo cada práctica mantiene o mejora la condición del suelo y minimiza la erosión "
                        "(§ 205.203(a)).",
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
                        "¿Cómo monitoreas la eficacia de tu plan de fertilidad?",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(
                        template="Fertility effectiveness monitored via: {answer}.",
                        section_key="monitoring_plan",
                    ),
                    options=(
                        Option("soil_tests", text("Soil tests", "Análisis de suelo"), evidence="soil_test_records"),
                        Option(
                            "tissue_tests",
                            text("Leaf / tissue tests", "Análisis foliar / de tejido"),
                            evidence="tissue_test_records",
                        ),
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
                        Option("soil_observation", text("Soil observation", "Observación del suelo")),
                        Option("crop_yield_comparison", text("Crop yield comparison", "Comparación de rendimientos")),
                        Option(
                            "crop_quality_analysis", text("Crop quality analysis", "Análisis de calidad del cultivo")
                        ),
                        Option("microbiological_testing", text("Microbiological testing", "Análisis microbiológico")),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="monitoring_frequency",
                    kind="radio",
                    label=text("How often is monitoring performed?", "¿Con qué frecuencia monitoreas?"),
                    # How often the operation monitors or observes; laboratory testing has its own
                    # frequency below (CCOF G4.0 B1a and B2a ask them apart). "No testing" is exclusive,
                    # so it stands alone and asks no frequency.
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
                        Option("daily", text("Daily", "Diariamente")),
                        Option("weekly", text("Weekly", "Semanalmente")),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="monitoring_frequency_other",
                    kind="text",
                    label=text("Other monitoring frequency", "Otra frecuencia de monitoreo"),
                    required=False,
                    visible_when=(Condition("monitoring_frequency", "eq", "other"),),
                    compiles_to=CompileRule(
                        template="Other monitoring frequency: {answer}.", section_key="monitoring_plan"
                    ),
                ),
                Question(
                    key="fertility_monitoring_other",
                    kind="text",
                    label=text("Other monitoring method", "Otro método de monitoreo"),
                    required=False,
                    visible_when=(Condition("fertility_monitoring", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Other fertility monitoring: {answer}.", section_key="monitoring_plan"
                    ),
                ),
                Question(
                    # CCOF G4.0 B2a (daily / weekly / monthly / annually / as needed / other); OTCO C4 4.6-2
                    # (with each crop / seasonally / annually / other).
                    key="fertility_testing_frequency",
                    kind="radio",
                    label=text(
                        "How often do you send soil or tissue samples for testing?",
                        "¿Con qué frecuencia envías muestras de suelo o tejido a análisis?",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    visible_when=(
                        Condition(
                            "fertility_monitoring",
                            "includes_any",
                            ("soil_tests", "tissue_tests", "microbiological_testing", "crop_quality_analysis"),
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Laboratory testing frequency: {answer}.", section_key="monitoring_plan"
                    ),
                    options=(
                        Option("per_crop", text("With each crop", "Con cada cultivo")),
                        Option("seasonally", text("Each season", "Cada temporada")),
                        Option("annually", text("Annually", "Anualmente")),
                        Option("every_few_years", text("Every two to three years", "Cada dos o tres años")),
                        Option("as_needed", text("As needed", "Según necesidad")),
                        Option("daily", text("Daily", "Diariamente")),
                        Option("weekly", text("Weekly", "Semanalmente")),
                        Option("monthly", text("Monthly", "Mensualmente")),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="fertility_testing_frequency_other",
                    kind="text",
                    label=text("Other testing frequency", "Otra frecuencia de análisis"),
                    required=False,
                    visible_when=(Condition("fertility_testing_frequency", "eq", "other"),),
                    compiles_to=CompileRule(
                        template="Other laboratory testing frequency: {answer}.", section_key="monitoring_plan"
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
                            "strip_cropping",
                            text("Strip cropping", "Cultivo en franjas"),
                        ),
                        Option(
                            "land_leveling",
                            text(
                                "Land leveling / land forming",
                                "Nivelación / conformación del terreno",
                            ),
                        ),
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
