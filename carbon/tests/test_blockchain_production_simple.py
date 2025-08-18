#!/usr/bin/env python3
"""
Simplified Blockchain Production Readiness Test
Tests Month 1, Week 3-4 implementation for Trazo MVP
"""

import os
import sys
import time

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.base")
django.setup()

try:
    from carbon.services.production_blockchain import production_blockchain_service

    PRODUCTION_SERVICE_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ Production blockchain service not available: {e}")
    PRODUCTION_SERVICE_AVAILABLE = False

from users.models import User


class SimpleBlockchainTester:
    def __init__(self):
        self.test_results = []
        print("🚀 Starting Simplified Blockchain Production Test")
        print("=" * 50)

    def test_service_availability(self):
        """Test if production blockchain service is available"""
        print("\n🧪 Testing Service Availability...")

        if PRODUCTION_SERVICE_AVAILABLE:
            try:
                stats = production_blockchain_service.get_service_stats()
                print(f"   ✅ Service loaded successfully")
                print(f"   Network: {stats['network']}")
                print(f"   Mock Mode: {stats['mock_mode']}")
                print(f"   Contracts: {stats['contracts_loaded']}")

                self.test_results.append({"test": "service_availability", "status": "passed", "details": stats})

            except Exception as e:
                print(f"   ❌ Service error: {e}")
                self.test_results.append({"test": "service_availability", "status": "failed", "error": str(e)})
        else:
            print("   ❌ Production blockchain service not available")
            self.test_results.append(
                {"test": "service_availability", "status": "failed", "error": "Service not available"}
            )

    def test_gas_optimization(self):
        """Test gas optimization functionality"""
        print("\n🧪 Testing Gas Optimization...")

        if not PRODUCTION_SERVICE_AVAILABLE:
            print("   ⏭️ Skipping - service not available")
            return

        try:
            analysis = production_blockchain_service.get_gas_optimization_analysis("verify", 10)
            print(f"   ✅ Gas analysis completed")
            print(f"   Estimated Gas: {analysis.estimated_gas:,}")
            print(f"   Network Congestion: {analysis.network_congestion}")

            self.test_results.append(
                {
                    "test": "gas_optimization",
                    "status": "passed",
                    "details": f"Gas: {analysis.estimated_gas}, Congestion: {analysis.network_congestion}",
                }
            )

        except Exception as e:
            print(f"   ❌ Gas optimization failed: {e}")
            self.test_results.append({"test": "gas_optimization", "status": "failed", "error": str(e)})

    def test_batch_verification(self):
        """Test batch verification functionality"""
        print("\n🧪 Testing Batch Verification...")

        if not PRODUCTION_SERVICE_AVAILABLE:
            print("   ⏭️ Skipping - service not available")
            return

        try:
            production_ids = [1001, 1002, 1003]
            result = production_blockchain_service.batch_verify_productions(production_ids)

            print(f"   ✅ Batch verification completed")
            print(f"   Processing Time: {result.processing_time:.2f}s")
            print(f"   Successful: {len(result.successful_verifications)}")
            print(f"   Total Cost: ${result.total_cost_usd:.6f}")

            self.test_results.append(
                {
                    "test": "batch_verification",
                    "status": "passed",
                    "details": f"Time: {result.processing_time:.2f}s, Cost: ${result.total_cost_usd:.6f}",
                }
            )

        except Exception as e:
            print(f"   ❌ Batch verification failed: {e}")
            self.test_results.append({"test": "batch_verification", "status": "failed", "error": str(e)})

    def test_user_model(self):
        """Test that user model is working"""
        print("\n🧪 Testing User Model...")

        try:
            user, created = User.objects.get_or_create(
                email="test_blockchain_user@trazo.com", defaults={"first_name": "Test", "last_name": "User"}
            )
            print(f"   ✅ User model working: {user.email}")

            self.test_results.append({"test": "user_model", "status": "passed", "details": f"User: {user.email}"})

        except Exception as e:
            print(f"   ❌ User model failed: {e}")
            self.test_results.append({"test": "user_model", "status": "failed", "error": str(e)})

    def test_smart_contract_files(self):
        """Test that smart contract files exist"""
        print("\n🧪 Testing Smart Contract Files...")

        contract_files = [
            "contracts/CarbonVerification.sol",
            "contracts/CarbonCreditToken.sol",
            "contracts/deploy.js",
            "contracts/deploy_carbon_credit.js",
        ]

        files_found = 0
        for file_path in contract_files:
            if os.path.exists(file_path):
                files_found += 1
                print(f"   ✅ {file_path}")
            else:
                print(f"   ❌ {file_path} - Not found")

        if files_found == len(contract_files):
            self.test_results.append(
                {"test": "smart_contract_files", "status": "passed", "details": f"All {files_found} files found"}
            )
        else:
            self.test_results.append(
                {
                    "test": "smart_contract_files",
                    "status": "partial",
                    "details": f"{files_found}/{len(contract_files)} files found",
                }
            )

    def test_api_imports(self):
        """Test that API view imports work"""
        print("\n🧪 Testing API Imports...")

        try:
            from carbon.views import (
                batch_verify_productions,
                get_blockchain_service_stats,
                get_gas_optimization_analysis,
                mint_carbon_credits_batch,
            )

            print("   ✅ All new API endpoints imported successfully")

            self.test_results.append(
                {"test": "api_imports", "status": "passed", "details": "All new endpoints available"}
            )

        except ImportError as e:
            print(f"   ❌ API import failed: {e}")
            self.test_results.append({"test": "api_imports", "status": "failed", "error": str(e)})

    def run_all_tests(self):
        """Run all simplified tests"""
        start_time = time.time()

        # Run tests
        self.test_service_availability()
        self.test_gas_optimization()
        self.test_batch_verification()
        self.test_user_model()
        self.test_smart_contract_files()
        self.test_api_imports()

        # Generate summary
        self.generate_summary(time.time() - start_time)

    def generate_summary(self, total_time):
        """Generate test summary"""
        print("\n" + "=" * 50)
        print("📊 BLOCKCHAIN PRODUCTION TEST SUMMARY")
        print("=" * 50)

        passed = len([t for t in self.test_results if t["status"] == "passed"])
        failed = len([t for t in self.test_results if t["status"] == "failed"])
        partial = len([t for t in self.test_results if t["status"] == "partial"])

        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"⚠️ Partial: {partial}")
        print(f"🕐 Total Time: {total_time:.2f}s")

        success_rate = (passed + partial * 0.5) / len(self.test_results) * 100
        print(f"📈 Success Rate: {success_rate:.1f}%")

        print("\n🎯 Month 1, Week 3-4 Status:")

        deliverables = {
            "Production Blockchain Service": any(
                t["test"] == "service_availability" and t["status"] == "passed" for t in self.test_results
            ),
            "Gas Optimization": any(
                t["test"] == "gas_optimization" and t["status"] == "passed" for t in self.test_results
            ),
            "Batch Processing": any(
                t["test"] == "batch_verification" and t["status"] == "passed" for t in self.test_results
            ),
            "Smart Contracts": any(
                t["test"] == "smart_contract_files" and t["status"] in ["passed", "partial"] for t in self.test_results
            ),
            "API Integration": any(t["test"] == "api_imports" and t["status"] == "passed" for t in self.test_results),
            "Database Integration": any(
                t["test"] == "user_model" and t["status"] == "passed" for t in self.test_results
            ),
        }

        for deliverable, completed in deliverables.items():
            status = "✅" if completed else "❌"
            print(f"   {status} {deliverable}")

        completion_rate = sum(deliverables.values()) / len(deliverables) * 100
        print(f"\n🎯 Implementation Completeness: {completion_rate:.1f}%")

        if completion_rate >= 80:
            print("🎉 Month 1, Week 3-4 (Blockchain Production Readiness) - COMPLETED!")
        elif completion_rate >= 60:
            print("⚠️ Month 1, Week 3-4 - Mostly completed, minor issues to resolve")
        else:
            print("🚨 Month 1, Week 3-4 - Significant work remaining")

        print("\n🔗 Next Steps:")
        if not PRODUCTION_SERVICE_AVAILABLE:
            print("   1. Fix production blockchain service imports")
            print("   2. Ensure all dependencies are installed")
        print("   3. Deploy contracts to Polygon testnet/mainnet")
        print("   4. Configure production environment variables")
        print("   5. Proceed to Month 2: Voice & Mobile Enhancement")

        print("=" * 50)


if __name__ == "__main__":
    tester = SimpleBlockchainTester()
    tester.run_all_tests()
