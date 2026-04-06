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
    const ext = v.rom_path ? v.rom_path.split('.').pop().toLowerCase() : '';
    const fmtBadge = ext ? `<span class="fmt-badge ${ext}">${ext.toUpperCase()}</span>` : '';
    return `
      <div class="variant-row ${v.collected ? 'has' : ''}">
        <span class="vrow-dot" style="color:${v.collected ? 'var(--aqua)' : 'var(--text2)'}">${v.collected ? '●' : '○'}</span>
        <span class="vrow-name">${esc(v.name)}</span>
        ${warn}
        ${fmtBadge}
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

// Unified scan queue: each entry is {type:'folder'|'file', path:string}
let _scanQueue = [];

function renderScan() {
  const view = document.getElementById("view-scan");
  view.innerHTML = `
    <div class="view-header">
      <div class="view-title">Scan <span>⟳</span></div>
    </div>
    <div class="scan-form">
      <div class="form-group">
        <label class="form-label">What to scan</label>
        <div style="display:flex;gap:8px;margin-bottom:10px;">
          <button class="btn" id="btn-browse">+ Folder</button>
          <button class="btn" id="btn-browse-files">+ Files</button>
          <button class="btn" id="btn-clear-queue" style="margin-left:auto;display:none;">✕ Clear all</button>
        </div>
        <div id="scan-queue-list" class="picked-files-list">
          <div class="muted" id="scan-queue-empty" style="font-size:12px;padding:6px 0;">No folders or files added yet.</div>
        </div>
      </div>
      <div class="form-hint">Add folders (scanned recursively) and/or individual ROM files. Match against your loaded DAT catalog.</div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px;">
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
    <div id="tools-setup-panel" style="padding:0 24px 8px;"></div>
    <div style="padding:0 24px 24px;">
      <div class="form-label" style="margin-bottom:12px;">Recent Scans</div>
      <div id="recent-scans"><span class="muted">Loading…</span></div>
    </div>
  `;

  _scanQueue = [];

  document.getElementById("btn-scan").addEventListener("click", startScan);
  loadToolsSetup();

  document.getElementById("btn-browse").addEventListener("click", async () => {
    const btn = document.getElementById("btn-browse");
    btn.disabled = true; btn.textContent = "Picking…";
    const res = await API.get("/api/browse");
    btn.disabled = false; btn.textContent = "+ Folder";
    if (res.ok && res.path && !_scanQueue.find(e => e.path === res.path)) {
      _scanQueue.push({ type: "folder", path: res.path });
      updateScanQueueUI();
    }
  });

  document.getElementById("btn-browse-files").addEventListener("click", async () => {
    const btn = document.getElementById("btn-browse-files");
    btn.disabled = true; btn.textContent = "Picking…";
    const res = await API.get("/api/browse/files");
    btn.disabled = false; btn.textContent = "+ Files";
    if (res.ok && res.paths && res.paths.length) {
      for (const p of res.paths) {
        if (!_scanQueue.find(e => e.path === p))
          _scanQueue.push({ type: "file", path: p });
      }
      updateScanQueueUI();
    }
  });

  document.getElementById("btn-clear-queue").addEventListener("click", () => {
    _scanQueue = [];
    updateScanQueueUI();
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
    const btn = document.getElementById("btn-clear-catalog");
    if (btn.dataset.armed !== label) {
      btn.dataset.armed = label;
      btn.textContent = "sure?";
      setTimeout(() => { btn.textContent = "Clear Catalog"; delete btn.dataset.armed; }, 3000);
      return;
    }
    delete btn.dataset.armed;
    btn.textContent = "Clear Catalog";
    await API.post("/api/catalog/clear", console_ ? { console: console_ } : {});
    refreshStats();
    toast(`${console_ || "Catalog"} cleared`, "ok");
  });

  loadRecentScans();
}

function updateScanQueueUI() {
  const list     = document.getElementById("scan-queue-list");
  const empty    = document.getElementById("scan-queue-empty");
  const clearBtn = document.getElementById("btn-clear-queue");
  if (!list) return;
  if (_scanQueue.length === 0) {
    empty.style.display = "";
    clearBtn.style.display = "none";
    list.querySelectorAll(".picked-file-row").forEach(el => el.remove());
  } else {
    empty.style.display = "none";
    clearBtn.style.display = "";
    list.querySelectorAll(".picked-file-row").forEach(el => el.remove());
    _scanQueue.forEach((entry, i) => {
      const icon = entry.type === "folder" ? "▦" : "◈";
      const row = document.createElement("div");
      row.className = "picked-file-row";
      row.innerHTML = `<span style="opacity:.5;margin-right:6px;">${icon}</span><span class="mono">${esc(entry.path)}</span>
        <button onclick="_scanQueue.splice(${i},1);updateScanQueueUI();" style="margin-left:auto;background:none;border:none;color:var(--fg3);cursor:pointer;font-size:11px;">✕</button>`;
      row.style.display = "flex";
      row.style.alignItems = "center";
      list.appendChild(row);
    });
  }
}

async function startScan() {
  if (_scanQueue.length === 0) { toast("Add a folder or files first", "err"); return; }

  const folders = _scanQueue.filter(e => e.type === "folder").map(e => e.path);
  const files   = _scanQueue.filter(e => e.type === "file").map(e => e.path);

  // If only one folder and no individual files, use simple path mode
  let payload;
  if (folders.length === 1 && files.length === 0) {
    payload = { path: folders[0] };
  } else if (folders.length === 0 && files.length > 0) {
    payload = { files };
  } else {
    // Mixed: expand folders on backend too — pass both
    payload = { files, folders };
  }

  const res = await API.post("/api/scan", payload);
  if (!res.ok) { toast(res.error, "err"); return; }
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

    const convertible = p.convertible || [];
    const autoFiles   = convertible.filter(f => !f.manual);
    const manualFiles = convertible.filter(f => f.manual);

    let convertHtml = "";
    if (convertible.length > 0) {
      const autoSection = autoFiles.length ? `
        <div class="convert-group">
          <div class="convert-group-label">⚡ Auto-convertible (${autoFiles.length} files)</div>
          ${autoFiles.map(f => `
            <div class="convert-file-row">
              <span class="convert-ext-badge">${f.ext}</span>
              <span class="convert-file-name mono">${esc(f.path.split("/").pop())}</span>
            </div>`).join("")}
          <button class="btn primary convert-run-btn" onclick="startConvert(${JSON.stringify(autoFiles.map(f => f.path))})">
            Convert ${autoFiles.length} file${autoFiles.length > 1 ? "s" : ""} → ISO
          </button>
        </div>` : "";

      const manualSection = manualFiles.length ? `
        <div class="convert-group">
          <div class="convert-group-label">⚠ Manual conversion needed (${manualFiles.length} files)</div>
          ${[...new Set(manualFiles.map(f => f.ext))].map(ext => {
            const group = manualFiles.filter(f => f.ext === ext);
            return `<div class="convert-manual-note">
              <span class="convert-ext-badge">${ext}</span>
              <span>${group.length} file${group.length > 1 ? "s" : ""} · ${esc(group[0].note)}</span>
            </div>`;
          }).join("")}
        </div>` : "";

      convertHtml = `
        <div class="convert-card">
          <div class="convert-card-title">Files needing conversion</div>
          <div class="convert-card-sub">These formats can't be matched directly. Convert them first, then rescan.</div>
          ${autoSection}${manualSection}
          <div id="convert-progress-wrap" class="progress-wrap" style="display:none;margin-top:12px;">
            <div class="progress-bar-bg"><div class="progress-bar-fill" id="convert-bar"></div></div>
            <div class="progress-label" id="convert-label">Converting…</div>
          </div>
          <div id="convert-result"></div>
        </div>`;
    }

    const pbpFiles = p.pbp_files || [];
    document.getElementById("scan-result").innerHTML = `
      <div class="badge ok" style="padding:8px 14px;font-size:13px;">
        ✓ ${matched.toLocaleString()} ROMs added to collection
        ${p.total - matched > 0 ? `<span class="muted" style="margin-left:8px;">(${(p.total-matched).toLocaleString()} not in any DAT)</span>` : ""}
      </div>
      ${convertHtml}
      <div id="pbp-panel"></div>`;
    if (pbpFiles.length > 0) initPBPPanel(pbpFiles);
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

let convertTimer = null;

async function startConvert(paths) {
  const btn = document.querySelector(".convert-run-btn");
  if (btn) btn.disabled = true;

  const res = await API.post("/api/convert", { paths });
  if (!res.ok) { toast(res.error || "Convert failed", "err"); return; }

  const wrap = document.getElementById("convert-progress-wrap");
  if (wrap) wrap.style.display = "block";

  clearInterval(convertTimer);
  convertTimer = setInterval(pollConvert, 700);
}

async function pollConvert() {
  const p     = await API.get("/api/convert/progress");
  const bar   = document.getElementById("convert-bar");
  const label = document.getElementById("convert-label");
  if (!bar) { clearInterval(convertTimer); return; }

  if (p.total > 0) {
    const pct = Math.round(p.current / p.total * 100);
    bar.style.width = pct + "%";
    label.textContent = `${pct}% · ${p.file}`;
  }

  if (p.status === "done") {
    clearInterval(convertTimer);
    bar.style.width = "100%";
    const ok  = p.results.filter(r => r.ok).length;
    const bad = p.results.filter(r => !r.ok).length;
    label.textContent = `Done — ${ok} converted${bad ? `, ${bad} failed` : ""}`;

    const resultEl = document.getElementById("convert-result");
    if (resultEl) {
      resultEl.innerHTML = p.results.map(r => `
        <div class="convert-result-row ${r.ok ? "ok" : "err"}">
          <span>${r.ok ? "✓" : "✗"}</span>
          <span class="mono" style="font-size:11px;">${esc(r.path.split("/").pop())}</span>
          <span class="muted" style="font-size:11px;">${esc(r.msg)}</span>
        </div>`).join("");
    }

    if (ok > 0 && p.converted_paths.length > 0) {
      // Add converted files to the scan queue and offer rescan
      p.converted_paths.forEach(fp => {
        if (!_scanQueue.find(e => e.path === fp))
          _scanQueue.push({ type: "file", path: fp });
      });
      updateScanQueueUI();
      toast(`${ok} files converted — added to scan queue`, "ok");
    }
  }

  if (p.status === "error") {
    clearInterval(convertTimer);
    if (label) label.textContent = "Conversion error";
    toast("Conversion error", "err");
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
    const emptyBtn = document.getElementById("btn-empty-trash");
    if (!emptyBtn.dataset.armed) {
      emptyBtn.dataset.armed = "1";
      emptyBtn.textContent = "sure?";
      setTimeout(() => { emptyBtn.textContent = "Empty Trash"; delete emptyBtn.dataset.armed; }, 3000);
      return;
    }
    delete emptyBtn.dataset.armed;
    emptyBtn.textContent = "Empty Trash";
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

let _datShowAll = false;

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
      <button class="btn" id="btn-toggle-bookshelf" style="margin-left:auto;">Show All Consoles</button>
    </div>
    <div style="padding:12px 24px 16px;border-bottom:1px solid var(--line);">
      <div class="form-label" style="margin-bottom:8px;">Import DAT File</div>
      <div class="form-hint" style="margin-bottom:10px;">
        Download a No-Intro DAT from <strong>datomatic.no-intro.org</strong> and import it here.
        Console is detected automatically from the file.
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <input class="form-input" id="import-path" placeholder="Path to .dat or .zip file" style="flex:1;min-width:200px;">
        <button class="btn" id="btn-browse-dat">Browse…</button>
        <button class="btn primary" id="btn-import-dat" disabled>Import</button>
      </div>
      <div id="import-detect" style="margin-top:8px;min-height:24px;"></div>
      <div id="import-result" class="mt8"></div>
    </div>
    <div id="dat-dl-progress" style="padding:8px 24px;display:none;">
      <div class="progress-bar-bg"><div class="progress-bar-fill" id="dat-bar" style="width:0%"></div></div>
      <div class="progress-label" id="dat-label">Downloading…</div>
    </div>
    <div class="dat-grid" id="dat-grid"><span class="muted">Loading…</span></div>
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

  document.getElementById("btn-toggle-bookshelf").addEventListener("click", () => {
    _datShowAll = !_datShowAll;
    document.getElementById("btn-toggle-bookshelf").textContent =
      _datShowAll ? "Show Loaded Only" : "Show All Consoles";
    loadDatStatus(_datShowAll);
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
      loadDatStatus(_datShowAll);
      refreshStats();
    } else {
      toast(res.error || "Import failed", "err");
    }
  });

  loadDatStatus(_datShowAll);
}

async function loadDatStatus(showAll = false) {
  const [status, unmatched] = await Promise.all([
    API.get("/api/dats/status"),
    API.get("/api/scan/unmatched"),
  ]);
  const grid = document.getElementById("dat-grid");

  // Split into groups
  const loaded   = [];
  const download = [];
  const manual   = [];

  for (const [con, info] of Object.entries(status)) {
    if (info.available)             loaded.push([con, info]);
    else if (!showAll)              continue;   // hide unloaded when in "loaded only" mode
    else if (info.downloadable)     download.push([con, info]);
    else                            manual.push([con, info]);
  }
  const sortName = ([a], [b]) => a.localeCompare(b);
  loaded.sort(sortName); download.sort(sortName); manual.sort(sortName);

  function makeCard(con, info) {
    const iconUrl = `/static/icons/${encodeURIComponent(con)}.png`;
    const iconEl  = `<img class="dat-console-icon" src="${iconUrl}" alt="${esc(con)}"
      onerror="this.outerHTML='<div class=\\'dat-icon-placeholder\\'>◈</div>'">`;
    const unmatchedInfo = unmatched[con] || null;
    const unmatchedCount = unmatchedInfo ? (unmatchedInfo.count || unmatchedInfo) : 0;
    const unmatchedExts  = unmatchedInfo && unmatchedInfo.exts ? unmatchedInfo.exts : {};
    const friendly = info.friendly || con;

    let statusEl, badge = "";
    if (info.available) {
      const tag = !info.downloadable ? ` <span style="font-size:9px;opacity:.5;">imported</span>` : "";
      statusEl = `<div class="dat-entries">${info.entries.toLocaleString()} entries${tag}</div>`;
    } else if (info.downloadable) {
      statusEl = `<div class="dat-entries" style="color:var(--text2);">available — not downloaded</div>`;
    } else {
      statusEl = `<div class="dat-entries" style="color:var(--text2);">import DAT manually</div>`;
    }

    if (unmatchedCount) {
      const extList = Object.entries(unmatchedExts).map(([e,n]) => `${n}×${e}`).join(", ");
      const hasCHD  = ".chd" in unmatchedExts;
      const tip = `${unmatchedCount} unidentified files from last scan${extList ? ': ' + extList : ''}${hasCHD ? ' — CHD files cannot be matched (compressed format)' : ''}`;
      badge = `<span class="dat-unmatched-badge" title="${tip}">!${unmatchedCount}</span>`;
      if (hasCHD && info.available) {
        statusEl += `<div style="font-size:9px;color:var(--orange);margin-top:2px;">CHD files can't be matched — use BIN/CUE</div>`;
      }
    }

    const deleteBtn = info.available
      ? `<button class="dat-delete-btn" data-console="${esc(con)}" title="Remove DAT">✕</button>`
      : "";

    return `
    <div class="dat-card ${info.available ? 'available' : ''} ${unmatchedCount ? 'has-unmatched' : ''}">
      ${iconEl}
      <div class="dat-info">
        <div class="dat-name">${esc(friendly)}</div>
        ${statusEl}
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0;">
        <div class="dat-dot ${info.available ? 'available' : ''}"></div>
        ${badge}
        ${deleteBtn}
      </div>
    </div>`;
  }

  function section(title, cards) {
    if (!cards.length) return "";
    return `<div class="dat-section-label">${title}</div>
      <div class="dat-grid-inner">${cards.map(([c,i]) => makeCard(c,i)).join("")}</div>`;
  }

  grid.innerHTML =
    section("Loaded", loaded) +
    section("Available to Download", download) +
    section("Import Manually", manual);

  let _pendingDelete = null;
  grid.querySelectorAll(".dat-delete-btn").forEach(btn => {
    btn.addEventListener("click", async e => {
      e.stopPropagation();
      const console_ = btn.dataset.console;
      if (_pendingDelete !== console_) {
        // First click — arm it
        if (_pendingDelete) {
          // Reset previously armed button
          const prev = grid.querySelector(`.dat-delete-btn[data-console="${_pendingDelete}"]`);
          if (prev) { prev.textContent = "✕"; prev.classList.remove("armed"); }
        }
        _pendingDelete = console_;
        btn.textContent = "sure?";
        btn.classList.add("armed");
        // Auto-cancel after 3s
        setTimeout(() => {
          if (_pendingDelete === console_) {
            btn.textContent = "✕"; btn.classList.remove("armed");
            _pendingDelete = null;
          }
        }, 3000);
      } else {
        // Second click — confirm delete
        const res = await API.post("/api/dats/delete", { console: console_ });
        _pendingDelete = null;
        if (res.ok) {
          toast(`${console_} DAT removed`, "ok");
          loadDatStatus(_datShowAll);
          refreshStats();
        } else {
          toast(res.error || "Delete failed", "err");
        }
      }
    });
  });
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
      loadDatStatus(_datShowAll);
      refreshStats();
      toast(`Downloaded ${done} DATs`, "ok");
    }
  }, 800);
}


