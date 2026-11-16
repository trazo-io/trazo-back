"""How `backend.test_runner.ShardedRunner` splits the CI list across matrix jobs.

The test classes below are built inside each test with `type()`, never at module level, so test
discovery does not collect and run them. Nothing here touches the database.
"""

import unittest

from django.test import SimpleTestCase, TestCase, TransactionTestCase

from backend.test_runner import deal


def _test_class(dotted, base):
    module, _, name = dotted.rpartition(".")
    cls = type(name, (base,), {"test_one": lambda self: None, "test_two": lambda self: None})
    cls.__module__ = module
    cls.__qualname__ = name
    return cls


def _suite(plain, transactional):
    tests = []
    for dotted in plain:
        cls = _test_class(dotted, TestCase)
        tests += [cls("test_one"), cls("test_two")]
    for dotted in transactional:
        cls = _test_class(dotted, TransactionTestCase)
        tests += [cls("test_one"), cls("test_two")]
    return tests


def _name(test):
    return f"{type(test).__module__}.{type(test).__qualname__}"


class DealTests(SimpleTestCase):
    # Thirty-six classes in sorted order, every third one transactional: dealt alphabetically
    # they all land on one shard, the way `carbon.tests.test_retired_*` clustered on shard 3 on
    # 2026-11-16.
    PLAIN = [f"app.tests.test_m{n:02d}.Tests" for n in range(36) if n % 3 != 2]
    TRANSACTIONAL = [f"app.tests.test_m{n:02d}.ChainTests" for n in range(36) if n % 3 == 2]

    def _alphabetical_shard_of(self, dotted, total=3):
        names = sorted(self.PLAIN + self.TRANSACTIONAL)
        return names.index(dotted) % total

    def test_the_fixture_reproduces_the_cluster(self):
        """Guards the next test: dealt alphabetically, every transactional class of this fixture
        lands on one shard. Without that, an even split below would prove nothing."""
        self.assertEqual({self._alphabetical_shard_of(name) for name in self.TRANSACTIONAL}, {2})

    def test_transactional_classes_split_evenly_whatever_their_names(self):
        tests = _suite(self.PLAIN, self.TRANSACTIONAL)
        for index in (1, 2, 3):
            selected, mine, _ = deal(tests, index, 3)
            with self.subTest(shard=index):
                self.assertEqual(len(mine & set(self.TRANSACTIONAL)), 4)

    def test_every_test_runs_on_exactly_one_shard(self):
        tests = _suite(self.PLAIN, self.TRANSACTIONAL)
        seen = []
        for index in (1, 2, 3):
            selected, _, classes = deal(tests, index, 3)
            seen += selected
            self.assertEqual(len(classes), len(self.PLAIN) + len(self.TRANSACTIONAL))
        self.assertEqual(sorted(map(id, seen)), sorted(map(id, tests)))

    def test_a_class_is_never_split(self):
        tests = _suite(self.PLAIN, self.TRANSACTIONAL)
        owner = {}
        for index in (1, 2, 3):
            selected, _, _ = deal(tests, index, 3)
            for test in selected:
                self.assertEqual(owner.setdefault(_name(test), index), index)

    def test_a_test_case_and_a_plain_unittest_class_are_not_transactional(self):
        """Only a TransactionTestCase that is not a TestCase is dealt first: a TestCase rolls back
        a transaction, and a plain unittest class never touches the database."""
        plain_unittest = _test_class("app.tests.test_aaa.Plain", unittest.TestCase)
        test_case = _test_class("app.tests.test_aab.Rolled", TestCase)
        chain = _test_class("app.tests.test_zzz.Chain", TransactionTestCase)
        _, _, classes = deal([plain_unittest("test_one"), test_case("test_one"), chain("test_one")], 1, 1)
        self.assertEqual(classes[0], "app.tests.test_zzz.Chain")
        self.assertEqual(classes[1:], ["app.tests.test_aaa.Plain", "app.tests.test_aab.Rolled"])
