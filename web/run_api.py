"""Run the bracket API server. Run from project root: python web/run_api.py"""
import sys
from pathlib import Path

# Add project root to path so bot imports work
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "web.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