// ── PBP Review Panel ──────────────────────────────────────────────────────────

let _pbpItems = [];  // [{file, status:'pending'|'accepted'|'skipped', selected:candidate|null}]

function initPBPPanel(pbpFiles) {
  _pbpItems = pbpFiles.map(f => ({
    file:     f,
    status:   'pending',
    selected: (f.candidates && f.candidates[0]) ? f.candidates[0] : null,
  }));
  _pbpRenderAll();
}

function _pbpRenderAll() {
  const el = document.getElementById('pbp-panel');
  if (!el) return;
  const accepted = _pbpItems.filter(i => i.status === 'accepted').length;
  const total    = _pbpItems.length;
  el.innerHTML = `
    <div class="pbp-panel">
      <div class="pbp-panel-header">
        <div class="pbp-panel-title">◈ ${total} PBP File${total !== 1 ? 's' : ''} Found</div>
        <div class="pbp-panel-sub">Accept or search for each game to link it to your catalog without converting.</div>
      </div>
      <div class="pbp-items">
        ${_pbpItems.map((item, idx) => _pbpRenderItem(item, idx)).join('')}
      </div>
      <div class="pbp-panel-footer">
        <button class="btn primary" onclick="_pbpConfirmAll()" ${accepted === 0 ? 'disabled' : ''}>
          ✓ Add ${accepted} to Collection
        </button>
        <button class="btn" onclick="_pbpDismiss()">Dismiss</button>
        <span class="muted" style="font-size:11px;margin-left:auto;">${accepted} / ${total} accepted</span>
      </div>
    </div>`;
}

