"""Test runner that can run one shard of the suite, for CI matrix jobs.

    manage.py test <labels> --testrunner backend.test_runner.ShardedRunner --shard 2/3

WHY SHARDS AND NOT --parallel (measured 2026-10-02)
---------------------------------------------------
The hosted runner for a private repo has 2 vCPUs, shared by the Python workers AND the Postgres
service container. `--parallel 2` and `--parallel 4` both left the CI module list at ~458s, the
same as serial: the two cores were already saturated. (On an 8-core laptop `--parallel 4` halved
it, which is why the laptop number does not transfer.) A matrix job brings its own 2 vCPUs and
its own Postgres, so splitting the suite across jobs is what actually adds CPU.

HOW TESTS ARE SPLIT
-------------------
By TEST CLASS, never by test method: a class's `setUpTestData` runs once per class, so splitting
a class across shards would make every shard pay its fixture. Classes are ordered by dotted path
and dealt round-robin, so a module with many heavy classes (the packet and specimen suites) is
spread over every shard instead of landing on one.

The partition is exhaustive and disjoint by construction (index modulo the shard count), so the
shards together run exactly the tests a single unsharded run would. Each shard prints its share,
and the counts across shards sum to the unsharded "Found N test(s)".
"""

import unittest

from django.test.runner import DiscoverRunner, partition_suite_by_case


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def _parse_shard(spec):
    try:
        index, total = (int(part) for part in spec.split("/"))
    except ValueError:
        raise ValueError(f"--shard expects INDEX/TOTAL, e.g. 2/3; got {spec!r}") from None
    if not 1 <= index <= total:
        raise ValueError(f"--shard index must be between 1 and {total}; got {spec!r}")
    return index, total


class ShardedRunner(DiscoverRunner):
    def __init__(self, shard=None, **kwargs):
        super().__init__(**kwargs)
        self.shard = _parse_shard(shard) if shard else None

    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--shard",
            help="Run only shard INDEX of TOTAL (1-based), splitting by test class. Example: 2/3.",
        )

    def build_suite(self, *args, **kwargs):
        if not self.shard:
            return super().build_suite(*args, **kwargs)
        index, total = self.shard

        # Shard the PLAIN suite, then parallelise the shard. super() wraps its result in a
        # ParallelTestSuite when --parallel > 1 and sets self.parallel, which later decides how
        # many test databases get cloned; filtering that wrapped suite would clone N databases and
        # then run serially. So ask super() for a serial suite and apply the same wrapping here.
        parallel, self.parallel = self.parallel, 1
        try:
            suite = super().build_suite(*args, **kwargs)
        finally:
            self.parallel = parallel

        tests = list(_flatten(suite))
        classes = sorted({f"{type(t).__module__}.{type(t).__qualname__}" for t in tests})
        mine = {name for position, name in enumerate(classes) if position % total == index - 1}
        selected = [t for t in tests if f"{type(t).__module__}.{type(t).__qualname__}" in mine]

        print(f"Shard {index}/{total}: {len(selected)} of {len(tests)} tests, {len(mine)} of {len(classes)} classes")
        suite = self.test_suite(selected)

        # Mirrors the tail of DiscoverRunner.build_suite (Django 5.2).
        if self.parallel > 1:
            subsuites = partition_suite_by_case(suite)
            self.parallel = min(self.parallel, len(subsuites))
            if self.parallel > 1:
                suite = self.parallel_test_suite(subsuites, self.parallel, self.failfast, self.debug_mode, self.buffer)
        return suite
