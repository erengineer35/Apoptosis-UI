# Publishing Checklist

## Current Repository State

- The original analysis algorithm remains in `process_images.py`.
- The web wrapper is `app.py`.
- `best_model.pth` is tracked with Git LFS.
- `.env`, chat history, generated analysis outputs, build outputs, and local IDE files are ignored.

## Before Publishing

Decide the visibility model:

- Public GitHub repository: source code is visible to everyone.
- Public Hugging Face Space: app is visible and the Space source is visible.
- Private Hugging Face Space: app and source are private.
- Protected Hugging Face Space: app can be publicly accessible while source remains private, but this may require a paid Hugging Face plan.

For a research project with original model weights, avoid publishing `best_model.pth` publicly unless that is intended.

## Recommended Deployment Flow

1. Push this repository to GitHub for version control.
2. Create a Hugging Face Space for the runnable app.
3. Push the same code to the Hugging Face Space, or connect deployment from GitHub.
4. Upload `best_model.pth` through Git LFS or the Hugging Face web interface.
5. Configure secrets in the Hugging Face Space settings, not in `.env`.
6. Test one microscopy image after the Space finishes building.

## Required Runtime Files

- `app.py`
- `process_images.py`
- `report_generator.py`
- `chat_handler.py`
- `best_model.pth`
- `requirements.txt`
- `README.md`
