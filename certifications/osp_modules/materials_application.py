"""
Materials Application — the thin frame over Trazo's Approved Inputs registry.

Sources: 7 CFR 205.105 (allowed and prohibited substances, methods, and ingredients in
production and handling), 205.601 (synthetic substances allowed for use in organic crop
production — the National List), 205.206(e) (biological, botanical, or National List
substance use for pest, weed, and disease management). Two pages:

A. Your materials list — the body of this page IS the shipped Approved Inputs panel
   (`embed="approved_inputs"`): every fertilizer, pest/disease/weed material, and
   production aid the operation uses or plans to use, already verified against OMRI,
   WSDA, and the National List. This module collects no new material rows — the
   materials themselves are enumerated by the compiler from that registry's M2M
   relation, never from questionnaire answers.

B. Category attestations — one boolean per material category confirming the list above
   is complete for that category, plus a disclosure of any fumigant or other
   prohibited-material use on the land in the last three years, which bears on parcel
   eligibility (§ 205.202(b)).
"""

from .schema import CompileRule, Condition, Module, ModulePage, Prefill, Question, text

MATERIALS_APPLICATION = Module(
    key="materials_application",
    code="",
    title=text("Materials Application", "Solicitud de materiales"),
    # § 205.605 added 2026-09-12: post-harvest contact materials (wash-water additives,
    # sanitizers) are handling inputs under that section, not § 205.601, and the form's §D row
    # now has a category on the operator's own entries plus a printed block of its own.
    # § 205.605 removed 2026-09-12: it lists nonagricultural ingredients allowed in PROCESSED
    # products, and printing it at the head of a crop producer's materials list cited the handling
    # rule for field inputs. The §D post-harvest rows keep their own category.
    nop_cites=("§ 205.105", "§ 205.601", "§ 205.206(e)"),
    education=(
        text(
            "Trazo resolves each input material's name against OMRI, the WSDA Materials List "
            "and the National List, and shows what it found — your certifying agent is the one "
            "who approves what may be used on certified or transitional land (§ 205.105, "
            "§ 205.601). This module does not collect a new list: it points to the materials "
            "list you already maintain and asks you to confirm it is complete by category.",
            "Trazo resuelve el nombre de cada material de insumo contra OMRI, la Lista de "
            "Materiales de WSDA y la Lista Nacional, y muestra lo que encontró — tu agente "
            "certificador es quien aprueba lo que puede usarse en tierra certificada o en "
            "transición (§ 205.105, § 205.601). Este módulo no recopila una lista nueva: "
            "remite a la lista de materiales que ya mantienes y te pide confirmar que está "
            "completa por categoría.",
        ),
    ),
    allows_not_applicable=False,
    default_section_key="inputs_list",
    pages=(
        ModulePage(
            key="a_materials_list",
            title=text("A. Your materials list", "A. Tu lista de materiales"),
            education=(
                text(
                    "The materials list below is the single record of every input used on "
                    "this operation. Trazo resolves each entry against OMRI, the WSDA "
                    "Materials List and the National List and shows what it found to your "
                    "certifier — add or update materials there, not in this questionnaire.",
                    "La lista de materiales a continuación es el registro único de cada "
                    "insumo usado en esta operación. Trazo resuelve cada entrada contra "
                    "OMRI, la Lista de Materiales de WSDA y la Lista Nacional y le muestra a "
                    "tu certificador lo que encontró — agrega o actualiza materiales ahí, no "
                    "en este cuestionario.",
                ),
            ),
            questions=(
                Question(
                    key="materials_list_panel",
                    kind="info",
                    required=False,
                    label=text(
                        "Input materials on this plan",
                        "Materiales de insumo de este plan",
                    ),
                    coaching=text(
                        "List every fertilizer, pest, disease, or weed-control material and "
                        "production aid you use or plan to use. Trazo resolves each name "
                        "against OMRI, the WSDA Materials List and the National List and shows "
                        "the result; your certifier reviews the list and decides what is "
                        "approved for your operation.",
                        "Lista cada fertilizante, material para el control de plagas, "
                        "enfermedades o malezas, y cada auxiliar de producción que usas o "
                        "planeas usar. Trazo resuelve cada nombre contra OMRI, la Lista de "
                        "Materiales de WSDA y la Lista Nacional y muestra el resultado; tu "
                        "certificador revisa la lista y decide qué queda aprobado para tu "
                        "operación.",
                    ),
                    embed="approved_inputs",
                    nop_cite="§ 205.601",
                ),
                Question(
                    # OTCO C11 Hdr-2 "Not Applicable; no materials/inputs are used" and CCOF ORGB41
                    # Header C's per-section N/A. Until 2026-09-09 an operation with no inputs
                    # printed an empty list under "No input materials have been added…", which
                    # reads as unfinished, and then attested five times that everything in use
                    # was on it. This is the affirmative statement OTCO's checkbox makes; it is
                    # checked against the plan's rows and the logged applications on the PDF.
                    key="no_materials_used",
                    kind="boolean",
                    label=text(
                        "No input materials or substances are used or planned in the organic system",
                        "No se usa ni se planea usar ningún material o sustancia de insumo en el sistema orgánico",
                    ),
                    coaching=text(
                        "Only for an operation that applies nothing at all — no fertilizer, compost, "
                        "spray, adjuvant or post-harvest sanitizer. If you use anything, leave this "
                        "unchecked and complete the list above.",
                        "Solo para una operación que no aplica nada — ni fertilizante, compost, aspersión, "
                        "adyuvante ni sanitizante poscosecha. Si usas algo, déjalo sin marcar y completa la lista "
                        "de arriba.",
                    ),
                    nop_cite="§ 205.105",
                    required=False,
                    compiles_to=CompileRule(
                        template=(
                            "The operator states that no input materials or substances are used or "
                            "planned in the organic system ({answer})."
                        ),
                        template_false=(
                            "The operator states that input materials or substances are used or planned in "
                            "the organic system."
                        ),
                    ),
                ),
                Question(
                    key="materials_list_complete",
                    kind="boolean",
                    visible_when=(Condition("no_materials_used", "falsy"),),
                    label=text(
                        "Every input material I use or plan to use on organic land is entered in this list",
                        "Todo material de insumo que uso o planeo usar en tierra orgánica "
                        "está registrado en esta lista",
                    ),
                    coaching=text(
                        "Confirm this only after reviewing the panel above — add any missing material there first.",
                        "Confirma esto solo después de revisar el panel de arriba — agrega ahí primero cualquier "
                        "material faltante.",
                    ),
                    nop_cite="§ 205.105",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all input materials in use are "
                            "enumerated in the materials list on this plan ({answer})."
                        ),
                        template_false=(
                            "The operator does not attest that every input material in use is enumerated in "
                            "the materials list on this plan."
                        ),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_category_attestations",
            title=text("B. Category attestations", "B. Declaraciones por categoría"),
            visible_when=(Condition("no_materials_used", "falsy"),),
            education=(
                text(
                    "For each category, either state that you use no such materials or confirm "
                    "that every one you use is on the list above. A stated 'none used' is what "
                    "CCOF and OTCO ask for; a 'Yes' over an empty category reads like a complete "
                    "list.",
                    "Para cada categoría, declara que no usas ese tipo de materiales o confirma que todos los que "
                    "usas están en la lista de arriba. Un 'ninguno en uso' declarado es lo que CCOF y OTCO piden; "
                    "un 'Sí' sobre una categoría vacía se lee como una lista completa.",
                ),
            ),
            questions=(
                Question(
                    key="fertilizers_none_used",
                    kind="boolean",
                    label=text(
                        "No fertilizer or soil amendment materials are used or planned",
                        "No se usa ni se planea usar ningún fertilizante ni enmienda de suelo",
                    ),
                    nop_cite="§ 205.105",
                    required=False,
                    compiles_to=CompileRule(
                        template=(
                            "The operator states that no fertilizer or soil amendment materials are used or planned "
                            "({answer})."
                        ),
                        template_false=(
                            "The operator states that fertilizer or soil amendment materials are used or planned."
                        ),
                    ),
                ),
                Question(
                    key="fertilizers_listed",
                    kind="boolean",
                    visible_when=(Condition("fertilizers_none_used", "falsy"),),
                    prefill=Prefill(source="materials_category_evidence"),
                    label=text(
                        "All fertilizer and soil amendment materials I use or plan to use "
                        "are entered in the materials list above",
                        "Todo material fertilizante y enmienda de suelo que uso o planeo "
                        "usar está registrado en la lista de materiales de arriba",
                    ),
                    coaching=text(
                        "Include compost, manure, mined minerals, and any synthetic "
                        "fertilizer product — even ones already OMRI-listed — in the "
                        "materials list above.",
                        "Incluye compost, estiércol, minerales de mina y cualquier producto fertilizante sintético "
                        "— incluso los ya listados por OMRI — en la lista de materiales de arriba.",
                    ),
                    nop_cite="§ 205.105",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all fertilizer and soil amendment "
                            "materials in use are entered in the materials list on this plan "
                            "({answer})."
                        ),
                        template_false=(
                            "The operator does not attest that every fertilizer and soil amendment material "
                            "in use is entered in the materials list on this plan."
                        ),
                    ),
                ),
                Question(
                    key="pest_disease_weed_none_used",
                    kind="boolean",
                    label=text(
                        "No pest, disease or weed-control materials are used or planned",
                        "No se usa ni se planea usar ningún material para el control de plagas, enfermedades o malezas",
                    ),
                    nop_cite="§ 205.206(e)",
                    required=False,
                    compiles_to=CompileRule(
                        template=(
                            "The operator states that no pest, disease or weed-control materials are used or planned "
                            "({answer})."
                        ),
                        template_false=(
                            "The operator states that pest, disease or weed-control materials are used or planned."
                        ),
                    ),
                ),
                Question(
                    key="pest_disease_weed_listed",
                    kind="boolean",
                    visible_when=(Condition("pest_disease_weed_none_used", "falsy"),),
                    prefill=Prefill(source="materials_category_evidence"),
                    label=text(
                        "All pest, disease, and weed-control materials I use or plan to "
                        "use are entered in the materials list above",
                        "Todo material para el control de plagas, enfermedades o malezas "
                        "que uso o planeo usar está registrado en la lista de materiales "
                        "de arriba",
                    ),
                    coaching=text(
                        "Include biological, botanical, and synthetic pest, disease, or "
                        "weed-control materials, even if applied only occasionally.",
                        "Incluye materiales biológicos, botánicos y sintéticos para el control de plagas, "
                        "enfermedades o malezas, aunque se apliquen solo ocasionalmente.",
                    ),
                    nop_cite="§ 205.206(e)",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all pest, disease, and weed-control "
                            "materials in use are entered in the materials list on this plan "
                            "({answer})."
                        ),
                        template_false=(
                            "The operator does not attest that every pest, disease and weed-control "
                            "material in use is entered in the materials list on this plan."
                        ),
                    ),
                ),
                Question(
                    key="production_aids_none_used",
                    kind="boolean",
                    label=text(
                        "No production aids (adjuvants, wetting agents) are used or planned",
                        "No se usa ni se planea usar ningún auxiliar de producción (adyuvantes, agentes humectantes)",
                    ),
                    nop_cite="§ 205.601",
                    required=False,
                    compiles_to=CompileRule(
                        template=(
                            "The operator states that no production aid materials are used or planned ({answer})."
                        ),
                        template_false="The operator states that production aid materials are used or planned.",
                    ),
                ),
                Question(
                    key="production_aids_listed",
                    kind="boolean",
                    visible_when=(Condition("production_aids_none_used", "falsy"),),
                    label=text(
                        "All production aids (adjuvants, wetting agents) I use or plan to "
                        "use are entered in the materials list above",
                        "Todo auxiliar de producción (adyuvantes, agentes humectantes) que "
                        "uso o planeo usar está registrado en la lista de materiales de "
                        "arriba",
                    ),
                    coaching=text(
                        "Include adjuvants, wetting agents, spreader-stickers, and other "
                        "materials that help other products work, even when they touch "
                        "the crop only indirectly.",
                        "Incluye adyuvantes, agentes humectantes, adherentes-dispersantes y otros materiales que "
                        "ayudan a que otros productos funcionen, aunque toquen el cultivo solo de forma indirecta.",
                    ),
                    nop_cite="§ 205.601",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all production aids, including "
                            "adjuvants and wetting agents, in use are entered in the "
                            "materials list on this plan ({answer})."
                        ),
                        template_false=(
                            "The operator does not attest that every production aid, including adjuvants "
                            "and wetting agents, in use is entered in the materials list on this plan."
                        ),
                    ),
                ),
                Question(
                    key="post_harvest_contact_none_used",
                    kind="boolean",
                    label=text(
                        "No post-harvest contact materials (wash water additives, sanitizers) are used or planned",
                        "No se usa ni se planea usar ningún material de contacto poscosecha (aditivos del agua de lavado, sanitizantes)",
                    ),
                    nop_cite="§ 205.105",
                    required=False,
                    compiles_to=CompileRule(
                        template=(
                            "The operator states that no post-harvest contact materials are used or planned "
                            "({answer})."
                        ),
                        template_false=("The operator states that post-harvest contact materials are used or planned."),
                    ),
                ),
                Question(
                    key="post_harvest_contact_listed",
                    kind="boolean",
                    visible_when=(Condition("post_harvest_contact_none_used", "falsy"),),
                    prefill=Prefill(source="materials_category_evidence"),
                    label=text(
                        "All post-harvest contact materials (wash water additives, "
                        "sanitizers) I use or plan to use are entered in the materials "
                        "list above",
                        "Todo material de contacto poscosecha (aditivos del agua de "
                        "lavado, sanitizantes) que uso o planeo usar está registrado en "
                        "la lista de materiales de arriba",
                    ),
                    coaching=text(
                        "Include wash water additives, sanitizers, and any material that "
                        "contacts the harvested crop after it leaves the field.",
                        "Incluye aditivos del agua de lavado, sanitizantes y cualquier material que entre en "
                        "contacto con el cultivo cosechado después de salir del campo.",
                    ),
                    nop_cite="§ 205.105",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all post-harvest contact "
                            "materials, including wash water additives and sanitizers, "
                            "in use are entered in the materials list on this plan "
                            "({answer})."
                        ),
                        template_false=(
                            "The operator does not attest that every post-harvest contact material, "
                            "including wash water additives and sanitizers, in use is entered in the "
                            "materials list on this plan."
                        ),
                    ),
                ),
                Question(
                    key="fumigant_prohibited_material_used",
                    kind="boolean",
                    label=text(
                        "Has any fumigant or other prohibited material been used on this land in the last 3 years?",
                        "¿Se ha usado algún fumigante u otro material prohibido en esta "
                        "tierra en los últimos 3 años?",
                    ),
                    coaching=text(
                        "A prohibited substance applied to this land affects parcel eligibility (§ 205.202(b)).",
                        "Una sustancia prohibida aplicada en esta tierra afecta la "
                        "elegibilidad de la parcela (§ 205.202(b)).",
                    ),
                    nop_cite="§ 205.202(b)",
                    compiles_to=CompileRule(
                        template=(
                            "Fumigant or other prohibited-material use on this land in "
                            "the last three years: {answer}."
                        )
                    ),
                ),
                Question(
                    key="fumigant_prohibited_material_detail",
                    kind="textarea",
                    label=text(
                        "Describe the substance and the date it was applied",
                        "Describe la sustancia y la fecha en que se aplicó",
                    ),
                    coaching=text(
                        "Name the substance and the application date; list each "
                        "application separately if there was more than one.",
                        "Indica el nombre de la sustancia y la fecha de aplicación; enumera cada aplicación por "
                        "separado si hubo más de una.",
                    ),
                    visible_when=(Condition("fumigant_prohibited_material_used", "truthy"),),
                ),
            ),
        ),
    ),
)
