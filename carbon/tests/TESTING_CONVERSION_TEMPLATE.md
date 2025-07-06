# Django Test Conversion Template

This document provides a template and guidelines for converting script-style test files to proper Django TestCase format.

## Conversion Process

### 1. File Structure Changes

**Before (Script Style):**
```python
#!/usr/bin/env python3
import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from some_module import some_function

def test_something():
    print("🧪 Testing something...")
    # Manual setup
    # print statements everywhere
    print("✅ Test passed")

if __name__ == "__main__":
    test_something()
```

**After (Django TestCase):**
```python
"""
Test Suite for [Module Name]

This module tests [description of what is being tested]:
- Feature 1
- Feature 2
- Feature 3
"""

from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock

from some_module import some_function

User = get_user_model()


class SomethingTestCase(TestCase):
    """Test [specific functionality]"""
    
    def setUp(self):
        """Set up test data"""
        # Create test data here
        pass
        
    def test_something_specific(self):
        """Test specific functionality with clear description"""
        # Test logic with assertions
        result = some_function()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'success')
```

### 2. Key Conversion Rules

#### A. Replace Print Statements with Assertions

**Before:**
```python
def test_calculation():
    result = calculate_something(100)
    print(f"Result: {result}")
    print(f"Expected: 200")
    if result == 200:
        print("✅ Test passed")
    else:
        print("❌ Test failed")
```

**After:**
```python
def test_calculation(self):
    """Test calculation returns expected result"""
    result = calculate_something(100)
    self.assertEqual(result, 200)
```

#### B. Convert Manual Verification to Automated Assertions

**Before:**
```python
stats = service.get_stats()
print(f"Network: {stats['network']}")
print(f"Status: {stats['status']}")
# Developer must manually verify output
```

**After:**
```python
stats = service.get_stats()
self.assertIn('network', stats)
self.assertIn('status', stats)
self.assertIsNotNone(stats['network'])
self.assertEqual(stats['status'], 'active')
```

#### C. Use setUp for Test Data Creation

**Before:**
```python
def test_something():
    # Create user every time
    user = User.objects.create_user(...)
    company = Company.objects.create(...)
    # Test logic
```

**After:**
```python
def setUp(self):
    """Set up test data"""
    self.user = User.objects.create_user(...)
    self.company = Company.objects.create(...)

def test_something(self):
    """Test something with pre-created data"""
    # Use self.user and self.company
```

#### D. Use Proper Test Method Names

**Before:**
```python
def test_complete_workflow():
    # Tests multiple things
```

**After:**
```python
def test_user_creation(self):
    """Test user creation functionality"""

def test_company_association(self):  
    """Test user-company association"""
    
def test_workflow_integration(self):
    """Test complete workflow integration"""
```

### 3. Django Test Best Practices

#### A. Use Appropriate TestCase Class

```python
# For most tests
class MyTestCase(TestCase):
    pass

# For tests that need real database transactions
class MyTestCase(TransactionTestCase):
    pass

# For tests that need client requests
from django.test import Client
class MyAPITestCase(TestCase):
    def setUp(self):
        self.client = Client()
```

#### B. Use subTest for Multiple Similar Tests

```python
def test_multiple_scenarios(self):
    """Test multiple input scenarios"""
    test_cases = [
        ('input1', 'expected1'),
        ('input2', 'expected2'),
        ('input3', 'expected3'),
    ]
    
    for input_val, expected in test_cases:
        with self.subTest(input=input_val):
            result = my_function(input_val)
            self.assertEqual(result, expected)
```

#### C. Use Mocking for External Services

```python
@patch('my_module.external_service')
def test_with_external_service(self, mock_service):
    """Test functionality that depends on external service"""
    mock_service.return_value = {'status': 'success'}
    
    result = my_function_that_uses_service()
    self.assertEqual(result['status'], 'success')
    mock_service.assert_called_once()
```

#### D. Test Error Conditions

```python
def test_error_handling(self):
    """Test proper error handling"""
    with self.assertRaises(ValueError):
        my_function(invalid_input)
        
def test_graceful_failure(self):
    """Test graceful handling of edge cases"""
    result = my_function(edge_case_input)
    self.assertIsNotNone(result)
    self.assertIn('error', result)
```

### 4. Common Assertion Patterns

#### A. Basic Assertions
```python
# Equality
self.assertEqual(actual, expected)
self.assertNotEqual(actual, unexpected)

# Truth values
self.assertTrue(condition)
self.assertFalse(condition)

# Existence
self.assertIsNone(value)
self.assertIsNotNone(value)

# Collections
self.assertIn(item, collection)
self.assertNotIn(item, collection)

# Types
self.assertIsInstance(obj, MyClass)
```

