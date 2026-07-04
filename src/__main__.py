import sys
from pathlib import Path

# Put src/ (this file's parent) on sys.path so bare imports like "api:app"
# and "from api ...", "from graph ..." resolve when run via `python -m src`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=False)
