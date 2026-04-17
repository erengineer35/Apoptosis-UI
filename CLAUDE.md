# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ApoptosisUI (Cell Morphology Studio) is a hybrid C#/Python desktop application for cell segmentation and morphological analysis of microscopy images. It combines a WPF frontend with a Python ML backend for deep learning-based image segmentation.

## Build and Run Commands

### C#/.NET Application
```bash
# Build the application
dotnet build ApoptosisUI.csproj

# Run the application
dotnet run --project ApoptosisUI.csproj
```

### Python Backend (Direct CLI Usage)
```bash
# Single image analysis (all actions)
python process_images.py --action all --json --pdf

# Individual actions
python process_images.py --action predict   # Segmentation only
python process_images.py --action cell      # Cell counting
python process_images.py --action cell_area # Area analysis

# Custom input file
python process_images.py --input /path/to/image.png --action all --json

# Batch processing
python process_images.py --batch /path/to/images --output /path/to/results --pdf --json
```

### Training
```bash
# Single GPU training
python train_segmentation.py

# Multi-GPU training with DDP
torchrun --nproc_per_node=2 train_segmentation.py
```

## Architecture

### Frontend-Backend Communication
1. WPF application copies uploaded image to `input.jpg` in script directory
2. Launches Python script via `Process.Start()` with arguments
3. Monitors stderr for `PROGRESS:{json}` messages for real-time progress
4. Parses stdout JSON for results (falls back to reading `results.json`)

### Model Architecture
- **ViT_UNet_CBAM** (`models.py`): Hybrid Vision Transformer + UNet with CBAM attention
  - Encoder: ViT-Base-Patch16-224 with multi-layer feature fusion (layers 4, 8, 12)
  - Decoder: UNet with CBAM (Convolutional Block Attention Module)
  - Deep supervision with auxiliary outputs
- **Inference model** (`process_images.py`): UNet++ with ResNet50 encoder from segmentation_models_pytorch
- 4 classes: Background (0), Healthy (1), Affected (2), Irrelevant (3)

### Key Configuration
- Input patch size: 512x512 pixels
- Inference stride: 128 pixels (75% overlap with Gaussian blending)
- Minimum cell area: 5 pixels

### Color Map (BGR)
- Class 0 (Background): Black (0, 0, 0)
- Class 1 (Healthy): Green (0, 255, 0)
- Class 2 (Affected): Blue (0, 0, 255)
- Class 3 (Irrelevant): Red (255, 0, 0)

## Key Files

- `MainWindow.xaml.cs` - WPF UI logic, Python process management, image handling
- `process_images.py` - Main inference pipeline, PDF report generation, batch processing
- `models.py` - ViT_UNet_CBAM model definition
- `train_segmentation.py` - DDP training script with CellPatchDataset
- `best_model.pth` - Pre-trained model weights (205MB, not in version control)

## Python Dependencies

Core: torch, torchvision, segmentation_models_pytorch, albumentations, opencv-python, numpy, scipy, scikit-image, matplotlib, pillow, transformers

Optional: reportlab (PDF generation - graceful fallback if missing)

## Special Considerations

- Uses `safe_imwrite()` for OneDrive/cloud path compatibility
- Progress reporting protocol: `PROGRESS:{json}` to stderr
- Model loading supports both full model and TorchScript traced format
- Patch-based inference with Gaussian weighting for seamless stitching
- Some code comments are in Turkish
