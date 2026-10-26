"""The weekly source watch tells an unchanged form from a moved one, a changed one and a dead link.

WHY THIS EXISTS
---------------
CCOF re-published every form on 2026-10-10 under new codes, and the register's URLs answered "Page
not found" for two weeks before anyone looked. `scripts/check_form_sources.py` now compares every
recorded URL with its recorded hash each week. Its first live run (2026-10-24) also caught Oregon
Tilth's O1 revised on 2026-10-02.

These run against a fake fetcher: no network in CI. Pinned: a "Page not found" served with status
200 is never read as the file; a file that only moved is not reported as changed; a captured web
form is never claimed as checked; and the exit code is non-zero exactly when a person is needed.
"""

import hashlib
import importlib.util
import sys
from pathlib import Path

from django.test import SimpleTestCase

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_form_sources.py"
_spec = importlib.util.spec_from_file_location("check_form_sources", _SCRIPT)
watch = importlib.util.module_from_spec(_spec)
# A dataclass module resolves its annotations through sys.modules, so it is registered first.
sys.modules[_spec.name] = watch
_spec.loader.exec_module(watch)

PDF = b"%PDF-1.7 the registered edition"
OLD_URL = "https://agent.example/uploads/2025/05/Form-A1.pdf"
NEW_URL = "https://agent.example/uploads/2026/10/Form-B1.pdf"
LANDING = "https://agent.example/resource/form/"
SOURCE = {"file": "Form-A1.pdf", "url": OLD_URL, "sha256": hashlib.sha256(PDF).hexdigest()}
NOT_FOUND = b"<html><title>Page not found</title></html>"


def _site(pages):
    def get(url):
        return pages.get(url, (404, b""))

    return get


class CheckFormTests(SimpleTestCase):
    def test_the_recorded_file_at_the_recorded_url_is_unchanged(self):
        result = watch.check_form("ccof", "A", SOURCE, LANDING, _site({OLD_URL: (200, PDF)}))
        self.assertEqual(result.state, watch.UNCHANGED)

    def test_a_different_file_at_the_recorded_url_is_changed(self):
        result = watch.check_form("otco", "O1", SOURCE, LANDING, _site({OLD_URL: (200, b"%PDF-1.7 new edition")}))
        self.assertEqual(result.state, watch.CHANGED)

    def test_a_not_found_page_served_200_is_not_the_file_and_the_landing_page_is_read(self):
        site = _site(
            {OLD_URL: (200, NOT_FOUND), LANDING: (200, f'<a href="{NEW_URL}">PDF</a>'.encode()), NEW_URL: (200, PDF)}
        )
        result = watch.check_form("ccof", "A", SOURCE, LANDING, site)
        self.assertEqual(result.state, watch.MOVED)
        self.assertEqual(result.candidates, [NEW_URL])

    def test_a_new_file_on_the_landing_page_is_changed_and_named(self):
        site = _site({LANDING: (200, b'<a href="/uploads/2026/10/Form-B1.pdf">PDF</a>'), NEW_URL: (200, b"%PDF new")})
        result = watch.check_form("ccof", "A", SOURCE, LANDING, site)
        self.assertEqual(result.state, watch.CHANGED)
        self.assertEqual(result.candidates, [NEW_URL])

    def test_no_url_and_no_landing_page_is_unreachable(self):
        self.assertEqual(watch.check_form("wsda", "X", SOURCE, LANDING, _site({})).state, watch.UNREACHABLE)
        self.assertEqual(watch.check_form("wsda", "X", SOURCE, "", _site({})).state, watch.UNREACHABLE)

    def test_a_captured_web_form_is_never_claimed_as_checked(self):
        source = {"file": "CCOF-Annual-Renewal-Contract.html", "url": "https://agent.example/payments/", "sha256": "x"}
        self.assertEqual(watch.check_form("ccof", "ARC", source, "", _site({})).state, watch.NOT_CHECKED)


class ReviewOfBack222Tests(SimpleTestCase):
    def test_a_link_that_is_not_http_is_never_fetched(self):
        """Links come from live third-party HTML; urllib also opens file:// and ftp://."""
        asked = []

        def get(url):
            asked.append(url)
            pages = {LANDING: (200, b'<a href="file:///etc/passwd.pdf">x</a><a href="ftp://h/f.pdf">y</a>')}
            return pages.get(url, (404, b""))

        result = watch.check_form("ccof", "A", SOURCE, LANDING, get)
        self.assertEqual(result.state, watch.CHANGED)
        self.assertEqual(result.candidates, [])
        self.assertEqual(asked, [OLD_URL, LANDING])
        self.assertEqual(watch.fetch("file:///etc/passwd"), (0, b""))

    def test_a_form_whose_landing_is_its_own_file_falls_back_to_the_agents_forms_page(self):
        """WSDA AGR 2521 names the PDF itself as its landing page."""
        wsda = watch.REGISTER / "wsda"
        index = watch._agent_index(wsda)
        self.assertTrue(index)
        self.assertFalse(watch._is_file_url(index))
        import yaml

        url_2521 = yaml.safe_load((wsda / "inventory" / "2521-renewal-fee.yaml").read_text())["source"]["url"]
        seen = []
        watch.check_register(get=lambda url: (seen.append(url), (404, b""))[1])
        at = seen.index(url_2521)
        self.assertEqual(seen[at + 1 : at + 2], [index])


class RequestHeaderTests(SimpleTestCase):
    def test_oregon_tilth_files_are_requested_with_the_forms_page_as_referer(self):
        headers = watch.request_headers("https://tilth.org/wp-content/uploads/2026/10/M1MushroomProduction.docx")
        self.assertEqual(headers.get("Referer"), "https://tilth.org/help-center/blank-forms-all/")
        self.assertIn("User-Agent", headers)

    def test_other_hosts_get_no_referer(self):
        for url in ("https://www.ccof.org/x.pdf", "https://nottilth.org/x.pdf", "https://tilth.org.evil.example/x.pdf"):
            with self.subTest(url):
                self.assertNotIn("Referer", watch.request_headers(url))


class RegisterAndExitTests(SimpleTestCase):
    def test_every_registered_form_is_checked_once(self):
        register = watch.REGISTER
        expected = sum(1 for _ in register.glob("*/inventory/*.yaml"))
        results = watch.check_register(get=_site({}))
        self.assertEqual(len(results), expected)
        self.assertGreater(expected, 50)

    def test_the_exit_code_asks_for_a_person_only_when_one_is_needed(self):
        calm = [watch.Result("a", "f", watch.UNCHANGED, "u"), watch.Result("a", "g", watch.NOT_CHECKED, "u")]
        self.assertFalse(any(r.state in watch.NEEDS_REVIEW for r in calm))
        for state in (watch.MOVED, watch.CHANGED, watch.UNREACHABLE):
            self.assertIn(state, watch.NEEDS_REVIEW)
        self.assertIn("2 registered forms: 1 unchanged, 1 not_checked", watch.report(calm))
