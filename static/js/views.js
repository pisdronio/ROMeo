/* View renderers */

// ── Console icon helper ───────────────────────────────────────────────────────

function conIcon(console_, cls = "con-icon") {
  const url = `/static/icons/${encodeURIComponent(console_)}.png`;
  return `<img class="${cls}" src="${url}" alt="${esc(console_)}" onerror="this.style.display='none'">`;
}

// ── Library / Pokedex view ────────────────────────────────────────────────────

let libState = { search: "", console: "all", show: "all", letter: "A" };
let _allGroups = [];
const LETTERS = ["#", ...Array.from("ABCDEFGHIJKLMNOPQRSTUVWXYZ")];

async function renderLibrary() {
  const view = document.getElementById("view-library");

  const stats = await API.get("/api/catalog/stats");
  const total     = stats.total || 0;
  const collected = stats.collected || 0;
  const missing   = stats.missing || 0;
  const pct       = total > 0 ? Math.round(collected / total * 100) : 0;

  const consoleOpts = Object.entries(stats.consoles || {}).map(([c, info]) =>
    `<option value="${esc(c)}">${esc(c)} (${info.have}/${info.total})</option>`
  ).join("");

  view.innerHTML = `
    <div class="view-header">
      <div class="view-title">Library <span>◈</span></div>
    </div>

    <div class="catalog-banner">
      <div class="catalog-banner-numbers">
        <span class="catalog-have">${collected.toLocaleString()}</span>
        <span class="catalog-sep"> / ${total.toLocaleString()} games</span>
        <span class="catalog-pct">${pct}%</span>
      </div>
      <div class="progress-bar-bg" style="height:6px;margin-top:6px;">
        <div class="progress-bar-fill" style="width:${pct}%"></div>
      </div>
    </div>

    <div class="toolbar">
      <input class="search-box" id="lib-search" placeholder="Search games…" value="${esc(libState.search)}">
      <select class="filter-sel" id="lib-console">
        <option value="all">All consoles</option>
        ${consoleOpts}
      </select>
      <div class="show-tabs" id="lib-show-tabs">
        <button class="show-tab ${libState.show==='all'?'active':''}" data-show="all">All</button>
        <button class="show-tab ${libState.show==='collected'?'active':''}" data-show="collected">Collected</button>
        <button class="show-tab ${libState.show==='missing'?'active':''}" data-show="missing">Missing</button>
      </div>
    </div>

    <div class="letter-bar" id="letter-bar"></div>
    <div id="library-list">
      <div class="empty-state"><div class="empty-state-text muted">Loading…</div></div>
    </div>
  `;

  const sel = document.getElementById("lib-console");
  sel.value = libState.console;

  document.getElementById("lib-search").addEventListener("input", e => {
    libState.search = e.target.value;
    if (libState.search) libState.letter = "";   // search overrides letter
    else if (!libState.letter) libState.letter = "A";
    loadGroups();
  });
  sel.addEventListener("change", e => {
    libState.console = e.target.value;
    libState.letter  = "all";
    loadGroups();
  });
  document.getElementById("lib-show-tabs").addEventListener("click", e => {
    const btn = e.target.closest("[data-show]");
    if (!btn) return;
    libState.show   = btn.dataset.show;
    libState.letter = "all";
    document.querySelectorAll(".show-tab").forEach(b => b.classList.toggle("active", b === btn));
    loadGroups();
  });

  loadGroups();
}

async function loadGroups() {
  const list = document.getElementById("library-list");
  list.innerHTML = `<div class="empty-state"><div class="empty-state-text muted">Loading…</div></div>`;

  const params = new URLSearchParams({ q: libState.search, show: libState.show });
  if (libState.console !== "all") params.set("console", libState.console);
  if (libState.letter && libState.letter !== "all") params.set("letter", libState.letter);

  const data = await API.get("/api/catalog/groups?" + params);
  _allGroups  = data.groups || [];

  renderLetterBar();

  if (!_allGroups.length) {
    const hint = libState.show === "all"
      ? "No games found. Load DATs in <strong>DAT Files</strong> first."
      : `No games with status "${libState.show}" for this filter.`;
    list.innerHTML = `<div class="empty-state"><div class="empty-state-icon">◎</div><div class="empty-state-text">${hint}</div></div>`;
    return;
  }

  renderFilteredGroups();
}

function renderFilteredGroups() {
  const list = document.getElementById("library-list");

  if (!_allGroups.length) {
    list.innerHTML = `<div class="empty-state"><div class="empty-state-text muted">No games under this letter</div></div>`;
    return;
  }

  // Server already filtered by letter/show/search — render directly
  list.innerHTML = _allGroups.map(g => renderGroupCard(g)).join("");
  list.querySelectorAll(".group-header").forEach(h => {
    h.addEventListener("click", () => h.closest(".group-card").classList.toggle("expanded"));
  });
}

