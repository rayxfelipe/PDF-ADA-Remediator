from __future__ import annotations

import hashlib
import html
import os
import secrets
import tempfile
import uuid
from pathlib import Path
from urllib.parse import parse_qs, quote

import azure.functions as func

from pdf_accessibility_audit import audit_pdf, write_html, write_json
from pdf_accessibility_remediator import remediate_from_json, write_remediation_html

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

MAX_UPLOAD_BYTES = int(os.getenv("PDF_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
CONTAINER_NAME = os.getenv("PDF_CONTAINER_NAME", "pdf-jobs")


def _blob_service():
    from azure.storage.blob import BlobServiceClient

    connection_string = os.getenv("AzureWebJobsStorage", "")
    if "DefaultEndpointsProtocol=" in connection_string:
        return BlobServiceClient.from_connection_string(connection_string)

    account_url = os.getenv("PDF_STORAGE_ACCOUNT_URL")
    if not account_url:
        account_name = os.getenv("AzureWebJobsStorage__accountName")
        if account_name:
            account_url = f"https://{account_name}.blob.core.windows.net"
    if not account_url:
        raise RuntimeError("Set PDF_STORAGE_ACCOUNT_URL or AzureWebJobsStorage__accountName.")
    from azure.identity import DefaultAzureCredential

    return BlobServiceClient(account_url, credential=DefaultAzureCredential())


def _container_client():
    container = _blob_service().get_container_client(CONTAINER_NAME)
    try:
        container.create_container()
    except Exception as exc:
        if getattr(exc, "status_code", None) != 409:
            raise
    return container


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    if not name.lower().endswith(".pdf"):
        raise ValueError("Only PDF files are accepted.")
    clean = "".join(character for character in name if character.isalnum() or character in " ._-").strip()
    return clean[:180] or "document.pdf"


def _job_blob(job_id: str, suffix: str) -> str:
    try:
        normalized = str(uuid.UUID(job_id))
    except ValueError as exc:
        raise ValueError("Invalid job identifier.") from exc
    return f"{normalized}/{suffix}"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_token(job_id: str, token: str) -> dict[str, str]:
    if not token:
        raise PermissionError("Missing job token.")
    blob = _container_client().get_blob_client(_job_blob(job_id, "source.pdf"))
    metadata = blob.get_blob_properties().metadata
    expected = metadata.get("token_hash", "")
    if not expected or not secrets.compare_digest(expected, _token_hash(token)):
        raise PermissionError("Invalid job token.")
    return metadata


def _function_code(req: func.HttpRequest) -> str:
    return req.params.get("code", "")


def _route_url(req: func.HttpRequest, action: str, **params: str) -> str:
    base = req.url.split("?", 1)[0].rstrip("/")
    current_action = req.route_params.get("action")
    if current_action:
        base = base[: -(len(current_action) + 1)]
    query = {key: value for key, value in params.items() if value}
    code = _function_code(req)
    if code:
        query["code"] = code
    query_string = "&".join(f"{quote(key)}={quote(value)}" for key, value in query.items())
    target = f"{base}/{action}" if action else base
    return target + (f"?{query_string}" if query_string else "")


def _upload_page(req: func.HttpRequest) -> func.HttpResponse:
    action_url = _route_url(req, "", code=_function_code(req))
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PDF Accessibility Audit</title><style>:root{{--ink:#172033;--muted:#596579;--paper:#fff;--canvas:#f3f6fa;--blue:#1456a0;--border:#d7dee8}}*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{width:min(760px,calc(100% - 2rem));margin:4rem auto}}section{{background:#fff;border:1px solid var(--border);border-top:6px solid var(--blue);border-radius:12px;padding:2rem;box-shadow:0 3px 14px #1720330d}}h1{{line-height:1.15}}p{{color:var(--muted)}}label{{display:block;font-weight:750;margin:1.5rem 0 .4rem}}input[type=file]{{width:100%;padding:1rem;border:2px dashed var(--border);border-radius:8px;background:#f8fafc}}button{{margin-top:1.3rem;padding:.8rem 1.2rem;border:0;border-radius:8px;background:var(--blue);color:#fff;font:inherit;font-weight:750;cursor:pointer}}button:disabled{{opacity:.55;cursor:wait}}button:focus-visible,input:focus-visible{{outline:3px solid #f5b942;outline-offset:3px}}#status{{min-height:1.5rem}}</style></head>
<body><main><section><h1>PDF Accessibility Audit</h1><p>Upload a PDF to screen it against the requirements derived from ADA Title II Web Accessibility.docx. Maximum size: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.</p>
<form id="upload"><label for="pdf">PDF file</label><input id="pdf" name="pdf" type="file" accept="application/pdf,.pdf" required><button id="submit" type="submit">Evaluate PDF</button><p id="status" role="status" aria-live="polite"></p></form></section></main>
<script>const form=document.getElementById('upload'),button=document.getElementById('submit'),status=document.getElementById('status');form.addEventListener('submit',async(e)=>{{e.preventDefault();const file=document.getElementById('pdf').files[0];if(!file)return;button.disabled=true;status.textContent='Uploading and evaluating…';try{{const response=await fetch({action_url!r},{{method:'POST',headers:{{'Content-Type':'application/pdf','X-PDF-Filename':encodeURIComponent(file.name)}},body:file}});const body=await response.text();if(!response.ok)throw new Error(body);document.open();document.write(body);document.close();}}catch(error){{status.textContent='Evaluation failed: '+error.message;button.disabled=false;}}}});</script></body></html>"""
    return func.HttpResponse(page, mimetype="text/html", status_code=200)


def _audit_upload(req: func.HttpRequest) -> func.HttpResponse:
    from azure.storage.blob import ContentSettings

    body = req.get_body()
    if not body:
        return func.HttpResponse("A PDF request body is required.", status_code=400)
    if len(body) > MAX_UPLOAD_BYTES:
        return func.HttpResponse(f"PDF exceeds the {MAX_UPLOAD_BYTES}-byte limit.", status_code=413)
    if not body.startswith(b"%PDF-"):
        return func.HttpResponse("The uploaded content is not a valid PDF signature.", status_code=400)

    try:
        encoded_name = req.headers.get("X-PDF-Filename", "document.pdf")
        from urllib.parse import unquote
        filename = _safe_filename(unquote(encoded_name))
    except ValueError as exc:
        return func.HttpResponse(str(exc), status_code=400)

    job_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    source_blob = _container_client().get_blob_client(_job_blob(job_id, "source.pdf"))
    source_blob.upload_blob(
        body,
        overwrite=False,
        metadata={"filename": filename, "token_hash": _token_hash(token)},
        content_settings=ContentSettings(content_type="application/pdf"),
    )

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / filename
        report_file = Path(directory) / "report.html"
        audit_json_file = Path(directory) / "audit.json"
        source.write_bytes(body)
        report = audit_pdf(source)
        write_json(report, audit_json_file)
        remediation_url = _route_url(req, "remediate", job=job_id)
        write_html(report, report_file, remediation_url, token)
        result = report_file.read_text(encoding="utf-8")
        audit_json = audit_json_file.read_bytes()

    audit_blob = _container_client().get_blob_client(_job_blob(job_id, "audit.json"))
    audit_blob.upload_blob(
        audit_json,
        overwrite=False,
        content_settings=ContentSettings(content_type="application/json"),
    )
    return func.HttpResponse(result, mimetype="text/html", status_code=200)


def _remediate(req: func.HttpRequest) -> func.HttpResponse:
    from azure.storage.blob import ContentSettings

    form = parse_qs(req.get_body().decode("utf-8", errors="replace"))
    token = form.get("token", [""])[0]
    job_id = req.params.get("job", "")
    try:
        metadata = _validate_token(job_id, token)
        source_blob = _container_client().get_blob_client(_job_blob(job_id, "source.pdf"))
        source_bytes = source_blob.download_blob().readall()
        audit_blob = _container_client().get_blob_client(_job_blob(job_id, "audit.json"))
        audit_json_bytes = audit_blob.download_blob().readall()
        filename = _safe_filename(metadata.get("filename", "document.pdf"))

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / filename
            audit_json_file = Path(directory) / "audit.json"
            remediated = source.with_name(f"{source.stem}_remediated.pdf")
            result_file = Path(directory) / "remediation-report.html"
            source.write_bytes(source_bytes)
            audit_json_file.write_bytes(audit_json_bytes)
            report = remediate_from_json(audit_json_file, remediated, source_pdf=source)
            remediated_bytes = remediated.read_bytes()
            download_url = _route_url(req, "download", job=job_id, token=token)
            write_remediation_html(report, result_file, download_url)
            result_html = result_file.read_text(encoding="utf-8")

        output_blob = _container_client().get_blob_client(_job_blob(job_id, "remediated.pdf"))
        output_blob.upload_blob(
            remediated_bytes,
            overwrite=True,
            metadata={"filename": remediated.name},
            content_settings=ContentSettings(content_type="application/pdf"),
        )
        return func.HttpResponse(result_html, mimetype="text/html", status_code=200)
    except PermissionError as exc:
        return func.HttpResponse(str(exc), status_code=403)
    except ValueError as exc:
        return func.HttpResponse(str(exc), status_code=400)


def _download(req: func.HttpRequest) -> func.HttpResponse:
    job_id = req.params.get("job", "")
    token = req.params.get("token", "")
    try:
        _validate_token(job_id, token)
        blob = _container_client().get_blob_client(_job_blob(job_id, "remediated.pdf"))
        properties = blob.get_blob_properties()
        data = blob.download_blob().readall()
        filename = properties.metadata.get("filename", "remediated.pdf")
        return func.HttpResponse(
            data,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
        )
    except PermissionError as exc:
        return func.HttpResponse(str(exc), status_code=403)
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            return func.HttpResponse("The remediated PDF is not available.", status_code=404)
        raise


@app.function_name(name="pdf_accessibility")
@app.route(route="pdf-accessibility/{action?}", methods=["GET", "POST"])
def pdf_accessibility(req: func.HttpRequest) -> func.HttpResponse:
    action = (req.route_params.get("action") or "").lower()
    try:
        if req.method == "GET" and not action:
            return _upload_page(req)
        if req.method == "POST" and not action:
            return _audit_upload(req)
        if req.method == "POST" and action == "remediate":
            return _remediate(req)
        if req.method == "GET" and action == "download":
            return _download(req)
        return func.HttpResponse("Not found.", status_code=404)
    except Exception as exc:
        return func.HttpResponse(
            f"PDF processing failed: {html.escape(str(exc))}",
            status_code=500,
            mimetype="text/plain",
        )
