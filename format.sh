#!/bin/bash

# Trazo Backend - Code Formatting Script
# Run this before committing to prevent CI/CD failures

echo "🎨 Formatting Trazo Backend Code..."
echo "=================================="

# Navigate to backend directory
cd "$(dirname "$0")"

echo "📝 Running Black formatter..."
poetry run black .

echo "📦 Sorting imports with isort..."
poetry run isort .

echo "🔍 Running critical linting checks..."
poetry run flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=.venv,venv,node_modules,.git,__pycache__,migrations

echo ""
echo "✅ Formatting complete!"
echo ""
echo "🔬 Running verification checks..."
echo "=================================="

# Verification
echo "Checking Black formatting..."
if poetry run black --check --diff .; then
    echo "✅ Black formatting: PASSED"
else
    echo "❌ Black formatting: FAILED"
    exit 1
fi

echo "Checking import sorting..."
if poetry run isort --check-only --diff .; then
    echo "✅ Import sorting: PASSED" 
else
    echo "❌ Import sorting: FAILED"
    exit 1
fi

echo "Checking critical linting..."
if poetry run flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=.venv,venv,node_modules,.git,__pycache__,migrations; then
    echo "✅ Critical linting: PASSED"
else
    echo "❌ Critical linting: FAILED"
    exit 1
fi

echo ""
echo "🎉 All formatting checks PASSED!"
echo "✅ Code is ready for CI/CD pipeline"
echo ""