function renderLetterBar() {
  const bar = document.getElementById("letter-bar");
  if (!bar) return;
  bar.innerHTML = LETTERS.map(l => {
    const active = libState.letter === l;
    return `<button class="letter-btn ${active ? "active" : ""}" data-letter="${l}">${l}</button>`;
  }).join("");
  bar.querySelectorAll(".letter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      libState.letter = btn.dataset.letter;
      libState.search = "";
      const searchEl = document.getElementById("lib-search");
      if (searchEl) searchEl.value = "";
      loadGroups();
    });
  });
}

function renderGroupCard(g) {
  const { title, console: con, variants, collected_count, total_count } = g;
  const allHave  = collected_count === total_count;
  const noneHave = collected_count === 0;
  const statusClass = allHave ? "complete" : noneHave ? "missing" : "partial";
  const dot         = allHave ? "●" : noneHave ? "○" : "◑";
  const dotColor    = allHave ? "var(--aqua)" : noneHave ? "var(--text2)" : "var(--orange)";

  // Compact variant pills — one per region, merged
  const regionMap = {};
  for (const v of variants) {
    const r = v.region || '?';
    if (!regionMap[r]) regionMap[r] = { collected: 0, total: 0, hasBad: false };
    regionMap[r].total++;
    if (v.collected) regionMap[r].collected++;
    if (v.bad_tags)  regionMap[r].hasBad = true;
  }
  const pills = Object.entries(regionMap).map(([r, info]) => {
    const has = info.collected > 0;
    const count = info.total > 1 ? ` ×${info.total}` : '';
    return `
    <span class="variant-pill ${has ? 'has' : ''}" title="${info.collected}/${info.total} ${r}">
      <span class="vpill-dot">${has ? '●' : '○'}</span>
      <span class="vpill-region">${esc(r)}${count}</span>
      ${info.hasBad ? `<span class="vpill-warn">⚠</span>` : ''}
    </span>`;
  }).join("");

  // Detail rows in body
  const rows = variants.map(v => {
    const pathEl = v.rom_path
      ? `<span class="vrow-path">${esc(v.rom_path)}</span>`
      : `<span class="vrow-path missing">not in collection</span>`;
    const warn = v.bad_tags ? `<span class="badge issues" style="font-size:9px;margin-left:4px;">⚠ ${esc(v.bad_tags)}</span>` : '';
    return `
      <div class="variant-row ${v.collected ? 'has' : ''}">
        <span class="vrow-dot" style="color:${v.collected ? 'var(--aqua)' : 'var(--text2)'}">${v.collected ? '●' : '○'}</span>
        <span class="vrow-name">${esc(v.name)}</span>
        ${warn}
        ${pathEl}
      </div>`;
  }).join("");

  const countBadge = total_count > 1
    ? `<span class="badge ${allHave ? 'ok' : 'count'}" style="margin-left:auto;">${collected_count}/${total_count}</span>`
    : '';

  return `
    <div class="group-card ${statusClass}">
      <div class="group-header">
        <span class="gcard-dot" style="color:${dotColor};">${dot}</span>
        <span class="group-title">${esc(title)}</span>
        <span class="group-console">${esc(con)}</span>
        <div class="variant-pills">${pills}</div>
        ${countBadge}
        <span class="group-chevron">▶</span>
      </div>
      <div class="group-body">${rows}</div>
    </div>`;
}


// ── Scan view ─────────────────────────────────────────────────────────────────

let scanTimer = null;

