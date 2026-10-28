"""
G3.0 — Seeds & Planting Stock.

Sources: 7 CFR 205.204 (seeds and planting stock practice standard), 205.2 (definitions:
annual seedling, planting stock), 205.105 (excluded methods — GMO). Topic order follows the
public Common OSP grower template; all wording authored for Trazo.

Trazo already holds seed evidence (`seed_lot_number`, `seed_certification_status`,
`seed_treatment`, `seed_supplier_name`, `seed_search_attempts`) — the prefill sources declared
here surface it as SUGGESTIONS the operator confirms, never as answers.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Prefill, Question, text

G3_0_SEEDS = Module(
    key="g3_0_seeds",
    code="G3.0",
    title=text("Seeds & Planting Stock", "Semillas y material de plantación"),
    nop_cites=("§ 205.2", "§ 205.204", "§ 205.105"),
    education=(
        text(
            "Organic production must use organically grown seeds, annual seedlings, and "
            "planting stock. Non-organic seed or planting stock may be used only when an "
            "equivalent organic variety is not commercially available (§ 205.204(a)(1)) — "
            "and organic seed must always be used to produce edible sprouts.",
            "La producción orgánica debe usar semillas, plántulas anuales y material de "
            "plantación cultivados orgánicamente. Solo puede usarse semilla o material no "
            "orgánico cuando una variedad orgánica equivalente no está comercialmente "
            "disponible (§ 205.204(a)(1)) — y para brotes comestibles la semilla siempre "
            "debe ser orgánica.",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — no seed, annual seedlings, or planting stock are used or planned " "at this operation.",
        "No aplica — esta operación no usa ni planea usar semillas, plántulas anuales ni " "material de plantación.",
    ),
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_usage",
            title=text("A. What you plant", "A. Qué siembras"),
            questions=(
                Question(
                    key="seeds_used",
                    kind="checkbox_group",
                    label=text("Seeds", "Semillas"),
                    coaching=text(
                        'Count seed as "with treatment" if it is fungicide- or '
                        "insecticide-treated, or carries any material that remains on the "
                        "seed when planted (inoculants, pelleting, coating, priming or "
                        "encrusting materials).",
                        'Considera la semilla "con tratamiento" si está tratada con fungicida o insecticida, o '
                        "lleva cualquier material que permanece en la semilla al sembrar (inoculantes, peletizado, "
                        "recubrimiento, priming o incrustación).",
                    ),
                    nop_cite="§ 205.204",
                    prefill=Prefill(source="seed_status"),
                    compiles_to=CompileRule(template="Seeds used in organic production: {answer}."),
                    options=(
                        Option("none", text("None used", "No se usan"), exclusive=True),
                        Option("organic_untreated", text("Organic, untreated", "Orgánica, sin tratar")),
                        Option("organic_treated", text("Organic, with treatment", "Orgánica, con tratamiento")),
                        Option(
                            "non_organic_untreated",
                            text("Non-organic, untreated", "No orgánica, sin tratar"),
                        ),
                        Option(
                            "non_organic_treated",
                            text("Non-organic, with treatment", "No orgánica, con tratamiento"),
                        ),
                    ),
                ),
                Question(
                    key="seedlings_used",
                    kind="checkbox_group",
                    label=text("Annual seedlings (transplants)", "Plántulas anuales (trasplantes)"),
                    coaching=text(
                        "An annual seedling completes its life cycle or produces a "
                        "harvestable yield within the same crop year it was planted. "
                        "Annual seedlings must be organically produced (§ 205.204(a)).",
                        "Una plántula anual completa su ciclo de vida o produce una cosecha "
                        "dentro del mismo año de cultivo en que se plantó. Las plántulas "
                        "anuales deben ser de producción orgánica (§ 205.204(a)).",
                    ),
                    nop_cite="§ 205.204(a)",
                    compiles_to=CompileRule(template="Annual seedlings: {answer}."),
                    options=(
                        Option("none", text("None used", "No se usan"), exclusive=True),
                        Option(
                            "purchased_organic",
                            text(
                                "Purchased certified organic seedlings (organic certificate " "kept for each supplier)",
                                "Plántulas orgánicas certificadas compradas (se conserva el "
                                "certificado orgánico de cada proveedor)",
                            ),
                        ),
                        Option(
                            "own_organic",
                            text(
                                "Produced on-farm under organic management",
                                "Producidas en la finca bajo manejo orgánico",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="planting_stock_used",
                    kind="checkbox_group",
                    label=text("Planting stock", "Material de plantación"),
                    coaching=text(
                        "Planting stock is any plant or plant tissue other than annual "
                        "seedlings used in production or propagation — rhizomes, shoots, "
                        "cuttings, roots, tubers, perennial nursery stock (§ 205.2).",
                        "Material de plantación es cualquier planta o tejido vegetal distinto "
                        "de las plántulas anuales usado en producción o propagación — "
                        "rizomas, brotes, esquejes, raíces, tubérculos, plantines perennes "
                        "de vivero (§ 205.2).",
                    ),
                    nop_cite="§ 205.2",
                    compiles_to=CompileRule(template="Planting stock: {answer}."),
                    options=(
                        Option("none", text("None used", "No se usa"), exclusive=True),
                        Option("organic", text("Organic", "Orgánico")),
                        Option("non_organic", text("Non-organic", "No orgánico")),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_commercial_availability",
            title=text("B. Commercial availability", "B. Disponibilidad comercial"),
            education=(
                text(
                    "Commercial availability means the ability to obtain seed or planting "
                    "stock in the appropriate form, quality, or quantity for your operation "
                    "(§ 205.2). Price is not a permitted consideration. An equivalent "
                    "organic variety is one of the same type or with the agronomic and "
                    "marketing characteristics your site requires — days to harvest, "
                    "disease resistance, regional adaptation, flavor, yield.",
                    "Disponibilidad comercial significa poder obtener semilla o material de plantación en la forma, "
                    "calidad o cantidad apropiada para tu operación (§ 205.2). El precio no es un criterio "
                    "permitido. Una variedad orgánica equivalente es una del mismo tipo o con las características "
                    "agronómicas y de mercado que tu sitio requiere — días a cosecha, resistencia a enfermedades, "
                    "adaptación regional, sabor, rendimiento.",
                ),
            ),
            visible_when=(
                Condition(
                    "seeds_used",
                    "includes_any",
                    ("non_organic_untreated", "non_organic_treated"),
                ),
            ),
            questions=(
                Question(
                    key="ca_search_before_use",
                    kind="radio",
                    label=text(
                        "Before using non-organic seed or planting stock, do you document a "
                        "search for an equivalent organic variety?",
                        "Antes de usar semilla o material no orgánico, ¿documentas una búsqueda de una variedad "
                        "orgánica equivalente?",
                    ),
                    coaching=text(
                        "Document at least three sources known to offer organic seed for "
                        "each crop, with the site-specific form/quality/quantity reasons an "
                        "organic equivalent did not meet. Trazo's Seed Search activity "
                        "records each attempt for you.",
                        "Documenta al menos tres fuentes conocidas de semilla orgánica por cultivo, con las razones "
                        "específicas de forma/calidad/cantidad por las que un equivalente orgánico no cumplió. La "
                        "actividad Búsqueda de Semilla de Trazo registra cada intento.",
                    ),
                    nop_cite="§ 205.204(a)(1)",
                    prefill=Prefill(source="seed_search_evidence"),
                    compiles_to=CompileRule(
                        template="Commercial-availability searches before non-organic seed use: {answer}."
                    ),
                    options=(
                        Option(
                            "all_organic",
                            text(
                                "Not applicable — all seed and planting stock is organic",
                                "No aplica — toda la semilla y el material son orgánicos",
                            ),
                        ),
                        Option(
                            "documented_search",
                            text(
                                "Yes — searches are documented (source names, dates, and the "
                                "characteristics evaluated)",
                                "Sí — las búsquedas se documentan (fuentes, fechas y las " "características evaluadas)",
                            ),
                        ),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="c_gmo",
            title=text("C. Excluded methods (GMO)", "C. Métodos excluidos (OGM)"),
            education=(
                text(
                    "Products of excluded methods (genetic engineering) are prohibited in "
                    "organic production (§ 205.105(e)). Non-organic seed and planting stock "
                    "must be documented as non-GMO.",
                    "Los productos de métodos excluidos (ingeniería genética) están "
                    "prohibidos en la producción orgánica (§ 205.105(e)). La semilla y el "
                    "material no orgánicos deben documentarse como no transgénicos.",
                ),
            ),
            visible_when=(
                Condition(
                    "seeds_used",
                    "includes_any",
                    ("non_organic_untreated", "non_organic_treated"),
                ),
            ),
            questions=(
                Question(
                    key="gmo_documentation",
                    kind="checkbox_group",
                    label=text(
                        "How do you document that non-organic seed and planting stock are " "not genetically modified?",
                        "¿Cómo documentas que la semilla y el material no orgánicos no son genéticamente "
                        "modificados?",
                    ),
                    nop_cite="§ 205.105(e)",
                    compiles_to=CompileRule(template="Non-GMO status documented via: {answer}."),
                    options=(
                        Option(
                            "all_organic",
                            text(
                                "Not applicable — all seed and planting stock is organic",
                                "No aplica — toda la semilla y el material son orgánicos",
                            ),
                            exclusive=True,
                        ),
                        Option(
                            "supplier_statement",
                            text("Non-GMO statement from the supplier", "Declaración no-OGM del proveedor"),
                        ),
                        Option("catalog", text("Catalog or label statement", "Declaración en catálogo o etiqueta")),
                        Option("seed_tag", text("Seed tag kept on file", "Etiqueta de semilla archivada")),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="d_treatments",
            title=text("D. Seed treatments", "D. Tratamientos de semilla"),
            education=(
                text(
                    "Any material on or applied to seed — pelleting, coating, priming, "
                    "inoculants, fungicides — must be allowed under the National List and "
                    "approved for your operation before use (§ 205.105, § 205.601).",
                    "Todo material sobre la semilla o aplicado a ella — peletizado, recubrimiento, priming, "
                    "inoculantes, fungicidas — debe estar permitido por la Lista Nacional y aprobado para tu "
                    "operación antes de usarse (§ 205.105, § 205.601).",
                ),
            ),
            visible_when=(Condition("seeds_used", "includes_any", ("organic_treated", "non_organic_treated")),),
            questions=(
                Question(
                    key="treatment_verification",
                    kind="checkbox_group",
                    label=text(
                        "How do you verify that seed treatments use only allowed, non-GMO " "materials?",
                        "¿Cómo verificas que los tratamientos de semilla usan solo materiales permitidos y no "
                        "transgénicos?",
                    ),
                    nop_cite="§ 205.105",
                    compiles_to=CompileRule(template="Basis on which seed treatment materials are allowed: {answer}."),
                    options=(
                        Option("omri_wsda", text("OMRI or WSDA listing", "Listado OMRI o WSDA")),
                        Option(
                            "certifier_approval",
                            text("Written certifier approval", "Aprobación escrita del certificador"),
                        ),
                    ),
                ),
                Question(
                    key="treatments_on_inputs_list",
                    kind="boolean",
                    label=text(
                        "Are all seed treatment materials included on your OSP inputs list?",
                        "¿Todos los materiales de tratamiento de semilla están en tu lista de insumos del OSP?",
                    ),
                    nop_cite="§ 205.201(a)(2)",
                    compiles_to=CompileRule(
                        template="Seed treatment materials on the OSP inputs list: {answer}.",
                        section_key="inputs_list",
                    ),
                ),
            ),
        ),
        ModulePage(
            key="e_grafting",
            title=text("E. Grafting", "E. Injertos"),
            visible_when=(Condition("planting_stock_used", "includes_any", ("organic", "non_organic")),),
            questions=(
                Question(
                    key="grafts_stock",
                    kind="radio",
                    label=text(
                        "Does your operation graft planting stock?",
                        "¿Tu operación injerta material de plantación?",
                    ),
                    coaching=text(
                        "If yes, grafting materials (wax, sealants, tape) must appear on " "your OSP inputs list.",
                        "Si es así, los materiales de injerto (cera, selladores, cinta) deben aparecer en tu lista "
                        "de insumos del OSP.",
                    ),
                    nop_cite="§ 205.204",
                    compiles_to=CompileRule(template="Grafting of planting stock: {answer}."),
                    options=(
                        Option("no", text("No", "No")),
                        Option(
                            "yes",
                            text(
                                "Yes — grafting materials are listed on the OSP inputs list",
                                "Sí — los materiales de injerto están en la lista de insumos " "del OSP",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
)
