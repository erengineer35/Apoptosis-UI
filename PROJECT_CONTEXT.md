# ApoptosisUI Project Context

This file is a continuation snapshot for future Codex sessions. Read this before making changes.

## User Goal

The user wants ApoptosisUI to be accessible through a browser link while preserving the original scientific algorithm. The project is related to a TUSEB research context, so algorithmic behavior must not be changed casually.

Primary goals:

- Let other users access the app from a browser.
- Keep the original image analysis algorithm unchanged.
- Keep the project visible/shareable through GitHub.
- Use the user's/lab's own machine for computation when hosted CPUs are too slow.

## Non-Negotiable Rule

Do not rewrite, replace, simplify, or reimplement the scientific algorithm unless explicitly requested.

The following files are considered algorithm/backend core:

- `process_images.py`
- `best_model.pth`
- model loading and inference behavior
- segmentation output class meanings
- cell counting
- cell area analysis
- plot/PDF/JSON generation

Changes so far were intentionally limited to wrappers, deployment, and UI.

## Original Project

Original folder inspected:

```text
C:\Users\Erenn\Desktop\ApoptosisUI-codex
```

Project type:

- WPF/.NET desktop app
- Python AI/image-analysis backend
- PyTorch model weights in `best_model.pth`

Important files:

- `MainWindow.xaml`, `MainWindow.xaml.cs`: original WPF UI
- `process_images.py`: original analysis pipeline
- `report_generator.py`: PDF report generator
- `chat_handler.py`: AI chat helper
- `best_model.pth`: model weights, about 205 MB

Initial `dotnet build` succeeded with 0 errors and 0 warnings.

## Hosting Decisions

### Hugging Face Attempt

An initial Gradio wrapper was created:

- `app.py`
- `requirements.txt`
- `README.md`
- `README_HUGGINGFACE.md`

GitHub and Hugging Face remotes were configured. The Hugging Face Space was pushed successfully after fixing the README emoji metadata.

Reason Hugging Face was abandoned for real use:

- CPU runtime was too slow for the required analysis.
- GPU runtime required payment.
- The algorithm is heavy and should run on a GPU-capable local/lab machine.

### Final Architecture

The chosen architecture is hybrid:

```text
GitHub Pages public entry link
  -> redirects to ngrok public app URL
  -> ngrok tunnels to the user's/lab's machine
  -> FastAPI backend on localhost:8000
  -> process_images.py runs unchanged
  -> best_model.pth is used locally
```

This preserves the original algorithm and uses the user's/lab's compute.

## Current Public Access Flow

GitHub Pages entry link:

```text
https://erengineer35.github.io/Apoptosis-UI/
```

The GitHub Pages `docs/index.html` page redirects to the ngrok app:

```text
https://engraving-sake-doing.ngrok-free.dev
```

Current ngrok app URL provided by the user:

```text
https://engraving-sake-doing.ngrok-free.dev
```

Important: the ngrok URL works directly. The GitHub Pages page is only a stable entry/redirect page. Cross-origin API calls from GitHub Pages to ngrok caused `failed to fetch`, so the solution was to redirect users to the ngrok app where frontend and API share the same origin.

## Backend Runtime

Backend machine path used by the user:

```text
C:\Users\wall-e\Desktop\ApoptosisUI-codex
```

Start FastAPI backend on the compute machine:

