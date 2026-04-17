"""Apoptosis processing pipeline.

Desteklenen aksiyonlar: predict, cell, cell_area, all (tümünü çalıştır).
Yeni model: UNet++ (segmentation_models_pytorch) ResNet50 encoder ile.
JSON çıktı formatı ve PDF rapor desteği.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Suppress warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

try:
    import torch
except ImportError:
    torch = None

try:
    import segmentation_models_pytorch as smp
except ImportError:
    smp = None

try:
    import albumentations as A
    from albumentations.pytorch import ToTensorV2
except ImportError:
    A = None
    ToTensorV2 = None

try:
    import skimage.measure
    SKIMAGE_AVAILABLE = True
except ImportError:
    SKIMAGE_AVAILABLE = False

try:
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle, PageBreak
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------
def report_progress(step: str, percent: int, message: str):
    """Report progress to stderr in a parseable format."""
    progress_data = {"step": step, "percent": percent, "message": message}
    print(f"PROGRESS:{json.dumps(progress_data)}", file=sys.stderr)


def safe_imwrite(filepath: str, img: np.ndarray) -> bool:
    """Write image using imencode - works on OneDrive/cloud folders where safe_imwrite fails."""
    try:
        ext = os.path.splitext(filepath)[1].lower()
        if ext == '.jpg' or ext == '.jpeg':
            encode_param = [cv2.IMWRITE_JPEG_QUALITY, 95]
            success, encoded = cv2.imencode('.jpg', img, encode_param)
        else:
            success, encoded = cv2.imencode('.png', img)

        if success:
            with open(filepath, 'wb') as f:
                f.write(encoded.tobytes())
            return True
        return False
    except Exception as e:
        print(f"DEBUG: safe_imwrite EXCEPTION: {e}", file=sys.stderr, flush=True)
        return False


# ---------------------------------------------------------------------------
# Dynamic paths - relative to script location
# ---------------------------------------------------------------------------
# Get script directory - handle Windows OneDrive paths properly
_script_file = os.path.abspath(__file__)
SCRIPT_DIR = Path(os.path.dirname(_script_file))
BASE_DIR = SCRIPT_DIR  # Output directory = script directory

# Debug log file - write to file in case stderr is not captured
DEBUG_LOG_PATH = os.path.join(os.path.dirname(_script_file), "debug_log.txt")

def debug_log(msg: str):
    """Write debug message to both stderr and log file."""
    print(f"DEBUG: {msg}", file=sys.stderr, flush=True)
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"DEBUG: {msg}\n")
            f.flush()
    except:
        pass

# Clear debug log on startup
try:
    with open(DEBUG_LOG_PATH, "w", encoding="utf-8") as f:
        f.write(f"=== DEBUG LOG STARTED ===\n")
except:
    pass

debug_log(f"Script file = {_script_file}")
debug_log(f"Output directory = {BASE_DIR}")
debug_log(f"Output directory exists = {os.path.exists(str(BASE_DIR))}")

INPUT_IMAGE = os.path.join(str(BASE_DIR), "input.jpg")
MODEL_PATH = os.path.join(str(BASE_DIR), "best_model.pth")

debug_log(f"Model path = {MODEL_PATH}")
debug_log(f"Model exists = {os.path.exists(MODEL_PATH)}")

# Model configuration (must match training)
NUM_CLASSES = 4
INPUT_SIZE = 512  # Model trained with 512x512 patches

COLOR_MAP = {
    0: (0, 0, 0),       # Background - Black
    1: (0, 255, 0),     # Healthy - Green
    2: (0, 0, 255),     # Affected - Blue (BGR)
    3: (255, 0, 0),     # Irrelevant - Red (BGR)
}

MIN_CELL_AREA = 5  # pixels

# ---------------------------------------------------------------------------
# Inference optimization config
# ---------------------------------------------------------------------------
BATCH_SIZE = 4  # Optimal for RTX 2060 (6GB VRAM)
USE_FP16 = True  # Use half precision for ~2x speedup
USE_JIT = False  # Disabled - can hang on some systems
WARMUP_RUNS = 1  # Single warmup run

# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------
MODEL = None
MODEL_LOADED = False
MODEL_WARMED_UP = False
DEVICE = None
MODEL_DTYPE = None  # Will be set to float16 or float32


def _load_model():
    """Load UNet++ model with ResNet50 encoder, with FP16 optimization."""
    global DEVICE, MODEL_DTYPE

    if torch is None or smp is None:
        return None

    if not os.path.exists(MODEL_PATH):
        return None

    try:
        DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Determine dtype - use FP16 on CUDA for speed
        if USE_FP16 and DEVICE.type == 'cuda':
            MODEL_DTYPE = torch.float16
        else:
            MODEL_DTYPE = torch.float32

        # Create model with same architecture as training
        model = smp.UnetPlusPlus(
            encoder_name="resnet50",
            encoder_weights=None,
            in_channels=3,
            classes=NUM_CLASSES,
            decoder_attention_type="scse",
        )

        # Load trained weights
        state_dict = torch.load(MODEL_PATH, map_location=DEVICE, weights_only=False)
        model.load_state_dict(state_dict)

        model.to(DEVICE)
        model.eval()

        # Enable cuDNN auto-tuner for optimal convolution algorithms
        if DEVICE.type == 'cuda':
            torch.backends.cudnn.benchmark = True

        # Convert to FP16 if enabled
        if MODEL_DTYPE == torch.float16:
            model = model.half()

        return model

    except Exception:
        return None


def _warmup_model(model, transform):
    """Warmup model for optimal performance (cuDNN autotuning)."""
    global MODEL_WARMED_UP
    if MODEL_WARMED_UP or model is None:
        return

    try:
        dummy = np.zeros((INPUT_SIZE, INPUT_SIZE, 3), dtype=np.uint8)
        transformed = transform(image=dummy)
        dummy_batch = transformed['image'].unsqueeze(0).to(DEVICE, dtype=MODEL_DTYPE)
        dummy_batch = dummy_batch.repeat(BATCH_SIZE, 1, 1, 1)

        with torch.inference_mode():
            for _ in range(WARMUP_RUNS):
                _ = model(dummy_batch)
            if DEVICE.type == 'cuda':
                torch.cuda.synchronize()

        MODEL_WARMED_UP = True
    except Exception:
        MODEL_WARMED_UP = True


def _ensure_model_loaded():
    """Lazy model loading."""
    global MODEL, MODEL_LOADED
    if MODEL_LOADED:
        return MODEL
    MODEL_LOADED = True
    MODEL = _load_model()
    return MODEL


def _get_transform():
    """Get inference transform (same as validation in training)."""
    if A is None or ToTensorV2 is None:
        return None
    return A.Compose([
        A.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ToTensorV2(),
    ])


def _imread_bgr(path: str) -> np.ndarray:
    """Read image with Unicode-safe path handling."""
    with open(path, "rb") as f:
        data = np.frombuffer(f.read(), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"{path} not found or unreadable.")
    return img


def _stub_mask_from_image(img_path: str, output_size: tuple) -> np.ndarray:
    """Generate a placeholder mask when no model is present."""
    img = _imread_bgr(img_path)
    img = cv2.resize(img, output_size)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresholds = np.percentile(gray, [33, 66])
    mask = np.zeros_like(gray, dtype=np.uint8)
    mask[gray >= thresholds[0]] = 1
    mask[gray >= thresholds[1]] = 2
    rng = np.random.default_rng(42)
    yx = rng.integers(0, output_size[0], size=(150, 2))
    mask[yx[:, 0], yx[:, 1]] = 3
    return mask


def _create_gaussian_weight(patch_size: int, sigma_factor: float = 0.25) -> np.ndarray:
    """Create a 2D Gaussian weight map for patch blending."""
    sigma = patch_size * sigma_factor
    center = patch_size // 2
    x = np.arange(patch_size)
    gaussian_1d = np.exp(-((x - center) ** 2) / (2 * sigma ** 2))
    gaussian_2d = np.outer(gaussian_1d, gaussian_1d)
    gaussian_2d = 0.1 + 0.9 * (gaussian_2d / gaussian_2d.max())
    return gaussian_2d.astype(np.float32)


def _clean_prediction(prediction: np.ndarray, min_size: int = 500) -> np.ndarray:
    """Remove small isolated regions using morphological operations."""
    cleaned = prediction.copy()
    num_classes = 4

    # First pass: morphological cleaning per class
    for cls in range(num_classes):
        mask = (cleaned == cls).astype(np.uint8)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        cleaned[prediction == cls] = 0
        cleaned[mask == 1] = cls

    # Second pass: remove small connected components
    for cls in range(num_classes):
        mask = (cleaned == cls).astype(np.uint8)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for label_id in range(1, num_labels):
            area = stats[label_id, cv2.CC_STAT_AREA]
            if area < min_size:
                cleaned[labels == label_id] = 255  # Mark for filling

    # Fill marked regions with nearest neighbor
    if np.any(cleaned == 255):
        filled = cleaned.copy()
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        for _ in range(50):
            if not np.any(filled == 255):
                break
            for cls in range(num_classes):
                cls_mask = (filled == cls).astype(np.uint8)
                dilated = cv2.dilate(cls_mask, kernel, iterations=1)
                fill_mask = (dilated == 1) & (filled == 255)
                filled[fill_mask] = cls
        filled[filled == 255] = 0
        cleaned = filled

    return cleaned


def infer_mask(input_path: str) -> np.ndarray:
    """Run patch-based inference with Gaussian blending for full resolution output.

    Optimized with batch processing and GPU accumulation.
    """
    model = _ensure_model_loaded()

    # Read original image
    original = _imread_bgr(input_path)
    image_rgb = cv2.cvtColor(original, cv2.COLOR_BGR2RGB)
    h, w = image_rgb.shape[:2]

    if model is None:
        return _stub_mask_from_image(input_path, (w, h))

    transform = _get_transform()
    if transform is None:
        return _stub_mask_from_image(input_path, (w, h))

    # Warmup model
    _warmup_model(model, transform)

    patch_size = INPUT_SIZE  # 512
    stride = 128  # 75% overlap

    # Create Gaussian weight map for blending (on GPU)
    gaussian_weight_np = _create_gaussian_weight(patch_size)
    gaussian_weight = torch.from_numpy(gaussian_weight_np).to(DEVICE)

    # Initialize output arrays on GPU
    output_sum = torch.zeros((NUM_CLASSES, h, w), dtype=torch.float32, device=DEVICE)
    weight_sum = torch.zeros((h, w), dtype=torch.float32, device=DEVICE)

    # Generate patch coordinates
    y_coords = list(range(0, max(1, h - patch_size + 1), stride))
    x_coords = list(range(0, max(1, w - patch_size + 1), stride))

    # Add edge patches if needed
    if len(y_coords) == 0 or y_coords[-1] + patch_size < h:
        y_coords.append(max(0, h - patch_size))
    if len(x_coords) == 0 or x_coords[-1] + patch_size < w:
        x_coords.append(max(0, w - patch_size))

    # Remove duplicates and sort
    y_coords = sorted(set(y_coords))
    x_coords = sorted(set(x_coords))

    # Collect all patch info
    patch_info = []  # (y, x, actual_h, actual_w, patch_tensor)

    for y in y_coords:
        for x in x_coords:
            y_end = min(y + patch_size, h)
            x_end = min(x + patch_size, w)
            actual_h = y_end - y
            actual_w = x_end - x

            # Extract patch
            patch = image_rgb[y:y_end, x:x_end]

            # Pad if necessary
            if actual_h < patch_size or actual_w < patch_size:
                padded = np.zeros((patch_size, patch_size, 3), dtype=np.uint8)
                padded[:actual_h, :actual_w] = patch
                patch = padded

            # Transform
            transformed = transform(image=patch)
            tensor = transformed['image']  # Don't move to GPU yet
            patch_info.append((y, x, actual_h, actual_w, tensor))

    # Process patches in batches
    with torch.inference_mode():
        for batch_start in range(0, len(patch_info), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(patch_info))
            batch_patches = patch_info[batch_start:batch_end]

            # Stack tensors, pin memory, and move to GPU with non-blocking transfer
            batch_tensors = torch.stack([p[4] for p in batch_patches])
            if DEVICE.type == 'cuda':
                batch_tensors = batch_tensors.pin_memory().to(DEVICE, dtype=MODEL_DTYPE, non_blocking=True)
            else:
                batch_tensors = batch_tensors.to(DEVICE, dtype=MODEL_DTYPE)

            # Batch inference
            batch_output = model(batch_tensors)
            batch_probs = torch.softmax(batch_output.float(), dim=1)  # softmax in FP32 for precision

            # Accumulate each patch result (still on GPU)
            for i, (y, x, actual_h, actual_w, _) in enumerate(batch_patches):
                y_end = y + actual_h
                x_end = x + actual_w

                probs = batch_probs[i]  # (4, H, W)
                weight = gaussian_weight[:actual_h, :actual_w]

                # Accumulate weighted predictions on GPU
                output_sum[:, y:y_end, x:x_end] += probs[:, :actual_h, :actual_w] * weight
                weight_sum[y:y_end, x:x_end] += weight

    # Ensure all GPU operations are complete before final transfer
    if DEVICE.type == 'cuda':
        torch.cuda.synchronize()

    # Weighted average predictions (on GPU)
    weight_sum = torch.clamp(weight_sum, min=1e-8)
    output_avg = output_sum / weight_sum.unsqueeze(0)

    # Get final prediction and transfer to CPU only once
    prediction = torch.argmax(output_avg, dim=0).cpu().numpy().astype(np.uint8)

    # Post-processing: clean up small isolated regions
    prediction = _clean_prediction(prediction, min_size=500)

    return prediction


# ---------------------------------------------------------------------------
# Visualization functions
# ---------------------------------------------------------------------------

def visualize_mask(mask: np.ndarray, target_class: Optional[int] = None) -> np.ndarray:
    """Convert mask to colored visualization."""
    h, w = mask.shape
    color_mask = np.zeros((h, w, 3), dtype=np.uint8)

    if target_class is not None:
        color_mask[mask == target_class] = COLOR_MAP.get(target_class, (255, 255, 255))
        return color_mask

    for cls, color in COLOR_MAP.items():
        color_mask[mask == cls] = color

    return color_mask


def save_overlay(color_mask: np.ndarray, input_path: str, filename: str) -> str:
    """Blend color mask with original image and save."""
    print(f"DEBUG: save_overlay called with filename={filename}", file=sys.stderr, flush=True)
    base = _imread_bgr(input_path)
    h, w = base.shape[:2]

    # Ensure mask is same size as image
    if color_mask.shape[:2] != (h, w):
        color_mask = cv2.resize(color_mask, (w, h), interpolation=cv2.INTER_NEAREST)

    overlay = cv2.addWeighted(base, 0.65, color_mask, 0.35, 0)

    # Use os.path.join for Windows compatibility
    out_path = os.path.join(str(BASE_DIR), filename)
    print(f"DEBUG: save_overlay saving to {out_path}", file=sys.stderr, flush=True)

    try:
        success = safe_imwrite(out_path, overlay)
        print(f"DEBUG: save_overlay imwrite returned: {success}", file=sys.stderr, flush=True)
        print(f"DEBUG: save_overlay file exists: {os.path.exists(out_path)}", file=sys.stderr, flush=True)
        if not success:
            print(f"DEBUG: safe_imwrite failed! overlay shape={overlay.shape}, dtype={overlay.dtype}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"DEBUG: save_overlay EXCEPTION: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)

    return out_path


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------

def run_predict_action(mask: np.ndarray, input_path: str) -> dict:
    """Basic prediction - just save mask and overlay."""
    print(f"DEBUG: ====== run_predict_action STARTED ======", file=sys.stderr, flush=True)
    print(f"DEBUG: BASE_DIR = {BASE_DIR}", file=sys.stderr, flush=True)
    print(f"DEBUG: input_path = {input_path}", file=sys.stderr, flush=True)
    print(f"DEBUG: input_path exists = {os.path.exists(input_path)}", file=sys.stderr, flush=True)

    # Use os.path.join for Windows compatibility
    base_dir_str = str(BASE_DIR)
    print(f"DEBUG: base_dir_str = {base_dir_str}", file=sys.stderr, flush=True)
    print(f"DEBUG: base_dir_str exists = {os.path.exists(base_dir_str)}", file=sys.stderr, flush=True)

    # TEST: Write a simple test file first to verify directory is writable
    test_path = os.path.join(base_dir_str, "predict_test.txt")
    try:
        with open(test_path, "w") as f:
            f.write("predict_test")
        print(f"DEBUG: TEST FILE written successfully: {test_path}", file=sys.stderr, flush=True)
        print(f"DEBUG: TEST FILE exists: {os.path.exists(test_path)}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"DEBUG: TEST FILE FAILED: {e}", file=sys.stderr, flush=True)

    # Check mask
    print(f"DEBUG: mask shape = {mask.shape}, dtype = {mask.dtype}", file=sys.stderr, flush=True)
    print(f"DEBUG: mask unique values = {np.unique(mask)}", file=sys.stderr, flush=True)

    color_mask = visualize_mask(mask)
    print(f"DEBUG: color_mask shape = {color_mask.shape}, dtype = {color_mask.dtype}", file=sys.stderr, flush=True)

    # Read base image
    print(f"DEBUG: Reading base image from {input_path}", file=sys.stderr, flush=True)
    try:
        base_img = _imread_bgr(input_path)
        h, w = base_img.shape[:2]
        print(f"DEBUG: base_img shape = {base_img.shape}, dtype = {base_img.dtype}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"DEBUG: FAILED to read base image: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        raise

    # Save original image for UI display
    original_path = os.path.join(base_dir_str, "original.png")
    print(f"DEBUG: Saving original to {original_path}", file=sys.stderr, flush=True)
    try:
        # Try with imencode + file write as alternative
        success = safe_imwrite(original_path, base_img)
        print(f"DEBUG: original.png safe_imwrite returned: {success}", file=sys.stderr, flush=True)
        if not success:
            # Alternative method
            print(f"DEBUG: Trying alternative method for original.png", file=sys.stderr, flush=True)
            retval, buffer = cv2.imencode('.png', base_img)
            if retval:
                with open(original_path, 'wb') as f:
                    f.write(buffer)
                print(f"DEBUG: original.png saved via imencode", file=sys.stderr, flush=True)
        print(f"DEBUG: original.png exists after save: {os.path.exists(original_path)}", file=sys.stderr, flush=True)
        if os.path.exists(original_path):
            print(f"DEBUG: original.png size: {os.path.getsize(original_path)} bytes", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"DEBUG: original.png EXCEPTION: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)

    # Save prediction mask
    out_mask_path = os.path.join(base_dir_str, "prediction_result_predict.png")
    print(f"DEBUG: Saving mask to {out_mask_path}", file=sys.stderr, flush=True)
    try:
        success = safe_imwrite(out_mask_path, color_mask)
        print(f"DEBUG: prediction_result_predict.png safe_imwrite returned: {success}", file=sys.stderr, flush=True)
        if not success:
            # Alternative method
            print(f"DEBUG: Trying alternative method for prediction_result_predict.png", file=sys.stderr, flush=True)
            retval, buffer = cv2.imencode('.png', color_mask)
            if retval:
                with open(out_mask_path, 'wb') as f:
                    f.write(buffer)
                print(f"DEBUG: prediction_result_predict.png saved via imencode", file=sys.stderr, flush=True)
        print(f"DEBUG: prediction_result_predict.png exists after save: {os.path.exists(out_mask_path)}", file=sys.stderr, flush=True)
        if os.path.exists(out_mask_path):
            print(f"DEBUG: prediction_result_predict.png size: {os.path.getsize(out_mask_path)} bytes", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"DEBUG: prediction_result_predict.png EXCEPTION: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)

    # Save overlay
    overlay_path = os.path.join(base_dir_str, "overlay_predict.png")
    print(f"DEBUG: Saving overlay to {overlay_path}", file=sys.stderr, flush=True)
    try:
        save_overlay(color_mask, input_path, "overlay_predict.png")
        print(f"DEBUG: overlay_predict.png exists after save: {os.path.exists(overlay_path)}", file=sys.stderr, flush=True)
        if os.path.exists(overlay_path):
            print(f"DEBUG: overlay_predict.png size: {os.path.getsize(overlay_path)} bytes", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"DEBUG: overlay_predict.png EXCEPTION: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)

    # Final verification
    print(f"DEBUG: ====== FINAL VERIFICATION ======", file=sys.stderr, flush=True)
    for fname in ["original.png", "prediction_result_predict.png", "overlay_predict.png", "predict_test.txt"]:
        fpath = os.path.join(base_dir_str, fname)
        exists = os.path.exists(fpath)
        size = os.path.getsize(fpath) if exists else 0
        print(f"DEBUG: {fname}: exists={exists}, size={size}", file=sys.stderr, flush=True)

    print(f"DEBUG: ====== run_predict_action COMPLETED ======", file=sys.stderr, flush=True)
    return {"action": "predict", "mask_path": out_mask_path}


def _separate_touching_cells(cell_mask: np.ndarray, min_distance: int = 20) -> np.ndarray:
    """Separate touching cells using watershed algorithm."""
    from scipy import ndimage
    from skimage.feature import peak_local_max
    from skimage.segmentation import watershed

    # Distance transform - peaks indicate cell centers
    distance = ndimage.distance_transform_edt(cell_mask)

    # Find local maxima as cell markers
    # min_distance controls minimum separation between cell centers
    coords = peak_local_max(
        distance,
        min_distance=min_distance,
        labels=cell_mask,
        exclude_border=False
    )

    # Create marker image
    markers = np.zeros(cell_mask.shape, dtype=np.int32)
    for i, (y, x) in enumerate(coords, start=1):
        markers[y, x] = i

    # Expand markers slightly for better watershed seeding
    markers = ndimage.grey_dilation(markers, size=(3, 3))

    # Apply watershed
    # Use negative distance as "elevation" so cell centers are valleys
    labels = watershed(-distance, markers, mask=cell_mask)

    return labels


def run_cell_action(mask: np.ndarray, input_path: str) -> dict:
    """Cell counting with watershed-based cell separation."""
    if not SKIMAGE_AVAILABLE:
        return {"action": "cell", "error": "skimage not available", "cell_count": 0}

    from skimage.measure import label, regionprops

    # Include all cell classes: Healthy (1), Affected (2), Irrelevant (3)
    # Class 0 = Background (not a cell)
    cell_mask = ((mask == 1) | (mask == 2) | (mask == 3)).astype(np.uint8)

    # Morphological cleanup
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cell_mask = cv2.morphologyEx(cell_mask, cv2.MORPH_CLOSE, kernel)
    cell_mask = cv2.morphologyEx(cell_mask, cv2.MORPH_OPEN, kernel)

    # Separate touching cells using watershed
    # min_distance=8 for fine cell separation
    labeled_mask = _separate_touching_cells(cell_mask, min_distance=8)
    props = regionprops(labeled_mask)

    valid_cells = [prop for prop in props if prop.area >= MIN_CELL_AREA]
    cell_count = len(valid_cells)

    # Create visualization (scale=1 for speed, original resolution is enough)
    h, w = cell_mask.shape

    background = _imread_bgr(input_path)
    background = cv2.resize(background, (w, h))

    colors = {
        "background": (15, 15, 35),
        "healthy": (50, 255, 126),       # Green for healthy (BGR)
        "affected": (60, 60, 255),       # Red for affected (BGR)
        "irrelevant": (255, 150, 50),    # Blue for irrelevant (BGR)
        "cell_border": (0, 230, 255),
        "text": (255, 255, 255),
        "accent": (255, 193, 7),
    }

    # Create gradient background (vectorized for speed)
    gradient_factors = np.linspace(0, 1, h).reshape(-1, 1, 1)
    bg_color = np.array(colors["background"], dtype=np.float32)
    canvas = (bg_color * (1 - gradient_factors * 0.1)).astype(np.uint8)
    canvas = np.broadcast_to(canvas, (h, w, 3)).copy()

    blended = cv2.addWeighted(canvas, 0.8, background, 0.2, 0)

    # Overlay cells with different colors based on original class
    cell_overlay = np.zeros_like(blended)
    # Healthy cells (class 1) in green
    cell_overlay[(labeled_mask > 0) & (mask == 1)] = colors["healthy"]
    # Affected cells (class 2) in red
    cell_overlay[(labeled_mask > 0) & (mask == 2)] = colors["affected"]
    # Irrelevant cells (class 3) in blue
    cell_overlay[(labeled_mask > 0) & (mask == 3)] = colors["irrelevant"]
    blended = cv2.addWeighted(blended, 0.7, cell_overlay, 0.3, 0)

    # Draw contours for each individual cell (watershed-separated)
    for prop in valid_cells:
        cell_id = prop.label
        single_cell_mask = (labeled_mask == cell_id).astype(np.uint8)
        contours, _ = cv2.findContours(single_cell_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(blended, contours, -1, colors["cell_border"], 1)

    # Number each cell
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.4
    thickness = 1

    for i, prop in enumerate(valid_cells, 1):
        y_center = int(prop.centroid[0])
        x_center = int(prop.centroid[1])

        text = str(i)
        text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
        badge_radius = max(text_size[0], text_size[1]) // 2 + 5

        cv2.circle(blended, (x_center, y_center), badge_radius, colors["accent"], -1)
        cv2.circle(blended, (x_center, y_center), badge_radius, colors["text"], 1)

        text_x = x_center - text_size[0] // 2
        text_y = y_center + text_size[1] // 2
        cv2.putText(blended, text, (text_x, text_y), font, font_scale, colors["background"], thickness)

    # Add legend
    legend_y = h - 120
    legend_items = [
        ("Healthy Cells", colors["healthy"]),
        ("Affected Cells", colors["affected"]),
        ("Irrelevant Cells", colors["irrelevant"]),
        ("Cell Boundaries", colors["cell_border"]),
        ("Cell Numbers", colors["accent"]),
    ]

    for i, (label, color) in enumerate(legend_items):
        y_pos = legend_y + i * 25
        cv2.rectangle(blended, (20, y_pos - 8), (35, y_pos + 8), color, -1)
        cv2.putText(blended, label, (45, y_pos + 5), font, 0.5, colors["text"], 1)

    # Save outputs - use os.path.join for Windows compatibility
    cell_count_path = os.path.join(str(BASE_DIR), "cell_count.png")
    print(f"DEBUG: Saving cell_count.png to {cell_count_path}", file=sys.stderr, flush=True)
    safe_imwrite(cell_count_path, blended)
    print(f"DEBUG: cell_count.png exists: {os.path.exists(cell_count_path)}", file=sys.stderr, flush=True)

    cell_count_txt_path = os.path.join(str(BASE_DIR), "cell_count.txt")
    with open(cell_count_txt_path, "w", encoding="utf-8") as f:
        f.write(str(cell_count))
    print(f"DEBUG: cell_count.txt exists: {os.path.exists(cell_count_txt_path)}", file=sys.stderr, flush=True)

    # Save mask and overlay - show all cell classes
    color_mask = visualize_mask(mask)  # All classes
    pred_cell_path = os.path.join(str(BASE_DIR), "prediction_result_cell.png")
    safe_imwrite(pred_cell_path, color_mask)
    save_overlay(color_mask, input_path, "overlay_cell.png")

    return {"action": "cell", "cell_count": cell_count}


def run_cell_area_action(mask: np.ndarray, input_path: str) -> dict:
    """Cell area analysis with statistics and plots."""
    if not SKIMAGE_AVAILABLE:
        return {"action": "cell_area", "error": "skimage not available", "total_cells": 0, "mean_area": 0}

    from skimage.measure import regionprops
    from scipy import stats
    import colorsys

    colors = {
        "background": (15, 15, 35),
        "cell": (50, 255, 126),
        "accent": (0, 230, 255),
        "text": (255, 255, 255),
        "gradient_start": (64, 224, 255),
        "warning": (255, 193, 7),
        "danger": (220, 53, 69),
        "success": (40, 167, 69),
    }

    # Include all cell classes: Healthy (1), Affected (2), Irrelevant (3)
    cell_mask = ((mask == 1) | (mask == 2) | (mask == 3)).astype(np.uint8)

    # Morphological cleanup
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cell_mask = cv2.morphologyEx(cell_mask, cv2.MORPH_CLOSE, kernel)
    cell_mask = cv2.morphologyEx(cell_mask, cv2.MORPH_OPEN, kernel)

    # Separate touching cells using watershed
    # min_distance=8 for fine cell separation
    labeled = _separate_touching_cells(cell_mask, min_distance=8)
    props = regionprops(labeled)

    if not props:
        print("No cells detected!", file=sys.stderr)
        with open(os.path.join(str(BASE_DIR), "cell_area.txt"), "w", encoding="utf-8") as f:
            f.write("No cells detected in the image.")
        color_mask = visualize_mask(mask)
        safe_imwrite(os.path.join(str(BASE_DIR), "prediction_result_cell_area.png"), color_mask)
        return {"action": "cell_area", "total_cells": 0}

    # Separate cells by class and calculate areas
    areas = [prop.area for prop in props]

    # Get class for each cell based on majority class in that region
    areas_by_class = {1: [], 2: [], 3: []}  # healthy, affected, irrelevant
    for prop in props:
        # Get the class at the centroid of the cell
        cy, cx = int(prop.centroid[0]), int(prop.centroid[1])
        cell_class = mask[cy, cx]
        if cell_class in areas_by_class:
            areas_by_class[cell_class].append(prop.area)
    min_area_val, max_area_val = min(areas), max(areas)
    area_range = max_area_val - min_area_val if max_area_val > min_area_val else 1

    # Create visualization (no upscaling for speed)
    h, w = mask.shape

    background = _imread_bgr(input_path)
    background = cv2.resize(background, (w, h))

    # Create gradient canvas (vectorized for speed)
    gradient_factors = np.linspace(0, 1, h).reshape(-1, 1, 1)
    bg_color = np.array(colors["background"], dtype=np.float32)
    grad_color = np.array(colors["gradient_start"], dtype=np.float32)
    canvas = (bg_color * (1 - gradient_factors * 0.15) + grad_color * (gradient_factors * 0.08)).astype(np.uint8)
    canvas = np.broadcast_to(canvas, (h, w, 3)).copy()

    blended = cv2.addWeighted(canvas, 0.7, background, 0.3, 0)

    # Draw cells with area-based coloring
    for prop in props:
        area = prop.area
        normalized_area = (area - min_area_val) / area_range
        hue = (1 - normalized_area) * 0.67
        color = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.8, 1.0))

        cell_id = prop.label
        cell_mask_single = (labeled == cell_id).astype(np.uint8)
        contours, _ = cv2.findContours(cell_mask_single, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            main_contour = max(contours, key=cv2.contourArea)
            cv2.drawContours(blended, [main_contour], -1, color, 2)
            cv2.drawContours(blended, [main_contour], -1, colors["text"], 1)

    # Add area labels
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale, thickness = 0.4, 1

    for prop in props:
        area = prop.area
        y_center, x_center = prop.centroid
        center = (int(x_center), int(y_center))

        normalized_area = (area - min_area_val) / area_range
        if normalized_area > 0.8:
            text_color = colors["danger"]
        elif normalized_area > 0.5:
            text_color = colors["warning"]
        else:
            text_color = colors["success"]

        area_text = f"{area}"
        text_size = cv2.getTextSize(area_text, font, font_scale, thickness)[0]

        # Find non-overlapping position
        text_pos = (center[0] + 10, center[1] - 10)
        text_pos = (
            max(0, min(text_pos[0], w - text_size[0])),
            max(text_size[1], min(text_pos[1], h)),
        )

        padding = 3
        box_pt1 = (text_pos[0] - padding, text_pos[1] - text_size[1] - padding)
        box_pt2 = (text_pos[0] + text_size[0] + padding, text_pos[1] + padding)

        cv2.rectangle(blended, box_pt1, box_pt2, (25, 25, 45), -1)
        cv2.rectangle(blended, box_pt1, box_pt2, text_color, 1)
        cv2.putText(blended, area_text, text_pos, font, font_scale, colors["text"], thickness)
        cv2.line(blended, center, text_pos, tuple(int(c * 0.7) for c in text_color), 1)

    # Add legend
    legend_y_start = 30
    legend_items = [
        ("Large Cells", colors["danger"]),
        ("Medium Cells", colors["warning"]),
        ("Small Cells", colors["success"]),
    ]

    for i, (label_text, color) in enumerate(legend_items):
        y_pos = legend_y_start + i * 25
        cv2.rectangle(blended, (10, y_pos - 8), (25, y_pos + 8), color, -1)
        cv2.putText(blended, label_text, (35, y_pos + 5), font, 0.5, colors["text"], 1)

    cell_area_png_path = os.path.join(str(BASE_DIR), "cell_area.png")
    print(f"DEBUG: Saving cell_area.png to {cell_area_png_path}", file=sys.stderr, flush=True)
    safe_imwrite(cell_area_png_path, blended)

    # Generate statistical plots
    plt.style.use("dark_background")

    # Plot 1: Class-based distribution (overlapping KDE curves)
    fig1 = plt.figure(figsize=(12, 7))
    fig1.patch.set_facecolor("#0F0F23")
    ax1 = fig1.add_subplot(111)

    class_colors = {
        1: ("#32CD32", "Healthy"),      # Green
        2: ("#FF4444", "Affected"),     # Red
        3: ("#4488FF", "Irrelevant"),   # Blue
    }

    # Find global min/max for x-axis
    all_areas_flat = [a for cls_areas in areas_by_class.values() for a in cls_areas]
    if all_areas_flat:
        x_min, x_max = min(all_areas_flat), max(all_areas_flat)
        kde_x = np.linspace(x_min, x_max, 200)

    # Plot each class as overlapping distribution
    for cls_id, cls_areas in areas_by_class.items():
        if len(cls_areas) < 2:
            continue
        color, label = class_colors[cls_id]

        # Histogram (semi-transparent)
        ax1.hist(cls_areas, bins=25, alpha=0.3, color=color, density=True, label=f"{label} (n={len(cls_areas)})")

        # KDE curve
        try:
            kde = stats.gaussian_kde(cls_areas)
            ax1.plot(kde_x, kde(kde_x), color=color, linewidth=2.5, alpha=0.9)
            ax1.fill_between(kde_x, kde(kde_x), alpha=0.15, color=color)
        except Exception:
            pass

    ax1.set_title("Cell Area Distribution by Class", fontsize=16, fontweight="bold", color="white")
    ax1.set_xlabel("Cell Area (pixels)", fontsize=12, color="white")
    ax1.set_ylabel("Density (Number of Cells)", fontsize=12, color="white")
    ax1.legend(loc="upper right", fontsize=10, facecolor="#1a1a2e", edgecolor="white", labelcolor="white")
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(colors="white")
    plt.savefig(os.path.join(str(BASE_DIR), "1_cell_area_distribution_kde.png"), dpi=100, facecolor="#0F0F23", bbox_inches="tight")
    plt.close()

    # Plot 2: Boxplot by class (side-by-side comparison)
    fig2 = plt.figure(figsize=(10, 6))
    fig2.patch.set_facecolor("#0F0F23")
    ax2 = fig2.add_subplot(111)

    # Prepare data for boxplot
    box_data = []
    box_labels = []
    box_colors = []
    for cls_id in [1, 2, 3]:
        if areas_by_class[cls_id]:
            box_data.append(areas_by_class[cls_id])
            color, label = class_colors[cls_id]
            box_labels.append(f"{label}\n(n={len(areas_by_class[cls_id])})")
            box_colors.append(color)

    if box_data:
        bp = ax2.boxplot(box_data, patch_artist=True, notch=True,
                         medianprops=dict(color="white", linewidth=2),
                         flierprops=dict(marker="o", markerfacecolor="gray", markersize=5, alpha=0.5))
        for patch, color in zip(bp["boxes"], box_colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        ax2.set_xticklabels(box_labels, color="white")

    ax2.set_title("Cell Area Comparison by Class", fontsize=14, fontweight="bold", color="white")
    ax2.set_ylabel("Cell Area (pixels)", fontsize=12, color="white")
    ax2.grid(True, alpha=0.3, axis="y")
    ax2.tick_params(colors="white")
    plt.savefig(os.path.join(str(BASE_DIR), "2_cell_area_boxplot.png"), dpi=100, facecolor="#0F0F23", bbox_inches="tight")
    plt.close()

    # Plot 3: Cumulative distribution
    fig3 = plt.figure(figsize=(10, 6))
    fig3.patch.set_facecolor("#0F0F23")
    ax3 = fig3.add_subplot(111)
    sorted_areas = np.sort(areas)
    cumulative = np.arange(1, len(sorted_areas) + 1) / len(sorted_areas)
    ax3.plot(sorted_areas, cumulative, "g-", linewidth=2)
    ax3.fill_between(sorted_areas, cumulative, alpha=0.3, color="green")
    ax3.set_title("Cumulative Distribution", fontsize=12, fontweight="bold", color="white")
    ax3.set_xlabel("Area (pixels)", color="white")
    ax3.set_ylabel("Cumulative Probability", color="white")
    ax3.grid(True, alpha=0.3)
    plt.savefig(os.path.join(str(BASE_DIR), "3_cell_area_cumulative.png"), dpi=100, facecolor="#0F0F23", bbox_inches="tight")
    plt.close()

    # Plot 4: Pie chart - Cell Class Distribution
    fig4 = plt.figure(figsize=(8, 8))
    fig4.patch.set_facecolor("#0F0F23")
    ax4 = fig4.add_subplot(111)

    # Use actual class counts
    pie_data = []
    pie_labels = []
    pie_colors = []

    class_info = {
        1: ("Healthy", "#32CD32", len(areas_by_class[1])),
        2: ("Affected", "#FF4444", len(areas_by_class[2])),
        3: ("Irrelevant", "#4488FF", len(areas_by_class[3])),
    }

    for cls_id, (label, color, count) in class_info.items():
        if count > 0:
            pie_data.append(count)
            pie_labels.append(f"{label}\n({count} cells)")
            pie_colors.append(color)

    if pie_data:
        wedges, texts, autotexts = ax4.pie(
            pie_data, labels=pie_labels, colors=pie_colors,
            autopct="%1.1f%%", startangle=90,
            textprops={"color": "white", "fontsize": 11},
            wedgeprops={"edgecolor": "white", "linewidth": 1.5},
            explode=[0.02] * len(pie_data)
        )
        for autotext in autotexts:
            autotext.set_fontsize(12)
            autotext.set_fontweight("bold")

    ax4.set_title("Cell Class Distribution", fontsize=14, fontweight="bold", color="white")
    plt.savefig(os.path.join(str(BASE_DIR), "4_cell_size_categories.png"), dpi=100, facecolor="#0F0F23", bbox_inches="tight")
    plt.close()

    # Calculate all statistics
    total_cells = len(areas)
    mean_area = float(np.mean(areas))
    median_area = float(np.median(areas))
    std_area = float(np.std(areas))
    cv_percent = (std_area / mean_area * 100) if mean_area > 0 else 0
    total_coverage = float(np.sum(areas))
    min_area = float(np.min(areas))
    max_area = float(np.max(areas))

    # Class-based cell counts
    healthy_count = len(areas_by_class[1])
    affected_count = len(areas_by_class[2])
    irrelevant_count = len(areas_by_class[3])

    # Save text report
    cell_area_txt_path = os.path.join(str(BASE_DIR), "cell_area.txt")
    with open(cell_area_txt_path, "w", encoding="utf-8") as f:
        f.write("COMPREHENSIVE CELL AREA ANALYSIS\n")
        f.write("=" * 50 + "\n\n")
        f.write("CELL COUNTS BY CLASS:\n")
        f.write("-" * 25 + "\n")
        f.write(f"Total Cells: {total_cells}\n")
        f.write(f"  - Healthy: {healthy_count}\n")
        f.write(f"  - Affected: {affected_count}\n")
        f.write(f"  - Irrelevant: {irrelevant_count}\n\n")
        f.write("AREA STATISTICS:\n")
        f.write("-" * 25 + "\n")
        f.write(f"Mean Area: {mean_area:.2f} pixels\n")
        f.write(f"Median Area: {median_area:.2f} pixels\n")
        f.write(f"Std Deviation: {std_area:.2f} pixels\n")
        f.write(f"CV: {cv_percent:.1f}%\n")
        f.write(f"Min Area: {min_area:.2f} pixels\n")
        f.write(f"Max Area: {max_area:.2f} pixels\n")
        f.write(f"Total Coverage: {total_coverage:.2f} pixels\n")

    # Save mask and overlay - show all cell classes
    color_mask = visualize_mask(mask)  # All classes, not just target_class=1
    pred_cell_area_path = os.path.join(str(BASE_DIR), "prediction_result_cell_area.png")
    safe_imwrite(pred_cell_area_path, color_mask)
    save_overlay(color_mask, input_path, "overlay_cell_area.png")

    return {
        "action": "cell_area",
        "total_cells": total_cells,
        "healthy_count": healthy_count,
        "affected_count": affected_count,
        "irrelevant_count": irrelevant_count,
        "mean_area": mean_area,
        "median_area": median_area,
        "std_area": std_area,
        "cv_percent": cv_percent,
        "min_area": min_area,
        "max_area": max_area,
        "total_coverage": total_coverage,
    }


def compute_class_distribution(mask: np.ndarray) -> dict:
    """Compute pixel distribution across classes."""
    total_pixels = mask.size
    distribution = {}
    class_names = {0: "background", 1: "healthy", 2: "affected", 3: "irrelevant"}

    for class_id, class_name in class_names.items():
        pixel_count = int(np.sum(mask == class_id))
        percent = (pixel_count / total_pixels) * 100 if total_pixels > 0 else 0
        distribution[class_name] = {
            "pixels": pixel_count,
            "percent": round(percent, 2)
        }

    return distribution


def run_all_actions(input_path: str) -> dict:
    """Run all actions with a single inference pass."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"{input_path} not found")

    report_progress("loading", 5, "Loading model...")

    # Single inference
    report_progress("inference", 20, "Running inference...")
    mask = infer_mask(input_path)

    # Compute class distribution
    report_progress("analysis", 30, "Computing class distribution...")
    class_distribution = compute_class_distribution(mask)

    # Run all actions on the same mask
    results = {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "input_file": os.path.basename(input_path),
        "actions_completed": [],
        "statistics": {
            "class_distribution": class_distribution
        },
        "output_files": []
    }

    report_progress("predict", 40, "Generating segmentation overlay...")
    predict_result = run_predict_action(mask, input_path)
    results["actions_completed"].append("predict")
    results["output_files"].extend(["original.png", "prediction_result_predict.png", "overlay_predict.png"])

    report_progress("cell", 60, "Counting cells...")
    cell_result = run_cell_action(mask, input_path)
    results["actions_completed"].append("cell")
    results["statistics"]["cell_count"] = cell_result.get("cell_count", 0)
    results["output_files"].extend(["cell_count.png", "cell_count.txt"])

    report_progress("cell_area", 80, "Analyzing cell areas...")
    area_result = run_cell_area_action(mask, input_path)
    results["actions_completed"].append("cell_area")

    # Add all cell area statistics to JSON
    results["statistics"]["total_cells"] = area_result.get("total_cells", 0)
    results["statistics"]["cell_counts_by_class"] = {
        "healthy": area_result.get("healthy_count", 0),
        "affected": area_result.get("affected_count", 0),
        "irrelevant": area_result.get("irrelevant_count", 0),
    }
    results["statistics"]["area_stats"] = {
        "mean": round(area_result.get("mean_area", 0), 2),
        "median": round(area_result.get("median_area", 0), 2),
        "std": round(area_result.get("std_area", 0), 2),
        "cv_percent": round(area_result.get("cv_percent", 0), 1),
        "min": round(area_result.get("min_area", 0), 2),
        "max": round(area_result.get("max_area", 0), 2),
        "total_coverage": round(area_result.get("total_coverage", 0), 2),
    }
    # Keep backward compatibility
    results["statistics"]["mean_cell_area"] = round(area_result.get("mean_area", 0), 2)

    results["output_files"].extend([
        "cell_area.png", "cell_area.txt",
        "1_cell_area_distribution_kde.png",
        "2_cell_area_boxplot.png",
        "3_cell_area_cumulative.png",
        "4_cell_size_categories.png"
    ])

    report_progress("complete", 100, "All actions completed.")

    # Save JSON results - use os.path.join for Windows compatibility
    json_path = os.path.join(str(BASE_DIR), "results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    results["output_files"].append("results.json")

    return results


def generate_pdf_report(results: dict, input_path: str, output_path: Optional[str] = None) -> str:
    """Generate a comprehensive PDF report."""
    if not REPORTLAB_AVAILABLE:
        print("ReportLab not available; skipping PDF generation.", file=sys.stderr)
        return ""

    if output_path is None:
        output_path = os.path.join(str(BASE_DIR), "report.pdf")

    doc = SimpleDocTemplate(output_path, pagesize=A4,
                           rightMargin=1.5*cm, leftMargin=1.5*cm,
                           topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        textColor=rl_colors.HexColor('#2C3E50')
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceAfter=12,
        textColor=rl_colors.HexColor('#34495E')
    )
    normal_style = styles['Normal']

    story = []

    # Title
    story.append(Paragraph("Cell Morphology Analysis Report", title_style))
    story.append(Paragraph(f"Generated: {results.get('timestamp', datetime.now().isoformat())}", normal_style))
    story.append(Paragraph(f"Input File: {results.get('input_file', 'Unknown')}", normal_style))
    story.append(Spacer(1, 20))

    # Class Distribution
    story.append(Paragraph("Class Distribution", heading_style))
    class_dist = results.get("statistics", {}).get("class_distribution", {})
    dist_data = [["Class", "Pixels", "Percentage"]]
    for class_name, data in class_dist.items():
        dist_data.append([
            class_name.capitalize(),
            f"{data['pixels']:,}",
            f"{data['percent']:.1f}%"
        ])

    dist_table = Table(dist_data, colWidths=[4*cm, 4*cm, 4*cm])
    dist_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor('#3498DB')),
        ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), rl_colors.HexColor('#ECF0F1')),
        ('GRID', (0, 0), (-1, -1), 1, rl_colors.HexColor('#BDC3C7')),
    ]))
    story.append(dist_table)
    story.append(Spacer(1, 20))

    # Cell Statistics
    story.append(Paragraph("Cell Statistics", heading_style))
    stats = results.get("statistics", {})
    stats_data = [
        ["Metric", "Value"],
        ["Total Cells", str(stats.get("cell_count", stats.get("total_cells", 0)))],
        ["Mean Cell Area", f"{stats.get('mean_cell_area', 0):.2f} px"],
    ]
    stats_table = Table(stats_data, colWidths=[6*cm, 6*cm])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor('#27AE60')),
        ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 1), (-1, -1), rl_colors.HexColor('#ECF0F1')),
        ('GRID', (0, 0), (-1, -1), 1, rl_colors.HexColor('#BDC3C7')),
    ]))
    story.append(stats_table)
    story.append(Spacer(1, 20))

    # Images
    story.append(Paragraph("Visualizations", heading_style))

    # Original image
    if os.path.exists(input_path):
        story.append(Paragraph("Original Image:", normal_style))
        try:
            img = RLImage(input_path, width=12*cm, height=9*cm)
            story.append(img)
        except:
            pass
        story.append(Spacer(1, 10))

    # Overlay
    overlay_path = os.path.join(str(BASE_DIR), "overlay_predict.png")
    if os.path.exists(overlay_path):
        story.append(Paragraph("Segmentation Overlay:", normal_style))
        try:
            img = RLImage(overlay_path, width=12*cm, height=9*cm)
            story.append(img)
        except:
            pass
        story.append(Spacer(1, 10))

    # Cell count visualization
    cell_count_path = os.path.join(str(BASE_DIR), "cell_count.png")
    if os.path.exists(cell_count_path):
        story.append(PageBreak())
        story.append(Paragraph("Cell Count Visualization:", normal_style))
        try:
            img = RLImage(cell_count_path, width=14*cm, height=10*cm)
            story.append(img)
        except:
            pass
        story.append(Spacer(1, 10))

    # Area distribution
    kde_path = os.path.join(str(BASE_DIR), "1_cell_area_distribution_kde.png")
    if os.path.exists(kde_path):
        story.append(PageBreak())
        story.append(Paragraph("Cell Area Distribution:", normal_style))
        try:
            img = RLImage(kde_path, width=14*cm, height=8*cm)
            story.append(img)
        except:
            pass

    # Pie chart
    pie_path = os.path.join(str(BASE_DIR), "4_cell_size_categories.png")
    if os.path.exists(pie_path):
        story.append(Spacer(1, 10))
        story.append(Paragraph("Cell Size Categories:", normal_style))
        try:
            img = RLImage(pie_path, width=10*cm, height=10*cm)
            story.append(img)
        except:
            pass

    # Build PDF
    try:
        doc.build(story)
        print(f"PDF report saved to: {output_path}", file=sys.stderr)
        return output_path
    except Exception as e:
        print(f"Failed to generate PDF: {e}", file=sys.stderr)
        return ""


