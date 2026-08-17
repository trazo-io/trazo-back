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
            "El producto orgánico debe protegerse de la mezcla con producto no orgánico y "
            "del contacto con sustancias prohibidas en todo punto donde se guarda después "
            "de la cosecha — contenedores de campo, cámaras frías en la finca, "
            "almacenamiento seco o una instalación fuera de la finca. Las prácticas de "
            "almacenamiento y las barreras físicas que usa su operación deben describirse "
            "aquí para la revisión del agente certificador (§ 205.272).",
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
                    "Enumere todos los lugares donde se guarda el producto orgánico después "
                    "de la cosecha, incluido el almacenamiento temporal en contenedores de "
                    "campo. Seleccionar una ubicación compartida o de un tercero abre "
                    "preguntas adicionales abajo.",
                ),
            ),
            questions=(
                Question(
                    key="storage_locations",
                    kind="checkbox_group",
                    prefill=Prefill(source="storage_location_evidence"),
                    label=text(
                        "Where is your organic product stored after harvest?",
                        "¿Dónde se almacena su producto orgánico después de la cosecha?",
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
                        Option("other", text("Other (describe below)", "Otra (describa abajo)")),
                    ),
                ),
                Question(
                    key="storage_other_description",
                    kind="text",
                    label=text("Describe the other storage location", "Describa la otra ubicación de almacenamiento"),
                    visible_when=(Condition("storage_locations", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional storage location: {answer}."),
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
                        "Describa la separación física y el etiquetado que evitan la mezcla",
                    ),
                    coaching=text(
                        "Include physical barriers (dedicated bins, partition walls, separate "
                        "rooms) and how each container or space is labeled so organic product "
                        "is never mistaken for nonorganic product in the same location.",
                        "Incluya las barreras físicas (contenedores dedicados, paredes "
                        "divisorias, salas separadas) y cómo se etiqueta cada contenedor o "
                        "espacio para que el producto orgánico nunca se confunda con producto "
                        "no orgánico en la misma ubicación.",
                    ),
                    nop_cite="§ 205.272(a)",
                    visible_when=(Condition("storage_shared_with_nonorganic", "truthy"),),
                    compiles_to=CompileRule(
                        template="Physical separation and labeling preventing commingling: {answer}"
                    ),
                ),
                Question(
                    key="uncertified_facility_records",
                    kind="textarea",
                    label=text(
                        "What records does that facility provide to preserve your product's " "organic identity?",
                        "¿Qué registros proporciona esa instalación para preservar la identidad "
                        "orgánica de su producto?",
                    ),
                    coaching=text(
                        "An uncertified storage operation handling your product needs records "
                        "proving identity preservation — for example lot tags, logs showing "
                        "physical or timing separation from nonorganic product, and cleaning "
                        "records for the space or container used.",
                        "Una instalación de almacenamiento no certificada que maneja su "
                        "producto necesita registros que demuestren la preservación de la "
                        "identidad — por ejemplo etiquetas de lote, bitácoras que muestren "
                        "separación física o temporal del producto no orgánico, y registros de "
                        "limpieza del espacio o contenedor utilizado.",
                    ),
                    nop_cite="§ 205.103",
                    visible_when=(Condition("storage_locations", "includes", "uncertified_facility"),),
                    compiles_to=CompileRule(template="Records provided by the uncertified storage facility: {answer}"),
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
                        "Describa el método de limpieza e inspección",
                    ),
                    coaching=text(
                        "Note what is checked for (pest activity, residue from a prior "
                        "nonorganic lot, prohibited-substance residue) and who is responsible "
                        "for the check.",
                        "Indique qué se revisa (actividad de plagas, residuos de un lote no "
                        "orgánico anterior, residuos de sustancias prohibidas) y quién es "
                        "responsable de la revisión.",
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
                        "Los materiales corresponden a su Solicitud de Materiales, no aquí — "
                        "la jerarquía del § 205.271 (controles mecánicos y culturales primero) "
                        "aplica a las plagas de instalaciones igual que a las plagas de campo.",
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
                        "Las etiquetas de lote de Trazo y la ubicación de almacenamiento "
                        "registrada en sus registros de cosecha son la evidencia de esto — una "
                        "etiqueta de lote impresa que acompaña al producto durante el "
                        "almacenamiento mantiene su identidad intacta.",
                    ),
                    nop_cite="§ 205.272",
                    compiles_to=CompileRule(
                        template="Lot identity maintained through storage (bin cards, pallet tags): {answer}."
                    ),
                ),
            ),
        ),
    ),
)