function renderScan() {
  const view = document.getElementById("view-scan");
  view.innerHTML = `
    <div class="view-header">
      <div class="view-title">Scan <span>⟳</span></div>
    </div>
    <div class="scan-form">
      <div class="form-group">
        <label class="form-label">ROM Folder Path</label>
        <div style="display:flex;gap:8px;">
          <input class="form-input" id="scan-path" placeholder="/Volumes/ROMs or ~/Desktop/roms" style="flex:1;">
          <button class="btn" id="btn-browse">Browse…</button>
        </div>
        <div class="form-hint">ROMeo will scan all ROM files and match them against your loaded DAT catalog. Load DATs first in the <strong>DAT Files</strong> tab.</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <button class="btn primary" id="btn-scan">Start Scan</button>
        <select class="filter-sel" id="clear-console-sel" style="min-width:140px;">
          <option value="">All consoles</option>
        </select>
        <button class="btn danger" id="btn-clear-catalog">Clear Catalog</button>
      </div>
      <div class="progress-wrap" id="scan-progress-wrap">
        <div class="progress-bar-bg"><div class="progress-bar-fill" id="scan-bar"></div></div>
        <div class="progress-label" id="scan-label">Scanning…</div>
      </div>
      <div id="scan-result" class="mt16"></div>
    </div>
    <div style="padding:0 24px 24px;">
      <div class="form-label" style="margin-bottom:12px;">Recent Scans</div>
      <div id="recent-scans"><span class="muted">Loading…</span></div>
    </div>
  `;

  document.getElementById("btn-scan").addEventListener("click", startScan);

  document.getElementById("btn-browse").addEventListener("click", async () => {
    const btn = document.getElementById("btn-browse");
    btn.disabled = true; btn.textContent = "Picking…";
    const res = await API.get("/api/browse");
    btn.disabled = false; btn.textContent = "Browse…";
    if (res.ok && res.path) document.getElementById("scan-path").value = res.path;
  });

  // Populate clear console dropdown
  API.get("/api/catalog/stats").then(stats => {
    const sel = document.getElementById("clear-console-sel");
    Object.keys(stats.consoles || {}).forEach(c => {
      const o = document.createElement("option");
      o.value = c; o.textContent = `${c} (${stats.consoles[c].have}/${stats.consoles[c].total})`;
      sel.appendChild(o);
    });
  });

  document.getElementById("btn-clear-catalog").addEventListener("click", async () => {
    const sel      = document.getElementById("clear-console-sel");
    const console_ = sel.value;
    const label    = console_ ? `${console_} catalog` : "entire catalog";
    if (!confirm(`Clear ${label}? You can re-import DATs and re-scan.`)) return;
    await API.post("/api/catalog/clear", console_ ? { console: console_ } : {});
    refreshStats();
    toast(`${console_ || "Catalog"} cleared`, "ok");
  });

  loadRecentScans();
}

async function startScan() {
  const path = document.getElementById("scan-path").value.trim();
  if (!path) { toast("Please enter a path", "err"); return; }

  const res = await API.post("/api/scan", { path });
  if (!res.ok) { toast(res.error, "err"); return; }

  document.getElementById("scan-progress-wrap").classList.add("visible");
  document.getElementById("btn-scan").disabled = true;
  toast("Scan started", "ok");

  clearInterval(scanTimer);
  scanTimer = setInterval(pollScan, 600);
  startGlobalScanPoll();
}

async function pollScan() {
  const p   = await API.get("/api/scan/progress");
  const bar   = document.getElementById("scan-bar");
  const label = document.getElementById("scan-label");

  if (p.total > 0) {
    const pct = Math.round(p.current / p.total * 100);
    bar.style.width = pct + "%";
    label.textContent = `${pct}% · ${p.current}/${p.total} files · ${p.file}`;
  } else {
    label.textContent = `Scanning… ${p.file}`;
  }

  if (p.status === "done") {
    clearInterval(scanTimer);
    bar.style.width = "100%";
    const matched = p.matched || 0;
    label.textContent = `Done — ${matched} matched / ${p.total} files`;
    document.getElementById("btn-scan").disabled = false;
    document.getElementById("scan-result").innerHTML = `
      <div class="badge ok" style="padding:8px 14px;font-size:13px;">
        ✓ ${matched.toLocaleString()} ROMs added to collection
        ${p.total - matched > 0 ? `<span class="muted" style="margin-left:8px;">(${(p.total-matched).toLocaleString()} not in any DAT)</span>` : ''}
      </div>`;
    refreshStats();
    loadRecentScans();
    toast(`${matched} ROMs matched`, "ok");
  }
  if (p.status === "error") {
    clearInterval(scanTimer);
    label.textContent = "Error: " + p.file;
    document.getElementById("btn-scan").disabled = false;
    toast("Scan error: " + p.file, "err");
  }
}

async function loadRecentScans() {
  const scans = await API.get("/api/scans");
  const el    = document.getElementById("recent-scans");
  if (!scans.length) { el.innerHTML = `<span class="muted">No scans yet</span>`; return; }
  el.innerHTML = scans.map(s => `
    <div style="padding:8px 0;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;">
      <div>
        <div class="mono" style="font-size:12px;">${esc(s.root_path)}</div>
        <div class="muted" style="font-size:11px;margin-top:2px;">
          ${(s.matched||0)} matched / ${s.total_files} files · ${s.started_at?.slice(0,16)}
        </div>
      </div>
      <span class="badge ${s.status==='done'?'ok':'issues'}">${s.status}</span>
    </div>
  `).join("");
}


// ── Export view ───────────────────────────────────────────────────────────────

