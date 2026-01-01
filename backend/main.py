"""Compatibility entrypoint for the prototype layout.

Phase A moves the production FastAPI app to `backend.src.app.main:app`.
This module remains so existing commands like `python -m backend.main` keep working.
"""

from backend.src.app.main import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
