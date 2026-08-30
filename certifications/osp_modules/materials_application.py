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
            title=text("A. Your materials list", "A. Su lista de materiales"),
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
                    key="materials_list_complete",
                    kind="boolean",
                    label=text(
                        "Every input material I use or plan to use on organic land is " "entered in this list",
                        "Todo material de insumo que uso o planeo usar en tierra orgánica "
                        "está registrado en esta lista",
                    ),
                    coaching=text(
                        "Confirm this only after reviewing the panel above — add any " "missing material there first.",
                        "Confirme esto solo después de revisar el panel de arriba — agregue "
                        "ahí primero cualquier material faltante.",
                    ),
                    nop_cite="§ 205.105",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all input materials in use are "
                            "enumerated in the materials list on this plan ({answer})."
                        )
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_category_attestations",
            title=text("B. Category attestations", "B. Declaraciones por categoría"),
            education=(
                text(
                    "Confirm each category below against the materials list above. If a "
                    "category does not apply because you use no such materials, attest "
                    "'Yes' — there is nothing outstanding to add.",
                    "Confirme cada categoría a continuación con base en la lista de "
                    "materiales de arriba. Si una categoría no aplica porque no usa esos "
                    "materiales, declare 'Sí' — no hay nada pendiente por agregar.",
                ),
            ),
            questions=(
                Question(
                    key="fertilizers_listed",
                    kind="boolean",
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
                        "Incluya compost, estiércol, minerales de mina y cualquier producto "
                        "fertilizante sintético — incluso los ya listados por OMRI — en la "
                        "lista de materiales de arriba.",
                    ),
                    nop_cite="§ 205.105",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all fertilizer and soil amendment "
                            "materials in use are entered in the materials list on this plan "
                            "({answer})."
                        )
                    ),
                ),
                Question(
                    key="pest_disease_weed_listed",
                    kind="boolean",
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
                        "Incluya materiales biológicos, botánicos y sintéticos para el "
                        "control de plagas, enfermedades o malezas, aunque se apliquen "
                        "solo ocasionalmente.",
                    ),
                    nop_cite="§ 205.206(e)",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all pest, disease, and weed-control "
                            "materials in use are entered in the materials list on this plan "
                            "({answer})."
                        )
                    ),
                ),
                Question(
                    key="production_aids_listed",
                    kind="boolean",
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
                        "Incluya adyuvantes, agentes humectantes, adherentes-dispersantes "
                        "y otros materiales que ayudan a que otros productos funcionen, "
                        "aunque toquen el cultivo solo de forma indirecta.",
                    ),
                    nop_cite="§ 205.601",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all production aids, including "
                            "adjuvants and wetting agents, in use are entered in the "
                            "materials list on this plan ({answer})."
                        )
                    ),
                ),
                Question(
                    key="post_harvest_contact_listed",
                    kind="boolean",
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
                        "Incluya aditivos del agua de lavado, sanitizantes y cualquier "
                        "material que entre en contacto con el cultivo cosechado después "
                        "de salir del campo.",
                    ),
                    nop_cite="§ 205.105",
                    compiles_to=CompileRule(
                        template=(
                            "The operator attests that all post-harvest contact "
                            "materials, including wash water additives and sanitizers, "
                            "in use are entered in the materials list on this plan "
                            "({answer})."
                        )
                    ),
                ),
                Question(
                    key="fumigant_prohibited_material_used",
                    kind="boolean",
                    label=text(
                        "Has any fumigant or other prohibited material been used on " "this land in the last 3 years?",
                        "¿Se ha usado algún fumigante u otro material prohibido en esta "
                        "tierra en los últimos 3 años?",
                    ),
                    coaching=text(
                        "A prohibited substance applied to this land affects parcel " "eligibility (§ 205.202(b)).",
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
                        "Describa la sustancia y la fecha en que se aplicó",
                    ),
                    coaching=text(
                        "Name the substance and the application date; list each "
                        "application separately if there was more than one.",
                        "Indique el nombre de la sustancia y la fecha de aplicación; "
                        "enumere cada aplicación por separado si hubo más de una.",
                    ),
                    visible_when=(Condition("fumigant_prohibited_material_used", "truthy"),),
                ),
            ),
        ),
    ),
)