#### B. Numeric Assertions
```python
# Comparisons
self.assertGreater(a, b)
self.assertGreaterEqual(a, b)
self.assertLess(a, b)
self.assertLessEqual(a, b)

# Approximate equality for floats
self.assertAlmostEqual(a, b, places=2)
self.assertAlmostEqual(a, b, delta=0.01)
```

#### C. Exception Testing
```python
# Test that exception is raised
with self.assertRaises(SpecificException):
    function_that_should_fail()

# Test exception message
with self.assertRaisesMessage(ValueError, "Expected message"):
    function_that_should_fail()
```

#### D. HTTP Response Testing
```python
# Status codes
self.assertEqual(response.status_code, 200)
self.assertIn(response.status_code, [200, 201])

# Response content
self.assertContains(response, "expected text")
self.assertJSONEqual(response.content, expected_json)
```

### 5. Performance and Database Considerations

#### A. Use TransactionTestCase When Needed
```python
# Use TransactionTestCase for tests that need real transactions
class MyTransactionTestCase(TransactionTestCase):
    def test_transaction_behavior(self):
        # Test transaction rollback, etc.
```

#### B. Optimize Database Queries
```python
def test_efficient_queries(self):
    """Test that queries are efficient"""
    with self.assertNumQueries(2):  # Expect exactly 2 queries
        result = my_function_that_queries_db()
```

#### C. Use Factory Pattern for Complex Objects
```python
def setUp(self):
    """Set up test data efficiently"""
    self.user = User.objects.create_user(
        email='test@example.com',
        password='testpass'
    )
    # Create related objects as needed
```

### 6. Running and Debugging Tests

#### A. Run Specific Tests
```bash
# Run specific test file
poetry run python manage.py test carbon.tests.test_calculations

# Run specific test class
poetry run python manage.py test carbon.tests.test_calculations.TestCarbonCalculations

# Run specific test method
poetry run python manage.py test carbon.tests.test_calculations.TestCarbonCalculations.test_fertilizer_calculation
```

#### B. Debug Test Failures
```python
def test_with_debugging(self):
    """Test with debug output when needed"""
    result = my_function()
    
    # Use fail() with custom message for debugging
    if result is None:
        self.fail(f"Expected result but got None. Debug info: {debug_data}")
    
    self.assertEqual(result.status, 'success')
```

### 7. Example Complete Conversion

**Before (Script Style - 45 print statements):**
```python
def test_complete_workflow():
    print("🔄 Testing Complete Workflow\n")
    
    try:
        company = Company.objects.create(name="Test")
        print(f"✓ Company created: {company.name}")
        
        user = User.objects.create_user('test@example.com')
        print(f"✓ User created: {user.email}")
        
        result = some_calculation(100)
        print(f"✓ Calculation result: {result}")
        
        if result > 0:
            print("✅ Test passed")
        else:
            print("❌ Test failed")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True
```

**After (Django TestCase - 0 print statements):**
```python
class WorkflowTestCase(TestCase):
    """Test complete workflow functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.company = Company.objects.create(name="Test")
        self.user = User.objects.create_user(email='test@example.com')
        
    def test_complete_workflow(self):
        """Test complete workflow executes successfully"""
        # Test company creation
        self.assertEqual(self.company.name, "Test")
        
        # Test user creation
        self.assertEqual(self.user.email, 'test@example.com')
        
        # Test calculation
        result = some_calculation(100)
        self.assertGreater(result, 0)
        self.assertIsInstance(result, (int, float))
        
    def test_workflow_error_handling(self):
        """Test workflow handles errors gracefully"""
        with self.assertRaises(ValueError):
            some_calculation(-1)  # Invalid input
```

### 8. Benefits of Proper Django Tests

1. **Automated verification** - No manual checking needed
2. **Silent when passing** - Only output when tests fail
3. **Selective running** - Run specific tests or test classes
4. **Better CI/CD integration** - Proper exit codes and reporting
5. **Database isolation** - Each test gets clean database state
6. **Detailed failure reporting** - Clear assertion messages
7. **Performance tracking** - Query counting and timing
8. **Code coverage** - Track which code is tested

### 9. Checklist for Converting Files

- [ ] Remove `#!/usr/bin/env python3` and manual Django setup
- [ ] Convert to proper Django TestCase class structure
- [ ] Replace all `print()` statements with `self.assert*()` methods
- [ ] Move common setup to `setUp()` method
- [ ] Split large test functions into focused test methods
- [ ] Add proper docstrings for test class and methods
- [ ] Use `@patch` for mocking external services
- [ ] Add error case testing with `assertRaises`
- [ ] Remove manual pass/fail return values
- [ ] Remove `if __name__ == "__main__"` blocks
- [ ] Verify tests run with `poetry run python manage.py test`
- [ ] Ensure tests are silent when passing
- [ ] Add edge case and error condition tests

This template should be used to convert the remaining ~1000+ print statements in the test files to proper Django test assertions.