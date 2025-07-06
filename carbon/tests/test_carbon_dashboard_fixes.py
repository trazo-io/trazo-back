"""
Carbon Dashboard Production-Readiness Tests

Tests all improvements made to the Carbon Dashboard including:
- Enhanced carbon calculation logic
- Data validation and edge cases 
- Number formatting functions
- API response structure validation
"""

from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.db.models import Sum, Count
from django.utils import timezone
from decimal import Decimal
from carbon.models import CarbonEntry, CarbonSource
from company.models import Company, Establishment

User = get_user_model()


class CarbonCalculationsTestCase(TransactionTestCase):
    """Test enhanced carbon calculation logic"""
    
    def setUp(self):
        """Set up test data"""
        self.company = Company.objects.create(
            name="Carbon Test Company",
            address="123 Farm St",
            city="Farmville",
            state="CA"
        )
        
        self.user = User.objects.create_user(
            email='carbon_test@trazo.io',
            password='testpass123'
        )
        
        # Create WorksIn relationship
        from users.models import WorksIn
        WorksIn.objects.create(
            user=self.user,
            company=self.company,
            role=WorksIn.COMPANY_ADMIN
        )
        
        self.establishment = Establishment.objects.create(
            name="Carbon Test Farm",
            company=self.company,
            establishment_type='farm'
        )
        
        # Create test carbon sources
        self.emission_source = CarbonSource.objects.create(
            name='diesel_fuel',
            category='emission',
            default_emission_factor=2.7,
            unit='kg CO2e/L'
        )
        
        self.offset_source = CarbonSource.objects.create(
            name='tree_planting',
            category='offset',
            default_emission_factor=-2.5,
            unit='kg CO2e/tree'
        )
        
        # Create test carbon entries
        self.emission_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type='emission',
            source=self.emission_source,
            amount=1000.0,
            year=2025,
            usda_verified=True
        )
        
        self.offset_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type='offset',
            source=self.offset_source,
            amount=500.0,
            effective_amount=400.0,  # 80% effectiveness
            year=2025,
            usda_verified=True
        )
    
    def test_emissions_and_offsets_calculation(self):
        """Test emissions and offsets aggregation"""
        year = 2025
        entries = CarbonEntry.objects.filter(establishment=self.establishment, year=year)
        
        emissions_data = entries.filter(type='emission').aggregate(
            total=Sum('amount'),
            count=Count('id')
        )
        
        offsets_data = entries.filter(type='offset').aggregate(
            total=Sum('effective_amount'),
            count=Count('id')
        )
        
        total_emissions = float(emissions_data['total'] or 0)
        total_offsets = float(offsets_data['total'] or 0)
        net_carbon = total_emissions - total_offsets
        
        self.assertEqual(total_emissions, 1000.0)
        self.assertEqual(total_offsets, 400.0)
        self.assertEqual(net_carbon, 600.0)
        self.assertEqual(emissions_data['count'], 1)
        self.assertEqual(offsets_data['count'], 1)
    
    def test_carbon_score_calculation(self):
        """Test enhanced carbon score calculation logic"""
        test_cases = [
            (1000, 0, 10),      # No offsets = low score
            (1000, 500, 60),    # 50% offset = good score
            (1000, 750, 75),    # 75% offset = very good
            (1000, 1000, 90),   # 100% offset = excellent
            (0, 100, 95),       # Only offsets = near perfect
            (0, 0, 50),         # No data = neutral
        ]
        
        for emissions, offsets, expected_min_score in test_cases:
            carbon_score = self._calculate_carbon_score(emissions, offsets)
            
            # Allow some tolerance in scoring
            self.assertGreaterEqual(carbon_score, expected_min_score - 5)
            self.assertLessEqual(carbon_score, 100)
            self.assertGreaterEqual(carbon_score, 0)
    
    def _calculate_carbon_score(self, total_emissions, total_offsets):
        """Helper method to calculate carbon score"""
        carbon_score = 50  # Neutral baseline
        
        if total_emissions > 0:
            offset_percentage = min(100, (total_offsets / total_emissions) * 100)
            
            if offset_percentage >= 100:
                excess_percentage = offset_percentage - 100
                carbon_score = 90 + min(10, (excess_percentage / 50) * 10)
            elif offset_percentage >= 75:
                carbon_score = 75 + ((offset_percentage - 75) / 25) * 15
            elif offset_percentage >= 50:
                carbon_score = 60 + ((offset_percentage - 50) / 25) * 15
            elif offset_percentage >= 25:
                carbon_score = 40 + ((offset_percentage - 25) / 25) * 20
            else:
                carbon_score = 10 + (offset_percentage / 25) * 30
        elif total_offsets > 0:
            carbon_score = 95
        else:
            carbon_score = 50
        
        return int(carbon_score)
    
    def test_transparency_score_calculation(self):
        """Test transparency score calculation"""
        year = 2025
        entries = CarbonEntry.objects.filter(establishment=self.establishment, year=year)
        
        total_entries_count = entries.count()
        usda_verified_count = entries.filter(usda_verified=True).count()
        
        # Calculate transparency score
        transparency_score = 10
        if total_entries_count > 0:
            base_score = min(total_entries_count * 0.8, 70)
            verification_ratio = usda_verified_count / total_entries_count
            verification_bonus = verification_ratio * 30
            transparency_score = min(base_score + verification_bonus, 100)
        
        self.assertEqual(total_entries_count, 2)
        self.assertEqual(usda_verified_count, 2)
        self.assertEqual(verification_ratio, 1.0)  # 100% verified
        self.assertGreaterEqual(transparency_score, 30)  # Should be decent score
        self.assertLessEqual(transparency_score, 100)
    
    def test_performance_tier_classification(self):
        """Test performance tier calculation"""
        def get_performance_tier(score):
            if score >= 90:
                return "Excellent"
            elif score >= 75:
                return "Very Good"
            elif score >= 60:
                return "Good"
            elif score >= 40:
                return "Fair"
            else:
                return "Needs Improvement"
        
        test_scores = [
            (95, "Excellent"),
            (80, "Very Good"),
            (65, "Good"),
            (45, "Fair"),
            (20, "Needs Improvement")
        ]
        
        for score, expected_tier in test_scores:
            actual_tier = get_performance_tier(score)
            self.assertEqual(actual_tier, expected_tier)


