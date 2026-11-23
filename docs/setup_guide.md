# Setup guide

Requires Python 3.10+ and Node 18+.

## 1. Backend

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows (cmd): .venv\Scripts\activate
                                     # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                 # optional (Windows: copy .env.example .env)
uvicorn backend.app.main:app --reload --port 8000
```

Check: `curl localhost:8000/api/health` → `{"status":"ok",...}`.
The SQLite file is created at `data/agent_monitoring.db` on first start.

Always run from the **project root**, not from `backend/`. Imports are `backend.app...`
and `reviewer`.

## 2. Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # production build into frontend/dist
```

In dev, Vite forwards `/api/*` to `http://127.0.0.1:8000`, so no CORS setup is needed.
To point at a different backend, copy `frontend/.env.example` to `frontend/.env` and set
`VITE_PROXY_TARGET` (dev proxy) or `VITE_API_BASE_URL` (direct calls; then add that
site's origin to `CORS_ORIGINS` in the root `.env`).

## 3. Tests

```bash
pytest                       # everything
pytest tests/test_reviewer.py    # Person 2 only: no backend imports
pytest tests/test_agent.py tests/test_trace.py   # Person 1 only
```

Tests use an in-memory database and never write to `data/`.

## Working independently

- **Reviewer only:** `pip install jsonschema pytest`, then `pytest tests/test_reviewer.py`.
  Try the reviewer by hand:
  ```python
  import json
  from reviewer import review_execution
  e = json.load(open("shared/sample_data/sample_execution.json"))
  v = json.load(open("shared/sample_data/sample_evidence.json"))
  print(review_execution(e, v)["verdict"])
  ```
- **Frontend only:** `cd frontend && npm run dev` with no backend running. It shows the
  bundled samples.
- **Backend only:** use `http://localhost:8000/docs`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: backend` or `reviewer` | Run from the project root. |
| Frontend banner says backend not reachable | Start uvicorn on port 8000, or set `VITE_PROXY_TARGET`. |
| Port already in use | `uvicorn ... --port 8001` and set `VITE_PROXY_TARGET=http://127.0.0.1:8001`. |
| Want a clean slate | Stop the server, delete `data/agent_monitoring.db` and `data/executions/*.json`, `data/evaluation/*.json`. |
| `test_samples_are_in_sync...` fails | Run `python scripts/generate_samples.py`. |