const EXPORT_PROFILES = [
  { id: "miyoo",      name: "Miyoo Mini",  desc: "Roms/SFC/, Roms/FC/…"   },
  { id: "miyoo_plus", name: "Miyoo Mini+", desc: "Same SD structure"       },
  { id: "anbernic",   name: "Anbernic",    desc: "RG35XX / RG40XX / RG28XX"},
  { id: "retropie",   name: "RetroPie",    desc: "roms/snes/, roms/nes/…" },
  { id: "batocera",   name: "Batocera",    desc: "roms/ structure"         },
  { id: "by_console", name: "By Console",  desc: "SNES/, NES/, GBA/…"     },
  { id: "flat",       name: "Flat",        desc: "All in one folder"       },
];

const SD_SIZES = [
  { gb: 0,   label: "No limit" },
  { gb: 4,   label: "4 GB"    },
  { gb: 8,   label: "8 GB"    },
  { gb: 16,  label: "16 GB"   },
  { gb: 32,  label: "32 GB"   },
  { gb: 64,  label: "64 GB"   },
  { gb: 128, label: "128 GB"  },
  { gb: 256, label: "256 GB"  },
  { gb: 512, label: "512 GB"  },
];

const MOODS = [
  { id: "curator",
    name: "Curator",
    desc: "Best version per game, no bad dumps",
    icon: "✦",
    one_per_game: true,  skip_bad_tags: true  },
  { id: "collector",
    name: "Collector",
    desc: "All collected ROMs, every region",
    icon: "▣",
    one_per_game: false, skip_bad_tags: false },
  { id: "archivist",
    name: "Archivist",
    desc: "Everything including Beta & Proto",
    icon: "◎",
    one_per_game: false, skip_bad_tags: false },
];

let exportState = {
  profile:       "miyoo",
  capacity_gb:   0,
  one_per_game:  true,
  skip_bad_tags: true,
  mood:          "curator",
  consoles:      null,   // null = all; array = selected subset
};

let _exportCatalogConsoles = {};   // { NES: {have, total}, ... }

async function renderExport() {
  const view = document.getElementById("view-export");
  view.innerHTML = `
    <div class="view-header">
      <div class="view-title">Export <span>↗</span></div>
    </div>
    <div class="export-layout">

      <!-- ── Left: settings ── -->
      <div class="export-settings">

        <div class="form-group">
          <label class="form-label">Output Folder</label>
          <div style="display:flex;gap:8px;">
            <input class="form-input" id="export-path" placeholder="/Volumes/SDCard or ~/Desktop/roms" style="flex:1;">
            <button class="btn" id="btn-browse-export">Browse…</button>
          </div>
          <div class="form-hint">ROMs are copied — originals are never moved or deleted.</div>
        </div>

        <div class="form-group">
          <label class="form-label">Device / Format</label>
          <div class="profile-grid">
            ${EXPORT_PROFILES.map(p => `
              <div class="profile-card ${p.id === exportState.profile ? 'selected' : ''}" data-profile="${p.id}">
                <div class="profile-name">${esc(p.name)}</div>
                <div class="profile-desc">${esc(p.desc)}</div>
              </div>`).join("")}
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">SD Card Capacity</label>
          <div class="sd-size-grid">
            ${SD_SIZES.map(s => `
              <button class="sd-btn ${s.gb === exportState.capacity_gb ? 'active' : ''}" data-gb="${s.gb}">
                ${esc(s.label)}
              </button>`).join("")}
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Mood</label>
          <div class="mood-grid">
            ${MOODS.map(m => `
              <div class="mood-card ${m.id === exportState.mood ? 'selected' : ''}" data-mood="${m.id}">
                <span class="mood-icon">${m.icon}</span>
                <div>
                  <div class="mood-name">${esc(m.name)}</div>
                  <div class="mood-desc">${esc(m.desc)}</div>
                </div>
              </div>`).join("")}
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">ROM Options</label>
          <div class="export-option">
            <label class="option-toggle">
              <input type="checkbox" id="opt-one-per-game" ${exportState.one_per_game ? 'checked' : ''}>
              <span class="option-label">1 game / 1 ROM — best version only</span>
            </label>
            <div class="form-hint" style="margin:2px 0 0 24px;">USA › World › Europe › Japan, newest revision first.</div>
          </div>
          <div class="export-option" style="margin-top:8px;">
            <label class="option-toggle">
              <input type="checkbox" id="opt-skip-bad" ${exportState.skip_bad_tags ? 'checked' : ''}>
              <span class="option-label">Skip Beta / Proto / Demo / Hack</span>
            </label>
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Consoles</label>
          <div id="console-checklist" class="console-checklist">
            <span class="muted" style="font-size:12px;">Loading…</span>
          </div>
        </div>

      </div>

      <!-- ── Right: plan + action ── -->
      <div class="export-sidebar">
        <div class="export-preview" id="export-preview">
          <div class="preview-title">Export Plan</div>
          <div id="preview-body" class="muted" style="font-size:12px;">Press Refresh to calculate</div>
        </div>

        <div style="display:flex;gap:6px;margin-top:12px;">
          <button class="btn" id="btn-preview" style="flex:1;">⟳ Refresh</button>
          <button class="btn" id="btn-autofit" style="flex:1;" title="Auto-select consoles that fit the SD capacity">⚡ Auto-fit</button>
        </div>
        <button class="btn primary" id="btn-export" style="width:100%;margin-top:8px;padding:12px;">
          Export Collection
        </button>
        <div id="export-result" class="mt16"></div>
      </div>

    </div>
  `;

  // Device profile
  view.querySelectorAll(".profile-card").forEach(card => {
    card.addEventListener("click", () => {
      exportState.profile = card.dataset.profile;
      view.querySelectorAll(".profile-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
    });
  });

  // SD size
  view.querySelectorAll(".sd-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      exportState.capacity_gb = parseInt(btn.dataset.gb);
      view.querySelectorAll(".sd-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
    });
  });

  // Mood
  view.querySelectorAll(".mood-card").forEach(card => {
    card.addEventListener("click", () => {
      const mood = MOODS.find(m => m.id === card.dataset.mood);
      if (!mood) return;
      exportState.mood          = mood.id;
      exportState.one_per_game  = mood.one_per_game;
      exportState.skip_bad_tags = mood.skip_bad_tags;
      document.getElementById("opt-one-per-game").checked = mood.one_per_game;
      document.getElementById("opt-skip-bad").checked     = mood.skip_bad_tags;
      view.querySelectorAll(".mood-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
    });
  });

  // Manual options (override mood)
  document.getElementById("opt-one-per-game").addEventListener("change", e => {
    exportState.one_per_game = e.target.checked;
    exportState.mood = "custom";
    view.querySelectorAll(".mood-card").forEach(c => c.classList.remove("selected"));
  });
  document.getElementById("opt-skip-bad").addEventListener("change", e => {
    exportState.skip_bad_tags = e.target.checked;
    exportState.mood = "custom";
    view.querySelectorAll(".mood-card").forEach(c => c.classList.remove("selected"));
  });

  // Browse
  document.getElementById("btn-browse-export").addEventListener("click", async () => {
    const btn = document.getElementById("btn-browse-export");
    btn.disabled = true; btn.textContent = "Picking…";
    const res = await API.get("/api/browse");
    btn.disabled = false; btn.textContent = "Browse…";
    if (res.ok && res.path) document.getElementById("export-path").value = res.path;
  });

  document.getElementById("btn-preview").addEventListener("click", refreshExportPreview);
  document.getElementById("btn-export").addEventListener("click", doExport);
  document.getElementById("btn-autofit").addEventListener("click", autoFit);

  // Load console list
  await loadExportConsoles();
  refreshExportPreview();
}

