#!/usr/bin/env bash
# Start OpenSentara — handles setup automatically on first run.

set -e
cd "$(dirname "$0")"

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "Python 3 is required. Install it from https://python.org"
    exit 1
fi

# Check version (need 3.11+)
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.minor}')")
if [ "$PY_VERSION" -lt 11 ]; then
    echo "Python 3.11+ required (you have 3.$PY_VERSION)"
    echo "Update from https://python.org"
    exit 1
fi

# Create venv on first run
if [ ! -d "venv" ]; then
    echo "First run — setting up..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -e . -q
    echo "Ready."
else
    source venv/bin/activate
fi

# Launch
python -m opensentara
