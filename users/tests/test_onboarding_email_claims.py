"""Claim safety for the two emails every new grower receives on day one.

The signup emails are collateral, and collateral drifts out of step with the product it
describes. On 2026-08-19 a pilot dress rehearsal ran a real signup and read what actually
arrived:

  - "Blockchain-recorded production data" (verification) and "Build consumer trust with
    blockchain-recorded data" (welcome, twice). BLOCKCHAIN_ENABLED is False and the $15/mo
    add-on is withdrawn (is_active=False). The surface was removed; the collateral kept
    selling it. This is the DATA != UI != COLLATERAL class.
  - "20 pre-configured US crops", when populate_usda_crop_types ships 33.
  - The welcome email's ONLY button pointed at https://producer.trazo.io, which does not
    resolve. Every producer who clicked the primary CTA hit NXDOMAIN. The plain-text half of
    the same email already said app.trazo.io.

These assert the templates, not a rendered message, because the failure mode is someone
editing the copy — and a template that never renders in tests still lands in an inbox.

The exception is the last test, which RENDERS. On 2026-08-20 the note explaining the
producer.trazo.io fix above was itself written as a multi-line {# ... #} — and Django's
hash comment is SINGLE-LINE only, so the whole engineering note, red circle and test path
included, rendered into the body of the welcome email between the bullet list and the CTA
button. Every source-reading test here passed while it shipped. A template comment is only
a comment once the engine has agreed it is one, so the check has to look at output.

Deleted 2026-08-20 (and so no longer swept): users/utils.py's `send_invitation_to_user` and the
`email_verification_code/` templates it rendered. The function's own docstring called it "Legacy
... kept for backward compatibility" and it had ZERO callers, so the templates were reachable by
name and by nothing else — which is why they had drifted to a layout that ignored base.html, a
lowercase wordmark and a "Hi ," greeting. Grep USAGE, not definition: a template referenced from
an uncalled function looks live to every search that stops at the reference.

Also 2026-08-20: the blockchain and host checks below were scoped to a hand-typed tuple of six
onboarding templates, so they never looked at subscriptions/templates. The three trial emails
there — live, dispatched by `subscriptions.tasks.send_trial_emails` — were still selling the
withdrawn add-on a year after the surface was removed, and trial_final_nudge used the phrase
compliance.md explicitly forbids ("Blockchain-verified records", not "-recorded"). The 08-19 fix
landed on the audited surface and never reached its sibling. The template list is now WALKED off
disk, not typed, so a new email is covered the day it is added rather than the day someone
remembers to add it here.
"""

from pathlib import Path

from django.test import TestCase

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

# Every app that ships templates rendered into an outbound message. Adding an app here is the
# only maintenance this file needs; the templates inside are discovered, never listed.
TEMPLATE_ROOTS = (
    BACKEND_ROOT / "users" / "templates",
    BACKEND_ROOT / "subscriptions" / "templates",
)


def _discover_email_templates():
    """Walk the template roots and return engine-relative names, sorted.

    Typed inventories rot: the six-name tuple this replaced was written for the onboarding
    audit and silently excluded the three subscription trial emails, which then drifted for
    a year. Anything a future app adds under a templates/ root is swept automatically.
    """
    found = []
    for root in TEMPLATE_ROOTS:
        for path in sorted(root.rglob("*")):
            if path.suffix in (".html", ".txt") and path.is_file():
                found.append(path.relative_to(root).as_posix())
    return tuple(found)


ALL_EMAIL_TEMPLATES = _discover_email_templates()


def read_template(name):
    """Resolve an engine-relative template name against whichever root holds it.

    Mirrors how the loader resolves it, so a source-reading test and a rendering test are
    always looking at the same file.
    """
    for root in TEMPLATE_ROOTS:
        candidate = root / name
        if candidate.is_file():
            return candidate.read_text()
    raise AssertionError(f"{name} is not under any root in TEMPLATE_ROOTS")


# The mails a brand-new grower receives before they have logged anything. Still named
# explicitly because the crop-count claim is specific to them — but the claim checks that
# apply to ANY outbound mail run over ALL_EMAIL_TEMPLATES instead.
ONBOARDING_TEMPLATES = (
    "emails/verification.txt",
    "emails/verification.html",
    "emails/welcome.txt",
    "emails/welcome.html",
    "emails/welcome_invited.txt",
    "emails/welcome_invited.html",
)

# Hosts an onboarding email is allowed to send someone to. producer.trazo.io is deliberately
# absent: it has never resolved.
ALLOWED_TRAZO_HOSTS = {"trazo.io", "www.trazo.io", "app.trazo.io", "consumer.trazo.io"}


