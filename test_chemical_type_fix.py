#!/usr/bin/env python3
"""
Test script to verify the chemical type detection fix
This simulates the frontend JavaScript logic in Python to test both formats
"""

def extract_chemical_type(type_str):
    """Simulate the JavaScript extractChemicalType function"""
    if not type_str:
        return None
    
    # Handle raw codes (FE, PE, FU, HE)
    if type_str in ['FE', 'PE', 'FU', 'HE']:
        return type_str
    
    # Handle serialized format (event.chemical.fungicide → FU)
    if 'event.chemical.fertilizer' in type_str:
        return 'FE'
    if 'event.chemical.pesticide' in type_str:
        return 'PE'
    if 'event.chemical.fungicide' in type_str:
        return 'FU'
    if 'event.chemical.herbicide' in type_str:
        return 'HE'
    
    return None

def get_chemical_type_message(type_str):
    """Simulate the chemical type message logic"""
    normalized_type = extract_chemical_type(type_str)
    
    if normalized_type == 'FE':
        return 'fertilizer application'
    elif normalized_type == 'PE':
        return 'pesticide application'
    elif normalized_type == 'FU':
        return 'fungicide application'
    elif normalized_type == 'HE':
        return 'herbicide application'
    else:
        return 'chemical application'  # fallback

# Test cases
test_cases = [
    # Raw format (original)
    ('FE', 'fertilizer application'),
    ('PE', 'pesticide application'), 
    ('FU', 'fungicide application'),
    ('HE', 'herbicide application'),
    
    # Serialized format (from backend)
    ('event.chemical.fertilizer', 'fertilizer application'),
    ('event.chemical.pesticide', 'pesticide application'),
    ('event.chemical.fungicide', 'fungicide application'),
    ('event.chemical.herbicide', 'herbicide application'),
    
    # Edge cases
    (None, 'chemical application'),
    ('', 'chemical application'),
    ('unknown', 'chemical application'),
]

print("🧪 Testing Chemical Type Detection Fix")
print("=" * 50)

all_passed = True
for input_type, expected in test_cases:
    result = get_chemical_type_message(input_type)
    status = "✅ PASS" if result == expected else "❌ FAIL"
    if result != expected:
        all_passed = False
    
    print(f"{status} Input: '{input_type}' → '{result}' (expected: '{expected}')")

print("=" * 50)
if all_passed:
    print("🎉 All tests passed! The fix should work correctly.")
    print()
    print("Key improvements:")
    print("- ✅ Raw codes (FU, PE, etc.) still work")
    print("- ✅ Serialized format (event.chemical.fungicide) now works") 
    print("- ✅ Fungicides will now show 'fungicide application' instead of 'chemical application'")
    print("- ✅ Backward compatible with existing data")
else:
    print("❌ Some tests failed. Please review the logic.")