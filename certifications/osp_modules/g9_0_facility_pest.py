"""
G9.0 — Facility Pest Management.

Sources: 7 CFR 205.271 (facility pest management practice standard), 205.272 (contact with
prohibited substances), 205.103 (recordkeeping). Federal Common OSP Crop & Wild Crop,
Section 9 "Facility Pest Management".

This module covers pests in STRUCTURES — storage buildings, packing sheds, hullers, coolers,
greenhouses, propagation areas, and any other on-farm processing space. G5.0 covers pests in
the FIELD. The two have different regulations and different answers, and a crop operation with
a huller or a cold room has to answer both.

§ 205.271 is a strict hierarchy, and the OSP has to show the operator understands it:

  (a) prevention first — sanitation, removing habitat, food sources, and breeding areas;
  (b) then mechanical, physical, and cultural controls — traps, barriers, light, sound;
  (c) then a substance on the National List, but only if (a) and (b) were insufficient;
  (d) then a synthetic substance NOT on the National List, only if (a) through (c) were
      insufficient AND the substance and its method of application are documented in the OSP
      and approved by the certifying agent in advance.

The question `preventive_measures_documentation` exists because of (c) and (d): the operator
must be able to show that the earlier tiers were tried and failed. An operation that jumps
straight to a material without that record has a finding regardless of what the material is.

§ 205.271(c) also requires that measures be taken to prevent contact between the applied
substance and organic products — hence `contamination_prevention`, which compiles into the
commingling-barriers section rather than practices.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text

G9_0_FACILITY_PEST = Module(
    key="g9_0_facility_pest",
    # Trazo display code for Common OSP Section 9. CCOF's overlay carries facility pest
    # management on its handler forms; the federal Common OSP asks it of crop operations too.
    code="G9.0",
    title=text("Facility Pest Management", "Manejo de plagas en instalaciones"),
    nop_cites=("§ 205.271", "§ 205.272", "§ 205.103"),
    education=(
        text(
            "This section is about pests in buildings and structures — storage, packing "
            "sheds, hullers, coolers, greenhouses, and propagation areas. Pests in the field "
            "belong in your Crop Pest, Weed & Disease module instead.",
            "Esta sección trata sobre plagas en edificios y estructuras — almacenamiento, empacadoras, "
            "descascaradoras, cámaras frías, invernaderos y áreas de propagación. Las plagas del campo corresponden "
            "a tu módulo de Manejo de Plagas, Malezas y Enfermedades del Cultivo.",
        ),
        text(
            "The regulation sets an order you must follow: remove habitat, food sources, and "
            "breeding areas first; then use mechanical and physical controls such as traps "
            "and barriers; only then a substance on the National List; and a synthetic "
            "substance that is not on the National List only with your certifier's advance "
            "approval. Whenever you reach for a material, you need a record showing the "
            "earlier steps were tried and were not enough (§ 205.271).",
            "El reglamento establece un orden que debes seguir: primero eliminar el hábitat, las fuentes de "
            "alimento y las áreas de reproducción; luego usar controles mecánicos y físicos como trampas y "
            "barreras; solo después una sustancia de la Lista Nacional; y una sustancia sintética que no esté en la "
            "Lista Nacional solo con aprobación previa de tu certificador. Siempre que recurras a un material, "
            "necesitas un registro que muestre que los pasos anteriores se intentaron y no fueron suficientes (§ "
            "205.271).",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — our operation has no storage, packing, or processing structures "
        "where organic product is held, and uses no pest control materials in any structure.",
        "No aplica — nuestra operación no tiene estructuras de almacenamiento, empaque o "
        "procesamiento donde se guarde producto orgánico, y no usa materiales de control de "
        "plagas en ninguna estructura.",
    ),
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_records_contracts",
            title=text("A. Records & pest control contracts", "A. Registros y contratos de control de plagas"),
            education=(
                text(
                    "If a pest control company services your buildings, the certifier will "
                    "want evidence that the company knows the site handles organic product. "
                    "Their standard program is usually built around synthetic materials, so "
                    "an unnotified company is a common route to an unapproved application.",
                    "Si una empresa de control de plagas atiende tus edificios, el certificador querrá evidencia de "
                    "que la empresa sabe que el sitio maneja producto orgánico. Su programa estándar generalmente "
                    "se basa en materiales sintéticos, por lo que una empresa no notificada es una vía común hacia "
                    "una aplicación no aprobada.",
                ),
            ),
            questions=(
                Question(
                    key="uses_pest_control_company",
                    kind="boolean",
                    label=text(
                        "Does your operation use a contracted pest control company?",
                        "¿Tu operación usa una empresa de control de plagas contratada?",
                    ),
                    nop_cite="§ 205.271",
                    compiles_to=CompileRule(template="Contracted pest control company used: {answer}."),
                ),
                Question(
                    key="pest_control_company_name",
                    kind="text",
                    label=text(
                        "Name of the pest control company",
                        "Nombre de la empresa de control de plagas",
                    ),
                    visible_when=(Condition("uses_pest_control_company", "truthy"),),
                    compiles_to=CompileRule(template="Pest control company: {answer}."),
                ),
                Question(
                    key="pest_control_company_notified",
                    kind="radio",
                    label=text(
                        "Has the pest control company been notified that this is a certified " "organic operation?",
                        "¿Se ha notificado a la empresa de control de plagas que esta es una "
                        "operación orgánica certificada?",
                    ),
                    coaching=text(
                        "Written notification is far stronger than a verbal one. A service "
                        "agreement naming the allowed materials, or a letter on file, is what "
                        "an inspector asks to see.",
                        "La notificación escrita es mucho más sólida que la verbal. Un acuerdo "
                        "de servicio que nombre los materiales permitidos, o una carta en "
                        "archivo, es lo que un inspector pide ver.",
                    ),
                    nop_cite="§ 205.271",
                    visible_when=(Condition("uses_pest_control_company", "truthy"),),
                    compiles_to=CompileRule(template="Pest control company notified of organic status: {answer}."),
                    options=(
                        Option(
                            "yes_written",
                            text(
                                "Yes — in writing, and the notification is on file",
                                "Sí — por escrito, y la notificación está en archivo",
                            ),
                        ),
                        Option(
                            "yes_verbal",
                            text("Yes — verbally only", "Sí — solo verbalmente"),
                        ),
                        Option("no", text("Not yet", "Todavía no")),
                    ),
                ),
                Question(
                    key="pest_control_records",
                    kind="checkbox_group",
                    label=text(
                        "Which facility pest control records do you keep?",
                        "¿Qué registros de control de plagas en instalaciones conservas?",
                    ),
                    nop_cite="§ 205.103",
                    compiles_to=CompileRule(
                        template="Facility pest control records maintained: {answer}.",
                        section_key="recordkeeping_description",
                    ),
                    options=(
                        Option("sighting_logs", text("Pest sighting records", "Registros de avistamiento de plagas")),
                        Option(
                            "structural_maintenance",
                            text("Structural maintenance logs", "Bitácoras de mantenimiento estructural"),
                        ),
                        Option(
                            "site_visit_reports", text("Service or site visit reports", "Informes de servicio o visita")
                        ),
                        Option(
                            "application_records",
                            text("Pesticide application records", "Registros de aplicación de plaguicidas"),
                        ),
                        Option("pest_control_map", text("Pest control device map", "Mapa de dispositivos de control")),
                        Option(
                            "monitoring_device_records",
                            text("Monitoring device records", "Registros de dispositivos de monitoreo"),
                        ),
                        Option(
                            "corrective_actions",
                            text(
                                "Records showing sanitation and structural issues were corrected",
                                "Registros que muestran que se corrigieron problemas de " "saneamiento y estructurales",
                            ),
                        ),
                        Option(
                            "none_yet",
                            text("No facility pest records kept yet", "Todavía no se conservan registros"),
                            exclusive=True,
                        ),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_prevention",
            title=text("B. Prevention & physical controls", "B. Prevención y controles físicos"),
            education=(
                text(
                    "These are the first two tiers of § 205.271. Answer them honestly even if "
                    "you have no pest pressure — an inspector reads an empty prevention answer "
                    "as an operation that has not thought about it.",
                    "Estos son los dos primeros niveles del § 205.271. Respóndelos con honestidad aunque no tengas "
                    "presión de plagas — un inspector interpreta una respuesta de prevención vacía como una "
                    "operación que no lo ha considerado.",
                ),
            ),
            questions=(
                Question(
                    key="preventive_practices",
                    kind="checkbox_group",
                    label=text(
                        "Which preventive practices are in place in your structures?",
                        "¿Qué prácticas preventivas tienes en tus estructuras?",
                    ),
                    nop_cite="§ 205.271(a)",
                    compiles_to=CompileRule(template="Facility pest prevention practices: {answer}."),
                    options=(
                        Option(
                            "sanitation",
                            text(
                                "Sanitation — cleaning up spilled product, culls, and debris",
                                "Saneamiento — limpieza de producto derramado, descartes y " "residuos",
                            ),
                        ),
                        Option(
                            "habitat_removal",
                            text(
                                "Removing pest habitat, food sources, and breeding areas",
                                "Eliminación de hábitat, fuentes de alimento y áreas de " "reproducción de plagas",
                            ),
                        ),
                        Option(
                            "exclusion",
                            text(
                                "Exclusion — sealing gaps, screens, door sweeps, air curtains",
                                "Exclusión — sellado de espacios, mallas, burletes, cortinas " "de aire",
                            ),
                        ),
                        Option(
                            "environmental_control",
                            text(
                                "Managing temperature, humidity, or light to discourage pests",
                                "Manejo de temperatura, humedad o luz para desalentar plagas",
                            ),
                        ),
                        Option(
                            "monitoring",
                            text(
                                "Routine monitoring and inspection of the structure",
                                "Monitoreo e inspección rutinaria de la estructura",
                            ),
                        ),
                        Option(
                            "stock_rotation",
                            text(
                                "Stock rotation so product does not sit long enough to attract pests",
                                "Rotación de existencias para que el producto no permanezca lo "
                                "suficiente como para atraer plagas",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="preventive_practices_other",
                    kind="text",
                    label=text("Describe the other preventive practice", "Describe la otra práctica preventiva"),
                    visible_when=(Condition("preventive_practices", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional facility pest prevention practice: {answer}"),
                ),
                Question(
                    key="mechanical_controls",
                    kind="checkbox_group",
                    label=text(
                        "Which mechanical or physical pest controls are in place?",
                        "¿Qué controles mecánicos o físicos de plagas tienes?",
                    ),
                    nop_cite="§ 205.271(b)",
                    compiles_to=CompileRule(template="Mechanical and physical facility pest controls: {answer}."),
                    options=(
                        Option("traps", text("Traps", "Trampas")),
                        Option("barriers", text("Barriers or screens", "Barreras o mallas")),
                        Option("light", text("Light traps", "Trampas de luz")),
                        Option("sound", text("Sound or ultrasonic devices", "Dispositivos sonoros o ultrasónicos")),
                        Option("repellents", text("Nonsynthetic repellents", "Repelentes no sintéticos")),
                        Option("temperature", text("Freezing or heat treatment", "Tratamiento por frío o calor")),
                        Option(
                            "none",
                            text(
                                "None used — prevention alone has been sufficient",
                                "Ninguno — la prevención por sí sola ha sido suficiente",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="c_materials",
            title=text("C. Pest control materials", "C. Materiales de control de plagas"),
            questions=(
                Question(
                    key="material_tier",
                    kind="radio",
                    label=text(
                        "What kinds of pest control materials are used in your structures?",
                        "¿Qué tipos de materiales de control de plagas se usan en tus estructuras?",
                    ),
                    coaching=text(
                        "A synthetic substance that is not on the National List needs your "
                        "certifier's approval BEFORE it is applied, and the substance and its "
                        "method of application must be described in this plan.",
                        "Una sustancia sintética que no está en la Lista Nacional necesita la aprobación de tu "
                        "certificador ANTES de aplicarse, y la sustancia y su método de aplicación deben "
                        "describirse en este plan.",
                    ),
                    nop_cite="§ 205.271(c)-(d)",
                    compiles_to=CompileRule(template="Facility pest control materials used: {answer}."),
                    options=(
                        Option(
                            "none",
                            text("None are used", "No se usa ninguno"),
                        ),
                        Option(
                            "non_production_only",
                            text(
                                "Only in non-production areas (offices, restrooms, break rooms)",
                                "Solo en áreas fuera de producción (oficinas, baños, comedores)",
                            ),
                        ),
                        Option(
                            "national_list",
                            text(
                                "Materials on the National List, entered on our OSP inputs list",
                                "Materiales de la Lista Nacional, incluidos en nuestra lista de " "insumos del OSP",
                            ),
                        ),
                        Option(
                            "synthetic_approved",
                            text(
                                "Synthetic materials not on the National List, approved by our "
                                "certifier in advance and entered on our OSP inputs list",
                                "Materiales sintéticos fuera de la Lista Nacional, aprobados "
                                "previamente por nuestro certificador e incluidos en nuestra lista de "
                                "insumos del OSP",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="preventive_measures_documentation",
                    kind="checkbox_group",
                    label=text(
                        "How do you document that prevention and physical controls were not "
                        "enough, before a material is applied?",
                        "¿Cómo documentas que la prevención y los controles físicos no fueron suficientes, antes de "
                        "aplicar un material?",
                    ),
                    coaching=text(
                        "This is what makes a material application defensible. Without it, the "
                        "record shows a material used first rather than last.",
                        "Esto es lo que hace defendible la aplicación de un material. Sin ello, "
                        "el registro muestra un material usado primero en lugar de último.",
                    ),
                    nop_cite="§ 205.271(c)",
                    visible_when=(Condition("material_tier", "one_of", ["national_list", "synthetic_approved"]),),
                    compiles_to=CompileRule(
                        template="Documentation that preventive and physical controls were "
                        "insufficient before applying a material: {answer}."
                    ),
                    options=(
                        Option("pest_log", text("Pest control log", "Bitácora de control de plagas")),
                        Option("incident_reports", text("Incident reports", "Informes de incidentes")),
                        Option(
                            "monitoring_counts",
                            text(
                                "Monitoring counts showing the threshold was exceeded",
                                "Conteos de monitoreo que muestran que se superó el umbral",
                            ),
                        ),
                        Option(
                            "service_reports",
                            text(
                                "Pest control company service reports",
                                "Informes de servicio de la empresa de control de plagas",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="preventive_measures_documentation_other",
                    kind="text",
                    label=text("Describe the other documentation", "Describe la otra documentación"),
                    visible_when=(Condition("preventive_measures_documentation", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional documentation of insufficiency: {answer}"),
                ),
                Question(
                    key="contamination_prevention",
                    kind="checkbox_group",
                    label=text(
                        "How do you prevent pest control materials from contacting organic "
                        "product, packaging, and food contact surfaces?",
                        "¿Cómo evitas que los materiales de control de plagas entren en contacto con el producto "
                        "orgánico, el empaque y las superficies de contacto con alimentos?",
                    ),
                    nop_cite="§ 205.271(c)",
                    visible_when=(Condition("material_tier", "one_of", ["national_list", "synthetic_approved"]),),
                    compiles_to=CompileRule(
                        template="Measures preventing contact between pest control materials "
                        "and organic product: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option(
                            "bait_stations",
                            text(
                                "Bait stations or other containerized methods",
                                "Estaciones de cebo u otros métodos contenidos",
                            ),
                        ),
                        Option(
                            "cracks_crevices",
                            text(
                                "Placed in cracks and crevices with no organic contact",
                                "Colocados en grietas y hendiduras sin contacto orgánico",
                            ),
                        ),
                        Option(
                            "product_removed",
                            text(
                                "Product and packaging documented as removed during treatment",
                                "Producto y empaque documentados como retirados durante el " "tratamiento",
                            ),
                        ),
                        Option(
                            "covered",
                            text(
                                "Non-permeable covers over product and equipment",
                                "Cubiertas no permeables sobre producto y equipo",
                            ),
                        ),
                        Option(
                            "rinse_before_organic",
                            text(
                                "Surfaces rinsed before organic product returns",
                                "Superficies enjuagadas antes de que regrese el producto " "orgánico",
                            ),
                        ),
                        Option("residue_testing", text("Residue testing", "Pruebas de residuos")),
                        Option(
                            "employee_training",
                            text("Documented employee training", "Capacitación documentada del personal"),
                        ),
                    ),
                ),
            ),
        ),
    ),
)
