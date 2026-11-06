"""
Parcel Application — the per-parcel § 205.202 module (plan #30, Appendix A §f).

Six lettered sections mirroring the certifier's own parcel application:
  A location & identity · B transitional status · C livestock · D adjacent land &
  buffers · E field map · F land history.

Evidence lives ONCE, on real models — this definition BINDS rather than stores:
  - `parcel_field` questions read/write Parcel columns through the application
    endpoint's whitelist (name, apn, section_township_range, address,
    container_production, treated lumber trio, date_began_managing).
  - `embed` questions mount live panels: the crop-history grid
    (ParcelCropHistory), the computed transition-status card, the buffer-zone
    editor (Parcel.buffer_zones), the map status panel, and the landowner
    affidavit card.
  - Everything else (county, livestock, attestations) lands in
    Parcel.application_answers.

Completion is NOT derived from these answers — the status service
(product/services/parcel_application_status.py) reads LIVE model state, so a
crop-history row added anywhere in the app moves this module forward.

NOT registered in MODULE_REGISTRY: farm-wide OSP modules ride module_responses
on the OSP lifecycle; this one repeats per parcel and binds models, so it is
served by the parcel `application` endpoint instead.
"""

from .schema import Condition, Module, ModulePage, Option, Question, text

PARCEL_APPLICATION = Module(
    key="parcel_application",
    code="",
    title=text("Parcel Application", "Solicitud de parcela"),
    nop_cites=("§ 205.202", "§ 205.201(a)"),
    education=(
        text(
            "Certifiers evaluate each parcel on its own: where it is, what grew there for "
            "the last three years, what borders it, and how drift is prevented. Answer once "
            "here — the same records feed your audit dossier and renewal packet.",
            "El certificador evalúa cada parcela por separado: dónde está, qué se cultivó en los últimos tres años, "
            "qué la rodea y cómo se previene la deriva. Responde una vez aquí — los mismos registros alimentan tu "
            "expediente de auditoría y tu paquete de renovación.",
        ),
    ),
    allows_not_applicable=False,
    default_section_key="practices_procedures",
    pages=(
        ModulePage(
            key="a_location",
            title=text("A. Location & identity", "A. Ubicación e identidad"),
            education=(
                text(
                    "APN (assessor's parcel number) or Section–Township–Range lets the "
                    "certifier match this parcel to county records. One of the two is "
                    "enough.",
                    "El APN (número de parcela del catastro) o Sección–Municipio–Rango "
                    "permite al certificador vincular la parcela con los registros del "
                    "condado. Basta con uno de los dos.",
                ),
            ),
            questions=(
                Question(
                    key="parcel_name",
                    kind="text",
                    label=text("Parcel name", "Nombre de la parcela"),
                    parcel_field="name",
                    required=False,
                ),
                Question(
                    key="apn",
                    kind="text",
                    label=text("APN (assessor's parcel number)", "APN (número de parcela del catastro)"),
                    parcel_field="apn",
                    required=False,
                    placeholder=text("e.g., 042-031-007", "p. ej., 042-031-007"),
                ),
                Question(
                    key="section_township_range",
                    kind="text",
                    label=text("Section – Township – Range", "Sección – Municipio – Rango"),
                    parcel_field="section_township_range",
                    required=False,
                    placeholder=text("e.g., S14 T3N R2E", "p. ej., S14 T3N R2E"),
                ),
                Question(
                    key="address",
                    kind="text",
                    label=text("Physical address / location", "Dirección física / ubicación"),
                    parcel_field="address",
                    required=False,
                ),
                Question(
                    key="county",
                    kind="text",
                    label=text("County", "Condado"),
                    required=False,
                ),
                Question(
                    key="container_production",
                    kind="boolean",
                    label=text(
                        "Is this parcel container or greenhouse production?",
                        "¿Esta parcela produce en contenedores o invernadero?",
                    ),
                    coaching=text(
                        "Container media is not land — a yes changes which land-history " "questions apply.",
                        "El sustrato en contenedor no es suelo — un sí cambia qué preguntas "
                        "de historial de tierra aplican.",
                    ),
                    parcel_field="container_production",
                    required=False,
                    nop_cite="§ 205.2",
                ),
                Question(
                    key="treated_lumber_present",
                    kind="boolean",
                    label=text(
                        "Is treated lumber in contact with crops or soil?",
                        "¿Hay madera tratada en contacto con cultivos o suelo?",
                    ),
                    parcel_field="treated_lumber_present",
                    required=False,
                    nop_cite="§ 205.206(f)",
                ),
                Question(
                    key="treated_lumber_description",
                    kind="textarea",
                    label=text("Describe the treated lumber", "Describe la madera tratada"),
                    parcel_field="treated_lumber_description",
                    required=False,
                    visible_when=(Condition(question="treated_lumber_present", op="truthy"),),
                ),
                Question(
                    key="treated_lumber_install_date",
                    kind="date",
                    label=text("When was it installed?", "¿Cuándo se instaló?"),
                    parcel_field="treated_lumber_install_date",
                    required=False,
                    visible_when=(Condition(question="treated_lumber_present", op="truthy"),),
                ),
                Question(
                    key="treated_lumber_contact_prevention",
                    kind="textarea",
                    label=text(
                        "How is contact between the treated lumber and organic crops or soil prevented?",
                        "¿Cómo se evita el contacto entre la madera tratada y los cultivos o el suelo orgánicos?",
                    ),
                    coaching=text(
                        "A liner, a setback, a barrier or a replacement schedule — the measure that "
                        "keeps what is already installed from touching organic crop or soil.",
                        "Un revestimiento, un retiro, una barrera o un calendario de reemplazo — la "
                        "medida que impide que lo ya instalado toque el cultivo o el suelo orgánicos.",
                    ),
                    required=False,
                    nop_cite="§ 205.206(f)",
                    visible_when=(Condition(question="treated_lumber_present", op="truthy"),),
                ),
                Question(
                    # WSDA AGR 2264 ref 7 ("Do you own this site?") and OTCO C2 2.1-6 ("Do you: Own /
                    # Lease/Rent / Manage this parcel? Other"). CCOF's Parcel Application does not ask.
                    # Today's tenure, NOT `LandownerAffidavit`: that names whoever attests to a past
                    # period of land use, and reading one as the other would misattribute a signature.
                    key="site_tenure",
                    kind="radio",
                    label=text(
                        "Do you own, lease or manage this parcel?",
                        "¿Esta parcela es tuya, la arriendas o la manejas?",
                    ),
                    options=(
                        Option(value="own", label=text("Own", "Es propia")),
                        Option(value="lease_rent", label=text("Lease or rent", "La arriendo o la alquilo")),
                        Option(
                            value="manage",
                            label=text(
                                "Manage it for the owner (neither own nor lease)",
                                "La manejo para el dueño (no es propia ni arrendada)",
                            ),
                        ),
                        Option(value="other", label=text("Other", "Otro")),
                    ),
                    required=False,
                ),
                Question(
                    key="site_tenure_other",
                    kind="text",
                    label=text("Describe the arrangement", "Describe el acuerdo"),
                    required=False,
                    visible_when=(Condition(question="site_tenure", op="eq", value="other"),),
                ),
                Question(
                    # WSDA AGR 2264 ref 7a: the land owner's name, email, phone no. and address.
                    key="landowner_name",
                    kind="text",
                    label=text("Landowner's name", "Nombre del dueño de la tierra"),
                    coaching=text(
                        "The person or business that owns the land today, not someone who signs a statement about "
                        "its past use.",
                        "La persona o empresa dueña de la tierra hoy, no quien firma una declaración sobre el uso "
                        "anterior de la tierra.",
                    ),
                    required=False,
                    visible_when=(
                        Condition(question="site_tenure", op="one_of", value=["lease_rent", "manage", "other"]),
                    ),
                ),
                Question(
                    key="landowner_email",
                    kind="text",
                    label=text("Landowner's email", "Correo electrónico del dueño de la tierra"),
                    required=False,
                    visible_when=(
                        Condition(question="site_tenure", op="one_of", value=["lease_rent", "manage", "other"]),
                    ),
                ),
                Question(
                    key="landowner_phone",
                    kind="text",
                    label=text("Landowner's phone", "Teléfono del dueño de la tierra"),
                    required=False,
                    visible_when=(
                        Condition(question="site_tenure", op="one_of", value=["lease_rent", "manage", "other"]),
                    ),
                ),
                Question(
                    key="landowner_address",
                    kind="text",
                    label=text("Landowner's address", "Dirección del dueño de la tierra"),
                    required=False,
                    visible_when=(
                        Condition(question="site_tenure", op="one_of", value=["lease_rent", "manage", "other"]),
                    ),
                ),
                Question(
                    # WSDA AGR 2264 ref 7b.
                    key="lease_management_detail",
                    kind="textarea",
                    label=text(
                        "Details of the lease or arrangement, and who is responsible for day-to-day management",
                        "Detalles del arrendamiento o del acuerdo, y quién es responsable del manejo diario",
                    ),
                    required=False,
                    visible_when=(
                        Condition(question="site_tenure", op="one_of", value=["lease_rent", "manage", "other"]),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_transition",
            title=text("B. Transitional status", "B. Estado de transición"),
            education=(
                text(
                    "Land must be free of prohibited substances for 36 months before harvest "
                    "of an organic crop (§ 205.202(b)). The card below computes your status "
                    "from the crop-history records — it updates itself as records change.",
                    "La tierra debe estar libre de sustancias prohibidas por 36 meses antes "
                    "de la cosecha orgánica (§ 205.202(b)). La tarjeta siguiente calcula su "
                    "estado desde los registros de historial — se actualiza sola cuando los "
                    "registros cambian.",
                ),
            ),
            questions=(
                Question(
                    key="transition_card",
                    kind="info",
                    label=text("Computed transition status", "Estado de transición calculado"),
                    embed="transition_card",
                    required=False,
                    nop_cite="§ 205.202(b)",
                ),
                Question(
                    key="date_began_managing",
                    kind="date",
                    label=text(
                        "When did you begin managing this parcel?",
                        "¿Cuándo comenzaste a manejar esta parcela?",
                    ),
                    parcel_field="date_began_managing",
                    required=False,
                ),
                Question(
                    key="expected_first_organic_harvest",
                    kind="date",
                    label=text(
                        "Expected first organic harvest (if in transition)",
                        "Primera cosecha orgánica esperada (si está en transición)",
                    ),
                    required=False,
                    # A parcel stated currently certified is not in transition, so the question does
                    # not apply to it (production specimen packet, 2026-10-29: every certified parcel
                    # listed it as an unanswered question). `ne`, not `one_of`: the deciding question
                    # is on page F, so the question stays visible until it is answered (review of #250).
                    visible_when=(Condition(question="currently_certified", op="ne", value="yes"),),
                ),
            ),
        ),
        ModulePage(
            key="c_livestock",
            title=text("C. Livestock", "C. Ganado"),
            questions=(
                Question(
                    key="livestock_present",
                    kind="radio",
                    label=text(
                        "Is livestock kept on this parcel?",
                        "¿Se mantiene ganado en esta parcela?",
                    ),
                    options=(
                        Option(value="no", label=text("No", "No")),
                        Option(value="yes", label=text("Yes", "Sí")),
                    ),
                    required=False,
                ),
                Question(
                    key="livestock_detail",
                    kind="textarea",
                    label=text(
                        "Describe the livestock and manure management",
                        "Describe el ganado y el manejo del estiércol",
                    ),
                    required=False,
                    visible_when=(Condition(question="livestock_present", op="eq", value="yes"),),
                ),
            ),
        ),
        ModulePage(
            key="d_buffers",
            title=text("D. Adjacent land & buffers", "D. Tierras colindantes y amortiguamiento"),
            education=(
                text(
                    "For each border with conventional or prohibited-use land, record the "
                    "adjoining use, the buffer type and width, and what grows in the buffer "
                    "— buffer crop may never be sold as organic (§ 205.202(c)).",
                    "Para cada límite con tierra convencional o de uso prohibido, registra el uso colindante, el "
                    "tipo y ancho del amortiguamiento, y qué crece en él — el cultivo del amortiguamiento nunca "
                    "puede venderse como orgánico (§ 205.202(c)).",
                ),
            ),
            questions=(
                Question(
                    key="buffer_editor",
                    kind="info",
                    label=text("Borders and buffer zones", "Límites y zonas de amortiguamiento"),
                    embed="buffer_editor",
                    required=False,
                    nop_cite="§ 205.202(c)",
                ),
                Question(
                    # § 205.400(f) — the notices the certifier was SENT about this field, printed
                    # on the field's own page. "Buffer widened to 45 ft" was filed on the OSP
                    # screen while the buffer row above still said 30 ft, and the two statements
                    # never met on one page until 2026-08-23.
                    key="parcel_change_notifications",
                    kind="info",
                    label=text(
                        "Change notifications filed about this parcel",
                        "Notificaciones de cambio presentadas sobre esta parcela",
                    ),
                    embed="parcel_change_notifications",
                    required=False,
                    nop_cite="§ 205.400(f)",
                ),
                Question(
                    # § 205.400(f)(1) — a drift or other contamination incident on THIS parcel
                    # belongs on its own application. It was recorded (a GeneralEvent marked
                    # is_contamination_incident) and notified, and then never appeared on the
                    # page a certifier reads about that parcel's adjacent land; the 2028
                    # renewal for a block that took drift on 11 May 2027 said nothing about it.
                    key="contamination_incidents",
                    kind="info",
                    label=text(
                        "Contamination incidents recorded on this parcel",
                        "Incidentes de contaminación registrados en esta parcela",
                    ),
                    embed="contamination_incidents",
                    required=False,
                    nop_cite="§ 205.400(f)(1)",
                ),
                Question(
                    key="no_adjoining_prohibited",
                    kind="boolean",
                    label=text(
                        "All adjoining land is organic or non-agricultural — no buffers needed",
                        "Toda la tierra colindante es orgánica o no agrícola — no se requieren amortiguamientos",
                    ),
                    coaching=text(
                        "Only attest this after walking every border. Leaving it unanswered "
                        "is not a claim either way.",
                        "Ateste esto solo tras recorrer cada límite. Dejarlo sin responder "
                        "no es una afirmación en ningún sentido.",
                    ),
                    required=False,
                ),
            ),
        ),
        ModulePage(
            key="e_map",
            title=text("E. Field map", "E. Mapa del campo"),
            education=(
                text(
                    "Certifiers require a map showing boundaries, buffers, and adjoining "
                    "land uses. Trazo generates it from your parcel boundaries and buffer "
                    "records — draw the boundary once and the map stays current.",
                    "El certificador requiere un mapa con límites, amortiguamientos y usos colindantes. Trazo lo "
                    "genera desde tus límites de parcela y registros de amortiguamiento — dibuja el límite una vez "
                    "y el mapa se mantiene al día.",
                ),
            ),
            questions=(
                Question(
                    key="map_status",
                    kind="info",
                    label=text("Boundary & map status", "Estado del límite y mapa"),
                    embed="parcel_map",
                    required=False,
                ),
                # CCOF ORGB49 §E prefers satellite imagery and names eleven required elements —
                # roads and landmarks, permanent block identifiers, other operation areas, the
                # livestock and treated-lumber notes — most of which a boundary schematic
                # cannot carry. WSDA AGR 2264 additionally wants the operation and site name
                # printed ON the map. So the drawing is a floor, not the answer: the operator's
                # own map rides in the packet under `parcels/maps/`.
                Question(
                    key="map_upload",
                    kind="upload",
                    label=text(
                        "Attach your parcel map (8.5x11, satellite imagery preferred)",
                        "Adjunta el mapa de tu parcela (8.5x11, se prefiere imagen satelital)",
                    ),
                    coaching=text(
                        "Mark the parcel boundaries, a north arrow, total acreage, block or lot "
                        "identifiers, the nearest roads or landmarks, adjacent land uses, and "
                        "your buffer zones with their widths. If you farm in Washington, print "
                        "your operation name and this site's name on the map itself.",
                        "Marca los límites de la parcela, una flecha norte, la superficie total, los "
                        "identificadores de bloque o lote, los caminos o puntos de referencia más cercanos, los "
                        "usos de la tierra colindante y sus zonas de amortiguamiento con sus anchos. Si produces en "
                        "Washington, imprime el nombre de tu operación y el de este sitio en el mapa.",
                    ),
                    nop_cite="\u00a7 205.202",
                    required=False,
                ),
            ),
        ),
        ModulePage(
            key="f_land_history",
            title=text("F. Land history", "F. Historial de la tierra"),
            education=(
                text(
                    "Three years of field history — crop grown, substances applied, and the "
                    "date/name of the last prohibited material — is the core of § 205.202(b) "
                    "eligibility. If you managed the land fewer than three years, a prior "
                    "land manager affidavit covers the gap.",
                    "Tres años de historial del campo — cultivo, sustancias aplicadas y la "
                    "fecha/nombre del último material prohibido — es el núcleo de la "
                    "elegibilidad § 205.202(b). Si manejó la tierra menos de tres años, una "
                    "declaración jurada del manejador anterior cubre el vacío.",
                ),
            ),
            questions=(
                Question(
                    key="crop_history",
                    kind="info",
                    label=text("Field history by year", "Historial del campo por año"),
                    embed="crop_history",
                    required=False,
                    nop_cite="§ 205.202(b)",
                ),
                Question(
                    # 2026-09-09 — read "certified organic by another certifier", which steered an
                    # operation renewing with its OWN certifier to "No — never certified" and left
                    # every pilot parcel reading like a first-time applicant's. CCOF F2, OTCO C2
                    # 2.1-7 and WSDA AGR 2264 ref 6 all ask it plainly; the answer now gates the
                    # certificate line below and is part of completion
                    # (`parcel_application_status`, key "certification_status").
                    key="currently_certified",
                    kind="radio",
                    label=text(
                        "Is this parcel currently certified organic?",
                        "¿Esta parcela está actualmente certificada como orgánica?",
                    ),
                    coaching=text(
                        "Answer for the parcel, whichever certifier holds the certificate — your own "
                        "included. A parcel already on your certificate is documented by that "
                        "certificate and a statement of no lapse; a parcel that is not needs the "
                        "36-month land history below.",
                        "Responde por la parcela, sea cual sea el certificador que tenga el certificado — el tuyo "
                        "incluido. Una parcela que ya figura en tu certificado se documenta con ese certificado y "
                        "una declaración de continuidad; una que no, necesita el historial de 36 meses de abajo.",
                    ),
                    options=(
                        Option(value="yes", label=text("Yes — currently certified", "Sí — certificada actualmente")),
                        Option(value="no", label=text("No — never certified", "No — nunca certificada")),
                        Option(
                            value="previously",
                            label=text(
                                "Not currently — but it was certified before",
                                "Actualmente no — pero estuvo certificada antes",
                            ),
                        ),
                    ),
                    nop_cite="§ 205.202(b)",
                    required=False,
                ),
                Question(
                    key="prior_certifier_name",
                    kind="text",
                    label=text("Current/previous certifier", "Certificador actual/anterior"),
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="one_of", value=["yes", "previously"]),),
                ),
                Question(
                    # OTCO C2 2.1-7 and WSDA AGR 2264 ref 6 ask for the certified OPERATION's name —
                    # it differs from this operation when the parcel is being taken over.
                    key="certified_operation_name",
                    kind="text",
                    label=text(
                        "Operation name on that certificate (if not this operation)",
                        "Nombre de la operación en ese certificado (si no es esta operación)",
                    ),
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="one_of", value=["yes", "previously"]),),
                ),
                Question(
                    # WSDA assigns its own site number and asks for it on AGR 2264 ref 6, AGR 2262 ref 5
                    # and AGR 2516; CCOF numbers parcels on the Client Profile Addendum and asks for it on
                    # the Crop Update (ORGB88). Worded generically: the number is whatever that agent gives.
                    key="prior_certificate_site_number",
                    kind="text",
                    label=text(
                        "Site or parcel number on that certificate or its client profile (if any)",
                        "Número de sitio o parcela en ese certificado o tu perfil de cliente (si lo hay)",
                    ),
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="one_of", value=["yes", "previously"]),),
                ),
                Question(
                    # WSDA AGR 2264 ref 6b: the whole previously or currently certified site, or a portion
                    # of it ("Ensure the attached map clearly illustrates the specific area of the site you
                    # will be managing"). Asked of any agent: a portion is a smaller certified area whoever
                    # certified it.
                    key="full_prior_site_area",
                    kind="radio",
                    label=text(
                        "Are you applying for the entire area of that certified site?",
                        "¿Solicitas el área completa de ese sitio certificado?",
                    ),
                    coaching=text(
                        "If only a portion, mark the area you will manage on the map in section E.",
                        "Si es solo una parte, marca en el mapa de la sección E el área que vas a manejar.",
                    ),
                    options=(
                        Option(value="entire", label=text("Yes, the entire site", "Sí, el sitio completo")),
                        Option(value="portion", label=text("No, only a portion of it", "No, solo una parte")),
                    ),
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="one_of", value=["yes", "previously"]),),
                ),
                Question(
                    # CCOF Crop Update (ORGB88) "Crop(s) (Current or planned within the next 12 months)"
                    # and WSDA AGR 2516 "your current plan for the coming year". A PLAN, so it is its own
                    # answer and never a land-history row: a future year typed into the history would
                    # print in the § 205.202(b) record as a crop grown (expert read of 2026-10-24).
                    key="planned_crops",
                    kind="textarea",
                    label=text(
                        "Crops planned on this parcel for the next 12 months (with acres for each if more than one)",
                        "Cultivos previstos en esta parcela para los próximos 12 meses (con las hectáreas o acres de "
                        "cada uno si hay más de uno)",
                    ),
                    required=False,
                    placeholder=text(
                        "e.g., Blueberries 12.5 ac; or Spinach 10 ac then Carrots 8.6 ac",
                        "p. ej., Arándanos 12.5 ac; o Espinaca 10 ac y luego Zanahoria 8.6 ac",
                    ),
                    visible_when=(Condition(question="currently_certified", op="eq", value="yes"),),
                ),
                Question(
                    # CCOF §G / OTCO 2.4-2 / WSDA 2264 ref 6: the operation's certificate of record,
                    # printed on the parcel's own page rather than the cover only.
                    key="certificate_card",
                    kind="info",
                    label=text("Certificate of record", "Certificado vigente"),
                    embed="certificate_of_record",
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="eq", value="yes"),),
                ),
                Question(
                    # CCOF §G(2) / OTCO 2.4-2: "verification of no lapse in organic management". An
                    # attestation the operator makes; unanswered prints nothing (absence stays absence).
                    key="no_lapse_attested",
                    kind="boolean",
                    label=text(
                        "There has been no lapse in organic management of this parcel since it was certified.",
                        "No ha habido interrupción del manejo orgánico de esta parcela desde que fue certificada.",
                    ),
                    nop_cite="§ 205.202(b)",
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="eq", value="yes"),),
                ),
                Question(
                    # OSP alignment audit T21-F1: what the selected agent's own form asks of a
                    # currently certified parcel, and what is on file for it. The card carries the
                    # two uploads; `certified_parcel_branch` decides the route and the states, and
                    # the PDF prints the same assessment.
                    key="certified_branch",
                    kind="info",
                    label=text(
                        "What your certifier's form asks for a certified parcel",
                        "Lo que pide el formulario de tu certificador para una parcela certificada",
                    ),
                    embed="certified_branch",
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="eq", value="yes"),),
                ),
                Question(
                    # "Referenced separately": the copy exists but is not uploaded here. Named, so a
                    # reviewer knows where to look; never read as attached.
                    key="certificate_reference",
                    kind="textarea",
                    label=text(
                        "If the certificate copy is kept elsewhere, say where",
                        "Si la copia del certificado se guarda en otro lugar, indica dónde",
                    ),
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="eq", value="yes"),),
                ),
                Question(
                    key="continuity_reference",
                    kind="textarea",
                    label=text(
                        "If the verification of no lapse (for example a letter from your certifier) is kept "
                        "elsewhere, say where",
                        "Si la verificación de continuidad (por ejemplo una carta de tu certificador) se guarda en "
                        "otro lugar, indica dónde",
                    ),
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="eq", value="yes"),),
                ),
                Question(
                    # CCOF F4 / OTCO 2.5-4: a genuinely clean tenure was a BLANK, not a statement.
                    # Printed as the current manager's declaration on the table below, and flagged
                    # there when a dated prohibited application inside the tenure contradicts it.
                    # It is about PROHIBITED material only; WSDA AGR 2264 ref 13's "no input
                    # materials applied" is the separate `no_inputs_within_tenure` below.
                    key="dlpm_none_within_tenure",
                    kind="boolean",
                    label=text(
                        "No prohibited material has been applied to this parcel since I began managing it.",
                        "No se ha aplicado ningún material prohibido a esta parcela desde que comencé a manejarla.",
                    ),
                    nop_cite="§ 205.202(b)",
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="one_of", value=["no", "previously"]),),
                ),
                Question(
                    # WSDA AGR 2264 ref 13's N/A: "No input materials have been applied while under my
                    # management" (OSP alignment audit T17-F2). Not the declaration above, which is
                    # about PROHIBITED material and is asked only of a parcel not currently certified:
                    # an operation can apply allowed inputs and truthfully answer that one Yes. Asked
                    # of every parcel. Unanswered prints as not stated; No is never read as "an input
                    # was applied", and Yes is flagged when a dated input event in the tenure says
                    # otherwise.
                    key="no_inputs_within_tenure",
                    kind="boolean",
                    label=text(
                        "No input materials of any kind (fertilizers, soil amendments, pest or disease "
                        "controls) have been applied to this parcel since I began managing it.",
                        "No se ha aplicado ningún insumo de ningún tipo (fertilizantes, enmiendas, control "
                        "de plagas o enfermedades) a esta parcela desde que comencé a manejarla.",
                    ),
                    nop_cite="§ 205.202(b)",
                    required=False,
                ),
                Question(
                    # CCOF ORGB49 F8: "Since the DLPM, have prohibited materials of any kind been applied
                    # to any parcel borders or portions of the parcel not submitted for certification
                    # (e.g. herbicides or other prohibited materials applied to blocks or lots associated
                    # with the same APN, or to land contained under the same CA pesticide use reporting
                    # site ID)?" Not `dlpm_none_within_tenure`, which is about the parcel applied for:
                    # this is the operator's OWN ground beside it, which no buffer row describes (a
                    # buffer row's dates are the neighbour's). Section F is skipped for a currently
                    # certified parcel (F2), so the same gate.
                    key="prohibited_on_excluded_ground",
                    kind="boolean",
                    label=text(
                        "Since the last prohibited material was applied to this parcel, have prohibited materials "
                        "been applied to its borders, or to any part of the same land not submitted for "
                        "certification (blocks on the same APN, or land under the same California pesticide use "
                        "reporting site ID)?",
                        "Desde la última aplicación de un material prohibido en esta parcela, ¿se han aplicado "
                        "materiales prohibidos en sus bordes o en alguna parte de la misma tierra que no se "
                        "presenta para certificación (bloques del mismo APN, o tierra bajo el mismo ID de sitio "
                        "de reporte de uso de pesticidas de California)?",
                    ),
                    nop_cite="§ 205.202(b)",
                    required=False,
                    visible_when=(Condition(question="currently_certified", op="one_of", value=["no", "previously"]),),
                ),
                Question(
                    # CCOF ORGB49 F8a: the materials, the application dates and a map of where.
                    key="prohibited_on_excluded_ground_detail",
                    kind="textarea",
                    label=text(
                        "Which materials, the dates they were applied, and where",
                        "Qué materiales, en qué fechas se aplicaron y dónde",
                    ),
                    coaching=text(
                        "Mark the places on the map in section E.",
                        "Marca los lugares en el mapa de la sección E.",
                    ),
                    required=False,
                    visible_when=(
                        Condition(question="currently_certified", op="one_of", value=["no", "previously"]),
                        Condition(question="prohibited_on_excluded_ground", op="truthy"),
                    ),
                ),
                Question(
                    key="affidavit_card",
                    kind="info",
                    label=text(
                        "Who has managed this parcel in the last 36 months",
                        "Quién ha manejado esta parcela en los últimos 36 meses",
                    ),
                    embed="landowner_affidavit",
                    required=False,
                    nop_cite="§ 205.202(b)",
                ),
                Question(
                    # USDA form #25 — the neighbour-signed attestation for a boundary. Counted
                    # on the same page as the prior-manager affidavit because a certifier
                    # looks for both together on new ground.
                    key="adjoining_affidavit_card",
                    kind="info",
                    label=text("Adjoining-land affidavits", "Declaraciones juradas de tierras colindantes"),
                    embed="adjoining_land_affidavit",
                    required=False,
                    nop_cite="§ 205.202(c)",
                ),
            ),
        ),
    ),
    repeat_per_parcel=True,
)