function _pbpRenderItem(item, idx) {
  const f      = item.file;
  const fname  = f.filename || f.path.split('/').pop();
  const sfoTitle = f.sfo_title || '';

  let bodyHtml = '';
  if (item.status === 'accepted') {
    const c = item.selected;
    bodyHtml = `
      <div class="pbp-accepted">
        <span class="pbp-match-score high">✓</span>
        <span class="pbp-cand-name">${esc(c.name)}</span>
        <span class="pbp-cand-meta muted">${esc(c.region || '')}${c.region && c.console ? ' · ' : ''}${esc(c.console || '')}</span>
        <button class="btn small" style="margin-left:auto;" onclick="_pbpUndo(${idx})">Undo</button>
      </div>`;
  } else if (item.status === 'skipped') {
    bodyHtml = `
      <div class="pbp-skipped muted">
        — Skipped
        <button class="btn small" style="margin-left:8px;" onclick="_pbpUndo(${idx})">Undo</button>
      </div>`;
  } else {
    const noCands = !f.candidates || !f.candidates.length;
    const candRows = (f.candidates || []).slice(0, 3).map((c, ci) => {
      const pct       = Math.round((c.score || 0) * 100);
      const cls       = item.selected && item.selected.crc32 === c.crc32 ? 'selected' : '';
      const scoreClass = pct >= 90 ? 'high' : pct >= 70 ? 'mid' : 'low';
      return `<div class="pbp-candidate ${cls}" onclick="_pbpSelect(${idx}, ${ci})">
        <span class="pbp-match-score ${scoreClass}">${pct}%</span>
        <span class="pbp-cand-name">${esc(c.name)}</span>
        <span class="pbp-cand-meta muted">${esc(c.region || '')}${c.region && c.console ? ' · ' : ''}${esc(c.console || '')}</span>
      </div>`;
    }).join('');

    const noMatchNote = noCands
      ? `<div class="pbp-nomatch-note">
           SFO title <strong>"${esc(sfoTitle)}"</strong> didn't match any catalog entry
           — this can happen when the PBP uses a regional title (e.g. <em>Biohazard</em> vs <em>Resident Evil</em>).
           Search by the Western name below.
         </div>`
      : '';

    bodyHtml = `
      <div class="pbp-candidates">
        ${candRows || ''}
        ${noMatchNote}
      </div>
      <div class="pbp-search-row">
        <input class="form-input pbp-search-input" id="pbp-q-${idx}" placeholder="Search game…"
          onkeydown="if(event.key==='Enter')_pbpSearch(${idx})">
        <button class="btn small" onclick="_pbpSearch(${idx})">Search</button>
      </div>
      <div class="pbp-search-results" id="pbp-results-${idx}"></div>
      <div class="pbp-item-actions">
        <button class="btn small primary" onclick="_pbpAccept(${idx})" ${item.selected ? '' : 'disabled'}>
          ✓ Accept${item.selected ? ' — ' + esc(item.selected.name.split(' (')[0].slice(0, 28)) : ''}
        </button>
        <button class="btn small" onclick="_pbpSkip(${idx})">Skip</button>
      </div>`;
  }

  const statusColor = item.status === 'accepted' ? 'var(--aqua)'
                    : item.status === 'skipped'  ? 'var(--text2)' : 'var(--orange)';
  const statusDot   = item.status === 'accepted' ? '●'
                    : item.status === 'skipped'  ? '—' : '○';

  return `
    <div class="pbp-item">
      <div class="pbp-item-header">
        <span class="pbp-status-dot" style="color:${statusColor}">${statusDot}</span>
        <span class="fmt-badge pbp">PBP</span>
        <span class="pbp-filename">${esc(fname)}</span>
        ${sfoTitle ? `<span class="pbp-sfo-title muted">· ${esc(sfoTitle)}</span>` : ''}
      </div>
      ${bodyHtml}
    </div>`;
}

