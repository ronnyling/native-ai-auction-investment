# 🏠 Auction Property Search

  

```dataviewjs

const con = this.container;

  

// =====================

// DESCRIPTION

// =====================

con.createEl("p", {

  text: "Decision dashboard. Top = WHAT to buy. Market = WHY. AI = CONFIDENCE.",

  attr: { style: "color:var(--text-muted);font-size:13px;margin-bottom:10px;" }

});

  

// =====================

// STATE

// =====================

let searchText = "";

  

// =====================

// STYLES

// =====================

const style = document.createElement("style");

style.textContent = `

.af-search {

  width:100%;

  padding:10px;

  margin-bottom:12px;

  border-radius:8px;

  background:var(--background-secondary);

  border:1px solid var(--background-modifier-border);

}

  

.af-scroll {

  overflow:auto;

  max-height:60vh;

  border:1px solid var(--background-modifier-border);

  border-radius:8px;

  margin-bottom:20px;

}

  

.af-tbl {

  width:100%;

  border-collapse:collapse;

  font-size:13px;

}

  

.af-tbl th {

  position: sticky;

  top: 0;

  background: var(--background-primary);

  z-index: 5;

  text-align:left;

  padding:8px;

  border-bottom:2px solid var(--background-modifier-border);

}

  

.af-tbl td {

  padding:7px;

  border-bottom:1px solid var(--background-modifier-border);

}

  

.af-tbl tr:hover td {

  background:var(--background-secondary);

}

  

.af-deal {

  background:rgba(0,255,100,0.05);

}

`;

con.appendChild(style);

  

// =====================

// SEARCH

// =====================

const input = con.createEl("input", {

  cls: "af-search",

  attr: { placeholder: "Search address, city..." }

});

  

input.addEventListener("input", () => {

  searchText = input.value.toLowerCase();

  render();

});

  

// =====================

// DATA

// =====================

function getData() {

  return dv.pages('"Properties"')

    .where(p => {

      if (!searchText) return true;

      return (p.address || "")

        .toLowerCase()

        .includes(searchText);

    })

    .array();

}

  

// =====================

// TABLE RENDER

// =====================

function drawTable(title, cols, rows) {

  con.createEl("h3", { text: title });

  

  const wrap = con.createDiv({ cls: "af-scroll" });

  const table = wrap.createEl("table", { cls: "af-tbl" });

  

  const thead = table.createEl("thead").createEl("tr");

  cols.forEach(c => {

    thead.createEl("th", { text: c.label });

  });

  

  const tbody = table.createEl("tbody");

  

  rows.forEach(p => {

    const tr = tbody.createEl("tr");

  

    if ((p.bmv_pct || 0) >= 25) {

      tr.classList.add("af-deal");

    }

  

    cols.forEach(c => {

      const td = tr.createEl("td");

  

      if (c.key === "address") {

        const text = (p.address || p.file.name.slice(0, 45));

        td.createEl("a", {

          text: text,

          attr: { href: p.file.path }

        });

      }

      else if (c.key === "price") {

        td.textContent = "RM " + (p.reserve_price || 0).toLocaleString();

      }

      else if (c.key === "bmv") {

        td.textContent = (p.bmv_pct || 0) + "%";

      }

      else if (c.key === "location") {

        td.textContent = (p.state || "") + " · " + (p.city || "");

      }

      else if (c.key === "date") {

        td.textContent = String(p.auction_date || "").slice(0,10);

      }

      else if (c.key === "agent_rec") {

        td.textContent = p.agent_recommendation || "—";

      }

      else if (c.key === "status") {

        td.textContent = p.status || "—";

      }

      else if (c.key === "mkt_val") {

        td.textContent = p.market_value_est ? "RM " + p.market_value_est.toLocaleString() : "—";

      }

      else if (c.key === "ind_bmv") {

        td.textContent = p.independent_bmv_pct ? p.independent_bmv_pct + "%" : "—";

      }

      else if (c.key === "yield") {

        td.textContent = p.est_rental_yield ? p.est_rental_yield + "%" : "—";

      }

      else if (c.key === "score") {

        td.textContent = p.agent_score || "—";

      }

    });

  });

}

  

// =====================

// MAIN RENDER

// =====================

function render() {

  con.querySelectorAll(".af-scroll, h3").forEach(el => el.remove());

  

  const data = getData();

  

  // PRIMARY

  drawTable("🔥 Top Deals", [

    { key:"address", label:"Property" },

    { key:"price", label:"Price" },

    { key:"bmv", label:"BMV%" },

    { key:"location", label:"Location" },

    { key:"date", label:"Date" },

    { key:"agent_rec", label:"AI" },

    { key:"status", label:"Status" }

  ], data);

  

  // MARKET

  drawTable("📊 Market", [

    { key:"address", label:"Property" },

    { key:"mkt_val", label:"Market" },

    { key:"ind_bmv", label:"True BMV%" },

    { key:"yield", label:"Yield" }

  ], data);

  

  // AI

  drawTable("🤖 AI", [

    { key:"address", label:"Property" },

    { key:"score", label:"Score" },

    { key:"agent_rec", label:"Recommendation" },

    { key:"status", label:"Status" }

  ], data);

}

  

render();

```