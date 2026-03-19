#!/usr/bin/env bash
# Start OpenSentara — handles setup automatically on first run.

set -e
cd "$(dirname "$0")"

# Find the best Python (3.13, 3.12, 3.11, or python3)
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        # Need 3.11+ but skip 3.14+ (pre-release, unstable)
        if [ "$ver" -ge 11 ] 2>/dev/null && [ "$ver" -le 13 ] 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    # Check if they have 3.14+ (too new)
    TOO_NEW=""
    for candidate in python3.14 python3; do
        if command -v "$candidate" &>/dev/null; then
            ver=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
            if [ "$ver" -ge 14 ] 2>/dev/null; then
                TOO_NEW="3.$ver"
                break
            fi
        fi
    done

    echo ""
    if [ -n "$TOO_NEW" ]; then
        echo "  Python $TOO_NEW detected but it's too new (pre-release)."
        echo "  OpenSentara requires Python 3.11, 3.12, or 3.13."
    else
        echo "  Python 3.11+ is required but not found."
    fi
    echo ""
    echo "  Install Python 3.12:"
    echo "    Mac:     https://www.python.org/downloads/release/python-31210/"
    echo "    Windows: https://www.python.org/downloads/release/python-31210/"
    echo "    Linux:   sudo apt install python3.12"
    echo ""
    echo "  After installing, close this terminal, open a new one, and run ./start.sh again."
    echo ""
    exit 1
fi

echo "Using $PYTHON ($(${PYTHON} --version 2>&1))"

# Kill any existing instance on port 8080
if lsof -ti:8080 &>/dev/null; then
    echo "Stopping previous instance..."
    kill $(lsof -ti:8080) 2>/dev/null || true
    sleep 1
fi

# Create venv on first run
if [ ! -d "venv" ]; then
    echo "First run — setting up..."
    "$PYTHON" -m venv venv
    source venv/bin/activate
    pip install -e . -q
    echo "Ready."
else
    source venv/bin/activate
fi

# Load .env file if it exists (API keys, etc.)
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Open browser after a short delay (background)
(sleep 2 && open http://localhost:8080 2>/dev/null || xdg-open http://localhost:8080 2>/dev/null) &

# Launch
python -m opensentara
