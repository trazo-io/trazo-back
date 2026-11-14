"""
G2.0 — Monitoring & Organic Fraud Prevention.

Sources: 7 CFR 205.201(a)(3) (the OSP's monitoring practices and procedures), 205.201(a)(6),
205.103. Federal Common OSP Crop & Wild Crop, Section 2 "Monitoring Practices and Procedures".

Strengthening Organic Enforcement (SOE) made fraud prevention part of every operation's OSP,
which is why this module carries **no "Not applicable" attestation** — the federal template
offers none for this section either. An operation with a simple supply chain answers that its
risks are few; it does not skip the section.

Trazo already stores a fraud-prevention plan document and a responsible person on the
Establishment (`fraud_prevention_plan_document`, `ofpp_responsible_person`). That upload was
the only fraud-prevention capture before this module: a farmer had to author the plan
somewhere else and attach the PDF. The value of the federal template is that answering the
questions *is* the plan, so this module asks them. The existing upload remains the home for a
plan the operator wrote themselves; the coaching points there rather than creating a second
upload path for the same document.

Scale matters here and the education text says so. The regulation asks for measures
"appropriate to the operation's activities, scope, and complexity" — a 200-acre walnut grower
selling to one handler does not need a processor's fraud programme, and a plan that overclaims
is worse than a short honest one.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text

#: OTCO's fraud prevention plan, Section 3: the steps where fraud could enter a grower's supply chain. Each is
#: (option key, option label, the short name its two columns print under). The short names stay plain so the
#: PDF reads as OTCO's table rows: "Transport: how is fraud prevented at this point?".
CONTROL_POINTS = (
    (
        "seed_stock",
        text("Buying seed, transplants or planting stock", "Compra de semilla, plántulas o material de plantación"),
        text("Seed and planting stock", "Semilla y material de plantación"),
    ),
    (
        "inputs",
        text(
            "Buying fertilizers, soil amendments or pest control materials",
            "Compra de fertilizantes, enmiendas del suelo o materiales para el control de plagas",
        ),
        text("Inputs", "Insumos"),
    ),
    (
        "purchased_product",
        text(
            "Buying organic crops or products from other operations",
            "Compra de cultivos o productos orgánicos a otras operaciones",
        ),
        text("Organic product bought in", "Producto orgánico comprado"),
    ),
    (
        "custom_operators",
        text(
            "Work done under contract, such as application, harvest or hulling",
            "Trabajo por contrato, como aplicación, cosecha o descascarado",
        ),
        text("Contracted work", "Trabajo por contrato"),
    ),
    (
        "transport",
        text(
            "Transport, including by a carrier that is not certified",
            "Transporte, incluido el que hace una empresa sin certificación",
        ),
        text("Transport", "Transporte"),
    ),
    (
        "offsite_storage",
        text(
            "Storage, cooling or packing away from the farm", "Almacenamiento, enfriamiento o empaque fuera de la finca"
        ),
        text("Storage and packing away from the farm", "Almacenamiento y empaque fuera de la finca"),
    ),
    (
        "split_handling",
        text(
            "Steps where organic and nonorganic product share people, equipment or space",
            "Pasos en que el producto orgánico y el no orgánico comparten personal, equipo o espacio",
        ),
        text("Shared people, equipment or space", "Personal, equipo o espacio en común"),
    ),
    (
        "sales",
        text(
            "Selling: invoices, bills of lading and labels that name the product organic",
            "Venta: facturas, conocimientos de embarque y etiquetas que identifican el producto como orgánico",
        ),
        text("Selling", "Venta"),
    ),
    (
        "import_export",
        text("Importing or exporting", "Importación o exportación"),
        text("Importing or exporting", "Importación o exportación"),
    ),
    (
        "other",
        text("Other (name it below)", "Otro (nómbralo abajo)"),
        text("Other control point", "Otro punto de control"),
    ),
)


def _control_point_columns(key: str, name: dict) -> tuple:
    """OTCO's two table columns for one picked control point: its prevention strategies, and its monitoring with
    how often. Shown only when the point is picked; optional like every question added after plans were filed."""
    shown = (Condition("critical_control_points", "includes", key),)
    return (
        Question(
            key=f"ccp_{key}_strategy",
            kind="textarea",
            label=text(
                f"{name['en']}: how do you prevent fraud at this point?",
                f"{name['es']}: ¿cómo previenes el fraude en este punto?",
            ),
            required=False,
            visible_when=shown,
            compiles_to=CompileRule(template=f"{name['en']}, how fraud is prevented: {{answer}}"),
        ),
        Question(
            key=f"ccp_{key}_monitoring",
            kind="textarea",
            label=text(
                f"{name['en']}: how do you check that this works, and how often?",
                f"{name['es']}: ¿cómo compruebas que esto funciona y con qué frecuencia?",
            ),
            required=False,
            visible_when=shown,
            compiles_to=CompileRule(template=f"{name['en']}, how it is monitored and how often: {{answer}}"),
        ),
    )


G2_0_FRAUD_PREVENTION = Module(
    key="g2_0_fraud_prevention",
    # Trazo display code for Common OSP Section 2.
    code="G2.0",
    title=text(
        "Monitoring & Organic Fraud Prevention",
        "Monitoreo y prevención del fraude orgánico",
    ),
    nop_cites=("§ 205.201(a)(3)", "§ 205.201(a)(6)", "§ 205.103"),
    education=(
        text(
            "Organic fraud is nonorganic product being sold, labeled, or represented as "
            "organic. It can happen anywhere in a supply chain, including upstream of your "
            "operation. This section identifies where the risk sits in your business and what "
            "you do about it.",
            "El fraude orgánico ocurre cuando un producto no orgánico se vende, etiqueta o representa como "
            "orgánico. Puede suceder en cualquier punto de una cadena de suministro, incluso antes de tu operación. "
            "Esta sección identifica dónde está el riesgo en tu negocio y qué haces al respecto.",
        ),
        text(
            "Your measures must be appropriate to your operation's activities, scope, and "
            "complexity — not to someone else's. A grower who sells one crop to one handler "
            "has a short, honest answer here, and that is the correct answer. Claiming "
            "controls you do not actually run is the failure mode to avoid.",
            "Tus medidas deben ser apropiadas a las actividades, el alcance y la complejidad de tu operación — no a "
            "las de otra. Un productor que vende un cultivo a un solo manejador tiene una respuesta breve y honesta "
            "aquí, y esa es la respuesta correcta. Declarar controles que en realidad no ejecutas es el error que "
            "se debe evitar.",
        ),
    ),
    # The federal Common OSP offers no "Not applicable" for Section 2 — SOE applies to every
    # certified operation. Neither do we.
    allows_not_applicable=False,
    default_section_key="monitoring_plan",
    pages=(
        ModulePage(
            key="a_risk_areas",
            title=text("A. Where risk exists", "A. Dónde existe el riesgo"),
            questions=(
                Question(
                    key="fraud_risk_areas",
                    kind="checkbox_group",
                    label=text(
                        "Which of these describe your operation?",
                        "¿Cuáles de estas describen tu operación?",
                    ),
                    coaching=text(
                        "These are the situations where organic fraud most often enters an "
                        "operation. Selecting several does not count against you — it tells "
                        "the certifier which mitigations to expect on the next page.",
                        "Estas son las situaciones por las que el fraude orgánico entra con más frecuencia a una "
                        "operación. Seleccionar varias no cuenta en tu contra — le indica al certificador qué "
                        "mitigaciones esperar en la página siguiente.",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Identified organic fraud risk areas: {answer}."),
                    options=(
                        Option(
                            "split_production",
                            text(
                                "We produce or sell both organic and nonorganic product",
                                "Producimos o vendemos producto orgánico y no orgánico",
                            ),
                        ),
                        Option(
                            "uncertified_suppliers",
                            text(
                                "We buy inputs, seed, or planting stock from uncertified suppliers",
                                "Compramos insumos, semilla o material de plantación a " "proveedores no certificados",
                            ),
                        ),
                        Option(
                            "supplier_churn",
                            text("Suppliers change frequently", "Los proveedores cambian con frecuencia"),
                        ),
                        Option(
                            "complex_chain",
                            text(
                                "Product passes through several hands before the buyer",
                                "El producto pasa por varias manos antes del comprador",
                            ),
                        ),
                        Option(
                            "custom_operators",
                            text(
                                "Custom harvesters, haulers, or hullers handle our product",
                                "Cosechadores, transportistas o descascaradores por contrato "
                                "manejan nuestro producto",
                            ),
                        ),
                        Option(
                            "seasonal_labor",
                            text(
                                "Seasonal or temporary crews, or high staff turnover",
                                "Cuadrillas temporales o de temporada, o alta rotación de " "personal",
                            ),
                        ),
                        Option(
                            "imports",
                            text(
                                "We import product or inputs, or source from high-risk regions",
                                "Importamos producto o insumos, o abastecemos de regiones de " "alto riesgo",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                        Option(
                            "none",
                            text(
                                "None of these — we grow and sell only our own certified organic crop",
                                "Ninguna — cultivamos y vendemos únicamente nuestro propio "
                                "cultivo orgánico certificado",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="fraud_risk_other",
                    kind="text",
                    label=text("Describe the other risk area", "Describe la otra área de riesgo"),
                    visible_when=(Condition("fraud_risk_areas", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional fraud risk area: {answer}"),
                ),
            ),
        ),
        ModulePage(
            key="b_mitigation",
            title=text("B. How the risk is managed", "B. Cómo se maneja el riesgo"),
            questions=(
                Question(
                    key="fraud_mitigation_practices",
                    kind="checkbox_group",
                    label=text(
                        "Which practices do you use to prevent organic fraud?",
                        "¿Qué prácticas usas para prevenir el fraude orgánico?",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Organic fraud prevention practices: {answer}."),
                    options=(
                        Option(
                            "verify_certificates",
                            text(
                                "Verify that supplier organic certificates are current and cover " "the product bought",
                                "Verificar que los certificados orgánicos de proveedores estén "
                                "vigentes y cubran el producto comprado",
                            ),
                        ),
                        Option(
                            "organic_integrity_database",
                            text(
                                "Check suppliers in the USDA Organic Integrity Database, "
                                "including surrendered, suspended, or revoked status",
                                "Consultar proveedores en la Base de Datos de Integridad "
                                "Orgánica del USDA, incluidos los estados de renuncia, "
                                "suspensión o revocación",
                            ),
                        ),
                        Option(
                            "review_paperwork",
                            text(
                                "Review labels and paperwork when product or inputs are received",
                                "Revisar etiquetas y documentación al recibir producto o insumos",
                            ),
                        ),
                        Option(
                            "known_suppliers",
                            text(
                                "Buy from known, long-standing suppliers",
                                "Comprar a proveedores conocidos y de larga trayectoria",
                            ),
                        ),
                        Option(
                            "employee_training",
                            text(
                                "Train staff on organic handling and separation",
                                "Capacitar al personal en manejo y separación orgánica",
                            ),
                        ),
                        Option(
                            "supplier_audits",
                            text("We audit or visit our suppliers", "Auditamos o visitamos a nuestros proveedores"),
                        ),
                        Option(
                            "buyer_audits",
                            text(
                                "Our buyers audit or visit our operation",
                                "Nuestros compradores auditan o visitan nuestra operación",
                            ),
                        ),
                        Option(
                            "price_flags",
                            text(
                                "Treat unusually low pricing as a warning sign",
                                "Tratar un precio inusualmente bajo como señal de alerta",
                            ),
                        ),
                        Option(
                            "product_testing",
                            text("Residue or product testing", "Pruebas de residuos o de producto"),
                        ),
                        Option(
                            "vulnerability_assessment",
                            text(
                                "Periodic vulnerability assessments of our own operation",
                                "Evaluaciones periódicas de vulnerabilidad de nuestra propia " "operación",
                            ),
                        ),
                        Option(
                            "report_suspected",
                            text(
                                "Report suspected fraud to our certifier or the NOP",
                                "Reportar sospechas de fraude a nuestro certificador o al NOP",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="product_testing_detail",
                    kind="text",
                    label=text(
                        "What is tested, and how often?",
                        "¿Qué se prueba y con qué frecuencia?",
                    ),
                    visible_when=(Condition("fraud_mitigation_practices", "includes", "product_testing"),),
                    compiles_to=CompileRule(template="Product testing scope and frequency: {answer}"),
                ),
                # WSDA AGR 2121 P 4a asks the screening or analysis performed beside what is sampled and
                # how often; P 4b how the operation responds when residues are detected.
                Question(
                    key="residue_screening_method",
                    kind="text",
                    label=text(
                        "What screening or analysis is performed (for example, the laboratory and the residue panel)?",
                        "¿Qué análisis o tamizaje se realiza (por ejemplo, el laboratorio y el panel de residuos)?",
                    ),
                    required=False,
                    visible_when=(Condition("fraud_mitigation_practices", "includes", "product_testing"),),
                    compiles_to=CompileRule(template="Residue screening or analysis performed: {answer}"),
                ),
                Question(
                    key="residue_detection_response",
                    kind="textarea",
                    label=text(
                        "What do you do when a pesticide residue is detected?",
                        "¿Qué haces cuando se detecta un residuo de plaguicida?",
                    ),
                    coaching=text(
                        "How you find the source of the contamination and decide whether the product keeps its "
                        "organic status, who is notified and involved (your certifier among them), and how the "
                        "response is documented.",
                        "Cómo encuentras el origen de la contaminación y decides si el producto mantiene su "
                        "condición orgánica, a quién se notifica y quién participa (tu certificador entre ellos), "
                        "y cómo se documenta la respuesta.",
                    ),
                    required=False,
                    nop_cite="§ 205.671",
                    visible_when=(Condition("fraud_mitigation_practices", "includes", "product_testing"),),
                    compiles_to=CompileRule(template="Response when a pesticide residue is detected: {answer}"),
                ),
                Question(
                    key="fraud_mitigation_other",
                    kind="text",
                    label=text("Describe the other practice", "Describe la otra práctica"),
                    visible_when=(Condition("fraud_mitigation_practices", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional fraud prevention practice: {answer}"),
                ),
                # 2026-11-14: OTCO's fraud prevention plan asks where suspected fraud is reported (1-2) and WSDA AGR
                # 2121 P 6 what would be reported. Both are asked of every operation, so neither waits on the
                # `report_suspected` tick above, which keeps the meaning it was answered with.
                Question(
                    key="fraud_reporting_channels",
                    kind="checkbox_group",
                    label=text(
                        "Where do you report suspected organic fraud?",
                        "¿A quién reportas una sospecha de fraude orgánico?",
                    ),
                    coaching=text(
                        "Check every route you would use. A California operation can also report to the state "
                        "organic program.",
                        "Marca cada vía que usarías. Una operación en California también puede reportar al programa "
                        "orgánico estatal.",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Suspected organic fraud is reported to: {answer}."),
                    options=(
                        Option("own_certifier", text("Our certifying agent", "Nuestra agencia certificadora")),
                        Option(
                            "suppliers_certifier",
                            text("The supplier's certifying agent", "La agencia certificadora del proveedor"),
                        ),
                        Option(
                            "usda_nop",
                            text("The USDA National Organic Program", "El Programa Nacional Orgánico del USDA"),
                        ),
                        Option(
                            "state_organic_program",
                            text(
                                "The California State Organic Program (CDFA), for a California operation",
                                "El Programa Orgánico Estatal de California (CDFA), para una operación en California",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="fraud_reporting_channels_other",
                    kind="text",
                    label=text("Where else do you report?", "¿A quién más reportas?"),
                    required=False,
                    visible_when=(Condition("fraud_reporting_channels", "includes", "other"),),
                    compiles_to=CompileRule(template="Other reporting route: {answer}."),
                ),
                Question(
                    key="fraud_reporting_triggers",
                    kind="checkbox_group",
                    label=text("What would you report?", "¿Qué reportarías?"),
                    coaching=text(
                        "The situations that would make you report, with the evidence you hold.",
                        "Las situaciones que te harían reportar, con la evidencia que tengas.",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Reported as suspected organic fraud: {answer}."),
                    options=(
                        Option(
                            "positive_sample_results",
                            text(
                                "Every positive residue result linked to an organic crop",
                                "Todo resultado positivo de residuos vinculado a un cultivo orgánico",
                            ),
                        ),
                        Option(
                            "suspected_fraud",
                            text(
                                "Any activity in the supply chain that may be fraudulent",
                                "Cualquier actividad en la cadena de suministro que pueda ser fraudulenta",
                            ),
                        ),
                        Option(
                            "quantity_exceeds_capacity",
                            text(
                                "A supplier delivering more organic product than it is known to produce",
                                "Un proveedor que entrega más producto orgánico del que se sabe que produce",
                            ),
                        ),
                        Option(
                            "below_market_price",
                            text(
                                "Organic product offered below market price with no reasonable explanation",
                                "Producto orgánico ofrecido por debajo del precio de mercado sin una explicación "
                                "razonable",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="fraud_reporting_triggers_other",
                    kind="text",
                    label=text("What else would you report?", "¿Qué más reportarías?"),
                    required=False,
                    visible_when=(Condition("fraud_reporting_triggers", "includes", "other"),),
                    compiles_to=CompileRule(template="Also reported: {answer}."),
                ),
                # CCOF G8.0 D2 asks how often a supplier's certificate is reviewed; nothing asked the cadence.
                Question(
                    key="supplier_certificate_review_frequency",
                    kind="radio",
                    label=text(
                        "How often do you review a supplier's organic certificate?",
                        "¿Con qué frecuencia revisas el certificado orgánico de un proveedor?",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    visible_when=(
                        Condition(
                            "fraud_mitigation_practices",
                            "includes_any",
                            ("verify_certificates", "organic_integrity_database"),
                        ),
                    ),
                    compiles_to=CompileRule(template="How often suppliers' organic status is reviewed: {answer}."),
                    options=(
                        Option(
                            "each_transaction",
                            text("With each shipment or purchase", "Con cada envío o compra"),
                        ),
                        Option("monthly", text("Monthly", "Mensualmente")),
                        Option("quarterly", text("Quarterly", "Trimestralmente")),
                        Option("annually", text("Annually", "Anualmente")),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="supplier_certificate_review_frequency_other",
                    kind="text",
                    label=text("Other frequency", "Otra frecuencia"),
                    required=False,
                    visible_when=(Condition("supplier_certificate_review_frequency", "eq", "other"),),
                    compiles_to=CompileRule(template="Other frequency of the supplier review: {answer}."),
                ),
                # OTCO's fraud prevention plan (2-2) and WSDA AGR 2121 P5 ask how a supplier is approved and
                # kept under watch. These are the controls the practices above do not name.
                Question(
                    key="supplier_approval_controls",
                    kind="checkbox_group",
                    label=text(
                        "How do you approve organic suppliers and keep track of them?",
                        "¿Cómo apruebas a los proveedores orgánicos y les das seguimiento?",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="How suppliers are approved and followed: {answer}."),
                    options=(
                        Option(
                            "supplier_list",
                            text(
                                "We keep a list of our organic suppliers",
                                "Mantenemos una lista de nuestros proveedores orgánicos",
                            ),
                        ),
                        Option(
                            "approval_program",
                            text(
                                "A new supplier is reviewed and approved before we buy from it",
                                "Un proveedor nuevo se revisa y aprueba antes de comprarle",
                            ),
                        ),
                        Option(
                            "annual_certificate_refresh",
                            text(
                                "Suppliers send us an updated organic certificate at least once a year, or when asked",
                                "Los proveedores nos envían un certificado orgánico actualizado al menos una vez al "
                                "año, o cuando lo pedimos",
                            ),
                        ),
                        Option(
                            "product_specifications",
                            text(
                                "Suppliers agree to meet our product specifications for every shipment",
                                "Los proveedores se comprometen a cumplir nuestras especificaciones en cada envío",
                            ),
                        ),
                        Option(
                            "food_safety_audit",
                            text(
                                "Suppliers pass a third-party food safety audit (such as GFSI) every year",
                                "Los proveedores aprueban cada año una auditoría de inocuidad de terceros (como GFSI)",
                            ),
                        ),
                        Option(
                            "capacity_check",
                            text(
                                "We confirm a supplier can meet our quality and quantity needs",
                                "Confirmamos que el proveedor puede cumplir con la calidad y la cantidad que "
                                "necesitamos",
                            ),
                        ),
                        Option(
                            "supplier_residue_results",
                            text(
                                "Suppliers send us residue test results on a schedule",
                                "Los proveedores nos envían resultados de análisis de residuos con una frecuencia "
                                "fija",
                            ),
                        ),
                        Option(
                            "residue_notice",
                            text(
                                "Suppliers tell us in writing if residue is found on product we receive",
                                "Los proveedores nos avisan por escrito si se encuentran residuos en el producto "
                                "que recibimos",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="supplier_approval_controls_other",
                    kind="text",
                    label=text(
                        "Other way you approve or follow suppliers", "Otra forma de aprobar o seguir proveedores"
                    ),
                    required=False,
                    visible_when=(Condition("supplier_approval_controls", "includes", "other"),),
                    compiles_to=CompileRule(template="Other supplier control: {answer}."),
                ),
                Question(
                    key="supplier_approval_procedure_upload",
                    kind="upload",
                    label=text(
                        "Attach your written supplier approval procedure, if you keep one",
                        "Adjunta tu procedimiento escrito de aprobación de proveedores, si tienes uno",
                    ),
                    required=False,
                ),
                Question(
                    key="fraud_review_process",
                    kind="textarea",
                    label=text(
                        "How do you review your risks and check that these measures are working?",
                        "¿Cómo revisas tus riesgos y compruebas que estas medidas funcionan?",
                    ),
                    coaching=text(
                        "Say who does the review, when it happens, and what would make you "
                        "change something — for example a new buyer, a new custom operator, or "
                        "a supplier whose certificate lapsed.",
                        "Indica quién hace la revisión, cuándo ocurre y qué te haría cambiar algo — por ejemplo un "
                        "comprador nuevo, un nuevo operador por contrato, o un proveedor cuyo certificado venció.",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(
                        template="Process for reviewing fraud vulnerabilities and updating "
                        "prevention measures: {answer}"
                    ),
                ),
                # 2026-11-14: OTCO's plan asks whether one already exists, No or Yes attached (1-4). A shown upload
                # with no file reads as missing, so the No needs a question of its own. The upload keeps its meaning
                # and hides only on that No (`ne False`, not `truthy`): a file filed before this question existed
                # stays on the page that names it in the packet until the operator answers.
                Question(
                    key="fraud_plan_kept_separately",
                    kind="boolean",
                    label=text(
                        "Do you keep a fraud prevention plan as its own document, apart from these answers?",
                        "¿Mantienes un plan de prevención del fraude como documento propio, aparte de estas respuestas?",
                    ),
                    coaching=text(
                        "Your answers in this section already form the plan. Say yes only if a separate written plan "
                        "exists, for instance one a buyer asked for, and attach it.",
                        "Tus respuestas en esta sección ya forman el plan. Responde que sí solo si existe un plan escrito "
                        "aparte, por ejemplo uno que pidió un comprador, y adjúntalo.",
                    ),
                    required=False,
                    compiles_to=CompileRule(
                        template="The operation keeps a separate written fraud prevention plan ({answer}).",
                        template_false="The operation keeps no separate fraud prevention plan; the answers in this "
                        "section are its plan.",
                    ),
                ),
                Question(
                    key="fraud_plan_upload",
                    kind="upload",
                    visible_when=(Condition("fraud_plan_kept_separately", "ne", False),),
                    label=text(
                        "Attach a written fraud prevention plan, if you keep one separately",
                        "Adjunta un plan escrito de prevención del fraude, si mantienes uno por separado",
                    ),
                    coaching=text(
                        "Optional — your answers above already form the plan. Attach a document "
                        "only if you maintain one, for instance because a buyer requires their "
                        "own template.",
                        "Opcional — tus respuestas anteriores ya constituyen el plan. Adjunta un documento solo si "
                        "mantienes uno, por ejemplo porque un comprador exige su propia plantilla.",
                    ),
                    required=False,
                ),
            ),
        ),
        ModulePage(
            key="c_osp_accuracy",
            title=text("C. Keeping this plan accurate", "C. Mantener este plan actualizado"),
            education=(
                text(
                    "An OSP describes what your operation actually does. When a practice "
                    "changes, the plan has to change with it — a plan that no longer matches "
                    "the operation is itself a compliance problem, and it is one inspectors "
                    "find quickly.",
                    "Un OSP describe lo que tu operación realmente hace. Cuando una práctica cambia, el plan debe "
                    "cambiar con ella — un plan que ya no coincide con la operación es en sí mismo un problema de "
                    "cumplimiento, y es uno que los inspectores detectan rápido.",
                ),
            ),
            questions=(
                Question(
                    key="osp_review_frequency",
                    kind="checkbox_group",
                    label=text(
                        "When do you review and update this plan?",
                        "¿Cuándo revisas y actualizas este plan?",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="OSP review and update schedule: {answer}."),
                    options=(
                        Option("annually", text("Annually at renewal", "Anualmente en la renovación")),
                        Option(
                            "on_change",
                            text(
                                "Whenever a practice, input, parcel, or supplier changes",
                                "Cada vez que cambia una práctica, insumo, parcela o proveedor",
                            ),
                        ),
                        Option(
                            "before_inspection",
                            text("Before each inspection", "Antes de cada inspección"),
                        ),
                        Option("quarterly", text("Quarterly", "Trimestralmente")),
                        Option("monthly", text("Monthly", "Mensualmente")),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="osp_review_frequency_other",
                    kind="text",
                    label=text("Describe the other schedule", "Describe el otro calendario"),
                    visible_when=(Condition("osp_review_frequency", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional OSP review timing: {answer}"),
                ),
                Question(
                    key="osp_accuracy_process",
                    kind="textarea",
                    label=text(
                        "Who keeps this plan accurate, and how?",
                        "¿Quién mantiene este plan actualizado, y cómo?",
                    ),
                    coaching=text(
                        "Name the person responsible and how a change on the ground reaches "
                        "the plan — for instance, the crew logs a new input in Trazo and the "
                        "owner reviews the inputs list before renewal.",
                        "Nombra a la persona responsable y cómo un cambio en el campo llega al plan — por ejemplo, "
                        "la cuadrilla registra un insumo nuevo en Trazo y el propietario revisa la lista de insumos "
                        "antes de la renovación.",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Process for keeping the OSP accurate: {answer}"),
                ),
                # 2026-11-14: OTCO's plan opens with the team that approves, implements, trains and monitors it, as
                # rows of name, job title and contact (1-1). One row per line, as `history_prior_agents` asks its list.
                Question(
                    key="ofpp_team",
                    kind="textarea",
                    label=text(
                        "Who is on your fraud prevention team? For each person: name, job title or role, and a phone "
                        "or email.",
                        "¿Quiénes forman tu equipo de prevención del fraude? Para cada persona: nombre, cargo o función, "
                        "y un teléfono o correo electrónico.",
                    ),
                    coaching=text(
                        "The people who approve the plan, put it into practice, train staff on it and check that it "
                        "works. On a small farm one person often does all four; say so.",
                        "Las personas que aprueban el plan, lo ponen en práctica, capacitan al personal y comprueban "
                        "que funciona. En una finca pequeña, a menudo una sola persona hace las cuatro cosas; indícalo.",
                    ),
                    placeholder=text(
                        "e.g. Laurel Brandt, member-manager, 541-555-0134: approves and monitors the plan. "
                        "Diego Ruiz, crew lead, diego@example.com: trains the crew.",
                        "p. ej. Laurel Brandt, gerente, 541-555-0134: aprueba y supervisa el plan. "
                        "Diego Ruiz, responsable de cuadrilla, diego@example.com: capacita a la cuadrilla.",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Fraud prevention team (name, role, contact): {answer}"),
                ),
                Question(
                    key="osp_implementation_monitoring",
                    kind="checkbox_group",
                    label=text(
                        "How do you verify that the practices described in this plan are " "actually being followed?",
                        "¿Cómo verificas que las prácticas descritas en este plan realmente se cumplen?",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Verification that OSP practices are implemented: {answer}."),
                    options=(
                        Option(
                            "record_review",
                            text(
                                "Review the operation's records against the plan",
                                "Revisar los registros de la operación contra el plan",
                            ),
                        ),
                        Option(
                            "internal_review",
                            text("Internal walk-through or self-audit", "Recorrido interno o autoauditoría"),
                        ),
                        Option("staff_training", text("Staff training", "Capacitación del personal")),
                        Option(
                            "staff_checkins",
                            text("Scheduled check-ins with the crew", "Reuniones programadas con la cuadrilla"),
                        ),
                        Option(
                            "dual_signoff",
                            text(
                                "A second person signs off on each transaction or completed task",
                                "Una segunda persona aprueba cada transacción o tarea terminada",
                            ),
                        ),
                        Option(
                            "procedures_in_activity_records",
                            text(
                                "Procedures are written into activity records, so staff confirm each step",
                                "Los procedimientos están escritos en los registros de actividad, y el personal confirma cada paso",
                            ),
                        ),
                        # 2026-11-14: WSDA AGR 2121 P 2's last two ways.
                        Option(
                            "employee_evaluations",
                            text(
                                "Staff observations and evaluations include organic practices",
                                "Las observaciones y evaluaciones del personal incluyen las prácticas orgánicas",
                            ),
                        ),
                        Option(
                            "corrective_actions_documented",
                            text(
                                "Deviations and corrective actions are written down",
                                "Las desviaciones y las acciones correctivas se dejan por escrito",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                # WSDA P 2 asks how often beside each way it names; OTCO C12 12.3-1 how often the records are checked.
                # Training has its own question below.
                Question(
                    key="record_review_frequency",
                    kind="text",
                    label=text("How often are the records reviewed?", "¿Con qué frecuencia se revisan los registros?"),
                    placeholder=text(
                        "e.g. weekly during harvest, monthly the rest of the year",
                        "p. ej. cada semana durante la cosecha, cada mes el resto del año",
                    ),
                    required=False,
                    visible_when=(Condition("osp_implementation_monitoring", "includes", "record_review"),),
                    compiles_to=CompileRule(template="Records reviewed against the plan: {answer}."),
                ),
                Question(
                    key="employee_evaluation_frequency",
                    kind="text",
                    label=text(
                        "How often are staff observed or evaluated?",
                        "¿Con qué frecuencia se observa o evalúa al personal?",
                    ),
                    required=False,
                    visible_when=(Condition("osp_implementation_monitoring", "includes", "employee_evaluations"),),
                    compiles_to=CompileRule(template="Staff observations and evaluations, how often: {answer}."),
                ),
                Question(
                    key="osp_implementation_monitoring_other",
                    kind="text",
                    label=text("Describe the other method", "Describe el otro método"),
                    visible_when=(Condition("osp_implementation_monitoring", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional implementation check: {answer}"),
                ),
                # OTCO's plan asks when staff are trained on it (4-1), all three of its boxes a WHEN; WSDA P 2 the
                # training programme's frequency. Asked of everyone: an operation with no staff says so.
                Question(
                    key="ofpp_training_cadence",
                    kind="checkbox_group",
                    label=text(
                        "How are staff trained on this plan and its changes?",
                        "¿Cómo se capacita al personal sobre este plan y sus cambios?",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Staff training on the fraud prevention plan: {answer}."),
                    options=(
                        Option(
                            "onboarding",
                            text(
                                "New staff are trained on it when they start",
                                "El personal nuevo se capacita al empezar",
                            ),
                        ),
                        Option(
                            "annual_refresher",
                            text("All staff take a refresher every year", "Todo el personal recibe un repaso cada año"),
                        ),
                        Option(
                            "within_month_of_change",
                            text(
                                "Staff are trained on a change to the plan within a month of it",
                                "El personal se capacita sobre un cambio del plan dentro del mes siguiente",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                        Option(
                            "no_staff",
                            text(
                                "We have no staff; the owners do all the work",
                                "No tenemos personal; las personas propietarias hacen todo el trabajo",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="ofpp_training_cadence_other",
                    kind="text",
                    label=text("Describe the other training", "Describe la otra capacitación"),
                    required=False,
                    visible_when=(Condition("ofpp_training_cadence", "includes", "other"),),
                    compiles_to=CompileRule(template="Other training on the plan: {answer}."),
                ),
                # WSDA P 3 and 3a: internal audits as a yes or no, then their scope and frequency.
                Question(
                    key="internal_audits_conducted",
                    kind="boolean",
                    label=text("Do you conduct internal audits?", "¿Realizas auditorías internas?"),
                    coaching=text(
                        "A planned check of your own operation against this plan, by you or someone you appoint. "
                        "Your certifier's inspection does not count.",
                        "Una revisión planificada de tu propia operación frente a este plan, hecha por ti o por alguien "
                        "que designes. La inspección de tu certificador no cuenta.",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(
                        template="The operation conducts internal audits ({answer}).",
                        template_false="The operation does not conduct internal audits.",
                    ),
                ),
                Question(
                    key="internal_audit_scope",
                    kind="textarea",
                    label=text(
                        "What do the internal audits cover, and how often are they done?",
                        "¿Qué cubren las auditorías internas y con qué frecuencia se hacen?",
                    ),
                    required=False,
                    visible_when=(Condition("internal_audits_conducted", "truthy"),),
                    compiles_to=CompileRule(template="Internal audit scope and frequency: {answer}"),
                ),
                # WSDA P 1: written SOPs for organic production and handling, Yes attached or No.
                Question(
                    key="written_sops_kept",
                    kind="boolean",
                    label=text(
                        "Do you keep written standard operating procedures (SOPs) for organic production or handling?",
                        "¿Mantienes procedimientos operativos estándar (SOP) escritos para la producción o el manejo "
                        "orgánico?",
                    ),
                    coaching=text(
                        "For example how a spray decision is made, how equipment is cleaned out, or how the harvest "
                        "crew keeps organic bins apart. This plan already describes your practices; say yes only if "
                        "written procedures exist as well, and attach them.",
                        "Por ejemplo, cómo se decide una aplicación, cómo se limpia el equipo o cómo la cuadrilla de "
                        "cosecha mantiene separados los contenedores orgánicos. Este plan ya describe tus prácticas; "
                        "responde que sí solo si además existen procedimientos escritos, y adjúntalos.",
                    ),
                    required=False,
                    compiles_to=CompileRule(
                        template="The operation keeps written standard operating procedures for organic production "
                        "or handling ({answer}).",
                        template_false="The operation keeps no written standard operating procedures beyond this "
                        "plan.",
                    ),
                ),
                Question(
                    key="sop_upload",
                    kind="upload",
                    label=text("Attach your written SOPs", "Adjunta tus SOP escritos"),
                    required=False,
                    visible_when=(Condition("written_sops_kept", "truthy"),),
                ),
                # WSDA P 7: the section's optional space.
                Question(
                    key="fraud_additional_notes",
                    kind="textarea",
                    label=text(
                        "Anything else about how you monitor this plan or prevent fraud?",
                        "¿Algo más sobre cómo supervisas este plan o previenes el fraude?",
                    ),
                    required=False,
                    compiles_to=CompileRule(template="Additional information: {answer}"),
                ),
            ),
        ),
        # 2026-11-14: OTCO's plan asks for the supply chain as a map or flow chart, or described when simple (2-1),
        # and a vulnerability assessment as a table: each critical control point with its prevention strategies and
        # its monitoring, how often included (3-1). The table is asked by construction: the operator picks the
        # control points, and each picked one asks its two columns.
        ModulePage(
            key="d_supply_chain",
            title=text(
                "D. Supply chain and critical control points",
                "D. Cadena de suministro y puntos críticos de control",
            ),
            education=(
                text(
                    "A critical control point is a step where fraud could enter your supply chain and where you can "
                    "stop it. For each one, say what you do there and how you check that it works. For example, "
                    "for transport: we confirm the shipper's clean truck procedure and file it with the receiving "
                    "records, and the product is listed as organic on every record; the clean truck affidavit is "
                    "checked for each load before the organic product is unloaded.",
                    "Un punto crítico de control es un paso en el que el fraude podría entrar a tu cadena de "
                    "suministro y en el que puedes detenerlo. Para cada uno, indica qué haces ahí y cómo compruebas "
                    "que funciona. Por ejemplo, para el transporte: confirmamos el procedimiento de camión limpio del "
                    "transportista y lo archivamos con los registros de recepción, y el producto figura como orgánico "
                    "en cada registro; la declaración de camión limpio se revisa en cada carga antes de descargar el "
                    "producto orgánico.",
                ),
            ),
            questions=(
                Question(
                    key="supply_chain_shown_as",
                    kind="radio",
                    label=text("How do you show your supply chain?", "¿Cómo muestras tu cadena de suministro?"),
                    coaching=text(
                        "Start with the certified operations that supply you and follow the product to your buyers. "
                        "Show where each supplier is, where the product changes ownership, any importing or "
                        "exporting, each step done away from the farm such as transport and storage, and mark the "
                        "critical control points you name below.",
                        "Empieza por las operaciones certificadas que te abastecen y sigue el producto hasta tus "
                        "compradores. Muestra dónde está cada proveedor, dónde cambia la propiedad del producto, cualquier "
                        "importación o exportación, cada paso hecho fuera de la finca, como el transporte y el "
                        "almacenamiento, y marca los puntos críticos de control que nombras abajo.",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    options=(
                        Option(
                            "map",
                            text("We attach a map or flow chart", "Adjuntamos un mapa o diagrama de flujo"),
                            requires_upload="supply_chain_map_upload",
                        ),
                        Option(
                            "described",
                            text(
                                "Our supply chain is simple, so we describe it here",
                                "Nuestra cadena de suministro es sencilla, así que la describimos aquí",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="supply_chain_map_upload",
                    kind="upload",
                    label=text("Attach the map or flow chart", "Adjunta el mapa o diagrama de flujo"),
                    required=False,
                    visible_when=(Condition("supply_chain_shown_as", "eq", "map"),),
                ),
                Question(
                    key="supply_chain_description",
                    kind="textarea",
                    label=text("Describe your supply chain", "Describe tu cadena de suministro"),
                    placeholder=text(
                        "e.g. Certified organic trees from Willow Drive Nursery, Ephrata WA. Our crew picks into our "
                        "own bins. Columbia Packers (certified, Wenatchee WA) hauls the bins in its own trucks and "
                        "owns the fruit from its dock on. No importing or exporting.",
                        "p. ej. Árboles orgánicos certificados de Willow Drive Nursery, Ephrata WA. Nuestra cuadrilla "
                        "cosecha en nuestros propios contenedores. Columbia Packers (con certificación, Wenatchee WA) "
                        "transporta los contenedores en sus camiones, y la fruta pasa a su propiedad en su andén. Sin "
                        "importación ni exportación.",
                    ),
                    required=False,
                    visible_when=(Condition("supply_chain_shown_as", "eq", "described"),),
                    compiles_to=CompileRule(template="Supply chain: {answer}"),
                ),
                Question(
                    key="critical_control_points",
                    kind="checkbox_group",
                    label=text(
                        "Which steps in your supply chain are critical control points?",
                        "¿Qué pasos de tu cadena de suministro son puntos críticos de control?",
                    ),
                    coaching=text(
                        "Weigh whether each supplier is certified or exempt, domestic or foreign; products that are "
                        "high value, hard to find or in high demand; pest or disease pressure; organic and nonorganic "
                        "product handled together; and how well you know the supplier.",
                        "Considera si cada proveedor está certificado o exento, si es nacional o extranjero; los "
                        "productos de alto valor, difíciles de conseguir o de alta demanda; la presión de plagas o "
                        "enfermedades; el manejo conjunto de producto orgánico y no orgánico; y qué tan bien conoces "
                        "al proveedor.",
                    ),
                    required=False,
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Critical control points: {answer}."),
                    options=tuple(Option(key, label) for key, label, _name in CONTROL_POINTS),
                ),
                Question(
                    key="ccp_other_name",
                    kind="text",
                    label=text("Name the other control point", "Nombra el otro punto de control"),
                    required=False,
                    visible_when=(Condition("critical_control_points", "includes", "other"),),
                    compiles_to=CompileRule(template="Other critical control point: {answer}."),
                ),
                *(question for key, _label, name in CONTROL_POINTS for question in _control_point_columns(key, name)),
            ),
        ),
    ),
)
