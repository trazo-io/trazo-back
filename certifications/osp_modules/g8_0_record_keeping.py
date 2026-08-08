"""
G8.0 — Record Keeping.

Sources: 7 CFR 205.103 (recordkeeping by certified operations), 205.101, 205.201(a)(4),
205.307 (nonretail container labeling — the lot-number linkage requirement). Two sections:

A. Records maintained — the body of this page IS the shipped Common OSP § 11 registry panel
   (`embed="s11_record_types"`): per-record-type evidence with explicit operator confirmation,
   never a bare Y/N. Structurally stronger than a single attestation because each checked box
   carries who confirmed it, when, and what evidence Trazo holds.

B. Audit trail — § 205.103(b)(2) requires records that fully disclose all activities and
   § 205.307 requires the lot number or other unique identification on nonretail containers to
   link to audit trail documentation. Trazo GENERATES a sample audit-trail exhibit from real
   records (lot tags + traceability + mass-balance dossier sections); the operator reviews and
   attaches it rather than hand-drawing one.
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
                        "Record types (Common OSP § 11)",
                        "Tipos de registro (OSP Común § 11)",
                    ),
                    embed="s11_record_types",
                    nop_cite="§ 205.103",
                ),
                Question(
                    key="records_retention_attestation",
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
                            "Operator attests that the records confirmed in the § 11 "
                            "registry are maintained, retained at least five years, and "
                            "available at inspection: {answer}."
                        )
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
                        "Trazo can generate this exhibit from your records (lot tag + "
                        "harvest record + storage + sale, linking elements highlighted). "
                        "Generate it from the Documents page, review it, and attach it here "
                        "— or attach your own.",
                        "Trazo puede generar este ejemplo desde sus registros (etiqueta de "
                        "lote + cosecha + almacenamiento + venta, con los elementos de "
                        "enlace resaltados). Genérelo desde la página Documentos, revíselo "
                        "y adjúntelo aquí — o adjunte el suyo propio.",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                ),
            ),
        ),
    ),
)
