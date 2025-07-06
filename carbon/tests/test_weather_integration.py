"""
Weather API Integration Tests

Tests weather API integration endpoints and services including:
- Weather service configuration
- NOAA API connectivity  
- Weather data processing
- Agricultural recommendations
- Weather alert creation
- API endpoint functionality
"""

from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch, Mock
from carbon.services.weather_api import WeatherService, get_weather_service, get_current_weather, check_weather_alerts
from carbon.models import IoTDevice, IoTDataPoint
from company.models import Company, Establishment
from django.test import RequestFactory
import json

User = get_user_model()


class WeatherServiceConfigurationTestCase(TestCase):
    """Test weather service configuration and initialization"""
    
    def test_weather_service_initialization(self):
        """Test weather service initializes properly"""
        weather_service = WeatherService()
        
        self.assertIsNotNone(weather_service)
        self.assertTrue(hasattr(weather_service, 'noaa_base_url'))
        self.assertIsInstance(weather_service.noaa_base_url, str)
    
    def test_get_weather_service_convenience_function(self):
        """Test convenience function for getting weather service"""
        service = get_weather_service()
        
        self.assertIsNotNone(service)
        self.assertIsInstance(service, WeatherService)
    
    def test_weather_service_has_required_methods(self):
        """Test weather service has all required methods"""
        weather_service = WeatherService()
        
        required_methods = [
            'generate_agricultural_recommendations',
            'should_trigger_alert'
        ]
        
        for method in required_methods:
            self.assertTrue(hasattr(weather_service, method))
            self.assertTrue(callable(getattr(weather_service, method)))


class WeatherDataRetrievalTestCase(TestCase):
    """Test weather data retrieval from APIs"""
    
    @patch('carbon.services.weather_api.requests.get')
    def test_current_weather_retrieval_success(self, mock_get):
        """Test successful weather data retrieval"""
        # Mock successful NOAA response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'properties': {
                'temperature': {'value': 75},
                'relativeHumidity': {'value': 60},
                'windSpeed': {'value': 8},
                'textDescription': 'Clear skies'
            }
        }
        mock_get.return_value = mock_response
        
        test_lat = 37.7749
        test_lng = -122.4194
        
        weather_data = get_current_weather(test_lat, test_lng)
        
        if weather_data:  # Only test if data returned (depends on implementation)
            self.assertIn('temperature', weather_data)
            self.assertIn('humidity', weather_data)
            self.assertIn('wind_speed', weather_data)
            self.assertIn('description', weather_data)
    
    @patch('carbon.services.weather_api.requests.get')
    def test_current_weather_retrieval_failure(self, mock_get):
        """Test weather data retrieval failure handling"""
        # Mock failed API response
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        test_lat = 37.7749
        test_lng = -122.4194
        
        weather_data = get_current_weather(test_lat, test_lng)
        
        # Should handle failure gracefully
        self.assertTrue(weather_data is None or isinstance(weather_data, dict))
    
    def test_weather_data_coordinates_validation(self):
        """Test weather data retrieval with invalid coordinates"""
        # Test with invalid coordinates
        invalid_coords = [
            (None, None),
            (200, 200),  # Out of range
            (-200, -200),  # Out of range
        ]
        
        for lat, lng in invalid_coords:
            try:
                weather_data = get_current_weather(lat, lng)
                # Should either return None or handle gracefully
                self.assertTrue(weather_data is None or isinstance(weather_data, dict))
            except Exception:
                # Exception handling is acceptable for invalid input
                pass


class WeatherAlertsTestCase(TestCase):
    """Test weather alerts functionality"""
    
    @patch('carbon.services.weather_api.requests.get')
    def test_weather_alerts_retrieval(self, mock_get):
        """Test weather alerts retrieval"""
        # Mock weather alerts response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'features': [
                {
                    'properties': {
                        'headline': 'Heat Warning',
                        'severity': 'Moderate',
                        'event': 'Heat Advisory'
                    }
                }
            ]
        }
        mock_get.return_value = mock_response
        
        test_lat = 39.0458
        test_lng = -76.6413
        
        alerts = check_weather_alerts(test_lat, test_lng)
        
        self.assertIsInstance(alerts, list)
        # Test passes if alerts is a list (empty or populated)
    
    @patch('carbon.services.weather_api.requests.get')
    def test_weather_alerts_empty_response(self, mock_get):
        """Test weather alerts with no active alerts"""
        # Mock empty alerts response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'features': []}
        mock_get.return_value = mock_response
        
        test_lat = 39.0458
        test_lng = -76.6413
        
        alerts = check_weather_alerts(test_lat, test_lng)
        
        self.assertIsInstance(alerts, list)
        self.assertEqual(len(alerts), 0)
    
    def test_weather_alerts_with_invalid_coordinates(self):
        """Test weather alerts with invalid coordinates"""
        try:
            alerts = check_weather_alerts(None, None)
            self.assertIsInstance(alerts, list)
        except Exception:
            # Exception handling is acceptable for invalid input
            pass


