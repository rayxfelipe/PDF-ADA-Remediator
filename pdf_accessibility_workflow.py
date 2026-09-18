from __future__ import annotations

import argparse
import os
import secrets
import sys
import tempfile
import webbrowser
from http.cookies import SimpleCookie
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import parse_qs, urlparse

from pdf_accessibility_audit import REMEDIATION_REPORTS_DIR, AuditReport, audit_pdf, read_json, write_html, write_json
from pdf_accessibility_remediator import RemediationReport, remediate_from_json, write_remediation_html

MAX_REMEDIATION_JSON_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES = 64 * 1024

UPLOAD_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PDF Accessibility Workflow</title>
<style>
:root { color-scheme: light; font-family: Georgia, "Times New Roman", serif; color: #16211b; background: #edf1ec; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; background: linear-gradient(135deg, #edf1ec 0 55%, #dce7df 55%); }
main { width: min(620px, 100%); padding: 40px; border-top: 6px solid #176b4d; background: #fff; box-shadow: 0 18px 50px rgba(22, 33, 27, .14); }
h1 { margin: 0 0 12px; font-size: clamp(2rem, 8vw, 3.5rem); line-height: 1; }
p { margin: 0 0 28px; color: #48574f; line-height: 1.6; }
label { display: block; margin-bottom: 8px; font-weight: 700; }
input[type=file] { width: 100%; padding: 16px; border: 1px solid #9aaba1; background: #f8faf8; }
button { margin-top: 20px; padding: 13px 20px; border: 0; background: #176b4d; color: #fff; font: 700 1rem Georgia, serif; cursor: pointer; }
button:hover { background: #0f523a; }
</style>
</head>
<body><main>
<h1>PDF accessibility check</h1>
<p>Upload a PDF to audit it. The original is processed temporarily and is not retained. Only a remediated PDF is saved.</p>
<form method="post" action="/upload-pdf" enctype="multipart/form-data">
<label for="pdf">PDF file</label>
<input id="pdf" name="pdf" type="file" accept="application/pdf,.pdf" required>
<button type="submit">Check PDF</button>
</form>
</main></body></html>"""


def _safe_upload_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].lstrip(".")


def _parse_pdf_upload(content_type: str, body: bytes) -> tuple[str, bytes]:
    if not content_type.lower().startswith("multipart/form-data;"):
        raise ValueError("Upload must use multipart/form-data.")
    message = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + body
    )
    filename = ""
    payload = b""
    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") == "pdf":
            filename = _safe_upload_name(part.get_filename() or "")
            payload = part.get_payload(decode=True) or b""
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Select a PDF file.")
    if not payload:
        raise ValueError("The uploaded PDF is empty.")
    if len(payload) > MAX_PDF_BYTES:
        raise ValueError(f"The uploaded PDF exceeds the {MAX_PDF_BYTES}-byte limit.")
    if not payload.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF.")
    return filename, payload


def prepare_audit(
    pdf_path: str | Path,
    audit_json_path: str | Path,
    audit_html_path: str | Path,
    remediation_url: str = "/remediate",
    csrf_token: str = "",
    upload_url: str | None = None,
    home_url: str | None = None,
) -> AuditReport:
    """Create the audit reports without modifying the source PDF."""
    audit_report = audit_pdf(pdf_path)
    write_json(audit_report, audit_json_path)
    write_html(audit_report, audit_html_path, remediation_url, csrf_token, upload_url, home_url)
    return audit_report


def apply_remediation(
    audit_json_path: str | Path,
    remediated_pdf_path: str | Path,
    remediation_html_path: str | Path,
    default_language: str = "en-US",
    download_url: str | None = None,
    source_pdf: str | Path | None = None,
    home_url: str | None = None,
) -> RemediationReport:
    """Run remediation only after an explicit caller action."""
    report = remediate_from_json(audit_json_path, remediated_pdf_path, default_language, source_pdf)
    write_remediation_html(report, remediation_html_path, download_url, home_url)
    return report


def _parse_remediation_upload(content_type: str, body: bytes) -> tuple[str, str, bytes]:
    if not content_type.lower().startswith("multipart/form-data;"):
        raise ValueError("Upload must use multipart/form-data.")
    message = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + body
    )
    token = ""
    filename = ""
    payload = b""
    for part in message.iter_parts():
        field_name = part.get_param("name", header="content-disposition")
        if field_name == "token":
            token = part.get_content().strip()
        elif field_name == "remediation_json":
            filename = _safe_upload_name(part.get_filename() or "")
            payload = part.get_payload(decode=True) or b""
    if not filename.lower().endswith(".json"):
        raise ValueError("Select a JSON remediation report.")
    if not payload:
        raise ValueError("The uploaded JSON report is empty.")
    return token, filename, payload


def serve_workflow(remediated_pdf_path: Path | None, default_language: str, open_browser: bool) -> None:
    """Accept a browser upload and retain only its remediated output."""
    host = os.getenv("WORKFLOW_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "0"))
    secure_cookie = bool(os.getenv("WEBSITE_HOSTNAME"))
    session_states: dict[str, dict[str, Any]] = {}
    sessions_lock = RLock()

    def new_state() -> dict[str, Any]:
        return {
            "token": secrets.token_urlsafe(32),
            "source_name": None,
            "source_bytes": None,
            "audit_json": None,
            "audit_html": None,
            "remediation": None,
            "remediation_html": None,
            "remediated_path": None,
        }

    class WorkflowHandler(BaseHTTPRequestHandler):
        session_id = ""
        session_cookie = ""

        def _state(self) -> dict[str, Any]:
            if self.session_id:
                return session_states[self.session_id]
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            candidate = cookie.get("pdf_workflow")
            requested_id = candidate.value if candidate else ""
            with sessions_lock:
                if requested_id in session_states:
                    self.session_id = requested_id
                else:
                    self.session_id = secrets.token_hex(24)
                    session_states[self.session_id] = new_state()
                    attributes = [f"pdf_workflow={self.session_id}", "Path=/", "HttpOnly", "SameSite=Lax"]
                    if secure_cookie:
                        attributes.append("Secure")
                    self.session_cookie = "; ".join(attributes)
                return session_states[self.session_id]

        def end_headers(self) -> None:
            if self.session_cookie:
                self.send_header("Set-Cookie", self.session_cookie)
            super().end_headers()

        def _send_bytes(self, data: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _audit_upload(self, content_type: str, body: bytes) -> None:
            state = self._state()
            filename, pdf_bytes = _parse_pdf_upload(content_type, body)
            with tempfile.TemporaryDirectory() as directory:
                work_dir = Path(directory)
                source = work_dir / filename
                audit_json = work_dir / "audit.json"
                audit_html = work_dir / "audit.html"
                source.write_bytes(pdf_bytes)
                report = prepare_audit(source, audit_json, audit_html, "/remediate", state["token"], "/upload-remediation", "/new")
                state.update(
                    source_name=filename,
                    source_bytes=pdf_bytes,
                    audit_json=audit_json.read_bytes(),
                    audit_html=audit_html.read_bytes(),
                    remediation=None,
                    remediation_html=None,
                    remediated_path=None,
                )
            print(f"Audit score for {filename}: {report.score}/100")

        def _apply_selected_report(self, report_bytes: bytes) -> None:
            state = self._state()
            source_name = state["source_name"]
            source_bytes = state["source_bytes"]
            if not source_name or not source_bytes:
                raise ValueError("Upload a PDF before requesting remediation.")
            output = remediated_pdf_path or (
                REMEDIATION_REPORTS_DIR / f"{Path(source_name).stem}-{self.session_id[:8]}_remediated.pdf"
            ).resolve()
            with tempfile.TemporaryDirectory() as directory:
                work_dir = Path(directory)
                source = work_dir / source_name
                audit_json = work_dir / "audit.json"
                remediation_html = work_dir / "remediation.html"
                source.write_bytes(source_bytes)
                audit_json.write_bytes(report_bytes)
                read_json(audit_json)
                report = apply_remediation(
                    audit_json,
                    output,
                    remediation_html,
                    default_language,
                    "/remediated.pdf",
                    source,
                    "/new",
                )
                state["remediation_html"] = remediation_html.read_bytes()
            state["remediation"] = report
            state["remediated_path"] = output

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            try:
                if route == "/health":
                    self._send_bytes(b'{"status":"ok"}', "application/json; charset=utf-8")
                    return
                state = self._state()
                if route in {"/", "/report.html"}:
                    self._send_bytes(state["audit_html"] or UPLOAD_PAGE.encode("utf-8"), "text/html; charset=utf-8")
                elif route == "/new":
                    state.update(
                        source_name=None,
                        source_bytes=None,
                        audit_json=None,
                        audit_html=None,
                        remediation=None,
                        remediation_html=None,
                        remediated_path=None,
                    )
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.end_headers()
                elif route == "/remediation-report" and state["remediation"] is not None:
                    self._send_bytes(state["remediation_html"], "text/html; charset=utf-8")
                elif route == "/remediated.pdf" and state["remediation"] is not None:
                    output = state["remediated_path"]
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f'attachment; filename="{output.name}"')
                    data = output.read_bytes()
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404)
            except OSError as exc:
                self.send_error(500, str(exc))

        def do_POST(self) -> None:
            route = urlparse(self.path).path
            if route not in {"/upload-pdf", "/remediate", "/upload-remediation"}:
                self.send_error(404)
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400, "Invalid content length")
                return
            maximum = MAX_PDF_BYTES if route == "/upload-pdf" else MAX_REMEDIATION_JSON_BYTES
            if content_length <= 0 or content_length > maximum + MULTIPART_OVERHEAD_BYTES:
                self.send_error(413, "Upload is too large")
                return

            body = self.rfile.read(content_length)
            try:
                state = self._state()
                if route == "/upload-pdf":
                    self._audit_upload(self.headers.get("Content-Type", ""), body)
                    self.send_response(303)
                    self.send_header("Location", "/report.html")
                    self.end_headers()
                    return
                if state["audit_json"] is None:
                    raise ValueError("Upload a PDF before requesting remediation.")
                selected_report = state["audit_json"]
                if route == "/upload-remediation":
                    submitted, filename, payload = _parse_remediation_upload(self.headers.get("Content-Type", ""), body)
                    if not secrets.compare_digest(submitted, state["token"]):
                        self.send_error(403, "Invalid remediation request")
                        return
                    selected_report = payload
                else:
                    form = parse_qs(body.decode("utf-8", errors="replace"))
                    submitted = form.get("token", [""])[0]
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            if not secrets.compare_digest(submitted, state["token"]):
                self.send_error(403, "Invalid remediation request")
                return
            try:
                self._apply_selected_report(selected_report)
            except Exception as exc:
                self.send_error(500, f"Remediation failed: {exc}")
                return
            self.send_response(303)
            self.send_header("Location", "/remediation-report")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            print(f"Workflow server: {format % args}")

    server = ThreadingHTTPServer((host, port), WorkflowHandler)
    browser_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{browser_host}:{server.server_port}/"
    print(f"PDF upload: {url}")
    print("The uploaded PDF is not retained. Only a remediated PDF is saved.")
    print("Keep this terminal running while using the report. Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWorkflow server stopped.")
    finally:
        server.server_close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open a browser to upload, audit, and remediate a PDF.")
    parser.add_argument("--remediated-output", help="Remediated PDF output path; defaults under reports/remediated")
    parser.add_argument("--language", default="en-US", help="Default language used when the audit reports none")
    parser.add_argument("--no-open", action="store_true", help="Do not open the upload page in a browser")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    remediated_output = (
        Path(args.remediated_output).expanduser().resolve()
        if args.remediated_output
        else None
    )
    try:
        serve_workflow(remediated_output, args.language, not args.no_open)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unable to complete PDF workflow: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
