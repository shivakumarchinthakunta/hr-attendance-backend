# Employee Attendance & Analytics API

FastAPI + MongoDB backend based on the supplied HROne engineering assignment.

## Run

1. Install Python 3.11+ and MongoDB 6.0+.
2. `python -m venv .venv` and activate it.
3. `pip install -r requirements.txt`
4. Set `MONGO_URI` and `MONGO_DB` in your environment.
5. `uvicorn app.main:app --port 8000`
6. Open `http://localhost:8000/docs`; `GET /health` checks MongoDB.

The application creates indexes at startup. Do not commit secrets or `.env`.

## Important contract note

Only `PROBLEM_STATEMENT.docx` was supplied. The assignment also specifies `openapi.yaml`,
`DATA_MODEL.md`, a starter `app/main.py`, seed data, and templates. Since those files were
not available, endpoint field names and some response envelopes are inferred from the
problem statement. Validate and adjust against the official OpenAPI contract before submission.
This is a working scaffold, not a claim of hidden-test compliance. Test concurrency and the
MongoDB aggregation stages against your target MongoDB 6.0+ deployment.
