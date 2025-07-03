"""
Django management command for database optimization
Usage: python manage.py optimize_database [--analyze] [--create-indexes] [--model=MODEL] [--dry-run]
"""

import json
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from common.services.database_optimizer import database_optimizer


class Command(BaseCommand):
    help = 'Analyze and optimize database performance'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            type=str,
            help='Specific model to analyze (e.g., CarbonEntry, History)'
        )
        
        parser.add_argument(
            '--analyze',
            action='store_true',
            help='Perform database analysis and show recommendations'
        )
        
        parser.add_argument(
            '--create-indexes',
            action='store_true',
            help='Create recommended indexes'
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show SQL statements without executing them'
        )
        
        parser.add_argument(
            '--report',
            action='store_true',
            help='Generate comprehensive performance report'
        )
        
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output results in JSON format'
        )
        
        parser.add_argument(
            '--priority',
            choices=['high', 'medium', 'low'],
            help='Only show recommendations with specified priority'
        )
    
    def handle(self, *args, **options):
        try:
            model = options.get('model')
            analyze = options.get('analyze')
            create_indexes = options.get('create_indexes')
            dry_run = options.get('dry_run', True)
            show_report = options.get('report')
            json_output = options.get('json')
            priority_filter = options.get('priority')
            
            if show_report:
                self.handle_performance_report(json_output)
                return
            
            if analyze or not create_indexes:
                self.handle_analysis(model, json_output, priority_filter)
                
                if create_indexes:
                    self.stdout.write("\n" + "="*60)
                    self.handle_index_creation(model, dry_run, json_output)
            
            elif create_indexes:
                self.handle_index_creation(model, dry_run, json_output)
            
        except Exception as e:
            raise CommandError(f'Database optimization failed: {e}')
    
    def handle_analysis(self, model_name: str = None, json_output: bool = False, 
                       priority_filter: str = None):
        """Handle database analysis"""
        if not json_output:
            self.stdout.write(self.style.HTTP_INFO('🔍 Database Performance Analysis\n'))
        
        try:
            analysis = database_optimizer.analyze_query_performance(model_name)
            
            if 'error' in analysis:
                self.stdout.write(self.style.ERROR(f"❌ Analysis failed: {analysis['error']}"))
                return
            
            if json_output:
                self.stdout.write(json.dumps(analysis, indent=2))
                return
            
            # Console output
            self.show_analysis_summary(analysis)
            self.show_model_details(analysis, priority_filter)
            self.show_recommendations(analysis, priority_filter)
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Analysis failed: {e}"))
    
    def show_analysis_summary(self, analysis: dict):
        """Show analysis summary"""
        models_count = len(analysis.get('models_analyzed', []))
        issues_count = len(analysis.get('performance_issues', []))
        recommendations_count = len(analysis.get('index_recommendations', []))
        overall_health = analysis.get('overall_health', 'unknown')
        
        self.stdout.write(f"Database Vendor: {analysis.get('database_vendor', 'unknown')}")
        self.stdout.write(f"Overall Health: {self._colorize_health(overall_health)}")
        self.stdout.write(f"Models Analyzed: {models_count}")
        self.stdout.write(f"Performance Issues: {issues_count}")
        self.stdout.write(f"Index Recommendations: {recommendations_count}")
        
        # Database statistics
        stats = analysis.get('query_statistics', {})
        if stats:
            self.stdout.write(f"\nDatabase Statistics:")
            for key, value in stats.items():
                if value:
                    self.stdout.write(f"  {key}: {value}")
        
        self.stdout.write("")
    
    def show_model_details(self, analysis: dict, priority_filter: str = None):
        """Show detailed model analysis"""
        models = analysis.get('models_analyzed', [])
        if not models:
            return
        
        self.stdout.write("📊 Model Analysis Details:")
        self.stdout.write(f"{'Model':<30} {'Records':<10} {'Size (MB)':<10} {'Indexes':<8} {'Issues':<8}")
        self.stdout.write("-" * 80)
        
        for model in models:
            model_name = model.get('model', 'Unknown')[:29]
            record_count = f"{model.get('record_count', 0):,}"
            table_size = f"{model.get('table_size_mb', 0):.1f}"
            index_count = len(model.get('existing_indexes', []))
            issue_count = len(model.get('issues', []))
            
            # Color coding based on issues
            if issue_count > 0:
                issues_critical = any(issue.get('severity') == 'critical' for issue in model.get('issues', []))
                if issues_critical:
                    style = self.style.ERROR
                else:
                    style = self.style.WARNING
            else:
                style = self.style.SUCCESS
            
            line = f"{model_name:<30} {record_count:<10} {table_size:<10} {index_count:<8} {issue_count:<8}"
            self.stdout.write(style(line))
        
        self.stdout.write("")
    
    def show_recommendations(self, analysis: dict, priority_filter: str = None):
        """Show index recommendations"""
        recommendations = analysis.get('index_recommendations', [])
        
        if priority_filter:
            recommendations = [r for r in recommendations if r.get('priority') == priority_filter]
        
        if not recommendations:
            self.stdout.write("✅ No index recommendations found")
            return
        
        self.stdout.write(f"💡 Index Recommendations ({len(recommendations)} total):")
        
        # Group by priority
        high_priority = [r for r in recommendations if r.get('priority') == 'high']
        medium_priority = [r for r in recommendations if r.get('priority') == 'medium']
        low_priority = [r for r in recommendations if r.get('priority') == 'low']
        
        if high_priority:
            self.stdout.write(self.style.ERROR("\n🚨 HIGH PRIORITY:"))
            self._show_recommendation_group(high_priority)
        
        if medium_priority:
            self.stdout.write(self.style.WARNING("\n⚠️  MEDIUM PRIORITY:"))
            self._show_recommendation_group(medium_priority)
        
        if low_priority:
            self.stdout.write(self.style.NOTICE("\n💡 LOW PRIORITY:"))
            self._show_recommendation_group(low_priority)
    
    def _show_recommendation_group(self, recommendations: list):
        """Show a group of recommendations"""
        for i, rec in enumerate(recommendations[:10], 1):  # Show max 10 per group
            field = rec.get('field', rec.get('fields', 'unknown'))
            reason = rec.get('reason', 'Performance optimization')
            rec_type = rec.get('type', 'index')
            
            self.stdout.write(f"  {i}. {field} ({rec_type})")
            self.stdout.write(f"     Reason: {reason}")
            
            if len(recommendations) > 10:
                self.stdout.write(f"     ... and {len(recommendations) - 10} more")
    
    def handle_index_creation(self, model_name: str = None, dry_run: bool = True, 
                            json_output: bool = False):
        """Handle index creation"""
        if not json_output:
            mode = "DRY RUN" if dry_run else "LIVE"
            self.stdout.write(self.style.HTTP_INFO(f'🔧 Index Creation ({mode})\n'))
        
        try:
            # Get recommendations
            analysis = database_optimizer.analyze_query_performance(model_name)
            
            if 'error' in analysis:
                self.stdout.write(self.style.ERROR(f"❌ Failed to get recommendations: {analysis['error']}"))
                return
            
            recommendations = analysis.get('index_recommendations', [])
            
            if not recommendations:
                self.stdout.write("✅ No index recommendations to implement")
                return
            
            # Create indexes
            results = database_optimizer.create_recommended_indexes(recommendations, dry_run)
            
            if json_output:
                self.stdout.write(json.dumps(results, indent=2))
                return
            
            # Console output
            self.show_index_results(results, dry_run)
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Index creation failed: {e}"))
    
    def show_index_results(self, results: dict, dry_run: bool):
        """Show index creation results"""
        created = results.get('created_indexes', [])
        failed = results.get('failed_indexes', [])
        skipped = results.get('skipped_indexes', [])
        
        if dry_run:
            self.stdout.write(f"📋 SQL Statements to Execute ({len(created)} total):")
            for i, index in enumerate(created, 1):
                self.stdout.write(f"{i}. {index['sql']}")
            
            if created:
                self.stdout.write(f"\n💡 Run with --create-indexes (without --dry-run) to execute these statements")
        else:
            self.stdout.write(f"✅ Successfully created: {len(created)} indexes")
            self.stdout.write(f"⚠️  Skipped (already exist): {len(skipped)} indexes")
            self.stdout.write(f"❌ Failed: {len(failed)} indexes")
            
            if failed:
                self.stdout.write("\nFailed indexes:")
                for failure in failed:
                    self.stdout.write(f"  - {failure['sql']}")
                    self.stdout.write(f"    Error: {failure['error']}")
    
    def handle_performance_report(self, json_output: bool = False):
        """Handle performance report generation"""
        if not json_output:
            self.stdout.write(self.style.HTTP_INFO('📊 Database Performance Report\n'))
        
        try:
            report = database_optimizer.get_query_performance_report()
            
            if json_output:
                self.stdout.write(json.dumps(report, indent=2))
                return
            
            # Console output
            self.show_performance_report(report)
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Report generation failed: {e}"))
    
    def show_performance_report(self, report: dict):
        """Show performance report"""
        health = report.get('database_health', {})
        summary = report.get('performance_summary', {})
        issues = report.get('critical_issues', [])
        recommendations = report.get('recommendations', [])
        index_opt = report.get('index_optimization', {})
        
        # Health status
        status = health.get('overall_status', 'unknown')
        self.stdout.write(f"Overall Health: {self._colorize_health(status)}")
        self.stdout.write(f"Models Analyzed: {health.get('models_analyzed', 0)}")
        self.stdout.write(f"Total Issues: {health.get('total_issues', 0)}")
        
        # Performance summary
        self.stdout.write(f"\n📈 Performance Summary:")
        self.stdout.write(f"  Total Records: {summary.get('total_records', 0):,}")
        self.stdout.write(f"  Total Size: {summary.get('total_size_mb', 0):.2f} MB")
        self.stdout.write(f"  Average Table Size: {summary.get('average_table_size_mb', 0):.2f} MB")
        self.stdout.write(f"  Large Tables: {summary.get('large_tables_count', 0)}")
        
        # Critical issues
        if issues:
            self.stdout.write(f"\n🚨 Critical Issues ({len(issues)}):")
            for i, issue in enumerate(issues[:5], 1):  # Show top 5
                severity = issue.get('severity', 'unknown')
                description = issue.get('description', 'No description')
                self.stdout.write(f"  {i}. [{severity.upper()}] {description}")
        
        # Index optimization
        self.stdout.write(f"\n🔧 Index Optimization Summary:")
        self.stdout.write(f"  Total Recommendations: {index_opt.get('total_recommendations', 0)}")
        self.stdout.write(f"  High Priority: {index_opt.get('high_priority', 0)}")
        self.stdout.write(f"  Foreign Key Indexes: {index_opt.get('foreign_key_indexes', 0)}")
        self.stdout.write(f"  Composite Indexes: {index_opt.get('composite_indexes', 0)}")
        self.stdout.write(f"  Text Search Indexes: {index_opt.get('text_search_indexes', 0)}")
        
        # Recommendations
        if recommendations:
            self.stdout.write(f"\n💡 Top Recommendations:")
            for i, rec in enumerate(recommendations[:5], 1):
                field = rec.get('field', rec.get('fields', 'unknown'))
                priority = rec.get('priority', 'medium')
                reason = rec.get('reason', 'Performance optimization')
                self.stdout.write(f"  {i}. {field} [{priority}] - {reason}")
    
    def _colorize_health(self, status: str) -> str:
        """Apply color to health status"""
        if status == 'good':
            return self.style.SUCCESS(status.upper())
        elif status == 'degraded':
            return self.style.WARNING(status.upper())
        else:
            return self.style.ERROR(status.upper())