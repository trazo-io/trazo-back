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
    nop_cites=("§ 205.300", "§ 205.301", "§ 205.303", "§ 205.307"),
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
                    "Indique cada forma en que el producto orgánico sale de esta operación — muchas "
                    "operaciones usan más de una según el comprador. Marcar el empaque listo para el "
                    "consumidor activa las preguntas sobre el agente certificador y el sello, más "
                    "abajo; los envíos a granel y mayoristas se cubren en cambio con las preguntas "
                    "sobre documentos de la sección B.",
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
                        ),
                        Option(
                            "buyer_label",
                            text(
                                "Sold under the buyer's own label (private label or repack)",
                                "Vendido bajo la etiqueta propia del comprador (marca privada o " "reempaque)",
                            ),
                        ),
                        Option("other", text("Other (describe below)", "Otra (describa abajo)")),
                    ),
                ),
                Question(
                    key="product_leaves_as_other",
                    kind="text",
                    label=text(
                        "Describe the other way product leaves the operation",
                        "Describa la otra forma en que el producto sale de la operación",
                    ),
                    visible_when=(Condition("product_leaves_as", "includes", "other"),),
                    compiles_to=CompileRule(template="Additional product form: {answer}."),
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
                        'Un cultivo agrícola crudo vendido entero normalmente es "100 por ciento '
                        'orgánico". "Orgánico" admite hasta 5% de ingredientes no orgánicos, y '
                        '"elaborado con orgánicos" es una categoría multi-ingrediente — ambas '
                        "corresponden al procesador, por lo que un productor que solo vende "
                        "cultivo entero elige la primera. Marque cada categoría que aparezca en "
                        "una etiqueta, una factura o una carta de porte.",
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
                        "Suba los archivos de sus etiquetas actuales",
                    ),
                    coaching=text(
                        "Your certifying agent reviews labels before they are used in commerce. Attach "
                        "the current file for each label or package presentation.",
                        "Su agente certificador revisa las etiquetas antes de que se usen en el "
                        "comercio. Adjunte el archivo vigente de cada etiqueta o presentación de "
                        "empaque.",
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
                Question(
                    key="invoices_identify_lot",
                    kind="boolean",
                    label=text(
                        "Do your invoices or bills of lading identify each organic shipment as "
                        "organic and show its lot number?",
                        "¿Sus facturas o cartas de porte identifican cada envío orgánico como "
                        "orgánico e indican su número de lote?",
                    ),
                    coaching=text(
                        'State the word "organic" and the lot number, or other unique identification, '
                        "on the sales document for every organic shipment, whether or not the "
                        "container itself is marked.",
                        'Indique la palabra "orgánico" y el número de lote, u otra identificación '
                        "única, en el documento de venta de cada envío orgánico, esté o no marcado el "
                        "propio contenedor.",
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
                        "¿Las marcas del contenedor — etiquetas de bins, etiquetas de pallets, "
                        "plantillas — coinciden con la misma identificación de lote usada en sus "
                        "registros?",
                    ),
                    coaching=text(
                        "A lot number on a bin tag or pallet label is only useful if it matches the "
                        "number in your harvest, storage, and sales records.",
                        "El número de lote en la etiqueta del bin o pallet solo es útil si coincide con "
                        "el número en sus registros de cosecha, almacenamiento y venta.",
                    ),
                    nop_cite="§ 205.307",
                    compiles_to=CompileRule(
                        template="Container markings link to the same lot identification used in records: {answer}."
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
                        "Describa quién revisa el nuevo etiquetado o el lenguaje de mercadeo frente a "
                        "su certificado antes de que llegue a un comprador o a un empaque. Nunca "
                        "declare ni dé a entender que un producto, parcela o actividad está "
                        "certificado si está fuera del alcance de su certificado.",
                    ),
                    nop_cite="§ 205.300",
                    compiles_to=CompileRule(template="New labels and organic claims are reviewed by: {answer}"),
                ),
            ),
        ),
    ),
)
