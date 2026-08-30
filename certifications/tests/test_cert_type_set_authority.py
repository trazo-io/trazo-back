"""One answer to "which certification types count as organic" — and no second copy.

WHAT WENT WRONG
---------------
Five hardcoded tuples answered this question, in three modules, with FOUR different answers:

    history/services/operation_readiness_service.py  ("usda_organic","ccof","cng","real_organic_project","roc")
    history/services/audit_export_service.py  (x3)   ...the same five, then
                                                     ("usda_organic","ccof","ccof_organic","ams_organic"), then
                                                     ("usda_organic","ccof")
    certifications/services/osp_module_pdf.py        ("usda_organic","ccof")

`ccof_organic` and `ams_organic` appear in NO vocabulary in this codebase — they were never
storable, so the § 205.404(d) no-expiry branch they guarded had two dead members and one
(`ccof`) that only existed because a CERTIFYING AGENT was sitting in the TYPE column. One of
the five even carried the comment "Mirrors AuditExportService's ORGANIC_CERT_TYPES", which is
a comment standing where an import belongs. No test held any of them together.

WHAT THIS FILE GUARDS
---------------------
1. Both sets contain only storable types (a member that is not in
   `CERTIFICATION_TYPE_CHOICES` can never match a row, so it is dead by construction).
2. NOP ⊆ organic-conferring, and NOP means Part 205 specifically — a private add-on standard
   with its own expiry date must not inherit the § 205.404(d) "does not expire" wording.
3. No module re-declares the members. This is a SOURCE scan, deliberately: the failure mode
   is someone typing the tuple again next to an import of the real thing, and an import-time
   assertion cannot see that.
4. A certifying AGENT never returns as a certification TYPE.
"""

import io as _io
import re
import tokenize
from pathlib import Path

from django.test import SimpleTestCase

