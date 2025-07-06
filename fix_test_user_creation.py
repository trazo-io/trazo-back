#!/usr/bin/env python3
"""
Script to fix User.objects.create_user calls that incorrectly use company parameter
"""

import os
import re

def fix_user_creation_in_file(file_path):
    """Fix user creation patterns in a single file"""
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Pattern to match User.objects.create_user with company parameter
    pattern = r'(\s+)self\.user = User\.objects\.create_user\(\s*\n(\s+email=.*?,)\s*\n(\s+password=.*?,)\s*\n(\s+company=self\.company)\s*\n(\s+)\)'
    
    def replacement(match):
        indent = match.group(1)
        email_line = match.group(2)
        password_line = match.group(3)
        closing_indent = match.group(5)
        
        return f"""{indent}self.user = User.objects.create_user(
{email_line}
{password_line}
{closing_indent})
{indent}
{indent}# Create WorksIn relationship
{indent}from users.models import WorksIn
{indent}WorksIn.objects.create(
{indent}    user=self.user,
{indent}    company=self.company,
{indent}    role=WorksIn.COMPANY_ADMIN
{indent})"""
    
    new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    # Also handle cases where it's all on multiple lines with different formatting
    pattern2 = r'(\s+)self\.user = User\.objects\.create_user\(\s*\n(\s+email=.*?),\s*\n(\s+password=.*?),\s*\n(\s+.*?company.*?)\n(\s+)\)'
    
    def replacement2(match):
        indent = match.group(1)
        email_line = match.group(2).strip()
        password_line = match.group(3).strip()
        closing_indent = match.group(5)
        
        return f"""{indent}self.user = User.objects.create_user(
{indent}    {email_line},
{indent}    {password_line}
{closing_indent})
{indent}
{indent}# Create WorksIn relationship
{indent}from users.models import WorksIn
{indent}WorksIn.objects.create(
{indent}    user=self.user,
{indent}    company=self.company,
{indent}    role=WorksIn.COMPANY_ADMIN
{indent})"""
    
    new_content = re.sub(pattern2, replacement2, new_content, flags=re.MULTILINE)
    
    if new_content != content:
        with open(file_path, 'w') as f:
            f.write(new_content)
        print(f"Fixed user creation in {file_path}")
        return True
    return False

def main():
    # Find all test files in carbon/tests/
    test_dir = "/Users/oscarmunoz/dev/trazo/trazo-back/carbon/tests"
    
    fixed_files = []
    for filename in os.listdir(test_dir):
        if filename.endswith('.py') and filename.startswith('test_'):
            file_path = os.path.join(test_dir, filename)
            if fix_user_creation_in_file(file_path):
                fixed_files.append(filename)
    
    print(f"\nFixed {len(fixed_files)} files:")
    for filename in fixed_files:
        print(f"  - {filename}")

if __name__ == "__main__":
    main()