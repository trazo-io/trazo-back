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

from .schema import CompileRule, Condition, Module, ModulePage, Option, Prefill, Question, text

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
                    "Confirma cada tipo de registro que mantiene tu operación. Cuando Trazo ya contiene registros "
                    "de un tipo, la fila muestra la evidencia — confirmarla sigue siendo tu declaración, no la de "
                    "Trazo.",
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
                    # 2026-10-01 (OSP alignment audit T17-F1): CCOF G8.0 A1 asks for ALL the
                    # records the plan's activities need, not the ones the operator happened to
                    # tick. The statement says so, and the gate refuses Yes while any record type
                    # the plan's own answers require is not confirmed (required_records).
                    label=text(
                        "Do you maintain all the records your plan's activities require (confirmed "
                        "above), keep them for at least 5 years, and make them available at inspection?",
                        "¿Mantienes todos los registros que requieren las actividades de tu plan (confirmados "
                        "arriba), los conservas al menos 5 años y los tienes disponibles en la inspección?",
                    ),
                    nop_cite="§ 205.103(b)",
                    compiles_to=CompileRule(
                        template=(
                            "Operator attests that it maintains every record type its plan's "
                            "activities require, retains them at least five years, and makes them "
                            "available at inspection: {answer}."
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
                        "¿Todos tus registros orgánicos se conservan en la ubicación principal de tu negocio?",
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
                        template="All organic records kept at the primary business location: {answer}.",
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
                        "Indica los tipos de registro y la ubicación de cada uno. Tu agencia certificadora puede "
                        "además pedir su propio formulario de instalaciones adicionales; esta respuesta es la que "
                        "les indica si hace falta.",
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
                        "¿Tu contacto principal puede acceder fácilmente a todos los registros relacionados con la "
                        "certificación?",
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
                        "¿Cómo se conservan tus registros?",
                    ),
                    coaching=text(
                        "Tick every kind you use. Paper source documents (delivery tickets, scale tickets, "
                        "handwritten spray logs) filed as well as entered here count as paper too.",
                        "Marca cada forma que uses. Los documentos en papel (boletas de entrega, tiquetes de báscula, "
                        "registros de aplicación escritos a mano) que conservas además de lo que registras aquí "
                        "también cuentan como papel.",
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
                        # 2026-11-15: OTCO C12 12.2-1 splits electronic three ways and offers other. Appended beside
                        # `electronic`, which stays: nearly every filed plan chose it, and retiring it would send every
                        # one back to unanswered over a finer grain. WSDA §O 7 reads any of them as electronic.
                        Option(
                            value="software_spreadsheet",
                            label=text("Computer software or spreadsheet", "Programa de computadora u hoja de cálculo"),
                        ),
                        Option(value="phone_app", label=text("Phone app", "Aplicación de teléfono")),
                        Option(
                            value="online_cloud",
                            label=text("Online or cloud program", "Programa en línea o en la nube"),
                        ),
                        Option(value="other", label=text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                    compiles_to=CompileRule(
                        template="Records are maintained as: {answer}.",
                    ),
                ),
                Question(
                    key="records_maintained_as_other",
                    kind="text",
                    required=False,
                    label=text("How else are records kept?", "¿De qué otra forma se conservan los registros?"),
                    visible_when=(Condition("records_maintained_as", "includes", "other"),),
                    compiles_to=CompileRule(template="Records are also kept as: {answer}."),
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
                # 2026-11-15: OTCO C12 12.2-4, 12.2-5 and 12.2-5a, asked as the form asks them. Whether the operation
                # sources or sells organic product was read from three other pages; now it is stated here, beside the
                # audit trail it decides.
                Question(
                    key="sources_organic_products",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Do you source organic agricultural products, such as seed or crops, for your operation?",
                        "¿Adquieres productos agrícolas orgánicos, como semilla o cultivos, para tu operación?",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(
                        template="The operation sources organic agricultural products ({answer}).",
                        template_false="The operation sources no organic agricultural products.",
                    ),
                ),
                Question(
                    key="sells_as_organic",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Do you sell any crops or crop products as organic?",
                        "¿Vendes algún cultivo o producto de cultivo como orgánico?",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(
                        template="The operation sells crops or crop products as organic ({answer}).",
                        template_false="The operation sells no crop or crop product as organic.",
                    ),
                ),
                Question(
                    key="records_identify_organic_status",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Do your records identify the organic status of every crop and crop product, through harvest, "
                        "storage, shipping and sale?",
                        "¿Tus registros identifican la condición orgánica de cada cultivo y producto, durante la cosecha, "
                        "el almacenamiento, el envío y la venta?",
                    ),
                    visible_when=(Condition("sells_as_organic", "truthy"),),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(
                        template="Records identify the organic status of every crop and crop product ({answer}).",
                        template_false="Records do not identify the organic status of every crop and crop product.",
                    ),
                ),
                Question(
                    key="records_organic_status_explanation",
                    kind="textarea",
                    required=False,
                    label=text(
                        "Which records do not, and how is organic status known for them?",
                        "¿Qué registros no la identifican, y cómo se conoce la condición orgánica en esos casos?",
                    ),
                    visible_when=(Condition("records_identify_organic_status", "eq", False),),
                    compiles_to=CompileRule(
                        template="Records that do not identify organic status, and how it is known: {answer}"
                    ),
                ),
                Question(
                    key="lot_numbering",
                    kind="radio",
                    label=text(
                        "Does your operation assign lot numbers (or another unique ID) to "
                        "track crops once they leave the operation?",
                        "¿Tu operación asigna números de lote (u otra identificación única) para rastrear los "
                        "cultivos una vez que salen de la operación?",
                    ),
                    nop_cite="§ 205.307",
                    compiles_to=CompileRule(template="Lot identification in use: {answer}."),
                    options=(
                        # Retired 2026.11.12. It told the certifier Trazo issues the operation's lot
                        # numbers and carries them on storage and sales records. Trazo does neither:
                        # `History.lot_id` is free text the operator types when a production finishes.
                        # A stored answer of this reads as unanswered and asks the operator to describe
                        # the numbering as their own (CCOF G8.0 B2 asks for exactly that). The label
                        # keeps what was chosen without the claim.
                        Option(
                            "trazo_lots",
                            text(
                                "Yes: the lot IDs recorded in Trazo",
                                "Sí: los IDs de lote registrados en Trazo",
                            ),
                            retired=True,
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
                        "Describe tu sistema de numeración de lotes",
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
                # CCOF G8.0 B2 asks the system "as a Code / Signifies table (example: Lot Number 23123O10 —
                # Code 23 / 123 / O / 10, Signifies Year 2023 / Julian harvest date / Organic / Parcel ID)".
                # The schema has no table kind, so the operator writes one part per line; the module PDF
                # prints the lines as that table, beside lot IDs from the operation's own records.
                Question(
                    key="lot_code_key",
                    kind="textarea",
                    required=False,
                    label=text(
                        "Break your lot number down: one part per line, the part, an equals sign, and what it "
                        "means.",
                        "Desglosa tu número de lote: una parte por línea, la parte, un signo igual y lo que "
                        "significa.",
                    ),
                    coaching=text(
                        "For example, for lot 26-HFE-07: 26 = harvest year, HFE = block (Home Field East), "
                        "07 = picking day. The packet prints it as a Code / Signifies table next to lot numbers "
                        "from your records, so a reviewer can read one against the other.",
                        "Por ejemplo, para el lote 26-HFE-07: 26 = año de cosecha, HFE = bloque (Home Field East), "
                        "07 = día de cosecha. El paquete lo imprime como una tabla Código / Significado junto a "
                        "números de lote de tus registros, para que quien revisa lea uno frente al otro.",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    visible_when=(Condition("lot_numbering", "eq", "own_system"),),
                    compiles_to=CompileRule(template="Lot number key: {answer}"),
                ),
                # OTCO C12 12.2-3 offers five ways records trace a sale back to the field; WSDA §O 8 asks the
                # same ("e.g. lot coding system, invoice dates"). Lot numbers are `lot_numbering` above, so
                # this asks only the others, and an operation that traces by field name no longer has to
                # answer "No lot numbering is used" and stop there.
                Question(
                    key="trace_mechanisms",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "Besides lot numbers, what on your records traces a sale back to the field it came "
                        "from? Check all that apply.",
                        "Además de los números de lote, ¿qué en tus registros rastrea una venta hasta el campo de "
                        "donde vino? Marca todas las que correspondan.",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(
                        template="Besides lot numbers, records trace a sale back to the field by: {answer}."
                    ),
                    options=(
                        Option(
                            "field_names",
                            text("Field or block numbers or names", "Números o nombres de campo o bloque"),
                        ),
                        Option("julian_date_codes", text("Julian date codes", "Códigos de fecha juliana")),
                        Option(
                            "farm_name_single_field",
                            text(
                                "The farm name (the operation is all organic, with one field)",
                                "El nombre de la finca (la operación es toda orgánica, con un solo campo)",
                            ),
                        ),
                        Option(
                            "harvest_invoice_dates", text("Harvest and invoice dates", "Fechas de cosecha y de factura")
                        ),
                        Option("other", text("Other", "Otro")),
                        Option(
                            "lot_numbers_only",
                            text("Nothing else: lot numbers only", "Nada más: solo números de lote"),
                            exclusive=True,
                        ),
                    ),
                ),
                Question(
                    key="trace_mechanisms_other",
                    kind="text",
                    required=False,
                    label=text(
                        "Other way records trace a sale to the field",
                        "Otra forma en que los registros rastrean una venta hasta el campo",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    visible_when=(Condition("trace_mechanisms", "includes", "other"),),
                    compiles_to=CompileRule(template="Other way records trace a sale to the field: {answer}."),
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
                        "Tu paquete de renovación ya incluye un ejemplo generado — documento 05, Rastro de "
                        "auditoría: los tipos de registro que confirmaste en §A con sus elementos de enlace, y un "
                        "lote terminado rastreado desde la cosecha, por el almacenamiento, hasta la venta. Adjunta "
                        "aquí tu propio ejemplo solo si deseas complementarlo.",
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
                    "question and the one about Canada, and are done with this page. It matters for tree nuts, dried "
                    "fruit, and other crops that commonly ship abroad: several trade partners "
                    "require an export certificate issued by your certifier BEFORE the "
                    "shipment leaves, and a shipment that departs without one cannot be "
                    "corrected afterwards.",
                    "La mayoría de las operaciones que venden solo dentro de Estados Unidos responden la primera "
                    "pregunta y la de Canadá, y terminan con esta página. Importa para frutos secos, fruta deshidratada y otros "
                    "cultivos que suelen enviarse al exterior: varios socios comerciales exigen un certificado de "
                    "exportación emitido por tu certificador ANTES de que salga el envío, y un envío que parte sin "
                    "él no puede corregirse después.",
                ),
            ),
            questions=(
                Question(
                    key="import_export_activity",
                    kind="checkbox_group",
                    label=text(
                        "Does your operation import or export organic products, directly or indirectly, "
                        "now or in plans?",
                        "¿Tu operación importa o exporta productos orgánicos, directa o indirectamente, ahora o en "
                        "tus planes?",
                    ),
                    coaching=text(
                        "Indirect export counts: product a buyer, broker or trader ships abroad, or that "
                        "leaves the country as an ingredient. Certifiers ask about it because the "
                        "destination country's rules can reach your crop.",
                        "La exportación indirecta cuenta: el producto que un comprador, corredor o comerciante "
                        "envía al exterior, o que sale del país como ingrediente. Los certificadores preguntan por "
                        "ella porque las reglas del país de destino pueden alcanzar tu cultivo.",
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
                        # WSDA AGR 2121 §Q 1. Seed bought abroad for the operation's own planting is
                        # neither a product nor an ingredient, so a farm importing only seed had no
                        # true box to tick and the import questions never opened (2026-11-17).
                        Option(
                            "import_seed",
                            text(
                                "We import, or plan to import, organic seed or planting stock directly from "
                                "other countries for use on our farm",
                                "Importamos, o planeamos importar, semilla o material de plantación orgánico "
                                "directamente de otros países para usarlo en nuestra finca",
                            ),
                        ),
                        Option(
                            "none_no_known_export",
                            text(
                                "Neither: all product is sold within the United States, and no buyer we "
                                "know of exports it or plans to export it",
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
                        "¿A qué países exportas o planeas exportar, directa o indirectamente?",
                    ),
                    coaching=text(
                        "For indirect export, name the countries your buyer, broker or trader ships to, as "
                        "far as you know them.",
                        "Para la exportación indirecta, indica los países a los que envía tu comprador, corredor o "
                        "comerciante, en la medida en que los conozcas.",
                    ),
                    visible_when=(Condition("import_export_activity", "includes_any", ["export", "indirect_export"]),),
                    compiles_to=CompileRule(template="Export destination countries: {answer}."),
                ),
                Question(
                    key="export_certificate_types",
                    kind="checkbox_group",
                    label=text(
                        "Which export certificates do your destination countries require?",
                        "¿Qué certificados de exportación exigen tus países de destino?",
                    ),
                    coaching=text(
                        "Each of these is issued by your certifier, not by you, and must be "
                        "requested before the shipment departs. Check the USDA NOP "
                        "International Trade Partners page if you are not sure which applies.",
                        "Cada uno de estos lo emite tu certificador, no tú, y debe solicitarse antes de que salga "
                        "el envío. Consulta la página de Socios Comerciales Internacionales del NOP del USDA si no "
                        "estás seguro de cuál aplica.",
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
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="export_certificate_types_other",
                    kind="text",
                    label=text(
                        "Describe the other export certificate",
                        "Describe el otro certificado de exportación",
                    ),
                    visible_when=(Condition("export_certificate_types", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional export certificate required: {answer}"),
                ),
                Question(
                    key="export_certificate_process",
                    kind="textarea",
                    label=text(
                        "How do you request, verify, and keep these export certificates?",
                        "¿Cómo solicitas, verificas y conservas estos certificados de exportación?",
                    ),
                    coaching=text(
                        "Say who requests the certificate, how far ahead of shipment, and "
                        "where the issued certificates are filed.",
                        "Indica quién solicita el certificado, con cuánta anticipación al envío, y dónde se "
                        "archivan los certificados emitidos.",
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
                        "¿Cómo aseguras que el producto exportado cumple los requisitos del país "
                        "de destino (etiquetado, prácticas de producción permitidas)?",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes", "export"),),
                    compiles_to=CompileRule(template="Meeting destination-country requirements: {answer}"),
                ),
                # WSDA AGR 2121 §Q 8. Asked of a direct exporter only, as the form asks it: packaging
                # chosen by a buyer who exports is the buyer's.
                Question(
                    key="export_package_types",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "What types of packages and labels do you use for export markets?",
                        "¿Qué tipos de empaques y etiquetas usas para los mercados de exportación?",
                    ),
                    coaching=text(
                        "Organic product must be labeled for the destination market's rules.",
                        "El producto orgánico debe etiquetarse según las reglas del mercado de destino.",
                    ),
                    nop_cite="§ 205.307",
                    visible_when=(Condition("import_export_activity", "includes", "export"),),
                    compiles_to=CompileRule(template="Packages and labels used for export markets: {answer}."),
                    options=(
                        Option(
                            "retail_consumer",
                            text("Retail consumer packages", "Empaques para venta al consumidor"),
                        ),
                        Option(
                            "wholesale_shipping",
                            text("Wholesale shipping containers", "Contenedores de envío mayorista"),
                        ),
                        Option(
                            "bulk",
                            text(
                                "Bulk shipping or storage containers",
                                "Contenedores a granel para envío o almacenamiento",
                            ),
                        ),
                    ),
                ),
                # WSDA AGR 2121 §Q 9. What travels WITH each shipment, which is not the same question as
                # which certificates a destination requires (`export_certificate_types`).
                Question(
                    key="export_shipment_documents",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "Which documents accompany each organic export shipment?",
                        "¿Qué documentos acompañan cada envío orgánico de exportación?",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes", "export"),),
                    compiles_to=CompileRule(template="Documents accompanying each organic export shipment: {answer}."),
                    options=(
                        Option("bill_of_lading", text("Bill of lading", "Conocimiento de embarque")),
                        Option("certificate_of_analysis", text("Certificate of analysis", "Certificado de análisis")),
                        Option(
                            "eu_coi",
                            text("EU Certificate of Inspection", "Certificado de Inspección de la UE"),
                        ),
                        Option("invoice", text("Invoice", "Factura")),
                        Option(
                            "naqs",
                            text(
                                "NAQS import certificate (South Korea)",
                                "Certificado de importación NAQS (Corea del Sur)",
                            ),
                        ),
                        Option("organic_certificate", text("Organic certificate", "Certificado orgánico")),
                        Option("phytosanitary", text("Phytosanitary certificate", "Certificado fitosanitario")),
                        Option(
                            "tm11",
                            text("USDA TM-11 export certificate", "Certificado de exportación TM-11 del USDA"),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="export_shipment_documents_other",
                    kind="text",
                    label=text(
                        "Describe the other export shipment document",
                        "Describe el otro documento del envío de exportación",
                    ),
                    visible_when=(Condition("export_shipment_documents", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional document accompanying export shipments: {answer}"),
                ),
                # OTCO C8 8.4-4.
                Question(
                    key="equivalency_compliance_method",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "How do you make sure exported products meet the organic equivalency arrangement with "
                        "the destination country?",
                        "¿Cómo te aseguras de que los productos exportados cumplan el acuerdo de equivalencia "
                        "orgánica con el país de destino?",
                    ),
                    coaching=text(
                        "The United States has organic equivalency arrangements with Canada, the European "
                        "Union, the United Kingdom, Switzerland, Japan, South Korea and Taiwan. Each one "
                        "carries its own conditions.",
                        "Estados Unidos tiene acuerdos de equivalencia orgánica con Canadá, la Unión Europea, el "
                        "Reino Unido, Suiza, Japón, Corea del Sur y Taiwán. Cada uno tiene sus propias "
                        "condiciones.",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes", "export"),),
                    compiles_to=CompileRule(
                        template="How exported products are kept within the destination's equivalency "
                        "arrangement: {answer}."
                    ),
                    options=(
                        Option(
                            "certifier_review",
                            text(
                                "Products are submitted to our certifier for review under the arrangement "
                                "before export",
                                "Enviamos los productos a nuestro certificador para que los revise según el "
                                "acuerdo antes de exportarlos",
                            ),
                        ),
                        Option("other", text("Another way (describe below)", "De otra forma (describe abajo)")),
                    ),
                ),
                Question(
                    key="equivalency_compliance_method_other",
                    kind="text",
                    label=text(
                        "Describe how exported products are kept within the arrangement",
                        "Describe cómo los productos exportados se mantienen dentro del acuerdo",
                    ),
                    visible_when=(Condition("equivalency_compliance_method", "includes", "other"),),
                    compiles_to=CompileRule(template="Other way exported products meet the arrangement: {answer}"),
                ),
                # WSDA AGR 2121 §Q Critical Variances: Canada, 1, 2 and 2a. Asked of every operation that
                # answered the first question, as WSDA asks it of every grower: a crop sold to a packer can
                # reach Canada without the grower exporting anything.
                Question(
                    key="canada_export_possible",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Do you produce crops or products that may be exported to Canada, directly, by a "
                        "distributor or buyer, or as an ingredient in a processed product?",
                        "¿Produces cultivos o productos que podrían exportarse a Canadá, directamente, a través de "
                        "un distribuidor o comprador, o como ingrediente de un producto procesado?",
                    ),
                    coaching=text(
                        "If a buyer may ship some of your crop to Canada and you cannot rule it out, answer Yes. "
                        "Canada does not accept as organic the crops produced with sodium nitrate.",
                        "Si un comprador podría enviar parte de tu cosecha a Canadá y no puedes descartarlo, "
                        "responde Sí. Canadá no acepta como orgánicos los cultivos producidos con nitrato de sodio.",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "truthy"),),
                    compiles_to=CompileRule(
                        template="Crops or products may be exported to Canada, directly, through a distributor "
                        "or buyer, or as an ingredient.",
                        template_false="No crops or products are expected to reach Canada, directly, through a "
                        "distributor or buyer, or as an ingredient.",
                    ),
                ),
                Question(
                    key="sodium_nitrate_used",
                    kind="boolean",
                    prefill=Prefill(source="sodium_nitrate_evidence"),
                    label=text(
                        "Do you use sodium nitrate (Chilean nitrate) to produce organic crops?",
                        "¿Usas nitrato de sodio (nitrato de Chile) para producir cultivos orgánicos?",
                    ),
                    coaching=text(
                        "The USDA organic regulations allow sodium nitrate up to 20% of a crop's total nitrogen "
                        "requirement (§ 205.602(h)). Canada does not accept as organic the crops produced with it.",
                        "El reglamento orgánico del USDA permite el nitrato de sodio hasta el 20% del requerimiento "
                        "total de nitrógeno del cultivo (§ 205.602(h)). Canadá no acepta como orgánicos los "
                        "cultivos producidos con él.",
                    ),
                    nop_cite="§ 205.602(h)",
                    visible_when=(Condition("canada_export_possible", "truthy"),),
                    compiles_to=CompileRule(
                        template="Sodium nitrate is used to produce organic crops.",
                        template_false="Sodium nitrate is not used to produce organic crops.",
                    ),
                ),
                Question(
                    key="sodium_nitrate_canada_separation",
                    kind="textarea",
                    label=text(
                        "How do you tell apart the organic crops produced with sodium nitrate from the organic "
                        "crops eligible for export to Canada?",
                        "¿Cómo distingues los cultivos orgánicos producidos con nitrato de sodio de los cultivos "
                        "orgánicos aptos para exportarse a Canadá?",
                    ),
                    coaching=text(
                        "Say which fields or lots receive it, how the records and lot codes mark them, and how "
                        "buyers are told those lots cannot go to Canada.",
                        "Indica qué campos o lotes lo reciben, cómo los marcan los registros y los códigos de lote, "
                        "y cómo se informa a los compradores que esos lotes no pueden ir a Canadá.",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("sodium_nitrate_used", "truthy"),),
                    compiles_to=CompileRule(
                        template="How crops produced with sodium nitrate are kept apart from crops eligible for "
                        "export to Canada: {answer}"
                    ),
                ),
                # WSDA AGR 2121 §Q 2 and 3, asked when the operation imports seed or planting stock.
                Question(
                    key="import_seed_countries",
                    kind="checkbox_group",
                    label=text(
                        "Which countries do you import organic seed or planting stock from?",
                        "¿De qué países importas semilla o material de plantación orgánico?",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes", "import_seed"),),
                    compiles_to=CompileRule(
                        template="Countries organic seed or planting stock is imported from: {answer}."
                    ),
                    options=(
                        Option("canada", text("Canada", "Canadá")),
                        Option("european_union", text("European Union", "Unión Europea")),
                        Option("great_britain", text("Great Britain", "Gran Bretaña")),
                        Option("india", text("India", "India")),
                        Option("israel", text("Israel", "Israel")),
                        Option("japan", text("Japan", "Japón")),
                        Option("mexico", text("Mexico", "México")),
                        Option("new_zealand", text("New Zealand", "Nueva Zelanda")),
                        Option("south_korea", text("South Korea", "Corea del Sur")),
                        Option("switzerland", text("Switzerland", "Suiza")),
                        Option("other", text("Other (name below)", "Otro (indícalo abajo)")),
                    ),
                ),
                Question(
                    key="import_seed_countries_other",
                    kind="text",
                    label=text("Name the other countries", "Indica los otros países"),
                    visible_when=(Condition("import_seed_countries", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Other countries seed or planting stock is imported from: {answer}"
                    ),
                ),
                Question(
                    key="import_seed_standards",
                    kind="checkbox_group",
                    label=text(
                        "Which organic standards is the imported seed or planting stock certified to?",
                        "¿Según qué normas orgánicas está certificada la semilla o el material de plantación "
                        "importado?",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("import_export_activity", "includes", "import_seed"),),
                    compiles_to=CompileRule(
                        template="Organic standards the imported seed or planting stock is certified to: {answer}."
                    ),
                    options=(
                        Option(
                            "usda_nop",
                            text(
                                "USDA organic regulations, 7 CFR Part 205",
                                "Reglamento orgánico del USDA, 7 CFR Parte 205",
                            ),
                        ),
                        Option(
                            "canada_cor",
                            text(
                                "Canada Organic Regime (COR), CAN/CGSB standards",
                                "Régimen Orgánico de Canadá (COR), normas CAN/CGSB",
                            ),
                        ),
                        Option(
                            "eu_organic",
                            text(
                                "EU organic regulation: (EC) No 834/2007, replaced since 2022 by (EU) 2018/848",
                                "Reglamento orgánico de la UE: (CE) n.º 834/2007, sustituido desde 2022 por el "
                                "(UE) 2018/848",
                            ),
                        ),
                        Option("other", text("Other (name below)", "Otra (indícala abajo)")),
                    ),
                ),
                Question(
                    key="import_seed_standards_other",
                    kind="text",
                    label=text("Name the other standard", "Indica la otra norma"),
                    visible_when=(Condition("import_seed_standards", "includes", "other"),),
                    compiles_to=CompileRule(
                        template="Other standard the imported seed or planting stock is certified to: {answer}"
                    ),
                ),
                Question(
                    key="import_documentation",
                    kind="checkbox_group",
                    label=text(
                        "How do you ensure each imported shipment carries the required " "documentation?",
                        "¿Cómo aseguras que cada envío importado lleve la documentación " "requerida?",
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
                    visible_when=(Condition("import_export_activity", "includes_any", ["import", "import_seed"]),),
                    compiles_to=CompileRule(template="Import documentation controls: {answer}."),
                    options=(
                        Option(
                            "nop_import_certificate",
                            text(
                                "A current NOP Import Certificate is kept for each shipment",
                                "Se conserva un Certificado de Importación NOP vigente para " "cada envío",
                            ),
                        ),
                        # WSDA AGR 2121 §Q 4 names these, per imported shipment (2026-11-17).
                        Option(
                            "bill_of_lading",
                            text(
                                "A bill of lading is kept for each shipment",
                                "Se conserva un conocimiento de embarque para cada envío",
                            ),
                        ),
                        Option(
                            "certificate_of_analysis",
                            text(
                                "A certificate of analysis is kept for each shipment",
                                "Se conserva un certificado de análisis para cada envío",
                            ),
                        ),
                        Option(
                            "invoice",
                            text("An invoice is kept for each shipment", "Se conserva una factura para cada envío"),
                        ),
                        Option(
                            "phytosanitary_certificate",
                            text(
                                "A phytosanitary certificate is kept for each shipment",
                                "Se conserva un certificado fitosanitario para cada envío",
                            ),
                        ),
                        Option(
                            "transaction_certificate",
                            text(
                                "A transaction certificate is kept for each shipment",
                                "Se conserva un certificado de transacción para cada envío",
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
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="import_documentation_other",
                    kind="text",
                    label=text(
                        "Describe the other import documentation control",
                        "Describe el otro control de documentación de importación",
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
                        "¿Cómo verificas y documentas que cada envío importado no tuvo contacto con sustancias "
                        "prohibidas ni radiación ionizante desde su exportación?",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("import_export_activity", "includes_any", ["import", "import_seed"]),),
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
                        "Incluye el sellado de contenedores, quién rompe y vuelve a colocar los sellos, y cualquier "
                        "fumigación o tratamiento fitosanitario que el puerto pueda exigir — un tratamiento con "
                        "material prohibido en el puerto termina con el estatus orgánico de esa carga.",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(
                        Condition("import_export_activity", "includes_any", ["export", "import", "import_seed"]),
                    ),
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
                        "¿Qué registros de importación y exportación conservas?",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(
                        Condition("import_export_activity", "includes_any", ["export", "import", "import_seed"]),
                    ),
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
