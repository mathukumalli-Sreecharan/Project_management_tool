# Project Management Tool

## Project structure

- `backend/` - FastAPI API and AI workflow modules
- `frontend/` - React and Vite application
- `artifacts/` - retained generated output
- `requirements.txt` - Python dependencies

## Run locally

From the project root, install the Python dependencies and start the API:

```powershell
python -m pip install -r requirements.txt
python -m backend.app
```

In another terminal, install and start the frontend:

```powershell
Set-Location frontend
npm install
npm run dev
```

Configure backend credentials and database settings in a root-level `.env` file.