function _pbpSelect(idx, ci) {
  if (!_pbpItems[idx]) return;
  _pbpItems[idx].selected = (_pbpItems[idx].file.candidates || [])[ci] || null;
  _pbpRenderAll();
}

function _pbpAccept(idx) {
  if (!_pbpItems[idx] || !_pbpItems[idx].selected) return;
  _pbpItems[idx].status = 'accepted';
  _pbpRenderAll();
}

function _pbpSkip(idx) {
  if (!_pbpItems[idx]) return;
  _pbpItems[idx].status = 'skipped';
  _pbpRenderAll();
}

function _pbpUndo(idx) {
  if (!_pbpItems[idx]) return;
  _pbpItems[idx].status = 'pending';
  _pbpRenderAll();
}

// Keyed by idx — stores last search results so event listeners can look them up
const _pbpSearchCache = {};

async function _pbpSearch(idx) {
  const input     = document.getElementById(`pbp-q-${idx}`);
  const resultsEl = document.getElementById(`pbp-results-${idx}`);
  if (!input || !resultsEl) return;
  const q = input.value.trim();
  if (!q) return;
  resultsEl.innerHTML = `<div class="muted" style="font-size:11px;padding:4px 0;">Searching…</div>`;
  const res   = await API.post('/api/pbp/search', { title: q });
  const cands = res.candidates || [];
  if (!cands.length) {
    resultsEl.innerHTML = `<div class="muted" style="font-size:11px;padding:4px 0;">No results</div>`;
    return;
  }
  // Cache by crc32 so click handler can retrieve full object safely
  _pbpSearchCache[idx] = {};
  cands.forEach(c => { _pbpSearchCache[idx][c.crc32] = c; });

  resultsEl.innerHTML = cands.map(c => {
    const pct        = Math.round((c.score || 0) * 100);
    const scoreClass = pct >= 90 ? 'high' : pct >= 70 ? 'mid' : 'low';
    return `<div class="pbp-candidate" data-crc="${esc(c.crc32)}">
      <span class="pbp-match-score ${scoreClass}">${pct}%</span>
      <span class="pbp-cand-name">${esc(c.name)}</span>
      <span class="pbp-cand-meta muted">${esc(c.region || '')}${c.region && c.console ? ' · ' : ''}${esc(c.console || '')}</span>
    </div>`;
  }).join('');

  resultsEl.querySelectorAll('.pbp-candidate').forEach(el => {
    el.addEventListener('click', () => {
      const c = (_pbpSearchCache[idx] || {})[el.dataset.crc];
      if (c) _pbpPickResult(idx, c.crc32, c.name, c.console || '', c.region || '');
    });
  });
}

