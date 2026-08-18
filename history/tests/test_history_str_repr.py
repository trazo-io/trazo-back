"""`str(History)` must never raise, and must never be empty.

Both properties are load-bearing rather than cosmetic: django-auditlog builds every
LogEntry's `object_repr` by calling `smart_str(instance)`, so a `__str__` that raises takes
down the SAVE, and a `__str__` that returns "" writes a blank row into the audit trail this
product sells.

The two defects fixed 2026-08-18:

  * `.strftime()` called on a nullable `start_date` -> AttributeError on any production
    created without one (white-glove / COG Pro import targets are built by hand).
  * `+` binds tighter than a conditional expression, so
    `... + self.product.name if self.product else ""` guarded the ENTIRE concatenation.
    A production with no product stringified to "".

No database — `__str__` reads only instance attributes.
"""

import datetime

from django.test import SimpleTestCase

from history.models import History
from product.models import Product


class HistoryStrTests(SimpleTestCase):
    START = datetime.datetime(2025, 2, 3, 9, 0)
    FINISH = datetime.datetime(2025, 10, 22, 17, 0)

    def test_a_production_with_no_start_date_does_not_raise(self):
        """The regression. This raised AttributeError, and auditlog turned that into a
        failed save rather than a bad label."""
        self.assertIsInstance(str(History()), str)

    def test_a_production_with_no_product_is_not_empty(self):
        """Precedence bug: the whole expression collapsed to "" without a product."""
        text = str(History(start_date=self.START, finish_date=self.FINISH))
        self.assertNotEqual(text, "")
        self.assertIn("02/03/2025", text)
        self.assertIn("10/22/2025", text)

    def test_an_unfinished_production_reads_as_present(self):
        text = str(History(start_date=self.START))
        self.assertIn("02/03/2025", text)
        self.assertIn("present", text)

    def test_a_complete_production_still_names_its_product(self):
        """Guards the guard: the null-safety must not have cost the normal label."""
        text = str(History(start_date=self.START, finish_date=self.FINISH, product=Product(name="Walnuts")))
        self.assertEqual(text, "[ 02/03/2025 - 10/22/2025 ] - Walnuts")

    def test_an_empty_production_still_produces_something_printable(self):
        text = str(History())
        self.assertTrue(text.strip(), "str(History()) is blank — auditlog would log an empty object_repr")