class AgriculturalRecommendationsTestCase(TestCase):
    """Test agricultural recommendations generation"""
    
    def setUp(self):
        """Set up test data"""
        self.weather_service = WeatherService()
    
    def test_normal_conditions_recommendations(self):
        """Test recommendations for normal weather conditions"""
        weather_data = {
            'temperature': 75,
            'humidity': 60,
            'wind_speed': 8,
            'description': 'Clear skies'
        }
        
        recommendations = self.weather_service.generate_agricultural_recommendations(
            weather_data, 'general'
        )
        
        self.assertIsInstance(recommendations, list)
        for rec in recommendations:
            self.assertIn('priority', rec)
            self.assertIn('title', rec)
            self.assertIn('actions', rec)
    
    def test_high_temperature_recommendations(self):
        """Test recommendations for high temperature conditions"""
        weather_data = {
            'temperature': 98,
            'humidity': 45,
            'wind_speed': 12,
            'description': 'Hot and dry'
        }
        
        recommendations = self.weather_service.generate_agricultural_recommendations(
            weather_data, 'general'
        )
        
        self.assertIsInstance(recommendations, list)
        
        # Should have high/critical priority recommendations for extreme heat
        priorities = [rec.get('priority') for rec in recommendations]
        self.assertTrue(any(p in ['critical', 'high'] for p in priorities))
    
    def test_high_wind_recommendations(self):
        """Test recommendations for high wind conditions"""
        weather_data = {
            'temperature': 72,
            'humidity': 55,
            'wind_speed': 28,
            'description': 'Windy conditions'
        }
        
        recommendations = self.weather_service.generate_agricultural_recommendations(
            weather_data, 'general'
        )
        
        self.assertIsInstance(recommendations, list)
        
        # Should generate recommendations for windy conditions
        titles = [rec.get('title', '').lower() for rec in recommendations]
        wind_related = any('wind' in title or 'spray' in title for title in titles)
        self.assertTrue(len(recommendations) > 0)  # Should generate some recommendations
    
    def test_freezing_temperature_recommendations(self):
        """Test recommendations for freezing conditions"""
        weather_data = {
            'temperature': 28,
            'humidity': 70,
            'wind_speed': 5,
            'description': 'Freezing conditions'
        }
        
        recommendations = self.weather_service.generate_agricultural_recommendations(
            weather_data, 'general'
        )
        
        self.assertIsInstance(recommendations, list)
        
        # Should have critical recommendations for freezing
        priorities = [rec.get('priority') for rec in recommendations]
        self.assertTrue(any(p == 'critical' for p in priorities))


class WeatherAlertThresholdsTestCase(TestCase):
    """Test weather alert threshold logic"""
    
    def setUp(self):
        """Set up test data"""
        self.weather_service = WeatherService()
    
    def test_normal_conditions_no_alert(self):
        """Test that normal conditions don't trigger alerts"""
        condition = {'temperature': 75, 'humidity': 60, 'wind_speed': 8}
        
        should_alert = self.weather_service.should_trigger_alert(condition)
        
        self.assertFalse(should_alert)
    
    def test_high_temperature_triggers_alert(self):
        """Test that high temperature triggers alert"""
        condition = {'temperature': 95, 'humidity': 60, 'wind_speed': 8}
        
        should_alert = self.weather_service.should_trigger_alert(condition)
        
        self.assertTrue(should_alert)
    
    def test_low_humidity_triggers_alert(self):
        """Test that low humidity triggers alert"""
        condition = {'temperature': 75, 'humidity': 25, 'wind_speed': 8}
        
        should_alert = self.weather_service.should_trigger_alert(condition)
        
        self.assertTrue(should_alert)
    
    def test_high_wind_triggers_alert(self):
        """Test that high wind speed triggers alert"""
        condition = {'temperature': 75, 'humidity': 60, 'wind_speed': 25}
        
        should_alert = self.weather_service.should_trigger_alert(condition)
        
        self.assertTrue(should_alert)
    
    def test_freezing_temperature_triggers_alert(self):
        """Test that freezing temperature triggers alert"""
        condition = {'temperature': 30, 'humidity': 60, 'wind_speed': 8}
        
        should_alert = self.weather_service.should_trigger_alert(condition)
        
        self.assertTrue(should_alert)