async function loadExportConsoles() {
  const stats = await API.get("/api/catalog/stats");
  _exportCatalogConsoles = stats.consoles || {};

  // Default: select all consoles that have collected ROMs
  if (exportState.consoles === null) {
    exportState.consoles = Object.entries(_exportCatalogConsoles)
      .filter(([, info]) => info.have > 0)
      .map(([c]) => c);
  }

  renderConsoleChecklist();
}

function renderConsoleChecklist(sizeMap = {}) {
  const el = document.getElementById("console-checklist");
  if (!el) return;
  const allHave = Object.entries(_exportCatalogConsoles).filter(([, i]) => i.have > 0);

  if (!allHave.length) {
    el.innerHTML = `<span class="muted" style="font-size:12px;">No collected ROMs yet</span>`;
    return;
  }

  el.innerHTML = `
    <div style="display:flex;gap:8px;margin-bottom:8px;">
      <button class="btn small" id="btn-all-consoles">All</button>
      <button class="btn small" id="btn-none-consoles">None</button>
    </div>
    ${allHave.map(([con, info]) => {
      const checked = exportState.consoles && exportState.consoles.includes(con);
      const sizeInfo = sizeMap[con];
      const sizeStr  = sizeInfo ? fmt_bytes(sizeInfo.size) : "";
      const fitsIcon = sizeInfo ? (sizeInfo.fits ? ' <span style="color:var(--aqua)">✓</span>' : ' <span style="color:var(--orange)">⚠</span>') : "";
      return `
        <label class="console-check-row">
          <input type="checkbox" class="con-chk" data-con="${esc(con)}" ${checked ? 'checked' : ''}>
          <span class="con-name">${esc(con)}</span>
          <span class="con-count muted">${info.have} ROMs</span>
          ${sizeStr ? `<span class="con-size">${sizeStr}${fitsIcon}</span>` : ''}
        </label>`;
    }).join("")}
  `;

  el.querySelectorAll(".con-chk").forEach(chk => {
    chk.addEventListener("change", () => {
      const checked = [...el.querySelectorAll(".con-chk:checked")].map(c => c.dataset.con);
      exportState.consoles = checked.length ? checked : [];
    });
  });

  document.getElementById("btn-all-consoles").addEventListener("click", () => {
    exportState.consoles = allHave.map(([c]) => c);
    el.querySelectorAll(".con-chk").forEach(c => c.checked = true);
  });
  document.getElementById("btn-none-consoles").addEventListener("click", () => {
    exportState.consoles = [];
    el.querySelectorAll(".con-chk").forEach(c => c.checked = false);
  });
}

