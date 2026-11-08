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
                        # OTCO C3 3.1-3 "established perennials in place": a mature orchard plants
                        # nothing new, and "None used" read as if it had no perennial stock at all.
                        Option(
                            "established_in_place",
                            text(
                                "Established perennials only — none planted or replaced this plan period",
                                "Solo perennes ya establecidas — no se plantó ni reemplazó ninguna en este período del plan",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    # WSDA AGR 2121 A1; OTCO C3 3.2-2 (farm-grown seed) and 3.3-3 (contract-supplied).
                    key="seed_source",
                    kind="checkbox_group",
                    label=text("Where does your seed come from?", "¿De dónde proviene tu semilla?"),
                    required=False,
                    nop_cite="§ 205.204",
                    visible_when=(
                        Condition(
                            "seeds_used",
                            "includes_any",
                            ("organic_untreated", "organic_treated", "non_organic_untreated", "non_organic_treated"),
                        ),
                    ),
                    compiles_to=CompileRule(template="Seed sources: {answer}."),
                    options=(
                        Option("save_own", text("Seed saved on this farm", "Semilla guardada en esta finca")),
                        Option("seed_companies", text("Seed companies", "Empresas de semillas")),
                        Option(
                            "contract_provided",
                            text(
                                "Supplied by a buyer or contractor under a growing contract",
                                "Suministrada por un comprador o contratista bajo un contrato de cultivo",
                            ),
                        ),
                        Option("other", text("Other", "Otra")),
                    ),
                ),
                Question(
                    # WSDA AGR 2121 A2a.
                    key="seed_verification_method",
                    kind="textarea",
                    label=text(
                        "How do you verify that the seed you buy as organic is certified organic, and what records "
                        "show it?",
                        "¿Cómo verificas que la semilla que compras como orgánica está certificada, y qué registros "
                        "lo demuestran?",
                    ),
                    coaching=text(
                        "For example: the supplier's organic certificate checked in the USDA Organic Integrity "
                        "Database each season, and the seed tag or invoice naming the lot as certified organic.",
                        "Por ejemplo: el certificado orgánico del proveedor revisado en la base de datos USDA Organic "
                        "Integrity cada temporada, y la etiqueta o factura que nombra el lote como orgánico "
                        "certificado.",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)",
                    visible_when=(Condition("seeds_used", "includes_any", ("organic_untreated", "organic_treated")),),
                    compiles_to=CompileRule(
                        template="How certified organic seed is verified, and the records kept: {answer}"
                    ),
                ),
                Question(
                    # OTCO C3 3.5: an untreated claim needs supporting documentation.
                    key="untreated_seed_documentation",
                    kind="checkbox_group",
                    label=text(
                        "What documents show that seed you use untreated was not treated?",
                        "¿Qué documentos muestran que la semilla que usas sin tratar no fue tratada?",
                    ),
                    required=False,
                    nop_cite="§ 205.204",
                    visible_when=(
                        Condition("seeds_used", "includes_any", ("organic_untreated", "non_organic_untreated")),
                    ),
                    compiles_to=CompileRule(template="Documents showing seed was untreated: {answer}."),
                    options=(
                        Option("seed_tag", text("Seed tag or packet", "Etiqueta o sobre de semilla")),
                        Option(
                            "supplier_statement",
                            text("Supplier or manufacturer statement", "Declaración del proveedor o fabricante"),
                        ),
                        Option(
                            "invoice",
                            text("Invoice or receipt naming it untreated", "Factura o recibo que la nombra sin tratar"),
                        ),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                Question(
                    # OTCO C3 3.3-3: the BUYER's commercial-availability search, when the buyer supplies the seed.
                    key="buyer_search_documents",
                    kind="checkbox_group",
                    label=text(
                        "When a buyer or contractor supplies the seed, which documents do you keep showing they "
                        "searched for organic seed first?",
                        "Cuando un comprador o contratista suministra la semilla, ¿qué documentos conservas que "
                        "muestran que buscó primero semilla orgánica?",
                    ),
                    required=False,
                    nop_cite="§ 205.204(a)(1)",
                    visible_when=(Condition("seed_source", "includes", "contract_provided"),),
                    compiles_to=CompileRule(
                        template="Documents kept for the buyer's or contractor's organic seed search: {answer}."
                    ),
                    options=(
                        Option("seed_search_log", text("Their seed search log", "Su registro de búsqueda de semilla")),
                        Option("invoices", text("Invoices", "Facturas")),
                        Option(
                            "supplier_letters", text("Letters from seed suppliers", "Cartas de proveedores de semilla")
                        ),
                        Option("organic_certificates", text("Organic certificates", "Certificados orgánicos")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                Question(
                    # OTCO C3 3.2-3. OTCO treats seed cleaning as processing (C7 7.3).
                    key="farm_grown_processing_contracted",
                    kind="radio",
                    label=text(
                        "Is any processing of your farm-saved seed or farm-grown transplants contracted to someone "
                        "else (for example, seed cleaning)?",
                        "¿Contratas a alguien para procesar tu semilla guardada o tus trasplantes producidos en la "
                        "finca (por ejemplo, limpieza de semilla)?",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)",
                    compiles_to=CompileRule(
                        template="Contracted processing of farm-grown seed or transplants: {answer}."
                    ),
                    options=(
                        Option("no", text("No", "No")),
                        Option("yes", text("Yes", "Sí")),
                    ),
                ),
                Question(
                    key="farm_grown_processing_description",
                    kind="textarea",
                    label=text(
                        "Who does it, and what do they do?",
                        "¿Quién lo hace y qué hace?",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)",
                    visible_when=(Condition("farm_grown_processing_contracted", "eq", "yes"),),
                    compiles_to=CompileRule(
                        template="Contracted processing of farm-grown seed or transplants: {answer}"
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
            # CCOF G3.0 §B and OTCO C3 3.3 apply to non-organic seed OR non-organic planting stock: an
            # orchard planting non-organic nursery stock with no non-organic seed answers them too
            # (2026.11.25; until then the page opened on seed alone). The seed-only questions below keep
            # the seed gate.
            visible_when_any=(
                Condition("seeds_used", "includes_any", ("non_organic_untreated", "non_organic_treated")),
                Condition("planting_stock_used", "includes", "non_organic"),
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
                        template="Commercial-availability searches before non-organic seed or planting stock is used: {answer}."
                    ),
                    options=(
                        # Retired 2026.11.25: the page opens only when non-organic seed or stock is
                        # declared, so "all organic" contradicted the answer that opened it. A stored one
                        # reads as given and counts unanswered until the operator picks a current option.
                        Option(
                            "all_organic",
                            text(
                                "Not applicable — all seed and planting stock is organic",
                                "No aplica — toda la semilla y el material son orgánicos",
                            ),
                            retired=True,
                        ),
                        Option(
                            "documented_search",
                            text(
                                "Yes — searches are documented (source names, dates, and the "
                                "characteristics evaluated)",
                                "Sí — las búsquedas se documentan (fuentes, fechas y las " "características evaluadas)",
                            ),
                        ),
                        Option(
                            "no_documented_search",
                            text(
                                "No, no search is documented yet",
                                "No, todavía no hay una búsqueda documentada",
                            ),
                            review="Non-organic seed or planting stock is used with no documented search for an "
                            "equivalent organic variety (§ 205.204(a)(1)).",
                        ),
                    ),
                ),
                Question(
                    # CCOF G3.0 B1a; OTCO C3 3.3-1; WSDA AGR 2121 A3a. Authored from NOP 5029 §4.1.2-§4.1.3
                    # (form, quality and quantity), not copied from one agent's list. Price is not one.
                    key="seed_required_characteristics",
                    kind="checkbox_group",
                    label=text(
                        "Which characteristics must a seed have for your operation before an organic variety "
                        "counts as equivalent?",
                        "¿Qué características debe tener una semilla para tu operación antes de que una variedad "
                        "orgánica cuente como equivalente?",
                    ),
                    required=False,
                    visible_when=(
                        Condition("seeds_used", "includes_any", ("non_organic_untreated", "non_organic_treated")),
                    ),
                    nop_cite="§ 205.204(a)(1)",
                    compiles_to=CompileRule(
                        template="Characteristics required of an equivalent organic seed: {answer}."
                    ),
                    options=(
                        Option("untreated_form", text("Available untreated", "Disponible sin tratar")),
                        Option(
                            "allowed_treatment_form",
                            text(
                                "Available with an allowed treatment (pelleted, inoculated)",
                                "Disponible con un tratamiento permitido (peletizada, inoculada)",
                            ),
                        ),
                        Option("germination", text("Germination rate", "Tasa de germinación")),
                        Option(
                            "pest_disease_resistance",
                            text("Pest or disease resistance", "Resistencia a plagas o enfermedades"),
                        ),
                        Option(
                            "regional_adaptation",
                            text(
                                "Regional or seasonal adaptation (days to maturity, drought, cold)",
                                "Adaptación regional o de temporada (días a madurez, sequía, frío)",
                            ),
                        ),
                        Option(
                            "market_traits",
                            text(
                                "Traits the buyer or market requires (size, color, flavor, yield)",
                                "Rasgos que exige el comprador o el mercado (tamaño, color, sabor, rendimiento)",
                            ),
                        ),
                        Option(
                            "quantity",
                            text("Quantity needed (bulk or small)", "Cantidad necesaria (a granel o pequeña)"),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="seed_required_characteristics_other",
                    kind="text",
                    label=text("Other characteristic", "Otra característica"),
                    required=False,
                    visible_when=(Condition("seed_required_characteristics", "includes", "other"),),
                    compiles_to=CompileRule(template="Other characteristic required: {answer}."),
                ),
                Question(
                    # CCOF G3.0 B2; OTCO C3 3.3-2; WSDA AGR 2121 A3a ("at least three organic seed suppliers").
                    key="ca_search_method",
                    kind="checkbox_group",
                    label=text(
                        "How do you determine that an equivalent organic seed is not available?",
                        "¿Cómo determinas que no hay una semilla orgánica equivalente disponible?",
                    ),
                    required=False,
                    visible_when=(
                        Condition("seeds_used", "includes_any", ("non_organic_untreated", "non_organic_treated")),
                    ),
                    nop_cite="§ 205.204(a)(1)",
                    compiles_to=CompileRule(template="How organic seed availability is searched: {answer}."),
                    options=(
                        Option(
                            "three_suppliers",
                            text(
                                "We check with at least three suppliers known to offer organic seed",
                                "Consultamos al menos a tres proveedores conocidos de semilla orgánica",
                            ),
                        ),
                        Option(
                            "third_party_searches",
                            text(
                                "Another party searches for us (a buyer under contract, a seed broker or distributor) "
                                "and checks at least three suppliers",
                                "Otra parte busca por nosotros (un comprador bajo contrato, un corredor o distribuidor "
                                "de semillas) y consulta al menos a tres proveedores",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="ca_search_method_other",
                    kind="textarea",
                    label=text("Describe the other search method", "Describe el otro método de búsqueda"),
                    required=False,
                    visible_when=(Condition("ca_search_method", "includes", "other"),),
                    compiles_to=CompileRule(template="Other search method: {answer}"),
                ),
                Question(
                    # CCOF G3.0 B3; OTCO C3 3.3-2 (records half); WSDA AGR 2121 A3a.
                    key="seed_search_records",
                    kind="checkbox_group",
                    label=text(
                        "Which records of the search do you keep? They should show the crop, the suppliers, your "
                        "site's requirements and the outcome.",
                        "¿Qué registros de la búsqueda conservas? Deben mostrar el cultivo, los proveedores, los "
                        "requisitos de tu sitio y el resultado.",
                    ),
                    required=False,
                    visible_when=(
                        Condition("seeds_used", "includes_any", ("non_organic_untreated", "non_organic_treated")),
                    ),
                    nop_cite="§ 205.103",
                    # No prefill: `seed_search_evidence` answers the radio above with a scalar that is not
                    # one of these options (review of back #252).
                    compiles_to=CompileRule(template="Seed search records kept: {answer}."),
                    options=(
                        Option(
                            "own_search_log",
                            text(
                                "Our own search log (Trazo's seed search records)",
                                "Nuestro propio registro de búsqueda (los registros de búsqueda de semilla de Trazo)",
                            ),
                        ),
                        Option(
                            "supplier_replies",
                            text(
                                "Supplier replies, quotes or catalog pages",
                                "Respuestas, cotizaciones o páginas de catálogo de proveedores",
                            ),
                        ),
                        Option(
                            "third_party_documentation",
                            text(
                                "Documentation from the party that searches for us",
                                "Documentación de la parte que busca por nosotros",
                            ),
                        ),
                        Option("other", text("Other", "Otro")),
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
                        Option(
                            "not_available_as_gmo",
                            text(
                                "The variety is not available in a genetically modified form",
                                "La variedad no existe en forma genéticamente modificada",
                            ),
                        ),
                        Option(
                            "safe_seed_pledge", text("Supplier's Safe Seed Pledge", "Safe Seed Pledge del proveedor")
                        ),
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
                    # OTCO C3 3.5-1.
                    key="seed_treatment_types",
                    kind="checkbox_group",
                    label=text(
                        "Which seed treatments are in use or planned?",
                        "¿Qué tratamientos de semilla usas o planeas usar?",
                    ),
                    required=False,
                    nop_cite="§ 205.204",
                    compiles_to=CompileRule(template="Seed treatments in use or planned: {answer}."),
                    options=(
                        Option("pelletization", text("Pelleting", "Peletizado")),
                        Option("coating", text("Coating or priming", "Recubrimiento o priming")),
                        Option("inoculant", text("Inoculant", "Inoculante")),
                        Option("fungicide", text("Fungicide", "Fungicida")),
                        Option("insecticide", text("Insecticide", "Insecticida")),
                        Option("disinfectant", text("Disinfectant", "Desinfectante")),
                        Option("other", text("Other", "Otro")),
                    ),
                ),
                Question(
                    # WSDA AGR 2121 A2b / A3c: "by the farm, supplier, or a third party".
                    key="seed_treatment_applied_by",
                    kind="checkbox_group",
                    label=text("Who applies the treatments?", "¿Quién aplica los tratamientos?"),
                    required=False,
                    nop_cite="§ 205.204",
                    compiles_to=CompileRule(template="Seed treatments are applied by: {answer}."),
                    options=(
                        Option("farm", text("This farm", "Esta finca")),
                        Option("supplier", text("The seed supplier", "El proveedor de semilla")),
                        Option("third_party", text("A third party", "Un tercero")),
                    ),
                ),
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
            visible_when=(
                Condition("planting_stock_used", "includes_any", ("organic", "non_organic", "established_in_place")),
            ),
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
                Question(
                    # CCOF G3.0 E1a: top-working and graft-overs are routine in orchards.
                    key="grafting_practices",
                    kind="textarea",
                    label=text(
                        "Describe your grafting practices: what is grafted, where the scion wood and rootstock "
                        "come from, and the materials used.",
                        "Describe tus prácticas de injerto: qué se injerta, de dónde vienen las púas y los "
                        "portainjertos, y los materiales que usas.",
                    ),
                    required=False,
                    nop_cite="§ 205.204",
                    visible_when=(Condition("grafts_stock", "eq", "yes"),),
                    compiles_to=CompileRule(template="Grafting practices: {answer}"),
                ),
            ),
        ),
        ModulePage(
            # WSDA AGR 2121 A4: "Optional space for additional information".
            key="f_notes",
            title=text("F. Additional information", "F. Información adicional"),
            questions=(
                Question(
                    key="seeds_additional_notes",
                    kind="textarea",
                    label=text(
                        "Anything else about your seed or planting stock the certifier should know",
                        "Cualquier otra cosa sobre tu semilla o material de plantación que el certificador deba "
                        "saber",
                    ),
                    required=False,
                    compiles_to=CompileRule(template="Additional information on seed and planting stock: {answer}"),
                ),
            ),
        ),
    ),
)
