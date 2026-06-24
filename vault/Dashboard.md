# 🏠 Auction Property Search

```dataviewjs
// ── Auction Property Filter Dashboard ────────────────────────────────────────
// Requires: Dataview plugin enabled

const con = this.container;

// Description (inside JS so code block is right at the top = renders immediately)
const desc = con.createEl("p", { attr:{ style:"color:var(--text-muted);font-size:13px;margin-bottom:10px;" } });
desc.innerHTML = "Search and filter all scraped listings. Click column headers to sort. <strong>Drag column edges</strong> to resize columns. Drag the <strong>bottom-right corner</strong> of the results area to resize height. Click a row to open the property note.";

// ── Filter state ──────────────────────────────────────────────────────────────
let sortCol = "date", sortDir = "asc";
let searchText = "";
let fTiming = "", fAuction = "", fMarketOnly = false, fAgentRec = "";
const fStatus = new Set();
const fState  = new Set();
const fType   = new Set();
let fMinP = 0, fMaxP = Infinity, fMinBmv = 0, fMinYield = 0;

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
  .af-ms-btn::after { content:"▾"; position:absolute; right:7px; top:50%; transform:translateY(-50%); color:var(--text-muted); pointer-events:none; }
  .af-ms-panel {
    display:none; position:absolute; z-index:9999; top:calc(100% + 4px); left:0;
    min-width:180px; max-height:240px; overflow-y:auto;
    background:var(--background-primary);
    border:1px solid var(--background-modifier-border);
    border-radius:6px; padding:4px 0; box-shadow:0 4px 20px rgba(0,0,0,.5);
  }
  .af-ms-panel.open { display:block; }
  .af-ms-ctrl { display:flex; gap:8px; padding:5px 10px 6px; border-bottom:1px solid var(--background-modifier-border); margin-bottom:3px; }
  .af-ms-lnk { cursor:pointer; color:var(--link-color); font-size:11px; }
  .af-ms-lnk:hover { text-decoration:underline; }
  .af-ms-row { display:flex; gap:8px; align-items:center; padding:4px 10px; cursor:pointer; }
  .af-ms-row:hover { background:var(--background-secondary); }
  .af-ms-row label { cursor:pointer; font-size:13px; user-select:none; flex:1; }
  .af-ms-row input[type=checkbox] { cursor:pointer; margin:0; flex-shrink:0; }
  /* ── resizable scroll container ── */
  .af-count { font-size:12px; color:var(--text-muted); margin-bottom:6px; }
  .af-scroll {
    resize:vertical; overflow:auto;
    min-height:320px; max-height:80vh;
    border:1px solid var(--background-modifier-border); border-radius:6px;
  }
  /* ── table ── */
  .af-tbl { width:100%; border-collapse:collapse; font-size:13px; table-layout:fixed; }
  .af-tbl th {
    text-align:left; padding:7px 10px; white-space:nowrap;
    cursor:pointer; user-select:none; position:relative;
    border-bottom:2px solid var(--background-modifier-border); color:var(--text-muted);
    overflow:hidden;
  }
  .af-tbl th:hover { color:var(--text-normal); background:var(--background-secondary); }
  .af-tbl th.sort-asc::after  { content:" ▲"; font-size:10px; }
  .af-tbl th.sort-desc::after { content:" ▼"; font-size:10px; }
  .af-tbl td {
    padding:6px 10px; border-bottom:1px solid var(--background-modifier-border);
    vertical-align:middle; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }
  .af-tbl tr:hover td { background:var(--background-secondary); }
  /* ── column resize handle ── */
  .col-rz {
    position:absolute; right:0; top:0; height:100%; width:5px;
    cursor:col-resize; user-select:none; z-index:2;
  }
  .col-rz:hover, .col-rz.dragging { background:var(--interactive-accent); opacity:.6; }
  /* ── badges ── */
  .af-badge { display:inline-block; padding:1px 7px; border-radius:3px; font-size:11px; font-weight:600; }
  .s-new         { background:#1e3a5f; color:#7eb8f7; }
  .s-reviewing   { background:#2d1e4f; color:#c0a0ff; }
  .s-shortlisted { background:#3d2e00; color:#ffd166; }
  .s-visiting    { background:#3d1e00; color:#ffaa55; }
  .s-bid         { background:#4f1e1e; color:#ff7777; }
  .s-passed      { background:#2a2a2a; color:#888; }
  /* ── agent recommendation badges ── */
  .ar-skip        { background:#2a2a2a; color:#888; }
  .ar-investigate { background:#1e3a5f; color:#7eb8f7; }
  .ar-shortlist   { background:#3d2e00; color:#ffd166; }
  .ar-bid         { background:#1a3d1e; color:#6fcf6f; }
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
const iMinYield = mkInp("Min Yield%",   "e.g. 5",       bar);

// Market-data-only toggle
const mktGrp = bar.createDiv({ cls: "af-grp" });
mktGrp.createEl("span", { cls: "af-lbl", text: "🔬 Market Data" });
const mktWrap = mktGrp.createDiv({ attr: { style: "display:flex;align-items:center;gap:6px;padding:5px 0;" } });
const mktChk  = mktWrap.createEl("input", { attr: { type: "checkbox", id: "af-mkt-only" } });
mktWrap.createEl("label", { attr: { for: "af-mkt-only", style: "font-size:13px;cursor:pointer;" }, text: "Only enriched" });
mktChk.addEventListener("change", () => { fMarketOnly = mktChk.checked; render(); });

// Agent recommendation filter
const sAgentRec = mkSel("🤖 AI Rec", [
  ["","All"], ["bid","🟢 Bid"], ["shortlist","🟠 Shortlist"],
  ["investigate","🟡 Investigate"], ["skip","🔴 Skip"]
], bar);
sAgentRec.addEventListener("change", () => { fAgentRec = sAgentRec.value; render(); });

sTiming.addEventListener ("change", () => { fTiming  = sTiming.value;  render(); });
sAuction.addEventListener("change", () => { fAuction = sAuction.value; render(); });
iMinP.addEventListener   ("input",  () => { fMinP     = parseFloat(iMinP.value)    || 0;        render(); });
iMaxP.addEventListener   ("input",  () => { fMaxP     = parseFloat(iMaxP.value)    || Infinity; render(); });
iMinBmv.addEventListener ("input",  () => { fMinBmv   = parseFloat(iMinBmv.value)  || 0;        render(); });
iMinYield.addEventListener("input", () => { fMinYield = parseFloat(iMinYield.value) || 0;        render(); });

// ── Results area ──────────────────────────────────────────────────────────────
const countDiv  = con.createDiv({ cls: "af-count" });
const scrollWrap = con.createDiv({ cls: "af-scroll" });
const tableWrap  = scrollWrap;  // table renders directly inside scroll container

// Column definitions: key, header label, default sort dir, initial width (px)
const COLS = [
  { key:"address",      label:"Address / Property",  def:"asc",  w:260 },
  { key:"price",        label:"Reserve Price",        def:"asc",  w:120 },
  { key:"bmv",          label:"BMV%",                 def:"desc", w:65  },
  { key:"type",         label:"Type",                 def:"asc",  w:100 },
  { key:"location",     label:"State · City",         def:"asc",  w:150 },
  { key:"date",         label:"Auction Date",         def:"asc",  w:110 },
  { key:"days",         label:"Days Left",            def:"asc",  w:75  },
  { key:"rnd",          label:"Rnd",                  def:"desc", w:45  },
  { key:"mkt_val",      label:"Est. Market",          def:"desc", w:110 },
  { key:"ind_bmv",      label:"Indep. BMV%",          def:"desc", w:90  },
  { key:"yield",        label:"Yield%",               def:"desc", w:70  },
  { key:"rent_est",     label:"Rental Est.",          def:"desc", w:95  },
  { key:"agent_score",  label:"Score",                def:"desc", w:60  },
  { key:"agent_rec",    label:"AI Rec",               def:"asc",  w:110 },
  { key:"status",       label:"Status",               def:"asc",  w:95  },
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
    case "mkt_val":  return p.market_value_est || 0;
    case "ind_bmv":  return p.independent_bmv_pct ?? -9999;
    case "yield":    return p.est_rental_yield || 0;
    case "rent_est": return p.market_rent_est || 0;
    case "agent_score": return p.agent_score ?? -1;
    case "agent_rec": return ["bid","shortlist","investigate","skip"].indexOf(p.agent_recommendation || "");
    case "status":   return p.status || "";
    default:         return "";
  }
}

// Add drag-resize handles to every <th>
function addColResizers(table) {
  table.querySelectorAll("th").forEach(th => {
    const rz = document.createElement("div");
    rz.className = "col-rz";
    th.appendChild(rz);
    let startX, startW;
    rz.addEventListener("mousedown", e => {
      e.stopPropagation();
      rz.classList.add("dragging");
      startX = e.pageX; startW = th.offsetWidth;
      const onMove = e2 => { th.style.width = Math.max(40, startW + e2.pageX - startX) + "px"; };
      const onUp   = () => {
        rz.classList.remove("dragging");
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });
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
    .where(p => !fMinYield || (p.est_rental_yield || 0) >= fMinYield)
    .where(p => !fMarketOnly || p.market_sale_psf)
    .where(p => !fAgentRec   || (p.agent_recommendation || "") === fAgentRec)
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
      attr: { style: "color:var(--text-muted);padding:20px;" }
    });
    return;
  }

  const tbl = tableWrap.createEl("table", { cls: "af-tbl" });

  // colgroup sets initial column widths; individual th.style.width takes over after drag
  const cg = tbl.createEl("colgroup");
  COLS.forEach(c => { const col = cg.createEl("col"); col.style.width = c.w + "px"; });

  const htr = tbl.createEl("thead").createEl("tr");
  for (const col of COLS) {
    const th = htr.createEl("th", { text: col.label });
    if (sortCol === col.key) th.classList.add("sort-" + sortDir);
    th.addEventListener("click", e => {
      if (e.target.classList.contains("col-rz")) return; // ignore drag clicks
      sortDir = (sortCol === col.key) ? (sortDir === "asc" ? "desc" : "asc") : col.def;
      sortCol = col.key;
      render();
    });
  }
  addColResizers(tbl);

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

    // Market columns
    const hasMkt = !!p.market_sale_psf;
    const mktStyle = hasMkt ? "" : "color:var(--text-faint);";
    tr.createEl("td", {
      text: hasMkt ? "RM " + (p.market_value_est || 0).toLocaleString() : "—",
      attr: { style: mktStyle }
    });
    const iBmv = p.independent_bmv_pct;
    const iBmvTd = tr.createEl("td");
    if (hasMkt && iBmv != null) {
      iBmvTd.createEl("span", {
        text: iBmv + "%",
        attr: { style: `font-weight:600;color:${iBmv >= 20 ? "#6fcf6f" : iBmv >= 0 ? "#ffd166" : "#ff7777"};` }
      });
    } else {
      iBmvTd.textContent = "—";
      iBmvTd.setAttribute("style", "color:var(--text-faint);");
    }
    tr.createEl("td", {
      text: hasMkt && p.est_rental_yield != null ? p.est_rental_yield + "%" : "—",
      attr: { style: mktStyle }
    });
    tr.createEl("td", {
      text: hasMkt && p.market_rent_est ? "RM " + p.market_rent_est.toLocaleString() + "/mo" : "—",
      attr: { style: mktStyle }
    });

    // Agent columns
    const hasAgent = !!p.agent_recommendation;
    const agentStyle = hasAgent ? "" : "color:var(--text-faint);";
    const scoreTd = tr.createEl("td");
    if (hasAgent && p.agent_score != null) {
      const sc = p.agent_score;
      scoreTd.createEl("span", {
        text: String(sc),
        attr: { style: `font-weight:600;color:${sc >= 61 ? "#6fcf6f" : sc >= 31 ? "#ffd166" : "#ff7777"};` }
      });
    } else {
      scoreTd.textContent = "—";
      scoreTd.setAttribute("style", "color:var(--text-faint);");
    }
    const recTd = tr.createEl("td");
    if (hasAgent) {
      const recLabel = { skip:"Skip", investigate:"Investigate", shortlist:"Shortlist", bid:"Bid" };
      const recCls   = { skip:"ar-skip", investigate:"ar-investigate", shortlist:"ar-shortlist", bid:"ar-bid" };
      const recIcon  = { skip:"🔴", investigate:"🟡", shortlist:"🟠", bid:"🟢" };
      const rec = p.agent_recommendation || "";
      recTd.createEl("span", {
        cls: "af-badge " + (recCls[rec] || ""),
        text: (recIcon[rec] || "") + " " + (recLabel[rec] || rec)
      });
    } else {
      recTd.textContent = "—";
      recTd.setAttribute("style", "color:var(--text-faint);");
    }

    const tdS = tr.createEl("td");
    tdS.createEl("span", {
      cls: "af-badge " + (badgeCls[p.status] || ""),
      text: p.status || "—"
    });
  }
}

render();
```