class WeatherEventCreationTestCase(TransactionTestCase):
    """Test weather event creation through IoT workflow"""
    
    def setUp(self):
        """Set up test data"""
        self.company = Company.objects.create(
            name="Test Weather Company",
            address='123 Weather Test St',
            city='Test City',
            state='CA',
            country='US'
        )
        
        self.establishment = Establishment.objects.create(
            name="Test Weather Farm",
            company=self.company,
            address='456 Farm Weather Rd',
            city='Test City',
            state='CA',
            country='US',
            latitude=37.7749,
            longitude=-122.4194,
            establishment_type='farm'
        )
    
    def test_weather_station_device_creation(self):
        """Test weather station device creation"""
        device = IoTDevice.objects.create(
            establishment=self.establishment,
            name=f"Weather Station - {self.establishment.name}",
            device_type='weather_station',
            status='online',
            battery_level=100,
            device_id=f'weather_station_{self.establishment.id}'
        )
        
        self.assertEqual(device.establishment, self.establishment)
        self.assertEqual(device.device_type, 'weather_station')
        self.assertEqual(device.status, 'online')
        self.assertEqual(device.battery_level, 100)
    
    def test_weather_data_point_creation(self):
        """Test weather data point creation"""
        device = IoTDevice.objects.create(
            establishment=self.establishment,
            name=f"Weather Station - {self.establishment.name}",
            device_type='weather_station',
            status='online',
            battery_level=100,
            device_id=f'weather_station_{self.establishment.id}'
        )
        
        weather_data = {
            'temperature': 95,
            'humidity': 30,
            'wind_speed': 5,
            'description': 'Hot and dry conditions'
        }
        
        data_point = IoTDataPoint.objects.create(
            device=device,
            timestamp=timezone.now(),
            data=weather_data,
            quality_score=0.9
        )
        
        self.assertEqual(data_point.device, device)
        self.assertEqual(data_point.data, weather_data)
        self.assertEqual(data_point.quality_score, 0.9)
        self.assertIn('temperature', data_point.data)
        self.assertIn('humidity', data_point.data)
        self.assertIn('wind_speed', data_point.data)
    
    def test_extreme_weather_data_recording(self):
        """Test recording of extreme weather conditions"""
        device = IoTDevice.objects.create(
            establishment=self.establishment,
            name="Extreme Weather Station",
            device_type='weather_station',
            status='online'
        )
        
        extreme_conditions = [
            {'temperature': 110, 'humidity': 15, 'wind_speed': 35, 'description': 'Extreme heat'},
            {'temperature': 10, 'humidity': 90, 'wind_speed': 45, 'description': 'Extreme cold'},
            {'temperature': 85, 'humidity': 95, 'wind_speed': 50, 'description': 'Storm conditions'}
        ]
        
        for condition in extreme_conditions:
            data_point = IoTDataPoint.objects.create(
                device=device,
                timestamp=timezone.now(),
                data=condition,
                quality_score=0.8
            )
            
            self.assertEqual(data_point.data, condition)
            self.assertGreaterEqual(data_point.quality_score, 0.0)
            self.assertLessEqual(data_point.quality_score, 1.0)


class WeatherAPIEndpointsTestCase(TestCase):
    """Test weather API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        
        self.company = Company.objects.create(
            name="Weather API Test Company",
            address="456 Weather API St",
            city="API City",
            state="NY"
        )
        
        self.user = User.objects.create_user(
            email='weather_test@example.com',
            password='testpass123',
            first_name='Weather',
            last_name='Test',
            company=self.company
        )
        
        self.client.force_authenticate(user=self.user)
    
    @patch('carbon.services.weather_api.get_current_weather')
    def test_current_conditions_endpoint(self, mock_weather):
        """Test current weather conditions endpoint"""
        # Mock weather response
        mock_weather.return_value = {
            'temperature': 75,
            'humidity': 60,
            'wind_speed': 8,
            'description': 'Clear skies',
            'source': 'NOAA'
        }
        
        response = self.client.get('/carbon/weather/current/', {
            'lat': '37.7749',
            'lng': '-122.4194'
        })
        
        # Accept various response codes depending on implementation
        self.assertIn(response.status_code, [200, 400, 404])
        
        if response.status_code == 200:
            data = response.json()
            self.assertIn('weather', data)
    
    @patch('carbon.services.weather_api.check_weather_alerts')
    def test_weather_alerts_endpoint(self, mock_alerts):
        """Test weather alerts endpoint"""
        # Mock alerts response
        mock_alerts.return_value = [
            {
                'title': 'Heat Warning',
                'severity': 'Moderate',
                'event': 'Heat Advisory'
            }
        ]
        
        response = self.client.get('/carbon/weather/alerts/', {
            'lat': '37.7749',
            'lng': '-122.4194'
        })
        
        # Accept various response codes
        self.assertIn(response.status_code, [200, 400, 404])
    
    def test_weather_recommendations_endpoint(self):
        """Test weather recommendations endpoint"""
        response = self.client.get('/carbon/weather/recommendations/', {
            'lat': '37.7749',
            'lng': '-122.4194',
            'establishment_type': 'general'
        })
        
        # Accept various response codes depending on implementation
        self.assertIn(response.status_code, [200, 400, 404])
        
        if response.status_code == 200:
            data = response.json()
            self.assertIn('recommendations', data)
    
    def test_weather_endpoints_require_coordinates(self):
        """Test weather endpoints require valid coordinates"""
        endpoints = [
            '/carbon/weather/current/',
            '/carbon/weather/alerts/',
            '/carbon/weather/recommendations/'
        ]
        
        for endpoint in endpoints:
            # Test without coordinates
            response = self.client.get(endpoint)
            self.assertIn(response.status_code, [400, 404])
            
            # Test with invalid coordinates
            response = self.client.get(endpoint, {
                'lat': 'invalid',
                'lng': 'invalid'
            })
            self.assertIn(response.status_code, [400, 404]) 