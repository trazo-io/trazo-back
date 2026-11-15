"""
G3.1 Container & Greenhouse/Shadehouse Production (CCOF ORGB46, V1 R8 9/21/2021).

CCOF asks every operation for this form, even if only to say it does not apply: "Complete this form if your organic
system includes any crop or plant production that does not take place in the ground ... Complete this form if you
have any crop production in greenhouses, shadehouses, and/or buildings." Until 2026-11-09 Trazo had no G3.1, so a
packet said nothing where CCOF expects either the form or "None of these", and a reviewer reads silence as
"not answered". (The module keyed `g3_1_seedlings` is G3.0a Annual Seedlings; see `stubs.py`.)

The module's not-applicable attestation is CCOF A1's "None of these. Stop. Do not complete this form." Each later
section opens on the answer that makes it apply, as the form's own "Skip to" lines do. When the module is marked not
applicable while the plan or the records say otherwise (own organic seedlings, organic planting stock sold, container
production on a parcel, an indoor production), the PDF prints a [REVIEW] line naming each one
(`certifications/services/structure_production.py`). Nothing is suggested into A1: a container parcel can be potted
nursery stock or a container crop, and a guess between them would be a claim.

OTCO (A1 Aquaponics, Container, and Greenhouse Production) and WSDA leave these systems out of this plan by a scope
decision (`otco/scope.yaml`); they ask no stub of a field grower, so only CCOF's register cites this module.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text

_SECTION = "practices_procedures"


def _other_text(key, visible_on, label_en, label_es, template):
    return Question(
        key=key,
        kind="textarea",
        label=text(label_en, label_es),
        required=True,
        visible_when=(Condition(visible_on, "includes", "other"),),
        compiles_to=CompileRule(template=template),
    )


G3_1_CONTAINER_GREENHOUSE = Module(
    key="g3_1_container_greenhouse",
    code="G3.1",
    title=text(
        "Container & Greenhouse/Shadehouse Production",
        "Producción en contenedores y en invernadero o casa sombra",
    ),
    nop_cites=("§ 205.200", "§ 205.201", "§ 205.202", "§ 205.272"),
    education=(
        text(
            "Complete this module if your organic system includes any crop or plant production that does not take "
            "place in the ground (annual seedlings or transplants, planting stock or other nursery production in pots, "
            "edible sprouts, wheatgrass or microgreens, mushrooms, or crops grown to harvest in containers), or any "
            "crop production in greenhouses, shadehouses or buildings. If none of these apply, mark it not applicable.",
            "Completa este módulo si tu sistema orgánico incluye cualquier producción de cultivos o plantas que no se "
            "haga en el suelo (plántulas anuales o trasplantes, material de plantación u otra producción de vivero en "
            "macetas, germinados comestibles, pasto de trigo o microverdes, hongos, o cultivos llevados a cosecha en "
            "contenedores), o cualquier producción en invernaderos, casas sombra o edificios. Si nada de esto aplica, "
            "márcalo como no aplicable.",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "None of these: no annual seedlings, potted planting stock, sprouts, microgreens, mushrooms or container "
        "crops are produced, and no crop is grown in a greenhouse, shadehouse or building.",
        "Nada de esto: no se producen plántulas anuales, material de plantación en macetas, germinados, "
        "microverdes, hongos ni cultivos en contenedores, y ningún cultivo se produce en invernadero, casa sombra "
        "o edificio.",
    ),
    default_section_key=_SECTION,
    pages=(
        ModulePage(
            key="a_types_locations",
            title=text("A. Production types and locations", "A. Tipos de producción y ubicaciones"),
            questions=(
                Question(
                    # CCOF G3.1 A1.
                    key="structure_production_types",
                    kind="checkbox_group",
                    label=text(
                        "Which of the following do you produce organically? Check all that apply.",
                        "¿Cuáles de estos produces de forma orgánica? Marca todo lo que corresponda.",
                    ),
                    nop_cite="§ 205.201",
                    compiles_to=CompileRule(
                        template="Container, greenhouse, shadehouse or building production: {answer}."
                    ),
                    options=(
                        Option(
                            "annual_seedlings",
                            text(
                                "Annual seedlings (e.g. tomato transplants or other annual plants grown from seed)",
                                "Plántulas anuales (p. ej. trasplantes de tomate u otras plantas anuales cultivadas "
                                "a partir de semilla)",
                            ),
                        ),
                        Option(
                            "potted_planting_stock",
                            text(
                                "Planting stock (other than annual seedlings) or other nursery production in pots "
                                "(e.g. ornamentals, potted herbs)",
                                "Material de plantación (que no sea plántula anual) u otra producción de vivero en "
                                "macetas (p. ej. ornamentales, hierbas en maceta)",
                            ),
                        ),
                        Option(
                            "edible_sprouts",
                            text(
                                "Edible sprouts (including fodder for livestock)",
                                "Germinados comestibles (incluido forraje para ganado)",
                            ),
                        ),
                        Option(
                            "microgreens",
                            text(
                                "Wheatgrass, microgreens, pea/sunflower shoots, or similar",
                                "Pasto de trigo, microverdes, brotes de chícharo o girasol, o similares",
                            ),
                        ),
                        Option(
                            "mushrooms",
                            text(
                                "Mushrooms (CCOF also asks G3.2 Mushroom Production)",
                                "Hongos (CCOF también pide G3.2 Producción de hongos)",
                            ),
                        ),
                        Option(
                            "container_crops",
                            text(
                                "Crops grown to harvest/maturity in containers (in substrate or growing media, or in "
                                "hydroponic, aeroponic or aquaponic systems)",
                                "Cultivos llevados a cosecha o madurez en contenedores (en sustrato o medio de "
                                "cultivo, o en sistemas hidropónicos, aeropónicos o acuapónicos)",
                            ),
                        ),
                        Option(
                            "in_ground_in_structures",
                            text(
                                "Crops grown in the ground (not in containers) within greenhouses, shadehouses "
                                "and/or buildings",
                                "Cultivos en el suelo (no en contenedores) dentro de invernaderos, casas sombra o "
                                "edificios",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="annual_seedlings_use",
                    kind="checkbox_group",
                    label=text("Annual seedlings are produced:", "Las plántulas anuales se producen:"),
                    visible_when=(Condition("structure_production_types", "includes", "annual_seedlings"),),
                    compiles_to=CompileRule(template="Annual seedlings are produced {answer}."),
                    options=(
                        Option("on_farm_use", text("For on-farm use", "Para uso en la finca")),
                        Option("for_sale", text("For sale", "Para venta")),
                    ),
                ),
                Question(
                    key="potted_stock_use",
                    kind="checkbox_group",
                    label=text(
                        "Planting stock or nursery production in pots is produced:",
                        "El material de plantación o la producción de vivero en macetas se produce:",
                    ),
                    visible_when=(Condition("structure_production_types", "includes", "potted_planting_stock"),),
                    compiles_to=CompileRule(
                        template="Planting stock or nursery production in pots is produced {answer}."
                    ),
                    options=(
                        Option("on_farm_use", text("For on-farm use", "Para uso en la finca")),
                        Option("for_sale", text("For sale", "Para venta")),
                    ),
                ),
                Question(
                    # CCOF G3.1 A2.
                    key="locations_within_certified_parcel",
                    kind="radio",
                    label=text(
                        "For these production types, are all growing locations within the boundaries of a "
                        "certified organic parcel?",
                        "Para estos tipos de producción, ¿todos los lugares de cultivo están dentro de los límites "
                        "de una parcela orgánica certificada?",
                    ),
                    coaching=text(
                        "Every organic growing location must be on your certifier's record before organic sales. "
                        "Show each greenhouse, shadehouse or building on your parcel map.",
                        "Cada lugar de cultivo orgánico debe estar en el registro de tu certificadora antes de las "
                        "ventas orgánicas. Muestra cada invernadero, casa sombra o edificio en tu mapa de parcela.",
                    ),
                    nop_cite="§ 205.202",
                    compiles_to=CompileRule(
                        template="All growing locations for these production types are within a certified organic "
                        "parcel: {answer}."
                    ),
                    options=(
                        Option("yes", text("Yes", "Sí")),
                        Option(
                            "no",
                            text(
                                "No: a Parcel Application is submitted for each other location",
                                "No: se presenta una solicitud de parcela por cada otro lugar",
                            ),
                            review=(
                                "A growing location is outside the certified parcels; CCOF G3.1 A2 asks for a Parcel "
                                "Application for each one before organic sales."
                            ),
                        ),
                    ),
                ),
                # 2026-11-15: CCOF G4.2 A8 asks an operation growing in enclosed structures what it does to conserve
                # resources there. Asked here, where the structures are; a module answered not applicable has none.
                Question(
                    key="enclosed_structure_conservation",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "What do you do to conserve resources in and around these structures?",
                        "¿Qué haces para conservar recursos en estas estructuras y a su alrededor?",
                    ),
                    nop_cite="§ 205.200",
                    compiles_to=CompileRule(
                        template="Conservation measures for production in enclosed structures: {answer}."
                    ),
                    options=(
                        Option("water_conservation", text("Water conservation", "Conservación del agua")),
                        Option("energy_conservation", text("Energy conservation", "Conservación de energía")),
                        Option("recycling", text("Recycling", "Reciclaje")),
                        Option("composting", text("Composting", "Compostaje")),
                        Option(
                            "outdoor_plantings",
                            text("Diverse outdoor plantings", "Plantaciones diversas al aire libre"),
                        ),
                        Option(
                            "surrounding_habitat",
                            text("Surrounding habitat restoration", "Restauración del hábitat circundante"),
                        ),
                        Option("sustainable_packaging", text("Sustainable packaging", "Empaques sostenibles")),
                        Option(
                            "greenhouse_rotation",
                            text(
                                "Crop rotation within the greenhouses",
                                "Rotación de cultivos dentro de los invernaderos",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                        Option("none", text("None of these", "Ninguna de estas"), exclusive=True),
                    ),
                ),
                Question(
                    key="enclosed_structure_conservation_other",
                    kind="text",
                    required=False,
                    label=text("Describe the other measure", "Describe la otra medida"),
                    visible_when=(Condition("enclosed_structure_conservation", "includes", "other"),),
                    compiles_to=CompileRule(template="Other conservation measure in enclosed structures: {answer}."),
                ),
            ),
        ),
        ModulePage(
            key="b_materials_practices",
            title=text("B. Production materials and practices", "B. Materiales y prácticas de producción"),
            questions=(
                Question(
                    # CCOF G3.1 B1.
                    key="uses_growing_media",
                    kind="radio",
                    label=text(
                        "Do you use growing media (including substrate, planting mix, potting soils)?",
                        "¿Usas medio de cultivo (incluido sustrato, mezcla para siembra, tierra para macetas)?",
                    ),
                    nop_cite="§ 205.203",
                    compiles_to=CompileRule(template="Growing media used: {answer}."),
                    options=(
                        Option("yes", text("Yes", "Sí")),
                        Option("none_used", text("No, none used", "No, no se usa")),
                    ),
                ),
                Question(
                    # CCOF G3.1 B1a.
                    key="growing_media_components_listed",
                    kind="boolean",
                    label=text(
                        "Are all components of your growing media (e.g. peat moss, coconut fiber, vermiculite, "
                        "perlite, sand, compost, microbial inoculants) on your materials list?",
                        "¿Todos los componentes de tu medio de cultivo (p. ej. turba, fibra de coco, vermiculita, "
                        "perlita, arena, composta, inoculantes microbianos) están en tu lista de materiales?",
                    ),
                    coaching=text(
                        "List each one under Production aids on the Materials Application.",
                        "Registra cada uno en Auxiliares de producción en la Solicitud de materiales.",
                    ),
                    nop_cite="§ 205.203",
                    visible_when=(Condition("uses_growing_media", "eq", "yes"),),
                    compiles_to=CompileRule(
                        template="All growing media components are on the materials list: {answer}.",
                        section_key="inputs_list",
                    ),
                ),
                Question(
                    # CCOF G3.1 B1b.
                    key="growing_media_new_each_cycle",
                    kind="radio",
                    label=text(
                        "Is new growing media used for each production cycle?",
                        "¿Se usa medio de cultivo nuevo en cada ciclo de producción?",
                    ),
                    coaching=text(
                        "Spent growing media from nonorganic production may not be reused for organic production.",
                        "El medio de cultivo usado en producción no orgánica no puede reutilizarse en producción "
                        "orgánica.",
                    ),
                    nop_cite="§ 205.203",
                    visible_when=(Condition("uses_growing_media", "eq", "yes"),),
                    compiles_to=CompileRule(template="New growing media for each production cycle: {answer}."),
                    options=(
                        Option("yes", text("Yes", "Sí")),
                        Option(
                            "no_reused", text("No, growing media is reused", "No, el medio de cultivo se reutiliza")
                        ),
                    ),
                ),
                Question(
                    key="growing_media_reuse_source",
                    kind="textarea",
                    label=text(
                        "Describe the source of the reused growing media.",
                        "Describe de dónde viene el medio de cultivo reutilizado.",
                    ),
                    visible_when=(Condition("growing_media_new_each_cycle", "eq", "no_reused"),),
                    compiles_to=CompileRule(template="Source of reused growing media: {answer}"),
                ),
                Question(
                    # CCOF G3.1 B1c.
                    key="growing_media_disposal",
                    kind="checkbox_group",
                    label=text(
                        "How is growing media disposed of at the end of the production cycle?",
                        "¿Cómo se desecha el medio de cultivo al final del ciclo de producción?",
                    ),
                    coaching=text(
                        "Spent growing media must be managed so it does not contribute to contamination or "
                        "degradation of natural resources.",
                        "El medio de cultivo usado debe manejarse de forma que no contribuya a la contaminación ni a "
                        "la degradación de los recursos naturales.",
                    ),
                    nop_cite="§ 205.200",
                    visible_when=(Condition("uses_growing_media", "eq", "yes"),),
                    compiles_to=CompileRule(template="Spent growing media: {answer}."),
                    options=(
                        Option(
                            "reused_onsite", text("Reused or recycled on site", "Se reutiliza o recicla en el sitio")
                        ),
                        Option("composted_onsite", text("Composted on site", "Se composta en el sitio")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                _other_text(
                    "growing_media_disposal_other",
                    "growing_media_disposal",
                    "Explain how else spent growing media is disposed of.",
                    "Explica de qué otra forma se desecha el medio de cultivo usado.",
                    "Spent growing media, other: {answer}",
                ),
                Question(
                    # CCOF G3.1 B2.
                    key="irrigation_effluent_management",
                    kind="checkbox_group",
                    label=text(
                        "How do you manage irrigation water effluent or runoff so it does not contaminate the "
                        "surrounding environment (waterways, soil)?",
                        "¿Cómo manejas el agua de riego sobrante o de escurrimiento para que no contamine el entorno "
                        "(cuerpos de agua, suelo)?",
                    ),
                    nop_cite="§ 205.200",
                    compiles_to=CompileRule(template="Irrigation effluent and runoff: {answer}."),
                    options=(
                        Option("recaptured_reused", text("Recaptured and reused", "Se recaptura y se reutiliza")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                _other_text(
                    "irrigation_effluent_other",
                    "irrigation_effluent_management",
                    "Explain how else irrigation effluent or runoff is managed.",
                    "Explica de qué otra forma se maneja el agua sobrante o de escurrimiento.",
                    "Irrigation effluent and runoff, other: {answer}",
                ),
                Question(
                    # CCOF G3.1 B3a. B3 itself ("Do you produce organic edible sprouts?") is A1's sprouts option.
                    key="sprout_seed_always_organic",
                    kind="boolean",
                    label=text(
                        "Do you always use organic seed to produce edible sprouts?",
                        "¿Siempre usas semilla orgánica para producir germinados comestibles?",
                    ),
                    coaching=text(
                        "Organic seed is always required for edible sprout production.",
                        "La semilla orgánica siempre es obligatoria para producir germinados comestibles.",
                    ),
                    nop_cite="§ 205.204(a)(1)",
                    visible_when=(Condition("structure_production_types", "includes", "edible_sprouts"),),
                    compiles_to=CompileRule(
                        template="Organic seed is always used for edible sprouts: {answer}.",
                        template_false="Organic seed is not always used for edible sprouts.",
                    ),
                ),
                Question(
                    # CCOF G3.1 B3b.
                    key="sprout_seed_sanitizers",
                    kind="radio",
                    label=text(
                        "Are sanitizers used on sprouting seed?",
                        "¿Se usan sanitizantes en la semilla para germinar?",
                    ),
                    nop_cite="§ 205.605",
                    visible_when=(Condition("structure_production_types", "includes", "edible_sprouts"),),
                    compiles_to=CompileRule(template="Sanitizers on sprouting seed: {answer}."),
                    options=(
                        Option("none", text("No sanitizers are used", "No se usan sanitizantes")),
                        Option(
                            "listed",
                            text(
                                "Yes, and each one is on my materials list",
                                "Sí, y cada uno está en mi lista de materiales",
                            ),
                        ),
                        # Review of back #361: a sanitizer not on the list is a true answer the operator must be able
                        # to give, and the procedure is asked of it too.
                        Option(
                            "not_listed",
                            text(
                                "Yes, but not every one is on my materials list yet",
                                "Sí, pero todavía no todos están en mi lista de materiales",
                            ),
                            review=(
                                "A sanitizer used on sprouting seed is not on the materials list; CCOF G3.1 B3b asks "
                                "that every one be listed."
                            ),
                        ),
                    ),
                ),
                Question(
                    key="sprout_seed_sanitizing_procedure",
                    kind="textarea",
                    label=text(
                        "Describe the seed sanitizing and rinsing procedures.",
                        "Describe los procedimientos de sanitización y enjuague de la semilla.",
                    ),
                    visible_when=(Condition("sprout_seed_sanitizers", "one_of", ["listed", "not_listed"]),),
                    compiles_to=CompileRule(template="Sprouting seed sanitizing and rinsing: {answer}"),
                ),
            ),
        ),
        ModulePage(
            # CCOF G3.1 B4: "Attach a detailed description of the production system(s)", items a-g.
            key="b4_container_systems",
            title=text(
                "B4. Crops grown to harvest in containers",
                "B4. Cultivos llevados a cosecha en contenedores",
            ),
            visible_when=(Condition("structure_production_types", "includes", "container_crops"),),
            questions=(
                Question(
                    key="container_system_photos",
                    kind="upload",
                    label=text("Photographs of the system", "Fotografías del sistema"),
                    nop_cite="§ 205.201",
                ),
                Question(
                    key="container_system_types",
                    kind="checkbox_group",
                    label=text("Type of system", "Tipo de sistema"),
                    nop_cite="§ 205.201",
                    compiles_to=CompileRule(template="Container production systems: {answer}."),
                    options=(
                        Option(
                            "substrate_containers",
                            text(
                                "Substrate production in pots, bags, troughs or other containers",
                                "Producción en sustrato en macetas, bolsas, canaletas u otros contenedores",
                            ),
                        ),
                        Option("hydroponic", text("Hydroponic", "Hidropónico")),
                        Option("aeroponic", text("Aeroponic", "Aeropónico")),
                        Option("aquaponic", text("Aquaponic", "Acuapónico")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                _other_text(
                    "container_system_types_other",
                    "container_system_types",
                    "Describe the other system.",
                    "Describe el otro sistema.",
                    "Other container production system: {answer}",
                ),
                Question(
                    key="container_production_cycle",
                    kind="textarea",
                    label=text(
                        "The stages and length of the production cycle for each crop grown",
                        "Las etapas y la duración del ciclo de producción de cada cultivo",
                    ),
                    nop_cite="§ 205.201",
                    compiles_to=CompileRule(template="Container production cycle by crop: {answer}"),
                ),
                Question(
                    key="container_root_support",
                    kind="textarea",
                    label=text(
                        "If substrate or growing media is not used, how are plants and roots supported (e.g. net "
                        "pots, trays, polystyrene sheets)?",
                        "Si no se usa sustrato ni medio de cultivo, ¿cómo se sostienen las plantas y las raíces (p. "
                        "ej. macetas de red, charolas, láminas de poliestireno)?",
                    ),
                    required=False,
                    nop_cite="§ 205.201",
                    compiles_to=CompileRule(
                        template="How plants and roots are supported without growing media: {answer}"
                    ),
                ),
                Question(
                    key="container_media_biology",
                    kind="textarea",
                    label=text(
                        "If substrate or growing media is used, does it contain biological activity or organic "
                        "matter, and does it feed the plant throughout the whole production cycle?",
                        "Si se usa sustrato o medio de cultivo, ¿tiene actividad biológica o materia orgánica, y "
                        "nutre a la planta durante todo el ciclo de producción?",
                    ),
                    required=False,
                    nop_cite="§ 205.203",
                    compiles_to=CompileRule(template="Growing media biology and nutrition: {answer}"),
                ),
                Question(
                    key="container_liquid_nutrition",
                    kind="textarea",
                    label=text(
                        "If liquid nutrition is used, how is it delivered to the roots (indirectly through the "
                        "growing media, or directly, such as NFT, flood and drain, deep water culture, rafts, "
                        "aeroponics)?",
                        "Si se usa nutrición líquida, ¿cómo llega a las raíces (de forma indirecta a través del medio "
                        "de cultivo, o directa, como NFT, inundación y drenaje, cultivo en agua profunda, balsas, "
                        "aeroponía)?",
                    ),
                    required=False,
                    nop_cite="§ 205.203",
                    compiles_to=CompileRule(template="How liquid nutrition reaches the roots: {answer}"),
                ),
                Question(
                    key="container_fish_integrated",
                    kind="boolean",
                    label=text(
                        "Are fish integrated into the system (aquaponics)?",
                        "¿El sistema integra peces (acuaponía)?",
                    ),
                    nop_cite="§ 205.201",
                    compiles_to=CompileRule(template="Fish integrated into the system: {answer}."),
                ),
            ),
        ),
        ModulePage(
            key="c_nonorganic_structures",
            title=text(
                "C. Nonorganic production in greenhouses, shadehouses and buildings",
                "C. Producción no orgánica en invernaderos, casas sombra y edificios",
            ),
            questions=(
                Question(
                    # CCOF G3.1 C1.
                    key="organic_in_structures",
                    kind="boolean",
                    label=text(
                        "Does any of this organic production take place in greenhouses, shadehouses or buildings?",
                        "¿Alguna parte de esta producción orgánica se hace en invernaderos, casas sombra o "
                        "edificios?",
                    ),
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(
                        template="Organic production in greenhouses, shadehouses or buildings: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    # CCOF G3.1 C2.
                    key="nonorganic_in_structures",
                    kind="boolean",
                    label=text(
                        "Does your operation also have nonorganic production in greenhouses, shadehouses or "
                        "buildings?",
                        "¿Tu operación también tiene producción no orgánica en invernaderos, casas sombra o "
                        "edificios?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("organic_in_structures", "truthy"),),
                    compiles_to=CompileRule(
                        template="Nonorganic production also in greenhouses, shadehouses or buildings: {answer}.",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    # CCOF G3.1 C3.
                    key="nonorganic_structure_arrangement",
                    kind="checkbox_group",
                    label=text(
                        "Which of these describe your nonorganic production in greenhouses, shadehouses or "
                        "buildings?",
                        "¿Cuáles de estos describen tu producción no orgánica en invernaderos, casas sombra o "
                        "edificios?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("nonorganic_in_structures", "truthy"),),
                    compiles_to=CompileRule(
                        template="Nonorganic production in structures: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "dedicated_areas",
                            text(
                                "Organic and nonorganic production take place in different, dedicated growing areas "
                                "(e.g. adjacent structures, bays, sectors), shown on the parcel map",
                                "La producción orgánica y la no orgánica se hacen en áreas de cultivo distintas y "
                                "dedicadas (p. ej. estructuras contiguas, naves, sectores), mostradas en el mapa de "
                                "parcela",
                            ),
                        ),
                        Option(
                            "alternating_production",
                            text(
                                "We seek CCOF approval to use specific organic growing areas for nonorganic "
                                "production when organic production is not taking place there (alternating "
                                "production)",
                                "Buscamos la aprobación de CCOF para usar áreas de cultivo orgánico específicas para "
                                "producción no orgánica cuando ahí no hay producción orgánica (producción alternada)",
                            ),
                        ),
                    ),
                ),
                Question(
                    # CCOF G3.1 C3a.
                    key="organic_area_identification",
                    kind="checkbox_group",
                    label=text(
                        "How do you identify organic and nonorganic growing areas?",
                        "¿Cómo identificas las áreas de cultivo orgánicas y no orgánicas?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("nonorganic_in_structures", "truthy"),),
                    compiles_to=CompileRule(
                        template="Organic and nonorganic growing areas are identified by: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option("clear_signage", text("Clear signage", "Letreros claros")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                _other_text(
                    "organic_area_identification_other",
                    "organic_area_identification",
                    "Describe how else the growing areas are identified.",
                    "Describe de qué otra forma se identifican las áreas de cultivo.",
                    "Growing areas identified, other: {answer}",
                ),
                Question(
                    # CCOF G3.1 C3b.
                    key="organic_plant_distinction",
                    kind="checkbox_group",
                    label=text(
                        "How do you label or distinguish organic and nonorganic plants from production through "
                        "shipment or sale?",
                        "¿Cómo etiquetas o distingues las plantas orgánicas de las no orgánicas desde la producción "
                        "hasta el envío o la venta?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("nonorganic_in_structures", "truthy"),),
                    compiles_to=CompileRule(
                        template="Organic and nonorganic plants are distinguished by: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "tray_plant_tags",
                            text(
                                "Tray or plant tags (attached with the labels on G7.0)",
                                "Etiquetas en charolas o plantas (adjuntas con las etiquetas en G7.0)",
                            ),
                        ),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                _other_text(
                    "organic_plant_distinction_other",
                    "organic_plant_distinction",
                    "Describe how else organic and nonorganic plants are distinguished.",
                    "Describe de qué otra forma se distinguen las plantas orgánicas de las no orgánicas.",
                    "Plants distinguished, other: {answer}",
                ),
                Question(
                    # CCOF G3.1 C3c.
                    key="media_fertility_commingling_prevention",
                    kind="checkbox_group",
                    label=text(
                        "How do you keep growing media and fertility materials for organic and nonorganic "
                        "production from mixing during preparation and storage?",
                        "¿Cómo evitas que se mezclen el medio de cultivo y los materiales de fertilidad para la "
                        "producción orgánica y la no orgánica durante la preparación y el almacenamiento?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("nonorganic_in_structures", "truthy"),),
                    compiles_to=CompileRule(
                        template="Growing media and fertility materials are kept apart by: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "only_listed_materials",
                            text(
                                "Only materials on my materials list are used, for both organic and nonorganic "
                                "production",
                                "Solo se usan materiales de mi lista de materiales, tanto en la producción orgánica "
                                "como en la no orgánica",
                            ),
                        ),
                        Option(
                            "cleanout_sop",
                            text(
                                "Standard Operating Procedure (SOP) for equipment cleanout (attached below)",
                                "Procedimiento operativo estándar (POE) para limpiar el equipo (adjunto abajo)",
                            ),
                            requires_upload="commingling_sop_upload",
                        ),
                        Option(
                            "separate_areas",
                            text(
                                "Separate preparation and/or storage areas",
                                "Áreas de preparación o almacenamiento separadas",
                            ),
                        ),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                Question(
                    key="commingling_sop_upload",
                    kind="upload",
                    label=text("Equipment cleanout SOP", "POE de limpieza del equipo"),
                    required=False,
                    nop_cite="§ 205.272",
                    visible_when=(Condition("media_fertility_commingling_prevention", "includes", "cleanout_sop"),),
                ),
                _other_text(
                    "media_fertility_commingling_other",
                    "media_fertility_commingling_prevention",
                    "Describe how else mixing is prevented.",
                    "Describe de qué otra forma se evita la mezcla.",
                    "Growing media and fertility materials kept apart, other: {answer}",
                ),
                Question(
                    # CCOF G3.1 C3d.
                    key="shared_ventilation_drift",
                    kind="checkbox_group",
                    label=text(
                        "How do you prevent drift of prohibited materials through shared ventilation systems?",
                        "¿Cómo evitas la deriva de materiales prohibidos por sistemas de ventilación compartidos?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("nonorganic_in_structures", "truthy"),),
                    compiles_to=CompileRule(
                        template="Drift through shared ventilation: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "no_shared_ventilation",
                            text(
                                "Not applicable, no shared ventilation systems",
                                "No aplica, no hay ventilación compartida",
                            ),
                            exclusive=True,
                        ),
                        Option(
                            "only_listed_materials",
                            text(
                                "Only materials on my materials list are applied, for both organic and nonorganic "
                                "production",
                                "Solo se aplican materiales de mi lista de materiales, tanto en la producción orgánica "
                                "como en la no orgánica",
                            ),
                        ),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                _other_text(
                    "shared_ventilation_other",
                    "shared_ventilation_drift",
                    "Describe how else drift through shared ventilation is prevented.",
                    "Describe de qué otra forma se evita la deriva por la ventilación compartida.",
                    "Drift through shared ventilation, other: {answer}",
                ),
                Question(
                    # CCOF G3.1 C3e.
                    key="shared_irrigation_contact",
                    kind="checkbox_group",
                    label=text(
                        "How do you prevent contact with prohibited materials applied through shared irrigation "
                        "systems?",
                        "¿Cómo evitas el contacto con materiales prohibidos aplicados por sistemas de riego "
                        "compartidos?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("nonorganic_in_structures", "truthy"),),
                    compiles_to=CompileRule(
                        template="Contact through shared irrigation: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "no_shared_irrigation",
                            text("Not applicable, no shared irrigation systems", "No aplica, no hay riego compartido"),
                            exclusive=True,
                        ),
                        Option(
                            "only_listed_materials",
                            text(
                                "Only materials on my materials list are applied, for both organic and nonorganic "
                                "production",
                                "Solo se aplican materiales de mi lista de materiales, tanto en la producción orgánica "
                                "como en la no orgánica",
                            ),
                        ),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                _other_text(
                    "shared_irrigation_other",
                    "shared_irrigation_contact",
                    "Describe how else contact through shared irrigation is prevented.",
                    "Describe de qué otra forma se evita el contacto por el riego compartido.",
                    "Contact through shared irrigation, other: {answer}",
                ),
            ),
        ),
        ModulePage(
            # CCOF G3.1 D. "Not applicable, not seeking approval for alternating production" is C3 left without the
            # alternating option, so the page opens only on it.
            key="d_alternating",
            title=text("D. Alternating production", "D. Producción alternada"),
            visible_when=(Condition("nonorganic_structure_arrangement", "includes", "alternating_production"),),
            education=(
                text(
                    "Prohibited substances may not be applied to certified organic land. CCOF may approve using an "
                    "organic growing area for nonorganic production while no organic production is there, if "
                    "prohibited substances do not contact land at the location, practices prevent contact when "
                    "organic production resumes, and records are sufficient. CCOF tells you whether the plan is "
                    "approved.",
                    "No se pueden aplicar sustancias prohibidas en tierra orgánica certificada. CCOF puede aprobar "
                    "el uso de un área de cultivo orgánico para producción no orgánica mientras ahí no haya "
                    "producción orgánica, si las sustancias prohibidas no tocan la tierra del lugar, las prácticas "
                    "evitan el contacto al reanudar la producción orgánica y los registros son suficientes. CCOF te "
                    "avisa si el plan se aprueba.",
                ),
            ),
            questions=(
                Question(
                    # CCOF G3.1 D1.
                    key="alternating_flooring",
                    kind="radio",
                    label=text(
                        "Which applies to the organic growing locations you want to use for alternating production?",
                        "¿Qué aplica a los lugares de cultivo orgánico que quieres usar para producción alternada?",
                    ),
                    nop_cite="§ 205.202",
                    compiles_to=CompileRule(template="Alternating production locations: {answer}."),
                    options=(
                        Option(
                            "impermeable_flooring",
                            text(
                                "They have solid, permanent, impermeable flooring (e.g. concrete)",
                                "Tienen piso sólido, permanente e impermeable (p. ej. concreto)",
                            ),
                        ),
                        Option(
                            "no_impermeable_flooring",
                            text(
                                "They do not have solid, permanent, impermeable flooring (e.g. soil, landscape "
                                "fabric, gravel)",
                                "No tienen piso sólido, permanente e impermeable (p. ej. suelo, malla, grava)",
                            ),
                            review=(
                                "Alternating production over a surface that is not solid, permanent and impermeable: "
                                "CCOF notes approval in this case is rare."
                            ),
                        ),
                    ),
                ),
                Question(
                    key="alternating_flooring_photos",
                    kind="upload",
                    label=text("Photographs of the locations", "Fotografías de los lugares"),
                    nop_cite="§ 205.202",
                ),
                Question(
                    key="alternating_ground_protection",
                    kind="textarea",
                    label=text(
                        "Explain how prohibited materials are kept from contacting the land beneath the growing area.",
                        "Explica cómo se evita que los materiales prohibidos toquen la tierra debajo del área de "
                        "cultivo.",
                    ),
                    nop_cite="§ 205.202",
                    visible_when=(Condition("alternating_flooring", "eq", "no_impermeable_flooring"),),
                    compiles_to=CompileRule(template="How the land beneath is protected: {answer}"),
                ),
                Question(
                    # CCOF G3.1 D1a.
                    key="alternating_locations",
                    kind="textarea",
                    label=text(
                        "List each organic growing location for alternating production (e.g. parcel name, "
                        "greenhouse or building number) and the crop types to be produced there.",
                        "Indica cada lugar de cultivo orgánico para producción alternada (p. ej. nombre de la "
                        "parcela, número de invernadero o edificio) y los tipos de cultivo que se producirán ahí.",
                    ),
                    coaching=text(
                        "Update this plan and have it approved again before using any other location.",
                        "Actualiza este plan y vuelve a obtener la aprobación antes de usar cualquier otro lugar.",
                    ),
                    nop_cite="§ 205.202",
                    compiles_to=CompileRule(template="Locations for alternating production: {answer}"),
                ),
                Question(
                    # CCOF G3.1 D1b.
                    key="alternating_timing",
                    kind="radio",
                    label=text(
                        "When do you expect to use these locations for nonorganic production?",
                        "¿Cuándo esperas usar estos lugares para producción no orgánica?",
                    ),
                    nop_cite="§ 205.202",
                    compiles_to=CompileRule(template="Nonorganic use of these locations: {answer}."),
                    options=(
                        Option(
                            "intermittent",
                            text("Intermittently, based on customer demand", "De forma intermitente, según la demanda"),
                        ),
                        Option("regular_schedule", text("On a regular schedule", "Con un calendario regular")),
                    ),
                ),
                Question(
                    key="alternating_schedule",
                    kind="textarea",
                    label=text("Describe the schedule.", "Describe el calendario."),
                    visible_when=(Condition("alternating_timing", "eq", "regular_schedule"),),
                    compiles_to=CompileRule(template="Alternating production schedule: {answer}"),
                ),
                Question(
                    # CCOF G3.1 D2.
                    key="alternating_cleaning_sop",
                    kind="textarea",
                    label=text(
                        "Describe your procedure for cleaning all equipment and surfaces of prohibited-substance "
                        "residue before organic production resumes.",
                        "Describe tu procedimiento para limpiar todo el equipo y las superficies de residuos de "
                        "sustancias prohibidas antes de reanudar la producción orgánica.",
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(
                        template="Cleaning before organic production resumes: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="alternating_cleaning_sop_upload",
                    kind="upload",
                    label=text(
                        "Cleaning SOP, if you keep it as a document", "POE de limpieza, si lo tienes como documento"
                    ),
                    required=False,
                    nop_cite="§ 205.272",
                ),
                Question(
                    # CCOF G3.1 D2a.
                    key="alternating_documentation",
                    kind="checkbox_group",
                    label=text(
                        "How do you document the start and end dates of each organic and nonorganic production "
                        "cycle, and that the cleaning procedure was done before each organic cycle?",
                        "¿Cómo documentas las fechas de inicio y fin de cada ciclo de producción orgánica y no "
                        "orgánica, y que el procedimiento de limpieza se hizo antes de cada ciclo orgánico?",
                    ),
                    nop_cite="§ 205.103",
                    compiles_to=CompileRule(
                        template="Alternating production is documented in: {answer}.",
                        section_key="recordkeeping_description",
                    ),
                    options=(
                        Option("production_records", text("Production records", "Registros de producción")),
                        Option("cleaning_logs", text("Cleaning logs", "Bitácoras de limpieza")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                _other_text(
                    "alternating_documentation_other",
                    "alternating_documentation",
                    "Describe how else it is documented.",
                    "Describe de qué otra forma se documenta.",
                    "Alternating production documented, other: {answer}",
                ),
            ),
        ),
    ),
)
