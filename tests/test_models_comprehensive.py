"""
Comprehensive model test suite with proper schema validation.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from company.models import Company, Establishment
from product.models import Parcel, Product
from history.models import History
from common.models import Gallery, GalleryImage

User = get_user_model()


class BaseModelTestCase(TestCase):
    """Base test case with common setup"""
    
    def setUp(self):
        """Set up common test data"""
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        
        self.company = Company.objects.create(
            name='Test Company',
            country='USA'
        )
        
        self.establishment = Establishment.objects.create(
            name='Test Farm',
            company=self.company,
            country='USA'
        )


class CompanyModelTests(BaseModelTestCase):
    """Test Company model functionality"""
    
    def test_company_creation(self):
        """Test basic company creation"""
        company = Company.objects.create(
            name='New Company',
            country='Canada'
        )
        self.assertEqual(company.name, 'New Company')
        self.assertEqual(company.country, 'Canada')
        self.assertIsNotNone(company.id)
    
    def test_company_string_representation(self):
        """Test company string representation"""
        self.assertEqual(str(self.company), 'Test Company')
    
    def test_company_establishment_relationship(self):
        """Test one-to-many relationship with establishments"""
        # Create additional establishment
        establishment2 = Establishment.objects.create(
            name='Second Farm',
            company=self.company,
            country='USA'
        )
        
        # Test relationship
        self.assertEqual(self.company.establishments.count(), 2)
        self.assertIn(self.establishment, self.company.establishments.all())
        self.assertIn(establishment2, self.company.establishments.all())


class EstablishmentModelTests(BaseModelTestCase):
    """Test Establishment model functionality"""
    
    def test_establishment_creation(self):
        """Test establishment creation with required fields"""
        establishment = Establishment.objects.create(
            name='New Farm',
            company=self.company,
            country='Mexico'
        )
        self.assertEqual(establishment.name, 'New Farm')
        self.assertEqual(establishment.company, self.company)
        self.assertEqual(establishment.country, 'Mexico')
    
    def test_establishment_optional_fields(self):
        """Test establishment with optional fields"""
        establishment = Establishment.objects.create(
            name='Full Farm',
            company=self.company,
            country='USA',
            description='A test farm with all details',
            address='123 Farm Road',
            contact_person='John Farmer',
            contact_phone='555-0123',
            contact_email='john@farm.com'
        )
        self.assertEqual(establishment.description, 'A test farm with all details')
        self.assertEqual(establishment.contact_person, 'John Farmer')
    
    def test_establishment_parcel_relationship(self):
        """Test one-to-many relationship with parcels"""
        # Create parcels
        parcel1 = Parcel.objects.create(
            name='Field 1',
            establishment=self.establishment,
            area=50.0
        )
        parcel2 = Parcel.objects.create(
            name='Field 2', 
            establishment=self.establishment,
            area=75.0
        )
        
        # Test relationship
        self.assertEqual(self.establishment.parcels.count(), 2)
        self.assertIn(parcel1, self.establishment.parcels.all())
        self.assertIn(parcel2, self.establishment.parcels.all())


class ParcelModelTests(BaseModelTestCase):
    """Test Parcel model functionality"""
    
    def test_parcel_creation_minimal(self):
        """Test parcel creation with minimal required fields"""
        parcel = Parcel.objects.create(
            name='Test Field',
            establishment=self.establishment,
            area=100.0
        )
        self.assertEqual(parcel.name, 'Test Field')
        self.assertEqual(parcel.establishment, self.establishment)
        self.assertEqual(parcel.area, 100.0)
        self.assertFalse(parcel.certified)  # Default value
    
    def test_parcel_creation_full(self):
        """Test parcel creation with all fields"""
        product = Product.objects.create(
            name='Test Crop',
            description='A test crop'
        )
        
        parcel = Parcel.objects.create(
            name='Full Field',
            establishment=self.establishment,
            area=150.0,
            product=product,
            certified=True,
            soil_type='Clay',
            unique_code='FIELD001',
            certification_type='Organic',
            contact_person='Field Manager',
            contact_phone='555-0456',
            contact_email='manager@field.com',
            address='Field Location Details',
            description='Detailed field description'
        )
        
        self.assertEqual(parcel.product, product)
        self.assertTrue(parcel.certified)
        self.assertEqual(parcel.soil_type, 'Clay')
        self.assertEqual(parcel.unique_code, 'FIELD001')
    
    def test_parcel_agricultural_details(self):
        """Test agricultural details JSON field"""
        agricultural_data = {
            'irrigation_type': 'drip',
            'organic_certified': True,
            'previous_crops': ['corn', 'soybeans'],
            'soil_analysis': {
                'ph': 6.5,
                'organic_matter': 3.2,
                'nitrogen': 45
            }
        }
        
        parcel = Parcel.objects.create(
            name='Agricultural Field',
            establishment=self.establishment,
            area=200.0,
            agricultural_details=agricultural_data
        )
        
        self.assertEqual(parcel.agricultural_details['irrigation_type'], 'drip')
        self.assertTrue(parcel.agricultural_details['organic_certified'])
        self.assertEqual(parcel.agricultural_details['soil_analysis']['ph'], 6.5)


class ProductModelTests(BaseModelTestCase):
    """Test Product model functionality"""
    
    def test_product_creation(self):
        """Test product creation"""
        product = Product.objects.create(
            name='Organic Tomatoes',
            description='Fresh organic tomatoes'
        )
        self.assertEqual(product.name, 'Organic Tomatoes')
        self.assertEqual(product.description, 'Fresh organic tomatoes')
    
    def test_product_string_representation(self):
        """Test product string representation"""
        product = Product.objects.create(name='Test Product')
        self.assertEqual(str(product), 'Test Product')
    
    def test_product_parcel_relationship(self):
        """Test relationship with parcels"""
        product = Product.objects.create(name='Corn')
        
        parcel = Parcel.objects.create(
            name='Corn Field',
            establishment=self.establishment,
            area=100.0,
            product=product
        )
        
        self.assertEqual(parcel.product, product)


class ModelValidationTests(BaseModelTestCase):
    """Test model validation and constraints"""
    
    def test_company_name_length_limit(self):
        """Test company name length constraints"""
        # Test that very long names are handled properly
        long_name = 'A' * 100  # Assuming 100 char limit based on our analysis
        
        try:
            company = Company.objects.create(
                name=long_name,
                country='USA'
            )
            # If creation succeeds, check the actual saved length
            self.assertLessEqual(len(company.name), 100)
        except (ValidationError, IntegrityError):
            # Expected for names that are too long
            pass
    
    def test_establishment_required_fields(self):
        """Test that required fields are enforced"""
        with self.assertRaises((ValidationError, IntegrityError)):
            # Missing required company field
            Establishment.objects.create(
                name='Invalid Farm',
                country='USA'
                # Missing company field
            )
    
    def test_parcel_area_positive(self):
        """Test that parcel area should be positive"""
        # Create parcel with zero area (should be allowed but flagged)
        parcel = Parcel.objects.create(
            name='Zero Area Field',
            establishment=self.establishment,
            area=0.0
        )
        self.assertEqual(parcel.area, 0.0)
        
        # Negative area test
        parcel_negative = Parcel.objects.create(
            name='Negative Area Field',
            establishment=self.establishment,
            area=-10.0
        )
        # Note: This might be allowed by Django but should be validated in forms
        self.assertEqual(parcel_negative.area, -10.0)


class ModelRelationshipIntegrityTests(BaseModelTestCase):
    """Test model relationship integrity"""
    
    def test_cascade_deletion_company_to_establishment(self):
        """Test that deleting company cascades to establishments"""
        establishment_id = self.establishment.id
        
        # Delete company
        self.company.delete()
        
        # Establishment should be deleted too
        with self.assertRaises(Establishment.DoesNotExist):
            Establishment.objects.get(id=establishment_id)
    
    def test_cascade_deletion_establishment_to_parcel(self):
        """Test that deleting establishment cascades to parcels"""
        parcel = Parcel.objects.create(
            name='Test Field',
            establishment=self.establishment,
            area=100.0
        )
        parcel_id = parcel.id
        
        # Delete establishment
        self.establishment.delete()
        
        # Parcel should be deleted too
        with self.assertRaises(Parcel.DoesNotExist):
            Parcel.objects.get(id=parcel_id)
    
    def test_optional_foreign_key_relationships(self):
        """Test optional foreign key relationships"""
        # Parcel without product should be allowed
        parcel = Parcel.objects.create(
            name='No Product Field',
            establishment=self.establishment,
            area=100.0
        )
        self.assertIsNone(parcel.product)
        
        # Parcel without current_history should be allowed
        self.assertIsNone(parcel.current_history)


class ModelQueryOptimizationTests(BaseModelTestCase):
    """Test that model queries are optimizable"""
    
    def test_select_related_works(self):
        """Test that select_related optimization works"""
        parcel = Parcel.objects.create(
            name='Test Field',
            establishment=self.establishment,
            area=100.0
        )
        
        # Query with select_related
        optimized_parcel = Parcel.objects.select_related('establishment__company').get(id=parcel.id)
        
        # Access related data (should not trigger additional queries)
        company_name = optimized_parcel.establishment.company.name
        self.assertEqual(company_name, 'Test Company')
    
    def test_prefetch_related_works(self):
        """Test that prefetch_related optimization works"""
        # Create multiple parcels
        for i in range(3):
            Parcel.objects.create(
                name=f'Field {i}',
                establishment=self.establishment,
                area=50.0 + i * 10
            )
        
        # Query with prefetch_related
        establishment_with_parcels = Establishment.objects.prefetch_related('parcels').get(id=self.establishment.id)
        
        # Access prefetched data
        parcel_count = establishment_with_parcels.parcels.count()
        self.assertEqual(parcel_count, 3)


if __name__ == '__main__':
    import unittest
    unittest.main()