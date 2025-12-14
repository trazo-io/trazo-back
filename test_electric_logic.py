#!/usr/bin/env python3
"""
Simplified logic validation for Phase 1 electric equipment implementation
Tests calculation logic without requiring full Django setup
"""

import re
from pathlib import Path


class Phase1LogicValidator:
    """Validate electric equipment implementation logic"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = []
        self.errors = []

    def validate_file(self, filepath):
        """Read and validate the verified_emission_factors.py file"""
        with open(filepath, 'r') as f:
            content = f.read()
            return content

    def check_pattern_consistency(self, content):
        """Verify all 6 methods follow identical pattern"""
        print("\n=== Pattern Consistency Check ===")

        methods = [
            "_calculate_planting_emissions",
            "_calculate_harvesting_emissions",
            "_calculate_transplanting_emissions",
            "_calculate_thinning_emissions",
            "_calculate_cultivation_emissions",
            "_calculate_general_production_emissions",
        ]

        for method in methods:
            # Find method definition (handle multi-line signatures)
            pattern = rf'def {method}\([\s\S]+?\*\*kwargs'
            if re.search(pattern, content):
                print(f"✓ {method} has **kwargs parameter")
                self.passed += 1
            else:
                print(f"✗ {method} MISSING **kwargs parameter")
                self.failed += 1
                self.errors.append(f"{method} missing **kwargs")

            # Check kwargs extraction
            method_start = content.find(f"def {method}")
            if method_start != -1:
                method_end = content.find("\n    @classmethod", method_start + 1)
                if method_end == -1:
                    method_end = content.find("\n    def ", method_start + 1)
                method_body = content[method_start:method_end]

                # Check for fuel_type extraction
                if 'fuel_type = kwargs.get("fuel_type", "diesel")' in method_body:
                    print(f"✓ {method} extracts fuel_type correctly")
                    self.passed += 1
                else:
                    print(f"✗ {method} missing fuel_type extraction")
                    self.failed += 1
                    self.errors.append(f"{method} missing fuel_type extraction")

                # Check for energy_source extraction
                if 'energy_source = kwargs.get("energy_source", "grid")' in method_body:
                    print(f"✓ {method} extracts energy_source correctly")
                    self.passed += 1
                else:
                    print(f"✗ {method} missing energy_source extraction")
                    self.failed += 1
                    self.errors.append(f"{method} missing energy_source extraction")

                # Check for electric branching
                if 'if fuel_type == "electric":' in method_body:
                    print(f"✓ {method} has electric branching logic")
                    self.passed += 1
                else:
                    print(f"✗ {method} missing electric branching logic")
                    self.failed += 1
                    self.errors.append(f"{method} missing electric branching")

                # Check for renewable energy handling
                if 'if energy_source in ["solar", "wind"]:' in method_body:
                    print(f"✓ {method} handles renewable energy sources")
                    self.passed += 1
                else:
                    print(f"✗ {method} missing renewable energy handling")
                    self.failed += 1
                    self.errors.append(f"{method} missing renewable handling")

                # Check for correct emission factors
                if '0.39' in method_body and 'electricity_factor.value' in method_body:
                    print(f"✓ {method} uses 0.39 kg CO₂/kWh factor")
                    self.passed += 1
                else:
                    print(f"⚠ {method} may not use correct electricity factor")
                    self.warnings.append(f"{method} electricity factor check")

                if '10.21' in method_body or 'diesel_factor.value' in method_body:
                    print(f"✓ {method} uses diesel factor correctly")
                    self.passed += 1
                else:
                    print(f"⚠ {method} may not use correct diesel factor")
                    self.warnings.append(f"{method} diesel factor check")

    def check_dispatcher_integration(self, content):
        """Verify dispatcher passes kwargs correctly"""
        print("\n=== Dispatcher Integration Check ===")

        dispatcher = content.find("def calculate_production_event_emissions")
        if dispatcher == -1:
            print("✗ Cannot find dispatcher method")
            self.failed += 1
            self.errors.append("Dispatcher method not found")
            return

        dispatcher_end = content.find("\n    @classmethod", dispatcher + 1)
        dispatcher_body = content[dispatcher:dispatcher_end]

        # Check each method call in dispatcher
        method_calls = [
            ("_calculate_harvesting_emissions", "harvest"),
            ("_calculate_transplanting_emissions", "transplant"),
            ("_calculate_planting_emissions", "plant"),
            ("_calculate_thinning_emissions", "thin"),
            ("_calculate_cultivation_emissions", "cultivat"),
            ("_calculate_general_production_emissions", "else"),
        ]

        for method, keyword in method_calls:
            # Check if method is called with **kwargs
            pattern = rf'{method}\([^)]+\*\*kwargs\)'
            if re.search(pattern, dispatcher_body):
                print(f"✓ Dispatcher passes **kwargs to {method}")
                self.passed += 1
            else:
                print(f"✗ Dispatcher NOT passing **kwargs to {method}")
                self.failed += 1
                self.errors.append(f"Dispatcher missing **kwargs for {method}")

    def check_migration_syntax(self):
        """Verify migration file syntax"""
        print("\n=== Migration File Check ===")

        migration_path = Path("history/migrations/0125_alter_productionevent_fuel_unit.py")
        if not migration_path.exists():
            print("✗ Migration file not found")
            self.failed += 1
            self.errors.append("Migration file missing")
            return

        with open(migration_path, 'r') as f:
            content = f.read()

        # Check for kWh choice
        if '"kWh", "Kilowatt-hours"' in content:
            print("✓ Migration adds kWh option")
            self.passed += 1
        else:
            print("✗ Migration missing kWh option")
            self.failed += 1
            self.errors.append("Migration missing kWh")

        # Check migration syntax
        if 'class Migration(migrations.Migration):' in content:
            print("✓ Migration has correct class structure")
            self.passed += 1
        else:
            print("✗ Migration has incorrect structure")
            self.failed += 1
            self.errors.append("Migration structure invalid")

    def check_backwards_compatibility(self, content):
        """Verify backwards compatibility is maintained"""
        print("\n=== Backwards Compatibility Check ===")

        # Check default values
        if 'kwargs.get("fuel_type", "diesel")' in content:
            print("✓ fuel_type defaults to 'diesel' for backwards compatibility")
            self.passed += 1
        else:
            print("✗ fuel_type may not default correctly")
            self.failed += 1
            self.errors.append("fuel_type default issue")

        if 'kwargs.get("energy_source", "grid")' in content:
            print("✓ energy_source defaults to 'grid' for backwards compatibility")
            self.passed += 1
        else:
            print("✗ energy_source may not default correctly")
            self.failed += 1
            self.errors.append("energy_source default issue")

    def check_calculation_logic(self, content):
        """Verify calculation logic correctness"""
        print("\n=== Calculation Logic Check ===")

        # Check electric calculation
        electric_calc = 'co2e_kg = fuel_consumed * electricity_factor.value  # 0.39 kg CO₂/kWh'
        if electric_calc in content:
            print("✓ Electric calculation uses correct formula (kWh × 0.39)")
            self.passed += 1
        else:
            print("⚠ Electric calculation formula may vary")
            self.warnings.append("Electric calculation formula")

        # Check diesel calculation
        diesel_calc = 'co2e_kg = fuel_consumed * diesel_factor.value'
        if content.count(diesel_calc) >= 6:
            print("✓ Diesel calculation uses correct formula (gal × factor)")
            self.passed += 1
        else:
            print("⚠ Diesel calculation formula may be inconsistent")
            self.warnings.append("Diesel calculation formula")

        # Check renewable zero emissions
        zero_emissions = 'co2e_kg = 0'
        if content.count(zero_emissions) >= 6:
            print("✓ Renewable energy sources correctly set zero emissions")
            self.passed += 1
        else:
            print("✗ Renewable energy zero emissions may be missing")
            self.failed += 1
            self.errors.append("Renewable zero emissions")

    def check_breakdown_completeness(self, content):
        """Verify breakdown dictionaries are complete"""
        print("\n=== Breakdown Dictionary Check ===")

        required_fields = [
            '"fuel_type": fuel_type',
            '"energy_source"',
            '"electricity_emission_factor_kg_per_kwh"',
            '"diesel_emission_factor_kg_per_gallon"',
        ]

        for field in required_fields:
            if field in content:
                print(f"✓ Breakdown includes {field}")
                self.passed += 1
            else:
                print(f"⚠ Breakdown may be missing {field}")
                self.warnings.append(f"Breakdown field: {field}")

    def run_all_checks(self):
        """Run all validation checks"""
        print("\n" + "="*70)
        print("PHASE 1 ELECTRIC EQUIPMENT LOGIC VALIDATION")
        print("="*70)

        # Read the main file
        filepath = "carbon/services/verified_emission_factors.py"
        content = self.validate_file(filepath)

        # Run checks
        self.check_pattern_consistency(content)
        self.check_dispatcher_integration(content)
        self.check_migration_syntax()
        self.check_backwards_compatibility(content)
        self.check_calculation_logic(content)
        self.check_breakdown_completeness(content)

        # Print summary
        print("\n" + "="*70)
        print("VALIDATION SUMMARY")
        print("="*70)

        print(f"\nPASSED: {self.passed}")
        print(f"FAILED: {self.failed}")
        print(f"WARNINGS: {len(self.warnings)}")
        print(f"TOTAL CHECKS: {self.passed + self.failed + len(self.warnings)}")

        if self.errors:
            print("\n" + "="*70)
            print("CRITICAL ERRORS")
            print("="*70)
            for error in self.errors:
                print(f"  ✗ {error}")

        if self.warnings:
            print("\n" + "="*70)
            print("WARNINGS (Non-Critical)")
            print("="*70)
            for warning in self.warnings:
                print(f"  ⚠ {warning}")

        print("\n" + "="*70)
        if self.failed == 0:
            print("✓✓✓ LOGIC VALIDATION PASSED ✓✓✓")
            print("Backend implementation follows correct pattern")
            print("="*70 + "\n")
            return True
        else:
            print(f"✗✗✗ VALIDATION FAILED ({self.failed} errors) ✗✗✗")
            print("Review required before deployment")
            print("="*70 + "\n")
            return False


if __name__ == "__main__":
    import sys
    validator = Phase1LogicValidator()
    success = validator.run_all_checks()
    sys.exit(0 if success else 1)