class OnboardingEmailClaimTests(TestCase):
    def test_the_template_inventory_is_not_empty_and_covers_every_app(self):
        """A discovery walk that silently finds nothing would make every check below vacuous."""
        self.assertGreaterEqual(len(ALL_EMAIL_TEMPLATES), 15, ALL_EMAIL_TEMPLATES)
        for expected in ("emails/welcome.html", "subscriptions/emails/trial_expired.html"):
            self.assertIn(expected, ALL_EMAIL_TEMPLATES)

    def test_no_template_name_is_shadowed_by_a_second_root(self):
        """Two roots holding the same relative name would silently halve the coverage.

        `read_template` returns the first root that has the file and the loader resolves by
        app order, so a duplicate name means one of the two files is never read by anything
        here while still appearing in the inventory as though it were.
        """
        seen = {}
        for root in TEMPLATE_ROOTS:
            for path in root.rglob("*"):
                if path.suffix in (".html", ".txt") and path.is_file():
                    name = path.relative_to(root).as_posix()
                    seen.setdefault(name, []).append(str(root))
        collisions = {n: roots for n, roots in seen.items() if len(roots) > 1}
        self.assertEqual(collisions, {}, f"template name served by two roots: {collisions}")

    def test_no_email_sells_the_withdrawn_blockchain_addon(self):
        offenders = []
        for name in ALL_EMAIL_TEMPLATES:
            for lineno, line in enumerate(read_template(name).splitlines(), 1):
                if "blockchain" in line.lower():
                    offenders.append(f"{name}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "Blockchain is disabled (BLOCKCHAIN_ENABLED=False) and the $15/mo add-on is "
            "withdrawn (is_active=False); these outbound emails still advertise it:\n" + "\n".join(offenders),
        )

    def test_no_email_points_at_a_host_that_does_not_resolve(self):
        import re

        offenders = []
        for name in ALL_EMAIL_TEMPLATES:
            for lineno, line in enumerate(read_template(name).splitlines(), 1):
                for host in re.findall(r"https?://([a-z0-9.-]*trazo\.io)", line):
                    if host not in ALLOWED_TRAZO_HOSTS:
                        offenders.append(f"{name}:{lineno}: {host}")
        self.assertEqual(
            offenders,
            [],
            "An outbound email links to a Trazo host outside the known-good set "
            f"{sorted(ALLOWED_TRAZO_HOSTS)}:\n" + "\n".join(offenders),
        )

    def test_crop_count_in_the_welcome_email_matches_the_seeder(self):
        from carbon.management.commands.populate_usda_crop_types import Command

        actual = len(Command()._get_crop_type_data())
        import re

        for name in ("emails/welcome.txt", "emails/welcome.html"):
            body = read_template(name)
            claimed = [int(n) for n in re.findall(r"(\d+)\s+pre-configured US crops", body)]
            self.assertTrue(claimed, f"{name} no longer states a crop count — update this test")
            for n in claimed:
                self.assertEqual(
                    n,
                    actual,
                    f"{name} claims {n} pre-configured US crops; the seeder ships {actual}.",
                )


class OnboardingEmailRenderTests(TestCase):
    """The templates must RENDER clean — source-reading tests cannot see this class of bug."""

    # Enough context for every onboarding template to render its branches.
    CONTEXTS = (
        {"user_type": "producer", "first_name": "Dana"},
        {"user_type": "consumer", "first_name": "Dana"},
    )

    # Anything that means "the engine did not consume this" or "an engineer talking to
    # engineers", in delivered output.
    LEAK_MARKERS = (
        "{#",
        "#}",
        "{%",
        "%}",
        "{{",
        "}}",
        "TODO",
        "FIXME",
        "XXX",
        "Guarded by",
        "🔴",
    )

    def test_no_onboarding_email_renders_template_syntax_or_engineering_notes(self):
        from django.template.loader import render_to_string

        offenders = []
        for name in ALL_EMAIL_TEMPLATES:
            for context in self.CONTEXTS:
                body = render_to_string(name, dict(context))
                for marker in self.LEAK_MARKERS:
                    if marker in body:
                        line = next((ln.strip() for ln in body.splitlines() if marker in ln), "")
                        offenders.append(f"{name} [{context['user_type']}]: {marker!r} in {line[:120]!r}")
        self.assertEqual(
            offenders,
            [],
            "Onboarding email rendered unconsumed template syntax or an internal note into "
            "the delivered body:\n" + "\n".join(offenders),
        )


