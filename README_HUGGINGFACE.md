# Hugging Face Deployment Notes

This web wrapper keeps the original analysis algorithm unchanged.

`app.py` does not reimplement segmentation, counting, area analysis, plotting, or PDF generation. It calls:

```bash
python process_images.py --input <uploaded-image> --action all --json --pdf
```

The following files must stay next to `app.py` in the Hugging Face Space:

- `process_images.py`
- `report_generator.py`
- `chat_handler.py`
- `best_model.pth`
- `requirements.txt`

Recommended first deployment:

1. Create a Hugging Face Space.
2. Choose Gradio as the SDK for the first working demo.
3. Upload the files listed above.
4. Add `best_model.pth` using Git LFS or Hugging Face's web upload because the file is larger than normal GitHub file limits.
5. Start with CPU or T4 GPU depending on runtime needs. GPU is recommended for public demos.

Do not commit `.env` or API keys. Configure secrets from the Space settings if chat/report interpretation needs external APIs.
