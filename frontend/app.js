document.addEventListener("DOMContentLoaded", () => {
  const cursorGlow = document.querySelector(".cursor-glow");
  const loginOverlay = document.getElementById("login-overlay");
  const dashboard = document.getElementById("dashboard");
  const btnLogin = document.getElementById("btn-login");
  const btnGuest = document.getElementById("btn-guest");
  const tabs = document.querySelectorAll(".tab");
  const views = document.querySelectorAll(".view-content");
  const dropzone = document.getElementById("dropzone");
  const btnSelect = document.getElementById("btn-select-image");
  const fileInput = document.getElementById("file-input");
  const btnRunAnalysis = document.getElementById("btn-run-analysis");
  const loadingOverlay = document.getElementById("loading-overlay");
  const analysisProgress = document.getElementById("analysis-progress");
  const analysisProgressText = document.getElementById("analysis-progress-text");
  const mainHeadline = document.getElementById("main-headline");
  const mainSubline = document.getElementById("main-subline");
  const valProcessed = document.getElementById("val-processed");
  const valStatus = document.getElementById("val-status");
  const barHealthy = document.getElementById("bar-healthy");
  const barAffected = document.getElementById("bar-affected");
  const barIrrelevant = document.getElementById("bar-irrelevant");
  const distHealthy = document.getElementById("dist-healthy");
  const distAffected = document.getElementById("dist-affected");
  const distIrrelevant = document.getElementById("dist-irrelevant");
  const btnExport = document.getElementById("btn-export");
  const btnReport = document.getElementById("btn-report");
  const viewerArea = document.getElementById("viewer-area");

  let selectedFile = null;
  let latestOutputs = [];

  document.addEventListener("mousemove", (event) => {
    cursorGlow.style.left = `${event.clientX}px`;
    cursorGlow.style.top = `${event.clientY}px`;
  });

  function animateLoginToDashboard() {
    const card = loginOverlay.querySelector(".login-card");
    card.style.transform = "scale(0.9)";
    card.style.opacity = "0";

    setTimeout(() => {
      loginOverlay.classList.remove("active");
      loginOverlay.classList.add("hidden");
      dashboard.classList.remove("hidden");

      dashboard.querySelectorAll(".fade-in-up").forEach((element) => {
        element.style.animation = "none";
        element.offsetHeight;
        element.style.animation = null;
      });
    }, 500);
  }

  btnLogin.addEventListener("click", animateLoginToDashboard);
  btnGuest.addEventListener("click", animateLoginToDashboard);

  function selectTab(targetId) {
    tabs.forEach((tab) => tab.classList.toggle("active", tab.getAttribute("data-target") === targetId));
    views.forEach((view) => view.classList.toggle("hidden", view.id !== targetId));
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => selectTab(tab.getAttribute("data-target")));
  });

  function outputUrl(name) {
    const found = latestOutputs.find((output) => output.name === name);
    return found ? found.url : "";
  }

  function absoluteUrl(path) {
    if (!path) return "";
    if (path.startsWith("http://") || path.startsWith("https://")) return path;
    return `${window.location.origin}${path}`;
  }

  function setImage(targetId, url, alt) {
    const target = document.getElementById(targetId);
    if (!url) {
      target.innerHTML = `<p class="viewer-placeholder">${alt} is not available.</p>`;
      return;
    }
    target.innerHTML = `<img class="result-img" src="${absoluteUrl(url)}" alt="${alt}">`;
  }

  function setPlot(targetId, url, alt) {
    const target = document.getElementById(targetId);
    if (!url) return;
    target.className = "mock-plot";
    target.innerHTML = `<img class="result-img" src="${absoluteUrl(url)}" alt="${alt}">`;
  }

  function resetResults() {
    analysisProgress.style.width = "0%";
    analysisProgressText.innerText = "Upload a frame to begin";
    distHealthy.innerText = "--%";
    distAffected.innerText = "--%";
    distIrrelevant.innerText = "--%";
    barHealthy.style.width = "0%";
    barAffected.style.width = "0%";
    barIrrelevant.style.width = "0%";
    btnExport.classList.add("disabled");
    btnReport.classList.add("disabled");
    btnExport.classList.remove("download-ready");
    btnReport.classList.remove("download-ready");
  }

  function handleImageLoad(file) {
    selectedFile = file;
    resetResults();

    const previewUrl = URL.createObjectURL(file);
    dropzone.classList.add("hidden");
    viewerArea.classList.add("has-image");
    document.getElementById("view-original").innerHTML =
      `<img src="${previewUrl}" alt="Selected microscopy frame" class="viewer-img">`;
    selectTab("view-original");

    btnRunAnalysis.classList.remove("disabled");
    mainHeadline.innerText = `${file.name} loaded`;
    mainSubline.innerText = "Ready for segmentation. Click Run Analysis to begin.";
    valStatus.innerText = "Ready";
  }

  btnSelect.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", () => {
    const [file] = fileInput.files;
    if (file) handleImageLoad(file);
  });

  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.style.background = "rgba(255, 255, 255, 0.8)";
  });

  dropzone.addEventListener("dragleave", (event) => {
    event.preventDefault();
    dropzone.style.background = "transparent";
  });

  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.style.background = "transparent";
    const [file] = event.dataTransfer.files;
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    handleImageLoad(file);
  });

  function setProgress(percent, text) {
    analysisProgress.style.width = `${percent}%`;
    analysisProgressText.innerText = text;
  }

  function updateDistribution(results) {
    const distribution = results?.statistics?.class_distribution || {};
    const healthy = distribution.healthy?.percent || 0;
    const affected = distribution.affected?.percent || 0;
    const irrelevant = distribution.irrelevant?.percent || 0;

    barHealthy.style.width = `${healthy}%`;
    distHealthy.innerText = `${healthy}%`;
    barAffected.style.width = `${affected}%`;
    distAffected.innerText = `${affected}%`;
    barIrrelevant.style.width = `${irrelevant}%`;
    distIrrelevant.innerText = `${irrelevant}%`;
  }

  function wireDownloads() {
    const results = outputUrl("results.json");
    const report = outputUrl("report.pdf");

    if (results) {
      btnExport.classList.remove("disabled");
      btnExport.classList.add("download-ready");
      btnExport.onclick = () => window.open(absoluteUrl(results), "_blank", "noopener");
    }

    if (report) {
      btnReport.classList.remove("disabled");
      btnReport.classList.add("download-ready");
      btnReport.onclick = () => window.open(absoluteUrl(report), "_blank", "noopener");
    }
  }

  function renderResults(payload) {
    latestOutputs = payload.outputs || [];
    setImage("view-original", outputUrl("original.png"), "Original");
    setImage("view-overlay", outputUrl("overlay_predict.png"), "Overlay");
    setImage("view-mask", outputUrl("prediction_result_predict.png"), "Mask");
    setImage("view-cells", outputUrl("cell_count.png"), "Cell count");
    setPlot("plot-kde", outputUrl("1_cell_area_distribution_kde.png"), "Area distribution");
    setPlot("plot-box", outputUrl("2_cell_area_boxplot.png"), "Statistical summary");
    setPlot("plot-pie", outputUrl("4_cell_size_categories.png"), "Size categories");
    updateDistribution(payload.results);
    wireDownloads();
    selectTab("view-overlay");
  }

  btnRunAnalysis.addEventListener("click", async () => {
    if (!selectedFile || btnRunAnalysis.classList.contains("disabled")) return;

    btnRunAnalysis.classList.add("disabled");
    loadingOverlay.classList.remove("hidden");
    valStatus.innerText = "Processing";
    mainHeadline.innerText = `Processing ${selectedFile.name}`;
    mainSubline.innerText = "Running segmentation and morphology analysis.";
    setProgress(18, "Uploading sample...");

    const formData = new FormData();
    formData.append("file", selectedFile);

    const progressTimer = setInterval(() => {
      const current = parseInt(analysisProgress.style.width || "18", 10);
      const next = Math.min(current + 7, 92);
      setProgress(next, next < 45 ? "Preparing inference..." : next < 75 ? "Analyzing morphology..." : "Generating outputs...");
    }, 900);

    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        body: formData,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || `Analysis failed with HTTP ${response.status}`);
      }

      clearInterval(progressTimer);
      setProgress(100, "Done");
      renderResults(payload);
      loadingOverlay.classList.add("hidden");
      valStatus.innerText = "Complete";
      valProcessed.innerText = parseInt(valProcessed.innerText, 10) + 1;
      mainHeadline.innerText = "Analysis complete";
      mainSubline.innerText = "Morphology segmentation and feature extraction finished successfully.";
    } catch (error) {
      clearInterval(progressTimer);
      loadingOverlay.classList.add("hidden");
      btnRunAnalysis.classList.remove("disabled");
      valStatus.innerText = "Error";
      mainHeadline.innerText = "Analysis failed";
      mainSubline.innerText = error.message || "The backend returned an error.";
      analysisProgressText.innerText = "Failed";
    }
  });
});
