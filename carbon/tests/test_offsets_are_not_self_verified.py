"""
⛔ No carbon write path may stamp "verified" on an offset the operator entered.

"Verified" on a carbon record asserts that a THIRD PARTY checked it. Nobody checks these.
Until 2026-09-23 five paths wrote it anyway:

  * views_security_enhanced.create_secure_carbon_offset  — hardcoded on every entry, and on
    the CarbonSource it derived from the request body's own `verification_level`;
  * the same view's CarbonOffsetPurchase, which a PDF certificate is generated from;
  * serializers_secure — passing its own shape/gaming validation is not verification;
  * views.py — on the same call that records `data_source="User-created offset"`, so the
    row contradicted itself.

Those rows are a false attestation stored in the database, and netted against emissions they
were the source of the public "Carbon Stored" badge removed the same day
(see self-created-label-can-be-a-colour-2026-09-23). FTC 16 CFR 260.5 governs offset claims.

This guard reads the SOURCE rather than exercising the endpoints: the endpoints demand a
signed session, a CSRF token and an anti-gaming payload, and a guard nobody can run is a
guard that does not hold. `self_reported` is the vocabulary certifications already use.

2026-11-07: views_security_enhanced.py and serializers_secure.py were deleted, with the
`secure/*` routes and carbon/services/verification.py, whose `verify_carbon_entry` still wrote
"verified" from checks on the caller's own input. views.py is the offset write path left, and
the deleted modules are held deleted below so the stamp cannot come back with them.

Later the same day the unrouted `CarbonOffsetViewSet` in views.py was deleted too. Offsets now
enter only through `entries/`, which writes the model default unless a path sets the status.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from carbon.models import VERIFICATION_SELF_REPORTED, CarbonEntry

CARBON = Path(__file__).resolve().parent.parent

# Offset write paths. ⛔ Seeders and one-off management commands are deliberately out of
# scope: they do not run in production and their rows are not user assertions.
OFFSET_WRITE_PATHS = ("views.py",)

#: Deleted 2026-11-07 with the `secure/*` routes. Each one wrote, or built a certificate from, an
#: offset the operator entered. See carbon/tests/test_retired_claim_routes_stay_retired.py.
DELETED_OFFSET_MODULES = (
    "views_security_enhanced.py",
    "serializers_secure.py",
    "services/backend_security_validation.py",
    "services/certificate.py",
    "services/verification.py",
)

_COMMENT = re.compile(r"^\s*#")


def _code_lines(path: Path):
    """Source lines with comments dropped — the fix's own comments quote the old literal."""
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        if not _COMMENT.match(line):
            yield i, line


class OffsetsAreNotSelfVerified(SimpleTestCase):
    def test_constant_is_self_reported(self):
        self.assertEqual(VERIFICATION_SELF_REPORTED, "self_reported")

    def test_no_offset_path_hardcodes_verified(self):
        offenders = []
        for name in OFFSET_WRITE_PATHS:
            for lineno, line in _code_lines(CARBON / name):
                if re.search(r'verification_status\s*[=:]\s*["\']verified["\']', line):
                    offenders.append(f"{name}:{lineno}: {line.strip()}")
                # The conditional form the source defaults used, e.g.
                # "verified" if verification_level == "certified_project" else "estimated"
                if re.search(r'["\']verified["\']\s+if\s+verification_level', line):
                    offenders.append(f"{name}:{lineno}: {line.strip()}")

        self.assertEqual(
            offenders,
            [],
            "An offset write path stamps 'verified' on user-entered data. Nothing verified it.\n"
            "Use VERIFICATION_SELF_REPORTED unless a named third party checked it and the\n"
            "artifact is stored.\n  " + "\n  ".join(offenders),
        )

    def test_the_unrouted_offset_viewset_stays_deleted(self):
        """`CarbonOffsetViewSet.create` was the explicit offset write in views.py, and the only
        user of VERIFICATION_SELF_REPORTED there. Its route was cut on 2026-09-07 and the class
        was deleted on 2026-11-07, so the constant check that used to stand here has nothing left
        to read. The class coming back is the regression."""
        source = (CARBON / "views.py").read_text()
        self.assertNotIn("class CarbonOffsetViewSet", source)
        self.assertIn("class CarbonEntryViewSet", source)  # read the real file

    def test_the_model_default_claims_no_verification(self):
        """What an offset posted to `entries/` gets when no path sets the status. A path that
        stopped writing "verified" by dropping the field lands here, so the default must not be
        a verification either."""
        default = CarbonEntry._meta.get_field("verification_status").default
        self.assertNotIn("verified", default)

    def test_request_body_is_never_treated_as_proof(self):
        """`verification_level` arrives in the payload. NEVER: it is the claimant's assertion and
        must never, by itself, decide a verification_status."""
        for name in OFFSET_WRITE_PATHS:
            for lineno, line in _code_lines(CARBON / name):
                if "verification_status" in line and "verification_level" in line:
                    self.fail(
                        f"{name}:{lineno} derives a verification_status from the request "
                        f"body's verification_level: {line.strip()}"
                    )
        self.assertIn("verification_level", (CARBON / "views.py").read_text())  # read something

    def test_the_deleted_offset_modules_stay_deleted(self):
        back = [name for name in DELETED_OFFSET_MODULES if (CARBON / name).exists()]
        self.assertEqual(
            back,
            [],
            "A deleted offset module is back. Each wrote or certified an offset nobody checked:\n"
            "re-adding one is a decision about what Trazo asserts, made in "
            "test_retired_claim_routes_stay_retired.py first.\n  " + "\n  ".join(back),
        )
