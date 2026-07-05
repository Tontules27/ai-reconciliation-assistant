"""Run the read-only reconciliation portal.

Usage:
    python portal.py            # http://127.0.0.1:8050
"""

from app.main import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