async function refreshExportPreview() {
  const btn = document.getElementById("btn-preview");
  btn.disabled = true; btn.textContent = "Calculating…";

  const res = await API.post("/api/export/preview", {
    one_per_game:  exportState.one_per_game,
    skip_bad_tags: exportState.skip_bad_tags,
    consoles:      exportState.consoles,
    capacity_gb:   exportState.capacity_gb,
  });

  btn.disabled = false; btn.textContent = "⟳ Refresh";

  // Re-render console list with size data
  renderConsoleChecklist(res.per_console || {});

  const body     = document.getElementById("preview-body");
  if (!res.ok) { body.textContent = "Error calculating preview"; return; }

  const sizeStr  = fmt_bytes(res.total_size);
  const capStr   = exportState.capacity_gb ? `${exportState.capacity_gb} GB SD` : "No limit";
  const fitsOk   = res.fits;
  const remStr   = res.remaining !== null
    ? (res.remaining >= 0
        ? `${fmt_bytes(res.remaining)} free`
        : `<span style="color:var(--orange)">+${fmt_bytes(-res.remaining)} over</span>`)
    : "";

  // Console breakdown rows
  const consoleRows = Object.entries(res.per_console || {})
    .sort((a, b) => b[1].size - a[1].size)
    .map(([con, info]) => {
      const icon = exportState.capacity_gb
        ? (info.fits ? '<span style="color:var(--aqua)">✓</span>' : '<span style="color:var(--orange)">⚠</span>')
        : '';
      return `<div class="preview-row">
        <span>${esc(con)} ${icon}</span>
        <span>${info.count} · ${fmt_bytes(info.size)}</span>
      </div>`;
    }).join("");

  // Log rows
  const logRows = (res.logs || []).map(l => `
    <div class="export-log ${l.level}">
      ${l.level === 'warn' ? '⚠' : 'ℹ'} ${esc(l.msg)}
    </div>`).join("");

  body.innerHTML = `
    <div class="preview-row" style="font-size:13px;font-weight:700;margin-bottom:4px;">
      <span>${res.count.toLocaleString()} ROMs</span>
      <span>${sizeStr}</span>
    </div>
    <div class="preview-row" style="color:${fitsOk ? 'var(--aqua)' : 'var(--orange)'};">
      <span>${fitsOk ? '✓ Fits on' : '⚠ Exceeds'} ${capStr}</span>
      <span>${remStr}</span>
    </div>
    ${res.missing_files ? `<div class="preview-row muted"><span>Missing on disk</span><span>${res.missing_files}</span></div>` : ''}
    <div style="border-top:1px solid var(--line);margin:8px 0;"></div>
    ${consoleRows}
    ${logRows}
  `;
}

async function autoFit() {
  if (!exportState.capacity_gb) {
    toast("Select an SD card size first", "err"); return;
  }
  const btn = document.getElementById("btn-autofit");
  btn.disabled = true; btn.textContent = "Fitting…";

  const res = await API.post("/api/export/autofit", {
    one_per_game:  exportState.one_per_game,
    skip_bad_tags: exportState.skip_bad_tags,
    capacity_gb:   exportState.capacity_gb,
  });

  btn.disabled = false; btn.textContent = "⚡ Auto-fit";

  if (!res.ok) { toast(res.error || "Auto-fit failed", "err"); return; }

  exportState.consoles = res.consoles;
  renderConsoleChecklist();
  toast(`Auto-fit: ${res.consoles.length} consoles · ${fmt_bytes(res.used)} used`, "ok");
  refreshExportPreview();
}

async function doExport() {
  const path = document.getElementById("export-path").value.trim();
  if (!path) { toast("Select an output folder first", "err"); return; }

  const btn = document.getElementById("btn-export");
  btn.disabled = true; btn.textContent = "Exporting…";

  const res = await API.post("/api/export", {
    output_dir:    path,
    profile:       exportState.profile,
    one_per_game:  exportState.one_per_game,
    skip_bad_tags: exportState.skip_bad_tags,
    consoles:      exportState.consoles,
    capacity_gb:   exportState.capacity_gb,
  });

  btn.disabled = false; btn.textContent = "Export Collection";

  if (res.ok) {
    document.getElementById("export-result").innerHTML = `
      <div class="badge ok" style="padding:10px 14px;font-size:13px;">
        ✓ ${res.copied.toLocaleString()} ROMs → ${esc(res.output)}
        ${res.skipped ? `<span class="muted" style="margin-left:8px;">${res.skipped} skipped</span>` : ''}
      </div>`;
    toast(`Exported ${res.copied} ROMs`, "ok");
  } else {
    toast(res.error || "Export failed", "err");
  }
}


