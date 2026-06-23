# 🏠 Auction Property Search

> Use the dropdowns and inputs below to filter all scraped listings. Click any row to open the property note. For map view, open **Map View** and use the **Presets** panel.

```dataviewjs
// ── Auction Property Filter Dashboard ────────────────────────────────────────
// Requires: Dataview plugin enabled

const con = this.container;

// ── Inline styles ─────────────────────────────────────────────────────────────
const sty = con.createEl("style");
sty.textContent = `
  .af-bar   { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:14px; align-items:flex-end; }
  .af-grp   { display:flex; flex-direction:column; }
  .af-lbl   { font-size:11px; color:var(--text-muted); margin-bottom:3px; }
  .af-sel, .af-inp {
    padding:5px 8px; border-radius:5px;
    background:var(--background-secondary);
    border:1px solid var(--background-modifier-border);
    color:var(--text-normal); font-size:13px; min-width:130px; }
  .af-inp   { min-width:100px; }
  .af-count { font-size:12px; color:var(--text-muted); margin-bottom:8px; }
  .af-tbl   { width:100%; border-collapse:collapse; font-size:13px; }
  .af-tbl th { text-align:left; padding:7px 10px; border-bottom:2px solid var(--background-modifier-border); color:var(--text-muted); white-space:nowrap; }
  .af-tbl td { padding:6px 10px; border-bottom:1px solid var(--background-modifier-border); vertical-align:top; }
  .af-tbl tr:hover td { background:var(--background-secondary); }
  .af-badge { display:inline-block; padding:1px 7px; border-radius:3px; font-size:11px; font-weight:600; }
  .s-new         { background:#1e3a5f; color:#7eb8f7; }
  .s-reviewing   { background:#2d1e4f; color:#c0a0ff; }
  .s-shortlisted { background:#3d2e00; color:#ffd166; }
  .s-visiting    { background:#3d1e00; color:#ffaa55; }
  .s-bid         { background:#4f1e1e; color:#ff7777; }
  .s-passed      { background:#2a2a2a; color:#888; }
`;

// ── Filter bar ────────────────────────────────────────────────────────────────
const bar = con.createDiv({ cls: "af-bar" });

function mkSel(label, options, parent) {
  const g = parent.createDiv({ cls: "af-grp" });
  g.createEl("span", { cls: "af-lbl", text: label });
  const s = g.createEl("select", { cls: "af-sel" });
  options.forEach(([v, t]) => s.createEl("option", { value: v, text: t }));
  return s;
}
function mkInp(label, ph, parent) {
  const g = parent.createDiv({ cls: "af-grp" });
  g.createEl("span", { cls: "af-lbl", text: label });
  const i = g.createEl("input", { cls: "af-inp", attr: { type: "number", placeholder: ph } });
  return i;
}

const sTiming  = mkSel("📅 Timing", [
  ["","All"], ["upcoming","⏳ Upcoming"], ["past","✅ Past"]
], bar);

const sStatus  = mkSel("🔖 Status", [
  ["","All Status"], ["new","New"], ["reviewing","Reviewing"],
  ["shortlisted","Shortlisted"], ["visiting","Visiting"], ["bid","Bid"], ["passed","Passed"]
], bar);

const sState   = mkSel("📍 State", [
  ["","All States"],
  ["Johor","Johor"], ["Kedah","Kedah"], ["Kelantan","Kelantan"],
  ["Kuala Lumpur","Kuala Lumpur"], ["Melaka","Melaka"],
  ["Negeri Sembilan","Negeri Sembilan"], ["Pahang","Pahang"],
  ["Penang","Penang"], ["Perak","Perak"], ["Perlis","Perlis"],
  ["Putrajaya","Putrajaya"], ["Sabah","Sabah"], ["Sarawak","Sarawak"],
  ["Selangor","Selangor"], ["Terengganu","Terengganu"]
], bar);

const sType    = mkSel("🏠 Type", [
  ["","All Types"],
  ["apartment","Apartment"], ["bungalow","Bungalow"],
  ["condominium","Condominium"], ["flat","Flat"],
  ["land","Land"], ["residential","Residential"],
  ["semi_detached","Semi-D"], ["shop","Shop / Office"],
  ["terrace","Terrace"], ["townhouse","Townhouse"], ["warehouse","Warehouse"]
], bar);

const sAuction = mkSel("⚖️ Auction", [
  ["","All"], ["LACA","LACA"], ["Non-LACA","Non-LACA"]
], bar);

const iMinP    = mkInp("Min Price (RM)", "100000", bar);
const iMaxP    = mkInp("Max Price (RM)", "1000000", bar);
const iMinBmv  = mkInp("Min BMV%", "0", bar);

const sSort    = mkSel("↕ Sort", [
  ["date_asc","Date ↑"], ["date_desc","Date ↓"],
  ["price_asc","Price ↑"], ["price_desc","Price ↓"],
  ["bmv_desc","BMV% ↓"], ["count_desc","Auction Round ↓"]
], bar);

// ── Results area ──────────────────────────────────────────────────────────────
const countDiv  = con.createDiv({ cls: "af-count" });
const tableWrap = con.createDiv();

const today = new Date().toISOString().slice(0, 10);
const badgeCls = {
  new: "s-new", reviewing: "s-reviewing", shortlisted: "s-shortlisted",
  visiting: "s-visiting", bid: "s-bid", passed: "s-passed"
};

function render() {
  tableWrap.empty();

  const timing  = sTiming.value;
  const status  = sStatus.value;
  const state   = sState.value;
  const type    = sType.value;
  const auction = sAuction.value;
  const minP    = parseFloat(iMinP.value)   || 0;
  const maxP    = parseFloat(iMaxP.value)   || Infinity;
  const minBmv  = parseFloat(iMinBmv.value) || 0;
  const sort    = sSort.value;

  let pages = dv.pages('"Properties"')
    .where(p => !status  || p.status === status)
    .where(p => !state   || (p.state || "").includes(state))
    .where(p => !type    || (p.property_type || "").toLowerCase() === type.toLowerCase())
    .where(p => !auction || (p.auction_type || "") === auction)
    .where(p => (p.reserve_price || 0) >= minP && (p.reserve_price || 0) <= maxP)
    .where(p => (p.bmv_pct || 0) >= minBmv)
    .where(p => {
      if (!timing) return true;
      const d = p.auction_date ? String(p.auction_date).slice(0, 10) : "";
      return timing === "upcoming" ? d >= today : d < today;
    });

  if      (sort === "date_asc")   pages = pages.sort(p => p.auction_date,   "asc");
  else if (sort === "date_desc")  pages = pages.sort(p => p.auction_date,   "desc");
  else if (sort === "price_asc")  pages = pages.sort(p => p.reserve_price || 0, "asc");
  else if (sort === "price_desc") pages = pages.sort(p => p.reserve_price || 0, "desc");
  else if (sort === "bmv_desc")   pages = pages.sort(p => p.bmv_pct || 0,   "desc");
  else if (sort === "count_desc") pages = pages.sort(p => p.auction_count || 1, "desc");

  const arr = pages.array();
  countDiv.textContent = `${arr.length} properties found`;

  if (!arr.length) {
    tableWrap.createEl("p", {
      text: "No properties match the selected filters.",
      attr: { style: "color:var(--text-muted); padding:20px 0;" }
    });
    return;
  }

  const tbl  = tableWrap.createEl("table", { cls: "af-tbl" });
  const htr  = tbl.createEl("thead").createEl("tr");
  ["Address / Property", "Reserve Price", "BMV%", "Type", "State · City", "Auction Date", "Days Left", "Rnd", "Status"]
    .forEach(h => htr.createEl("th", { text: h }));

  const tb = tbl.createEl("tbody");
  for (const p of arr) {
    const tr = tb.createEl("tr");

    // Clickable address link
    const td0 = tr.createEl("td");
    const a = td0.createEl("a", {
      cls: "internal-link",
      attr: { "data-href": p.file.path, "href": p.file.path }
    });
    const addr = p.address || p.file.name.replace(/\.md$/, "");
    a.textContent = addr.length > 50 ? addr.slice(0, 48) + "…" : addr;
    if (addr.length > 50) a.setAttribute("title", addr);

    tr.createEl("td", { text: "RM " + (p.reserve_price || 0).toLocaleString() });
    tr.createEl("td", { text: (p.bmv_pct || 0) + "%" });
    tr.createEl("td", { text: (p.property_type || "").replace(/_/g, " ") });
    tr.createEl("td", { text: (p.state || "—") + " · " + (p.city || "—") });
    tr.createEl("td", { text: p.auction_date ? String(p.auction_date).slice(0, 10) : "—" });
    tr.createEl("td", { text: p.days_to_auction != null ? String(p.days_to_auction) + "d" : "—" });
    tr.createEl("td", { text: String(p.auction_count || 1) });

    const tdS  = tr.createEl("td");
    const cls  = "af-badge " + (badgeCls[p.status] || "");
    tdS.createEl("span", { cls, text: p.status || "—" });
  }
}

[sTiming, sStatus, sState, sType, sAuction, sSort]
  .forEach(el => el.addEventListener("change", render));
[iMinP, iMaxP, iMinBmv]
  .forEach(el => el.addEventListener("input", render));

render();
```
