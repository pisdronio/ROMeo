/* ROMeo app bootstrap */

const VIEWS = {
  library: renderLibrary,
  scan:    renderScan,
  export:  renderExport,
  trash:   renderTrash,
  dats:    renderDats,
};

let currentView = "library";

function navigate(view) {
  document.querySelectorAll(".nav-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach(v => {
    v.classList.toggle("active", v.id === `view-${view}`);
  });
  currentView = view;
  VIEWS[view]();
}

async function refreshStats() {
  try {
    const s = await API.get("/api/catalog/stats");
    document.getElementById("st-catalog").textContent   = (s.total || 0).toLocaleString();
    document.getElementById("st-collected").textContent = (s.collected || 0).toLocaleString();
    document.getElementById("st-missing").textContent   = (s.missing || 0).toLocaleString();
  } catch {}
}

document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => navigate(btn.dataset.view));
});

// ── Global scan progress indicator ───────────────────────────────────────────

let _globalScanTimer = null;

async function pollGlobalScan() {
  const p     = await API.get("/api/scan/progress");
  const wrap  = document.getElementById("sidebar-scan-status");
  const label = document.getElementById("sss-label");
  const bar   = document.getElementById("sss-bar");

  if (p.status === "scanning") {
    wrap.style.display = "block";
    const pct = p.total ? Math.round(p.current / p.total * 100) : 0;
    bar.style.width = pct + "%";
    label.textContent = p.file
      ? `Scanning… ${p.current.toLocaleString()} / ${p.total.toLocaleString()}`
      : "Scanning…";
  } else if (p.status === "done") {
    wrap.style.display = "block";
    bar.style.width = "100%";
    label.textContent = `✓ ${(p.matched || 0).toLocaleString()} matched`;
    clearInterval(_globalScanTimer);
    _globalScanTimer = null;
    refreshStats();
    setTimeout(() => { wrap.style.display = "none"; }, 4000);
  } else if (p.status === "error") {
    wrap.style.display = "block";
    label.textContent = "Scan error";
    bar.style.background = "var(--red)";
    clearInterval(_globalScanTimer);
    _globalScanTimer = null;
    setTimeout(() => { wrap.style.display = "none"; bar.style.background = ""; }, 5000);
  } else {
    wrap.style.display = "none";
    clearInterval(_globalScanTimer);
    _globalScanTimer = null;
  }
}

function startGlobalScanPoll() {
  if (_globalScanTimer) return;
  _globalScanTimer = setInterval(pollGlobalScan, 700);
  pollGlobalScan();
}

// Check on load in case a scan is already running
pollGlobalScan();

// ── Light / dark theme toggle ─────────────────────────────────────────────────

(function () {
  const btn = document.getElementById("theme-toggle");
  const apply = (light) => {
    document.body.classList.toggle("light", light);
    btn.textContent = light ? "◑" : "◐";
    btn.title = light ? "Switch to dark" : "Switch to light";
    localStorage.setItem("romeo-theme", light ? "light" : "dark");
  };
  apply(localStorage.getItem("romeo-theme") === "light");
  btn.addEventListener("click", () => apply(!document.body.classList.contains("light")));
})();

navigate("library");
refreshStats();
setInterval(refreshStats, 10000);
