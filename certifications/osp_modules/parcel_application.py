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
            "El certificador evalúa cada parcela por separado: dónde está, qué se cultivó en "
            "los últimos tres años, qué la rodea y cómo se previene la deriva. Responda una "
            "vez aquí — los mismos registros alimentan su expediente de auditoría y su "
            "paquete de renovación.",
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
                    label=text("Describe the treated lumber", "Describa la madera tratada"),
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
                        "¿Cuándo comenzó a manejar esta parcela?",
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
                        "Describa el ganado y el manejo del estiércol",
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
                    "Para cada límite con tierra convencional o de uso prohibido, registre "
                    "el uso colindante, el tipo y ancho del amortiguamiento, y qué crece en "
                    "él — el cultivo del amortiguamiento nunca puede venderse como orgánico "
                    "(§ 205.202(c)).",
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
                    "El certificador requiere un mapa con límites, amortiguamientos y usos "
                    "colindantes. Trazo lo genera desde sus límites de parcela y registros "
                    "de amortiguamiento — dibuje el límite una vez y el mapa se mantiene al "
                    "día.",
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
                    key="currently_certified",
                    kind="radio",
                    label=text(
                        "Is this parcel currently certified organic by another certifier?",
                        "¿Esta parcela está actualmente certificada como orgánica por otro certificador?",
                    ),
                    options=(
                        Option(value="no", label=text("No — never certified", "No — nunca certificada")),
                        Option(value="yes", label=text("Yes", "Sí")),
                        Option(
                            value="previously",
                            label=text(
                                "Not currently — but it was certified before",
                                "Actualmente no — pero estuvo certificada antes",
                            ),
                        ),
                    ),
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
                    key="affidavit_card",
                    kind="info",
                    label=text("Prior land manager affidavit", "Declaración jurada del manejador anterior"),
                    embed="landowner_affidavit",
                    required=False,
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