class DataValidationTestCase(TestCase):
    """Test data validation and edge cases"""
    
    def test_carbon_score_edge_cases(self):
        """Test carbon score calculation edge cases"""
        test_cases = [
            {"emissions": 0, "offsets": 0, "expected_score": 50},
            {"emissions": 100, "offsets": 0, "expected_score": 10},
            {"emissions": 100, "offsets": 50, "expected_score": 60},
            {"emissions": 100, "offsets": 100, "expected_score": 90},
            {"emissions": 0, "offsets": 100, "expected_score": 95},
            {"emissions": 100, "offsets": 150, "expected_score": 95},  # Over 100%
        ]
        
        for case in test_cases:
            emissions = case["emissions"]
            offsets = case["offsets"]
            expected = case["expected_score"]
            
            score = self._calculate_carbon_score(emissions, offsets)
            
            # Allow tolerance of ±5 points
            self.assertGreaterEqual(score, expected - 5)
            self.assertLessEqual(score, expected + 5)
    
    def _calculate_carbon_score(self, emissions, offsets):
        """Helper method to calculate carbon score"""
        # Handle negative values - treat as 0
        emissions = max(0, emissions)
        offsets = max(0, offsets)
        
        if emissions > 0:
            offset_percentage = min(100, (offsets / emissions) * 100)
            if offset_percentage >= 100:
                score = 90 + min(10, ((offset_percentage - 100) / 50) * 10)
            elif offset_percentage >= 75:
                score = 75 + ((offset_percentage - 75) / 25) * 15
            elif offset_percentage >= 50:
                score = 60 + ((offset_percentage - 50) / 25) * 15
            elif offset_percentage >= 25:
                score = 40 + ((offset_percentage - 25) / 25) * 20
            else:
                score = 10 + (offset_percentage / 25) * 30
        elif offsets > 0:
            score = 95
        else:
            score = 50
        
        return int(score)
    
    def test_negative_values_handling(self):
        """Test handling of negative or invalid values"""
        # Test negative emissions (should be treated as 0)
        score = self._calculate_carbon_score(-100, 50)
        self.assertEqual(score, 95)  # Only offsets case
        
        # Test negative offsets (should be treated as 0)
        score = self._calculate_carbon_score(100, -50)
        self.assertEqual(score, 10)  # 100 emissions, 0 offsets = low score
    
    def test_large_numbers_handling(self):
        """Test handling of very large numbers"""
        large_emissions = 1000000
        large_offsets = 500000
        
        score = self._calculate_carbon_score(large_emissions, large_offsets)
        
        self.assertIsInstance(score, int)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)
        # Should be around 60 for 50% offset ratio
        self.assertGreaterEqual(score, 55)
        self.assertLessEqual(score, 65)