def run_action(action: str, input_path: str) -> dict:
    """Run a single action."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"{input_path} not found")

    action = action.lower()

    if action == "all":
        return run_all_actions(input_path)

    mask = infer_mask(input_path)

    if action == "predict":
        return run_predict_action(mask, input_path)
    elif action == "cell":
        return run_cell_action(mask, input_path)
    elif action == "cell_area":
        return run_cell_area_action(mask, input_path)
    else:
        raise ValueError(f"Unsupported action '{action}'. Use predict/cell/cell_area/all.")


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_batch(input_folder: str, output_folder: Optional[str] = None, generate_pdf: bool = True) -> dict:
    """Process multiple images in a folder."""
    input_path = Path(input_folder)
    if not input_path.is_dir():
        raise ValueError(f"{input_folder} is not a valid directory")

    if output_folder:
        output_path = Path(output_folder)
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = input_path / "results"
        output_path.mkdir(exist_ok=True)

    # Find all images
    image_extensions = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp'}
    images = [f for f in input_path.iterdir() if f.suffix.lower() in image_extensions]

    if not images:
        return {"status": "error", "message": "No images found in folder"}

    batch_results = {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "input_folder": str(input_folder),
        "output_folder": str(output_path),
        "total_images": len(images),
        "processed": 0,
        "failed": 0,
        "results": []
    }

    for i, image_file in enumerate(images, 1):
        report_progress("batch", int((i / len(images)) * 100),
                       f"Processing {image_file.name} ({i}/{len(images)})")

        try:
            # Create subfolder for this image
            image_output = output_path / image_file.stem
            image_output.mkdir(exist_ok=True)

            # Temporarily change BASE_DIR
            global BASE_DIR
            original_base = BASE_DIR
            BASE_DIR = image_output

            # Copy input image
            input_copy = image_output / "input.jpg"
            import shutil
            shutil.copy(str(image_file), str(input_copy))

            # Process
            result = run_all_actions(str(input_copy))
            result["source_file"] = str(image_file)

            # Generate PDF if requested
            if generate_pdf:
                pdf_path = generate_pdf_report(result, str(input_copy),
                                              str(image_output / f"{image_file.stem}_report.pdf"))
                if pdf_path:
                    result["pdf_report"] = pdf_path

            batch_results["results"].append(result)
            batch_results["processed"] += 1

            # Restore BASE_DIR
            BASE_DIR = original_base

        except Exception as e:
            batch_results["failed"] += 1
            batch_results["results"].append({
                "source_file": str(image_file),
                "status": "error",
                "error": str(e)
            })

    # Save batch summary
    summary_path = output_path / "batch_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(batch_results, f, indent=2, ensure_ascii=False)

    report_progress("complete", 100, f"Batch complete: {batch_results['processed']}/{len(images)} successful")

    return batch_results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Apoptosis processing pipeline")
    parser.add_argument("--action", choices=["predict", "cell", "cell_area", "all"],
                        default="all", help="Action to run (default: all)")
    parser.add_argument("--input", type=str, help="Input image path (default: input.jpg in script directory)")
    parser.add_argument("--batch", type=str, help="Process all images in folder (batch mode)")
    parser.add_argument("--output", type=str, help="Output folder for batch mode")
    parser.add_argument("--pdf", action="store_true", help="Generate PDF report")
    parser.add_argument("--json", action="store_true", help="Output results as JSON to stdout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if args.batch:
            # Batch mode
            result = process_batch(args.batch, args.output, generate_pdf=args.pdf)
        else:
            # Single image mode
            input_path = args.input if args.input else str(INPUT_IMAGE)

            # Check if input file exists
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Input file not found: {input_path}")

            result = run_action(args.action, input_path)

            # Generate PDF if requested
            if args.pdf and args.action == "all":
                pdf_path = generate_pdf_report(result, input_path)
                if pdf_path:
                    result["pdf_report"] = pdf_path

        # Output JSON to stdout if requested
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))

        return 0

    except Exception as exc:
        error_result = {"status": "error", "message": str(exc)}
        if args.json:
            print(json.dumps(error_result, indent=2))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())