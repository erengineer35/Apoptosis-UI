# Hybrid HTML + FastAPI Deployment

This mode keeps the original algorithm in `process_images.py` and exposes it through a local FastAPI backend.

## Architecture

```text
Browser HTML frontend
  -> FastAPI backend on the GPU workstation
  -> process_images.py
  -> best_model.pth
  -> result images, JSON, PDF
```

`api_server.py` calls:

```bash
python process_images.py --input <uploaded-image> --action all --json --pdf
```

The algorithm, model loading, segmentation, counting, area analysis, plotting, and PDF generation remain in `process_images.py`.

## Local Run

Install dependencies in the Python environment used by the project:

```powershell
pip install -r requirements.txt
```

Start the backend and bundled HTML frontend:

```powershell
cd "C:\Users\Erenn\Desktop\ApoptosisUI-codex"
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000
```

## Optional Access Key

Set an API key before starting the server:

```powershell
$env:APOPTOSIS_API_KEY = "choose-a-private-key"
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

Enter the same key in the frontend's Access key field.

## Tunnel For External Access

For a temporary public HTTPS URL without router port forwarding:

```powershell
cloudflared tunnel --url http://localhost:8000
```

Share the generated `https://...trycloudflare.com` URL only with intended users.

The workstation must stay powered on, connected to the internet, and running both `uvicorn` and the tunnel.

## GitHub Pages Frontend

The `docs/` folder contains the static frontend for GitHub Pages.

In GitHub repository settings:

1. Open `Settings`.
2. Open `Pages`.
3. Set source to `Deploy from a branch`.
4. Select branch `main`.
5. Select folder `/docs`.
6. Save.

The frontend URL will be similar to:

```text
https://erengineer35.github.io/Apoptosis-UI/
```

The GitHub Pages page is configured as a stable entry point that opens the live ngrok app:

```text
https://engraving-sake-doing.ngrok-free.dev
```

The ngrok app serves both the HTML interface and the FastAPI backend from the same origin, which avoids browser cross-origin request failures.

## Runtime Notes

- One analysis runs at a time to avoid shared output file collisions from `process_images.py`.
- Uploaded files and outputs are saved under `api_jobs/`, which is ignored by Git.
- Set `APOPTOSIS_MAX_UPLOAD_MB` to change the upload limit. The default is 50 MB.
- Set `APOPTOSIS_PROCESS_TIMEOUT` to change the analysis timeout. The default is 1800 seconds.
