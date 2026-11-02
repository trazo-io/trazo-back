"""
G5.0 — Crop Pest, Weed & Disease Management.

Sources: 7 CFR 205.206 (crop pest, weed, and disease management practice standard) and
205.601 (synthetic substances allowed for use in organic crop production — the National
List substances a producer may reach for under § 205.206(e)). Topic order follows the
public Common OSP grower template; all wording authored for Trazo.

The § 205.206 hierarchy is the spine of this module: prevention through systems practices
(a) comes first, mechanical/physical/biological methods (b)-(d) are the next line of
defense, and a substance from § 205.601 is allowed under (e) only once the OSP documents
that those practices were insufficient. Pages A-D follow that order exactly, ending with
the monitoring that shows the whole plan is actually working.

Unlike G3.0/G4.0, this module does not wire `Prefill` sources — no resolver exists yet
over logged pest, weed, and disease event history. The checkbox batteries below are
written to accept one later (page-level categories mirror how that history is likely to
be shaped) without restructuring; coaching text points growers at their own Trazo event
log as a record-keeping aid in the meantime, never as an auto-filled answer.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Prefill, Question, text

G5_0_PEST = Module(
    key="g5_0_pest",
    code="G5.0",
    title=text("Crop Pest, Weed & Disease Management", "Manejo de Plagas, Malezas y Enfermedades de Cultivos"),
    nop_cites=("§ 205.206", "§ 205.601", "§ 205.203(e)(3)"),
    education=(
        text(
            "The organic rule requires pest, weed, and disease management to start with "
            "prevention: crop rotation, sanitation, and other cultural practices that keep "
            "pressure low before any material is ever applied (§ 205.206(a)). When those "
            "practices are not enough on their own, mechanical, physical, and biological "
            "methods — traps, beneficial-insect habitat, targeted cultivation — are the "
            "next line of defense (§ 205.206(b)-(d)). Only when prevention and non-material "
            "methods are insufficient may a biological, botanical, or National List "
            "substance be applied (§ 205.206(e), § 205.601) — and the conditions that made "
            "it necessary must be documented in this OSP.",
            "La normativa orgánica exige que el manejo de plagas, malezas y enfermedades "
            "comience por la prevención: rotación de cultivos, saneamiento y otras "
            "prácticas culturales que mantengan baja la presión antes de aplicar cualquier "
            "material (§ 205.206(a)). Cuando esas prácticas no bastan por sí solas, los "
            "métodos mecánicos, físicos y biológicos — trampas, hábitat para insectos "
            "benéficos, cultivo dirigido — son la siguiente línea de defensa "
            "(§ 205.206(b)-(d)). Solo cuando la prevención y los métodos no materiales son "
            "insuficientes puede aplicarse una sustancia biológica, botánica o incluida en "
            "la Lista Nacional (§ 205.206(e), § 205.601) — y las condiciones que hicieron "
            "necesaria su aplicación deben documentarse en este OSP.",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — this operation does not encounter pest, weed, or disease "
        "pressure that requires active management (for example, wild-crop harvest only).",
        "No aplica — esta operación no enfrenta presión de plagas, malezas o enfermedades "
        "que requiera manejo activo (por ejemplo, únicamente cosecha de cultivos "
        "silvestres).",
    ),
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_prevention",
            title=text("A. Prevention & cultural practices", "A. Prevención y prácticas culturales"),
            education=(
                text(
                    "Prevention practices are the foundation of organic pest, weed, and "
                    "disease management — the rule requires them before any material is "
                    "ever considered (§ 205.206(a)). Select every practice this operation "
                    "actually uses; the more of these that are in place, the stronger your "
                    "OSP's prevention story.",
                    "Las prácticas de prevención son la base del manejo orgánico de plagas, malezas y enfermedades "
                    "— la normativa las exige antes de considerar cualquier material (§ 205.206(a)). Selecciona "
                    "todas las prácticas que esta operación realmente utiliza; cuantas más estén implementadas, más "
                    "sólido será el relato de prevención de tu OSP.",
                ),
            ),
            questions=(
                Question(
                    key="prevention_practices",
                    kind="checkbox_group",
                    label=text(
                        "Which prevention and cultural practices does your operation use to "
                        "manage pest, weed, and disease pressure?",
                        "¿Qué prácticas de prevención y culturales utiliza tu operación para manejar la presión de "
                        "plagas, malezas y enfermedades?",
                    ),
                    coaching=text(
                        "These practices keep pressure from building up in the first place, "
                        "without applying any material — the organic rule's first line of "
                        "defense.",
                        "Estas prácticas evitan que la presión se acumule desde el inicio, "
                        "sin aplicar ningún material — la primera línea de defensa de la "
                        "normativa orgánica.",
                    ),
                    nop_cite="§ 205.206(a)",
                    compiles_to=CompileRule(template="Pest, weed, and disease prevention practices used: {answer}."),
                    options=(
                        Option("crop_rotation", text("Crop rotation", "Rotación de cultivos")),
                        Option(
                            "sanitation",
                            text(
                                "Sanitation — removing crop residue, cull piles, and disease vectors",
                                "Saneamiento — retiro de residuos de cosecha, pilas de "
                                "descarte y vectores de enfermedad",
                            ),
                        ),
                        Option(
                            "tool_sanitation",
                            text(
                                "Cleaning tools and equipment between fields or blocks",
                                "Limpieza de herramientas y equipo entre campos o bloques",
                            ),
                        ),
                        Option(
                            "beneficial_habitat",
                            text(
                                "Habitat for beneficial insects and natural predators "
                                "(hedgerows, insectary plantings, refuge strips)",
                                "Hábitat para insectos benéficos y depredadores naturales "
                                "(cercos vivos, plantaciones de insectario, franjas refugio)",
                            ),
                        ),
                        Option(
                            "beneficial_release",
                            text(
                                "Augmentation or release of beneficial insects, predators, or parasitoids",
                                "Aumento o liberación de insectos benéficos, depredadores o " "parasitoides",
                            ),
                        ),
                        Option(
                            "resistant_varieties",
                            text(
                                "Resistant or site-adapted plant varieties",
                                "Variedades vegetales resistentes o adaptadas al sitio",
                            ),
                        ),
                        Option(
                            "spacing_timing",
                            text(
                                "Plant spacing and planting-date timing to reduce pest and disease pressure",
                                "Distanciamiento entre plantas y calendario de siembra para "
                                "reducir la presión de plagas y enfermedades",
                            ),
                        ),
                        Option(
                            "pruning_canopy",
                            text(
                                "Pruning and canopy management to improve airflow and reduce disease pressure",
                                "Poda y manejo del dosel para mejorar la circulación de aire "
                                "y reducir la presión de enfermedades",
                            ),
                        ),
                        Option("mulching", text("Mulching", "Acolchado")),
                        Option(
                            "irrigation_management",
                            text(
                                "Irrigation timing and method managed to reduce disease pressure",
                                "Manejo del momento y método de riego para reducir la presión " "de enfermedades",
                            ),
                        ),
                        Option(
                            "nutrient_management",
                            text(
                                "Nutrient management that supports plant health and natural resistance",
                                "Manejo de nutrientes que favorece la salud vegetal y la "
                                "resistencia natural de las plantas",
                            ),
                        ),
                        Option(
                            "vertebrate_exclusion",
                            text(
                                "Vertebrate exclusion — fencing, netting, or tree guards for "
                                "deer, birds, or rodents",
                                "Exclusión de vertebrados — cercas, mallas o protectores de "
                                "tronco contra ciervos, aves o roedores",
                            ),
                        ),
                        Option(
                            "raptor_habitat",
                            text(
                                "Owl boxes, raptor perches, or other predator habitat for " "rodent control",
                                "Cajas para lechuzas, perchas para rapaces u otro hábitat de "
                                "depredadores para el control de roedores",
                            ),
                        ),
                        Option(
                            "vertebrate_trapping",
                            text(
                                "Trapping or allowed vertebrate-pest controls (ground " "squirrels, gophers, voles)",
                                "Trampeo u otros controles permitidos de vertebrados "
                                "(ardillas terrestres, tuzas, ratones de campo)",
                            ),
                        ),
                        Option(
                            "field_borders",
                            text(
                                "Field borders, windbreaks, or buffer plantings",
                                "Bordes de campo, cortavientos o franjas de amortiguación",
                            ),
                        ),
                        Option("cover_cropping", text("Cover cropping", "Cultivos de cobertura")),
                        Option(
                            "interplanting_mixed_species",
                            text("Interplanting or mixed species", "Cultivos intercalados o especies mixtas"),
                        ),
                        Option("trap_crops", text("Trap crops", "Cultivos trampa")),
                        Option("companion_planting", text("Companion planting", "Plantas acompañantes")),
                        Option("mating_disruption", text("Mating disruption", "Confusión sexual")),
                        Option(
                            "insect_rodent_traps", text("Insect or rodent traps", "Trampas para insectos o roedores")
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="prevention_practices_other",
                    kind="text",
                    label=text("Describe the other practice", "Describe la otra práctica"),
                    visible_when=(Condition("prevention_practices", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional prevention practice: {answer}."),
                ),
                # § 205.203(e)(3) — burning crop residue is PROHIBITED as a means of
                # disposal, and permitted only "to suppress the spread of disease or to
                # stimulate seed germination". It sits on this page rather than under soil
                # management because both lawful reasons are disease/weed reasons, which is
                # also where the federal template puts the question.
                #
                # It records, it does not block. An operation that burns for a reason
                # outside the exception has a real compliance problem, and the product's job
                # is to make that visible to the operator and their certifier — not to
                # refuse the record and push it onto paper nobody audits.
                Question(
                    key="burns_crop_residue",
                    kind="boolean",
                    label=text(
                        "Do you burn crop residue on this operation?",
                        "¿Quemas residuos de cultivo en esta operación?",
                    ),
                    coaching=text(
                        "Includes prunings, brush, and orchard removals burned in place or "
                        "in a pile. Burning as a way to dispose of crop residue is "
                        "prohibited; burning is allowed only to suppress the spread of "
                        "disease or to stimulate seed germination.",
                        "Incluye podas, ramas y arranques de huerto quemados en el lugar o en "
                        "pila. Quemar como forma de eliminar residuos de cultivo está "
                        "prohibido; solo se permite quemar para suprimir la propagación de "
                        "una enfermedad o para estimular la germinación de semillas.",
                    ),
                    nop_cite="§ 205.203(e)(3)",
                    compiles_to=CompileRule(template="Crop residue is burned on this operation: {answer}."),
                ),
                Question(
                    key="burn_crops",
                    kind="text",
                    label=text(
                        "Which crops or residues are burned?",
                        "¿Qué cultivos o residuos se queman?",
                    ),
                    nop_cite="§ 205.203(e)(3)",
                    visible_when=(Condition("burns_crop_residue", "truthy"),),
                    compiles_to=CompileRule(template="Crops or residues burned: {answer}."),
                ),
                Question(
                    # CCOF G5.0 C2; OTCO C5 5.2-1 ("and how often burning is conducted").
                    key="burn_frequency",
                    kind="text",
                    label=text(
                        "How often do you burn crop residue?", "¿Con qué frecuencia quemas residuos de cultivo?"
                    ),
                    required=False,
                    nop_cite="§ 205.203(e)(3)",
                    visible_when=(Condition("burns_crop_residue", "truthy"),),
                    compiles_to=CompileRule(template="Crop residue burn frequency: {answer}."),
                ),
                Question(
                    key="burn_reason",
                    kind="checkbox_group",
                    label=text("Why is it burned?", "¿Por qué se queman?"),
                    coaching=text(
                        "The rule names exactly two allowed reasons. If neither applies, say "
                        "so here — an accurate record your certifier can act on is worth more "
                        "than a tidy one.",
                        "La normativa nombra exactamente dos razones permitidas. Si ninguna aplica, indícalo aquí — "
                        "un registro exacto sobre el que tu certificadora pueda actuar vale más que uno prolijo.",
                    ),
                    nop_cite="§ 205.203(e)(3)",
                    visible_when=(Condition("burns_crop_residue", "truthy"),),
                    options=(
                        Option(
                            "disease_suppression",
                            text(
                                "To suppress the spread of disease",
                                "Para suprimir la propagación de una enfermedad",
                            ),
                        ),
                        Option(
                            "seed_germination",
                            text(
                                "To stimulate seed germination",
                                "Para estimular la germinación de semillas",
                            ),
                        ),
                        Option(
                            "other",
                            text(
                                "Another reason (describe below)",
                                "Otra razón (describe abajo)",
                            ),
                        ),
                    ),
                    compiles_to=CompileRule(template="Reason for burning crop residue: {answer}."),
                ),
                Question(
                    key="burn_reason_other",
                    kind="textarea",
                    label=text(
                        "Describe the other reason for burning",
                        "Describe la otra razón para quemar",
                    ),
                    coaching=text(
                        "§ 205.203(e)(3) allows burning only for disease suppression or seed "
                        "germination, so a reason outside those two needs to be raised with "
                        "your certifying agent rather than left in the plan unexplained.",
                        "El § 205.203(e)(3) solo permite la quema para suprimir enfermedades o estimular la "
                        "germinación, por lo que una razón fuera de esas dos debe plantearse a tu agencia "
                        "certificadora en lugar de quedar sin explicar en el plan.",
                    ),
                    visible_when=(Condition("burn_reason", "includes", "other"),),
                    compiles_to=CompileRule(template="Other stated reason for burning crop residue: {answer}"),
                ),
            ),
        ),
        ModulePage(
            key="b_weed_management",
            title=text("B. Weed management", "B. Manejo de malezas"),
            education=(
                text(
                    "Weed control methods allowed under the organic rule range from "
                    "mechanical and physical (cultivation, mowing, flame) to biological "
                    "(grazing, cover-crop suppression) (§ 205.206(c)). Plastic or other "
                    "synthetic mulch is allowed for weed suppression only if it is removed "
                    "from the field at the end of the growing or harvest season "
                    "(§ 205.206(c)(6)).",
                    "Los métodos de control de malezas permitidos por la normativa orgánica "
                    "van de mecánicos y físicos (cultivo, corte, flameado) a biológicos "
                    "(pastoreo, supresión con cultivo de cobertura) (§ 205.206(c)). El "
                    "plástico u otro acolchado sintético está permitido para suprimir "
                    "malezas solo si se retira del campo al final de la temporada de "
                    "cultivo o cosecha (§ 205.206(c)(6)).",
                ),
            ),
            questions=(
                Question(
                    key="weed_management_practices",
                    kind="checkbox_group",
                    label=text(
                        "Which methods does your operation use to manage weeds?",
                        "¿Qué métodos utiliza tu operación para manejar las malezas?",
                    ),
                    nop_cite="§ 205.206(c)",
                    compiles_to=CompileRule(template="Weeds are managed through: {answer}."),
                    options=(
                        Option("mechanical_cultivation", text("Mechanical cultivation", "Cultivo mecánico")),
                        Option("hand_weeding", text("Hand weeding", "Deshierbe manual")),
                        Option("mowing", text("Mowing", "Corte o desbrozado")),
                        Option(
                            "organic_mulch",
                            text("Organic (biodegradable) mulch", "Acolchado orgánico (biodegradable)"),
                        ),
                        Option(
                            "plastic_mulch",
                            text("Plastic or other synthetic mulch", "Plástico u otro acolchado sintético"),
                        ),
                        Option(
                            "flame_weeding",
                            text(
                                "Flame, heat, or electrical weeding",
                                "Deshierbe por flameado, calor o electricidad",
                            ),
                        ),
                        Option("grazing", text("Livestock grazing", "Pastoreo de ganado")),
                        Option("solarization", text("Soil solarization", "Solarización del suelo")),
                        Option(
                            "cover_crop_suppression",
                            text(
                                "Cover-crop suppression (planted or roller-crimped covers that outcompete weeds)",
                                "Supresión con cultivo de cobertura (coberturas sembradas o "
                                "aplastadas con rodillo que compiten con las malezas)",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="weed_management_other",
                    kind="text",
                    label=text("Describe the other method", "Describe el otro método"),
                    visible_when=(Condition("weed_management_practices", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional weed management method: {answer}."),
                ),
                Question(
                    key="plastic_mulch_used",
                    kind="boolean",
                    label=text(
                        "Do you use plastic or other synthetic mulch for weed control?",
                        "¿Utilizas plástico u otro acolchado sintético para el control de malezas?",
                    ),
                    nop_cite="§ 205.206(c)(6)",
                    compiles_to=CompileRule(template="Plastic or synthetic mulch used for weed control: {answer}."),
                ),
                Question(
                    key="plastic_mulch_removal",
                    kind="textarea",
                    label=text(
                        "Describe how the plastic or synthetic mulch is removed at season end",
                        "Describe cómo se retira el acolchado plástico o sintético al final de la temporada",
                    ),
                    coaching=text(
                        "Plastic and other synthetic mulches are allowed for weed "
                        "suppression only if removed from the field at the end of the "
                        "growing or harvest season — describe when and how removal happens.",
                        "El acolchado plástico y otros sintéticos están permitidos para suprimir malezas solo si se "
                        "retiran del campo al final de la temporada de cultivo o cosecha — describe cuándo y cómo "
                        "se realiza el retiro.",
                    ),
                    nop_cite="§ 205.206(c)(6)",
                    visible_when=(Condition("plastic_mulch_used", "truthy"),),
                    compiles_to=CompileRule(template="Plastic or synthetic mulch removal at season end: {answer}."),
                ),
            ),
        ),
        ModulePage(
            key="c_when_prevention_insufficient",
            title=text("C. When prevention is not enough", "C. Cuando la prevención no basta"),
            education=(
                text(
                    "Prevention, plus the mechanical, physical, and biological methods "
                    "above, is the required starting point. A biological, botanical, or "
                    "National List substance may be applied only when those practices are "
                    "insufficient to prevent or control the pest, weed, or disease — and "
                    "the organic system plan must document the conditions that made the "
                    "substance necessary (§ 205.206(e), § 205.601).",
                    "La prevención, junto con los métodos mecánicos, físicos y biológicos "
                    "anteriores, es el punto de partida obligatorio. Una sustancia "
                    "biológica, botánica o incluida en la Lista Nacional solo puede "
                    "aplicarse cuando esas prácticas son insuficientes para prevenir o "
                    "controlar la plaga, maleza o enfermedad — y el plan de sistema "
                    "orgánico debe documentar las condiciones que hicieron necesaria la "
                    "sustancia (§ 205.206(e), § 205.601).",
                ),
            ),
            questions=(
                Question(
                    key="applies_pest_weed_disease_inputs",
                    kind="boolean",
                    # Suggests TRUE from a logged application; never suggests FALSE from the
                    # absence of one. See _applies_inputs_evidence.
                    prefill=Prefill(source="applies_inputs_evidence"),
                    label=text(
                        "Do you ever apply allowed input materials for pest, weed, or disease control?",
                        "¿Alguna vez aplicas materiales de insumo permitidos para el control de plagas, malezas o "
                        "enfermedades?",
                    ),
                    nop_cite="§ 205.206(e)",
                    compiles_to=CompileRule(
                        template="Allowed input materials are applied for pest, weed, or disease control when "
                        "prevention is insufficient: {answer}."
                    ),
                ),
                Question(
                    # CCOF G5.0 B2; OTCO C5 5.1-4.
                    key="input_use_triggers",
                    kind="checkbox_group",
                    label=text("When do you turn to these materials?", "¿Cuándo recurres a estos materiales?"),
                    required=False,
                    nop_cite="§ 205.206(e)",
                    visible_when=(Condition("applies_pest_weed_disease_inputs", "truthy"),),
                    compiles_to=CompileRule(template="Pest, weed or disease materials are used only when: {answer}."),
                    options=(
                        Option(
                            "preventive_insufficient",
                            text("Preventive measures are not enough", "Las medidas preventivas no son suficientes"),
                        ),
                        Option(
                            "economic_threshold",
                            text(
                                "An economic threshold for damage is exceeded", "Se supera un umbral económico de daño"
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="input_use_conditions",
                    kind="textarea",
                    label=text(
                        "Describe the conditions under which you apply these materials",
                        "Describe las condiciones bajo las cuales aplicas estos materiales",
                    ),
                    coaching=text(
                        "The rule requires you to document that your prevention, "
                        "mechanical, and biological practices were insufficient before a "
                        "material is applied — not just that the material itself is "
                        "allowed. Describe the pest, weed, or disease pressure that "
                        "triggers use and which practices you rely on first. The materials "
                        "themselves belong on your OSP inputs list in the Materials "
                        "Application, not here.",
                        "La normativa exige documentar que tus prácticas de prevención, mecánicas y biológicas "
                        "fueron insuficientes antes de aplicar un material — no basta con que el material en sí "
                        "esté permitido. Describe la presión de plaga, maleza o enfermedad que motiva el uso y en qué"
                        "prácticas te apoyas primero. Los materiales en sí van en la lista de insumos de tu OSP, "
                        "en la Aplicación de Materiales, no aquí.",
                    ),
                    nop_cite="§ 205.206(e)",
                    visible_when=(Condition("applies_pest_weed_disease_inputs", "truthy"),),
                    compiles_to=CompileRule(
                        template="Conditions documented for applying allowed pest, weed, or disease control "
                        "materials: {answer}."
                    ),
                ),
            ),
        ),
        ModulePage(
            key="d_monitoring",
            title=text("D. Monitoring", "D. Monitoreo"),
            education=(
                text(
                    "Regular monitoring is how you show that prevention is actually "
                    "working and catch pest, weed, or disease pressure early enough to "
                    "manage it without escalating to a material application "
                    "(§ 205.201(a)(3)).",
                    "El monitoreo regular es cómo demuestra que la prevención realmente "
                    "está funcionando y detecta a tiempo la presión de plagas, malezas o "
                    "enfermedades, antes de tener que recurrir a la aplicación de un "
                    "material (§ 205.201(a)(3)).",
                ),
            ),
            questions=(
                Question(
                    key="monitoring_scope",
                    kind="checkbox_group",
                    prefill=Prefill(source="pest_monitoring_scope"),
                    label=text("What do you monitor?", "¿Qué monitoreas?"),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(
                        template="Pest, weed, and disease monitoring covers: {answer}.",
                        section_key="monitoring_plan",
                    ),
                    options=(
                        Option("pest_populations", text("Pest populations", "Poblaciones de plagas")),
                        Option("disease_pressure", text("Disease pressure", "Presión de enfermedades")),
                        Option("weed_pressure", text("Weed pressure", "Presión de malezas")),
                        Option(
                            "beneficial_activity",
                            text(
                                "Beneficial insect and natural predator activity",
                                "Actividad de insectos benéficos y depredadores naturales",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="monitoring_frequency",
                    kind="radio",
                    prefill=Prefill(source="pest_monitoring_frequency"),
                    label=text("How often is monitoring performed?", "¿Con qué frecuencia se realiza el monitoreo?"),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(
                        template="Monitoring frequency: {answer}.",
                        section_key="monitoring_plan",
                    ),
                    options=(
                        Option(
                            "per_event",
                            text(
                                "At each field visit or scouting event",
                                "En cada visita al campo o recorrido de monitoreo",
                            ),
                        ),
                        Option("weekly", text("Weekly", "Semanalmente")),
                        Option("monthly", text("Monthly", "Mensualmente")),
                        Option("seasonally", text("Each season", "Cada temporada")),
                    ),
                ),
                Question(
                    # WSDA AGR 2121 F1, G1, H1; OTCO C5 5.3-1: the METHOD, beside what is monitored.
                    key="monitoring_methods",
                    kind="checkbox_group",
                    label=text(
                        "How do you monitor? Check all that apply.",
                        "¿Cómo monitoreas? Marca todas las que correspondan.",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Monitoring methods: {answer}.", section_key="monitoring_plan"),
                    options=(
                        Option("scouting", text("Scouting program", "Programa de recorridos de monitoreo")),
                        Option(
                            "traps_lures",
                            text("Trap monitoring (traps or lures)", "Monitoreo con trampas o atrayentes"),
                        ),
                        Option(
                            "crop_health_observation",
                            text("Crop health observation", "Observación de la sanidad del cultivo"),
                        ),
                        Option("crop_yield_comparison", text("Crop yield comparison", "Comparación de rendimientos")),
                        Option("target_observation", text("Observation of weeds", "Observación de malezas")),
                        Option("modeling", text("Pest or disease modeling", "Modelos de plagas o enfermedades")),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="monitoring_methods_other",
                    kind="text",
                    label=text("Other monitoring method", "Otro método de monitoreo"),
                    required=False,
                    visible_when=(Condition("monitoring_methods", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Other monitoring method: {answer}.", section_key="monitoring_plan"
                    ),
                ),
                Question(
                    # WSDA AGR 2121 F2 asks this frequency apart.
                    key="weed_monitoring_frequency",
                    kind="radio",
                    label=text("How often do you monitor weeds?", "¿Con qué frecuencia monitoreas malezas?"),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    visible_when=(Condition("monitoring_scope", "includes", "weed_pressure"),),
                    compiles_to=CompileRule(
                        template="Weed monitoring frequency: {answer}.", section_key="monitoring_plan"
                    ),
                    options=(
                        Option(
                            "per_event",
                            text(
                                "At each field visit or scouting event",
                                "En cada visita al campo o recorrido de monitoreo",
                            ),
                        ),
                        Option("weekly", text("Weekly", "Semanalmente")),
                        Option("monthly", text("Monthly", "Mensualmente")),
                        Option("seasonally", text("Each season", "Cada temporada")),
                    ),
                ),
                Question(
                    # WSDA AGR 2121 G2 asks this frequency apart.
                    key="pest_monitoring_frequency",
                    kind="radio",
                    label=text("How often do you monitor pests?", "¿Con qué frecuencia monitoreas plagas?"),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    visible_when=(Condition("monitoring_scope", "includes", "pest_populations"),),
                    compiles_to=CompileRule(
                        template="Pest monitoring frequency: {answer}.", section_key="monitoring_plan"
                    ),
                    options=(
                        Option(
                            "per_event",
                            text(
                                "At each field visit or scouting event",
                                "En cada visita al campo o recorrido de monitoreo",
                            ),
                        ),
                        Option("weekly", text("Weekly", "Semanalmente")),
                        Option("monthly", text("Monthly", "Mensualmente")),
                        Option("seasonally", text("Each season", "Cada temporada")),
                    ),
                ),
                Question(
                    # WSDA AGR 2121 H2 asks this frequency apart.
                    key="disease_monitoring_frequency",
                    kind="radio",
                    label=text("How often do you monitor diseases?", "¿Con qué frecuencia monitoreas enfermedades?"),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    visible_when=(Condition("monitoring_scope", "includes", "disease_pressure"),),
                    compiles_to=CompileRule(
                        template="Disease monitoring frequency: {answer}.", section_key="monitoring_plan"
                    ),
                    options=(
                        Option(
                            "per_event",
                            text(
                                "At each field visit or scouting event",
                                "En cada visita al campo o recorrido de monitoreo",
                            ),
                        ),
                        Option("weekly", text("Weekly", "Semanalmente")),
                        Option("monthly", text("Monthly", "Mensualmente")),
                        Option("seasonally", text("Each season", "Cada temporada")),
                    ),
                ),
                Question(
                    key="monitoring_records",
                    kind="textarea",
                    label=text(
                        "How do you record monitoring results?", "¿Cómo registras los resultados del " "monitoreo?"
                    ),
                    coaching=text(
                        "Include what you record — pest or disease counts, trap catches, "
                        "weed maps, scouting notes — and where it is kept. Pest, weed, and "
                        "disease events logged in Trazo can serve as this record.",
                        "Incluye qué registras — conteos de plagas o enfermedades, capturas en trampas, mapas de "
                        "malezas, notas de recorrido — y dónde se conserva. Los eventos de plagas, malezas y "
                        "enfermedades registrados en Trazo pueden servir como este registro.",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(
                        template="Monitoring results are recorded: {answer}.",
                        section_key="monitoring_plan",
                    ),
                ),
            ),
        ),
    ),
)
