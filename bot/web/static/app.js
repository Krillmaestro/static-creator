/* Banana Squad Dashboard — WebSocket client + DOM updates */

(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────
  let ws = null;
  let currentJobId = null;
  let jobs = {};
  let agentLog = [];

  // ── DOM refs ───────────────────────────────────────────
  const $statusDot = document.getElementById("status-dot");
  const $statusText = document.getElementById("status-text");
  const $stages = document.getElementById("pipeline-stages");
  const $agentLog = document.getElementById("agent-log");
  const $imageGrid = document.getElementById("image-grid");
  const $jobList = document.getElementById("job-list");
  const $jobTitle = document.getElementById("job-title");

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
        const event = JSON.parse(e.data);
        handleEvent(event);
      } catch (err) {
        console.error("WS parse error:", err);
      }
    };
  }

  // ── Event handler ──────────────────────────────────────

  function handleEvent(event) {
    const { type, job_id, data, timestamp } = event;

    // Track job
    if (!jobs[job_id]) {
      jobs[job_id] = {
        id: job_id,
        stage: "queued",
        prompt: data.prompt || "",
        images: [],
        scores: [],
        agentLog: [],
      };
    }
    const job = jobs[job_id];

    switch (type) {
      case "job_started":
        job.prompt = data.prompt || job.prompt;
        job.stage = "research";
        currentJobId = job_id;
        renderJobList();
        renderPipeline(job);
        clearImages();
        $jobTitle.textContent = job.prompt || "Nytt jobb";
        break;

      case "stage_changed":
        job.stage = data.stage;
        renderPipeline(job);
        break;

      case "agent_message":
        const logEntry = {
          agent: data.agent,
          message: data.message,
          time: new Date(timestamp).toLocaleTimeString("sv-SE"),
        };
        agentLog.push(logEntry);
        job.agentLog.push(logEntry);
        renderAgentLog();
        break;

      case "progress":
        addAgentLogEntry({
          agent: data.agent,
          message: data.message,
          time: new Date(timestamp).toLocaleTimeString("sv-SE"),
        });
        break;

      case "image_generated":
        job.images.push({
          variant: data.variant,
          file_path: data.file_path,
          index: data.index,
        });
        renderImages(job);
        break;

      case "variant_scored":
        job.scores.push({
          variant: data.variant,
          scores: data.scores,
          rank: data.rank,
          review: data.review,
        });
        renderImages(job);
        break;

      case "job_completed":
        job.stage = "complete";
        renderPipeline(job);
        renderJobList();
        break;

      case "job_failed":
        job.stage = "failed";
        renderPipeline(job);
        renderJobList();
        addAgentLogEntry({
          agent: "system",
          message: `Fel: ${data.error}`,
          time: new Date(timestamp).toLocaleTimeString("sv-SE"),
        });
        break;
    }
  }

  // ── Renderers ──────────────────────────────────────────

  const STAGES = [
    { key: "research", icon: "🔍", label: "Analys" },
    { key: "prompt_crafting", icon: "✏️", label: "Promptdesign" },
    { key: "generating", icon: "🎨", label: "Bildgenerering" },
    { key: "evaluating", icon: "⭐", label: "Utvärdering" },
  ];

  function renderPipeline(job) {
    const stageIndex = STAGES.findIndex((s) => s.key === job.stage);
    const isFailed = job.stage === "failed";
    const isComplete = job.stage === "complete";

    $stages.innerHTML = STAGES.map((s, i) => {
      let iconClass = "pending";
      if (isFailed && i === stageIndex) iconClass = "failed";
      else if (isComplete || i < stageIndex) iconClass = "done";
      else if (i === stageIndex) iconClass = "active";

      const labelClass = i === stageIndex && !isComplete ? "active" : "";

      return `
        <div class="stage">
          <div class="stage-icon ${iconClass}">${s.icon}</div>
          <span class="stage-label ${labelClass}">${s.label}</span>
        </div>`;
    }).join("");
  }

  function renderAgentLog() {
    const entries = agentLog.slice(-30);
    $agentLog.innerHTML = entries
      .map(
        (e) => `
      <div class="log-entry">
        <span class="log-agent">${escapeHtml(e.agent)}</span>
        <span>${escapeHtml(e.message)}</span>
        <span class="log-time">${e.time}</span>
      </div>`
      )
      .join("");
    $agentLog.scrollTop = $agentLog.scrollHeight;
  }

  function addAgentLogEntry(entry) {
    agentLog.push(entry);
    renderAgentLog();
  }

  function renderImages(job) {
    if (!job.images.length) {
      $imageGrid.innerHTML = `
        <div class="empty-state">
          <div class="emoji">🎨</div>
          <p>Bilder visas här när de genereras...</p>
        </div>`;
      return;
    }

    $imageGrid.innerHTML = job.images
      .map((img) => {
        const scoreData = job.scores.find((s) => s.variant === img.variant);
        const filePath = img.file_path.includes("/outputs/")
          ? "/outputs/" + img.file_path.split("/outputs/")[1]
          : "/outputs/" + img.file_path;

        let scoreHtml = "";
        if (scoreData) {
          const dims = ["faithfulness", "conciseness", "readability", "aesthetics"];
          scoreHtml = dims
            .map(
              (d) => `
            <div class="score-bar-container">
              <span>${d.charAt(0).toUpperCase() + d.slice(1, 5)}</span>
              <div class="score-bar">
                <div class="score-bar-fill" style="width: ${(scoreData.scores[d] / 10) * 100}%"></div>
              </div>
              <span>${scoreData.scores[d].toFixed(1)}</span>
            </div>`
            )
            .join("");

          const rankClass = scoreData.rank <= 3 ? `rank-${scoreData.rank}` : "";
          const medal = { 1: "🥇", 2: "🥈", 3: "🥉" }[scoreData.rank] || `#${scoreData.rank}`;
          scoreHtml += `<div class="rank-badge ${rankClass}">${medal} ${scoreData.scores.total.toFixed(1)}/40</div>`;
        }

        return `
          <div class="image-card">
            <img src="${escapeHtml(filePath)}" alt="${escapeHtml(img.variant)}"
                 onclick="window.open('${escapeHtml(filePath)}', '_blank')" loading="lazy">
            <div class="image-info">
              <div class="variant-label">${escapeHtml(img.variant)}</div>
              ${scoreHtml}
            </div>
          </div>`;
      })
      .join("");
  }

  function clearImages() {
    agentLog = [];
    $agentLog.innerHTML = "";
    $imageGrid.innerHTML = `
      <div class="empty-state">
        <div class="emoji">🎨</div>
        <p>Bilder visas här när de genereras...</p>
      </div>`;
  }

  function renderJobList() {
    const jobArr = Object.values(jobs).reverse();
    if (!jobArr.length) {
      $jobList.innerHTML = `
        <div class="empty-state">
          <div class="emoji">📋</div>
          <p>Inga jobb ännu. Skicka en beskrivning via Telegram!</p>
        </div>`;
      return;
    }

    $jobList.innerHTML = jobArr
      .map((j) => {
        const active = j.id === currentJobId ? "active" : "";
        let statusClass = "running";
        let statusLabel = "Arbetar...";
        if (j.stage === "complete") {
          statusClass = "complete";
          statusLabel = "Klar";
        } else if (j.stage === "failed") {
          statusClass = "failed";
          statusLabel = "Misslyckades";
        }

        return `
          <div class="job-item ${active}" onclick="selectJob('${j.id}')">
            <span class="job-prompt">${escapeHtml(j.prompt || j.id)}</span>
            <span class="job-status ${statusClass}">${statusLabel}</span>
          </div>`;
      })
      .join("");
  }

  // ── Helpers ────────────────────────────────────────────

  function escapeHtml(str) {
    const el = document.createElement("span");
    el.textContent = str || "";
    return el.innerHTML;
  }

  // ── Public API ─────────────────────────────────────────

  window.selectJob = function (jobId) {
    currentJobId = jobId;
    const job = jobs[jobId];
    if (!job) return;

    agentLog = [...job.agentLog];
    $jobTitle.textContent = job.prompt || jobId;
    renderPipeline(job);
    renderAgentLog();
    renderImages(job);
    renderJobList();
  };

  // ── Init ───────────────────────────────────────────────

  async function init() {
    connect();

    // Load existing jobs
    try {
      const res = await fetch("/api/jobs");
      const data = await res.json();
      for (const j of data) {
        jobs[j.job_id] = {
          id: j.job_id,
          stage: j.stage,
          prompt: j.prompt,
          images: [],
          scores: [],
          agentLog: [],
        };
      }
      renderJobList();
    } catch (err) {
      console.error("Failed to load jobs:", err);
    }

    // Reset pipeline view
    $stages.innerHTML = STAGES.map(
      (s) => `
      <div class="stage">
        <div class="stage-icon pending">${s.icon}</div>
        <span class="stage-label">${s.label}</span>
      </div>`
    ).join("");
  }

  init();
})();
