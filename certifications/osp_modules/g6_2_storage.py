"""
G6.2 — Storage.

Sources: 7 CFR 205.272 (commingling and contact with prohibited substance prevention),
205.103 (recordkeeping by certified operations). Storage is the first point after harvest
where an organic lot can be commingled with nonorganic product or exposed to a prohibited
substance — this module covers every place product is held, how shared or third-party
space keeps organic identity intact, and how facility pest control stays inside the
§ 205.271 hierarchy (mechanical and cultural practices before materials).

Trazo already holds `storage_location` on harvest/post-harvest events (lot traceback) — the
only storage signal on record today. No prefill resolver exists yet for storage evidence, so
this module collects the operator's own answers directly.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Prefill, Question, text

G6_2_STORAGE = Module(
    key="g6_2_storage",
    code="G6.2",
    title=text("Storage", "Almacenamiento"),
    nop_cites=("§ 205.272", "§ 205.103"),
    education=(
        text(
            "Organic product must be protected from commingling with nonorganic product "
            "and from contact with prohibited substances at every point where it is held "
            "after harvest — field bins, on-farm coolers, dry storage, or a facility off "
            "the farm. The storage practices and physical barriers your operation uses "
            "must be described here for the certifying agent's review (§ 205.272).",
            "El producto orgánico debe protegerse de la mezcla con producto no orgánico y del contacto con "
            "sustancias prohibidas en todo punto donde se guarda después de la cosecha — contenedores de campo, "
            "cámaras frías en la finca, almacenamiento seco o una instalación fuera de la finca. Las prácticas de "
            "almacenamiento y las barreras físicas que usa tu operación deben describirse aquí para la revisión del "
            "agente certificador (§ 205.272).",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — product is never stored; it is sold and shipped directly from " "the field.",
        "No aplica — el producto nunca se almacena; se vende y se envía directamente " "desde el campo.",
    ),
    default_section_key="commingling_barriers",
    pages=(
        ModulePage(
            key="a_storage_locations",
            title=text("A. Where product is stored", "A. Dónde se almacena el producto"),
            education=(
                text(
                    "List every place organic product is held after harvest, including "
                    "short-term staging in field bins. Selecting a shared or third-party "
                    "location opens additional questions below.",
                    "Enumera todos los lugares donde se guarda el producto orgánico después de la cosecha, incluido "
                    "el almacenamiento temporal en contenedores de campo. Seleccionar una ubicación compartida o de "
                    "un tercero abre preguntas adicionales abajo.",
                ),
            ),
            questions=(
                Question(
                    key="storage_locations",
                    kind="checkbox_group",
                    prefill=Prefill(source="storage_location_evidence"),
                    label=text(
                        "Where is your organic product stored after harvest?",
                        "¿Dónde se almacena tu producto orgánico después de la cosecha?",
                    ),
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(template="Organic product is stored in: {answer}."),
                    options=(
                        Option("on_farm_cold", text("On-farm cold storage", "Almacenamiento frío en la finca")),
                        Option("on_farm_dry", text("On-farm dry storage", "Almacenamiento seco en la finca")),
                        Option("bins_silos", text("Bins or silos", "Contenedores o silos")),
                        Option(
                            "commercial_cold_off_farm",
                            text(
                                "Commercial cold storage off-farm",
                                "Almacenamiento frío comercial fuera de la finca",
                            ),
                        ),
                        Option(
                            "certified_handler",
                            text("Certified handler's facility", "Instalación de manejador certificado"),
                        ),
                        Option(
                            "uncertified_facility",
                            text("Uncertified storage facility", "Instalación de almacenamiento no certificada"),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                # OTCO C7 7.7-1 and CCOF G6.2 A1: whether the operation still owns the crop while it sits in someone
                # else's storage. OTCO uses it to decide whether 7.7 applies; CCOF opens section A on it (2026.12.02).
                Question(
                    key="owns_crop_in_storage",
                    kind="radio",
                    required=False,
                    label=text(
                        "Do you still own the crop while it is stored at a facility you do not operate?",
                        "¿El cultivo sigue siendo tuyo mientras está almacenado en una instalación que no operas?",
                    ),
                    coaching=text(
                        "Answer No if ownership passes to the buyer or the facility when the crop is delivered there.",
                        "Responde No si la propiedad pasa al comprador o a la instalación al entregar el cultivo.",
                    ),
                    nop_cite="§ 205.100(a)",
                    visible_when=(
                        Condition(
                            "storage_locations",
                            "includes_any",
                            ["commercial_cold_off_farm", "certified_handler", "uncertified_facility"],
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="The operation owns the crop while it is in off-farm storage: {answer}.",
                        section_key="commingling_barriers",
                    ),
                    options=(
                        Option("yes", text("Yes, we still own it there", "Sí, sigue siendo nuestro")),
                        Option(
                            "no",
                            text(
                                "No, ownership passes when it is delivered",
                                "No, la propiedad pasa al entregarlo",
                            ),
                        ),
                    ),
                ),
                Question(
                    key="storage_other_description",
                    kind="text",
                    label=text("Describe the other storage location", "Describe la otra ubicación de almacenamiento"),
                    visible_when=(Condition("storage_locations", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional storage location: {answer}."),
                ),
                # WSDA AGR 2121 §K3. Sealed, impermeable packages protect the crop by themselves; anything
                # else is a room or an area, and §K3a/§K3b ask how it is kept organic and what shows it.
                Question(
                    key="stored_in_sealed_packaging",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Is all the organic product you store kept in sealed, impermeable packages?",
                        "¿Todo el producto orgánico que almacenas está en empaques sellados e impermeables?",
                    ),
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(
                        template="All stored organic product is kept in sealed, impermeable packages: {answer}."
                    ),
                ),
                # WSDA §K3a, its options as the form prints them.
                Question(
                    key="unsealed_storage_controls",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "How is organic product that is not in sealed packages kept from prohibited substances "
                        "and from non-organic product in storage? Check all that apply.",
                        "¿Cómo proteges el producto orgánico que no está en empaques sellados de las sustancias "
                        "prohibidas y del producto no orgánico durante el almacenamiento? Marca todas las que "
                        "correspondan.",
                    ),
                    nop_cite="§ 205.272",
                    visible_when=(Condition("stored_in_sealed_packaging", "eq", False),),
                    compiles_to=CompileRule(
                        template="Organic product not in sealed packages is protected in storage by: {answer}."
                    ),
                    options=(
                        Option(
                            "rooms_permanently_dedicated",
                            text(
                                "It is stored in rooms permanently dedicated to organic product",
                                "Se almacena en cuartos dedicados de forma permanente al producto orgánico",
                            ),
                        ),
                        Option(
                            "rooms_dedicated_for_season",
                            text(
                                "It is stored in rooms cleaned and dedicated to organic product for the whole season",
                                "Se almacena en cuartos limpiados y dedicados al producto orgánico toda la temporada",
                            ),
                        ),
                        Option(
                            "areas_with_organic_signage",
                            text(
                                "It is stored in areas or on shelves marked with organic signage",
                                "Se almacena en áreas o estantes señalizados como orgánicos",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="unsealed_storage_controls_other",
                    kind="text",
                    label=text("Describe the other way", "Describe la otra forma"),
                    visible_when=(
                        Condition("stored_in_sealed_packaging", "eq", False),
                        Condition("unsealed_storage_controls", "includes", "other"),
                    ),
                    compiles_to=CompileRule(template="Other storage protection: {answer}."),
                ),
                # WSDA §K3b.
                Question(
                    key="storage_location_records",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "What records show where organic product is stored and how the area was cleaned for it? "
                        "Check all that apply.",
                        "¿Qué registros muestran dónde se almacena el producto orgánico y cómo se limpió el área "
                        "para recibirlo? Marca todas las que correspondan.",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("stored_in_sealed_packaging", "eq", False),),
                    compiles_to=CompileRule(
                        template="Records showing where organic product is stored and how the area was cleaned: "
                        "{answer}."
                    ),
                    options=(
                        Option(
                            "storage_location_on_harvest_records",
                            text(
                                "The storage location written on harvest or post-harvest records",
                                "La ubicación de almacenamiento anotada en los registros de cosecha o poscosecha",
                            ),
                            evidence="storage_location_entries",
                        ),
                        Option(
                            "storage_cleaning_log",
                            text(
                                "A cleaning log for storage areas or coolers",
                                "Un registro de limpieza de las áreas de almacenamiento o cámaras frías",
                            ),
                            evidence="storage_area_cleanouts",
                        ),
                        Option("other", text("Other (describe below)", "Otros (describe abajo)")),
                    ),
                ),
                Question(
                    key="storage_location_records_other",
                    kind="text",
                    label=text("Describe the other records", "Describe los otros registros"),
                    visible_when=(
                        Condition("stored_in_sealed_packaging", "eq", False),
                        Condition("storage_location_records", "includes", "other"),
                    ),
                    compiles_to=CompileRule(template="Other storage records: {answer}."),
                ),
                Question(
                    key="storage_shared_with_nonorganic",
                    kind="boolean",
                    label=text(
                        "Is any storage location shared with nonorganic product?",
                        "¿Alguna ubicación de almacenamiento se comparte con producto no orgánico?",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(template="Storage shared with nonorganic product: {answer}."),
                ),
                Question(
                    key="storage_shared_separation",
                    kind="textarea",
                    label=text(
                        "Describe the physical separation and labeling that prevents commingling",
                        "Describe la separación física y el etiquetado que evitan la mezcla",
                    ),
                    coaching=text(
                        "Include physical barriers (dedicated bins, partition walls, separate "
                        "rooms) and how each container or space is labeled so organic product "
                        "is never mistaken for nonorganic product in the same location.",
                        "Incluye las barreras físicas (contenedores dedicados, paredes divisorias, salas separadas) "
                        "y cómo se etiqueta cada contenedor o espacio para que el producto orgánico nunca se "
                        "confunda con producto no orgánico en la misma ubicación.",
                    ),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("storage_shared_with_nonorganic", "truthy"),),
                    compiles_to=CompileRule(
                        template="Physical separation and labeling preventing commingling: {answer}"
                    ),
                ),
                # CCOF G6.2 §B2b, asked where CCOF asks it: once storage is shared.
                Question(
                    key="organic_storage_area_identification",
                    kind="textarea",
                    required=False,
                    label=text(
                        "How are organic storage areas marked?",
                        "¿Cómo se señalan las áreas de almacenamiento orgánico?",
                    ),
                    coaching=text(
                        "For example signs on the door or the rack, a painted floor area, or a room used only for "
                        "organic product.",
                        "Por ejemplo, letreros en la puerta o en el estante, un área del piso pintada, o un cuarto "
                        "que se usa solo para producto orgánico.",
                    ),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("storage_shared_with_nonorganic", "truthy"),),
                    compiles_to=CompileRule(template="How organic storage areas are marked: {answer}"),
                ),
                Question(
                    key="uncertified_facility_records",
                    kind="textarea",
                    label=text(
                        "What records does that facility provide to preserve your product's " "organic identity?",
                        "¿Qué registros proporciona esa instalación para preservar la identidad orgánica de tu "
                        "producto?",
                    ),
                    coaching=text(
                        "An uncertified storage operation handling your product needs records "
                        "proving identity preservation — for example lot tags, logs showing "
                        "physical or timing separation from nonorganic product, and cleaning "
                        "records for the space or container used.",
                        "Una instalación de almacenamiento no certificada que maneja tu producto necesita registros "
                        "que demuestren la preservación de la identidad — por ejemplo etiquetas de lote, bitácoras "
                        "que muestren separación física o temporal del producto no orgánico, y registros de "
                        "limpieza del espacio o contenedor utilizado.",
                    ),
                    nop_cite="§ 205.103",
                    # CCOF G6.2 A1 "No, skip to section B" / OTCO C7 7.7-1: a crop no longer owned in storage closes
                    # this section. Only an explicit No closes it: an unanswered ownership question leaves it open, so
                    # no stored plan loses what it shows (review of back #369).
                    visible_when=(
                        Condition("storage_locations", "includes", "uncertified_facility"),
                        # Repeats owns_crop_in_storage's own gate, the chained-gates convention.
                        Condition(
                            "storage_locations",
                            "includes_any",
                            ["commercial_cold_off_farm", "certified_handler", "uncertified_facility"],
                        ),
                        Condition("owns_crop_in_storage", "ne", "no"),
                    ),
                    compiles_to=CompileRule(template="Records provided by the uncertified storage facility: {answer}"),
                ),
                # CCOF G6.2 A2 asks for an affidavit the uncertified facility's manager signs, and OTCO
                # C7 7.7-2 for the sheet that manager signs: the facility's own statement, which the
                # grower's description above cannot stand in for.
                Question(
                    key="uncertified_facility_statement_upload",
                    kind="upload",
                    label=text(
                        "Attach the statement the facility's manager signed",
                        "Adjunta la declaración firmada por el encargado de la instalación",
                    ),
                    coaching=text(
                        "Your certifier's form for an uncertified storage facility, signed by the person who "
                        "runs it: for example an exempt handler affidavit or an independent storage sheet.",
                        "El formulario de tu certificadora para una instalación de almacenamiento no certificada, "
                        "firmado por quien la dirige: por ejemplo una declaración de manejador exento o una hoja "
                        "de almacenamiento independiente.",
                    ),
                    required=False,
                    nop_cite="§ 205.103",
                    # CCOF G6.2 A1 "No, skip to section B" / OTCO C7 7.7-1: a crop no longer owned in storage closes
                    # this section. Only an explicit No closes it: an unanswered ownership question leaves it open, so
                    # no stored plan loses what it shows (review of back #369).
                    visible_when=(
                        Condition("storage_locations", "includes", "uncertified_facility"),
                        # Repeats owns_crop_in_storage's own gate, the chained-gates convention.
                        Condition(
                            "storage_locations",
                            "includes_any",
                            ["commercial_cold_off_farm", "certified_handler", "uncertified_facility"],
                        ),
                        Condition("owns_crop_in_storage", "ne", "no"),
                    ),
                ),
                # WSDA K1 asks whether a THIRD PARTY is contracted to store the crop, which
                # none of the location options above can answer: "commercial cold storage
                # off-farm" reads the same whether the operation rents the unit itself or
                # another business stores for it, and only the second puts the crop inside
                # someone else's records.
                Question(
                    key="third_party_storage_contracted",
                    kind="boolean",
                    label=text(
                        "Do you contract another operation to store your organic product?",
                        "¿Contratas a otra operación para almacenar tu producto orgánico?",
                    ),
                    nop_cite="\u00a7 205.272(a)",
                    visible_when=(
                        Condition(
                            "storage_locations",
                            "includes_any",
                            ["commercial_cold_off_farm", "certified_handler", "uncertified_facility"],
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="Organic product is stored by another operation under contract: {answer}."
                    ),
                ),
                # OTCO C7 7.7-2 lists every storage facility with its documentation class; the operation's own
                # are OWN. The same records G6.4 §B lists (2026-11-07).
                Question(
                    key="on_farm_storage_table",
                    kind="info",
                    required=False,
                    embed="on_farm_facilities",
                    label=text(
                        "Your own storage facilities",
                        "Tus propias instalaciones de almacenamiento",
                    ),
                    coaching=text(
                        "Add each storage facility you run yourself with its name and full address, and attach "
                        "its layout. Your own certificate covers it, so no certificate is asked.",
                        "Agrega cada instalación de almacenamiento que operas tú con su nombre y dirección "
                        "completa, y adjunta su plano. Tu propio certificado la cubre, así que no se pide "
                        "certificado.",
                    ),
                    nop_cite="\u00a7 205.272(a)",
                    visible_when=(
                        Condition("storage_locations", "includes_any", ["on_farm_cold", "on_farm_dry", "bins_silos"]),
                    ),
                ),
                # Selecting `certified_handler` used to open nothing at all, so the plan named
                # a facility class and never the facility — while CCOF G6.2 \u00a7A's attachment is
                # mandatory the moment that box is ticked. Same records, same embed as G6.1 \u00a7D.
                Question(
                    key="off_farm_storage_table",
                    kind="info",
                    required=False,
                    embed="post_harvest_facilities",
                    label=text(
                        "Storage facilities on file for this operation",
                        "Instalaciones de almacenamiento registradas para esta operaci\u00f3n",
                    ),
                    coaching=text(
                        "These are the facilities recorded on your farm profile, with their "
                        "address and organic certificate. A facility that both stores and "
                        "handles your crop appears here and on G6.1 \u00a7D \u2014 it is one record.",
                        "Estas son las instalaciones registradas en el perfil de tu finca, con su dirección y su "
                        "certificado orgánico. Una instalación que almacena y además manipula tu cultivo aparece "
                        "aquí y en G6.1 §D — es un solo registro.",
                    ),
                    nop_cite="\u00a7 205.272(a)",
                    visible_when=(
                        Condition(
                            "storage_locations",
                            "includes_any",
                            ["commercial_cold_off_farm", "certified_handler", "uncertified_facility"],
                        ),
                        Condition("owns_crop_in_storage", "ne", "no"),
                    ),
                ),
            ),
        ),
        ModulePage(
            key="b_conditions_pest_control",
            title=text(
                "B. Storage conditions & pest control",
                "B. Condiciones de almacenamiento y control de plagas",
            ),
            questions=(
                Question(
                    key="storage_cleaned_before_organic",
                    kind="boolean",
                    label=text(
                        "Are storage areas cleaned and inspected before organic product enters?",
                        "¿Las áreas de almacenamiento se limpian e inspeccionan antes de que "
                        "ingrese el producto orgánico?",
                    ),
                    nop_cite="§ 205.272(a)",
                    compiles_to=CompileRule(
                        template="Storage areas cleaned and inspected before organic product enters: {answer}."
                    ),
                ),
                Question(
                    key="storage_cleaning_method",
                    kind="textarea",
                    label=text(
                        "Describe the cleaning and inspection method",
                        "Describe el método de limpieza e inspección",
                    ),
                    coaching=text(
                        "Note what is checked for (pest activity, residue from a prior "
                        "nonorganic lot, prohibited-substance residue) and who is responsible "
                        "for the check.",
                        "Indica qué se revisa (actividad de plagas, residuos de un lote no orgánico anterior, "
                        "residuos de sustancias prohibidas) y quién es responsable de la revisión.",
                    ),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("storage_cleaned_before_organic", "truthy"),),
                    compiles_to=CompileRule(template="Cleaning and inspection method for storage areas: {answer}"),
                ),
                Question(
                    key="storage_pest_control_materials_used",
                    kind="boolean",
                    label=text(
                        "Are pest control materials used in storage areas?",
                        "¿Se usan materiales de control de plagas en las áreas de almacenamiento?",
                    ),
                    coaching=text(
                        "Materials belong on your Materials Application, not here — the "
                        "§ 205.271 hierarchy (mechanical and cultural controls first) applies "
                        "to facility pests the same way it applies to field pests.",
                        "Los materiales corresponden a tu Solicitud de Materiales, no aquí — la jerarquía del § "
                        "205.271 (controles mecánicos y culturales primero) aplica a las plagas de instalaciones "
                        "igual que a las plagas de campo.",
                    ),
                    nop_cite="§ 205.271",
                    compiles_to=CompileRule(template="Pest control materials used in storage areas: {answer}."),
                ),
                Question(
                    key="storage_pest_control_materials_description",
                    kind="textarea",
                    label=text(
                        "Which materials are used, and how is contact with product prevented?",
                        "¿Qué materiales se usan y cómo se evita el contacto con el producto?",
                    ),
                    nop_cite="§ 205.271",
                    visible_when=(Condition("storage_pest_control_materials_used", "truthy"),),
                    compiles_to=CompileRule(template="Storage pest control materials and contact prevention: {answer}"),
                ),
                Question(
                    key="lot_identity_maintained",
                    kind="boolean",
                    label=text(
                        "Does every stored lot keep its lot identity (bin cards, pallet tags)?",
                        "¿Cada lote almacenado conserva su identidad de lote (tarjetas de "
                        "contenedor, etiquetas de pallet)?",
                    ),
                    coaching=text(
                        "Trazo lot tags and the storage location recorded on your harvest "
                        "records are the evidence for this — a printed lot tag that stays "
                        "with the product through storage keeps its identity intact.",
                        "Las etiquetas de lote de Trazo y la ubicación de almacenamiento registrada en tus "
                        "registros de cosecha son la evidencia de esto — una etiqueta de lote impresa que acompaña "
                        "al producto durante el almacenamiento mantiene su identidad intacta.",
                    ),
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(
                        template="Lot identity maintained through storage (bin cards, pallet tags): {answer}."
                    ),
                ),
                # 2026-11-15: OTCO C12 12.2-7 asks the crop inventory system and how often inventory is taken. Nothing
                # asked it; the storage module owns the stored product.
                Question(
                    key="inventory_system_description",
                    kind="textarea",
                    required=False,
                    label=text(
                        "How do you keep track of the crop you have on hand?",
                        "¿Cómo llevas el control del cultivo que tienes en existencia?",
                    ),
                    placeholder=text(
                        "e.g. each bin is counted onto a storage sheet by lot as it goes into the cooler and counted "
                        "off as it ships; the sheet is reconciled with the harvest and sales records",
                        "p. ej. cada contenedor se anota por lote en una hoja de almacenamiento al entrar a la cámara y "
                        "se descuenta al despacharse; la hoja se concilia con los registros de cosecha y de venta",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(template="Crop inventory system: {answer}"),
                ),
                Question(
                    key="inventory_frequency",
                    kind="radio",
                    required=False,
                    label=text(
                        "How often is inventory taken and recorded?",
                        "¿Con qué frecuencia se toma y registra el inventario?",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    compiles_to=CompileRule(template="Inventory is taken and recorded: {answer}."),
                    options=(
                        Option(
                            "per_movement",
                            text("Every time product moves in or out", "Cada vez que el producto entra o sale"),
                        ),
                        Option("weekly", text("Weekly", "Semanalmente")),
                        Option("monthly", text("Monthly", "Mensualmente")),
                        Option("seasonal", text("Once a season", "Una vez por temporada")),
                        Option("annual", text("Once a year", "Una vez al año")),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="inventory_frequency_other",
                    kind="text",
                    required=False,
                    label=text("How often, then?", "¿Con qué frecuencia, entonces?"),
                    visible_when=(Condition("inventory_frequency", "eq", "other"),),
                    compiles_to=CompileRule(template="Inventory is taken and recorded: {answer}."),
                ),
            ),
        ),
    ),
)
