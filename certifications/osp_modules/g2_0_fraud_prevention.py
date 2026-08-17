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
            "El fraude orgánico ocurre cuando un producto no orgánico se vende, etiqueta o "
            "representa como orgánico. Puede suceder en cualquier punto de una cadena de "
            "suministro, incluso antes de su operación. Esta sección identifica dónde está el "
            "riesgo en su negocio y qué hace al respecto.",
        ),
        text(
            "Your measures must be appropriate to your operation's activities, scope, and "
            "complexity — not to someone else's. A grower who sells one crop to one handler "
            "has a short, honest answer here, and that is the correct answer. Claiming "
            "controls you do not actually run is the failure mode to avoid.",
            "Sus medidas deben ser apropiadas a las actividades, el alcance y la complejidad "
            "de su operación — no a las de otra. Un productor que vende un cultivo a un solo "
            "manejador tiene una respuesta breve y honesta aquí, y esa es la respuesta "
            "correcta. Declarar controles que en realidad no ejecuta es el error que se debe "
            "evitar.",
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
                        "¿Cuáles de estas describen su operación?",
                    ),
                    coaching=text(
                        "These are the situations where organic fraud most often enters an "
                        "operation. Selecting several does not count against you — it tells "
                        "the certifier which mitigations to expect on the next page.",
                        "Estas son las situaciones por las que el fraude orgánico entra con "
                        "más frecuencia a una operación. Seleccionar varias no cuenta en su "
                        "contra — le indica al certificador qué mitigaciones esperar en la "
                        "página siguiente.",
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
                        Option("other", text("Other (describe below)", "Otro (describa abajo)")),
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
                    label=text("Describe the other risk area", "Describa la otra área de riesgo"),
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
                        "¿Qué prácticas usa para prevenir el fraude orgánico?",
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
                        Option("other", text("Other (describe below)", "Otra (describa abajo)")),
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
                Question(
                    key="fraud_mitigation_other",
                    kind="text",
                    label=text("Describe the other practice", "Describa la otra práctica"),
                    visible_when=(Condition("fraud_mitigation_practices", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional fraud prevention practice: {answer}"),
                ),
                Question(
                    key="fraud_review_process",
                    kind="textarea",
                    label=text(
                        "How do you review your risks and check that these measures are working?",
                        "¿Cómo revisa sus riesgos y comprueba que estas medidas funcionan?",
                    ),
                    coaching=text(
                        "Say who does the review, when it happens, and what would make you "
                        "change something — for example a new buyer, a new custom operator, or "
                        "a supplier whose certificate lapsed.",
                        "Indique quién hace la revisión, cuándo ocurre y qué le haría cambiar "
                        "algo — por ejemplo un comprador nuevo, un nuevo operador por "
                        "contrato, o un proveedor cuyo certificado venció.",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(
                        template="Process for reviewing fraud vulnerabilities and updating "
                        "prevention measures: {answer}"
                    ),
                ),
                Question(
                    key="fraud_plan_upload",
                    kind="upload",
                    label=text(
                        "Attach a written fraud prevention plan, if you keep one separately",
                        "Adjunte un plan escrito de prevención del fraude, si mantiene uno por " "separado",
                    ),
                    coaching=text(
                        "Optional — your answers above already form the plan. Attach a document "
                        "only if you maintain one, for instance because a buyer requires their "
                        "own template.",
                        "Opcional — sus respuestas anteriores ya constituyen el plan. Adjunte "
                        "un documento solo si mantiene uno, por ejemplo porque un comprador "
                        "exige su propia plantilla.",
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
                    "Un OSP describe lo que su operación realmente hace. Cuando una práctica "
                    "cambia, el plan debe cambiar con ella — un plan que ya no coincide con la "
                    "operación es en sí mismo un problema de cumplimiento, y es uno que los "
                    "inspectores detectan rápido.",
                ),
            ),
            questions=(
                Question(
                    key="osp_review_frequency",
                    kind="checkbox_group",
                    label=text(
                        "When do you review and update this plan?",
                        "¿Cuándo revisa y actualiza este plan?",
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
                        Option("other", text("Other (describe below)", "Otro (describa abajo)")),
                    ),
                ),
                Question(
                    key="osp_review_frequency_other",
                    kind="text",
                    label=text("Describe the other schedule", "Describa el otro calendario"),
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
                        "Nombre a la persona responsable y cómo un cambio en el campo llega al "
                        "plan — por ejemplo, la cuadrilla registra un insumo nuevo en Trazo y "
                        "el propietario revisa la lista de insumos antes de la renovación.",
                    ),
                    nop_cite="§ 205.201(a)(3)",
                    compiles_to=CompileRule(template="Process for keeping the OSP accurate: {answer}"),
                ),
                Question(
                    key="osp_implementation_monitoring",
                    kind="checkbox_group",
                    label=text(
                        "How do you verify that the practices described in this plan are " "actually being followed?",
                        "¿Cómo verifica que las prácticas descritas en este plan realmente se " "cumplen?",
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
                        Option("other", text("Other (describe below)", "Otro (describa abajo)")),
                    ),
                ),
                Question(
                    key="osp_implementation_monitoring_other",
                    kind="text",
                    label=text("Describe the other method", "Describa el otro método"),
                    visible_when=(Condition("osp_implementation_monitoring", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional implementation check: {answer}"),
                ),
            ),
        ),
    ),
)
