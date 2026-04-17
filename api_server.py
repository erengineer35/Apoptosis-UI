from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BASE_DIR / "process_images.py"
MODEL_PATH = BASE_DIR / "best_model.pth"
JOBS_DIR = BASE_DIR / "api_jobs"
FRONTEND_DIR = BASE_DIR / "frontend"

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
MAX_UPLOAD_BYTES = int(os.environ.get("APOPTOSIS_MAX_UPLOAD_MB", "50")) * 1024 * 1024
API_ACCESS_KEY = os.environ.get("APOPTOSIS_API_KEY", "").strip()
PROCESS_TIMEOUT_SECONDS = int(os.environ.get("APOPTOSIS_PROCESS_TIMEOUT", "1800"))

OUTPUT_FILES = [
    "original.png",
    "prediction_result_predict.png",
    "overlay_predict.png",
    "cell_count.png",
    "cell_count.txt",
    "cell_area.png",
    "cell_area.txt",
    "1_cell_area_distribution_kde.png",
    "2_cell_area_boxplot.png",
    "3_cell_area_cumulative.png",
    "4_cell_size_categories.png",
    "results.json",
    "report.pdf",
]

ANALYSIS_LOCK = threading.Lock()

app = FastAPI(title="ApoptosisUI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get("APOPTOSIS_ALLOWED_ORIGINS", "*").split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _require_access_key(x_api_key: str | None) -> None:
    if API_ACCESS_KEY and x_api_key != API_ACCESS_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")


def _assert_runtime_ready() -> None:
    if not SCRIPT_PATH.exists():
        raise HTTPException(status_code=500, detail="process_images.py was not found.")
    if not MODEL_PATH.exists():
        raise HTTPException(status_code=500, detail="best_model.pth was not found.")


def _clean_shared_outputs() -> None:
    for filename in OUTPUT_FILES:
        path = BASE_DIR / filename
        if path.exists() and path.is_file():
            path.unlink()


def _extract_json(stdout: str) -> dict[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        fallback = BASE_DIR / "results.json"
        if fallback.exists():
            return json.loads(fallback.read_text(encoding="utf-8"))
        raise RuntimeError("Analysis finished without JSON output.")

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


def _file_url(job_id: str, filename: str) -> str:
    return f"/api/jobs/{job_id}/files/{filename}"


def _copy_outputs(job_dir: Path) -> list[dict[str, str]]:
    copied: list[dict[str, str]] = []
    for filename in OUTPUT_FILES:
        source = BASE_DIR / filename
        if source.exists() and source.is_file():
            destination = job_dir / filename
            shutil.copy2(source, destination)
            copied.append(
                {
                    "name": filename,
                    "url": _file_url(job_dir.name, filename),
                    "kind": "image" if destination.suffix.lower() in {".png", ".jpg", ".jpeg"} else "file",
                }
            )
    return copied


async def _save_upload(upload: UploadFile, job_dir: Path) -> Path:
    original_name = Path(upload.filename or "sample.png").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image format.")

    destination = job_dir / f"input{suffix}"
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Uploaded image is too large.")
            handle.write(chunk)

    if total == 0:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    return destination


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model_present": MODEL_PATH.exists(),
        "script_present": SCRIPT_PATH.exists(),
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_access_key(x_api_key)
    _assert_runtime_ready()

    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    input_path = await _save_upload(file, job_dir)

    with ANALYSIS_LOCK:
        _clean_shared_outputs()
        command = [
            sys.executable,
            str(SCRIPT_PATH),
            "--input",
            str(input_path),
            "--action",
            "all",
            "--json",
            "--pdf",
        ]

        completed = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROCESS_TIMEOUT_SECONDS,
        )

        (job_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8", errors="replace")
        (job_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8", errors="replace")

        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "Analysis failed."
            raise HTTPException(status_code=500, detail=message[-4000:])

        try:
            results = _extract_json(completed.stdout)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not parse analysis JSON: {exc}") from exc

        outputs = _copy_outputs(job_dir)

    (job_dir / "api_result.json").write_text(
        json.dumps({"job_id": job_id, "results": results, "outputs": outputs}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return {
        "job_id": job_id,
        "status": results.get("status", "success"),
        "results": results,
        "outputs": outputs,
    }


@app.get("/api/jobs/{job_id}/files/{filename}")
def get_job_file(
    job_id: str,
    filename: str,
    x_api_key: str | None = Header(default=None),
) -> FileResponse:
    _require_access_key(x_api_key)
    if not job_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid job id.")

    safe_name = Path(filename).name
    path = JOBS_DIR / job_id / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