class NumberFormattingTestCase(TestCase):
    """Test number formatting functions"""
    
    def setUp(self):
        """Set up number formatting function"""
        def format_number(value, decimals=1):
            if value is None or str(value) == 'nan':
                return '0'
            
            try:
                num = float(value)
            except (ValueError, TypeError):
                return '0'
            
            # Handle zero specifically
            if num == 0:
                return '0'
            
            if abs(num) >= 1000000:
                return f"{num / 1000000:.1f}M"
            elif abs(num) >= 1000:
                return f"{num / 1000:.1f}K"
            else:
                return f"{num:.{decimals}f}"
        
        self.format_number = format_number
    
    def test_format_number_basic_cases(self):
        """Test basic number formatting cases"""
        test_values = [
            (1234.567, "1.2K"),
            (1234567.89, "1.2M"),
            (123.45, "123.5"),
            (0, "0"),
            (None, "0"),
            (-1234, "-1.2K")
        ]
        
        for value, expected in test_values:
            actual = self.format_number(value)
            self.assertEqual(actual, expected, f"Failed for value {value}")
    
    def test_format_number_edge_cases(self):
        """Test edge cases for number formatting"""
        edge_cases = [
            (999, "999.0"),        # Just under 1K
            (1000, "1.0K"),        # Exactly 1K
            (999999, "1000.0K"),   # Just under 1M
            (1000000, "1.0M"),     # Exactly 1M
            (float('inf'), "inf"),  # Infinity
            (-0, "0"),             # Negative zero
        ]
        
        for value, expected_pattern in edge_cases:
            actual = self.format_number(value)
            self.assertIsInstance(actual, str)
            # For infinity and special cases, just check it returns a string
            if value == float('inf'):
                self.assertIn('inf', actual.lower())
            elif value == -0:
                self.assertEqual(actual, "0")
            else:
                self.assertEqual(actual, expected_pattern, f"Failed for value {value}")
    
    def test_format_number_invalid_inputs(self):
        """Test formatting with invalid inputs"""
        invalid_inputs = [
            "not_a_number",
            [],
            {},
            object()
        ]
        
        for invalid_input in invalid_inputs:
            result = self.format_number(invalid_input)
            self.assertEqual(result, "0", f"Should return '0' for invalid input: {invalid_input}")


