#!/usr/bin/env python3
"""
Production Stress Test Runner

Comprehensive test runner for all production readiness edge cases and failure scenarios.
Orchestrates and executes all stress tests in a controlled manner with detailed reporting.
"""

import os
import sys
import time
import json
import subprocess
import threading
import logging
import traceback
import psutil
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, '/Users/oscarmunoz/dev/trazo/trazo-back')

# Import all test suites
from test_production_edge_cases import ProductionEdgeCaseTests
from test_circuit_breaker_stress import CircuitBreakerStressTests
from test_database_resilience import DatabaseResilienceTests
from test_security_edge_cases import SecurityEdgeCaseTests


class ProductionStressTestRunner:
    """Comprehensive production stress test runner"""
    
    def __init__(self):
        self.logger = self._setup_logging()
        self.start_time = datetime.now()
        self.system_metrics = SystemMetricsCollector()
        self.test_results = {}
        self.overall_status = "UNKNOWN"
        
    def _setup_logging(self):
        """Set up comprehensive logging"""
        logger = logging.getLogger("ProductionStressTests")
        logger.setLevel(logging.INFO)
        
        # Create logs directory if it doesn't exist
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # File handler for detailed logs
        file_handler = logging.FileHandler(
            log_dir / f"production_stress_tests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        file_handler.setLevel(logging.DEBUG)
        
        # Console handler for immediate feedback
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
        
    def run_all_stress_tests(self):
        """Run all production stress tests in sequence"""
        print("\n" + "="*80)
        print("🚀 PRODUCTION READINESS STRESS TESTING SUITE")
        print("="*80)
        print(f"Started at: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"System: {psutil.cpu_count()} CPUs, {psutil.virtual_memory().total // (1024**3)}GB RAM")
        print("="*80)
        
        # Start system monitoring
        monitoring_thread = threading.Thread(target=self.system_metrics.start_monitoring, daemon=True)
        monitoring_thread.start()
        
        # Define test suites to run
        test_suites = [
            ("Production Edge Cases", ProductionEdgeCaseTests),
            ("Circuit Breaker Stress", CircuitBreakerStressTests),
            ("Database Resilience", DatabaseResilienceTests),
            ("Security Edge Cases", SecurityEdgeCaseTests),
        ]
        
        # Run each test suite
        for suite_name, test_class in test_suites:
            self._run_test_suite(suite_name, test_class)
            
        # Stop monitoring
        self.system_metrics.stop_monitoring()
        
        # Generate comprehensive report
        self._generate_final_report()
        
    def _run_test_suite(self, suite_name, test_class):
        """Run individual test suite with error handling"""
        print(f"\n{'='*60}")
        print(f"🧪 RUNNING TEST SUITE: {suite_name}")
        print(f"{'='*60}")
        
        suite_start_time = time.time()
        
        try:
            # Create and run test suite
            test_suite = test_class()
            
            # Different test suites have different run methods
            if hasattr(test_suite, 'run_all_tests'):
                test_suite.run_all_tests()
            elif hasattr(test_suite, 'run_stress_tests'):
                test_suite.run_stress_tests()
            elif hasattr(test_suite, 'run_database_tests'):
                test_suite.run_database_tests()
            elif hasattr(test_suite, 'run_security_tests'):
                test_suite.run_security_tests()
            else:
                raise AttributeError(f"No suitable run method found for {test_class}")
                
            # Collect results
            if hasattr(test_suite, 'test_results'):
                suite_results = test_suite.test_results
            else:
                suite_results = {"status": "COMPLETED"}
                
            suite_duration = time.time() - suite_start_time
            
            self.test_results[suite_name] = {
                'status': 'COMPLETED',
                'duration': suite_duration,
                'results': suite_results,
                'start_time': suite_start_time,
                'metrics': self.system_metrics.get_current_metrics()
            }
            
            print(f"\n✅ {suite_name} COMPLETED ({suite_duration:.2f}s)")
            
        except Exception as e:
            suite_duration = time.time() - suite_start_time
            error_details = {
                'error': str(e),
                'traceback': traceback.format_exc(),
                'duration': suite_duration
            }
            
            self.test_results[suite_name] = {
                'status': 'FAILED',
                'duration': suite_duration,
                'error_details': error_details,
                'metrics': self.system_metrics.get_current_metrics()
            }
            
            print(f"\n❌ {suite_name} FAILED ({suite_duration:.2f}s)")
            print(f"Error: {str(e)}")
            self.logger.error(f"Test suite {suite_name} failed", exc_info=True)
            
        # Brief pause between test suites
        time.sleep(2)
        
    def _generate_final_report(self):
        """Generate comprehensive final report"""
        end_time = datetime.now()
        total_duration = (end_time - self.start_time).total_seconds()
        
        print("\n" + "="*80)
        print("📊 FINAL PRODUCTION STRESS TEST REPORT")
        print("="*80)
        
        # Test suite summary
        total_suites = len(self.test_results)
        completed_suites = len([r for r in self.test_results.values() if r['status'] == 'COMPLETED'])
        failed_suites = total_suites - completed_suites
        
        print(f"🕐 Duration: {total_duration:.2f}s ({total_duration/60:.1f} minutes)")
        print(f"📦 Test Suites: {total_suites} total, {completed_suites} completed, {failed_suites} failed")
        
        # Individual test summary
        total_individual_tests = 0
        passed_individual_tests = 0
        
        for suite_name, suite_result in self.test_results.items():
            print(f"\n📋 {suite_name}:")
            print(f"   Status: {suite_result['status']}")
            print(f"   Duration: {suite_result['duration']:.2f}s")
            
            if 'results' in suite_result:
                suite_tests = suite_result['results']
                if isinstance(suite_tests, dict):
                    suite_total = len(suite_tests)
                    suite_passed = len([r for r in suite_tests.values() if 
                                      (isinstance(r, dict) and r.get('status') == 'PASSED') or
                                      r == 'PASSED'])
                    
                    total_individual_tests += suite_total
                    passed_individual_tests += suite_passed
                    
                    print(f"   Individual Tests: {suite_passed}/{suite_total} passed")
                    
                    # Show failed tests
                    for test_name, test_result in suite_tests.items():
                        if isinstance(test_result, dict) and test_result.get('status') == 'FAILED':
                            print(f"     ❌ {test_name}: {test_result.get('error', 'Unknown error')}")
                            
        # Overall success rate
        if total_individual_tests > 0:
            success_rate = passed_individual_tests / total_individual_tests
            print(f"\n🎯 Overall Success Rate: {success_rate:.1%} ({passed_individual_tests}/{total_individual_tests})")
        else:
            success_rate = 0
            print(f"\n🎯 Overall Success Rate: Unable to calculate")
            
        # System performance during tests
        print(f"\n💾 System Performance:")
        final_metrics = self.system_metrics.get_summary()
        print(f"   CPU Usage: avg {final_metrics['cpu_avg']:.1f}%, max {final_metrics['cpu_max']:.1f}%")
        print(f"   Memory Usage: avg {final_metrics['memory_avg']:.1f}%, max {final_metrics['memory_max']:.1f}%")
        print(f"   Disk I/O: {final_metrics['disk_io_total']:.2f}MB")
        
        # Production readiness assessment
        self._assess_production_readiness(success_rate, completed_suites, total_suites, final_metrics)
        
        # Save detailed report
        self._save_detailed_report(total_duration, success_rate, final_metrics)
        
    def _assess_production_readiness(self, success_rate, completed_suites, total_suites, metrics):
        """Assess overall production readiness"""
        print(f"\n🚀 PRODUCTION READINESS ASSESSMENT:")
        print("-" * 40)
        
        # Calculate readiness score
        readiness_factors = {
            'test_completion': completed_suites / max(total_suites, 1),
            'test_success': success_rate,
            'system_stability': 1.0 - (metrics['cpu_max'] / 100.0) * 0.5,  # Penalize high CPU
            'memory_efficiency': 1.0 - (metrics['memory_max'] / 100.0) * 0.3,  # Penalize high memory
        }
        
        readiness_score = sum(readiness_factors.values()) / len(readiness_factors)
        
        print(f"📊 Readiness Factors:")
        for factor, score in readiness_factors.items():
            print(f"   {factor.replace('_', ' ').title()}: {score:.1%}")
            
        print(f"\n🎯 Overall Readiness Score: {readiness_score:.1%}")
        
        # Readiness assessment
        if readiness_score >= 0.9:
            self.overall_status = "EXCELLENT"
            recommendation = "✅ EXCELLENT - System is highly production-ready"
            next_steps = [
                "Deploy to production with confidence",
                "Monitor key metrics for first 24 hours",
                "Schedule regular stress testing"
            ]
        elif readiness_score >= 0.8:
            self.overall_status = "GOOD"
            recommendation = "✅ GOOD - System is production-ready with minor monitoring"
            next_steps = [
                "Address any failed tests before deployment",
                "Implement enhanced monitoring",
                "Plan gradual rollout"
            ]
        elif readiness_score >= 0.7:
            self.overall_status = "FAIR"
            recommendation = "⚠️  FAIR - Address key issues before production deployment"
            next_steps = [
                "Fix critical failed tests",
                "Optimize resource usage",
                "Implement additional safety measures"
            ]
        else:
            self.overall_status = "POOR"
            recommendation = "❌ POOR - Significant issues must be resolved"
            next_steps = [
                "Do not deploy to production",
                "Address all critical failures",
                "Re-run stress tests after fixes"
            ]
            
        print(f"\n{recommendation}")
        
        print(f"\n📋 Recommended Next Steps:")
        for i, step in enumerate(next_steps, 1):
            print(f"   {i}. {step}")
            
        # Critical issues summary
        self._summarize_critical_issues()
        
    def _summarize_critical_issues(self):
        """Summarize critical issues found during testing"""
        print(f"\n🚨 Critical Issues Summary:")
        
        critical_issues = []
        
        for suite_name, suite_result in self.test_results.items():
            if suite_result['status'] == 'FAILED':
                critical_issues.append(f"Test suite failure: {suite_name}")
                
            if 'results' in suite_result:
                for test_name, test_result in suite_result['results'].items():
                    if isinstance(test_result, dict) and test_result.get('status') == 'FAILED':
                        error = test_result.get('error', 'Unknown error')
                        if any(keyword in error.lower() for keyword in ['security', 'sql', 'xss', 'auth']):
                            critical_issues.append(f"Security issue in {test_name}")
                        elif any(keyword in error.lower() for keyword in ['database', 'connection', 'deadlock']):
                            critical_issues.append(f"Database issue in {test_name}")
                        elif any(keyword in error.lower() for keyword in ['circuit', 'timeout', 'api']):
                            critical_issues.append(f"Service reliability issue in {test_name}")
                            
        if critical_issues:
            for issue in critical_issues[:10]:  # Show top 10
                print(f"   🔴 {issue}")
            if len(critical_issues) > 10:
                print(f"   ... and {len(critical_issues) - 10} more issues")
        else:
            print("   ✅ No critical issues detected")
            
    def _save_detailed_report(self, total_duration, success_rate, metrics):
        """Save detailed report to file"""
        report_data = {
            'timestamp': self.start_time.isoformat(),
            'duration_seconds': total_duration,
            'overall_status': self.overall_status,
            'success_rate': success_rate,
            'system_metrics': metrics,
            'test_results': self.test_results,
            'summary': {
                'total_suites': len(self.test_results),
                'completed_suites': len([r for r in self.test_results.values() if r['status'] == 'COMPLETED']),
                'total_individual_tests': sum(
                    len(r.get('results', {})) for r in self.test_results.values()
                    if isinstance(r.get('results'), dict)
                )
            }
        }
        
        # Save to JSON file
        report_file = Path("logs") / f"production_stress_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report_data, f, indent=2, default=str)
            
        print(f"\n💾 Detailed report saved to: {report_file}")
        
        # Also save a human-readable summary
        summary_file = Path("logs") / f"production_stress_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(summary_file, 'w') as f:
            f.write("PRODUCTION STRESS TEST SUMMARY\n")
            f.write("="*50 + "\n\n")
            f.write(f"Timestamp: {self.start_time}\n")
            f.write(f"Duration: {total_duration:.2f}s\n")
            f.write(f"Overall Status: {self.overall_status}\n")
            f.write(f"Success Rate: {success_rate:.1%}\n\n")
            
            f.write("TEST SUITE RESULTS:\n")
            f.write("-"*30 + "\n")
            for suite_name, result in self.test_results.items():
                f.write(f"{suite_name}: {result['status']} ({result['duration']:.2f}s)\n")
                
        print(f"📄 Summary report saved to: {summary_file}")


class SystemMetricsCollector:
    """Collect system metrics during testing"""
    
    def __init__(self):
        self.metrics = []
        self.monitoring = False
        
    def start_monitoring(self):
        """Start collecting system metrics"""
        self.monitoring = True
        
        while self.monitoring:
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                disk_io = psutil.disk_io_counters()
                
                metric = {
                    'timestamp': time.time(),
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'memory_used_mb': memory.used / (1024**2),
                    'disk_read_mb': disk_io.read_bytes / (1024**2) if disk_io else 0,
                    'disk_write_mb': disk_io.write_bytes / (1024**2) if disk_io else 0,
                }
                
                self.metrics.append(metric)
                
            except Exception as e:
                logging.error(f"Error collecting metrics: {e}")
                
            time.sleep(5)  # Collect every 5 seconds
            
    def stop_monitoring(self):
        """Stop collecting system metrics"""
        self.monitoring = False
        
    def get_current_metrics(self):
        """Get current system metrics snapshot"""
        if not self.metrics:
            return {}
            
        latest = self.metrics[-1]
        return {
            'cpu_percent': latest['cpu_percent'],
            'memory_percent': latest['memory_percent'],
            'memory_used_mb': latest['memory_used_mb']
        }
        
    def get_summary(self):
        """Get summary of all collected metrics"""
        if not self.metrics:
            return {
                'cpu_avg': 0, 'cpu_max': 0,
                'memory_avg': 0, 'memory_max': 0,
                'disk_io_total': 0
            }
            
        cpu_values = [m['cpu_percent'] for m in self.metrics]
        memory_values = [m['memory_percent'] for m in self.metrics]
        
        first_disk = self.metrics[0]['disk_read_mb'] + self.metrics[0]['disk_write_mb']
        last_disk = self.metrics[-1]['disk_read_mb'] + self.metrics[-1]['disk_write_mb']
        
        return {
            'cpu_avg': sum(cpu_values) / len(cpu_values),
            'cpu_max': max(cpu_values),
            'memory_avg': sum(memory_values) / len(memory_values),
            'memory_max': max(memory_values),
            'disk_io_total': last_disk - first_disk
        }


def main():
    """Main entry point for production stress testing"""
    print("🚀 Initializing Production Stress Test Runner...")
    
    # Check requirements
    try:
        import django
        import psutil
        print("✅ All required dependencies available")
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        sys.exit(1)
        
    # Check Django setup
    try:
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
        django.setup()
        print("✅ Django environment configured")
    except Exception as e:
        print(f"❌ Django setup failed: {e}")
        sys.exit(1)
        
    # Run the stress tests
    runner = ProductionStressTestRunner()
    runner.run_all_stress_tests()
    
    print(f"\n🏁 Production stress testing completed with status: {runner.overall_status}")
    
    # Exit with appropriate code
    if runner.overall_status in ['EXCELLENT', 'GOOD']:
        sys.exit(0)
    elif runner.overall_status == 'FAIR':
        sys.exit(1)
    else:  # POOR
        sys.exit(2)


if __name__ == "__main__":
    main()