"""
The OSP module Spanish speaks to the grower in neutral tuteo, the register es-419 uses everywhere.

Measured 2026-10-28 in the harvest e2e run: about 290 module strings addressed the grower as
usted ("Describa la otra práctica", "¿Conserva registros...?", "su operación") while the newer
questions on the same screens said "Marca todas las que correspondan" and "tus contenedores".
The frontend guard (`spanishRegister.test.ts`) reads es-419.json only, and only for voseo, so
the module text was never checked.

Scoped to forms that are usted and nothing else, so the guard does not argue about style:
"usted" itself, an usted imperative opening a clause ("Describa", "Indique"), an usted
imperative with an enclitic ("indíquelo", "respóndalos", "asegúrese"), and a question that
opens on "¿Su"/"¿Sus". A third-person subjunctive mid-clause ("una declaración que confirme",
"antes de que ingrese") is ordinary Spanish in either register and is left alone.
"""

import re

from django.test import SimpleTestCase

from certifications.osp_modules import serialize_registry

_W = r"[\wáéíóúüñÁÉÍÓÚÜÑ]"

_USTED = re.compile(rf"(?<!{_W})usted(?!{_W})", re.I)

# Clause starts: the string's start, or after sentence punctuation, an opening bracket or a dash.
_IMPERATIVE = re.compile(
    rf"(?:^|[.;:!?¿(—–]\s*)(Describa|Indique|Adjunte|Seleccione|Explique|Marque|Proporcione|Elija|Escriba"
    rf"|Incluya|Confirme|Anote|Consulte|Ingrese|Agregue|Registre|Mantenga|Guarde|Revise|Utilice|Identifique"
    rf"|Especifique|Enumere|Pregunte|Cargue|Conserve|Responda|Añada|Considere|Documente|Vincule|Solicite"
    rf"|Imprima|Dibuje|Declare|Verifique|Suba|Deje|Tenga|Haga)(?!{_W})",
    re.I,
)

_ENCLITIC = re.compile(
    rf"(?<!{_W})(indíquel[oa]s?|déjel[oa]s?|descríbal[oa]s?|respóndal[oa]s?|asegúrese|anótel[oa]s?"
    rf"|consérvel[oa]s?|adjúntel[oa]s?|márquel[oa]s?|explíquel[oa]s?|inclúyal[oa]s?)(?!{_W})",
    re.I,
)

_QUESTION_SU = re.compile(r"¿Sus?\s")


def _spanish_strings(node, path=""):
    if isinstance(node, dict):
        if isinstance(node.get("es"), str) and "en" in node:
            yield path, node["es"]
        for key, value in node.items():
            yield from _spanish_strings(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _spanish_strings(value, f"{path}[{i}]")


class OspModuleSpanishIsTuteoTests(SimpleTestCase):
    def setUp(self):
        self.strings = list(_spanish_strings(serialize_registry()))

    def test_the_walk_reads_the_module_text(self):
        # A guard that read nothing would pass on any registry.
        self.assertGreater(len(self.strings), 1000)
        self.assertTrue(any(s.startswith("Describe ") for _, s in self.strings))

    def test_no_module_string_addresses_the_grower_as_usted(self):
        offenders = []
        for path, text in self.strings:
            for rx in (_USTED, _IMPERATIVE, _ENCLITIC, _QUESTION_SU):
                match = rx.search(text)
                if match:
                    offenders.append(f"{path}: …{text[max(0, match.start() - 30):match.end() + 30]}…")
                    break
        self.assertEqual(offenders, [], "usted in the module Spanish:\n" + "\n".join(offenders))
