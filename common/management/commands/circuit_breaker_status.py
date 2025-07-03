"""
Django management command for circuit breaker monitoring and management
Usage: python manage.py circuit_breaker_status [--reset] [--service=SERVICE] [--health-check]
"""

import json
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from carbon.services.circuit_breaker_enhanced import circuit_manager
from common.services.external_api_manager import api_manager


class Command(BaseCommand):
    help = 'Monitor and manage circuit breaker status for external APIs'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--service',
            type=str,
            help='Specific service to check (usda_nass, stripe, polygon_rpc, etc.)'
        )
        
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Reset circuit breakers to closed state'
        )
        
        parser.add_argument(
            '--force-open',
            type=str,
            help='Force a specific service circuit breaker to open state'
        )
        
        parser.add_argument(
            '--health-check',
            action='store_true',
            help='Perform comprehensive health check of all external services'
        )
        
        parser.add_argument(
            '--metrics',
            action='store_true',
            help='Show detailed metrics for all circuit breakers'
        )
        
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output results in JSON format'
        )
        
        parser.add_argument(
            '--watch',
            action='store_true',
            help='Watch mode - continuously monitor circuit breaker status'
        )
    
    def handle(self, *args, **options):
        try:
            service = options.get('service')
            reset = options.get('reset')
            force_open = options.get('force_open')
            health_check = options.get('health_check')
            show_metrics = options.get('metrics')
            json_output = options.get('json')
            watch_mode = options.get('watch')
            
            if watch_mode:
                self.watch_circuit_breakers()
                return
            
            if reset:
                self.handle_reset(service)
                return
            
            if force_open:
                self.handle_force_open(force_open)
                return
            
            if health_check:
                self.handle_health_check(json_output)
                return
            
            if show_metrics:
                self.handle_metrics(service, json_output)
                return
            
            # Default: show circuit breaker status
            self.handle_status(service, json_output)
            
        except Exception as e:
            raise CommandError(f'Command failed: {e}')
    
    def handle_status(self, service_name: str = None, json_output: bool = False):
        """Show circuit breaker status"""
        if not json_output:
            self.stdout.write(self.style.HTTP_INFO('🔍 Circuit Breaker Status Report\n'))
        
        try:
            all_metrics = circuit_manager.get_all_metrics()
            health_summary = circuit_manager.get_health_summary()
            
            if service_name:
                # Filter for specific service
                filtered_metrics = {
                    name: metrics for name, metrics in all_metrics.items()
                    if service_name in name.lower()
                }
                if not filtered_metrics:
                    self.stdout.write(
                        self.style.WARNING(f"No circuit breakers found for service: {service_name}")
                    )
                    return
                all_metrics = filtered_metrics
            
            if json_output:
                output = {
                    'health_summary': health_summary,
                    'circuit_breakers': all_metrics,
                    'timestamp': timezone.now().isoformat()
                }
                self.stdout.write(json.dumps(output, indent=2))
                return
            
            # Console output
            self.stdout.write(f"Overall Health: {self._colorize_health(health_summary['overall_health'])}")
            self.stdout.write(f"Total Circuits: {health_summary['total_circuits']}")
            self.stdout.write(f"Open: {health_summary['open_circuits']} | "
                            f"Half-Open: {health_summary['half_open_circuits']} | "
                            f"Closed: {health_summary['closed_circuits']}\n")
            
            # Circuit breaker details
            self.stdout.write(f"{'Service':<25} {'State':<12} {'Success Rate':<12} {'Requests':<10} {'Avg Response':<12} {'Last Failure':<20}")
            self.stdout.write("-" * 120)
            
            for name, metrics in all_metrics.items():
                state = metrics['state']
                success_rate = f"{metrics['success_rate_percent']:.1f}%"
                requests = str(metrics['total_requests'])
                avg_response = f"{metrics['average_response_time_ms']:.0f}ms"
                last_failure = metrics.get('last_failure_time', 'Never')
                
                if last_failure and last_failure != 'Never':
                    try:
                        dt = timezone.datetime.fromisoformat(last_failure.replace('Z', '+00:00'))
                        last_failure = dt.strftime('%m-%d %H:%M')
                    except:
                        last_failure = 'Unknown'
                
                # Color coding
                if state == 'open':
                    style = self.style.ERROR
                elif state == 'half_open':
                    style = self.style.WARNING
                elif float(metrics['success_rate_percent']) < 90:
                    style = self.style.NOTICE
                else:
                    style = self.style.SUCCESS
                
                line = f"{name:<25} {state:<12} {success_rate:<12} {requests:<10} {avg_response:<12} {last_failure:<20}"
                self.stdout.write(style(line))
            
            # Summary statistics
            if all_metrics:
                total_requests = sum(m['total_requests'] for m in all_metrics.values())
                total_failures = sum(m['failed_requests'] for m in all_metrics.values())
                overall_success = ((total_requests - total_failures) / total_requests * 100) if total_requests > 0 else 0
                
                self.stdout.write("\n" + "=" * 120)
                self.stdout.write(f"Summary: {len(all_metrics)} services, {total_requests} total requests, {overall_success:.1f}% success rate")
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to get circuit breaker status: {e}"))
    
    def handle_reset(self, service_name: str = None):
        """Reset circuit breakers"""
        try:
            if service_name:
                # Reset specific service
                circuit_breaker = None
                all_metrics = circuit_manager.get_all_metrics()
                
                # Find matching circuit breaker
                for name in all_metrics.keys():
                    if service_name.lower() in name.lower():
                        circuit_breaker = circuit_manager.circuit_breakers.get(name)
                        break
                
                if circuit_breaker:
                    circuit_breaker.reset()
                    self.stdout.write(
                        self.style.SUCCESS(f"✅ Reset circuit breaker for {service_name}")
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f"⚠️  No circuit breaker found for service: {service_name}")
                    )
            else:
                # Reset all circuit breakers
                circuit_manager.reset_all()
                self.stdout.write(
                    self.style.SUCCESS("✅ Reset all circuit breakers")
                )
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to reset circuit breakers: {e}"))
    
    def handle_force_open(self, service_name: str):
        """Force circuit breaker to open state"""
        try:
            all_metrics = circuit_manager.get_all_metrics()
            
            # Find matching circuit breaker
            circuit_breaker = None
            for name in all_metrics.keys():
                if service_name.lower() in name.lower():
                    circuit_breaker = circuit_manager.circuit_breakers.get(name)
                    break
            
            if circuit_breaker:
                circuit_breaker.force_open()
                self.stdout.write(
                    self.style.WARNING(f"🚨 Forced circuit breaker OPEN for {service_name}")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"❌ No circuit breaker found for service: {service_name}")
                )
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to force open circuit breaker: {e}"))
    
    def handle_health_check(self, json_output: bool = False):
        """Perform comprehensive health check"""
        if not json_output:
            self.stdout.write(self.style.HTTP_INFO('🏥 External API Health Check\n'))
        
        try:
            health_data = api_manager.get_service_health()
            
            if json_output:
                self.stdout.write(json.dumps(health_data, indent=2))
                return
            
            # Console output
            overall_status = health_data['overall_status']
            self.stdout.write(f"Overall Status: {self._colorize_health(overall_status)}")
            
            if health_data.get('unhealthy_services'):
                self.stdout.write(
                    self.style.ERROR(f"🚨 Unhealthy Services: {', '.join(health_data['unhealthy_services'])}")
                )
            
            if health_data.get('degraded_services'):
                self.stdout.write(
                    self.style.WARNING(f"⚠️  Degraded Services: {', '.join(health_data['degraded_services'])}")
                )
            
            self.stdout.write("\nService Details:")
            self.stdout.write(f"{'Service':<20} {'Status':<12} {'Circuit':<12} {'Success Rate':<12} {'Avg Response':<12}")
            self.stdout.write("-" * 80)
            
            for service_name, service_health in health_data['services'].items():
                status = service_health['status']
                circuit_state = service_health['circuit_state']
                success_rate = f"{service_health['success_rate']:.1f}%"
                avg_response = f"{service_health['average_response_time_ms']:.0f}ms"
                
                # Color coding
                if status == 'unhealthy':
                    style = self.style.ERROR
                elif status == 'degraded':
                    style = self.style.WARNING
                elif status == 'recovering':
                    style = self.style.NOTICE
                else:
                    style = self.style.SUCCESS
                
                line = f"{service_name:<20} {status:<12} {circuit_state:<12} {success_rate:<12} {avg_response:<12}"
                self.stdout.write(style(line))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Health check failed: {e}"))
    
    def handle_metrics(self, service_name: str = None, json_output: bool = False):
        """Show detailed metrics"""
        try:
            all_metrics = circuit_manager.get_all_metrics()
            
            if service_name:
                filtered_metrics = {
                    name: metrics for name, metrics in all_metrics.items()
                    if service_name.lower() in name.lower()
                }
                all_metrics = filtered_metrics
            
            if json_output:
                self.stdout.write(json.dumps(all_metrics, indent=2))
                return
            
            if not json_output:
                self.stdout.write(self.style.HTTP_INFO('📊 Circuit Breaker Detailed Metrics\n'))
            
            for name, metrics in all_metrics.items():
                self.stdout.write(f"\n{self.style.HTTP_INFO(f'=== {name} ===')}")
                self.stdout.write(f"State: {metrics['state']}")
                self.stdout.write(f"Total Requests: {metrics['total_requests']}")
                self.stdout.write(f"Successful: {metrics['successful_requests']}")
                self.stdout.write(f"Failed: {metrics['failed_requests']}")
                self.stdout.write(f"Success Rate: {metrics['success_rate_percent']:.2f}%")
                self.stdout.write(f"Timeouts: {metrics['timeouts']}")
                self.stdout.write(f"Circuit Opens: {metrics['circuit_opens']}")
                self.stdout.write(f"Circuit Closes: {metrics['circuit_closes']}")
                self.stdout.write(f"Fallback Uses: {metrics['fallback_uses']}")
                self.stdout.write(f"Average Response Time: {metrics['average_response_time_ms']:.2f}ms")
                
                if metrics.get('error_types'):
                    self.stdout.write("Error Types:")
                    for error_type, count in metrics['error_types'].items():
                        self.stdout.write(f"  {error_type}: {count}")
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Failed to get metrics: {e}"))
    
    def watch_circuit_breakers(self):
        """Watch mode - continuously monitor circuit breakers"""
        import time
        
        self.stdout.write(self.style.HTTP_INFO("👁️  Watching circuit breakers (Ctrl+C to stop)...\n"))
        
        try:
            while True:
                # Clear screen (simple version)
                self.stdout.write("\033[2J\033[H")
                
                # Show timestamp
                now = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
                self.stdout.write(f"Last Update: {now}\n")
                
                # Show status
                self.handle_status()
                
                # Wait before next update
                time.sleep(5)
                
        except KeyboardInterrupt:
            self.stdout.write("\n👋 Watch mode stopped")
    
    def _colorize_health(self, status: str) -> str:
        """Apply color to health status"""
        if status == 'healthy':
            return self.style.SUCCESS(status.upper())
        elif status == 'degraded':
            return self.style.WARNING(status.upper())
        elif status == 'recovering':
            return self.style.NOTICE(status.upper())
        else:
            return self.style.ERROR(status.upper())