# Backend

`api/main.py` runs the FastAPI service. `api/crypto_bridge.py` is the Python AES-256-GCM envelope implementation; `java/edu/ua/docsecure/portal/security/CryptoService.java` provides the matching Java service example.

Run `./start.ps1` from this folder. The API serves port 8001 and creates `portal_demo.sqlite3` plus `private_uploads/` beside this README. Both are local runtime data and ignored by Git.

## Main routes

- `POST /api/auth/{student|cashier|registrar}` and `GET /api/session/me`
- `GET /api/students/me`, `GET /api/students/me/document-options`, `GET /api/students/me/requests`
- `POST /api/students/requests`, `POST /api/students/requests/{id}/resubmit`, `POST /api/students/requests/{id}/qr`
- `GET /api/cashier/payment-queue`, `POST /api/cashier/requests/{id}/verify-payment`
- `GET /api/registrar/requests`, `POST /api/registrar/requests/{id}/decision`
- `POST /api/registrar/verify-qr`, `POST /api/registrar/requests/{id}/claim`, `GET /api/registrar/audit`

All workflow routes require a signed bearer session and enforce the role that owns the action. Receipt images are limited to 2 MB and stored under a generated filename outside the public frontend. The audit table uses SQLite triggers to prevent update and delete operations.