// ── Trash view ────────────────────────────────────────────────────────────────

async function renderTrash() {
  const view = document.getElementById("view-trash");
  view.innerHTML = `
    <div class="view-header">
      <div class="view-title">Trash <span>⊘</span></div>
    </div>
    <div class="toolbar">
      <button class="btn danger" id="btn-empty-trash">Empty Trash</button>
      <span class="muted" style="font-size:12px;">Files are not permanently deleted until you empty the trash.</span>
    </div>
    <div id="trash-list" style="flex:1;overflow-y:auto;"></div>
  `;

  document.getElementById("btn-empty-trash").addEventListener("click", async () => {
    if (!confirm("Permanently delete all trashed ROMs? This cannot be undone.")) return;
    const res = await API.post("/api/trash/empty", {});
    toast(`Deleted ${res.deleted} files`, res.ok ? "ok" : "err");
    renderTrash();
  });

  loadTrash();
}

async function loadTrash() {
  const items = await API.get("/api/trash/list");
  const el    = document.getElementById("trash-list");
  if (!items.length) {
    el.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⊘</div><div class="empty-state-text">Trash is empty</div></div>`;
    return;
  }
  el.innerHTML = `
    <div style="padding:0 24px;">
    ${items.map(item => `
      <div class="trash-item">
        <div>
          <div class="mono" style="font-size:12px;">${esc(item.name)}</div>
          <div class="muted" style="font-size:11px;">${fmt_bytes(item.size)}</div>
        </div>
      </div>`).join("")}
    </div>`;
}


// ── DAT Files view ────────────────────────────────────────────────────────────

const ALL_CONSOLES = [
  "NES","SNES","GB","GBC","GBA","N64","NDS","GameCube","Wii",
  "PS1","PS2","PSP","Dreamcast","Saturn","Genesis","MasterSys",
  "GameGear","PCE","WonderSwan","NeoGeo","Atari2600","Atari7800",
  "Lynx","FDS","PICO8","MAME",
];

async function renderDats() {
  const view = document.getElementById("view-dats");
  view.innerHTML = `
    <div class="view-header">
      <div class="view-title">DAT Files <span>◎</span></div>
    </div>
    <div class="toolbar">
      <button class="btn primary" id="btn-dl-all">Download Available DATs</button>
      <button class="btn" id="btn-rebuild-catalog" title="Re-import all DAT files — fixes numbered names and duplicate groups">⟳ Rebuild Catalog</button>
      <span class="muted" style="font-size:11px;">No-Intro databases via libretro-database.</span>
    </div>
    <div id="dat-dl-progress" style="padding:8px 24px;display:none;">
      <div class="progress-bar-bg"><div class="progress-bar-fill" id="dat-bar" style="width:0%"></div></div>
      <div class="progress-label" id="dat-label">Downloading…</div>
    </div>
    <div class="dat-grid" id="dat-grid"><span class="muted">Loading…</span></div>

    <div style="padding:24px 24px 8px;">
      <div class="form-label" style="margin-bottom:8px;">Import DAT File</div>
      <div class="form-hint" style="margin-bottom:12px;">
        Download a No-Intro DAT from <strong>datomatic.no-intro.org</strong> and import it here.
        Importing loads all game entries into your catalog immediately.
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <input class="form-input" id="import-path" placeholder="Path to .dat or .zip file" style="flex:1;min-width:200px;">
        <button class="btn" id="btn-browse-dat">Browse…</button>
        <button class="btn primary" id="btn-import-dat" disabled>Import</button>
      </div>
      <div id="import-detect" style="margin-top:8px;min-height:24px;"></div>
      <div id="import-result" class="mt16"></div>
    </div>
  `;

  document.getElementById("btn-dl-all").addEventListener("click", downloadAllDats);

  document.getElementById("btn-rebuild-catalog").addEventListener("click", async () => {
    const btn = document.getElementById("btn-rebuild-catalog");
    btn.disabled = true; btn.textContent = "Rebuilding…";
    await API.post("/api/catalog/rebuild", {});
    btn.disabled = false; btn.textContent = "⟳ Rebuild Catalog";
    refreshStats();
    toast("Catalog rebuilt — names and groups updated", "ok");
  });

  // Auto-detect console when a file path is entered/pasted
  let _detectedConsole = "";
  async function detectDatConsole(path) {
    const detectEl = document.getElementById("import-detect");
    const importBtn = document.getElementById("btn-import-dat");
    _detectedConsole = "";
    importBtn.disabled = true;
    if (!path) { detectEl.innerHTML = ""; return; }
    detectEl.innerHTML = `<span class="muted">Detecting…</span>`;
    const res = await API.post("/api/dats/detect", { path });
    if (res.ok && res.console) {
      _detectedConsole = res.console;
      detectEl.innerHTML = `<span class="badge ok" style="padding:4px 10px;font-size:12px;">Detected: <strong>${esc(res.console)}</strong></span>`;
      importBtn.disabled = false;
    } else {
      detectEl.innerHTML = `<span class="badge warn" style="padding:4px 10px;font-size:12px;">Console not recognised — file may still be imported if it's a valid DAT</span>`;
      importBtn.disabled = false;  // allow manual import attempt anyway
    }
  }

  document.getElementById("import-path").addEventListener("change", e => {
    detectDatConsole(e.target.value.trim());
  });

  document.getElementById("btn-browse-dat").addEventListener("click", async () => {
    const btn = document.getElementById("btn-browse-dat");
    btn.disabled = true; btn.textContent = "Picking…";
    const res = await API.get("/api/browse/file");
    btn.disabled = false; btn.textContent = "Browse…";
    if (res.ok && res.path) {
      document.getElementById("import-path").value = res.path;
      detectDatConsole(res.path);
    }
  });

  document.getElementById("btn-import-dat").addEventListener("click", async () => {
    const path = document.getElementById("import-path").value.trim();
    if (!path) { toast("Select a DAT file first", "err"); return; }
    const btn = document.getElementById("btn-import-dat");
    btn.disabled = true; btn.textContent = "Importing…";
    // Pass detected console (empty = server will auto-detect again)
    const res = await API.post("/api/dats/import", { console: _detectedConsole, path });
    btn.disabled = false; btn.textContent = "Import";
    if (res.ok) {
      document.getElementById("import-result").innerHTML =
        `<div class="badge ok" style="padding:8px 14px;font-size:13px;">
          ✓ ${esc(res.console)} — ${(res.entries||0).toLocaleString()} games loaded into catalog
        </div>`;
      document.getElementById("import-detect").innerHTML = "";
      document.getElementById("import-path").value = "";
      _detectedConsole = "";
      btn.disabled = true;
      toast(`${res.console} catalog loaded`, "ok");
      loadDatStatus();
      refreshStats();
    } else {
      toast(res.error || "Import failed", "err");
    }
  });

  loadDatStatus();
}

