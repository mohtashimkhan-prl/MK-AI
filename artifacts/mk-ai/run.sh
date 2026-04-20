#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

pip install -q flask groq pillow requests flask-session werkzeug

export FLASK_APP=app.py
export FLASK_ENV=production

python3 app.py
