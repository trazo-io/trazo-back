"""
G8.0 — Record Keeping.

Sources: 7 CFR 205.103 (recordkeeping by certified operations), 205.101, 205.201(a)(4),
205.307 (nonretail container labeling — the lot-number linkage requirement), 205.272.
Mirrors Common OSP Section 11, whose three parts are:

A. Records maintained — the body of this page IS the shipped Common OSP § 11 registry panel
   (`embed="s11_record_types"`): per-record-type evidence with explicit operator confirmation,
   never a bare Y/N. Structurally stronger than a single attestation because each checked box
   carries who confirmed it, when, and what evidence Trazo holds.

   The registry answers WHICH records the operation keeps. WSDA AGR 2121-O asks three more
   things about the same records that no checkbox list can carry — where they are (q5), who can
   reach them (q6), and whether they are electronic, paper or both (q7) — so those are three
   questions on this page rather than a fourth artifact. Q5's "No" is WSDA's routing gate to
   their AGR 2519, which Trazo does not generate: the follow-up names the locations so the
   reviewer can decide, instead of finding a blank.

B. Audit trail — § 205.103(b)(2) requires records that fully disclose all activities and
   § 205.307 requires the lot number or other unique identification on nonretail containers to
   link to audit trail documentation. Trazo GENERATES a sample audit-trail exhibit from real
   records (lot tags + traceability + mass-balance dossier sections); the operator reviews and
   attaches it rather than hand-drawing one.

C. Import & export — the Common OSP puts this inside Section 11 rather than giving it its own
   section, and so do we: a whole extra module that almost every domestic grower would mark
   "not applicable" is worse than one gated question. Everything below the trigger uses
   `includes_any`, so an operation selling only within the US answers once and the page ends.

   It is not the edge case it looks like for this ICP. California tree nuts are largely
   exported, and several trade partners require a certificate issued by the CERTIFIER before
   the shipment departs — a load that sails without one cannot be fixed retroactively.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text

G8_0_RECORD_KEEPING = Module(
    key="g8_0_record_keeping",
    code="G8.0",
    title=text("Record Keeping", "Mantenimiento de registros"),
    nop_cites=("§ 205.103", "§ 205.101", "§ 205.201", "§ 205.307"),
    education=(
        text(
            "Certified operations must maintain records that fully disclose all activities "
            "and transactions, in enough detail to be readily understood and audited; keep "
            "them at least 5 years; and make them available for inspection (§ 205.103). "
            "Records must trace every organic product from production through sale and back.",
            "Las operaciones certificadas deben mantener registros que revelen por completo "
            "todas las actividades y transacciones, con suficiente detalle para ser "
            "comprendidos y auditados; conservarlos al menos 5 años; y tenerlos disponibles "
            "para inspección (§ 205.103). Los registros deben rastrear cada producto "
            "orgánico desde la producción hasta la venta y de vuelta.",
        ),
    ),
    allows_not_applicable=False,
    default_section_key="recordkeeping_description",
    pages=(
        ModulePage(
            key="a_records_maintained",
            title=text("A. Records maintained", "A. Registros mantenidos"),
            education=(
                text(
                    "Confirm each record type your operation maintains. Where Trazo already "
                    "holds records of a type, the row shows the evidence — confirming it is "
                    "still your statement, not Trazo's.",
                    "Confirme cada tipo de registro que mantiene su operación. Cuando Trazo "
                    "ya contiene registros de un tipo, la fila muestra la evidencia — "
                    "confirmarla sigue siendo su declaración, no la de Trazo.",
                ),
            ),
            questions=(
                Question(
                    key="s11_records",
                    kind="info",
                    required=False,
                    label=text(
                        "Record types (USDA Common OSP, section 11)",
                        "Tipos de registro (OSP Común de USDA, sección 11)",
                    ),
                    embed="s11_record_types",
                    nop_cite="§ 205.103",
                ),
                Question(
                    key="records_retention_attestation",
                    attests_embed="s11_record_types",
                    kind="boolean",
                    label=text(
                        "Do you maintain the records confirmed above, keep them for at "
                        "least 5 years, and make them available at inspection?",
                        "¿Mantiene los registros confirmados arriba, los conserva al menos "
                        "5 años y los tiene disponibles en la inspección?",
                    ),
                    nop_cite="§ 205.103(b)",
                    compiles_to=CompileRule(
                        template=(
                            "Operator attests that the record types it confirmed are "
                            "maintained, retained at least five years, and available at "
                            "inspection: {answer}."
                        )
                    ),
                ),
                # WSDA AGR 2121-O questions 5, 6 and 7. The § 11 registry above records WHICH
                # records the operation keeps and never WHERE they are, WHO can reach them, or
                # in WHAT FORM — three separate lines on WSDA's own recordkeeping form that had
                # no field anywhere in the product. Q5's "No" is the one that costs a grower a
                # bounce: it declares an attached AGR 2519 (Additional Facilities and
                # Third-Parties), which Trazo does not produce, so the answer has to name the
                # locations here or the reviewer is left to ask.
                Question(
                    key="records_location",
                    kind="radio",
                    label=text(
                        "Are all of your organic records kept at your primary business " "location?",
                        "¿Todos sus registros orgánicos se conservan en la ubicación " "principal de su negocio?",
                    ),
                    # (c) is the availability-for-inspection paragraph — where the records
                    # physically are is a question about whether an inspector can be shown
                    # them, not about what they contain.
                    nop_cite="§ 205.103(c)",
                    options=(
                        Option(
                            value="primary_only",
                            label=text(
                                "Yes — all records are at the primary location",
                                "Sí — todos los registros están en la ubicación principal",
                            ),
                        ),
                        Option(
                            value="multiple_locations",
                            label=text(
                                "No — some records are kept somewhere else",
                                "No — algunos registros se conservan en otro lugar",
                            ),
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Location of organic records: {answer}.",
                    ),
                ),
                Question(
                    key="additional_records_locations",
                    kind="textarea",
                    visible_when=(Condition("records_location", "eq", "multiple_locations"),),
                    label=text(
                        "Which records are kept elsewhere, and where are they?",
                        "¿Qué registros se conservan en otro lugar y dónde están?",
                    ),
                    coaching=text(
                        "Name the record types and the location for each. Your certifier may "
                        "also ask for their own additional-facilities form; this answer is "
                        "what tells them whether it is needed.",
                        "Indique los tipos de registro y la ubicación de cada uno. Su "
                        "agencia certificadora puede además pedir su propio formulario de "
                        "instalaciones adicionales; esta respuesta es la que les indica si "
                        "hace falta.",
                    ),
                    nop_cite="§ 205.103(c)",
                    max_length=1000,
                    compiles_to=CompileRule(
                        template="Records kept away from the primary location: {answer}.",
                    ),
                ),
                Question(
                    key="primary_contact_records_access",
                    kind="radio",
                    label=text(
                        "Can your primary contact readily access every record relating to " "certification?",
                        "¿Su contacto principal puede acceder fácilmente a todos los "
                        "registros relacionados con la certificación?",
                    ),
                    nop_cite="§ 205.103(c)",
                    options=(
                        Option(
                            value="yes",
                            label=text(
                                "Yes — the primary contact can reach all of them",
                                "Sí — el contacto principal puede acceder a todos",
                            ),
                        ),
                        Option(
                            value="no",
                            label=text(
                                "No — someone else holds or maintains some records",
                                "No — otra persona conserva o mantiene algunos registros",
                            ),
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Primary contact can access all certification records: {answer}.",
                    ),
                ),
                Question(
                    key="records_access_delegate",
                    kind="textarea",
                    visible_when=(Condition("primary_contact_records_access", "eq", "no"),),
                    label=text(
                        "Who else maintains or holds those records, and which record types " "are they?",
                        "¿Quién más mantiene o conserva esos registros y de qué tipos de " "registro se trata?",
                    ),
                    coaching=text(
                        "An inspector arriving on the day needs one name to ask for. A "
                        "bookkeeper, a packing house, or a family member all count.",
                        "Un inspector que llega ese día necesita un nombre a quien "
                        "preguntar. Un contador, una empacadora o un familiar cuentan.",
                    ),
                    nop_cite="§ 205.103(c)",
                    max_length=1000,
                    compiles_to=CompileRule(
                        template="Records held by someone other than the primary contact: {answer}.",
                    ),
                ),
                Question(
                    key="records_maintained_as",
                    kind="checkbox_group",
                    label=text(
                        "How are your records kept?",
                        "¿Cómo se conservan sus registros?",
                    ),
                    coaching=text(
                        "Tick both if paper source documents — delivery tickets, scale "
                        "tickets, handwritten spray logs — are filed as well as entered here.",
                        "Marque ambas si además conserva documentos en papel — boletas de "
                        "entrega, tiquetes de báscula, registros de aplicación escritos a "
                        "mano — aparte de lo que registra aquí.",
                    ),
                    # (b)(1) — records "adapted to the particular business that the certified
                    # operation is conducting". Electronic vs paper is exactly that question.
                    nop_cite="§ 205.103(b)(1)",
                    options=(
                        Option(
                            value="electronic",
                            label=text("Electronic", "Electrónicos"),
                        ),
                        Option(
                            value="hardcopy",
                            label=text("Hardcopy / paper", "Copia impresa / papel"),
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Records are maintained as: {answer}.",
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_audit_trail",
            title=text("B. Audit trail", "B. Rastro de auditoría"),
            education=(
                text(
                    "An audit trail links harvest, storage, handling, transport, and sale "
                    "records so any organic product traces back to the parcel it came from. "
                    "Nonretail containers must carry the lot number, shipping ID, or other "
                    "unique identification that appears in those records (§ 205.307).",
                    "Un rastro de auditoría vincula los registros de cosecha, "
                    "almacenamiento, manejo, transporte y venta para que cualquier producto "
                    "orgánico se rastree hasta la parcela de origen. Los contenedores no "
                    "minoristas deben llevar el número de lote, ID de envío u otra "
                    "identificación única que aparezca en esos registros (§ 205.307).",
                ),
            ),
            questions=(
                Question(
                    key="lot_numbering",
                    kind="radio",
                    label=text(
                        "Does your operation assign lot numbers (or another unique ID) to "
                        "track crops once they leave the operation?",
                        "¿Su operación asigna números de lote (u otra identificación única) "
                        "para rastrear los cultivos una vez que salen de la operación?",
                    ),
                    nop_cite="§ 205.307",
                    compiles_to=CompileRule(template="Lot identification in use: {answer}."),
                    options=(
                        Option(
                            "trazo_lots",
                            text(
                                "Yes — Trazo lot IDs (printed on lot tags and carried on "
                                "harvest, storage, and sales records)",
                                "Sí — IDs de lote de Trazo (impresos en etiquetas de lote y "
                                "presentes en registros de cosecha, almacenamiento y venta)",
                            ),
                        ),
                        Option(
                            "own_system",
                            text(
                                "Yes — our own numbering system (described below)",
                                "Sí — nuestro propio sistema de numeración (descrito abajo)",
                            ),
                        ),
                        Option(
                            "none",
                            text(
                                "No lot numbering is used",
                                "No se usa numeración de lotes",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="lot_numbering_description",
                    kind="textarea",
                    label=text(
                        "Describe your lot numbering system",
                        "Describa su sistema de numeración de lotes",
                    ),
                    coaching=text(
                        "What the number encodes (year, parcel, sequence), where it is "
                        "printed, and which records carry it.",
                        "Qué codifica el número (año, parcela, secuencia), dónde se imprime "
                        "y qué registros lo llevan.",
                    ),
                    visible_when=(Condition("lot_numbering", "eq", "own_system"),),
                    compiles_to=CompileRule(template="Lot numbering system: {answer}"),
                ),
                Question(
                    key="audit_trail_exhibit",
                    kind="upload",
                    required=False,
                    label=text(
                        "Sample audit trail exhibit",
                        "Ejemplo de rastro de auditoría",
                    ),
                    coaching=text(
                        "Your renewal packet already carries a generated exhibit — document 05, "
                        "Audit trail exhibit: the record types you confirmed in §A with their "
                        "linking elements, and one finished lot traced from harvest through "
                        "storage to sale. Attach your own sample here only if you want to add "
                        "to it.",
                        "Su paquete de renovación ya incluye un ejemplo generado — documento 05, "
                        "Rastro de auditoría: los tipos de registro que confirmó en §A con sus "
                        "elementos de enlace, y un lote terminado rastreado desde la cosecha, "
                        "por el almacenamiento, hasta la venta. Adjunte aquí su propio ejemplo "
                        "solo si desea complementarlo.",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                ),
            ),
        ),
        ModulePage(
            key="c_import_export",
            title=text("C. Import & export", "C. Importación y exportación"),
            education=(
                text(
                    "Most operations selling only within the United States answer the first "
                    "question and are done with this page. It matters for tree nuts, dried "
                    "fruit, and other crops that commonly ship abroad: several trade partners "
                    "require an export certificate issued by your certifier BEFORE the "
                    "shipment leaves, and a shipment that departs without one cannot be "
                    "corrected afterwards.",
                    "La mayoría de las operaciones que venden solo dentro de Estados Unidos "
                    "responden la primera pregunta y terminan con esta página. Importa para "
                    "frutos secos, fruta deshidratada y otros cultivos que suelen enviarse al "
                    "exterior: varios socios comerciales exigen un certificado de exportación "
                    "emitido por su certificador ANTES de que salga el envío, y un envío que "
                    "parte sin él no puede corregirse después.",
                ),
            ),
            questions=(
                Question(
                    key="import_export_activity",
                    kind="checkbox_group",
                    label=text(
                        "Does your operation import or export organic products, directly or indirectly, "
                        "now or in plans?",
                        "¿Su operación importa o exporta productos orgánicos, directa o indirectamente, "
                        "ahora o en sus planes?",
                    ),
                    coaching=text(
                        "Indirect export counts: product a buyer, broker or trader ships abroad, or that "
                        "leaves the country as an ingredient. Certifiers ask about it because the "
                        "destination country's rules can reach your crop.",
                        "La exportación indirecta cuenta: el producto que un comprador, corredor o "
                        "comerciante envía al exterior, o que sale del país como ingrediente. Los "
                        "certificadores preguntan por ella porque las reglas del país de destino pueden "
                        "alcanzar su cultivo.",
                    ),
                    nop_cite="§ 205.103",
                    compiles_to=CompileRule(template="Import and export activity: {answer}."),
                    options=(
                        Option(
                            "export",
                            text(
                                "We export, or plan to export, organic product to other countries",
                                "Exportamos, o planeamos exportar, producto orgánico a otros países",
                            ),
                        ),
                        Option(
                            "indirect_export",
                            text(
                                "Our product is exported, or will be, by a buyer, broker or trader, or as an "
                                "ingredient",
                                "Un comprador, corredor o comerciante exporta, o exportará, nuestro producto, "
                                "o sale del país como ingrediente",
                            ),
                        ),
                        Option(
                            "import",
                            text(
                                "We import, or plan to import, organic product or ingredients into the "
                                "United States",
                                "Importamos, o planeamos importar, producto o ingredientes orgánicos a "
                                "Estados Unidos",
                            ),
                        ),
                        Option(
                            "none_no_known_export",
                            text(
                                "Neither: all product is sold within the United States, and no buyer we "
                                "know of exports it or plans to",
                                "Ninguna: todo el producto se vende dentro de Estados Unidos, y ningún "
                                "comprador que conozcamos lo exporta ni planea hacerlo",
                            ),
                            exclusive=True,
                        ),
                        # Replaced 2026-09-30 (OSP alignment audit, T17). It said nothing about
                        # indirect export, which CCOF's contract D2 asks about, so a stored answer of
                        # only this option is no longer an answer (see conditions.effective_value).
                        # Kept so plans answered with it still print what the operator chose.
                        Option(
                            "none",
                            text(
                                "Neither — all product is sold within the United States",
                                "Ninguna — todo el producto se vende dentro de Estados Unidos",
                            ),
                            exclusive=True,
                            retired=True,
                        ),
                    ),
                ),
                Question(
                    key="export_destinations",
                    kind="text",
                    label=text(
                        "Which countries do you export to or plan to export to, directly or indirectly?",
                        "¿A qué países exporta o planea exportar, directa o indirectamente?",
                    ),
                    coaching=text(
                        "For indirect export, name the countries your buyer, broker or trader ships to, as "
                        "far as you know them.",
                        "Para la exportación indirecta, indique los países a los que envía su comprador, "
                        "corredor o comerciante, en la medida en que los conozca.",
                    ),
                    visible_when=(Condition("import_export_activity", "includes_any", ["export", "indirect_export"]),),
                    compiles_to=CompileRule(template="Export destination countries: {answer}."),
                ),
                Question(
                    key="export_certificate_types",
                    kind="checkbox_group",
                    label=text(
                        "Which export certificates do your destination countries require?",
                        "¿Qué certificados de exportación exigen sus países de destino?",
                    ),
                    coaching=text(
                        "Each of these is issued by your certifier, not by you, and must be "
                        "requested before the shipment departs. Check the USDA NOP "
                        "International Trade Partners page if you are not sure which applies.",
                        "Cada uno de estos lo emite su certificador, no usted, y debe "
                        "solicitarse antes de que salga el envío. Consulte la página de Socios "
                        "Comerciales Internacionales del NOP del USDA si no está seguro de "
                        "cuál aplica.",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes", "export"),),
                    compiles_to=CompileRule(template="Export certificates required by destination: {answer}."),
                    options=(
                        Option(
                            "coi_eu",
                            text(
                                "Certificate of Inspection (EU, UK, Switzerland)",
                                "Certificado de Inspección (UE, Reino Unido, Suiza)",
                            ),
                        ),
                        Option("tm11", text("TM-11 (Japan, Taiwan)", "TM-11 (Japón, Taiwán)")),
                        Option("naqs", text("NAQS import certificate (Korea)", "Certificado NAQS (Corea)")),
                        Option(
                            "canada",
                            text(
                                "Canada organic equivalence attestation",
                                "Constancia de equivalencia orgánica de Canadá",
                            ),
                        ),
                        Option(
                            "none_required",
                            text(
                                "None required by our destination countries",
                                "Ninguno exigido por nuestros países de destino",
                            ),
                            exclusive=True,
                        ),
                        Option("other", text("Other (describe below)", "Otro (describa abajo)")),
                    ),
                ),
                Question(
                    key="export_certificate_types_other",
                    kind="text",
                    label=text(
                        "Describe the other export certificate",
                        "Describa el otro certificado de exportación",
                    ),
                    visible_when=(Condition("export_certificate_types", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional export certificate required: {answer}"),
                ),
                Question(
                    key="export_certificate_process",
                    kind="textarea",
                    label=text(
                        "How do you request, verify, and keep these export certificates?",
                        "¿Cómo solicita, verifica y conserva estos certificados de exportación?",
                    ),
                    coaching=text(
                        "Say who requests the certificate, how far ahead of shipment, and "
                        "where the issued certificates are filed.",
                        "Indique quién solicita el certificado, con cuánta anticipación al "
                        "envío, y dónde se archivan los certificados emitidos.",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes", "export"),),
                    compiles_to=CompileRule(
                        template="Process for requesting, verifying, and retaining export certificates: {answer}"
                    ),
                ),
                Question(
                    key="export_destination_requirements",
                    kind="textarea",
                    label=text(
                        "How do you ensure exported product meets the destination country's "
                        "requirements (labeling, permitted production practices)?",
                        "¿Cómo asegura que el producto exportado cumple los requisitos del país "
                        "de destino (etiquetado, prácticas de producción permitidas)?",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes", "export"),),
                    compiles_to=CompileRule(template="Meeting destination-country requirements: {answer}"),
                ),
                Question(
                    key="import_documentation",
                    kind="checkbox_group",
                    label=text(
                        "How do you ensure each imported shipment carries the required " "documentation?",
                        "¿Cómo asegura que cada envío importado lleve la documentación " "requerida?",
                    ),
                    coaching=text(
                        "A NOP Import Certificate must be issued by a certifier before the "
                        "shipment leaves the country of origin — it cannot be obtained after "
                        "arrival.",
                        "Un Certificado de Importación NOP debe ser emitido por un "
                        "certificador antes de que el envío salga del país de origen — no "
                        "puede obtenerse después de la llegada.",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes", "import"),),
                    compiles_to=CompileRule(template="Import documentation controls: {answer}."),
                    options=(
                        Option(
                            "nop_import_certificate",
                            text(
                                "A current NOP Import Certificate is kept for each shipment",
                                "Se conserva un Certificado de Importación NOP vigente para " "cada envío",
                            ),
                        ),
                        Option(
                            "ace_declaration",
                            text(
                                "Import Certificate data is entered into US Customs' ACE system",
                                "Los datos del Certificado de Importación se ingresan al "
                                "sistema ACE de Aduanas de EE. UU.",
                            ),
                        ),
                        Option(
                            "marked_organic",
                            text(
                                "Each import is identified as organic on all import documents",
                                "Cada importación se identifica como orgánica en todos los "
                                "documentos de importación",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describa abajo)")),
                    ),
                ),
                Question(
                    key="import_documentation_other",
                    kind="text",
                    label=text(
                        "Describe the other import documentation control",
                        "Describa el otro control de documentación de importación",
                    ),
                    visible_when=(Condition("import_documentation", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional import documentation control: {answer}"),
                ),
                Question(
                    key="import_integrity_verification",
                    kind="textarea",
                    label=text(
                        "How do you verify and document that each imported shipment had no "
                        "contact with prohibited substances or ionizing radiation since export?",
                        "¿Cómo verifica y documenta que cada envío importado no tuvo contacto "
                        "con sustancias prohibidas ni radiación ionizante desde su exportación?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("import_export_activity", "includes", "import"),),
                    compiles_to=CompileRule(
                        template="Verification that imported shipments avoided prohibited "
                        "substances and ionizing radiation since export: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="port_integrity_measures",
                    kind="textarea",
                    label=text(
                        "What measures keep organic integrity intact at the port of export or " "entry?",
                        "¿Qué medidas mantienen intacta la integridad orgánica en el puerto de "
                        "exportación o entrada?",
                    ),
                    coaching=text(
                        "Include container sealing, who breaks and re-applies seals, and any "
                        "fumigation or phytosanitary treatment the port may require — a "
                        "treatment with a prohibited material at the port ends the organic "
                        "status of that load.",
                        "Incluya el sellado de contenedores, quién rompe y vuelve a colocar "
                        "los sellos, y cualquier fumigación o tratamiento fitosanitario que el "
                        "puerto pueda exigir — un tratamiento con material prohibido en el "
                        "puerto termina con el estatus orgánico de esa carga.",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("import_export_activity", "includes_any", ["export", "import"]),),
                    compiles_to=CompileRule(
                        template="Measures preserving organic integrity at port: {answer}",
                        section_key="commingling_barriers",
                    ),
                ),
                Question(
                    key="import_export_records",
                    kind="checkbox_group",
                    label=text(
                        "Which import and export records do you keep?",
                        "¿Qué registros de importación y exportación conserva?",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes_any", ["export", "import"]),),
                    compiles_to=CompileRule(template="Import and export records maintained: {answer}."),
                    options=(
                        Option(
                            "certificates",
                            text(
                                "Import or export certificates",
                                "Certificados de importación o exportación",
                            ),
                        ),
                        Option(
                            "operation_certificate",
                            text("Our own organic certificate", "Nuestro propio certificado orgánico"),
                        ),
                        Option(
                            "contracts",
                            text("Contractual agreements", "Acuerdos contractuales"),
                        ),
                        Option(
                            "phytosanitary",
                            text(
                                "Phytosanitary certificates and treatment records",
                                "Certificados fitosanitarios y registros de tratamiento",
                            ),
                        ),
                        Option(
                            "fda_ean",
                            text(
                                "FDA Emergency Action Notifications, where a treatment was performed",
                                "Notificaciones de Acción de Emergencia de la FDA, cuando se " "realizó un tratamiento",
                            ),
                        ),
                        Option(
                            "entry_summary",
                            text("Customs entry summaries", "Resúmenes de entrada aduanera"),
                        ),
                        Option(
                            "labeling",
                            text("Labels used on exported product", "Etiquetas usadas en producto exportado"),
                        ),
                    ),
                ),
            ),
        ),
    ),
)