from certifications.constants import (
    CERTIFICATION_TYPE_CHOICES,
    NOP_CERTIFICATION_TYPES,
    ORGANIC_CONFERRING_CERT_TYPES,
    VERIFIER_REGISTRY,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories whose source is scanned for a re-declared allowlist. Migrations are excluded:
# a migration's job is to freeze the vocabulary as it stood, so it MUST restate values.
SCANNED_DIRS = ("history", "certifications", "company", "product", "carbon", "subscriptions")

# Accredited certifying agents. None of these is a certification — each one ISSUES USDA
# Organic under 7 CFR Part 205, so it belongs in `Certification.certifier_name`.
CERTIFYING_AGENTS = (
    "ccof",
    "wsda",
    "oregon_tilth",
    "pco",
    "oeffa",
    "mosa",
    "nofa_ny",
    "qcs",
    "baystate",
    "mofga",
    "wfcf",
)


class SetMembershipTests(SimpleTestCase):
    def test_every_member_is_a_storable_certification_type(self):
        declared = {key for key, _ in CERTIFICATION_TYPE_CHOICES}
        for name, members in (
            ("NOP_CERTIFICATION_TYPES", NOP_CERTIFICATION_TYPES),
            ("ORGANIC_CONFERRING_CERT_TYPES", ORGANIC_CONFERRING_CERT_TYPES),
        ):
            unstorable = sorted(set(members) - declared)
            self.assertEqual(
                unstorable,
                [],
                f"{name} names {unstorable}, which no Certification row can ever hold. "
                "A member that is not in CERTIFICATION_TYPE_CHOICES is dead code guarding "
                "a branch that never runs — exactly how 'ccof_organic' and 'ams_organic' "
                "survived in audit_export_service for as long as they did.",
            )

    def test_nop_is_a_subset_of_organic_conferring(self):
        self.assertTrue(
            set(NOP_CERTIFICATION_TYPES) <= set(ORGANIC_CONFERRING_CERT_TYPES),
            "a certificate issued under Part 205 must also count as organic-conferring",
        )

    def test_private_add_on_standards_are_not_treated_as_nop(self):
        """The § 205.404(d) / § 205.406 boundary.

        ROP and ROC sit on top of a USDA Organic certificate but are private standards
        with real expiry dates; CNG is a non-NOP peer-review programme. Printing
        "does not expire per § 205.404(d)" over any of them would be false on the page a
        certifier reads.
        """
        for private in ("real_organic_project", "roc", "cng", "korean_organic"):
            self.assertNotIn(private, NOP_CERTIFICATION_TYPES)

    def test_only_nop_types_have_a_database_verifier(self):
        """`VERIFIER_REGISTRY` is what turns a claim into "Verified via Database".

        The Organic Integrity Database covers NOP operations. Wiring a verifier to anything
        else would put the word "verified" behind a lookup that cannot substantiate it
        (16 CFR 260.6).
        """
        self.assertEqual(sorted(VERIFIER_REGISTRY), sorted(NOP_CERTIFICATION_TYPES))


class NoCertifierIsATypeTests(SimpleTestCase):
    def test_no_certifying_agent_is_offered_as_a_certification_type(self):
        declared = {key for key, _ in CERTIFICATION_TYPE_CHOICES}
        agents_as_types = sorted(declared & set(CERTIFYING_AGENTS))
        self.assertEqual(
            agents_as_types,
            [],
            f"{agents_as_types} are certifying AGENTS, not certifications. An agent in the "
            "type column costs the operation its Organic Integrity Database verification "
            "(VERIFIER_REGISTRY only knows 'usda_organic') and forces every organic-type "
            "allowlist in the codebase to name that one certifier forever. The agent goes "
            "in Certification.certifier_name.",
        )

    def test_the_september_named_lists_top_certifier_is_not_special_cased(self):
        """The reason the CCOF entry was a strategy bug and not only a modelling one.

        Of the 981 operations on `named-list-2026-09-v2.csv`, 288 are certified by WSDA and
        zero by CCOF. Hardcoding any single certifier bakes a market assumption into the
        data model; hardcoding the one with no targets left is how it got noticed.
        """
        declared = {key for key, _ in CERTIFICATION_TYPE_CHOICES}
        self.assertNotIn("wsda", declared)
        self.assertNotIn("ccof", declared)


class NoSecondCopyTests(SimpleTestCase):
    """The members must appear in exactly one file: certifications/constants.py."""

    # A tuple/list literal that contains "usda_organic" alongside at least one other quoted
    # slug — i.e. someone rebuilding one of these sets by hand.
    LITERAL_SET = re.compile(
        r"[\(\[]\s*\n?\s*[\"']usda_organic[\"']\s*,\s*\n?\s*[\"'][a-z_]+[\"']",
        re.MULTILINE,
    )

    # certifications/constants.py IS the authority — it is supposed to spell the members out.
    AUTHORITY = Path("certifications") / "constants.py"

    def _python_sources(self):
        for directory in SCANNED_DIRS:
            root = REPO_ROOT / directory
            if not root.exists():
                continue
            for path in root.rglob("*.py"):
                if "/migrations/" in str(path) or "/tests/" in str(path):
                    continue
                if path.name.startswith("test_"):
                    continue
                if path.relative_to(REPO_ROOT) == self.AUTHORITY:
                    continue
                yield path

    @staticmethod
    def _without_comments(source: str) -> str:
        """Blank out comments before scanning.

        A comment quoting the retired tuple — which is exactly how the fix documents what it
        replaced — is not a second copy. Scanning raw text made the guard fire on its own
        changelog, which would have taught the next person to delete the explanation.
        Line numbers are preserved so an offender still reports a usable location.
        """
        lines = source.splitlines()
        try:
            for token in tokenize.generate_tokens(_io.StringIO(source).readline):
                if token.type != tokenize.COMMENT:
                    continue
                row, col = token.start[0] - 1, token.start[1]
                lines[row] = lines[row][:col]
        except (tokenize.TokenError, IndentationError, SyntaxError):
            # A file we cannot tokenize is scanned raw rather than skipped: a false positive
            # is recoverable, a silently unscanned module is the failure this guard exists for.
            return source
        return "\n".join(lines)

    def test_the_regex_would_actually_catch_a_rebuilt_set(self):
        """Anti-vacuity. A scan that matches nothing passes for the wrong reason.

        This is the shape that was live in four places until 2026-08-27; if the pattern
        stops recognising it, the scan below is decoration.
        """
        self.assertTrue(self.LITERAL_SET.search('ORGANIC_CERT_TYPES = (\n    "usda_organic",\n    "cng",\n)'))
        self.assertTrue(self.LITERAL_SET.search('X = ("usda_organic", "ccof")'))

    def test_no_module_rebuilds_an_organic_type_set(self):
        offenders = []
        for path in self._python_sources():
            source = self._without_comments(path.read_text(encoding="utf-8"))
            for match in self.LITERAL_SET.finditer(source):
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")
        self.assertEqual(
            offenders,
            [],
            "these files rebuild a certification-type set by hand instead of importing "
            f"NOP_CERTIFICATION_TYPES / ORGANIC_CONFERRING_CERT_TYPES: {offenders}. Five "
            "such copies with four different answers is what this guard exists to stop.",
        )
