/* Banana Squad Dashboard v2 — Form + Gallery + WebSocket */

(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────
  let ws = null;
  let currentJobId = null;       // Job currently being tracked (live pipeline)
  let expandedJobId = null;      // Job whose gallery card is expanded
  let jobList = [];              // Array from GET /api/jobs
  let jobDetailCache = {};       // job_id → full detail JSON
  let agentLog = [];
  let uploadedFiles = [];        // Files from the form
  let searchDebounce = null;
  let generationProgress = { current: 0, total: 6 };
  let activityTimer = null;

  // ── DOM refs ───────────────────────────────────────────
  const $statusDot = document.getElementById("status-dot");
  const $statusText = document.getElementById("status-text");
  const $stages = document.getElementById("pipeline-stages");
  const $agentLog = document.getElementById("agent-log");
  const $pipelineCard = document.getElementById("pipeline-card");
  const $logCard = document.getElementById("log-card");
  const $gallery = document.getElementById("job-gallery");
  const $searchInput = document.getElementById("search-input");
  const $sortSelect = document.getElementById("sort-select");
  const $activityBanner = document.getElementById("activity-banner");
  const $activityText = document.getElementById("activity-text");

  // Form refs
  const $form = document.getElementById("generate-form");
  const $prompt = document.getElementById("prompt-input");
  const $aspect = document.getElementById("aspect-select");
  const $resolution = document.getElementById("resolution-select");
  const $fileInput = document.getElementById("file-input");
  const $dropZone = document.getElementById("file-drop-zone");
  const $filePreviews = document.getElementById("file-previews");
  const $submitBtn = document.getElementById("submit-btn");
  const $fileBrowse = document.getElementById("file-browse");

  // ── WebSocket ──────────────────────────────────────────

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => {
      $statusDot.className = "status-dot connected";
      $statusText.textContent = "Ansluten";
    };

    ws.onclose = () => {
      $statusDot.className = "status-dot disconnected";
      $statusText.textContent = "Frånkopplad";
      setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();

    ws.onmessage = (e) => {
      try {
        handleEvent(JSON.parse(e.data));
      } catch (err) {
        console.error("WS parse error:", err);
      }
    };
  }

  // ── Event handler ──────────────────────────────────────

  // ── Activity Banner ────────────────────────────────────

  function showActivity(text, isError, autoDismissMs) {
    if (activityTimer) clearTimeout(activityTimer);
    $activityBanner.style.display = "";
    $activityBanner.className = "activity-banner" + (isError ? " banner-error" : "");
    $activityText.textContent = text;
    if (autoDismissMs) {
      activityTimer = setTimeout(() => {
        $activityBanner.style.display = "none";
      }, autoDismissMs);
    }
  }

  function hideActivity() {
    if (activityTimer) clearTimeout(activityTimer);
    $activityBanner.style.display = "none";
  }

  const STAGE_LABELS = {
    research: "Analyserar referensbilder...",
    prompt_crafting: "Designar 6 promptvarianter...",
    generating: "Genererar bilder...",
    evaluating: "Utvärderar och rankar varianter...",
  };

  function handleEvent(event) {
    const { type, job_id, data, timestamp } = event;

    switch (type) {
      case "job_started":
        currentJobId = job_id;
        agentLog = [];
        generationProgress = { current: 0, total: 6 };
        showPipelineCards();
        renderPipeline("research");
        showActivity("Nytt jobb — analyserar referensbilder...");
        // Add to the top of jobList if not already there
        if (!jobList.find((j) => j.job_id === job_id)) {
          jobList.unshift({
            job_id: job_id,
            prompt: data.prompt || "",
            stage: "research",
            created_at: timestamp,
            completed_at: null,
            image_count: 0,
            winner: null,
            winner_path: null,
          });
        }
        // Invalidate cache for this job
        delete jobDetailCache[job_id];
        renderGallery();
        break;

      case "stage_changed":
        renderPipeline(data.stage);
        updateJobStage(job_id, data.stage);
        if (data.stage === "generating") {
          generationProgress = { current: 0, total: 6 };
        }
        showActivity(STAGE_LABELS[data.stage] || "Arbetar...");
        break;

      case "agent_message":
        agentLog.push({
          agent: data.agent,
          message: data.message,
          time: new Date(timestamp).toLocaleTimeString("sv-SE"),
        });
        renderAgentLog();
        break;

      case "progress":
        agentLog.push({
          agent: data.agent,
          message: data.message,
          time: new Date(timestamp).toLocaleTimeString("sv-SE"),
        });
        renderAgentLog();
        // Update generation progress from message like "Generating v2-enhanced (2/6)..."
        const progressMatch = (data.message || "").match(/\((\d+)\/(\d+)\)/);
        if (progressMatch) {
          generationProgress.current = parseInt(progressMatch[1], 10);
          generationProgress.total = parseInt(progressMatch[2], 10);
          renderPipeline("generating");
          showActivity("Genererar bilder (" + generationProgress.current + "/" + generationProgress.total + ")...");
        }
        break;

      case "image_generated":
        // Update live image count and re-render
        delete jobDetailCache[job_id];
        var jobEntry = jobList.find((j) => j.job_id === job_id);
        if (jobEntry) {
          jobEntry.image_count = (jobEntry.image_count || 0) + 1;
          renderGallery();
        }
        break;

      case "variant_scored":
        delete jobDetailCache[job_id];
        break;

      case "image_refined":
        delete jobDetailCache[job_id];
        // Re-render if this card is expanded
        if (expandedJobId === job_id) {
          fetchAndRenderDetail(job_id, true);
        }
        agentLog.push({
          agent: "generator",
          message: "Förfinad variant: " + (data.variant || ""),
          time: new Date(timestamp).toLocaleTimeString("sv-SE"),
        });
        renderAgentLog();
        break;

      case "job_completed": {
        updateJobStage(job_id, "complete");
        renderPipeline("complete");
        delete jobDetailCache[job_id];
        // Auto-expand the completed job
        expandedJobId = job_id;
        renderGallery();
        const imgCount = (data && data.successful_images) || "?";
        showActivity("Klart! " + imgCount + " bilder genererade.", false, 8000);
        break;
      }

      case "job_failed":
        updateJobStage(job_id, "failed");
        renderPipeline("failed");
        agentLog.push({
          agent: "system",
          message: "Fel: " + (data.error || "unknown"),
          time: new Date(timestamp).toLocaleTimeString("sv-SE"),
        });
        renderAgentLog();
        renderGallery();
        showActivity("Fel: " + (data.error || "okänt fel"), true, 10000);
        break;
    }
  }

  function updateJobStage(jobId, stage) {
    const job = jobList.find((j) => j.job_id === jobId);
    if (job) job.stage = stage;
  }

  // ── Pipeline + Log Cards ───────────────────────────────

  function showPipelineCards() {
    $pipelineCard.style.display = "";
    $logCard.style.display = "";
  }

  const STAGES = [
    { key: "research", icon: "🔍", label: "Analys" },
    { key: "prompt_crafting", icon: "✏️", label: "Promptdesign" },
    { key: "generating", icon: "🎨", label: "Bildgenerering" },
    { key: "evaluating", icon: "⭐", label: "Utvärdering" },
  ];

  function renderPipeline(currentStage) {
    const stageIndex = STAGES.findIndex((s) => s.key === currentStage);
    const isFailed = currentStage === "failed";
    const isComplete = currentStage === "complete";

    $stages.innerHTML = STAGES.map((s, i) => {
      let iconClass = "pending";
      if (isFailed && i === stageIndex) iconClass = "failed";
      else if (isComplete || i < stageIndex) iconClass = "done";
      else if (i === stageIndex) iconClass = "active";

      const labelClass = i === stageIndex && !isComplete ? "active" : "";

      // Progress bar for generating stage
      let subProgress = "";
      if (s.key === "generating" && i === stageIndex && !isComplete && !isFailed) {
        const pct = generationProgress.total > 0
          ? Math.round((generationProgress.current / generationProgress.total) * 100)
          : 0;
        subProgress = `
          <div class="stage-progress-bar"><div style="width: ${pct}%"></div></div>
          <span class="stage-sub-progress">${generationProgress.current}/${generationProgress.total} bilder</span>`;
      }

      return `
        <div class="stage">
          <div class="stage-icon ${iconClass}">${s.icon}</div>
          <div class="stage-content">
            <span class="stage-label ${labelClass}">${s.label}</span>
            ${subProgress}
          </div>
        </div>`;
    }).join("");
  }

  function renderAgentLog() {
    const entries = agentLog.slice(-30);
    $agentLog.innerHTML = entries
      .map(
        (e, i) => `
      <div class="log-entry${i === entries.length - 1 ? " log-entry-latest" : ""}">
        <span class="log-agent">${esc(e.agent)}</span>
        <span>${esc(e.message)}</span>
        <span class="log-time">${e.time}</span>
      </div>`
      )
      .join("");
    $agentLog.scrollTop = $agentLog.scrollHeight;
  }

  // ── Gallery ────────────────────────────────────────────

  function renderGallery() {
    if (!jobList.length) {
      $gallery.innerHTML = `
        <div class="empty-state">
          <div class="emoji">🎨</div>
          <p>Inga jobb ännu. Generera bilder med formuläret!</p>
        </div>`;
      return;
    }

    $gallery.innerHTML = jobList
      .map((j) => {
        const isExpanded = expandedJobId === j.job_id;
        const statusInfo = stageStatus(j.stage);
        const thumbSrc = j.winner_path
          ? "/outputs/" + j.winner_path
          : null;
        const date = j.created_at
          ? new Date(j.created_at).toLocaleDateString("sv-SE")
          : "";

        return `
          <div class="gallery-card ${isExpanded ? "expanded" : ""}" id="card-${j.job_id}">
            <div class="gallery-card-header" onclick="toggleJob('${j.job_id}')">
              ${
                thumbSrc
                  ? `<img class="gallery-card-thumb" src="${esc(thumbSrc)}" alt="thumb" loading="lazy">`
                  : `<div class="gallery-card-thumb" style="display:flex;align-items:center;justify-content:center;font-size:1.4rem;">🎨</div>`
              }
              <div class="gallery-card-info">
                <div class="gallery-card-prompt">${esc(j.prompt || j.job_id)}</div>
                <div class="gallery-card-meta">${date} · ${j.image_count || 0} bilder</div>
              </div>
              <span class="gallery-card-status ${statusInfo.cls}">${statusInfo.label}</span>
              <span class="gallery-card-chevron">▶</span>
            </div>
            <div class="gallery-card-body" id="detail-${j.job_id}">
              ${isExpanded ? '<div class="loading-spinner">Laddar...</div>' : ""}
            </div>
          </div>`;
      })
      .join("");

    // If a card is expanded, fetch its detail
    if (expandedJobId) {
      fetchAndRenderDetail(expandedJobId);
    }
  }

  function stageStatus(stage) {
    if (stage === "complete") return { cls: "complete", label: "Klar" };
    if (stage === "failed") return { cls: "failed", label: "Misslyckades" };
    return { cls: "running", label: "Arbetar..." };
  }

  window.toggleJob = function (jobId) {
    if (expandedJobId === jobId) {
      expandedJobId = null;
      renderGallery();
    } else {
      expandedJobId = jobId;
      renderGallery();
    }
  };

  async function fetchAndRenderDetail(jobId, forceRefresh) {
    const $container = document.getElementById("detail-" + jobId);
    if (!$container) return;

    // Use cache if available (unless force refresh)
    if (!forceRefresh && jobDetailCache[jobId]) {
      renderJobDetail(jobDetailCache[jobId], $container);
      return;
    }

    $container.innerHTML = '<div class="loading-spinner">Laddar detaljer...</div>';

    try {
      const res = await fetch("/api/jobs/" + jobId);
      if (!res.ok) throw new Error("Not found");
      const detail = await res.json();
      jobDetailCache[jobId] = detail;
      renderJobDetail(detail, $container);
    } catch (err) {
      $container.innerHTML = '<div class="loading-spinner">Kunde inte ladda jobb.</div>';
    }
  }

  function renderJobDetail(detail, $container) {
    let html = "";

    // Research info
    if (detail.research && detail.research.style) {
      html += `
        <div class="research-detail">
          <strong>Stil:</strong> ${esc(detail.research.style.slice(0, 200))}${detail.research.style.length > 200 ? "..." : ""}
          ${detail.research.mood ? `<br><strong>Mood:</strong> ${esc(detail.research.mood)}` : ""}
          ${detail.research.colors && detail.research.colors.length ? `<br><strong>Färger:</strong> ${esc(detail.research.colors.join(", "))}` : ""}
        </div>`;
    }

    // Variant images
    const images = (detail.images || []).filter((img) => img.success);
    const evals = detail.evaluations || [];

    if (images.length) {
      html += '<div class="variant-grid">';
      for (const img of images) {
        const filePath = img.file_path
          ? "/outputs/" + img.file_path
          : "";
        const ev = evals.find((e) => e.variant === img.variant);

        let scoreHtml = "";
        if (ev) {
          const dims = ["faithfulness", "conciseness", "readability", "aesthetics"];
          scoreHtml = dims
            .map(
              (d) => `
            <div class="score-bar-container">
              <span>${d.charAt(0).toUpperCase() + d.slice(1, 5)}</span>
              <div class="score-bar">
                <div class="score-bar-fill" style="width: ${(ev.scores[d] / 10) * 100}%"></div>
              </div>
              <span>${ev.scores[d].toFixed(1)}</span>
            </div>`
            )
            .join("");

          const rankClass = ev.rank <= 3 ? "rank-" + ev.rank : "";
          const medal = { 1: "🥇", 2: "🥈", 3: "🥉" }[ev.rank] || "#" + ev.rank;
          scoreHtml += `<span class="rank-badge ${rankClass}">${medal} ${ev.scores.total.toFixed(1)}/40</span>`;
        }

        // Find refinements for this variant
        const variantRefinements = (detail.refinements || []).filter(
          (r) => r.variant === img.variant
        );

        let refinementsHtml = "";
        if (variantRefinements.length) {
          refinementsHtml = '<div class="refinement-list">';
          for (const ref of variantRefinements) {
            const refPath = ref.refined_path
              ? "/outputs/" + ref.refined_path
              : "";
            const refDate = ref.created_at
              ? new Date(ref.created_at).toLocaleTimeString("sv-SE")
              : "";
            refinementsHtml += `
              <div class="refinement-row">
                ${refPath ? `<img src="${esc(refPath)}" alt="Refined"
                     onclick="window.open('${esc(refPath)}', '_blank')" loading="lazy">` : ""}
                <div class="refinement-meta">
                  ${ref.instruction ? `<span class="refinement-instruction">${esc(ref.instruction)}</span>` : '<span class="refinement-instruction">Allmän förbättring</span>'}
                  <span class="refinement-time">${refDate}</span>
                  ${refPath ? `<a class="btn-download" href="${esc(refPath)}" download>Ladda ner</a>` : ""}
                </div>
              </div>`;
          }
          refinementsHtml += "</div>";
        }

        // Feedback state for this variant
        const fb = (detail.feedback || {})[img.variant] || {};
        const isUp = fb.rating === 1;
        const isDown = fb.rating === -1;
        const isSelected = fb.selected === true;

        html += `
          <div class="variant-card">
            <img src="${esc(filePath)}" alt="${esc(img.variant)}"
                 onclick="window.open('${esc(filePath)}', '_blank')" loading="lazy">
            <div class="variant-info">
              <div class="variant-label">${esc(img.variant)}</div>
              ${scoreHtml}
              <div class="feedback-actions">
                <button class="btn-feedback${isUp ? " active-up" : ""}" onclick="window.submitFeedback('${esc(detail.job_id)}', '${esc(img.variant)}', ${isUp ? 0 : 1}, false)" title="Bra bild">&#128077;</button>
                <button class="btn-feedback${isDown ? " active-down" : ""}" onclick="window.submitFeedback('${esc(detail.job_id)}', '${esc(img.variant)}', ${isDown ? 0 : -1}, false)" title="Dålig bild">&#128078;</button>
                <button class="btn-select${isSelected ? " active" : ""}" onclick="window.submitFeedback('${esc(detail.job_id)}', '${esc(img.variant)}', ${fb.rating || 0}, ${!isSelected})">${isSelected ? "Vald ✓" : "Använd denna"}</button>
              </div>
              <div class="variant-actions">
                ${filePath ? `<a class="btn-download" href="${esc(filePath)}" download>Ladda ner</a>` : ""}
                <button class="btn-refine" onclick="window.showRefineForm('${esc(detail.job_id)}', '${esc(img.variant)}', this)">Refinea</button>
              </div>
              <div class="refine-form" id="refine-form-${esc(detail.job_id)}-${esc(img.variant)}" style="display:none">
                <input type="text" class="refine-input" placeholder="Instruktioner (valfritt)..."
                       id="refine-input-${esc(detail.job_id)}-${esc(img.variant)}">
                <div class="refine-form-actions">
                  <button class="btn-refine-submit" onclick="window.submitRefine('${esc(detail.job_id)}', '${esc(img.variant)}')">Skicka</button>
                  <button class="btn-refine-cancel" onclick="window.cancelRefine('${esc(detail.job_id)}', '${esc(img.variant)}')">Avbryt</button>
                </div>
              </div>
              ${refinementsHtml}
            </div>
          </div>`;
      }
      html += "</div>";
    } else if (detail.stage !== "complete" && detail.stage !== "failed") {
      html += '<div class="loading-spinner">Genererar bilder...</div>';
    } else {
      html += '<div class="loading-spinner">Inga bilder genererades.</div>';
    }

    // Summary
    if (detail.summary) {
      html += `<div class="research-detail" style="margin-top:0.75rem">
        <strong>Sammanfattning:</strong> ${esc(detail.summary)}
      </div>`;
    }

    $container.innerHTML = html;
  }

  // ── Search & Sort ──────────────────────────────────────

  async function loadJobs() {
    const search = $searchInput.value.trim();
    const sort = $sortSelect.value;
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (sort) params.set("sort", sort);

    try {
      const res = await fetch("/api/jobs?" + params.toString());
      jobList = await res.json();
      renderGallery();
    } catch (err) {
      console.error("Failed to load jobs:", err);
    }
  }

  $searchInput.addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(loadJobs, 350);
  });

  $sortSelect.addEventListener("change", loadJobs);

  // ── Form: File Upload ──────────────────────────────────

  $fileBrowse.addEventListener("click", (e) => {
    e.preventDefault();
    $fileInput.click();
  });

  $dropZone.addEventListener("click", () => $fileInput.click());

  $dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    $dropZone.classList.add("dragover");
  });

  $dropZone.addEventListener("dragleave", () => {
    $dropZone.classList.remove("dragover");
  });

  $dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    $dropZone.classList.remove("dragover");
    addFiles(e.dataTransfer.files);
  });

  $fileInput.addEventListener("change", () => {
    addFiles($fileInput.files);
    $fileInput.value = "";
  });

  function addFiles(fileList) {
    for (const f of fileList) {
      if (f.type.startsWith("image/")) {
        uploadedFiles.push(f);
      }
    }
    renderFilePreviews();
  }

  function renderFilePreviews() {
    $filePreviews.innerHTML = uploadedFiles
      .map((f, i) => {
        const url = URL.createObjectURL(f);
        return `
          <div class="file-preview">
            <img src="${url}" alt="${esc(f.name)}">
            <button type="button" class="remove-file" onclick="removeFile(${i})">×</button>
          </div>`;
      })
      .join("");
  }

  window.removeFile = function (index) {
    uploadedFiles.splice(index, 1);
    renderFilePreviews();
  };

  // ── Form: Submit ───────────────────────────────────────

  $form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const prompt = $prompt.value.trim();
    if (!prompt) return;

    $submitBtn.disabled = true;
    $submitBtn.textContent = "Skickar...";

    const formData = new FormData();
    formData.append("prompt", prompt);
    formData.append("aspect_ratio", $aspect.value);
    formData.append("resolution", $resolution.value);
    for (const f of uploadedFiles) {
      formData.append("files", f);
    }

    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        alert("Fel: " + (err.detail || err.error || "Okänt fel"));
        return;
      }

      const { job_id } = await res.json();
      currentJobId = job_id;

      // Clear form
      $prompt.value = "";
      uploadedFiles = [];
      renderFilePreviews();

      // Show pipeline cards
      agentLog = [];
      showPipelineCards();
      renderPipeline("queued");
      renderAgentLog();
    } catch (err) {
      alert("Nätverksfel: " + err.message);
    } finally {
      $submitBtn.disabled = false;
      $submitBtn.textContent = "Generera 6 varianter";
    }
  });

  // ── Refine ─────────────────────────────────────────────

  window.showRefineForm = function (jobId, variant, btn) {
    const formId = "refine-form-" + jobId + "-" + variant;
    const $form = document.getElementById(formId);
    if ($form) {
      $form.style.display = "block";
      const $input = document.getElementById("refine-input-" + jobId + "-" + variant);
      if ($input) $input.focus();
    }
  };

  window.cancelRefine = function (jobId, variant) {
    const formId = "refine-form-" + jobId + "-" + variant;
    const $form = document.getElementById(formId);
    if ($form) $form.style.display = "none";
  };

  window.submitRefine = async function (jobId, variant) {
    const inputId = "refine-input-" + jobId + "-" + variant;
    const $input = document.getElementById(inputId);
    const instruction = $input ? $input.value.trim() : "";

    const formId = "refine-form-" + jobId + "-" + variant;
    const $form = document.getElementById(formId);

    // Disable form while submitting
    const $submitBtn = $form ? $form.querySelector(".btn-refine-submit") : null;
    if ($submitBtn) {
      $submitBtn.disabled = true;
      $submitBtn.textContent = "Skickar...";
    }

    try {
      const formData = new FormData();
      formData.append("job_id", jobId);
      formData.append("variant", variant);
      formData.append("instruction", instruction);

      const res = await fetch("/api/refine", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        alert("Fel: " + (err.error || "Okänt fel"));
        return;
      }

      // Hide form and show progress in agent log
      if ($form) $form.style.display = "none";
      if ($input) $input.value = "";

      agentLog.push({
        agent: "generator",
        message: "Förfinar " + variant + "...",
        time: new Date().toLocaleTimeString("sv-SE"),
      });
      showPipelineCards();
      renderAgentLog();
    } catch (err) {
      alert("Nätverksfel: " + err.message);
    } finally {
      if ($submitBtn) {
        $submitBtn.disabled = false;
        $submitBtn.textContent = "Skicka";
      }
    }
  };

  // ── Feedback ─────────────────────────────────────────────

  window.submitFeedback = async function (jobId, variant, rating, selected) {
    try {
      const formData = new FormData();
      formData.append("variant", variant);
      formData.append("rating", rating);
      formData.append("selected", selected);

      const res = await fetch("/api/jobs/" + jobId + "/feedback", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        console.error("Feedback error:", err);
        return;
      }

      // Invalidate cache and re-render
      delete jobDetailCache[jobId];
      if (expandedJobId === jobId) {
        fetchAndRenderDetail(jobId, true);
      }
    } catch (err) {
      console.error("Feedback network error:", err);
    }
  };

  // ── Helpers ────────────────────────────────────────────

  function esc(str) {
    const el = document.createElement("span");
    el.textContent = str || "";
    return el.innerHTML;
  }

  // ── Init ───────────────────────────────────────────────

  async function init() {
    connect();
    await loadJobs();

    // Show pipeline for any active (in-progress) job after page reload
    const activeJob = jobList.find(
      (j) => j.stage !== "complete" && j.stage !== "failed"
    );
    if (activeJob) {
      currentJobId = activeJob.job_id;
      showPipelineCards();
      renderPipeline(activeJob.stage);
      showActivity(STAGE_LABELS[activeJob.stage] || "Arbetar...");
    }
  }

  init();
})();
