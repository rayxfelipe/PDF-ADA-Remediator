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

from pdf_accessibility_audit import audit_pdf, write_html
from pdf_accessibility_remediator import remediate_pdf, write_remediation_html
from pdf_accessibility_ui import APP_STYLES, app_footer, app_header

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
    max_megabytes = MAX_UPLOAD_BYTES // (1024 * 1024)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PDF Accessibility Checker and Remediator</title><style>{APP_STYLES}</style></head>
<body>{app_header("PDF Accessibility Checker and Remediator", "Deterministic PDF audits and safe accessibility remediation")}
<main id="main-content" class="container">
<section class="upload-card" aria-labelledby="upload-heading">
<h2 id="upload-heading">Upload a PDF document</h2>
<p class="hint">Screen a PDF against the supported accessibility requirements, review the findings, and apply safe automatic remediation. Maximum size: {max_megabytes} MB.</p>
<form id="upload" novalidate>
<div id="dropzone" class="dropzone" tabindex="0" role="button" aria-describedby="dropzone-hint">
<input id="pdf" name="pdf" type="file" accept="application/pdf,.pdf" aria-label="Choose a PDF file to audit">
<p id="dropzone-hint">Drag &amp; drop a PDF here, or <span class="link-text">browse files</span></p>
<p id="file-name" class="file-name" aria-live="polite"></p>
</div>
<button id="submit" type="submit" disabled>Run Accessibility Audit</button>
<p id="error" class="error-message" role="alert" hidden></p>
</form></section>
<section id="status" class="status-card" hidden role="status" aria-live="polite" aria-atomic="true">
<div class="spinner" aria-hidden="true"></div><div><strong>Auditing document...</strong><p>The findings will appear when the deterministic audit is complete.</p></div>
</section></main>{app_footer()}
<script>
const form=document.getElementById('upload'),dropzone=document.getElementById('dropzone'),input=document.getElementById('pdf'),button=document.getElementById('submit'),fileName=document.getElementById('file-name'),status=document.getElementById('status'),error=document.getElementById('error');
let selectedFile=null;
function showError(message){{error.textContent=message;error.hidden=false;}}
function selectFile(file){{
  if(!file)return;
  if(file.type!=='application/pdf'&&!file.name.toLowerCase().endsWith('.pdf')){{showError('Only PDF files are supported.');return;}}
  if(file.size>{MAX_UPLOAD_BYTES}){{showError('File exceeds the {max_megabytes} MB size limit.');return;}}
  error.hidden=true;selectedFile=file;fileName.textContent='Selected: '+file.name;button.disabled=false;
}}
input.addEventListener('change',event=>selectFile(event.target.files[0]));
dropzone.addEventListener('keydown',event=>{{if(event.key==='Enter'||event.key===' '){{event.preventDefault();input.click();}}}});
['dragenter','dragover'].forEach(name=>dropzone.addEventListener(name,event=>{{event.preventDefault();dropzone.classList.add('dragover');}}));
['dragleave','drop'].forEach(name=>dropzone.addEventListener(name,event=>{{event.preventDefault();dropzone.classList.remove('dragover');}}));
dropzone.addEventListener('drop',event=>selectFile(event.dataTransfer.files[0]));
form.addEventListener('submit',async event=>{{
  event.preventDefault();if(!selectedFile)return;button.disabled=true;status.hidden=false;error.hidden=true;
  try{{
    const response=await fetch({action_url!r},{{method:'POST',headers:{{'Content-Type':'application/pdf','X-PDF-Filename':encodeURIComponent(selectedFile.name)}},body:selectedFile}});
    const body=await response.text();if(!response.ok)throw new Error(body);document.open();document.write(body);document.close();
  }}catch(reason){{showError('Evaluation failed: '+reason.message);status.hidden=true;button.disabled=false;}}
}});
</script></body></html>"""
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
        source.write_bytes(body)
        report = audit_pdf(source)
        remediation_url = _route_url(req, "remediate", job=job_id)
        write_html(report, report_file, remediation_url, token)
        result = report_file.read_text(encoding="utf-8")
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
        filename = _safe_filename(metadata.get("filename", "document.pdf"))

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / filename
            remediated = source.with_name(f"{source.stem}_remediated.pdf")
            result_file = Path(directory) / "remediation-report.html"
            source.write_bytes(source_bytes)
            report = remediate_pdf(source, remediated)
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