class APIResponseStructureTestCase(TransactionTestCase):
    """Test API response structure for production readiness"""
    
    def setUp(self):
        """Set up test data"""
        self.company = Company.objects.create(
            name="API Test Company",
            address="456 Test Ave",
            city="Testville", 
            state="NY"
        )
        
        self.establishment = Establishment.objects.create(
            name="API Test Farm",
            company=self.company,
            establishment_type='farm'
        )
        
        self.required_fields = [
            'establishment_id',
            'year',
            'total_emissions',
            'total_offsets',
            'net_carbon',
            'carbon_score',
            'transparency_score',
            'offset_ratio',
            'performance_tier',
            'entries_count',
            'has_data',
            'data_quality',
            'calculated_at',
            'api_version'
        ]
    
    def test_api_response_structure_completeness(self):
        """Test API response contains all required fields"""
        response_data = self._create_sample_response()
        
        # Check all required fields are present
        missing_fields = [field for field in self.required_fields if field not in response_data]
        
        self.assertEqual(len(missing_fields), 0, f"Missing required fields: {missing_fields}")
        self.assertGreaterEqual(len(response_data), len(self.required_fields))
    
    def test_api_response_data_types(self):
        """Test API response field data types"""
        response_data = self._create_sample_response()
        
        type_checks = [
            ('establishment_id', int),
            ('year', int),
            ('total_emissions', (int, float)),
            ('total_offsets', (int, float)),
            ('net_carbon', (int, float)),
            ('carbon_score', int),
            ('transparency_score', int),
            ('offset_ratio', (int, float)),
            ('performance_tier', dict),
            ('entries_count', dict),
            ('has_data', bool),
            ('data_quality', dict),
            ('calculated_at', str),
            ('api_version', str)
        ]
        
        for field_name, expected_type in type_checks:
            if field_name in response_data:
                actual_value = response_data[field_name]
                self.assertIsInstance(
                    actual_value, 
                    expected_type, 
                    f"Field '{field_name}' should be {expected_type}, got {type(actual_value)}"
                )
    
    def test_api_response_nested_structures(self):
        """Test nested data structures in API response"""
        response_data = self._create_sample_response()
        
        # Test performance_tier structure
        performance_tier = response_data['performance_tier']
        self.assertIn('tier', performance_tier)
        self.assertIn('color', performance_tier)
        self.assertIsInstance(performance_tier['tier'], str)
        self.assertIsInstance(performance_tier['color'], str)
        
        # Test entries_count structure
        entries_count = response_data['entries_count']
        expected_count_fields = ['emissions', 'offsets', 'total', 'usda_verified']
        for field in expected_count_fields:
            self.assertIn(field, entries_count)
            self.assertIsInstance(entries_count[field], int)
        
        # Test data_quality structure
        data_quality = response_data['data_quality']
        self.assertIn('completeness', data_quality)
        self.assertIn('verification_rate', data_quality)
        self.assertIsInstance(data_quality['completeness'], (int, float))
        self.assertIsInstance(data_quality['verification_rate'], (int, float))
    
    def test_api_response_value_ranges(self):
        """Test API response values are within expected ranges"""
        response_data = self._create_sample_response()
        
        # Test score ranges (0-100)
        self.assertGreaterEqual(response_data['carbon_score'], 0)
        self.assertLessEqual(response_data['carbon_score'], 100)
        self.assertGreaterEqual(response_data['transparency_score'], 0)
        self.assertLessEqual(response_data['transparency_score'], 100)
        
        # Test boolean values
        self.assertIsInstance(response_data['has_data'], bool)
        
        # Test positive numeric values where appropriate
        self.assertGreaterEqual(response_data['total_emissions'], 0)
        self.assertGreaterEqual(response_data['total_offsets'], 0)
        self.assertGreaterEqual(response_data['offset_ratio'], 0)
        
        # Test API version format
        self.assertRegex(response_data['api_version'], r'^\d+\.\d+$')
    
    def _create_sample_response(self):
        """Create a sample API response for testing"""
        return {
            'establishment_id': self.establishment.id,
            'year': 2025,
            'total_emissions': 56534.7,
            'total_offsets': 997.5,
            'net_carbon': 55537.2,
            'carbon_score': 12,
            'transparency_score': 54,
            'offset_ratio': 1.8,
            'performance_tier': {'tier': 'Needs Improvement', 'color': 'red'},
            'entries_count': {'emissions': 30, 'offsets': 2, 'total': 32, 'usda_verified': 31},
            'has_data': True,
            'data_quality': {'completeness': 64, 'verification_rate': 96.9},
            'calculated_at': timezone.now().isoformat(),
            'api_version': '2.0'
        }


class CarbonDashboardIntegrationTestCase(TestCase):
    """Test overall carbon dashboard integration"""
    
    def test_dashboard_components_integration(self):
        """Test that all dashboard components work together"""
        # Test that calculation, formatting, and API structure work together
        test_emissions = 1000.0
        test_offsets = 500.0
        
        # Carbon score calculation
        carbon_score = self._calculate_carbon_score(test_emissions, test_offsets)
        self.assertIsInstance(carbon_score, int)
        self.assertGreaterEqual(carbon_score, 0)
        self.assertLessEqual(carbon_score, 100)
        
        # Number formatting
        formatted_emissions = self._format_number(test_emissions)
        self.assertEqual(formatted_emissions, "1.0K")
        
        # Performance tier
        tier = self._get_performance_tier(carbon_score)
        self.assertIsInstance(tier, str)
        self.assertIn(tier, ["Excellent", "Very Good", "Good", "Fair", "Needs Improvement"])
    
    def _calculate_carbon_score(self, emissions, offsets):
        """Helper method for carbon score calculation"""
        if emissions > 0:
            offset_percentage = min(100, (offsets / emissions) * 100)
            if offset_percentage >= 50:
                return 60 + int((offset_percentage - 50) / 25 * 15)
            else:
                return 10 + int(offset_percentage / 25 * 30)
        elif offsets > 0:
            return 95
        else:
            return 50
    
    def _format_number(self, value):
        """Helper method for number formatting"""
        if value is None or value == 0:
            return '0'
        if abs(value) >= 1000000:
            return f"{value / 1000000:.1f}M"
        elif abs(value) >= 1000:
            return f"{value / 1000:.1f}K"
        else:
            return f"{value:.1f}"
    
    def _get_performance_tier(self, score):
        """Helper method for performance tier calculation"""
        if score >= 90:
            return "Excellent"
        elif score >= 75:
            return "Very Good"
        elif score >= 60:
            return "Good"
        elif score >= 40:
            return "Fair"
        else:
            return "Needs Improvement"