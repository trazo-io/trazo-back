"""
G7.0 — Labeling.

Sources: 7 CFR 205.300 (labeling, general — the word "organic" may identify only certified
product), 205.303 (packaged products labeled "100 percent organic" or "organic" — certifying
agent identification required), 205.307 (nonretail container labeling — lot identification
carried on the container or the accompanying shipping documents), 205.311 (USDA seal —
optional, separately regulated). Topic order follows the public Common OSP grower template;
all wording authored for Trazo.

For a raw-crop grower the operative split is consumer-facing labels, which must name the
certifying agent, versus bulk/wholesale shipments, which carry organic identity on container
markings or shipping paperwork instead of a printed label. The two pages below follow that
split:

A. How product leaves the farm — the packaging/marking method(s) in use, with the
   certifying-agent statement, seal, and label-file questions gated behind consumer
   packaging.
B. Documents & claims — the paperwork and lot linkage that carry organic identity for
   everything that is not a consumer label, plus who reviews new claims before they ship.
"""

from .schema import CompileRule, Condition, Module, ModulePage, Option, Question, text

G7_0_LABELING = Module(
    key="g7_0_labeling",
    code="G7.0",
    title=text("Labeling", "Etiquetado"),
    # § 205.311 added 2026-08-22: this module already ASKS whether the USDA seal appears on
    # the label, and the seal has its own section governing its form and who may apply it.
    # Asking the question while citing four neighbouring sections and not that one left the
    # only rule the answer is judged against uncited.
    nop_cites=("§ 205.300", "§ 205.301", "§ 205.303", "§ 205.307", "§ 205.311"),
    education=(
        text(
            'The word "organic" may identify only product that is certified organic (§ 205.300); a '
            "consumer-facing label carrying that word must also name the certifying agent — for "
            'example, "Certified organic by [certifying agent name]" (§ 205.303). Product that '
            "leaves the farm in bulk, without a consumer label, carries its organic identity on the "
            "shipping documents or the container markings instead, tied to a lot number (§ 205.307). "
            "The USDA organic seal is optional on any label and is separately regulated.",
            'La palabra "orgánico" solo puede identificar producto certificado orgánico (§ 205.300); '
            "una etiqueta dirigida al consumidor que lleve esa palabra también debe identificar al "
            'agente certificador — por ejemplo, "Certificado orgánico por [nombre del agente '
            'certificador]" (§ 205.303). El producto que sale de la finca a granel, sin etiqueta al '
            "consumidor, lleva su identidad orgánica en los documentos de envío o en las marcas del "
            "contenedor, vinculada a un número de lote (§ 205.307). El sello orgánico del USDA es "
            "opcional en cualquier etiqueta y está regulado por separado.",
        ),
    ),
    allows_not_applicable=True,
    na_label=text(
        "Not applicable — product is sold unlabeled in bulk, and its organic identity is carried "
        "only on sales documents (invoices, bills of lading), never on a printed label or a "
        "container marking.",
        "No aplica — el producto se vende a granel sin etiquetar, y su identidad orgánica se "
        "mantiene únicamente en los documentos de venta (facturas, cartas de porte), nunca en una "
        "etiqueta impresa ni en una marca del contenedor.",
    ),
    default_section_key="commingling_barriers",
    pages=(
        ModulePage(
            key="a_product_form",
            title=text("A. How product leaves the farm", "A. Cómo sale el producto de la finca"),
            education=(
                text(
                    "List every way organic product leaves this operation — many operations use more "
                    "than one depending on the buyer. Selecting consumer-ready packaging opens the "
                    "certifying-agent and seal questions below; bulk and wholesale shipments are "
                    "instead covered by the documents questions in section B.",
                    "Indica cada forma en que el producto orgánico sale de esta operación — muchas operaciones usan "
                    "más de una según el comprador. Marcar el empaque listo para el consumidor activa las preguntas "
                    "sobre el agente certificador y el sello, más abajo; los envíos a granel y mayoristas se cubren "
                    "en cambio con las preguntas sobre documentos de la sección B.",
                ),
            ),
            questions=(
                Question(
                    key="product_leaves_as",
                    kind="checkbox_group",
                    label=text(
                        "How does organic product leave this operation?",
                        "¿Cómo sale el producto orgánico de esta operación?",
                    ),
                    nop_cite="§ 205.300",
                    compiles_to=CompileRule(template="Organic product leaves this operation as: {answer}."),
                    options=(
                        Option(
                            "consumer_packaging",
                            text(
                                "Consumer-ready packaging with a printed organic label",
                                "Empaque listo para el consumidor con etiqueta orgánica impresa",
                            ),
                        ),
                        Option(
                            "bulk_bins_marked",
                            text(
                                "Bulk bins or totes with container markings (no consumer label)",
                                "Bins o contenedores a granel con marcas en el envase (sin etiqueta al " "consumidor)",
                            ),
                        ),
                        Option(
                            "unlabeled_bulk_documents",
                            text(
                                "Unlabeled bulk — organic identity carried on invoices or bills of " "lading only",
                                "A granel sin etiquetar — identidad orgánica solo en facturas o cartas " "de porte",
                            ),
                            # Kept as an answer: it can be true, and the operator must be able to say so.
                            # The register's fix (ccof/forms/G7.0-labeling.yaml A1) is a notice and a
                            # review line, never a refusal.
                            review=(
                                "Some organic product leaves in nonretail containers that carry no organic "
                                "identification. Nonretail containers must identify the product as organic "
                                "(§ 205.307(a)(1)), unless they hold retail-packaged product whose organic "
                                "label is visible (§ 205.307(c))."
                            ),
                        ),
                        Option(
                            "buyer_label",
                            text(
                                "Sold under the buyer's own label (private label or repack)",
                                "Vendido bajo la etiqueta propia del comprador (marca privada o " "reempaque)",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                    ),
                ),
                Question(
                    key="product_leaves_as_other",
                    kind="text",
                    label=text(
                        "Describe the other way product leaves the operation",
                        "Describe la otra forma en que el producto sale de la operación",
                    ),
                    visible_when=(Condition("product_leaves_as", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional product form: {answer}."),
                ),
                # Write-time notice for the answer above (decision 7 of the harvest coverage plan). An
                # `info` question renders its label and coaching and stores nothing.
                Question(
                    key="unlabeled_bulk_notice",
                    kind="info",
                    required=False,
                    label=text(
                        "Bulk containers need an organic marking",
                        "Los contenedores a granel necesitan una marca orgánica",
                    ),
                    coaching=text(
                        "Bins, totes, trailers and other containers used to ship or store organic product must "
                        'identify it as organic ("organic", "ORG" or similar) and carry a lot number or other '
                        "identifier that links to your records (§ 205.307(a)). Invoices alone do not meet this. "
                        "The one exception is a container holding retail packages whose organic label shows "
                        "through it (§ 205.307(c)). Your plan says what you do today, and the packet shows this "
                        "answer to your certifier for review.",
                        "Los bins, contenedores, remolques y demás envases usados para enviar o almacenar producto "
                        'orgánico deben identificarlo como orgánico ("organic", "ORG" o similar) y llevar un número '
                        "de lote u otro identificador que se vincule con tus registros (§ 205.307(a)). Las facturas "
                        "solas no cumplen con esto. La única excepción es un envase que contiene empaques al por "
                        "menor cuya etiqueta orgánica se ve a través de él (§ 205.307(c)). Tu plan dice lo que haces "
                        "hoy, y el paquete muestra esta respuesta a tu certificador para su revisión.",
                    ),
                    nop_cite="§ 205.307",
                    visible_when=(Condition("product_leaves_as", "includes", "unlabeled_bulk_documents"),),
                ),
                # § 205.301 defines four labeling categories and § 205.103(b)(3) requires the
                # records to IDENTIFY the product by the one it is sold under. The per-sale
                # column (`SalesRecord.organic_label_category`) records what each load went out
                # as; this asks the plan-level question — which categories this operation uses
                # at all — because a certifier reviews the categories before reviewing the loads.
                #
                # Values mirror `history.models.ORGANIC_LABEL_CATEGORY_CHOICES` EXACTLY. A
                # second vocabulary for one fact is how the two surfaces silently stop agreeing.
                Question(
                    key="organic_label_categories",
                    kind="checkbox_group",
                    label=text(
                        "Which labeling categories does this operation sell under?",
                        "¿Bajo qué categorías de etiquetado vende esta operación?",
                    ),
                    coaching=text(
                        'A raw agricultural crop sold whole is normally "100 percent organic". '
                        '"Organic" allows up to 5% nonorganic ingredients, and "made with '
                        'organic" is a multi-ingredient category — both are handler-side, so a '
                        "grower who only sells whole crop picks the first. Pick every category "
                        "that appears on a label, an invoice, or a bill of lading.",
                        'Un cultivo agrícola crudo vendido entero normalmente es "100 por ciento orgánico". '
                        '"Orgánico" admite hasta 5% de ingredientes no orgánicos, y "elaborado con orgánicos" '
                        "es una categoría multi-ingrediente — ambas corresponden al procesador, por lo que un "
                        "productor que solo vende cultivo entero elige la primera. Marca cada categoría que "
                        "aparezca en una etiqueta, una factura o una carta de porte.",
                    ),
                    nop_cite="§ 205.301",
                    options=(
                        Option(
                            "100_percent_organic",
                            text("100 percent organic", "100 por ciento orgánico"),
                        ),
                        Option("organic", text("Organic", "Orgánico")),
                        Option(
                            "made_with_organic",
                            text(
                                "Made with organic (specified ingredients or food group(s))",
                                "Elaborado con orgánicos (ingredientes o grupos de alimentos " "especificados)",
                            ),
                        ),
                    ),
                    # No section_key override: this rides the module default like every other
                    # G7.0 question. (a)(2) would be wrong — that clause is the INPUT list —
                    # and inventing a lone routing exception for one question is how a module's
                    # narrative ends up split across two sections for no stated reason.
                    compiles_to=CompileRule(
                        template="Organic product is sold under the following labeling categories: {answer}."
                    ),
                ),
                Question(
                    key="label_states_certifier",
                    kind="boolean",
                    label=text(
                        'Does the consumer label state "Certified organic by [certifying agent]"?',
                        'La etiqueta al consumidor, ¿indica "Certificado orgánico por [agente ' 'certificador]"?',
                    ),
                    coaching=text(
                        "The name of the certifying agent, or its certification mark, must appear on "
                        'the label of any product that carries the word "organic" and is sold to '
                        "consumers.",
                        "El nombre del agente certificador, o su marca de certificación, debe aparecer "
                        'en la etiqueta de todo producto que lleve la palabra "orgánico" y se venda a '
                        "consumidores.",
                    ),
                    nop_cite="§ 205.303",
                    visible_when=(Condition("product_leaves_as", "includes", "consumer_packaging"),),
                    compiles_to=CompileRule(template="Consumer label identifies the certifying agent: {answer}."),
                ),
                Question(
                    key="label_has_usda_seal",
                    kind="boolean",
                    label=text(
                        "Does the USDA organic seal appear on the label?",
                        "¿El sello orgánico del USDA aparece en la etiqueta?",
                    ),
                    coaching=text(
                        "The seal is optional. When used, it must be reproduced from the official USDA "
                        "artwork without modification, and it may not appear on any product that is not "
                        "at least 95 percent organic.",
                        "El sello es opcional. Cuando se usa, debe reproducirse a partir del arte "
                        "oficial del USDA sin modificaciones, y no puede aparecer en ningún producto "
                        "que no sea al menos 95 por ciento orgánico.",
                    ),
                    nop_cite="§ 205.311",
                    visible_when=(Condition("product_leaves_as", "includes", "consumer_packaging"),),
                    compiles_to=CompileRule(template="USDA organic seal displayed on the label: {answer}."),
                ),
                Question(
                    key="label_files_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Upload your current label files",
                        "Sube los archivos de tus etiquetas actuales",
                    ),
                    coaching=text(
                        "Your certifying agent reviews labels before they are used in commerce. Attach "
                        "the current file for each label or package presentation.",
                        "Tu agente certificador revisa las etiquetas antes de que se usen en el comercio. Adjunta "
                        "el archivo vigente de cada etiqueta o presentación de empaque.",
                    ),
                    nop_cite="§ 205.303",
                    visible_when=(Condition("product_leaves_as", "includes", "consumer_packaging"),),
                ),
            ),
        ),
        ModulePage(
            key="b_documents_claims",
            title=text("B. Documents & claims", "B. Documentos y declaraciones"),
            education=(
                text(
                    "Bulk and wholesale shipments carry their organic identity on the paperwork and "
                    "the container instead of a printed label. Every shipment must trace back to a "
                    "specific production lot (§ 205.307).",
                    "Los envíos a granel y mayoristas llevan su identidad orgánica en la documentación "
                    "y en el contenedor en lugar de una etiqueta impresa. Todo envío debe poder "
                    "rastrearse hasta un lote de producción específico (§ 205.307).",
                ),
            ),
            questions=(
                # WSDA AGR 2121 §N1, its options as the form prints them. Asked of everyone: WSDA holds the
                # operation responsible "even if you are not responsible for the transportation of your
                # crops after harvest".
                Question(
                    key="nonretail_container_types",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "What nonretail containers are used to store or ship your organic crops? Check all that "
                        "apply.",
                        "¿Qué envases no destinados a la venta al por menor se usan para almacenar o enviar tus "
                        "cultivos orgánicos? Marca todas las que correspondan.",
                    ),
                    coaching=text(
                        "A nonretail container is any storage or shipping container that is not the package the "
                        "shopper sees.",
                        "Un envase no destinado a la venta al por menor es cualquier envase de almacenamiento o "
                        "envío que no es el empaque que ve el comprador final.",
                    ),
                    nop_cite="§ 205.307",
                    compiles_to=CompileRule(
                        template="Nonretail containers used to store or ship organic crops: {answer}."
                    ),
                    options=(
                        Option("produce_boxes", text("Produce boxes", "Cajas para productos frescos")),
                        Option("totes_bulk_bags", text("Totes or bulk bags", "Totes o sacos a granel")),
                        Option("harvest_crates_bins", text("Harvest crates or bins", "Cajas o bins de cosecha")),
                        Option("bulk_trailers_tanks", text("Bulk trailers or tanks", "Remolques o tanques a granel")),
                        Option(
                            "elevators_silos_bulk_storage",
                            text(
                                "Grain elevators or bins, silos, or other bulk storage",
                                "Elevadores o bins de grano, silos u otro almacenamiento a granel",
                            ),
                        ),
                        Option(
                            "master_cases_pallets",
                            text(
                                "Master cases or pallets of retail packages",
                                "Cajas master o pallets de empaques al por menor",
                            ),
                        ),
                        Option("other", text("Other", "Otros")),
                        # OTCO 8.1-1 and CCOF A1 ask "do you use any?" first; without this a farm that uses none
                        # could never close those rows.
                        Option(
                            "none",
                            text(
                                "None: no organic product is stored or shipped in nonretail containers",
                                "Ninguno: ningún producto orgánico se almacena ni se envía en envases no destinados a la "
                                "venta al por menor",
                            ),
                            exclusive=True,
                        ),
                    ),
                ),
                # WSDA §N2, CCOF G7.0 A2 and OTCO C8 8.1-1 ask one fact three ways; the options are their
                # union, with the agent's name left out so one answer reads right for each of them.
                Question(
                    key="nonretail_organic_identification",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "How do those containers show that the product inside is organic? Check all that apply.",
                        "¿Cómo muestran esos envases que el producto que contienen es orgánico? Marca todas las "
                        "que correspondan.",
                    ),
                    nop_cite="§ 205.307(a)(1)",
                    visible_when=(Condition("nonretail_container_types", "not_includes", "none"),),
                    compiles_to=CompileRule(
                        template="Nonretail containers show that the product is organic by: {answer}."
                    ),
                    options=(
                        Option(
                            "permanent_stamp",
                            text(
                                'Containers are permanently and clearly stamped "organic", "ORG" or similar',
                                'Los envases están marcados de forma permanente y clara con "organic", "ORG" o '
                                "similar",
                            ),
                        ),
                        Option(
                            "container_label_or_tag",
                            text(
                                'A label or tag on each container (bin tag, pallet label) says "organic", "ORG" or '
                                "similar",
                                'Una etiqueta en cada envase (etiqueta de bin, de pallet) dice "organic", "ORG" o '
                                "similar",
                            ),
                        ),
                        Option(
                            "temporary_signage",
                            text(
                                'Temporary signage marks bulk storage or transport units "organic", "ORG" or similar',
                                "Letreros temporales marcan el almacenamiento a granel o las unidades de transporte "
                                'como "organic", "ORG" o similar',
                            ),
                        ),
                        Option(
                            "certifier_statement",
                            text(
                                'A "Certified organic by [certifying agent]" statement',
                                'Una leyenda "Certificado orgánico por [agente certificador]"',
                            ),
                        ),
                        Option(
                            "certifier_seal", text("The certifying agent's seal", "El sello del agente certificador")
                        ),
                        Option("usda_seal", text("The USDA organic seal", "El sello orgánico del USDA")),
                        Option(
                            "visible_through_container",
                            text(
                                "The container holds retail packages whose organic label shows through it",
                                "El envase contiene empaques al por menor cuya etiqueta orgánica se ve a través de él",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describe abajo)")),
                        Option(
                            "no_marking",
                            text(
                                "They carry no organic marking",
                                "No llevan ninguna marca orgánica",
                            ),
                            exclusive=True,
                            review=(
                                "Nonretail containers carry no organic identification. They must identify the "
                                "product as organic (§ 205.307(a)(1)), unless they hold retail-packaged product whose "
                                "organic label is visible (§ 205.307(c))."
                            ),
                        ),
                    ),
                ),
                # The "describe" of CCOF A2's "other", and where WSDA §N2's notes go. Shown on "other" only:
                # an always-open notes box would leave each agent's row open whenever it is left blank.
                Question(
                    key="nonretail_identification_other",
                    kind="textarea",
                    label=text(
                        "Describe the other way containers show the product is organic",
                        "Describe la otra forma en que los envases muestran que el producto es orgánico",
                    ),
                    nop_cite="§ 205.307(a)(1)",
                    visible_when=(
                        Condition("nonretail_container_types", "not_includes", "none"),
                        Condition("nonretail_organic_identification", "includes", "other"),
                    ),
                    compiles_to=CompileRule(template="Other way containers show the product is organic: {answer}"),
                ),
                # CCOF G7.0 A1 ("attach all nonretail container labels") and OTCO C8 8.1-1 ("attach an example
                # of the non-retail shipping or storage label"). Consumer label files have their own question.
                Question(
                    key="nonretail_label_upload",
                    kind="upload",
                    required=False,
                    label=text(
                        "Attach an example of each nonretail container label, tag or stamp",
                        "Adjunta un ejemplo de cada etiqueta, marca o sello de envase no destinado a la venta al "
                        "por menor",
                    ),
                    coaching=text(
                        "A photo of a stamped bin or a printed bin tag is enough. If the USDA seal is on it, include "
                        "it in color.",
                        "Basta una foto de un bin marcado o de una etiqueta de bin impresa. Si lleva el sello del USDA, "
                        "inclúyela a color.",
                    ),
                    nop_cite="§ 205.307",
                    visible_when=(
                        Condition("nonretail_container_types", "not_includes", "none"),
                        Condition(
                            "nonretail_organic_identification",
                            "includes_any",
                            [
                                "permanent_stamp",
                                "container_label_or_tag",
                                "temporary_signage",
                                "certifier_statement",
                                "certifier_seal",
                                "usda_seal",
                            ],
                        ),
                    ),
                ),
                Question(
                    key="invoices_identify_lot",
                    kind="boolean",
                    label=text(
                        "Do your invoices or bills of lading identify each organic shipment as "
                        "organic and show its lot number?",
                        "¿Tus facturas o cartas de porte identifican cada envío orgánico como orgánico e indican su "
                        "número de lote?",
                    ),
                    coaching=text(
                        'State the word "organic" and the lot number, or other unique identification, '
                        "on the sales document for every organic shipment, whether or not the "
                        "container itself is marked.",
                        'Indica la palabra "orgánico" y el número de lote, u otra identificación única, en el '
                        "documento de venta de cada envío orgánico, esté o no marcado el propio contenedor.",
                    ),
                    nop_cite="§ 205.307",
                    compiles_to=CompileRule(
                        template="Sales documents identify organic shipments by lot number: {answer}."
                    ),
                ),
                Question(
                    key="container_markings_tie_to_lot",
                    kind="boolean",
                    label=text(
                        "Do any container markings — bin tags, pallet labels, stencils — tie back to "
                        "the same lot identification used in your records?",
                        "¿Las marcas del contenedor — etiquetas de bins, etiquetas de pallets, plantillas — "
                        "coinciden con la misma identificación de lote usada en tus registros?",
                    ),
                    coaching=text(
                        "A lot number on a bin tag or pallet label is only useful if it matches the "
                        "number in your harvest, storage, and sales records.",
                        "El número de lote en la etiqueta del bin o pallet solo es útil si coincide con el número "
                        "en tus registros de cosecha, almacenamiento y venta.",
                    ),
                    nop_cite="§ 205.307",
                    compiles_to=CompileRule(
                        template="Container markings link to the same lot identification used in records: {answer}."
                    ),
                ),
                # WSDA §N3 and CCOF G7.0 A3, their options. Asked of everyone who uses nonretail containers,
                # not behind `container_markings_tie_to_lot`: a container can carry a shipping ID whether or
                # not its marking matches the record lot, and N3 asks which identifier it carries.
                Question(
                    key="container_lot_identifier_types",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "Which identifier is on your storage and shipping containers? Check all that apply.",
                        "¿Qué identificador llevan tus envases de almacenamiento y envío? Marca todas las que "
                        "correspondan.",
                    ),
                    nop_cite="§ 205.307(a)(2)",
                    visible_when=(Condition("nonretail_container_types", "not_includes", "none"),),
                    compiles_to=CompileRule(template="Identifier on storage and shipping containers: {answer}."),
                    options=(
                        Option("lot_number", text("A lot number", "Un número de lote")),
                        Option(
                            "shipping_identification", text("Shipping identification", "Una identificación de envío")
                        ),
                        Option("other_identifier", text("Another unique identifier", "Otro identificador único")),
                        Option(
                            "no_identifier",
                            text("They carry no identifier", "No llevan ningún identificador"),
                            exclusive=True,
                            review=(
                                "Nonretail containers carry no lot number, shipping identification or other unique "
                                "identifier linking them to the records (§ 205.307(a)(2))."
                            ),
                        ),
                    ),
                ),
                # OTCO C8 8.1-1a, and the "describe" of WSDA §N3 and CCOF A3.
                Question(
                    key="container_lot_linkage_description",
                    kind="textarea",
                    required=False,
                    label=text(
                        "How does that identifier lead back to where the product came from in your records?",
                        "¿Cómo lleva ese identificador al origen del producto en tus registros?",
                    ),
                    coaching=text(
                        "For example: the lot number on the bin tag is the harvest lot, which names the block and "
                        "the pick date, and the same number is on the invoice.",
                        "Por ejemplo: el número de lote en la etiqueta del bin es el lote de cosecha, que indica el "
                        "bloque y la fecha de cosecha, y el mismo número va en la factura.",
                    ),
                    nop_cite="§ 205.307(a)(2)",
                    visible_when=(
                        Condition("nonretail_container_types", "not_includes", "none"),
                        Condition(
                            "container_lot_identifier_types",
                            "includes_any",
                            ["lot_number", "shipping_identification", "other_identifier"],
                        ),
                    ),
                    compiles_to=CompileRule(
                        template="How the container identifier leads back to the product's origin in the records: "
                        "{answer}"
                    ),
                ),
                # WSDA §N 4: storage and shipping records must carry the crop's certification status, the
                # identifier on the container, and the certified business's name. Invoices are asked
                # above (`invoices_identify_lot`); this asks the storage and shipping records themselves.
                Question(
                    key="container_record_elements",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "What do your storage and shipping records show for each organic lot? Check all that " "apply.",
                        "¿Qué muestran tus registros de almacenamiento y envío para cada lote orgánico? Marca todas "
                        "las que correspondan.",
                    ),
                    nop_cite="§ 205.103(b)(2)",
                    visible_when=(Condition("nonretail_container_types", "not_includes", "none"),),
                    compiles_to=CompileRule(
                        template="Storage and shipping records show, for each organic lot: {answer}."
                    ),
                    options=(
                        Option("organic_status", text("That the crop is organic", "Que el cultivo es orgánico")),
                        Option(
                            "container_identifier",
                            text("The identifier on the container", "El identificador del envase"),
                        ),
                        Option(
                            "certified_business_name",
                            text("Our certified business name", "El nombre de nuestro negocio certificado"),
                        ),
                        Option(
                            "none_of_these",
                            text("None of these", "Ninguno de estos"),
                            exclusive=True,
                            review=(
                                "Storage and shipping records show none of: the crop's organic status, the container's "
                                "identifier, the certified business name. A container cannot be read against the "
                                "records."
                            ),
                        ),
                    ),
                ),
                Question(
                    key="label_claim_review_process",
                    kind="textarea",
                    label=text(
                        "Who reviews new labels, package copy, or organic claims before they are used?",
                        "¿Quién revisa las nuevas etiquetas, textos de empaque o declaraciones "
                        "orgánicas antes de que se usen?",
                    ),
                    coaching=text(
                        "Describe who checks new labeling or marketing language against your "
                        "certificate before it reaches a buyer or a package. Never state or imply "
                        "certification for a product, parcel, or activity outside the scope of your "
                        "certificate.",
                        "Describe quién revisa el nuevo etiquetado o el lenguaje de mercadeo frente a tu "
                        "certificado antes de que llegue a un comprador o a un empaque. Nunca declares ni des a "
                        "entender que un producto, parcela o actividad está certificado si está fuera del alcance "
                        "de tu certificado.",
                    ),
                    nop_cite="§ 205.300",
                    compiles_to=CompileRule(template="New labels and organic claims are reviewed by: {answer}"),
                ),
            ),
        ),
        # CCOF G7.0 C, OTCO C8 8.3, WSDA AGR 2121 N 6-7 (2026.11.07). Opened by the one fact all three
        # forms gate on: some crop leaves under a brand the operation does not own. Who those brand
        # owners are, and the copies behind them, live in the brand-owner register; this page shows it
        # and asks how the operation keeps it current.
        ModulePage(
            key="c_brand_owners",
            title=text("C. Brands you pack for", "C. Marcas para las que empacas"),
            visible_when=(Condition("product_leaves_as", "includes", "buyer_label"),),
            education=(
                text(
                    "A crop packed under another company's organic brand is labeled with that company's "
                    "claim, so your certifier asks who each brand owner is and whether it is certified. A "
                    "certified brand owner's certificate is kept on file; an uncertified one needs your "
                    "certifier's private-label or co-packer agreement before its labels are used.",
                    "Un cultivo empacado bajo la marca orgánica de otra empresa se etiqueta con la declaración "
                    "de esa empresa, así que tu certificadora pregunta quién es cada dueño de marca y si está "
                    "certificado. El certificado de un dueño de marca certificado se guarda en archivo; uno no "
                    "certificado necesita el acuerdo de marca privada o de coempacador de tu certificadora antes "
                    "de usar sus etiquetas.",
                ),
            ),
            questions=(
                Question(
                    key="brand_owners_panel",
                    kind="info",
                    embed="brand_owners",
                    required=False,
                    label=text("Brand owners you pack for", "Dueños de marca para los que empacas"),
                    coaching=text(
                        "Add each company, its brands, the products you pack for it with each label's organic "
                        "claim, and a copy of its certificate (or of your certifier's agreement, if it is not "
                        "certified) in the brand-owner register on your farm profile.",
                        "Agrega cada empresa, sus marcas, los productos que empacas para ella con la declaración "
                        "orgánica de cada etiqueta, y una copia de su certificado (o del acuerdo de tu "
                        "certificadora, si no está certificada) en el registro de dueños de marca del perfil de "
                        "tu finca.",
                    ),
                ),
                # OTCO C8 8.3-3, its options as the form prints them.
                Question(
                    key="brand_owner_certificate_check",
                    kind="checkbox_group",
                    required=False,
                    label=text(
                        "How do you make sure each brand owner you pack for holds a current organic certificate?",
                        "¿Cómo te aseguras de que cada dueño de marca para el que empacas tenga un certificado "
                        "orgánico vigente?",
                    ),
                    nop_cite="§ 205.103",
                    compiles_to=CompileRule(
                        template="How brand owners' organic certificates are kept current: {answer}."
                    ),
                    options=(
                        Option(
                            "certificates_on_file",
                            text(
                                "We keep each one's valid certificate, listing the branded products, and get an "
                                "updated one every year",
                                "Guardamos el certificado vigente de cada uno, con los productos de marca, y "
                                "pedimos uno actualizado cada año",
                            ),
                        ),
                        Option(
                            "oid_check",
                            text(
                                "We check the USDA Organic Integrity Database to confirm the certificate is valid",
                                "Revisamos la base de datos Organic Integrity del USDA para confirmar que el "
                                "certificado es válido",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="brand_owner_certificate_check_other",
                    kind="text",
                    required=False,
                    label=text("Describe how", "Describe cómo"),
                    visible_when=(Condition("brand_owner_certificate_check", "includes", "other"),),
                    compiles_to=CompileRule(template="Brand owners' certificates are also kept current by: {answer}"),
                ),
                # WSDA AGR 2121 N 7a, its options.
                Question(
                    key="brand_owner_certificate_frequency",
                    kind="radio",
                    required=False,
                    label=text(
                        "How often do you ask brand owners for an updated certificate?",
                        "¿Cada cuánto pides a los dueños de marca un certificado actualizado?",
                    ),
                    nop_cite="§ 205.103",
                    compiles_to=CompileRule(template="Updated brand-owner certificates are requested: {answer}."),
                    options=(
                        Option("annually", text("Annually", "Cada año")),
                        Option(
                            "prior_to_each_use",
                            text("Before each use of the label", "Antes de cada uso de la etiqueta"),
                        ),
                        Option("other", text("Other (describe below)", "Otro (describe abajo)")),
                    ),
                ),
                Question(
                    key="brand_owner_certificate_frequency_other",
                    kind="text",
                    required=False,
                    label=text("How often", "Cada cuánto"),
                    visible_when=(Condition("brand_owner_certificate_frequency", "eq", "other"),),
                    compiles_to=CompileRule(template="Updated brand-owner certificates are requested: {answer}"),
                ),
                # WSDA AGR 2121 N 7.
                Question(
                    key="labels_name_other_agency",
                    kind="boolean",
                    required=False,
                    label=text(
                        "Do any of these labels name a certifying agent other than yours, below the distributor's "
                        "name?",
                        "¿Alguna de estas etiquetas indica una certificadora distinta de la tuya, debajo del nombre "
                        "del distribuidor?",
                    ),
                    coaching=text(
                        "The distributor shown on the label must be certified by the agent shown, for each "
                        "branded product.",
                        "El distribuidor que aparece en la etiqueta debe estar certificado por la certificadora "
                        "que aparece, para cada producto de marca.",
                    ),
                    nop_cite="§ 205.303(b)(2)",
                    compiles_to=CompileRule(
                        template="Some labels packed for brand owners name a certifying agent other than the "
                        "operation's own below the distributor ({answer}).",
                        template_false="No label packed for a brand owner names a certifying agent other than the "
                        "operation's own.",
                    ),
                ),
                # WSDA AGR 2121 N 6a and 6b, asked of every agent: each reviews organic labels.
                Question(
                    key="labels_submitted_to_certifier",
                    kind="radio",
                    required=False,
                    label=text(
                        "Has your certifying agent reviewed every current label making an organic claim that you "
                        "pack into?",
                        "¿Tu certificadora revisó todas las etiquetas vigentes con declaración orgánica en las "
                        "que empacas?",
                    ),
                    nop_cite="§ 205.300",
                    compiles_to=CompileRule(
                        template="Review of current brand-owner labels by the certifying agent: {answer}."
                    ),
                    options=(
                        Option(
                            "all_approved",
                            text(
                                "Yes, every current label has been approved",
                                "Sí, todas las etiquetas vigentes fueron aprobadas",
                            ),
                        ),
                        Option(
                            "new_or_updated_attached",
                            text(
                                "No, new or updated labels are attached for review",
                                "No, las etiquetas nuevas o actualizadas se adjuntan para revisión",
                            ),
                            requires_upload="label_files_upload",
                        ),
                        Option(
                            "not_submitted",
                            text("Not yet submitted", "Todavía no se enviaron"),
                            review="Labels packed for a brand owner have not been submitted to the certifying agent for review.",
                        ),
                    ),
                ),
                Question(
                    key="label_approval_before_use",
                    kind="textarea",
                    required=False,
                    label=text(
                        "How do you make sure your certifying agent approves new and revised labels before they "
                        "are used?",
                        "¿Cómo te aseguras de que tu certificadora apruebe las etiquetas nuevas y modificadas "
                        "antes de usarlas?",
                    ),
                    nop_cite="§ 205.300",
                    compiles_to=CompileRule(
                        template="New and revised labels are approved before use as follows: {answer}"
                    ),
                ),
            ),
        ),
    ),
)