function _pbpPickResult(idx, crc32, name, console_, region) {
  if (!_pbpItems[idx]) return;
  _pbpItems[idx].selected = { crc32, name, console: console_, region };
  _pbpRenderAll();
}

async function _pbpConfirmAll() {
  const accepted = _pbpItems.filter(i => i.status === 'accepted');
  if (!accepted.length) return;
  const links = accepted.map(i => ({
    pbp_path:   i.file.path,
    game_crc32: i.selected.crc32,
    sfo_title:  i.file.sfo_title || '',
    sfo_id:     i.file.sfo_id    || '',
  }));
  const res = await API.post('/api/pbp/confirm', { links });
  if (res.ok) {
    toast(`${res.count} PBP${res.count !== 1 ? 's' : ''} added to collection`, 'ok');
    refreshStats();
    const el = document.getElementById('pbp-panel');
    if (el) el.innerHTML = `<div class="badge ok" style="padding:8px 14px;margin-top:12px;font-size:13px;">
      ✓ ${res.count} PBP${res.count !== 1 ? 's' : ''} linked to catalog</div>`;
  } else {
    toast(res.error || 'Failed to confirm links', 'err');
  }
}

function _pbpDismiss() {
  const el = document.getElementById('pbp-panel');
  if (el) el.innerHTML = '';
}


