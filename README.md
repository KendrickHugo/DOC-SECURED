# DOC-SECURE

An encrypted QR document-request system for the University of the Assumption. This repository is arranged into separate `frontend/` and `backend/` folders so the student app, staff workspaces, API, and cryptography code are easy to locate.

## Repository map

```text
frontend/
  index.html                 Portal entry page
  login/                     Separate student, cashier, registrar sign-in routes
  student.html               Student request and status dashboard
  cashier.html               Receipt and OR review dashboard
  registrar.html             Request decision, QR scan, claim, audit dashboard
  js/app.js                  Role routing and workflow UI
  js/crypto.js               Browser AES-256-GCM envelope helper
  styles.css                 Shared responsive design system
  server.js                  Local static frontend server
backend/
  api/main.py                FastAPI auth, request, review and fulfillment routes
  api/crypto_bridge.py       Python AES-256-GCM envelope helper
  java/.../CryptoService.java Java AES-256-GCM service example
  requirements.txt           Python dependencies
  start.ps1                  Local backend launcher
```

## Run locally on Windows

Open two PowerShell terminals from the repository folder.

Terminal 1:

```powershell
Set-Location .\frontend
node .\server.js
```

Terminal 2:

```powershell
Set-Location .\backend
.\start.ps1
```

Open `http://localhost:8080`. The API listens on `http://localhost:8001`. `uv` downloads the packages listed in `backend/requirements.txt` on first start. QR camera access requires localhost or HTTPS; the QR renderer and camera scanner load from public CDNs.

## Demo accounts

The local backend seeds these sample identities into its SQLite database on first start:

| Role | ID | Password | Extra credential |
|---|---|---|---|
| Student | `2024-01842` | `StudentDemo!2026` | — |
| Cashier | `EMP-00421` | `CashierDemo!2026` | Terminal PIN: `4821` |
| Registrar | `REG-00158` | `RegistrarDemo!2026` | Security token: `REG-UA-7319` |

These are public demo credentials, not real UA accounts. Passwords are stored as salted scrypt hashes. Do not reuse them or expose the demo backend as a production login service.

## Seven-stage document workflow

1. **Authentication:** separate student, cashier, and registrar sign-ins with role checks.
2. **Checklist:** students choose Copy of Grades, Transcript of Records, and/or Certificate of Enrollment. Clearance flags trigger a digital undertaking before submission.
3. **Payment:** students upload a PNG/JPEG/WebP payment screenshot and enter the Official Receipt (OR) reference. Requests wait in the cashier review queue.
4. **Verification and decision:** cashiers verify proof and OR details; registrars inspect the request and approve or reject it with a reason.
5. **Encrypted QR:** only approved requests can receive a short-lived AES-256-GCM encrypted QR containing request/document IDs, OR reference, undertaking state, timestamp, and a random nonce.
6. **Counter validation:** the registrar scanner checks the GCM authentication tag, expiry, current request binding, and single-use nonce.
7. **Fulfillment:** after a successful scan, the registrar confirms physical handover and marks the request claimed. Workflow events are written to an append-only SQLite audit table.

The document fees currently displayed are sample values for the demo, not official UA rates.

## Cryptography and deployment notes

The Web Crypto, Python, and Java helpers use AES-256-GCM, a fresh 12-byte IV, a 128-bit tag, and authenticated additional data. The API keeps the key server-side and issues the QR envelope; the browser never receives a shared production key. The default local key and generated session secret are development-only. Production startup requires `APP_ENV=production`, `PORTAL_AES256_KEY_B64`, and a `PORTAL_SESSION_SECRET` of at least 32 characters.

This is a local demo: SQLite, sample users, file-based receipt storage, and cashier approval are not a substitute for UA identity, payment, and records systems. Use HTTPS, secret management, rate limiting, secure server-side sessions, access-controlled object storage, database backups, and a payment provider integration before production. GitHub stores this source code; GitHub Pages cannot run the Python API. A hosted deployment needs a separate backend host and a configured frontend API URL/CORS allowlist.
