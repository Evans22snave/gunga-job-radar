#!/bin/bash
# Run integration tests and diagnostics for Gunga Job Radar

set -e

echo ""
echo "=========================================="
echo "GUNGA JOB RADAR — TEST & DIAGNOSTIC RUN"
echo "=========================================="
echo ""

# Check environment
if [ -z "$DATABASE_URL" ]; then
    echo "❌ DATABASE_URL not set. Loading from .env..."
    if [ -f .env ]; then
        export $(cat .env | grep -v '#' | xargs)
    else
        echo "❌ .env file not found!"
        exit 1
    fi
fi

echo "✅ Database URL configured"
echo ""

# Initialize schema
echo "Initializing database schema..."
python -m database.schema
echo ""

# Run integration tests
echo "Running integration tests..."
python -m tests
echo ""

# Run diagnostics
echo "Running diagnostics..."
python -m diagnostics
echo ""

echo "=========================================="
echo "TEST & DIAGNOSTIC RUN COMPLETE"
echo "=========================================="