// ── Tools setup panel ─────────────────────────────────────────────────────────

let _toolInstallTimer = null;

async function loadToolsSetup() {
  const el = document.getElementById('tools-setup-panel');
  if (!el) return;

  const tools = await API.get('/api/tools');

  if (tools.chdman) {
    el.innerHTML = '';  // all good — hide panel
    return;
  }

  const brewAvailable = !!tools.brew;

  el.innerHTML = `
    <div class="setup-card">
      <div class="setup-card-title">⚠ Missing: chdman</div>
      <div class="setup-card-body">
        <p>chdman is required to match <strong>CHD</strong> disc images against your catalog.
        Without it, CHD files will show as unmatched.</p>
        <div class="setup-tool-row">
          <span class="setup-tool-name">chdman</span>
          <span class="badge issues">not found</span>
        </div>
        <div class="setup-options">
          ${brewAvailable ? `
          <div class="setup-option">
            <div class="setup-option-label">Option 1 — Auto-install via Homebrew</div>
            <div class="setup-option-desc muted">Installs the MAME toolchain (~500 MB). Takes a few minutes.</div>
            <button class="btn primary small" id="btn-brew-install">Install via Homebrew</button>
            <div class="progress-wrap" id="tool-install-wrap" style="display:none;margin-top:8px;">
              <div class="progress-bar-bg"><div class="progress-bar-fill" id="tool-install-bar" style="width:30%;animation:indeterminate 1.4s ease infinite;"></div></div>
              <div class="progress-label mono" id="tool-install-label" style="font-size:10px;">Starting…</div>
            </div>
          </div>` : `
          <div class="setup-option">
            <div class="setup-option-label">Option 1 — Install Homebrew first</div>
            <div class="setup-option-desc muted">Homebrew not found. Install it from <strong>brew.sh</strong>, then reopen ROMeo.</div>
          </div>`}
          <div class="setup-option" style="margin-top:10px;">
            <div class="setup-option-label">Option 2 — RetroArch</div>
            <div class="setup-option-desc muted">If you have RetroArch installed, chdman is bundled inside it and will be detected automatically.</div>
          </div>
          <div class="setup-option" style="margin-top:10px;">
            <div class="setup-option-label">Option 3 — Manual placement</div>
            <div class="setup-option-desc muted">Drop any <code>chdman</code> binary into:</div>
            <div class="mono setup-path">~/Library/Application Support/ROMeo/tools/chdman</div>
          </div>
        </div>
      </div>
    </div>`;

  if (brewAvailable) {
    document.getElementById('btn-brew-install').addEventListener('click', startToolInstall);
  }
}

