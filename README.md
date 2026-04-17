---
title: Cell Morphology Studio
emoji: 🔬
colorFrom: green
colorTo: blue
sdk: gradio
app_file: app.py
pinned: false
---

# Cell Morphology Studio

Web wrapper for the original ApoptosisUI analysis pipeline.

The analysis algorithm remains in `process_images.py` and is called by `app.py` without reimplementing the model, segmentation, counting, area analysis, plotting, or PDF generation logic.
