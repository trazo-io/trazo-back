"""
Test suite for BusinessEvent validation constraints
Tests all validation rules from Phase 1.4: Business Event Validation
"""

import pytest
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework import serializers as rest_serializers
from rest_framework.test import APITestCase

from history.models import BusinessEvent, History
from history.serializers import UpdateBusinessEventSerializer
from company.models import Company, Plan, Subscription, Establishment
from product.models import Parcel
from users.models import User


class BusinessEventValidationTestCase(APITestCase):
    """Test cases for BusinessEvent model and serializer validation"""
    
    def setUp(self):
        """Set up test data"""
        # Create a test user
        self.user = User.objects.create_user(
            email='test@trazo.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        
        # Create company, plan, subscription
        self.plan = Plan.objects.create(name='Test Plan', price=9.99)
        self.company = Company.objects.create(name='Test Company', user=self.user)
        self.subscription = Subscription.objects.create(
            company=self.company,
            plan=self.plan,
            is_active=True
        )
        
        # Create establishment and parcel
        self.establishment = Establishment.objects.create(
            company=self.company,
            name='Test Farm'
        )
        self.parcel = Parcel.objects.create(
            establishment=self.establishment,
            name='Test Parcel'
        )
        
        # Create history (production)
        self.history = History.objects.create(
            name='Test Production',
            parcel=self.parcel,
            crop_type_id=1  # Assuming crop type 1 exists
        )

    def _create_valid_business_event_data(self):
        """Create valid business event data for testing"""
        return {
            'description': 'Test business event',
            'date': '2024-01-15T10:30:00Z',
            'history': self.history.id,
            'business_type': 'certification',
            'certification_type': 'organic_usda',
            'carbon_credits_earned': Decimal('5.25'),
            'verification_status': 'verified'
        }

    def test_valid_business_event_creation(self):
        """Test creating a valid business event"""
        event = BusinessEvent.objects.create(
            description='USDA Organic Certification',
            date='2024-01-15T10:30:00Z',
            history=self.history,
            business_type='certification',
            certification_type='organic_usda',
            carbon_credits_earned=Decimal('5.25'),
            verification_status='verified'
        )
        
        # Should not raise any exceptions
        event.full_clean()
        self.assertEqual(event.business_type, 'certification')
        self.assertEqual(event.carbon_credits_earned, Decimal('5.25'))

    def test_carbon_credits_earned_cannot_be_negative(self):
        """Test that carbon_credits_earned cannot be negative"""
        with self.assertRaises(IntegrityError):
            BusinessEvent.objects.create(
                description='Invalid carbon credits',
                date='2024-01-15T10:30:00Z',
                history=self.history,
                business_type='carbon_credits',
                carbon_credits_earned=Decimal('-10.5')
            )

    def test_model_validation_negative_carbon_credits(self):
        """Test model-level validation for negative carbon credits"""
        event = BusinessEvent(
            description='Test event',
            date='2024-01-15T10:30:00Z',
            history=self.history,
            business_type='carbon_credits',
            carbon_credits_earned=Decimal('-5.0')
        )
        
        with self.assertRaises(ValidationError) as context:
            event.full_clean()
        
        self.assertIn('carbon_credits_earned', context.exception.error_dict)
        self.assertEqual(context.exception.error_dict['carbon_credits_earned'][0], 'Carbon credits earned cannot be negative')

    def test_model_validation_large_carbon_credits(self):
        """Test model-level validation for unusually large carbon credits"""
        event = BusinessEvent(
            description='Test event',
            date='2024-01-15T10:30:00Z',
            history=self.history,
            business_type='carbon_credits',
            carbon_credits_earned=Decimal('15000.0')  # Larger than 10000 limit
        )
        
        with self.assertRaises(ValidationError) as context:
            event.full_clean()
        
        self.assertIn('carbon_credits_earned', context.exception.error_dict)
        error_message = str(context.exception.error_dict['carbon_credits_earned'][0])
        self.assertIn('seems unusually large', error_message)

    def test_model_validation_empty_business_type(self):
        """Test model-level validation for empty business_type"""
        event = BusinessEvent(
            description='Test event',
            date='2024-01-15T10:30:00Z',
            history=self.history,
            business_type='',  # Empty business type
        )
        
        with self.assertRaises(ValidationError) as context:
            event.full_clean()
        
        self.assertIn('business_type', context.exception.error_dict)
        self.assertEqual(context.exception.error_dict['business_type'][0], 'Business type is required')

    def test_model_validation_certification_requires_type(self):
        """Test that certification business type requires certification_type"""
        event = BusinessEvent(
            description='Test certification',
            date='2024-01-15T10:30:00Z',
            history=self.history,
            business_type='certification',
            certification_type=None  # Missing certification type
        )
        
        with self.assertRaises(ValidationError) as context:
            event.full_clean()
        
        self.assertIn('certification_type', context.exception.error_dict)
        self.assertEqual(context.exception.error_dict['certification_type'][0], 'Certification type is required for certification events')

    def test_model_validation_carbon_credits_requires_amount(self):
        """Test that carbon_credits business type requires carbon_credits_earned"""
        event = BusinessEvent(
            description='Test carbon credits',
            date='2024-01-15T10:30:00Z',
            history=self.history,
            business_type='carbon_credits',
            carbon_credits_earned=None  # Missing carbon credits amount
        )
        
        with self.assertRaises(ValidationError) as context:
            event.full_clean()
        
        self.assertIn('carbon_credits_earned', context.exception.error_dict)
        self.assertEqual(context.exception.error_dict['carbon_credits_earned'][0], 'Carbon credits amount is required for carbon credit transactions')

    def test_serializer_validation_negative_carbon_credits(self):
        """Test serializer validation for negative carbon credits with helpful messages"""
        data = self._create_valid_business_event_data()
        data['carbon_credits_earned'] = -5.0
        
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        
        errors = serializer.errors['carbon_credits_earned']
        self.assertIn('Carbon credits earned cannot be negative', errors[0])
        self.assertIn('Carbon credits represent positive environmental impact', errors[1])

    def test_serializer_validation_large_carbon_credits(self):
        """Test serializer validation for unusually large carbon credits"""
        data = self._create_valid_business_event_data()
        data['carbon_credits_earned'] = 15000.0
        
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        
        errors = serializer.errors['carbon_credits_earned']
        self.assertIn('seems unusually large', errors[0])
        self.assertIn('Typical farm operations generate 0.1-100 credits', errors[1])

    def test_serializer_validation_empty_business_type(self):
        """Test serializer validation for empty business_type"""
        data = self._create_valid_business_event_data()
        data['business_type'] = ''
        
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        
        errors = serializer.errors['business_type']
        self.assertIn('Business type is required', errors[0])
        self.assertIn('Please select the type of business activity', errors[1])

    def test_serializer_validation_certification_missing_type(self):
        """Test serializer validation for certification without type"""
        data = self._create_valid_business_event_data()
        data['business_type'] = 'certification'
        data['certification_type'] = None
        
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        
        errors = serializer.errors['certification_type']
        self.assertIn('Certification type is required for certification events', errors[0])
        self.assertIn('Examples: USDA Organic, Carbon Neutral', errors[2])

    def test_serializer_validation_carbon_credits_missing_amount(self):
        """Test serializer validation for carbon_credits without amount"""
        data = self._create_valid_business_event_data()
        data['business_type'] = 'carbon_credits'
        data['carbon_credits_earned'] = None
        
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        
        errors = serializer.errors['carbon_credits_earned']
        self.assertIn('Carbon credits amount is required for carbon credit transactions', errors[0])
        self.assertIn('Please enter the number of credits generated or traded', errors[1])

    def test_serializer_validation_verification_status(self):
        """Test serializer validation for verification events with pending status"""
        data = self._create_valid_business_event_data()
        data['business_type'] = 'verification'
        data['verification_status'] = 'pending'
        
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        
        errors = serializer.errors['verification_status']
        self.assertIn('Verification events should have a definitive verification status', errors[0])

    def test_valid_business_types(self):
        """Test all valid business types work correctly"""
        valid_types = [
            'certification',
            'carbon_credits', 
            'sustainability_audit',
            'verification',
            'compliance',
            'transparency'
        ]
        
        for business_type in valid_types:
            data = self._create_valid_business_event_data()
            data['business_type'] = business_type
            
            # Adjust required fields based on business type
            if business_type == 'carbon_credits':
                data['carbon_credits_earned'] = Decimal('1.5')
            elif business_type == 'certification':
                data['certification_type'] = 'organic_usda'
            elif business_type == 'verification':
                data['verification_status'] = 'verified'
            
            serializer = UpdateBusinessEventSerializer(data=data)
            self.assertTrue(serializer.is_valid(), f"Business type '{business_type}' should be valid. Errors: {serializer.errors}")

    def test_valid_carbon_credit_amounts(self):
        """Test valid carbon credit amounts"""
        valid_amounts = [0, 0.1, 1.0, 10.5, 100.0, 999.99]
        
        for amount in valid_amounts:
            data = self._create_valid_business_event_data()
            data['business_type'] = 'carbon_credits'
            data['carbon_credits_earned'] = Decimal(str(amount))
            
            serializer = UpdateBusinessEventSerializer(data=data)
            self.assertTrue(serializer.is_valid(), f"Amount {amount} should be valid. Errors: {serializer.errors}")

    def test_boundary_values(self):
        """Test boundary values for carbon credits"""
        # Test exactly at the upper boundary
        data = self._create_valid_business_event_data()
        data['business_type'] = 'carbon_credits'
        data['carbon_credits_earned'] = Decimal('10000.0')  # Exactly at limit
        
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        
        # Test just over the boundary
        data['carbon_credits_earned'] = Decimal('10000.1')  # Just over limit
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_zero_carbon_credits(self):
        """Test that zero carbon credits is allowed"""
        data = self._create_valid_business_event_data()
        data['business_type'] = 'carbon_credits'
        data['carbon_credits_earned'] = Decimal('0.0')
        
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_null_carbon_credits_allowed_for_other_types(self):
        """Test that null carbon_credits_earned is allowed for non-carbon-credit events"""
        data = self._create_valid_business_event_data()
        data['business_type'] = 'compliance'
        data['carbon_credits_earned'] = None
        
        serializer = UpdateBusinessEventSerializer(data=data)
        self.assertTrue(serializer.is_valid())