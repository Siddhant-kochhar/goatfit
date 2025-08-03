#!/bi#!/bin/bash

# GoatFit Health Monitoring System
# Quick startup script

echo "🏥 GoatFit - Emergency Health Monitoring System"/bash

# HadesFit Health Monitoring System
# Clean startup script for the emergency alert system

echo "� HadesFit - Emergency Health Monitoring System"
echo "================================================"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created"
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install/upgrade dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Start the server with reload functionality
echo "🚀 Starting GoatFit server with auto-reload..."
echo "🌐 Open: http://localhost:8000"
echo "📊 Dashboard: http://localhost:8000/fit"
echo "❤️ Vitals: http://localhost:8000/vitals"
echo "🏥 Automated Monitoring: http://localhost:8000/monitoring-dashboard"
echo "🔄 Auto-reload enabled - changes will restart server automatically"
echo "=================================="

# Use uvicorn with proper import string for reload functionality
uvicorn app:app --host 0.0.0.0 --port 8000 --reload --reload-dir .