```powershell
cd "C:\Users\wall-e\Desktop\ApoptosisUI-codex"
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

Health check:

```text
http://localhost:8000/api/health
```

Expected JSON includes:

```json
{
  "status": "ok",
  "model_present": true,
  "script_present": true
}
```

Start ngrok in a second PowerShell:

```powershell
cd "C:\Users\wall-e\Desktop\ApoptosisUI-codex"
.\ngrok.exe http 8000
```

The `uvicorn` window and the `ngrok` window must stay open. If either closes, external access stops.

## FastAPI Wrapper

File:

```text
api_server.py
```

Purpose:

- Serve the HTML frontend from `frontend/`
- Accept uploaded microscopy images at `POST /api/analyze`
- Save input into a job folder under `api_jobs/`
- Call the unchanged pipeline:

```bash
python process_images.py --input <uploaded-image> --action all --json --pdf
```

- Copy generated result files into the job folder
- Return JSON with `job_id`, `results`, and `outputs`

The backend serializes analysis with a lock because `process_images.py` writes shared output filenames in the project root.

`api_jobs/` is ignored by Git.

## GitHub Repo

Repository:

```text
https://github.com/erengineer35/Apoptosis-UI
```

The repo was initially private, then the user made it public so GitHub Pages works publicly.

Branch:

```text
main
```

Git LFS tracks:

```text
best_model.pth
```

Do not commit:

- `.env`
- `api_jobs/`
- `bin/`
- `obj/`
- `.vs/`
- generated output PNG/TXT/PDF/JSON files
- local secrets

## GitHub Pages

GitHub Pages source:

```text
main / docs
```

`docs/index.html` is currently a redirect/launch page for the ngrok app, not the full frontend.

Reason:

- GitHub Pages static frontend could display the UI.
- But API calls from GitHub Pages to ngrok failed due to cross-origin/ngrok behavior.
- Direct ngrok app works because frontend and backend are same-origin.

## Current UI State

The user created a custom WebUI in:

```text
C:\Users\Erenn\Desktop\ApoptosisUI\WebUI
```

Files there:

- `index.html`
- `script.js`
- `style.css`

That design was copied into:

```text
C:\Users\Erenn\Desktop\ApoptosisUI-codex\frontend
```

Then `frontend/app.js` was rewritten to connect the custom UI to the real FastAPI backend instead of using mock simulation.

Current active frontend files:

- `frontend/index.html`
- `frontend/styles.css`
- `frontend/app.js`

Important note:

- `frontend/index.html` currently has CSS and JS inlined into the HTML to avoid tunnel/static asset loading problems.
- `frontend/styles.css` and `frontend/app.js` remain as source files, but the served HTML includes their contents inline.
- If editing CSS/JS, update the source files and then re-inline into `frontend/index.html`.

The latest active UI commit at the time of this snapshot:

```text
68f2aa6 Activate custom WebUI design
```

Then another commit inlined frontend assets:

```text
36b32a9 Inline frontend assets for tunnel delivery
```

Note: if future log order differs, run:

```powershell
git log --oneline --decorate -10
```

## Known Issues And Resolutions

### Hugging Face slow startup / slow processing

Cause: CPU runtime too slow for PyTorch image analysis.

Resolution: abandoned HF CPU for production path; use local/lab machine with FastAPI + ngrok.

### Cloudflare quick tunnel worked but was temporary

Cloudflare quick tunnel produced random temporary URLs. It worked but was not ideal for stable use.

Resolution: moved to ngrok free dev domain.

### GitHub Pages `failed to fetch`

Cause: GitHub Pages frontend calling ngrok backend cross-origin caused fetch failures.

Resolution: GitHub Pages now redirects to the ngrok app URL. The app runs same-origin on ngrok.

### Page appeared unstyled after redirect

Cause: HTML loaded but CSS/JS static assets could fail over the tunnel/cache path.

Resolution: CSS and JS were inlined into `frontend/index.html`.

## Commands Frequently Needed

Update local development repo:

```powershell
cd "C:\Users\Erenn\Desktop\ApoptosisUI-codex"
git status --short --branch
git pull origin main
```

Push changes from development repo:

```powershell
cd "C:\Users\Erenn\Desktop\ApoptosisUI-codex"
git add <files>
git commit -m "message"
git push origin main
```

Update backend machine after changes:

```powershell
cd "C:\Users\wall-e\Desktop\ApoptosisUI-codex"
git pull origin main
```

Restart backend:

```powershell
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

Start ngrok:

```powershell
.\ngrok.exe http 8000
```

## Verification Checklist

After changes:

1. Check JS syntax:

```powershell
node --check frontend/app.js
```

2. Confirm algorithm/backend files were not changed unintentionally:

```powershell
git diff -- process_images.py api_server.py
```

3. Start backend and check:

```text
http://localhost:8000/api/health
```

4. Open ngrok app and run a test image.

5. Open GitHub Pages entry link and confirm it redirects to ngrok.

## How To Continue In A New Chat

Tell Codex:

```text
Read C:\Users\Erenn\Desktop\ApoptosisUI-codex\PROJECT_CONTEXT.md and continue the ApoptosisUI project from there.
```

Then provide the specific next task.
