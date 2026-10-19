"""Compatibility entry point for existing `uvicorn app:app` deployments."""

from backend.app import app, main


if __name__ == "__main__":
    main()
