const apiBaseInput = document.getElementById("apiBaseInput");
const apiKeyInput = document.getElementById("apiKeyInput");
const imageInput = document.getElementById("imageInput");
const fileName = document.getElementById("fileName");
const runButton = document.getElementById("runButton");
const statusText = document.getElementById("statusText");
const metricsGrid = document.getElementById("metricsGrid");
const gallery = document.getElementById("gallery");
const downloads = document.getElementById("downloads");
const jsonOutput = document.getElementById("jsonOutput");
const savedApiBase = localStorage.getItem("apoptosis_api_base") || "";
const savedApiKey = localStorage.getItem("apoptosis_api_key") || "";

apiBaseInput.value = savedApiBase;
apiKeyInput.value = savedApiKey;

const imageOutputNames = new Set([
  "original.png",
  "prediction_result_predict.png",
  "overlay_predict.png",
  "cell_count.png",
  "cell_area.png",
  "1_cell_area_distribution_kde.png",
  "2_cell_area_boxplot.png",
  "3_cell_area_cumulative.png",
  "4_cell_size_categories.png",
]);

function apiBase() {
  return (apiBaseInput.value.trim() || window.location.origin).replace(/\/$/, "");
}

function setStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.classList.toggle("error", isError);
}

function authHeaders() {
  const key = apiKeyInput.value.trim();
  const headers = { "ngrok-skip-browser-warning": "1" };
  if (key) {
    headers["X-API-Key"] = key;
  }
  return headers;
}

function absoluteUrl(path) {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `${apiBase()}${path}`;
}

function metric(label, value) {
  const card = document.createElement("div");
  card.className = "metric";
  card.innerHTML = `<span></span><strong></strong>`;
  card.querySelector("span").textContent = label;
  card.querySelector("strong").textContent = value ?? "-";
  return card;
}

function renderMetrics(results) {
  const stats = results.statistics || {};
  const classDistribution = stats.class_distribution || {};
  const areaStats = stats.area_stats || {};
  const byClass = stats.cell_counts_by_class || {};

  metricsGrid.innerHTML = "";
  metricsGrid.append(
    metric("Cell count", stats.cell_count),
    metric("Total cells", stats.total_cells),
    metric("Mean cell area", `${stats.mean_cell_area ?? 0} px`),
    metric("Healthy", byClass.healthy ?? 0),
    metric("Affected", byClass.affected ?? 0),
    metric("Irrelevant", byClass.irrelevant ?? 0),
    metric("Healthy pixels", `${classDistribution.healthy?.percent ?? 0}%`),
    metric("Affected pixels", `${classDistribution.affected?.percent ?? 0}%`),
    metric("Median area", areaStats.median ?? 0),
    metric("Std area", areaStats.std ?? 0),
    metric("Min area", areaStats.min ?? 0),
    metric("Max area", areaStats.max ?? 0),
  );
}

function labelFromName(name) {
  return name
    .replace(/^\d+_/, "")
    .replace(/_/g, " ")
    .replace(/\.[^.]+$/, "")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function renderOutputs(outputs) {
  gallery.innerHTML = "";
  downloads.innerHTML = "";

  for (const output of outputs) {
    const url = absoluteUrl(output.url);
    if (imageOutputNames.has(output.name)) {
      const card = document.createElement("article");
      card.className = "image-card";
      const image = document.createElement("img");
      image.src = url;
      image.alt = labelFromName(output.name);
      const caption = document.createElement("p");
      caption.textContent = labelFromName(output.name);
      card.append(image, caption);
      gallery.append(card);
    }

    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = output.name;
    downloads.append(link);
  }
}

async function runAnalysis() {
  const file = imageInput.files[0];
  if (!file) {
    setStatus("Select a microscopy image first.", true);
    return;
  }

  runButton.disabled = true;
  setStatus("Uploading image and running analysis. Keep this page open.");
  gallery.innerHTML = "";
  downloads.innerHTML = "";
  metricsGrid.innerHTML = "";
  jsonOutput.textContent = "{}";

  const formData = new FormData();
  formData.append("file", file);
  localStorage.setItem("apoptosis_api_base", apiBaseInput.value.trim());
  localStorage.setItem("apoptosis_api_key", apiKeyInput.value.trim());

  try {
    const response = await fetch(`${apiBase()}/api/analyze`, {
      method: "POST",
      headers: authHeaders(),
      body: formData,
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `Analysis failed with HTTP ${response.status}`);
    }

    renderMetrics(payload.results || {});
    renderOutputs(payload.outputs || []);
    jsonOutput.textContent = JSON.stringify(payload, null, 2);
    setStatus(`Analysis complete. Job ID: ${payload.job_id}`);
  } catch (error) {
    setStatus(error.message || "Analysis failed.", true);
  } finally {
    runButton.disabled = false;
  }
}

imageInput.addEventListener("change", () => {
  fileName.textContent = imageInput.files[0]?.name || "PNG, JPG, TIFF, or BMP";
});

runButton.addEventListener("click", runAnalysis);
