from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pypdf

from pdf_accessibility_audit import AUDIT_SCHEMA_VERSION, CHECKER_VERSION, RULESET_VERSION, audit_pdf
from pdf_accessibility_remediator import remediate_pdf

APPLICATION_FILES = (
    "corpus_regression.py",
    "pdf_accessibility_audit.py",
    "pdf_accessibility_policy.py",
    "pdf_accessibility_remediator.py",
    "pdf_accessibility_ui.py",
    "pdf_accessibility_workflow.py",
    "function_app.py",
    "requirements.txt",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_dirty() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _application_sha256() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in APPLICATION_FILES:
        digest.update(name.encode("utf-8"))
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def _manifest_files(input_dir: Path, manifest: Path | None) -> list[Path]:
    if manifest is None:
        return sorted(path for path in input_dir.rglob("*") if path.suffix.lower() == ".pdf")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Corpus manifest must be a JSON list.")
    values: list[Any] = []
    for item in data:
        if isinstance(item, dict):
            values.append(item["file"])
        elif isinstance(item, list) and item:
            values.append(item[0])
        else:
            values.append(item)
    paths = [(input_dir / str(value)).resolve() for value in values]
    root = input_dir.resolve()
    if any(root not in path.parents for path in paths):
        raise ValueError("Corpus manifest paths must remain inside the input directory.")
    return paths


def run_corpus(
    input_dir: str | Path,
    output_dir: str | Path,
    manifest: str | Path | None = None,
) -> dict[str, Any]:
    source_root = Path(input_dir).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    manifest_path = Path(manifest).expanduser().resolve() if manifest else None
    files = _manifest_files(source_root, manifest_path)
    if not files:
        raise ValueError(f"No PDF files found in {source_root}.")
    destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    criteria: set[str] = set()

    for source in files:
        relative = source.relative_to(source_root).as_posix()
        row: dict[str, Any] = {
            "file": relative,
            "source_sha256": _sha256(source),
        }
        try:
            first_audit = audit_pdf(source)
            second_audit = audit_pdf(source)
            with tempfile.TemporaryDirectory() as folder:
                first_output = Path(folder) / "first.pdf"
                second_output = Path(folder) / "second.pdf"
                first = remediate_pdf(source, first_output)
                second = remediate_pdf(source, second_output)
                row.update({
                    "pages": first_audit.page_count,
                    "audit_repeatable": first_audit.findings == second_audit.findings
                    and first_audit.wcag_results == second_audit.wcag_results,
                    "output_sha_equal": first.output_sha256 == second.output_sha256,
                    "output_sha_matches_file": first.output_sha256 == _sha256(first_output)
                    and second.output_sha256 == _sha256(second_output),
                    "source_sha_matches_file": first.source_sha256 == row["source_sha256"]
                    and second.source_sha256 == row["source_sha256"],
                    "matrix_repeatable": [asdict(item) for item in first.wcag_results]
                    == [asdict(item) for item in second.wcag_results],
                    "before_score": first.before_score,
                    "after_score": first.after_score,
                    "determination": first.wcag_determination,
                    "actions": [item.action_id for item in first.actions],
                    "statuses": {
                        item.criterion: item.after_status
                        for item in first.wcag_results
                    },
                })
                criteria.update(row["statuses"])
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        report_path = destination / f"{relative.replace('/', '__')}.json"
        report_path.write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")

    criteria_order = sorted(criteria, key=lambda value: tuple(int(part) for part in value.split(".")))
    csv_path = destination / "corpus-summary.csv"
    columns = [
        "file", "source_sha256", "pages", "before_score", "after_score",
        "determination", "actions", "audit_repeatable", "output_sha_equal",
        "output_sha_matches_file", "source_sha_matches_file", "matrix_repeatable",
        "error",
    ] + criteria_order
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            flattened = {
                **row,
                "actions": "|".join(row.get("actions", [])),
                **row.get("statuses", {}),
            }
            flattened.pop("statuses", None)
            writer.writerow({key: flattened.get(key, "") for key in columns})

    successful = [row for row in rows if "error" not in row]
    metadata = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "git_worktree_dirty": _git_dirty(),
        "application_sha256": _application_sha256(),
        "python_version": platform.python_version(),
        "pypdf_version": pypdf.__version__,
        "langdetect_version": importlib.metadata.version("langdetect"),
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "checker_version": CHECKER_VERSION,
        "ruleset_version": RULESET_VERSION,
        "input_directory": str(source_root),
        "manifest": str(manifest_path) if manifest_path else None,
        "file_count": len(rows),
        "error_count": len(rows) - len(successful),
        "checks": {
            key: f"{sum(bool(row.get(key)) for row in successful)}/{len(successful)}"
            for key in (
                "audit_repeatable",
                "output_sha_equal",
                "output_sha_matches_file",
                "source_sha_matches_file",
                "matrix_repeatable",
            )
        },
        "actions": dict(Counter(action for row in successful for action in row["actions"])),
        "rows": rows,
    }
    (destination / "corpus-summary.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return metadata


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic PDF accessibility corpus regression checks.")
    parser.add_argument("--input-dir", required=True, help="Directory containing source PDFs")
    parser.add_argument("--out", default="reports/corpus", help="Output directory for JSON and CSV reports")
    parser.add_argument("--manifest", help="Optional JSON list or list of objects containing a file property")
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_corpus(args.input_dir, args.out, args.manifest)
    print(json.dumps({
        key: result[key]
        for key in (
            "git_commit",
            "git_worktree_dirty",
            "application_sha256",
            "file_count",
            "error_count",
            "checks",
            "actions",
        )
    }, indent=2))
    return 1 if result["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