async function startToolInstall() {
  const btn = document.getElementById('btn-brew-install');
  if (btn) btn.disabled = true;

  const res = await API.post('/api/tools/install', { tool: 'chdman' });
  if (!res.ok) {
    toast(res.error || 'Install failed', 'err');
    if (btn) btn.disabled = false;
    return;
  }

  const wrap = document.getElementById('tool-install-wrap');
  if (wrap) wrap.style.display = 'block';

  clearInterval(_toolInstallTimer);
  _toolInstallTimer = setInterval(pollToolInstall, 1000);
}

async function pollToolInstall() {
  const p     = await API.get('/api/tools/install/progress');
  const label = document.getElementById('tool-install-label');
  if (label && p.message) label.textContent = p.message;

  if (p.status === 'done') {
    clearInterval(_toolInstallTimer);
    const bar = document.getElementById('tool-install-bar');
    if (bar) { bar.style.width = '100%'; bar.style.animation = 'none'; }
    toast('chdman installed — ready to scan CHD files', 'ok');
    setTimeout(loadToolsSetup, 800);  // re-check — panel should disappear
  }

  if (p.status === 'error') {
    clearInterval(_toolInstallTimer);
    if (label) label.textContent = '✗ ' + p.message;
    toast('Install failed: ' + p.message, 'err');
    const btn = document.getElementById('btn-brew-install');
    if (btn) btn.disabled = false;
  }
}
