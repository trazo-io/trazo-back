"""Twelve legacy demo seeders and repair commands, deleted 2026-11-07.

Each one wrote the retiring offset, benchmark or report models, or wrote claims compliance.md
forbids as if they were facts, or both. No script, Dockerfile or deploy spec invoked them; two
were still reachable by hand: `create_staging_superuser --seed` called
`seed_comprehensive_demo_ultimate`, and PRODUCTION_DEPLOYMENT_README.md listed
`seed_crop_benchmarks` as a deploy step.

They are checked against Django's command registry, not file paths, so a command of the same name
in another app is caught too. Bringing one back is a decision about what Trazo asserts: give it a
new name and a source for every figure it writes.
"""

from django.core.management import get_commands
from django.test import SimpleTestCase

#: name -> one example of what it wrote (quoted from the deleted source).
DELETED_SEEDERS = {
    "seed_comprehensive_demo": 'sustainability_commitment "Carbon Neutral by 2026"; offset projects',
    "seed_comprehensive_demo_ultimate": '"Carbon Negative by 2025 - Currently at 78% reduction"',
    "seed_comprehensive_demo_v2": '"40% water reduction vs traditional"; offset projects',
    "quick_carbon_fix": 'third_party_verification_url "https://usda.gov/verify"',
    "fix_demo_data": 'certification_standard "Verified Carbon Standard (VCS)"',
    "complete_demo_data": 'a source described as "USDA verified organic fertilizer emissions"',
    "create_sample_certified_projects": 'offset projects certified "VCS (Verra)"',
    "seed_crop_benchmarks": 'counts marked "# Simulated data", sourced to "USDA Agricultural Research Service"',
    "seed_test_data": '"Premium product - $3.8/kg"',
    "seed_consumer_data": '"Saves approximately $500 per acre annually"',
    "seed_2025_data": '"Reduced water usage by 30% compared to industry average"',
    "create_crop_templates": '"Convert to organic practices (premium pricing 15-30%)"',
    # 2026-11-11: unreferenced; created EquipmentEvent rows (a type closed for creation that day,
    # history/views.py RETIRED_CREATE_EVENT_TYPES) and a user oscar+test@trazo.io with a password
    # hard-coded in the source.
    "seed_realistic_data": 'EquipmentEvent rows and user.set_password("<hard-coded>")',
}


class LegacySeedersStayDeletedTests(SimpleTestCase):
    def test_none_is_registered(self):
        registered = get_commands()
        self.assertIn("create_comprehensive_production_templates_v2", registered)  # read the registry
        back = sorted(name for name in DELETED_SEEDERS if name in registered)
        self.assertEqual(back, [], "A deleted seeder is registered again:\n  " + "\n  ".join(back))
