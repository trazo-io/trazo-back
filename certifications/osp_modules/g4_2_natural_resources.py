"""
G4.2 — Natural Resources & Biodiversity.

Sources: 7 CFR 205.200 (organic production and handling practices must maintain or improve
the natural resources of the operation), 205.2 (definition: natural resources of the
operation), and USDA guidance on biodiversity conservation (NOP guidance 5020). Topic order
follows the public Common OSP grouping for this section — conservation practices, then
conservation agreements and wildlife pressures, then monitoring — all wording authored for
Trazo.

Page B exists because the certifier's own form asks more here than the federal template does:
conservation agreements, invasive species, and what an operation does about the habitat it
gives up when a buyer's food-safety scheme pushes it toward bare ground and wildlife exclusion.
The questions were authored from § 205.200 and NOP guidance 5020; a competitor's rendering told
us the topics were expected, never the wording.

Options cover practices common on Trazo's orchard-heavy ICP (windbreaks, hedgerows,
pollinator habitat, riparian buffers) alongside general soil and water conservation
practices, so the same two batteries serve row-crop and perennial operations without a
branching page.

No prefill: conservation and habitat practices are not currently logged as a distinct event
type, so operators answer directly here rather than confirming a suggestion. A future
workstream can wire prefill once a conservation-practice event exists to source it from.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text

G4_2_NATURAL_RESOURCES = Module(
    key="g4_2_natural_resources",
    code="G4.2",
    title=text("Natural Resources & Biodiversity", "Recursos naturales y biodiversidad"),
    nop_cites=("§ 205.200", "§ 205.2"),
    education=(
        text(
            "Organic production and handling practices must be managed to maintain or "
            "improve the natural resources of the operation, including soil and water "
            "quality (§ 205.200). The natural resources of the operation are its physical, "
            "hydrological, and biological features — soil, water, wetlands, woodlands, and "
            "wildlife (§ 205.2). USDA guidance on biodiversity conservation recognizes "
            "buffers, unmanaged or minimally managed land, and structures that support "
            "beneficial organisms as evidence that an operation is maintaining and "
            "enhancing those resources.",
            "Las prácticas de producción y manejo orgánico deben manejarse de modo que "
            "mantengan o mejoren los recursos naturales de la operación, incluida la "
            "calidad del suelo y el agua (§ 205.200). Los recursos naturales de la "
            "operación son sus características físicas, hidrológicas y biológicas — "
            "suelo, agua, humedales, bosques y fauna silvestre (§ 205.2). La guía del "
            "USDA sobre conservación de la biodiversidad reconoce los amortiguamientos, "
            "las áreas no manejadas o de manejo mínimo, y las estructuras que favorecen a "
            "organismos benéficos como evidencia de que una operación mantiene y mejora "
            "esos recursos.",
        ),
    ),
    allows_not_applicable=False,
    default_section_key="monitoring_plan",
    pages=(
        ModulePage(
            key="a_conservation_practices",
            title=text("A. Conservation practices", "A. Prácticas de conservación"),
            education=(
                text(
                    "Document the conservation and biodiversity practices actually "
                    "implemented on this operation, not practices that are only planned. "
                    "These practices are the evidence that production activities maintain "
                    "or improve the natural resources of the operation (§ 205.200).",
                    "Documenta las prácticas de conservación y biodiversidad que realmente están implementadas en "
                    "esta operación, no las que solo están planificadas. Estas prácticas son la evidencia de que "
                    "las actividades de producción mantienen o mejoran los recursos naturales de la operación (§ "
                    "205.200).",
                ),
            ),
            questions=(
                Question(
                    key="soil_water_practices",
                    kind="checkbox_group",
                    label=text(
                        "Which soil and water conservation practices does this operation " "use?",
                        "¿Qué prácticas de conservación de suelo y agua usa esta " "operación?",
                    ),
                    nop_cite="§ 205.200",
                    compiles_to=CompileRule(
                        template="Soil and water conservation practices used on this operation: {answer}.",
                        section_key="practices_procedures",
                    ),
                    options=(
                        Option("cover_cropping", text("Cover cropping", "Cultivos de cobertura")),
                        Option(
                            "reduced_tillage",
                            text("Reduced or minimum tillage", "Labranza reducida o mínima"),
                        ),
                        Option(
                            "contour_terracing",
                            text("Contour farming or terracing", "Cultivo en contorno o terrazas"),
                        ),
                        Option(
                            "grassed_waterways",
                            text(
                                "Grassed waterways",
                                "Canales de desagüe cubiertos de pasto",
                            ),
                        ),
                        Option(
                            "riparian_buffers",
                            text("Riparian buffers", "Franjas de amortiguamiento ribereñas"),
                        ),
                        Option(
                            "irrigation_efficiency",
                            text(
                                "Irrigation efficiency improvements",
                                "Mejoras de eficiencia del riego",
                            ),
                        ),
                        Option(
                            "tailwater_management",
                            text("Tailwater management", "Manejo del agua de cola de riego"),
                        ),
                        Option("windbreaks", text("Windbreaks", "Cortavientos")),
                        Option(
                            "erosion_control_plantings",
                            text(
                                "Erosion-control plantings",
                                "Plantaciones para control de erosión",
                            ),
                        ),
                        Option(
                            "irrigation_scheduling_recharge",
                            text(
                                "Irrigation scheduling that avoids overdrafting groundwater and aids recharge",
                                "Programación del riego que evita sobreexplotar el agua subterránea y favorece la recarga",
                            ),
                        ),
                        Option(
                            "soil_moisture_monitoring",
                            text("Soil moisture monitoring", "Monitoreo de la humedad del suelo"),
                        ),
                        Option(
                            "infiltration",
                            text("Practices that encourage infiltration", "Prácticas que favorecen la infiltración"),
                        ),
                        Option(
                            "regionally_appropriate_crops",
                            text("Regionally appropriate crops", "Cultivos adecuados a la región"),
                        ),
                        Option(
                            "drought_tolerant_natives",
                            text("Drought-tolerant native plantings", "Plantas nativas tolerantes a la sequía"),
                        ),
                        Option("irrigation_reservoir", text("Irrigation reservoir", "Reservorio de riego")),
                        Option("tailwater_recovery", text("Tailwater recovery", "Recuperación de agua de escorrentía")),
                        Option(
                            "micro_irrigation",
                            text(
                                "Micro-irrigation (drip or micro-sprinklers)",
                                "Microirrigación (goteo o microaspersión)",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    # WSDA AGR 2121 E10.
                    key="irrigation_efficiency_monitoring",
                    kind="checkbox_group",
                    label=text(
                        "How do you check that irrigation water is used efficiently?",
                        "¿Cómo verificas que el agua de riego se usa de forma eficiente?",
                    ),
                    required=False,
                    nop_cite="§ 205.200",
                    compiles_to=CompileRule(template="Irrigation efficiency is monitored by: {answer}."),
                    options=(
                        Option("soil_moisture_sensors", text("Soil moisture sensors", "Sensores de humedad del suelo")),
                        Option("visual_observations", text("Visual observation", "Observación visual")),
                        Option(
                            "scheduling_software",
                            text("Irrigation scheduling software", "Software de programación del riego"),
                        ),
                        Option(
                            "not_irrigated",
                            text("Not applicable: no irrigation", "No aplica: sin riego"),
                            exclusive=True,
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="irrigation_efficiency_monitoring_other",
                    kind="text",
                    label=text(
                        "Other way you check irrigation efficiency", "Otra forma de verificar la eficiencia del riego"
                    ),
                    required=False,
                    visible_when=(Condition("irrigation_efficiency_monitoring", "includes", "other"),),
                    compiles_to=CompileRule(template="Other irrigation efficiency monitoring: {answer}."),
                ),
                Question(
                    key="soil_water_practices_other",
                    kind="text",
                    label=text(
                        "Describe the other soil or water conservation practice",
                        "Describe la otra práctica de conservación de suelo o agua",
                    ),
                    visible_when=(Condition("soil_water_practices", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Additional soil or water conservation practice: {answer}.",
                        section_key="practices_procedures",
                    ),
                ),
                Question(
                    key="habitat_biodiversity_practices",
                    kind="checkbox_group",
                    label=text(
                        "Which habitat and biodiversity practices does this operation use?",
                        "¿Qué prácticas de hábitat y biodiversidad usa esta operación?",
                    ),
                    coaching=text(
                        "USDA guidance on biodiversity conservation (NOP guidance 5020) "
                        "recognizes hedgerows, native or pollinator plantings, and habitat "
                        "structures like nest boxes as practices that support the "
                        "biological diversity of the operation's natural resources.",
                        "La guía del USDA sobre conservación de la biodiversidad (guía NOP "
                        "5020) reconoce los cercos vivos, las plantaciones nativas o para "
                        "polinizadores, y las estructuras de hábitat como cajas nido, como "
                        "prácticas que respaldan la diversidad biológica de los recursos "
                        "naturales de la operación.",
                    ),
                    nop_cite="§ 205.2",
                    compiles_to=CompileRule(
                        template="Habitat and biodiversity practices used on this operation: {answer}.",
                        section_key="practices_procedures",
                    ),
                    options=(
                        Option("hedgerows", text("Hedgerows", "Cercos vivos")),
                        Option(
                            "native_plantings",
                            text("Native plantings", "Plantaciones de especies nativas"),
                        ),
                        Option(
                            "pollinator_habitat",
                            text("Pollinator habitat", "Hábitat para polinizadores"),
                        ),
                        Option(
                            "owl_raptor_boxes",
                            text(
                                "Owl or raptor boxes or perches",
                                "Cajas nido o perchas para búhos o aves rapaces",
                            ),
                        ),
                        Option("bat_boxes", text("Bat boxes", "Cajas para murciélagos")),
                        Option(
                            "wetland_woodland_protection",
                            text(
                                "Wetland or woodland protection",
                                "Protección de humedales o bosques",
                            ),
                        ),
                        Option(
                            "wildlife_corridors",
                            text("Wildlife corridors", "Corredores de vida silvestre"),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="habitat_biodiversity_practices_other",
                    kind="text",
                    label=text(
                        "Describe the other habitat or biodiversity practice",
                        "Describe la otra práctica de hábitat o biodiversidad",
                    ),
                    visible_when=(Condition("habitat_biodiversity_practices", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Additional habitat or biodiversity practice: {answer}.",
                        section_key="practices_procedures",
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_conservation_agreements",
            title=text(
                "B. Conservation agreements, invasive species & wildlife",
                "B. Acuerdos de conservación, especies invasoras y fauna",
            ),
            questions=(
                Question(
                    key="conservation_plan_agency",
                    kind="checkbox_group",
                    label=text(
                        "Does this operation have a current conservation plan or agreement with "
                        "a conservation agency or program?",
                        "¿Esta operación tiene un plan o acuerdo de conservación vigente con "
                        "una agencia o programa de conservación?",
                    ),
                    coaching=text(
                        "An existing plan is evidence you are already managing the natural "
                        "resources of the operation, and the certifier can read it alongside "
                        "this section. Keep a copy available for the inspection.",
                        "Un plan existente es evidencia de que ya manejas los recursos naturales de la operación, y "
                        "el certificador puede leerlo junto con esta sección. Ten una copia disponible para la "
                        "inspección.",
                    ),
                    nop_cite="§ 205.200",
                    compiles_to=CompileRule(
                        template="Conservation plans or agreements in place: {answer}.",
                        section_key="practices_procedures",
                    ),
                    options=(
                        Option(
                            "federal_agency",
                            text(
                                "Federal conservation agency (NRCS, FSA)",
                                "Agencia federal de conservación (NRCS, FSA)",
                            ),
                        ),
                        Option(
                            "local_district",
                            text(
                                "Local resource conservation district",
                                "Distrito local de conservación de recursos",
                            ),
                        ),
                        Option(
                            "land_trust",
                            text(
                                "Land trust or stewardship organization",
                                "Fideicomiso de tierras u organización de custodia",
                            ),
                        ),
                        Option(
                            "stewardship_program",
                            text(
                                "Certification or stewardship program",
                                "Programa de certificación o custodia ambiental",
                            ),
                        ),
                        Option(
                            "none",
                            text(
                                "No current conservation plan or agreement",
                                "Ningún plan o acuerdo de conservación vigente",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="conservation_plan_detail",
                    kind="text",
                    label=text(
                        "Name the agency or program and what the plan covers",
                        "Nombra la agencia o el programa y qué cubre el plan",
                    ),
                    visible_when=(
                        Condition(
                            "conservation_plan_agency",
                            "includes_any",
                            ["federal_agency", "local_district", "land_trust", "stewardship_program"],
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Conservation plan detail: {answer}",
                        section_key="practices_procedures",
                    ),
                ),
                Question(
                    key="invasive_species_practices",
                    kind="checkbox_group",
                    label=text(
                        "How does this operation prevent and control invasive plants and animals?",
                        "¿Cómo previene y controla esta operación las plantas y animales " "invasores?",
                    ),
                    coaching=text(
                        "Invasive species displace the native plants and wildlife that "
                        "§ 205.200 asks you to maintain, and they travel in on seed, planting "
                        "stock, amendments and mulch — which is why sourcing weed-free inputs "
                        "counts as prevention here.",
                        "Las especies invasoras desplazan las plantas nativas y la fauna que el "
                        "§ 205.200 pide mantener, y llegan en semillas, material de plantación, "
                        "enmiendas y mantillo — por eso abastecerse de insumos libres de malezas "
                        "cuenta como prevención aquí.",
                    ),
                    nop_cite="§ 205.200",
                    compiles_to=CompileRule(
                        template="Invasive species prevention and control: {answer}.",
                        section_key="practices_procedures",
                    ),
                    options=(
                        Option(
                            "identification",
                            text(
                                "Crew can identify the invasive species of concern locally",
                                "La cuadrilla sabe identificar las especies invasoras de " "interés local",
                            ),
                        ),
                        Option(
                            "early_removal",
                            text(
                                "New infestations are monitored for and removed promptly",
                                "Se monitorean y eliminan con prontitud las nuevas " "infestaciones",
                            ),
                        ),
                        Option(
                            "competitive_natives",
                            text(
                                "Competitive native plantings established in their place",
                                "Se establecen plantaciones nativas competitivas en su lugar",
                            ),
                        ),
                        Option(
                            "weed_free_inputs",
                            text(
                                "Seed, planting stock, amendments and mulch sourced weed- and " "pest-free",
                                "Semilla, material de plantación, enmiendas y mantillo "
                                "adquiridos libres de malezas y plagas",
                            ),
                        ),
                        Option(
                            "agency_program",
                            text(
                                "A state or county program controls the species on or near " "this land",
                                "Un programa estatal o del condado controla la especie en o " "cerca de estas tierras",
                            ),
                        ),
                        Option(
                            "none_present",
                            text(
                                "No invasive species pressure on this operation",
                                "No hay presión de especies invasoras en esta operación",
                            ),
                            exclusive=True,
                        ),
                        Option("grazing", text("Grazing", "Pastoreo")),
                        Option("biological_control", text("Biological control", "Control biológico")),
                        Option("prescribed_burning", text("Prescribed burning", "Quema prescrita")),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="invasive_species_practices_other",
                    kind="text",
                    label=text("Other invasive species practice", "Otra práctica contra especies invasoras"),
                    required=False,
                    visible_when=(Condition("invasive_species_practices", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Other invasive species practice: {answer}.",
                        section_key="practices_procedures",
                    ),
                ),
                Question(
                    key="wildlife_habitat_pressure",
                    kind="checkbox_group",
                    # Names both situations: the printed plan shows the question and the answer, never
                    # the option list, so "either of these" pointed at nothing (2026-09-11).
                    label=text(
                        "Is wildlife kept out of your production areas, or has native habitat been "
                        "brought into crop production since certification?",
                        "¿Mantienes la fauna fuera de tus áreas de producción, o has incorporado hábitat nativo a "
                        "la producción desde la certificación?",
                    ),
                    coaching=text(
                        "Buyers and food-safety schemes often push growers toward bare ground, "
                        "fencing and wildlife exclusion, while § 205.200 requires the operation "
                        "to maintain or improve its natural resources. The two pull against "
                        "each other, and the certifier will ask how you resolve it — an honest "
                        "answer with mitigation is stronger than claiming the tension does not "
                        "exist.",
                        "Los compradores y los esquemas de inocuidad alimentaria a menudo "
                        "empujan hacia suelo desnudo, cercos y exclusión de fauna, mientras que "
                        "el § 205.200 exige mantener o mejorar los recursos naturales. Ambas "
                        "cosas se contraponen, y el certificador preguntará cómo lo resuelve — "
                        "una respuesta honesta con mitigación es más sólida que afirmar que la "
                        "tensión no existe.",
                    ),
                    nop_cite="§ 205.200",
                    compiles_to=CompileRule(
                        template="Wildlife kept out of production areas, or native habitat brought into production: {answer}.",
                        section_key="practices_procedures",
                    ),
                    options=(
                        Option(
                            "wildlife_restricted",
                            text(
                                "Wildlife is kept out of production areas (food safety or crop " "protection)",
                                "Se mantiene la fauna fuera de las áreas de producción "
                                "(inocuidad o protección del cultivo)",
                            ),
                        ),
                        Option(
                            "habitat_converted",
                            text(
                                "Native habitat has been brought into crop production since " "certification",
                                "Se ha incorporado hábitat nativo a la producción desde la " "certificación",
                            ),
                        ),
                        Option(
                            "neither",
                            text(
                                "Neither — no wildlife exclusion and no habitat converted since " "certification",
                                "Ninguna — sin exclusión de fauna ni conversión de hábitat desde " "la certificación",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="wildlife_habitat_mitigation",
                    kind="checkbox_group",
                    label=text(
                        "How do you offset the resulting loss of wildlife habitat?",
                        "¿Cómo compensa la pérdida de hábitat que esto ocasiona?",
                    ),
                    nop_cite="§ 205.200",
                    visible_when=(
                        Condition(
                            "wildlife_habitat_pressure",
                            "includes_any",
                            ["wildlife_restricted", "habitat_converted"],
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Habitat loss is offset by: {answer}.",
                        section_key="practices_procedures",
                    ),
                    options=(
                        Option(
                            "habitat_elsewhere",
                            text(
                                "Habitat developed or enhanced elsewhere on the operation",
                                "Hábitat desarrollado o mejorado en otra parte de la operación",
                            ),
                        ),
                        Option(
                            "buffers_between",
                            text(
                                "Buffers planted between production and habitat areas",
                                "Franjas plantadas entre las áreas de producción y de hábitat",
                            ),
                        ),
                        Option(
                            "fencing_corridors",
                            text(
                                "Fencing routed to leave riparian areas and wildlife corridors " "open",
                                "Cercos trazados para dejar libres áreas ribereñas y corredores " "de fauna",
                            ),
                        ),
                        Option(
                            "restoration",
                            text(
                                "Degraded ground restored to offset the area taken",
                                "Restauración de terreno degradado para compensar el área " "tomada",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="wildlife_habitat_mitigation_other",
                    kind="text",
                    label=text(
                        "Describe the other mitigation",
                        "Describe la otra mitigación",
                    ),
                    visible_when=(Condition("wildlife_habitat_mitigation", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Additional habitat mitigation: {answer}",
                        section_key="practices_procedures",
                    ),
                ),
            ),
        ),
        ModulePage(
            key="c_monitoring_water",
            title=text("C. Monitoring & water", "C. Monitoreo y agua"),
            education=(
                text(
                    "Irrigation water is part of the natural resources of the operation "
                    "(§ 205.2). Monitoring shows how conservation and habitat practices are "
                    "performing over time and when a practice needs to change.",
                    "El agua de riego forma parte de los recursos naturales de la operación "
                    "(§ 205.2). El monitoreo muestra cómo funcionan a lo largo del tiempo "
                    "las prácticas de conservación y hábitat, y cuándo una práctica "
                    "necesita cambiar.",
                ),
            ),
            questions=(
                # CCOF G6.0 D1/D2, OTCO C9 9.2-1 (2026.11.09): the source by type, with a "not irrigated"
                # answer, beside the free-text sources above (kept, never retyped).
                Question(
                    key="irrigation_source_types",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "Which kinds of irrigation water do you use? Check all that apply.",
                        "¿Qué tipos de agua de riego usas? Marca todos los que correspondan.",
                    ),
                    nop_cite="§ 205.200",
                    compiles_to=CompileRule(template="Irrigation water comes from: {answer}."),
                    options=(
                        Option("not_irrigated", text("We do not irrigate", "No regamos"), exclusive=True),
                        Option("well", text("Well", "Pozo")),
                        Option("municipal", text("Municipal supply", "Suministro municipal")),
                        Option(
                            "river_stream_lake",
                            text("River, stream, spring or lake", "Río, arroyo, manantial o lago"),
                        ),
                        Option("pond_reservoir", text("Pond or reservoir", "Estanque o embalse")),
                        Option(
                            "irrigation_district",
                            text("Irrigation or water district", "Distrito de riego o de agua"),
                        ),
                        Option(
                            "catchment_cistern", text("Rain catchment or cistern", "Captación de lluvia o cisterna")
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="irrigation_water_sources",
                    kind="text",
                    label=text(
                        "What are your water sources for irrigation?",
                        "¿Cuáles son tus fuentes de agua para riego?",
                    ),
                    coaching=text(
                        "Identify each source — well, surface water (river, canal, "
                        "reservoir), or a municipal or irrigation-district supply.",
                        "Identifica cada fuente — pozo, agua superficial (río, canal, embalse) o suministro "
                        "municipal o de un distrito de riego.",
                    ),
                    nop_cite="§ 205.200",
                    visible_when=(Condition("irrigation_source_types", "not_includes", "not_irrigated"),),
                    compiles_to=CompileRule(template="Irrigation water sources: {answer}."),
                ),
                Question(
                    key="irrigation_source_names",
                    kind="text",
                    required=False,
                    label=text(
                        "Name the district, river, stream or lake",
                        "Indica el nombre del distrito, río, arroyo o lago",
                    ),
                    visible_when=(
                        Condition(
                            "irrigation_source_types", "includes_any", ["irrigation_district", "river_stream_lake"]
                        ),
                    ),
                    compiles_to=CompileRule(template="Named irrigation water source: {answer}."),
                ),
                Question(
                    key="irrigation_source_types_other",
                    kind="text",
                    required=False,
                    label=text("Describe the other source", "Describe la otra fuente"),
                    visible_when=(Condition("irrigation_source_types", "includes", "other"),),
                    compiles_to=CompileRule(template="Other irrigation water source: {answer}."),
                ),
                # CCOF G6.0 D4, D4a and D5.
                Question(
                    key="shared_irrigation_with_prohibited",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Does your organic cropland share irrigation lines or water, including tailwater, with "
                        "cropland where prohibited materials are applied into the water?",
                        "¿Tus tierras de cultivo orgánico comparten líneas o agua de riego, incluida el agua de "
                        "escorrentía, con tierras donde se aplican materiales prohibidos en el agua?",
                    ),
                    nop_cite="§ 205.202(c)",
                    visible_when=(Condition("irrigation_source_types", "not_includes", "not_irrigated"),),
                    compiles_to=CompileRule(
                        template="Organic cropland shares irrigation lines or water with cropland where prohibited "
                        "materials are applied into the water ({answer}).",
                        template_false="Organic cropland shares no irrigation lines or water with cropland where "
                        "prohibited materials are applied into the water.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="shared_irrigation_responsible",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Is your operation responsible for those applications of prohibited materials?",
                        "¿Tu operación es responsable de esas aplicaciones de materiales prohibidos?",
                    ),
                    visible_when=(Condition("shared_irrigation_with_prohibited", "eq", True),),
                    compiles_to=CompileRule(
                        template="The operation applies the prohibited materials put into the shared water ({answer}).",
                        template_false="Another operation applies the prohibited materials put into the shared water.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="shared_irrigation_mitigation",
                    kind="textarea",
                    required=False,
                    label=text(
                        "What keeps organic crops and land from contact with those materials (valves, backflow "
                        "prevention, separate laterals, timing)?",
                        "¿Qué evita el contacto de los cultivos y la tierra orgánica con esos materiales "
                        "(válvulas, prevención de reflujo, laterales separados, horarios)?",
                    ),
                    nop_cite="§ 205.202(c)",
                    visible_when=(Condition("shared_irrigation_with_prohibited", "eq", True),),
                    compiles_to=CompileRule(
                        template="Measures keeping organic crops and land from prohibited materials in shared "
                        "irrigation water: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="irrigation_piping_map_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach a map or piping diagram showing valves or backflow prevention devices, if installed",
                        "Adjunta un mapa o diagrama de tuberías con las válvulas o dispositivos de prevención de "
                        "reflujo, si los hay",
                    ),
                    visible_when=(Condition("shared_irrigation_with_prohibited", "eq", True),),
                ),
                Question(
                    key="water_quality_tested",
                    kind="boolean",
                    label=text(
                        "Is irrigation water quality tested?",
                        "¿Se analiza la calidad del agua de riego?",
                    ),
                    nop_cite="§ 205.200",
                    visible_when=(Condition("irrigation_source_types", "not_includes", "not_irrigated"),),
                    compiles_to=CompileRule(template="Irrigation water quality testing performed: {answer}."),
                ),
                Question(
                    key="water_quality_test_frequency",
                    kind="text",
                    label=text(
                        "How often is water quality tested?",
                        "¿Con qué frecuencia se analiza la calidad del agua?",
                    ),
                    visible_when=(Condition("water_quality_tested", "truthy"),),
                    compiles_to=CompileRule(template="Water quality testing frequency: {answer}."),
                ),
                Question(
                    key="water_from_irrigation_district",
                    kind="boolean",
                    label=text(
                        "Does any irrigation water come from an irrigation district or other "
                        "shared delivery system?",
                        "¿Parte del agua de riego proviene de un distrito de riego u otro "
                        "sistema de entrega compartido?",
                    ),
                    coaching=text(
                        "Districts and canal companies routinely treat their own canals — "
                        "copper-based algaecides and aquatic herbicides are common. The water "
                        "reaching your field is the district's decision, not yours, so the "
                        "certifier wants to see that you asked.",
                        "Los distritos y las compañías de canales tratan rutinariamente sus propios canales — los "
                        "alguicidas a base de cobre y los herbicidas acuáticos son comunes. El agua que llega a tu "
                        "campo depende de la decisión del distrito, no de la tuya, por lo que el certificador "
                        "quiere ver que preguntaste.",
                    ),
                    nop_cite="§ 205.202(b)",
                    visible_when=(Condition("irrigation_source_types", "not_includes", "not_irrigated"),),
                    compiles_to=CompileRule(
                        template="Irrigation water supplied by a district or shared system: {answer}."
                    ),
                ),
                Question(
                    key="irrigation_district_additives",
                    kind="radio",
                    label=text(
                        "Does the district add substances to the water that are prohibited in " "organic production?",
                        "¿El distrito agrega al agua sustancias prohibidas en la producción " "orgánica?",
                    ),
                    nop_cite="§ 205.202(b)",
                    visible_when=(Condition("water_from_irrigation_district", "truthy"),),
                    compiles_to=CompileRule(
                        template="Prohibited substances added to district irrigation water: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "no_confirmed",
                            text(
                                "No — confirmed by the district, and the confirmation is on file",
                                "No — confirmado por el distrito, y la confirmación está " "archivada",
                            ),
                        ),
                        Option(
                            "yes",
                            text(
                                "Yes — the district applies one or more prohibited substances",
                                "Sí — el distrito aplica una o más sustancias prohibidas",
                            ),
                        ),
                        Option(
                            "unknown",
                            text(
                                "Not yet confirmed with the district",
                                "Todavía no confirmado con el distrito",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="irrigation_district_mitigation",
                    kind="textarea",
                    label=text(
                        "How do you monitor for those substances and keep them off your fields " "and crops?",
                        "¿Cómo monitoreas esas sustancias y evitas que lleguen a tus campos y cultivos?",
                    ),
                    coaching=text(
                        "Typical answers include the district's treatment calendar and "
                        "advance notices, shutting the head gate during and after a treatment "
                        "for a stated interval, an alternate source such as a well during "
                        "that window, or water testing.",
                        "Las respuestas típicas incluyen el calendario de tratamientos del "
                        "distrito y sus avisos anticipados, cerrar la compuerta durante y "
                        "después de un tratamiento por un intervalo definido, una fuente "
                        "alterna como un pozo durante esa ventana, o análisis de agua.",
                    ),
                    nop_cite="§ 205.202(b)",
                    visible_when=(Condition("irrigation_district_additives", "eq", "yes"),),
                    compiles_to=CompileRule(
                        template="Monitoring and prevention for prohibited substances in "
                        "district irrigation water: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="irrigation_district_documentation",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach the district's written statement or treatment schedule",
                        "Adjunta la declaración escrita o el calendario de tratamientos del distrito",
                    ),
                    visible_when=(Condition("water_from_irrigation_district", "truthy"),),
                ),
                Question(
                    key="monitoring_method",
                    kind="checkbox_group",
                    label=text(
                        "How are natural-resource outcomes on this operation monitored?",
                        "¿Cómo se monitorean los resultados de los recursos naturales de " "esta operación?",
                    ),
                    coaching=text(
                        "Photo points are fixed locations photographed on a regular "
                        "schedule to visually track change in vegetation, erosion, or "
                        "habitat over time.",
                        "Los puntos fotográficos son ubicaciones fijas fotografiadas en un "
                        "calendario regular para observar visualmente los cambios en la "
                        "vegetación, la erosión o el hábitat a lo largo del tiempo.",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Natural-resource outcomes are monitored through: {answer}."),
                    options=(
                        Option(
                            "visual_field_checks",
                            text("Visual field checks", "Inspecciones visuales de campo"),
                        ),
                        Option("photo_points", text("Photo points", "Puntos fotográficos fijos")),
                        Option(
                            "soil_test_trends",
                            text(
                                "Soil test trends over time",
                                "Tendencias de análisis de suelo a lo largo del tiempo",
                            ),
                        ),
                        Option(
                            "third_party_conservation_plan",
                            text(
                                "Third-party conservation plan (e.g., NRCS)",
                                "Plan de conservación de un tercero (p. ej., NRCS)",
                            ),
                        ),
                        Option(
                            "surveys", text("Plant, animal or insect surveys", "Censos de plantas, animales o insectos")
                        ),
                        Option(
                            "conservation_map",
                            text("Conservation maps kept up to date", "Mapas de conservación actualizados"),
                        ),
                        Option("farm_logs", text("Farm logs or journals", "Bitácoras o diarios de la finca")),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="monitoring_method_other",
                    kind="text",
                    label=text(
                        "Describe the other monitoring method",
                        "Describe el otro método de monitoreo",
                    ),
                    visible_when=(Condition("monitoring_method", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional natural-resource monitoring method: {answer}."),
                ),
                # REMOVED 2026-08-13 — "What would trigger a change in your natural-resource
                # practices?" (key `practice_change_trigger`).
                #
                # It carried nop_cite § 205.201(a)(3), which is real, but that clause requires
                # "the monitoring practices and procedures ... including the frequency with
                # which they will be performed". Both are already asked above
                # (`monitoring_method` + its frequency) and both appear in the federal template.
                # The change-trigger question itself appears NOWHERE in the USDA Common OSP —
                # checked against the frozen OSP_Crop_WildCrop_V1.docx, Section 7 (Natural
                # Resources) AND Section 2 (Monitoring, which is entirely fraud prevention).
                #
                # Asking a grower an unconditional required question that neither USDA nor the
                # certifier overlay asks is Trazo inventing a requirement — the same fault this
                # codebase refuses at field level. One stored answer exists on OSP 53; it stays
                # in the JSON envelope, inert and unrendered.
            ),
        ),
    ),
)
