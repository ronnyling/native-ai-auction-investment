# 🏠 Auction Property Search

> Search and filter all scraped listings. Click any column header to sort. Click a row to open the property note. For map view, open **Map View** and use the **Presets** panel.

```dataviewjs
// ── Auction Property Filter Dashboard ────────────────────────────────────────
// Requires: Dataview plugin enabled

const con = this.container;

// ── Filter state ──────────────────────────────────────────────────────────────
let sortCol = "date", sortDir = "asc";
let searchText = "";
let fTiming = "", fAuction = "";
const fStatus = new Set();
const fState  = new Set();
const fType   = new Set();
let fMinP = 0, fMaxP = Infinity, fMinBmv = 0;

const today = new Date().toISOString().slice(0, 10);
const badgeCls = {
  new:"s-new", reviewing:"s-reviewing", shortlisted:"s-shortlisted",
  visiting:"s-visiting", bid:"s-bid", passed:"s-passed"
};

// ── Styles ────────────────────────────────────────────────────────────────────
con.createEl("style").textContent = `
  .af-search {
    width:100%; padding:8px 12px; margin-bottom:10px; border-radius:6px;
    font-size:14px; background:var(--background-secondary);
    border:1px solid var(--background-modifier-border);
    color:var(--text-normal); box-sizing:border-box;
  }
  .af-bar { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; align-items:flex-end; }
  .af-grp { display:flex; flex-direction:column; }
  .af-lbl { font-size:11px; color:var(--text-muted); margin-bottom:3px; }
  .af-sel, .af-inp {
    padding:5px 8px; border-radius:5px; background:var(--background-secondary);
    border:1px solid var(--background-modifier-border);
    color:var(--text-normal); font-size:13px; min-width:100px;
  }
  /* ── multi-select ── */
  .af-ms-wrap { position:relative; }
  .af-ms-btn {
    padding:5px 24px 5px 8px; border-radius:5px; cursor:pointer;
    background:var(--background-secondary);
    border:1px solid var(--background-modifier-border);
    color:var(--text-normal); font-size:13px; min-width:120px;
    text-align:left; position:relative; white-space:nowrap;
    display:block; width:100%;
  }
  .af-ms-btn::after {
    content:"▾"; position:absolute; right:7px; top:50%;
    transform:translateY(-50%); color:var(--text-muted); pointer-events:none;
  }
  .af-ms-panel {
    display:none; position:absolute; z-index:9999; top:calc(100% + 4px); left:0;
    min-width:180px; max-height:240px; overflow-y:auto;
    background:var(--background-primary);
    border:1px solid var(--background-modifier-border);
    border-radius:6px; padding:4px 0; box-shadow:0 4px 20px rgba(0,0,0,.5);
  }
  .af-ms-panel.open { display:block; }
  .af-ms-ctrl {
    display:flex; gap:8px; padding:5px 10px 6px;
    border-bottom:1px solid var(--background-modifier-border); margin-bottom:3px;
  }
  .af-ms-lnk { cursor:pointer; color:var(--link-color); font-size:11px; }
  .af-ms-lnk:hover { text-decoration:underline; }
  .af-ms-row { display:flex; gap:8px; align-items:center; padding:4px 10px; cursor:pointer; }
  .af-ms-row:hover { background:var(--background-secondary); }
  .af-ms-row label { cursor:pointer; font-size:13px; user-select:none; flex:1; }
  .af-ms-row input[type=checkbox] { cursor:pointer; margin:0; flex-shrink:0; }
  /* ── table ── */
  .af-count { font-size:12px; color:var(--text-muted); margin-bottom:8px; }
  .af-tbl { width:100%; border-collapse:collapse; font-size:13px; }
  .af-tbl th {
    text-align:left; padding:7px 10px; white-space:nowrap;
    cursor:pointer; user-select:none;
    border-bottom:2px solid var(--background-modifier-border); color:var(--text-muted);
  }
  .af-tbl th:hover { color:var(--text-normal); background:var(--background-secondary); }
  .af-tbl th.sort-asc::after  { content:" ▲"; font-size:10px; }
  .af-tbl th.sort-desc::after { content:" ▼"; font-size:10px; }
  .af-tbl td {
    padding:6px 10px; border-bottom:1px solid var(--background-modifier-border);
    vertical-align:middle;
  }
  .af-tbl tr:hover td { background:var(--background-secondary); }
  .af-badge { display:inline-block; padding:1px 7px; border-radius:3px; font-size:11px; font-weight:600; }
  .s-new         { background:#1e3a5f; color:#7eb8f7; }
  .s-reviewing   { background:#2d1e4f; color:#c0a0ff; }
  .s-shortlisted { background:#3d2e00; color:#ffd166; }
  .s-visiting    { background:#3d1e00; color:#ffaa55; }
  .s-bid         { background:#4f1e1e; color:#ff7777; }
  .s-passed      { background:#2a2a2a; color:#888; }
`;

// ── Search bar ────────────────────────────────────────────────────────────────
const si = con.createEl("input", {
  cls: "af-search",
  attr: { type: "text", placeholder: "🔍  Search address, city, postcode, bank, auctioneer…" }
});
si.addEventListener("input", () => { searchText = si.value.toLowerCase(); render(); });

// ── Filter bar ────────────────────────────────────────────────────────────────
const bar = con.createDiv({ cls: "af-bar" });

// Single-select helper
function mkSel(label, opts, parent) {
  const g = parent.createDiv({ cls: "af-grp" });
  g.createEl("span", { cls: "af-lbl", text: label });
  const s = g.createEl("select", { cls: "af-sel" });
  opts.forEach(([v, t]) => { const o = s.createEl("option"); o.value = v; o.textContent = t; });
  return s;
}

// Number input helper
function mkInp(label, ph, parent) {
  const g = parent.createDiv({ cls: "af-grp" });
  g.createEl("span", { cls: "af-lbl", text: label });
  return g.createEl("input", { cls: "af-inp", attr: { type: "number", placeholder: ph } });
}

// Multi-select helper
let _openPanel = null;

function mkMultiSel(label, opts, selSet, parent) {
  const g = parent.createDiv({ cls: "af-grp" });
  g.createEl("span", { cls: "af-lbl", text: label });
  const wrap  = g.createDiv({ cls: "af-ms-wrap" });
  const btn   = wrap.createEl("button", { cls: "af-ms-btn" });
  const panel = wrap.createDiv({ cls: "af-ms-panel" });
  btn.textContent = "All";

  function updBtn() { btn.textContent = selSet.size ? selSet.size + " selected" : "All"; }

  // Select All / Clear controls
  const ctrl = panel.createDiv({ cls: "af-ms-ctrl" });
  const lAll = ctrl.createEl("span", { cls: "af-ms-lnk", text: "Select All" });
  ctrl.createEl("span", { text: " · " });
  const lClr = ctrl.createEl("span", { cls: "af-ms-lnk", text: "Clear" });

  const cbMap = {};
  for (const [v, t] of opts) {
    const rid = "af" + Math.random().toString(36).slice(2);
    const row = panel.createDiv({ cls: "af-ms-row" });
    const cb  = row.createEl("input", { attr: { type: "checkbox", id: rid } });
    cb.value  = v;
    row.createEl("label", { attr: { for: rid }, text: t });
    cb.addEventListener("change", e => {
      e.stopPropagation();
      cb.checked ? selSet.add(v) : selSet.delete(v);
      updBtn(); render();
    });
    cbMap[v] = cb;
  }

  lAll.addEventListener("click", e => {
    e.stopPropagation();
    opts.forEach(([v]) => { selSet.add(v); cbMap[v].checked = true; });
    updBtn(); render();
  });
  lClr.addEventListener("click", e => {
    e.stopPropagation();
    selSet.clear();
    for (const cb of Object.values(cbMap)) cb.checked = false;
    updBtn(); render();
  });

  btn.addEventListener("click", e => {
    e.stopPropagation();
    if (_openPanel && _openPanel !== panel) _openPanel.classList.remove("open");
    panel.classList.toggle("open");
    _openPanel = panel.classList.contains("open") ? panel : null;
  });
}

// Close open panel on outside click
document.addEventListener("click", e => {
  if (_openPanel && !_openPanel.parentElement.contains(e.target)) {
    _openPanel.classList.remove("open");
    _openPanel = null;
  }
});

// ── Build controls ────────────────────────────────────────────────────────────
const sTiming = mkSel("📅 Timing", [
  ["","All"], ["upcoming","⏳ Upcoming"], ["past","✅ Past"]
], bar);

mkMultiSel("🔖 Status", [
  ["new","New"], ["reviewing","Reviewing"], ["shortlisted","Shortlisted"],
  ["visiting","Visiting"], ["bid","Bid"], ["passed","Passed"]
], fStatus, bar);

mkMultiSel("📍 State", [
  ["Johor","Johor"], ["Kedah","Kedah"], ["Kelantan","Kelantan"],
  ["Kuala Lumpur","Kuala Lumpur"], ["Melaka","Melaka"],
  ["Negeri Sembilan","Negeri Sembilan"], ["Pahang","Pahang"],
  ["Penang","Penang"], ["Perak","Perak"], ["Perlis","Perlis"],
  ["Putrajaya","Putrajaya"], ["Sabah","Sabah"], ["Sarawak","Sarawak"],
  ["Selangor","Selangor"], ["Terengganu","Terengganu"]
], fState, bar);

mkMultiSel("🏠 Type", [
  ["apartment","Apartment"], ["bungalow","Bungalow"], ["condominium","Condominium"],
  ["flat","Flat"], ["land","Land"], ["residential","Residential"],
  ["semi_detached","Semi-D"], ["shop","Shop / Office"],
  ["terrace","Terrace"], ["townhouse","Townhouse"], ["warehouse","Warehouse"]
], fType, bar);

const sAuction = mkSel("⚖️ Auction", [
  ["","All"], ["LACA","LACA"], ["Non-LACA","Non-LACA"]
], bar);

const iMinP   = mkInp("Min Price (RM)", "e.g. 100000",  bar);
const iMaxP   = mkInp("Max Price (RM)", "e.g. 2000000", bar);
const iMinBmv = mkInp("Min BMV%",       "e.g. 10",      bar);

sTiming.addEventListener ("change", () => { fTiming  = sTiming.value;  render(); });
sAuction.addEventListener("change", () => { fAuction = sAuction.value; render(); });
iMinP.addEventListener   ("input",  () => { fMinP  = parseFloat(iMinP.value)   || 0;        render(); });
iMaxP.addEventListener   ("input",  () => { fMaxP  = parseFloat(iMaxP.value)   || Infinity; render(); });
iMinBmv.addEventListener ("input",  () => { fMinBmv = parseFloat(iMinBmv.value) || 0;       render(); });

// ── Results area ──────────────────────────────────────────────────────────────
const countDiv  = con.createDiv({ cls: "af-count" });
const tableWrap = con.createDiv();

// Column definitions: key, header label, default sort direction
const COLS = [
  { key:"address",  label:"Address / Property", def:"asc"  },
  { key:"price",    label:"Reserve Price",       def:"asc"  },
  { key:"bmv",      label:"BMV%",                def:"desc" },
  { key:"type",     label:"Type",                def:"asc"  },
  { key:"location", label:"State · City",        def:"asc"  },
  { key:"date",     label:"Auction Date",        def:"asc"  },
  { key:"days",     label:"Days Left",           def:"asc"  },
  { key:"rnd",      label:"Rnd",                 def:"desc" },
  { key:"status",   label:"Status",              def:"asc"  },
];

function sortKey(p) {
  switch (sortCol) {
    case "address":  return (p.address || p.file.name || "").toLowerCase();
    case "price":    return p.reserve_price || 0;
    case "bmv":      return p.bmv_pct || 0;
    case "type":     return (p.property_type || "").toLowerCase();
    case "location": return (p.state || "") + " " + (p.city || "");
    case "date":     return String(p.auction_date || "");
    case "days":     return p.days_to_auction ?? 9999;
    case "rnd":      return p.auction_count || 1;
    case "status":   return p.status || "";
    default:         return "";
  }
}

function render() {
  tableWrap.empty();

  let pages = dv.pages('"Properties"')
    .where(p => fStatus.size === 0 || fStatus.has(p.status || ""))
    .where(p => fState.size  === 0 || fState.has(p.state  || ""))
    .where(p => fType.size   === 0 || fType.has((p.property_type || "").toLowerCase()))
    .where(p => !fAuction || (p.auction_type || "") === fAuction)
    .where(p => (p.reserve_price || 0) >= fMinP && (p.reserve_price || 0) <= fMaxP)
    .where(p => (p.bmv_pct || 0) >= fMinBmv)
    .where(p => {
      if (!fTiming) return true;
      const d = p.auction_date ? String(p.auction_date).slice(0, 10) : "";
      return fTiming === "upcoming" ? d >= today : d < today;
    })
    .where(p => {
      if (!searchText) return true;
      return [p.address, p.city, p.state, p.postcode, p.bank, p.auctioneer, p.file.name]
        .filter(Boolean).join(" ").toLowerCase().includes(searchText);
    });

  pages = pages.sort(p => sortKey(p), sortDir);

  const arr = pages.array();
  countDiv.textContent = arr.length + " properties found";

  if (!arr.length) {
    tableWrap.createEl("p", {
      text: "No properties match the selected filters.",
      attr: { style: "color:var(--text-muted);padding:20px 0;" }
    });
    return;
  }

  const tbl = tableWrap.createEl("table", { cls: "af-tbl" });
  const htr = tbl.createEl("thead").createEl("tr");

  for (const col of COLS) {
    const th = htr.createEl("th", { text: col.label });
    if (sortCol === col.key) th.classList.add("sort-" + sortDir);
    th.addEventListener("click", () => {
      sortDir = (sortCol === col.key) ? (sortDir === "asc" ? "desc" : "asc") : col.def;
      sortCol = col.key;
      render();
    });
  }

  const tb = tbl.createEl("tbody");
  for (const p of arr) {
    const tr = tb.createEl("tr");

    const td0 = tr.createEl("td");
    const a = td0.createEl("a", {
      cls: "internal-link",
      attr: { "data-href": p.file.path, href: p.file.path }
    });
    const addr = p.address || p.file.name.replace(/\.md$/, "");
    a.textContent = addr.length > 52 ? addr.slice(0, 50) + "…" : addr;
    if (addr.length > 52) a.title = addr;

    tr.createEl("td", { text: "RM " + (p.reserve_price || 0).toLocaleString() });
    tr.createEl("td", { text: (p.bmv_pct || 0) + "%" });
    tr.createEl("td", { text: (p.property_type || "").replace(/_/g, " ") });
    tr.createEl("td", { text: (p.state || "—") + " · " + (p.city || "—") });
    tr.createEl("td", { text: p.auction_date ? String(p.auction_date).slice(0, 10) : "—" });
    tr.createEl("td", { text: p.days_to_auction != null ? p.days_to_auction + "d" : "—" });
    tr.createEl("td", { text: String(p.auction_count || 1) });

    const tdS = tr.createEl("td");
    tdS.createEl("span", {
      cls: "af-badge " + (badgeCls[p.status] || ""),
      text: p.status || "—"
    });
  }
}

render();
```
