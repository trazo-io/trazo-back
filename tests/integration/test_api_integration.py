"""
Comprehensive integration tests for Trazo API endpoints.
Tests end-to-end flows with real database interactions.
"""
import json
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from unittest.mock import patch, MagicMock

from company.models import Company, Establishment
from product.models import Parcel, Product
from history.models import History, HistoryScan
from carbon.models import CarbonCalculation
from subscriptions.models import Subscription

User = get_user_model()


class AuthenticationIntegrationTests(APITestCase):
    """Test authentication flows end-to-end"""
    
    def setUp(self):
        self.client = APIClient()
        self.user_data = {
            'email': 'test@example.com',
            'password': 'testpass123',
            'first_name': 'Test',
            'last_name': 'User'
        }
    
    def test_complete_signup_login_flow(self):
        """Test complete user signup and login flow"""
        # Step 1: Sign up
        signup_url = reverse('rest_register')
        response = self.client.post(signup_url, self.user_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access_token', response.data)
        self.assertIn('refresh_token', response.data)
        
        # Verify user was created
        user = User.objects.get(email=self.user_data['email'])
        self.assertEqual(user.first_name, 'Test')
        self.assertEqual(user.last_name, 'User')
        
        # Step 2: Login with credentials
        login_url = reverse('rest_login')
        login_data = {
            'email': self.user_data['email'],
            'password': self.user_data['password']
        }
        
        response = self.client.post(login_url, login_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access_token', response.data)
        
        # Step 3: Access protected endpoint
        access_token = response.data['access_token']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        
        profile_url = reverse('rest_user_details')
        response = self.client.get(profile_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.user_data['email'])
    
    def test_token_refresh_flow(self):
        """Test JWT token refresh functionality"""
        # Create and login user
        user = User.objects.create_user(**self.user_data)
        login_url = reverse('rest_login')
        
        response = self.client.post(login_url, {
            'email': self.user_data['email'],
            'password': self.user_data['password']
        })
        
        refresh_token = response.data['refresh_token']
        
        # Use refresh token to get new access token
        refresh_url = reverse('token_refresh')
        response = self.client.post(refresh_url, {
            'refresh': refresh_token
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        
        # Verify new access token works
        new_access_token = response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {new_access_token}')
        
        profile_url = reverse('rest_user_details')
        response = self.client.get(profile_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class CompanyEstablishmentIntegrationTests(APITestCase):
    """Test company and establishment management flows"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            email='company@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)
        
    def test_complete_company_setup_flow(self):
        """Test complete company and establishment setup"""
        # Step 1: Create company
        company_data = {
            'name': 'Green Farm Co',
            'description': 'Sustainable agriculture company',
            'country': 'USA',
            'website': 'https://greenfarm.com'
        }
        
        company_url = reverse('company-list')
        response = self.client.post(company_url, company_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        company_id = response.data['id']
        
        # Step 2: Create establishment
        establishment_data = {
            'name': 'Main Farm',
            'company': company_id,
            'address': '123 Farm Road',
            'country': 'USA',
            'farm_type': 'organic'
        }
        
        establishment_url = reverse('establishment-list')
        response = self.client.post(establishment_url, establishment_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        establishment_id = response.data['id']
        
        # Step 3: Create parcel for establishment
        parcel_data = {
            'name': 'Field A',
            'establishment': establishment_id,
            'area': 250.5,
            'coordinates': '{"type":"Polygon","coordinates":[[[-122.4,37.8],[-122.3,37.8],[-122.3,37.9],[-122.4,37.9],[-122.4,37.8]]]}'
        }
        
        parcel_url = reverse('parcel-list')
        response = self.client.post(parcel_url, parcel_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Step 4: Verify relationship chain
        parcel_id = response.data['id']
        parcel_detail_url = reverse('parcel-detail', kwargs={'pk': parcel_id})
        response = self.client.get(parcel_detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['establishment']['name'], 'Main Farm')
        self.assertEqual(response.data['establishment']['company']['name'], 'Green Farm Co')
    
    def test_establishment_parcel_listing_with_filtering(self):
        """Test listing establishments and parcels with filters"""
        # Create test data
        company = Company.objects.create(
            name='Test Company',
            country='USA'
        )
        
        establishment1 = Establishment.objects.create(
            name='Farm North',
            company=company,
            country='USA'
        )
        
        establishment2 = Establishment.objects.create(
            name='Farm South',
            company=company,
            country='USA'
        )
        
        # Create parcels
        Parcel.objects.create(
            name='North Field 1',
            establishment=establishment1,
            area=100.0
        )
        
        Parcel.objects.create(
            name='South Field 1',
            establishment=establishment2,
            area=200.0
        )
        
        # Test establishment listing
        establishment_url = reverse('establishment-list')
        response = self.client.get(establishment_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
        
        # Test parcel listing with establishment filter
        parcel_url = reverse('parcel-list')
        response = self.client.get(f'{parcel_url}?establishment={establishment1.id}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['name'], 'North Field 1')


class ProductionHistoryIntegrationTests(APITestCase):
    """Test production history and scanning flows"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            email='farmer@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)
        
        # Create company structure
        self.company = Company.objects.create(
            name='Test Farm',
            country='USA'
        )
        
        self.establishment = Establishment.objects.create(
            name='Main Farm',
            company=self.company,
            country='USA'
        )
        
        self.parcel = Parcel.objects.create(
            name='Test Field',
            establishment=self.establishment,
            area=150.0
        )
        
        self.product = Product.objects.create(
            name='Organic Tomatoes',
            description='Fresh organic tomatoes'
        )
    
    def test_complete_production_tracking_flow(self):
        """Test complete production history creation and tracking"""
        # Step 1: Create production history
        history_data = {
            'name': 'Tomato Production 2024',
            'parcel': self.parcel.id,
            'product': self.product.id,
            'start_date': '2024-01-01',
            'end_date': '2024-06-30',
            'published': True
        }
        
        history_url = reverse('history-list')
        response = self.client.post(history_url, history_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        history_id = response.data['id']
        
        # Step 2: Add production events (mocked)
        # In real implementation, this would add planting, fertilizing, harvesting events
        
        # Step 3: Generate QR code for history
        qr_url = reverse('history-qr-code', kwargs={'pk': history_id})
        response = self.client.get(qr_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('qr_code_url', response.data)
        
        # Step 4: Simulate public QR scan
        self.client.force_authenticate(user=None)  # Public access
        
        public_scan_url = reverse('public-history-scan', kwargs={'pk': history_id})
        response = self.client.get(public_scan_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Tomato Production 2024')
        
        # Step 5: Verify scan was recorded
        scan_count = HistoryScan.objects.filter(history_id=history_id).count()
        self.assertEqual(scan_count, 1)
    
    @patch('carbon.services.usda_api.USDAApiService.get_emission_factor')
    def test_carbon_calculation_integration(self, mock_usda):
        """Test carbon calculation integration with production history"""
        # Mock USDA API response
        mock_usda.return_value = {
            'emission_factor': 2.5,
            'unit': 'kg_co2_per_kg',
            'source': 'USDA_2024'
        }
        
        # Create production history
        history = History.objects.create(
            name='Carbon Test Production',
            parcel=self.parcel,
            product=self.product,
            start_date='2024-01-01',
            published=True
        )
        
        # Request carbon calculation
        carbon_url = reverse('carbon-calculate')
        carbon_data = {
            'history_id': history.id,
            'crop_type': 'tomatoes',
            'production_amount': 1000,  # kg
            'farming_practices': ['organic', 'no_till']
        }
        
        response = self.client.post(carbon_url, carbon_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('total_emissions', response.data)
        self.assertIn('carbon_score', response.data)
        
        # Verify calculation was stored
        calculation = CarbonCalculation.objects.get(history=history)
        self.assertEqual(calculation.crop_type, 'tomatoes')
        self.assertEqual(calculation.production_amount, 1000)


class SubscriptionIntegrationTests(APITestCase):
    """Test subscription and billing integration"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            email='subscriber@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)
        
        self.company = Company.objects.create(
            name='Subscription Test Farm',
            country='USA'
        )
    
    @patch('stripe.checkout.Session.create')
    @patch('stripe.Price.retrieve')
    def test_subscription_creation_flow(self, mock_price_retrieve, mock_session_create):
        """Test complete subscription creation flow"""
        # Mock Stripe responses
        mock_price_retrieve.return_value = MagicMock(
            id='price_test123',
            unit_amount=2900,  # $29.00
            currency='usd'
        )
        
        mock_session_create.return_value = MagicMock(
            id='cs_test123',
            url='https://checkout.stripe.com/pay/cs_test123'
        )
        
        # Step 1: Create checkout session
        checkout_url = reverse('create-checkout-session')
        checkout_data = {
            'price_id': 'price_test123',
            'company_id': self.company.id,
            'success_url': 'https://app.trazo.com/success',
            'cancel_url': 'https://app.trazo.com/cancel'
        }
        
        response = self.client.post(checkout_url, checkout_data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('checkout_url', response.data)
        
        # Step 2: Simulate successful webhook (subscription created)
        webhook_data = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test123',
                    'customer': 'cus_test123',
                    'subscription': 'sub_test123',
                    'metadata': {
                        'company_id': str(self.company.id)
                    }
                }
            }
        }
        
        webhook_url = reverse('stripe-webhook')
        response = self.client.post(
            webhook_url,
            json.dumps(webhook_data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Step 3: Verify subscription was created
        subscription = Subscription.objects.get(company=self.company)
        self.assertEqual(subscription.stripe_subscription_id, 'sub_test123')
        self.assertTrue(subscription.is_active)
    
    def test_feature_gating_with_subscription(self):
        """Test that features are properly gated by subscription status"""
        # Test without subscription - should be limited
        premium_feature_url = reverse('premium-analytics')
        response = self.client.get(premium_feature_url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Create active subscription
        subscription = Subscription.objects.create(
            company=self.company,
            stripe_customer_id='cus_test123',
            stripe_subscription_id='sub_test123',
            plan='premium',
            status='active'
        )
        
        # Test with subscription - should have access
        response = self.client.get(premium_feature_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class BlockchainIntegrationTests(TransactionTestCase):
    """Test blockchain integration flows (mocked)"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            email='blockchain@example.com',
            password='testpass123'
        )
        
        self.company = Company.objects.create(
            name='Blockchain Test Farm',
            country='USA'
        )
        
        self.establishment = Establishment.objects.create(
            name='Blockchain Farm',
            company=self.company,
            country='USA'
        )
        
        self.parcel = Parcel.objects.create(
            name='Blockchain Field',
            establishment=self.establishment,
            area=100.0
        )
    
    @patch('carbon.services.blockchain_service.BlockchainService.verify_carbon_data')
    @patch('carbon.services.blockchain_service.BlockchainService.submit_verification')
    def test_carbon_verification_blockchain_flow(self, mock_submit, mock_verify):
        """Test complete carbon verification blockchain integration"""
        # Mock successful blockchain responses
        mock_submit.return_value = {
            'transaction_hash': '0x1234567890abcdef',
            'block_number': 12345,
            'gas_used': 150000
        }
        
        mock_verify.return_value = {
            'verified': True,
            'verification_hash': '0xabcdef1234567890',
            'timestamp': '2024-01-15T10:00:00Z'
        }
        
        # Create production history with carbon calculation
        history = History.objects.create(
            name='Blockchain Verified Production',
            parcel=self.parcel,
            start_date='2024-01-01',
            published=True
        )
        
        carbon_calc = CarbonCalculation.objects.create(
            history=history,
            crop_type='corn',
            production_amount=1500,
            total_emissions=750.0,
            carbon_score=85
        )
        
        # Submit for blockchain verification
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.user)
        
        verification_url = reverse('blockchain-verify-carbon')
        verification_data = {
            'calculation_id': carbon_calc.id,
            'verification_type': 'carbon_footprint'
        }
        
        response = client.post(verification_url, verification_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('transaction_hash', response.data)
        self.assertIn('verification_status', response.data)
        
        # Verify blockchain submission was called
        mock_submit.assert_called_once()
        mock_verify.assert_called_once()


class APIPerformanceIntegrationTests(APITestCase):
    """Test API performance under realistic load"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            email='performance@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)
        
        # Create test data structure
        self.company = Company.objects.create(
            name='Performance Test Co',
            country='USA'
        )
        
        # Create multiple establishments
        self.establishments = []
        for i in range(5):
            establishment = Establishment.objects.create(
                name=f'Farm {i+1}',
                company=self.company,
                country='USA'
            )
            self.establishments.append(establishment)
            
            # Create parcels for each establishment
            for j in range(3):
                Parcel.objects.create(
                    name=f'Field {j+1} - Farm {i+1}',
                    establishment=establishment,
                    area=100.0 + j * 50
                )
    
    def test_bulk_operations_performance(self):
        """Test performance of bulk operations"""
        import time
        
        # Test establishment listing performance
        start_time = time.time()
        establishment_url = reverse('establishment-list')
        response = self.client.get(establishment_url)
        end_time = time.time()
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 5)
        
        # Should complete within reasonable time
        execution_time = end_time - start_time
        self.assertLess(execution_time, 1.0, 
                       f"Establishment listing took {execution_time:.3f}s, expected < 1.0s")
        
        # Test parcel listing performance
        start_time = time.time()
        parcel_url = reverse('parcel-list')
        response = self.client.get(parcel_url)
        end_time = time.time()
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 15)  # 5 establishments * 3 parcels
        
        execution_time = end_time - start_time
        self.assertLess(execution_time, 1.5,
                       f"Parcel listing took {execution_time:.3f}s, expected < 1.5s")
    
    def test_nested_relationship_performance(self):
        """Test performance when accessing nested relationships"""
        import time
        
        # Create history records with relationships
        for establishment in self.establishments[:2]:  # Limit to prevent excessive test data
            for parcel in establishment.parcel_set.all()[:2]:
                History.objects.create(
                    name=f'Production for {parcel.name}',
                    parcel=parcel,
                    start_date='2024-01-01',
                    published=True
                )
        
        # Test history listing with nested data access
        start_time = time.time()
        history_url = reverse('history-list')
        response = self.client.get(history_url)
        end_time = time.time()
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify nested data is accessible without additional queries
        for history in response.data['results']:
            self.assertIn('parcel', history)
            self.assertIn('establishment', history['parcel'])
            self.assertIn('company', history['parcel']['establishment'])
        
        execution_time = end_time - start_time
        self.assertLess(execution_time, 2.0,
                       f"History listing with nested data took {execution_time:.3f}s, expected < 2.0s")


if __name__ == '__main__':
    import unittest
    unittest.main()