class EmailPositioningTests(TestCase):
    """Copy and palette must match the October positioning, not the transparency era.

    Trazo stopped being "the agricultural transparency platform" when the one-pager was
    rewritten on 2026-08-11 (documentation/sales/TRAZO_ONEPAGER.md — "Organic recordkeeping
    that's ready for renewal season", one entry → two outputs). The emails kept the old
    category name, and worse, kept selling a producer "transparency score" that has had no
    widget since 2026-08-11 and promising CONSUMERS a score that is deliberately withheld
    from every consumer surface (EU 2024/825, FTC 16 CFR 260.6).
    """

    def test_no_email_uses_the_retired_transparency_positioning(self):
        offenders = []
        for name in ALL_EMAIL_TEMPLATES:
            for lineno, line in enumerate(read_template(name).splitlines(), 1):
                if "transparency" in line.lower():
                    offenders.append(f"{name}:{lineno}: {line.strip()[:110]}")
        self.assertEqual(
            offenders,
            [],
            "The transparency-era positioning is retired (TRAZO_ONEPAGER.md, 2026-08-11) and the "
            "producer transparency score has no UI; these emails still use it:\n" + "\n".join(offenders),
        )

    def test_every_greeting_has_a_fallback_name(self):
        """`User.first_name` is blank=True, so a bare greeting variable renders "Hi ,".

        Most templates already carried |default:"there"; five did not, including two
        first-contact emails. A default that never fires costs nothing.
        """
        import re

        bare = re.compile(r"Hi \{\{ (?!.*\|default:)[^}]+\}\},")
        offenders = []
        for name in ALL_EMAIL_TEMPLATES:
            for lineno, line in enumerate(read_template(name).splitlines(), 1):
                if bare.search(line):
                    offenders.append(f"{name}:{lineno}: {line.strip()[:100]}")
        self.assertEqual(
            offenders,
            [],
            'Greeting without |default:"there" — renders "Hi ," when the name is blank:\n' + "\n".join(offenders),
        )

    def test_no_email_claims_a_trial(self):
        """Starter is free forever — no card, no clock, no trial. Migration 0015 exists because
        the phantom "14-day free trial" survived on the $249 plan; it was still in the subject
        line of two live subscription emails, one of them naming Starter by name."""
        offenders = []
        for name in ALL_EMAIL_TEMPLATES:
            body = read_template(name).lower()
            for phrase in ("14-day", "14 day", "free trial of trazo", "starter plan ends"):
                if phrase in body:
                    offenders.append(f"{name}: {phrase!r}")
        self.assertEqual(offenders, [], "Trial claim in an outbound email:\n" + "\n".join(offenders))


class EmailPaletteTests(TestCase):
    """The brand green is measured, not chosen — and an email cannot fall back to a token.

    green.500 (#4CAF50) is the DECORATIVE brand green: 2.78:1 against white, which fails AA
    and even the 3:1 non-text floor. It may never carry white text and may never render
    glyphs. It was the header gradient, the primary button, the verification code, the
    checkmarks and the footer links across every template — 50 occurrences against 3 for
    green.700, the token whose job is actually carrying content.
    """

    # Hexes that are not ours, keyed by where they actually come from. Grep the DECLARATION:
    # these arrive by copy-paste from a Tailwind or Material snippet, never on purpose.
    FOREIGN_HEXES = {
        "#4CAF50": "green.500 — decorative only, 2.78:1; use green.700 for anything with type",
        "#f0fdf4": "Tailwind green-50 — use green.50 #F8FDF9",
        "#166534": "Tailwind green-800 — use green.700 #2E7D32",
        "#2196F3": "Material blue — blue carries no meaning in this system",
        "#1E88E5": "Material blue",
        "#0ea5e9": "Tailwind sky-500",
        "#0369a1": "Tailwind sky-700",
        "#eff6ff": "Tailwind blue-50",
        "#1d4ed8": "Tailwind blue-700",
        "#f59e0b": "Tailwind amber-500 — the theme defines amber, not orange",
        "#d97706": "Tailwind amber-600",
        "#fef3c7": "Tailwind amber-100 — use amber.50 #FFF8E1",
        "#ef4444": "Tailwind red-500 — use red.700 #D32F2F",
        "#991b1b": "Tailwind red-800 — use red.900 #B71C1C",
        "#fef2f2": "Tailwind red-50 — use red.50 #FFEBEE",
        "#888888": "3.54:1 on white — fails AA for body copy",
        "#999999": "2.85:1 on white — fails AA",
    }

    def test_no_email_uses_a_colour_outside_the_theme(self):
        offenders = []
        for name in ALL_EMAIL_TEMPLATES:
            body = read_template(name)
            for hexcode, why in self.FOREIGN_HEXES.items():
                for lineno, line in enumerate(body.splitlines(), 1):
                    if hexcode.lower() in line.lower():
                        offenders.append(f"{name}:{lineno}: {hexcode} — {why}")
        self.assertEqual(
            offenders,
            [],
            "Foreign or failing colour in an email template:\n" + "\n".join(offenders),
        )

    def test_white_text_never_sits_on_the_decorative_green(self):
        """The specific 2.78:1 failure, asserted on RENDERED output.

        A literal hex check is not enough on its own: the colour usually arrives through a
        gradient or a bgcolor attribute rather than a `color:` prop, which is why this failure
        kept coming back in the app. Rendering catches it wherever it is spelled.
        """
        from django.template.loader import render_to_string

        offenders = []
        for name in ALL_EMAIL_TEMPLATES:
            for user_type in ("producer", "consumer"):
                body = render_to_string(name, {"user_type": user_type})
                if "4caf50" in body.lower():
                    offenders.append(f"{name} [{user_type}]")
        self.assertEqual(
            offenders,
            [],
            "green.500 reached a rendered email; it may not carry white text or render "
            "glyphs (2.78:1):\n" + "\n".join(offenders),
        )
