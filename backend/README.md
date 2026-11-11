# ALE backend

Python 3.10+; FastAPI, SQLAlchemy Core reflection, PyMySQL, existing MySQL only.

```sh
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
python -m pytest -q
```

Run from `backend`. No DDL, migrations, `create_all`, or business-data seeding occurs. Apply the parent-managed phase-one migration before database endpoints are used: `auth_sessions`, `invitations`, `app_settings`, `users.token_version`, and `batches/samples.row_version` are required. All existing base tables are reflected, including foreign keys used to protect deletion even for CASCADE/SET NULL relationships.

Configuration reads `database/.appcreds` (flat account blocks or INI sections), explicitly selecting `ale_app`. Environment overrides: `ALE_DB_HOST` (Windows `127.0.0.1`, otherwise `172.16.10.254`), `ALE_DB_PORT` (`3307`), `ALE_DB_NAME`, `ALE_DB_PASSWORD`, `ALE_JWT_SECRET`, `ALE_COOKIE_SECURE` (`false` for development), and comma-separated `ALE_ALLOWED_ORIGINS`. Generated local `.env` and `.setup-code` contain secrets; never commit or log them. Retrieve the setup code locally and submit it to `/api/v1/auth/setup`; setup is available only with an empty users table. Passwords use Argon2.

Access expires after 3600 seconds; refresh expires after 604800 seconds and rotates once per successful refresh. Refresh is available both in the contract response and an HttpOnly SameSite Strict cookie scoped to `/api/v1/auth`. Empty refresh body uses the cookie; cookie requests reject disallowed Origins. Localhost, 127.0.0.1, and 172.16.10.3 frontend ports are supported. Every authenticated request checks session revocation and user token version. Password, role, and status changes revoke all user sessions. Auth rate limiting is bounded in memory at 10 requests/minute/IP; deploy a single process or add a shared limiter before multi-worker operation. Forwarded headers are not trusted.

Operators create/edit owned batches and samples; viewers read owned data. Sample access requires both sample and batch ownership. Admin-created samples inherit the batch owner; clients cannot change ownership. Only admins delete, and scientific references block deletion. PATCH accepts optional `expected_row_version`; supplied stale versions return 409. Clients omitting it receive serialized last-write-wins updates; use the returned `row_version` to opt into stale-write protection. Parent/batch/type cannot be patched. DECIMAL input must be a plain decimal string; unknown values remain null. Exclusion is metadata and requires a reason.

`/health` executes SELECT 1. `/api-contract` serves the full canonical bundle. `/openapi.json` and `/docs` describe implemented endpoints with `x-implementation: phase1`; actual request models reflect the stricter security extensions. Frontend dist is served with SPA fallback; unknown API routes return enveloped 404. Audit writes occur in the same transaction and exclude raw requests, secret fields, and changed values.

Integration tests use `ale_app` against real MySQL, an outer rollback transaction, and per-request SAVEPOINTs via a database dependency override. They never create schema or commit test records. They skip while the parent migration is absent. Test inserts can consume auto-increment sequence numbers despite rollback.

### Optional contract validation tools (Windows)

From the project root, install optional tooling with its application constraints:

```powershell
backend\.venv-win\Scripts\python.exe -m pip install --only-binary=:all: -r api\tools\requirements-validation.txt
backend\.venv-win\Scripts\python.exe -m pip check
backend\.venv-win\Scripts\python.exe api\tools\validate_contract.py --no-db
```

Do not install an unconstrained latest `openapi-spec-validator` into the application environment. Its transitive `pydantic-settings` dependency can require a newer `python-dotenv` than the application pins, causing the launcher's dependency check to fail. The validation requirements pin compatible tooling and apply `backend/requirements.txt` as constraints; they are not application runtime requirements.
