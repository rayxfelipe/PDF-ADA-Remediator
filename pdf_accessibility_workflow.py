from __future__ import annotations

import argparse
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from pdf_accessibility_audit import AUDIT_REPORTS_DIR, REMEDIATION_REPORTS_DIR, AuditReport, audit_pdf, write_html, write_json
from pdf_accessibility_remediator import RemediationReport, remediate_from_json, write_remediation_html


def prepare_audit(
    pdf_path: str | Path,
    audit_json_path: str | Path,
    audit_html_path: str | Path,
    remediation_url: str = "/remediate",
    csrf_token: str = "",
) -> AuditReport:
    """Create the audit reports without modifying the source PDF."""
    audit_report = audit_pdf(pdf_path)
    write_json(audit_report, audit_json_path)
    write_html(audit_report, audit_html_path, remediation_url, csrf_token)
    return audit_report


def apply_remediation(
    audit_json_path: str | Path,
    remediated_pdf_path: str | Path,
    remediation_html_path: str | Path,
    default_language: str = "en-US",
    download_url: str | None = None,
) -> RemediationReport:
    """Run remediation only after an explicit caller action."""
    report = remediate_from_json(audit_json_path, remediated_pdf_path, default_language)
    write_remediation_html(report, remediation_html_path, download_url)
    return report


def serve_workflow(
    source_pdf: Path,
    audit_json_path: Path,
    audit_html_path: Path,
    remediated_pdf_path: Path,
    remediation_html_path: Path,
    default_language: str,
    open_browser: bool,
) -> AuditReport:
    """Serve the audit first and remediate only when its button is clicked."""
    token = secrets.token_urlsafe(32)
    state: dict[str, RemediationReport | None] = {"remediation": None}
    audit_report = prepare_audit(source_pdf, audit_json_path, audit_html_path, "/remediate", token)

    class WorkflowHandler(BaseHTTPRequestHandler):
        def _send_file(self, file_path: Path, content_type: str, attachment: bool = False) -> None:
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            try:
                if route in {"/", "/report.html"}:
                    self._send_file(audit_html_path, "text/html; charset=utf-8")
                elif route == "/remediation-report" and state["remediation"] is not None:
                    self._send_file(remediation_html_path, "text/html; charset=utf-8")
                elif route == "/remediated.pdf" and state["remediation"] is not None:
                    self._send_file(remediated_pdf_path, "application/pdf", attachment=True)
                else:
                    self.send_error(404)
            except OSError as exc:
                self.send_error(500, str(exc))

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/remediate":
                self.send_error(404)
                return
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
            submitted = form.get("token", [""])[0]
            if not secrets.compare_digest(submitted, token):
                self.send_error(403, "Invalid remediation request")
                return
            try:
                state["remediation"] = apply_remediation(
                    audit_json_path,
                    remediated_pdf_path,
                    remediation_html_path,
                    default_language,
                    "/remediated.pdf",
                )
            except Exception as exc:
                self.send_error(500, f"Remediation failed: {exc}")
                return
            self.send_response(303)
            self.send_header("Location", "/remediation-report")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            print(f"Workflow server: {format % args}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), WorkflowHandler)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Audit score: {audit_report.score}/100")
    print(f"Audit report: {url}")
    print("The PDF will not be remediated until the remediation button is clicked.")
    print("Keep this terminal running while using the report. Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWorkflow server stopped.")
    finally:
        server.server_close()
    return audit_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Display a PDF audit and remediate only after confirmation.")
    parser.add_argument("pdf", help="Path to the PDF to audit")
    parser.add_argument("--audit-json", help="Audit JSON output path; defaults under reports/audits")
    parser.add_argument("--audit-report", default=str(AUDIT_REPORTS_DIR / "accessibility-report.html"), help="Audit HTML output path")
    parser.add_argument("--remediated-output", help="Remediated PDF output path; defaults under reports/remediated")
    parser.add_argument("--remediation-report", default=str(REMEDIATION_REPORTS_DIR / "accessibility-report-remediation.html"), help="Remediation HTML output path")
    parser.add_argument("--language", default="en-US", help="Default language used when the audit reports none")
    parser.add_argument("--no-open", action="store_true", help="Do not open the audit report in a browser")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    source = Path(args.pdf).expanduser().resolve()
    remediated_output = (
        Path(args.remediated_output).expanduser().resolve()
        if args.remediated_output
        else (REMEDIATION_REPORTS_DIR / f"{source.stem}_remediated.pdf").resolve()
    )
    audit_json = Path(args.audit_json or AUDIT_REPORTS_DIR / f"accessibility-report-{source.stem}.json").expanduser().resolve()
    audit_html = Path(args.audit_report).expanduser().resolve()
    remediation_html = Path(args.remediation_report).expanduser().resolve()
    try:
        serve_workflow(
            source,
            audit_json,
            audit_html,
            remediated_output,
            remediation_html,
            args.language,
            not args.no_open,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unable to complete PDF workflow: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
