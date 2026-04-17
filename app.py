from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import gradio as gr


BASE_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BASE_DIR / "process_images.py"
MODEL_PATH = BASE_DIR / "best_model.pth"

OUTPUT_IMAGES = [
    ("Original", "original.png"),
    ("Overlay", "overlay_predict.png"),
    ("Mask", "prediction_result_predict.png"),
    ("Cell Count", "cell_count.png"),
    ("Cell Area", "cell_area.png"),
    ("Area Distribution", "1_cell_area_distribution_kde.png"),
    ("Statistical Summary", "2_cell_area_boxplot.png"),
    ("Cumulative Distribution", "3_cell_area_cumulative.png"),
    ("Size Categories", "4_cell_size_categories.png"),
]

OUTPUT_DOWNLOADS = [
    "results.json",
    "report.pdf",
    "cell_count.txt",
    "cell_area.txt",
]

analysis_lock = threading.Lock()


def _extract_json(stdout: str) -> dict[str, Any]:
    """Read the JSON object emitted by process_images.py --json."""
    stripped = stdout.strip()
    if not stripped:
        raise RuntimeError("Analysis finished without JSON output.")

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


def _format_metrics(results: dict[str, Any]) -> str:
    stats = results.get("statistics", {})
    class_distribution = stats.get("class_distribution", {})
    area_stats = stats.get("area_stats", {})
    counts_by_class = stats.get("cell_counts_by_class", {})

    lines = [
        "## Analysis Metrics",
        f"- Status: `{results.get('status', 'unknown')}`",
        f"- Input file: `{results.get('input_file', '-')}`",
        f"- Cell count: `{stats.get('cell_count', 0)}`",
        f"- Total cells: `{stats.get('total_cells', 0)}`",
        f"- Mean cell area: `{stats.get('mean_cell_area', 0)}` px",
        "",
        "## Class Distribution",
    ]

    for label in ("background", "healthy", "affected", "irrelevant"):
        values = class_distribution.get(label, {})
        lines.append(
            f"- {label.title()}: `{values.get('percent', 0)}%` "
            f"({values.get('pixels', 0)} px)"
        )

    lines.extend(
        [
            "",
            "## Cell Counts By Class",
            f"- Healthy: `{counts_by_class.get('healthy', 0)}`",
            f"- Affected: `{counts_by_class.get('affected', 0)}`",
            f"- Irrelevant: `{counts_by_class.get('irrelevant', 0)}`",
            "",
            "## Area Statistics",
            f"- Mean: `{area_stats.get('mean', 0)}`",
            f"- Median: `{area_stats.get('median', 0)}`",
            f"- Std: `{area_stats.get('std', 0)}`",
            f"- CV: `{area_stats.get('cv_percent', 0)}%`",
            f"- Min: `{area_stats.get('min', 0)}`",
            f"- Max: `{area_stats.get('max', 0)}`",
            f"- Total coverage: `{area_stats.get('total_coverage', 0)}`",
        ]
    )

    return "\n".join(lines)


def _copy_upload_to_input(upload_path: str) -> Path:
    suffix = Path(upload_path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        suffix = ".png"

    destination = BASE_DIR / f"uploaded_sample{suffix}"
    shutil.copy2(upload_path, destination)
    return destination


def _existing_output_images() -> list[tuple[str, str]]:
    gallery = []
    for label, filename in OUTPUT_IMAGES:
        path = BASE_DIR / filename
        if path.exists():
            gallery.append((str(path), label))
    return gallery


def _existing_downloads(results: dict[str, Any]) -> list[str]:
    downloads = []

    pdf_report = results.get("pdf_report")
    if pdf_report and Path(pdf_report).exists():
        downloads.append(str(Path(pdf_report)))

    for filename in OUTPUT_DOWNLOADS:
        path = BASE_DIR / filename
        if path.exists() and str(path) not in downloads:
            downloads.append(str(path))

    return downloads


def analyze_image(uploaded_file: str | None):
    if uploaded_file is None:
        raise gr.Error("Please upload a microscopy image.")

    if not SCRIPT_PATH.exists():
        raise gr.Error("process_images.py was not found next to app.py.")

    if not MODEL_PATH.exists():
        raise gr.Error("best_model.pth was not found next to app.py.")

    with analysis_lock:
        input_path = _copy_upload_to_input(uploaded_file)

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
            timeout=1800,
        )

        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip()
            raise gr.Error(f"Analysis failed: {details}")

        results = _extract_json(completed.stdout)
        if results.get("status") == "error":
            raise gr.Error(results.get("message", "Analysis returned an error."))

        return (
            _existing_output_images(),
            _format_metrics(results),
            json.dumps(results, indent=2, ensure_ascii=False),
            _existing_downloads(results),
        )


with gr.Blocks(title="Cell Morphology Studio") as demo:
    gr.Markdown(
        """
        # Cell Morphology Studio

        Upload a microscopy image and run the original ApoptosisUI analysis pipeline.
        """
    )

    with gr.Row():
        with gr.Column(scale=1):
            image_input = gr.File(
                label="Microscopy image",
                file_types=[".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"],
                type="filepath",
            )
            analyze_button = gr.Button("Run Analysis", variant="primary")
            downloads_output = gr.Files(label="Downloads")

        with gr.Column(scale=2):
            gallery_output = gr.Gallery(
                label="Analysis Outputs",
                columns=2,
                height=520,
                object_fit="contain",
            )

    metrics_output = gr.Markdown(label="Metrics")
    json_output = gr.Code(label="Raw JSON", language="json")

    analyze_button.click(
        analyze_image,
        inputs=[image_input],
        outputs=[gallery_output, metrics_output, json_output, downloads_output],
    )


if __name__ == "__main__":
    server_port = int(os.environ.get("PORT", "7860"))
    demo.queue(default_concurrency_limit=1).launch(
        server_name="0.0.0.0",
        server_port=server_port,
    )
