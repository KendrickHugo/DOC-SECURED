"""DOC-SECURE demo API for encrypted document requests.

This local capstone demo uses SQLite and sample accounts. Replace demo identities,
payment review, storage, and session policies before connecting real university data.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from cryptography.exceptions import InvalidTag
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .crypto_bridge import decrypt_json, encrypt_json

ROOT = Path(__file__).resolve().parents[1]
ON_VERCEL = any(os.environ.get(name) for name in ("VERCEL", "VERCEL_ENV", "VERCEL_URL"))
RUNTIME_DIR = Path("/tmp/docsecure") if ON_VERCEL else ROOT
DATABASE = Path(os.environ.get("PORTAL_DATABASE", RUNTIME_DIR / "portal_demo.sqlite3"))
UPLOADS = Path(os.environ.get("PORTAL_UPLOADS", RUNTIME_DIR / "private_uploads"))
APP_ENV = os.environ.get("APP_ENV", "development").lower()
SESSION_SECRET = os.environ.get("PORTAL_SESSION_SECRET", "")
if APP_ENV == "production" and len(SESSION_SECRET) < 32:
    raise RuntimeError("Set PORTAL_SESSION_SECRET to a random secret of at least 32 characters")
if len(SESSION_SECRET) < 32:
    SESSION_SECRET = secrets.token_urlsafe(48)

DEMO_KEY = base64.b64encode(hashlib.sha256(b"DOC-SECURE local demo AES key only").digest()).decode("ascii")
if APP_ENV == "production" and not os.environ.get("PORTAL_AES256_KEY_B64"):
    raise RuntimeError("Set PORTAL_AES256_KEY_B64 in production")
try:
    AES_KEY = base64.b64decode(os.environ.get("PORTAL_AES256_KEY_B64", DEMO_KEY), validate=True)
except ValueError as exc:
    raise RuntimeError("PORTAL_AES256_KEY_B64 must be valid base64") from exc
if len(AES_KEY) != 32:
    raise RuntimeError("PORTAL_AES256_KEY_B64 must decode to exactly 32 bytes")

AAD = b"ua-doc-secure-document-request-v1"
UNDERTAKING_VERSION = "ua-doc-undertaking-v1"
DEMO_USERS = [
    {"role": "student", "identifier": "2024-01842", "password": "StudentDemo!2026", "name": "Maya Santos", "pin": None, "token": None},
    {"role": "cashier", "identifier": "EMP-00421", "password": "CashierDemo!2026", "name": "Jordan Reyes", "pin": "4821", "token": None},
    {"role": "registrar", "identifier": "REG-00158", "password": "RegistrarDemo!2026", "name": "Alex Morgan", "pin": None, "token": "REG-UA-7319"},
]
DOCUMENTS = {
    "GRADES": {"id": "GRADES", "name": "Copy of Grades", "fee": 150.0, "prerequisite": "Active student record"},
    "TOR": {"id": "TOR", "name": "Transcript of Records", "fee": 500.0, "prerequisite": "Library and financial clearance"},
    "COE": {"id": "COE", "name": "Certificate of Enrollment", "fee": 100.0, "prerequisite": "Current enrollment"},
}
MAX_PAPERS_PER_REQUEST = 10
SAMPLE_STUDENT = {
    "student_id": "2024-01842",
    "name": "Maya Santos",
    "program": "BS Computer Science · Year 2",
    "email": "maya.santos@ua.example",
    "enrollment_status": "Enrolled",
    "balance_cents": 1845000,
    "units": 21,
}

app = FastAPI(title="DOC-SECURE Document Request API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def password_hash(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt, digest


def audit(connection: sqlite3.Connection, actor_id: str, actor_role: str, action: str,
          target_type: str, target_id: str, details: dict[str, Any] | None = None) -> None:
    connection.execute(
        "INSERT INTO audit_log (actor_id, actor_role, action, target_type, target_id, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (actor_id, actor_role, action, target_type, target_id,
         json.dumps(details or {}, separators=(",", ":")), now_iso()),
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_database() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              identifier TEXT PRIMARY KEY, role TEXT NOT NULL, name TEXT NOT NULL,
              password_salt BLOB NOT NULL, password_digest BLOB NOT NULL,
              pin_digest BLOB, token_digest BLOB
            );
            CREATE TABLE IF NOT EXISTS students (
              student_id TEXT PRIMARY KEY, name TEXT NOT NULL, program TEXT NOT NULL,
              email TEXT NOT NULL, enrollment_status TEXT NOT NULL,
              balance_cents INTEGER NOT NULL, units INTEGER NOT NULL, holds_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS document_requests (
              id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(student_id),
              document_ids_json TEXT NOT NULL, document_quantities_json TEXT NOT NULL DEFAULT '{}', amount_cents INTEGER NOT NULL,
              or_number TEXT NOT NULL UNIQUE, undertaking_signed INTEGER NOT NULL,
              undertaking_version TEXT NOT NULL, proof_filename TEXT NOT NULL,
              proof_mime TEXT NOT NULL, proof_path TEXT NOT NULL,
              status TEXT NOT NULL, rejection_stage TEXT, rejection_reason TEXT,
              payment_verified_by TEXT, payment_verified_at TEXT,
              reviewed_by TEXT, reviewed_at TEXT,
              qr_nonce_hash TEXT, qr_expires_at INTEGER, qr_used_at TEXT,
              backup_code_hash TEXT, backup_code_expires_at INTEGER, backup_code_used_at TEXT,
              counter_verified_by TEXT, counter_verified_at TEXT,
              claimed_by TEXT, claimed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL,
              actor_role TEXT NOT NULL, action TEXT NOT NULL,
              target_type TEXT NOT NULL, target_id TEXT NOT NULL,
              details_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS audit_log_no_update
              BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'Audit log is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
              BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'Audit log is append-only'); END;
            CREATE TABLE IF NOT EXISTS counter_code_attempts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL,
              attempted_at INTEGER NOT NULL
            );
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(students)")}
        if "holds_json" not in columns:
            connection.execute("ALTER TABLE students ADD COLUMN holds_json TEXT NOT NULL DEFAULT '[]'")
            connection.execute("UPDATE students SET holds_json = ? WHERE student_id = ?", (json.dumps(["Library clearance pending"]), SAMPLE_STUDENT["student_id"]))
        request_columns = {row["name"] for row in connection.execute("PRAGMA table_info(document_requests)")}
        for name, declaration in (
            ("document_quantities_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("backup_code_hash", "TEXT"),
            ("backup_code_expires_at", "INTEGER"),
            ("backup_code_used_at", "TEXT"),
        ):
            if name not in request_columns:
                connection.execute(f"ALTER TABLE document_requests ADD COLUMN {name} {declaration}")
        for user in DEMO_USERS:
            if connection.execute("SELECT 1 FROM users WHERE identifier = ?", (user["identifier"],)).fetchone():
                continue
            salt, digest = password_hash(user["password"])
            pin_digest = hashlib.sha256(user["pin"].encode()).digest() if user["pin"] else None
            token_digest = hashlib.sha256(user["token"].encode()).digest() if user["token"] else None
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user["identifier"], user["role"], user["name"], salt, digest, pin_digest, token_digest),
            )
        connection.execute(
            "INSERT OR IGNORE INTO students (student_id, name, program, email, enrollment_status, balance_cents, units, holds_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (*SAMPLE_STUDENT.values(), json.dumps(["Library clearance pending"])),
        )


init_database()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def session_user(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    try:
        body, signature = authorization[7:].split(".", 1)
        expected = b64url(hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid session signature")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("Session expired")
        return {"identifier": str(payload["sub"]), "role": str(payload["role"])}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Your session is invalid or expired. Please sign in again.") from exc


def require_role(*roles: str):
    def dependency(user: dict[str, str] = Depends(session_user)) -> dict[str, str]:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Your account does not have access to this action.")
        return user
    return dependency


def sign_session(identifier: str, role: str) -> str:
    payload = {"sub": identifier, "role": role, "exp": int(time.time()) + 1800}
    body = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signature = b64url(hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)
    terminalPin: str | None = Field(default=None, max_length=20)
    securityToken: str | None = Field(default=None, max_length=80)


class ProofFields(BaseModel):
    proofFilename: str = Field(min_length=1, max_length=120)
    proofMime: str
    proofBase64: str = Field(min_length=1)


class CreateRequest(ProofFields):
    documentIds: list[str] = Field(min_length=1, max_length=10)
    documentQuantities: dict[str, int] = Field(default_factory=dict)
    orNumber: str = Field(min_length=3, max_length=80)
    undertakingSigned: bool
    undertakingVersion: str | None = None


class ResubmitRequest(ProofFields):
    orNumber: str = Field(min_length=3, max_length=80)
    undertakingSigned: bool
    undertakingVersion: str | None = None


class PaymentReview(BaseModel):
    valid: bool
    reason: str | None = Field(default=None, max_length=300)


class RegistrarDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str | None = Field(default=None, max_length=500)


class RequestId(BaseModel):
    requestId: str


class EnvelopeRequest(BaseModel):
    envelope: dict[str, Any]


class BackupCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)


def get_student(student_id: str) -> dict[str, Any]:
    with database() as connection:
        row = connection.execute("SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Student account was not found.")
    student = dict(row)
    student["holds"] = json.loads(student.pop("holds_json"))
    student["balance"] = student["balance_cents"] / 100
    return student


def decode_proof(filename: str, mime: str, encoded: str) -> tuple[str, Path]:
    allowed = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
    if mime not in allowed:
        raise HTTPException(status_code=415, detail="Upload a PNG, JPEG, or WebP payment screenshot.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="The payment screenshot upload is invalid.") from exc
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Payment screenshots must be 2 MB or smaller.")
    # Check basic magic bytes to prevent mismatched file extensions and content types.
    signatures = {"image/png": data.startswith(b"\x89PNG\r\n\x1a\n"), "image/jpeg": data.startswith(b"\xff\xd8\xff"), "image/webp": len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"}
    if not signatures[mime]:
        raise HTTPException(status_code=415, detail="The file contents do not match the selected image type.")
    stored_name = f"{uuid.uuid4().hex}{allowed[mime]}"
    target = UPLOADS / stored_name
    target.write_bytes(data)
    clean_name = Path(filename).name.replace("\x00", "")[:120] or "payment-proof"
    return clean_name, target


def document_names(ids: list[str], quantities: dict[str, int]) -> list[str]:
    return [
        f"{DOCUMENTS[item]['name']} × {quantities.get(item, 1)}"
        for item in ids if item in DOCUMENTS
    ]


def validated_quantities(document_ids: list[str], requested: dict[str, int]) -> dict[str, int]:
    selected = set(document_ids)
    if set(requested) - selected:
        raise HTTPException(status_code=422, detail="Paper counts may only be set for selected documents.")
    quantities = {document_id: requested.get(document_id, 1) for document_id in document_ids}
    if any(type(count) is not int or not 1 <= count <= MAX_PAPERS_PER_REQUEST for count in quantities.values()):
        raise HTTPException(status_code=422, detail=f"Choose between 1 and {MAX_PAPERS_PER_REQUEST} papers for each selected document.")
    if sum(quantities.values()) > MAX_PAPERS_PER_REQUEST:
        raise HTTPException(status_code=422, detail=f"A request can include at most {MAX_PAPERS_PER_REQUEST} papers total.")
    return quantities


def row_with_details(row: sqlite3.Row, include_proof: bool = False) -> dict[str, Any]:
    item = dict(row)
    ids = json.loads(item.pop("document_ids_json"))
    try:
        saved_quantities = json.loads(item.pop("document_quantities_json", "{}") or "{}")
    except (TypeError, json.JSONDecodeError):
        saved_quantities = {}
    quantities = {document_id: int(saved_quantities.get(document_id, 1)) for document_id in ids}
    item["documentIds"] = ids
    item["documentQuantities"] = quantities
    item["documents"] = document_names(ids, quantities)
    item["amount"] = item.pop("amount_cents") / 100
    item["orNumber"] = item.pop("or_number")
    item["undertakingSigned"] = bool(item.pop("undertaking_signed"))
    item["createdAt"] = item.pop("created_at")
    item["updatedAt"] = item.pop("updated_at")
    item["rejectionReason"] = item.pop("rejection_reason")
    item["rejectionStage"] = item.pop("rejection_stage")
    item["studentId"] = item.pop("student_id")
    item["studentName"] = item.pop("student_name", "")
    item["proofFilename"] = item.pop("proof_filename")
    item["proofMime"] = item.pop("proof_mime")
    if include_proof:
        file_path = Path(item.pop("proof_path"))
        if file_path.exists():
            item["proofDataUrl"] = f"data:{item['proofMime']};base64,{base64.b64encode(file_path.read_bytes()).decode('ascii')}"
    else:
        item.pop("proof_path", None)
    for field in ("payment_verified_by", "payment_verified_at", "reviewed_by", "reviewed_at", "counter_verified_by", "counter_verified_at", "claimed_by", "claimed_at", "qr_nonce_hash", "qr_expires_at", "qr_used_at", "backup_code_hash", "backup_code_expires_at", "backup_code_used_at", "undertaking_version"):
        item.pop(field, None)
    return item


def fetch_requests(where: str, values: tuple[Any, ...], include_proof: bool = False) -> list[dict[str, Any]]:
    with database() as connection:
        rows = connection.execute(
            f"SELECT r.*, s.name AS student_name FROM document_requests r JOIN students s ON s.student_id = r.student_id WHERE {where} ORDER BY r.created_at DESC LIMIT 100",
            values,
        ).fetchall()
    return [row_with_details(row, include_proof) for row in rows]


def get_request(request_id: str) -> dict[str, Any]:
    with database() as connection:
        row = connection.execute(
            "SELECT r.*, s.name AS student_name FROM document_requests r JOIN students s ON s.student_id = r.student_id WHERE r.id = ?",
            (request_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document request not found.")
    return row_with_details(row)


def add_request(student_id: str, document_ids: list[str], document_quantities: dict[str, int], or_number: str, undertaking: bool,
                undertaking_version: str | None, proof_filename: str, proof_mime: str,
                proof_path: Path, actor: dict[str, str], request_id: str | None = None) -> str:
    request_id = request_id or str(uuid.uuid4())
    total_cents = sum(round(DOCUMENTS[item]["fee"] * 100) * document_quantities[item] for item in document_ids)
    timestamp = now_iso()
    try:
        with database() as connection:
            if request_id:
                existing = connection.execute("SELECT status FROM document_requests WHERE id = ? AND student_id = ?", (request_id, student_id)).fetchone()
                if existing:
                    connection.execute(
                        "UPDATE document_requests SET document_quantities_json=?, amount_cents=?, or_number=?, proof_filename=?, proof_mime=?, proof_path=?, undertaking_signed=?, undertaking_version=?, status='PENDING_PAYMENT_REVIEW', rejection_stage=NULL, rejection_reason=NULL, payment_verified_by=NULL, payment_verified_at=NULL, reviewed_by=NULL, reviewed_at=NULL, qr_nonce_hash=NULL, qr_expires_at=NULL, qr_used_at=NULL, backup_code_hash=NULL, backup_code_expires_at=NULL, backup_code_used_at=NULL, counter_verified_by=NULL, counter_verified_at=NULL, claimed_by=NULL, claimed_at=NULL, updated_at=? WHERE id=?",
                        (json.dumps(document_quantities, sort_keys=True), total_cents, or_number, proof_filename, proof_mime, str(proof_path), int(undertaking), undertaking_version or "", timestamp, request_id),
                    )
                    audit(connection, actor["identifier"], actor["role"], "REQUEST_RESUBMITTED", "document_request", request_id, {"orNumber": or_number})
                    return request_id
            connection.execute(
                "INSERT INTO document_requests (id, student_id, document_ids_json, document_quantities_json, amount_cents, or_number, undertaking_signed, undertaking_version, proof_filename, proof_mime, proof_path, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_PAYMENT_REVIEW', ?, ?)",
                (request_id, student_id, json.dumps(document_ids), json.dumps(document_quantities, sort_keys=True), total_cents, or_number, int(undertaking), undertaking_version or "", proof_filename, proof_mime, str(proof_path), timestamp, timestamp),
            )
            audit(connection, actor["identifier"], actor["role"], "REQUEST_SUBMITTED", "document_request", request_id, {"documentIds": document_ids, "documentQuantities": document_quantities, "orNumber": or_number, "amount": total_cents / 100, "undertakingSigned": undertaking})
    except sqlite3.IntegrityError as exc:
        proof_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="That Official Receipt number is already attached to a request.") from exc
    return request_id


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "DOC-SECURE Document Request API"}


@app.post("/api/auth/{role}")
def authenticate(role: str, body: LoginRequest) -> dict[str, Any]:
    if role not in {"student", "cashier", "registrar"}:
        raise HTTPException(status_code=404, detail="Unknown portal role.")
    with database() as connection:
        row = connection.execute("SELECT * FROM users WHERE identifier=? AND role=?", (body.identifier, role)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="The ID or password is incorrect.")
    candidate = hashlib.scrypt(body.password.encode(), salt=row["password_salt"], n=2**14, r=8, p=1, dklen=32)
    if not hmac.compare_digest(candidate, row["password_digest"]):
        raise HTTPException(status_code=401, detail="The ID or password is incorrect.")
    if role == "cashier" and not hmac.compare_digest(hashlib.sha256((body.terminalPin or "").encode()).digest(), row["pin_digest"] or b""):
        raise HTTPException(status_code=401, detail="The terminal PIN is incorrect.")
    if role == "registrar" and not hmac.compare_digest(hashlib.sha256((body.securityToken or "").encode()).digest(), row["token_digest"] or b""):
        raise HTTPException(status_code=401, detail="The security token is incorrect.")
    return {"access_token": sign_session(row["identifier"], role), "token_type": "bearer", "expires_in": 1800, "redirect": f"{role}.html"}


@app.get("/api/session/me")
def current_session(user: dict[str, str] = Depends(session_user)) -> dict[str, str]:
    with database() as connection:
        row = connection.execute("SELECT name FROM users WHERE identifier=? AND role=?", (user["identifier"], user["role"])).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="This account is no longer active.")
    return {**user, "name": row["name"]}


@app.get("/api/students/me")
def student_profile(user: dict[str, str] = Depends(require_role("student"))) -> dict[str, Any]:
    student = get_student(user["identifier"])
    return {key: student[key] for key in ("student_id", "name", "program", "email", "enrollment_status", "balance", "units", "holds")}


@app.get("/api/students/me/document-options")
def document_options(user: dict[str, str] = Depends(require_role("student"))) -> dict[str, Any]:
    student = get_student(user["identifier"])
    return {
        "documents": list(DOCUMENTS.values()),
        "holds": student["holds"],
        "undertakingRequired": bool(student["holds"]),
        "undertakingVersion": UNDERTAKING_VERSION,
        "undertakingText": "I understand that one or more clearance requirements are still pending. I agree to resolve them and understand that this request remains subject to registrar verification before document release.",
    }


@app.get("/api/students/me/requests")
def student_requests(user: dict[str, str] = Depends(require_role("student"))) -> list[dict[str, Any]]:
    return fetch_requests("r.student_id=?", (user["identifier"],))


@app.post("/api/students/requests")
def create_request(body: CreateRequest, user: dict[str, str] = Depends(require_role("student"))) -> dict[str, Any]:
    document_ids = list(dict.fromkeys(body.documentIds))
    unknown = [item for item in document_ids if item not in DOCUMENTS]
    if unknown:
        raise HTTPException(status_code=422, detail="One or more selected documents are not available.")
    document_quantities = validated_quantities(document_ids, body.documentQuantities)
    student = get_student(user["identifier"])
    if student["holds"] and (not body.undertakingSigned or body.undertakingVersion != UNDERTAKING_VERSION):
        raise HTTPException(status_code=422, detail="Review and accept the digital undertaking before submitting.")
    if not body.orNumber.strip():
        raise HTTPException(status_code=422, detail="Enter the payment Official Receipt number.")
    filename, proof_path = decode_proof(body.proofFilename, body.proofMime, body.proofBase64)
    request_id = add_request(user["identifier"], document_ids, document_quantities, body.orNumber.strip(), body.undertakingSigned,
                             body.undertakingVersion, filename, body.proofMime, proof_path, user)
    return {"request": get_request(request_id), "message": "Request submitted for cashier payment review."}


@app.post("/api/students/requests/{request_id}/resubmit")
def resubmit_request(request_id: str, body: ResubmitRequest, user: dict[str, str] = Depends(require_role("student"))) -> dict[str, Any]:
    with database() as connection:
        row = connection.execute("SELECT * FROM document_requests WHERE id=? AND student_id=?", (request_id, user["identifier"])).fetchone()
    if not row or row["status"] != "REJECTED":
        raise HTTPException(status_code=409, detail="Only a rejected request can be resubmitted.")
    student = get_student(user["identifier"])
    if student["holds"] and (not body.undertakingSigned or body.undertakingVersion != UNDERTAKING_VERSION):
        raise HTTPException(status_code=422, detail="Review and accept the digital undertaking before resubmitting.")
    filename, proof_path = decode_proof(body.proofFilename, body.proofMime, body.proofBase64)
    previous = Path(row["proof_path"])
    ids = json.loads(row["document_ids_json"])
    quantities = json.loads(row["document_quantities_json"] or "{}")
    quantities = {document_id: int(quantities.get(document_id, 1)) for document_id in ids}
    try:
        add_request(user["identifier"], ids, quantities, body.orNumber.strip(), body.undertakingSigned,
                    body.undertakingVersion, filename, body.proofMime, proof_path, user, request_id)
    except Exception:
        raise
    previous.unlink(missing_ok=True)
    return {"request": get_request(request_id), "message": "Updated proof submitted for review."}


@app.post("/api/students/requests/{request_id}/qr")
def issue_request_qr(request_id: str, user: dict[str, str] = Depends(require_role("student"))) -> dict[str, Any]:
    with database() as connection:
        row = connection.execute("SELECT * FROM document_requests WHERE id=? AND student_id=?", (request_id, user["identifier"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document request not found.")
        if row["status"] != "APPROVED":
            raise HTTPException(status_code=409, detail="A QR code is available only after registrar approval.")
        if row["qr_used_at"]:
            raise HTTPException(status_code=409, detail="This request QR was already used at the counter.")
        issued_at = int(time.time())
        expiry = issued_at + 300
        nonce = secrets.token_urlsafe(24)
        backup_code = secrets.token_hex(8).upper()
        backup_code_hash = hashlib.sha256(backup_code.encode("ascii")).hexdigest()
        saved_quantities = json.loads(row["document_quantities_json"] or "{}")
        quantities = {document_id: int(saved_quantities.get(document_id, 1)) for document_id in json.loads(row["document_ids_json"])}
        payload = {
            "requestId": row["id"], "studentId": row["student_id"],
            "documentIds": json.loads(row["document_ids_json"]), "orNumber": row["or_number"],
            "documentQuantities": quantities,
            "undertakingSigned": bool(row["undertaking_signed"]),
            "timestamp": issued_at, "expiresAt": expiry, "nonce": nonce,
        }
        envelope = encrypt_json(payload, AES_KEY, AAD)
        connection.execute("UPDATE document_requests SET qr_nonce_hash=?, qr_expires_at=?, qr_used_at=NULL, backup_code_hash=?, backup_code_expires_at=?, backup_code_used_at=NULL, updated_at=? WHERE id=?", (hashlib.sha256(nonce.encode()).hexdigest(), expiry, backup_code_hash, expiry, now_iso(), row["id"]))
        audit(connection, user["identifier"], user["role"], "QR_ISSUED", "document_request", row["id"], {"expiresAt": expiry})
    display_code = "-".join(backup_code[index:index + 4] for index in range(0, len(backup_code), 4))
    return {"payload": envelope, "backupCode": display_code, "expiresIn": 300, "filename": "DOC-SECURE_Request_QR.png"}


@app.get("/api/cashier/payment-queue")
def cashier_queue(user: dict[str, str] = Depends(require_role("cashier"))) -> list[dict[str, Any]]:
    return fetch_requests("r.status='PENDING_PAYMENT_REVIEW'", (), include_proof=True)


@app.get("/api/cashier/students/{student_id}")
def cashier_student_lookup(student_id: str, _user: dict[str, str] = Depends(require_role("cashier"))) -> dict[str, Any]:
    student = get_student(student_id)
    return {key: student[key] for key in ("student_id", "name", "program", "email", "enrollment_status", "balance", "holds")}


@app.post("/api/cashier/requests/{request_id}/verify-payment")
def verify_payment(request_id: str, body: PaymentReview, user: dict[str, str] = Depends(require_role("cashier"))) -> dict[str, Any]:
    if not body.valid and not (body.reason and body.reason.strip()):
        raise HTTPException(status_code=422, detail="Add a reason when rejecting payment proof.")
    next_status = "PENDING_REGISTRAR_REVIEW" if body.valid else "REJECTED"
    reason = None if body.valid else body.reason.strip()
    timestamp = now_iso()
    with database() as connection:
        row = connection.execute("SELECT status FROM document_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document request not found.")
        if row["status"] != "PENDING_PAYMENT_REVIEW":
            raise HTTPException(status_code=409, detail="This request is no longer waiting for payment review.")
        connection.execute("UPDATE document_requests SET status=?, rejection_stage=?, rejection_reason=?, payment_verified_by=?, payment_verified_at=?, updated_at=? WHERE id=?",
                           (next_status, None if body.valid else "payment", reason, user["identifier"] if body.valid else None, timestamp if body.valid else None, timestamp, request_id))
        audit(connection, user["identifier"], user["role"], "PAYMENT_VERIFIED" if body.valid else "PAYMENT_REJECTED", "document_request", request_id, {"reason": reason})
    return {"request": get_request(request_id)}


@app.get("/api/registrar/requests")
def registrar_queue(user: dict[str, str] = Depends(require_role("registrar"))) -> list[dict[str, Any]]:
    return fetch_requests("r.status='PENDING_REGISTRAR_REVIEW'", (), include_proof=True)


@app.post("/api/registrar/requests/{request_id}/decision")
def registrar_decision(request_id: str, body: RegistrarDecision, user: dict[str, str] = Depends(require_role("registrar"))) -> dict[str, Any]:
    if body.decision == "reject" and not (body.reason and body.reason.strip()):
        raise HTTPException(status_code=422, detail="Provide a clear reason so the student knows what to correct.")
    timestamp = now_iso()
    status = "APPROVED" if body.decision == "approve" else "REJECTED"
    with database() as connection:
        row = connection.execute("SELECT * FROM document_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document request not found.")
        if row["status"] != "PENDING_REGISTRAR_REVIEW" or not row["payment_verified_at"]:
            raise HTTPException(status_code=409, detail="Cashier must verify the receipt before registrar review.")
        connection.execute("UPDATE document_requests SET status=?, rejection_stage=?, rejection_reason=?, reviewed_by=?, reviewed_at=?, updated_at=? WHERE id=?",
                           (status, None if status == "APPROVED" else "registrar", None if status == "APPROVED" else body.reason.strip(), user["identifier"], timestamp, timestamp, request_id))
        audit(connection, user["identifier"], user["role"], "REQUEST_APPROVED" if status == "APPROVED" else "REQUEST_REJECTED", "document_request", request_id, {"orNumber": row["or_number"], "reason": body.reason if status == "REJECTED" else None})
    return {"request": get_request(request_id)}


@app.post("/api/registrar/verify-qr")
def verify_request_qr(body: EnvelopeRequest, user: dict[str, str] = Depends(require_role("registrar"))) -> dict[str, Any]:
    try:
        payload = decrypt_json(body.envelope, AES_KEY, AAD)
    except (KeyError, ValueError, TypeError, InvalidTag) as exc:
        raise HTTPException(status_code=400, detail="QR authentication failed: the payload is invalid or was changed.") from exc
    timestamp = int(time.time())
    if int(payload.get("expiresAt", 0)) < timestamp:
        raise HTTPException(status_code=410, detail="This QR has expired. Ask the student to generate a fresh one.")
    request_id = str(payload.get("requestId", ""))
    nonce_hash = hashlib.sha256(str(payload.get("nonce", "")).encode()).hexdigest()
    with database() as connection:
        row = connection.execute("SELECT * FROM document_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="The QR does not match a document request.")
        if row["status"] != "APPROVED":
            raise HTTPException(status_code=409, detail="This request is not approved or was already claimed.")
        if row["qr_used_at"]:
            raise HTTPException(status_code=409, detail="This single-use QR was already scanned.")
        if row["qr_nonce_hash"] != nonce_hash or row["qr_expires_at"] != payload.get("expiresAt") or row["qr_expires_at"] < timestamp:
            raise HTTPException(status_code=409, detail="This QR was superseded or is no longer valid.")
        saved_quantities = json.loads(row["document_quantities_json"] or "{}")
        quantities = {document_id: int(saved_quantities.get(document_id, 1)) for document_id in json.loads(row["document_ids_json"])}
        if (row["student_id"] != payload.get("studentId") or row["or_number"] != payload.get("orNumber")
                or json.loads(row["document_ids_json"]) != payload.get("documentIds")
                or quantities != payload.get("documentQuantities", {document_id: 1 for document_id in json.loads(row["document_ids_json"])})
                or bool(row["undertaking_signed"]) != bool(payload.get("undertakingSigned"))):
            raise HTTPException(status_code=400, detail="The QR details do not match the approved request.")
        timestamp_text = now_iso()
        connection.execute("UPDATE document_requests SET qr_used_at=?, counter_verified_by=?, counter_verified_at=?, updated_at=? WHERE id=? AND qr_used_at IS NULL",
                           (timestamp_text, user["identifier"], timestamp_text, timestamp_text, request_id))
        audit(connection, user["identifier"], user["role"], "QR_VERIFIED_AT_COUNTER", "document_request", request_id, {"orNumber": row["or_number"], "nonceHash": nonce_hash})
    request = get_request(request_id)
    return {"verified": True, "request": request, "message": "QR verified. Confirm physical document handover to mark this request claimed."}


@app.post("/api/registrar/verify-backup-code")
def verify_backup_code(body: BackupCodeRequest, user: dict[str, str] = Depends(require_role("registrar"))) -> dict[str, Any]:
    normalized = body.code.replace("-", "").replace(" ", "").strip().upper()
    timestamp = int(time.time())
    error_status: int | None = None
    error_message = "The backup code is invalid, expired, or already used."
    verified_request_id: str | None = None
    with database() as connection:
        connection.execute("DELETE FROM counter_code_attempts WHERE attempted_at < ?", (timestamp - 600,))
        attempts = connection.execute(
            "SELECT COUNT(*) AS count FROM counter_code_attempts WHERE actor_id=? AND attempted_at>=?",
            (user["identifier"], timestamp - 600),
        ).fetchone()["count"]
        if attempts >= 5:
            error_status = 429
            error_message = "Too many backup-code attempts. Try again in 10 minutes."
        else:
            if len(normalized) != 16:
                connection.execute("INSERT INTO counter_code_attempts (actor_id, attempted_at) VALUES (?, ?)", (user["identifier"], timestamp))
                error_status = 400
            else:
                code_hash = hashlib.sha256(normalized.encode("ascii", errors="ignore")).hexdigest()
                row = connection.execute("SELECT * FROM document_requests WHERE backup_code_hash=?", (code_hash,)).fetchone()
                if (not row or row["status"] != "APPROVED" or row["qr_used_at"] or row["backup_code_used_at"]
                        or not row["backup_code_expires_at"] or row["backup_code_expires_at"] < timestamp):
                    connection.execute("INSERT INTO counter_code_attempts (actor_id, attempted_at) VALUES (?, ?)", (user["identifier"], timestamp))
                    error_status = 400
                else:
                    timestamp_text = now_iso()
                    updated = connection.execute(
                        "UPDATE document_requests SET backup_code_used_at=?, qr_used_at=?, counter_verified_by=?, counter_verified_at=?, updated_at=? WHERE id=? AND qr_used_at IS NULL AND backup_code_used_at IS NULL",
                        (timestamp_text, timestamp_text, user["identifier"], timestamp_text, timestamp_text, row["id"]),
                    )
                    if updated.rowcount != 1:
                        error_status = 409
                        error_message = "This QR or backup code has already been used."
                    else:
                        verified_request_id = row["id"]
                        audit(connection, user["identifier"], user["role"], "BACKUP_CODE_VERIFIED_AT_COUNTER", "document_request", row["id"], {"codeExpiresAt": row["backup_code_expires_at"]})
    if error_status:
        raise HTTPException(status_code=error_status, detail=error_message)
    request = get_request(verified_request_id)
    return {"verified": True, "request": request, "message": "Backup code verified. Confirm physical document handover to mark this request claimed."}


@app.post("/api/registrar/requests/{request_id}/claim")
def claim_request(request_id: str, user: dict[str, str] = Depends(require_role("registrar"))) -> dict[str, Any]:
    timestamp = now_iso()
    with database() as connection:
        row = connection.execute("SELECT status, counter_verified_at FROM document_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document request not found.")
        if row["status"] != "APPROVED" or not row["counter_verified_at"]:
            raise HTTPException(status_code=409, detail="Scan and verify the student's current QR before marking a handover.")
        connection.execute("UPDATE document_requests SET status='CLAIMED', claimed_by=?, claimed_at=?, updated_at=? WHERE id=?", (user["identifier"], timestamp, timestamp, request_id))
        audit(connection, user["identifier"], user["role"], "DOCUMENTS_CLAIMED", "document_request", request_id, {"claimedAt": timestamp})
    return {"request": get_request(request_id), "message": "Request marked claimed and written to the audit log."}


@app.get("/api/registrar/audit")
def audit_entries(_user: dict[str, str] = Depends(require_role("registrar"))) -> list[dict[str, Any]]:
    with database() as connection:
        rows = connection.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100").fetchall()
    return [{"id": row["id"], "actorId": row["actor_id"], "actorRole": row["actor_role"], "action": row["action"], "targetType": row["target_type"], "targetId": row["target_id"], "details": json.loads(row["details_json"]), "createdAt": row["created_at"]} for row in rows]