async function loadDatStatus() {
  const status = await API.get("/api/dats/status");
  const grid   = document.getElementById("dat-grid");
  // Sort: available first, then alphabetical
  const entries = Object.entries(status).sort((a, b) => {
    if (a[1].available !== b[1].available) return b[1].available - a[1].available;
    return a[0].localeCompare(b[0]);
  });
  grid.innerHTML = entries.map(([con, info]) => {
    const tag = (!info.downloadable && info.available)
      ? `<span style="font-size:9px;opacity:.5;"> imported</span>` : "";
    const iconUrl = `/static/icons/${encodeURIComponent(con)}.png`;
    const iconEl = `<img class="dat-console-icon" src="${iconUrl}" alt="${esc(con)}"
      onerror="this.outerHTML='<div class=\\'dat-icon-placeholder\\'>◈</div>'">`;
    return `
    <div class="dat-card ${info.available ? 'available' : ''}">
      ${iconEl}
      <div class="dat-info">
        <div class="dat-name">${esc(con)}${tag}</div>
        <div class="dat-entries">${info.available ? info.entries.toLocaleString() + ' entries' : 'not downloaded'}</div>
      </div>
      <div class="dat-dot ${info.available ? 'available' : ''}"></div>
    </div>`;
  }).join("");
}

let datTimer = null;

async function downloadAllDats() {
  const res = await API.post("/api/dats/download", {});
  if (!res.ok) { toast(res.error, "err"); return; }
  document.getElementById("dat-dl-progress").style.display = "block";
  document.getElementById("btn-dl-all").disabled = true;
  toast("Downloading DATs…", "ok");

  clearInterval(datTimer);
  datTimer = setInterval(async () => {
    const p    = await API.get("/api/dats/progress");
    const done = p.done?.length || 0;
    document.getElementById("dat-label").textContent = p.message || `${done} done…`;
    if (p.status === "done") {
      clearInterval(datTimer);
      document.getElementById("dat-bar").style.width = "100%";
      document.getElementById("dat-label").textContent = `Done — ${done} DATs downloaded`;
      document.getElementById("btn-dl-all").disabled = false;
      loadDatStatus();
      refreshStats();
      toast(`Downloaded ${done} DATs`, "ok");
    }
  }, 800);
}
