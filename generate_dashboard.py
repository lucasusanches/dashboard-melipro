"""
MeliPro Dashboard Generator
Queries BigQuery and generates a self-contained HTML dashboard.
Run daily at 08:00 via Windows Task Scheduler.
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime
from google.cloud import bigquery

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ── Config ──────────────────────────────────────────────────────────────────
PROJECT = "meli-bi-data"
TABLE   = f"`{PROJECT}.WHOWNER.DM_EFICIENCIA_MLB`"

SELLERS = {
    383523670:  {"name": "Colibri Decor",           "group": "COLIBRI"},
    794123311:  {"name": "Kappesberg",               "group": "KAPPESBERG"},
    568773774:  {"name": "Linea Brasil",             "group": "LINEA"},
    70123968:   {"name": "Outlet das Fábricas RS",   "group": "Outlet das Fábricas"},
    2355501248: {"name": "Outlet das Fábricas BA",   "group": "Outlet das Fábricas"},
    638325656:  {"name": "Outlet das Fábricas ES",   "group": "Outlet das Fábricas"},
    1802758219: {"name": "Móveis Província",         "group": "Móveis Província"},
    700583148:  {"name": "Decorise",                 "group": "Decorise"},
}

CUST_IDS = list(SELLERS.keys())
IDS_STR  = ",".join(str(x) for x in CUST_IDS)

FF_TYPES      = ("fulfillment",)
XD_TYPES      = ("cross_docking", "xd_drop_off")
SS_TYPES      = ("self_service", "drop_off", "default")

client = bigquery.Client(project=PROJECT)


# ── Query helpers ────────────────────────────────────────────────────────────
def run(sql: str) -> list[dict]:
    rows = list(client.query(sql).result())
    return [dict(r) for r in rows]


# ── Queries ──────────────────────────────────────────────────────────────────
def q_geral_monthly():
    """GMV, SI, ASP por seller por mês — últimos 25 meses (YoY + MoM)."""
    return run(f"""
        SELECT
            FORMAT_DATE('%Y-%m', ORD_CLOSED_DT)      AS mes,
            CUS_CUST_ID_SEL                           AS cust_id,
            ROUND(SUM(GMV_LC), 2)                     AS gmv,
            SUM(SI)                                   AS si,
            ROUND(SAFE_DIVIDE(SUM(GMV_LC), SUM(SI)), 2) AS asp
        FROM {TABLE}
        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
          AND GMV_FLG = TRUE
          AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 25 MONTH)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_geral_daily():
    """GMV, SI por seller por dia — últimos 90 dias."""
    return run(f"""
        SELECT
            CAST(ORD_CLOSED_DT AS STRING)             AS dia,
            CUS_CUST_ID_SEL                           AS cust_id,
            ROUND(SUM(GMV_LC), 2)                     AS gmv,
            SUM(SI)                                   AS si
        FROM {TABLE}
        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
          AND GMV_FLG = TRUE
          AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_logistica_monthly():
    """Logística por tipo por seller por mês."""
    ff   = "', '".join(FF_TYPES)
    xd   = "', '".join(XD_TYPES)
    ss   = "', '".join(SS_TYPES)
    return run(f"""
        SELECT
            FORMAT_DATE('%Y-%m', ORD_CLOSED_DT)         AS mes,
            CUS_CUST_ID_SEL                              AS cust_id,
            ROUND(SUM(GMV_LC), 2)                        AS gmv_total,
            SUM(SI)                                      AS si_total,
            ROUND(SUM(CASE WHEN LOGISTIC_TYPE IN ('{ff}') THEN GMV_LC ELSE 0 END), 2) AS gmv_ff,
            SUM(CASE WHEN LOGISTIC_TYPE IN ('{ff}') THEN SI ELSE 0 END)               AS si_ff,
            ROUND(SUM(CASE WHEN LOGISTIC_TYPE IN ('{xd}') THEN GMV_LC ELSE 0 END), 2) AS gmv_xd,
            SUM(CASE WHEN LOGISTIC_TYPE IN ('{xd}') THEN SI ELSE 0 END)               AS si_xd,
            ROUND(SUM(CASE WHEN LOGISTIC_TYPE IN ('{ss}') THEN GMV_LC ELSE 0 END), 2) AS gmv_ss,
            SUM(CASE WHEN LOGISTIC_TYPE IN ('{ss}') THEN SI ELSE 0 END)               AS si_ss
        FROM {TABLE}
        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
          AND GMV_FLG = TRUE
          AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 25 MONTH)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_ads_monthly():
    """ADS: investimento, GMV ads, ROAS por seller por mês."""
    return run(f"""
        SELECT
            FORMAT_DATE('%Y-%m', ORD_CLOSED_DT)                               AS mes,
            CUS_CUST_ID_SEL                                                    AS cust_id,
            ROUND(SUM(GMV_LC), 2)                                              AS gmv,
            ROUND(SUM(AUTOMATIC_CAMPAIGN_INVESTMENT_LC), 2)                    AS ads_invest,
            ROUND(SUM(CASE WHEN AUTOMATIC_CAMPAIGN_FLG = TRUE THEN GMV_LC ELSE 0 END), 2) AS gmv_ads
        FROM {TABLE}
        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
          AND GMV_FLG = TRUE
          AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 25 MONTH)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_investimentos_monthly():
    """Cupons + Rebate pré-negociado + Rebate outras frentes por seller por mês."""
    return run(f"""
        SELECT
            FORMAT_DATE('%Y-%m', ORD_CLOSED_DT)           AS mes,
            CUS_CUST_ID_SEL                                AS cust_id,
            ROUND(SUM(GMV_LC), 2)                          AS gmv,
            ROUND(SUM(CPN_AMOUNT_LC), 2)                   AS cupons,
            ROUND(SUM(REBATES_MANUAIS_LC), 2)              AS rebate_pre,
            ROUND(SUM(CP_INVESTMENTS_LC), 2)               AS rebate_outras,
            ROUND(SUM(TOTAL_INVESTMENTS_LC), 2)            AS total_invest
        FROM {TABLE}
        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
          AND GMV_FLG = TRUE
          AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 25 MONTH)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_buybox_monthly():
    """BuyBox: pedidos totais, pedidos BB, GMV BB por seller por mês."""
    return run(f"""
        SELECT
            FORMAT_DATE('%Y-%m', ORD_CLOSED_DT)                          AS mes,
            CUS_CUST_ID_SEL                                               AS cust_id,
            COUNT(DISTINCT ORD_ORDER_ID)                                  AS pedidos_total,
            COUNT(DISTINCT CASE WHEN BUYBOX_FLG = TRUE THEN ORD_ORDER_ID END) AS pedidos_bb,
            ROUND(SUM(GMV_LC), 2)                                         AS gmv_total,
            ROUND(SUM(CASE WHEN BUYBOX_FLG = TRUE THEN GMV_LC ELSE 0 END), 2) AS gmv_bb
        FROM {TABLE}
        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
          AND GMV_FLG = TRUE
          AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 25 MONTH)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_catalogo_top_items():
    """Top 20 itens por seller nos últimos 3 meses."""
    return run(f"""
        SELECT
            CUS_CUST_ID_SEL                                        AS cust_id,
            ITE_ITEM_ID                                            AS item_id,
            MAX(ITE_ITEM_TITLE)                                    AS titulo,
            ROUND(SUM(GMV_LC), 2)                                  AS gmv,
            SUM(SI)                                                AS si,
            ROUND(SAFE_DIVIDE(SUM(GMV_LC), SUM(SI)), 2)            AS asp,
            ROUND(SUM(CASE WHEN BUYBOX_FLG = TRUE THEN GMV_LC ELSE 0 END), 2) AS gmv_bb
        FROM {TABLE}
        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
          AND GMV_FLG = TRUE
          AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
        GROUP BY 1, 2
        QUALIFY ROW_NUMBER() OVER (PARTITION BY CUS_CUST_ID_SEL ORDER BY SUM(GMV_LC) DESC) <= 20
        ORDER BY 1, 4 DESC
    """)


# ── Data assembly ────────────────────────────────────────────────────────────
def build_dataset() -> dict:
    print("Consultando BQ...")
    print("  → Geral mensal...")
    geral_m  = q_geral_monthly()
    print("  → Geral diário...")
    geral_d  = q_geral_daily()
    print("  → Logística...")
    log_m    = q_logistica_monthly()
    print("  → ADS...")
    ads_m    = q_ads_monthly()
    print("  → Investimentos...")
    inv_m    = q_investimentos_monthly()
    print("  → BuyBox...")
    bb_m     = q_buybox_monthly()
    print("  → Catálogo top itens...")
    cat      = q_catalogo_top_items()
    print("  Consultas concluídas.")

    # Convert date/Decimal to serialisable types
    def clean(obj):
        if isinstance(obj, (date, datetime)):
            return str(obj)
        return obj

    def clean_rows(rows):
        return [{k: clean(v) for k, v in row.items()} for row in rows]

    sellers_meta = [
        {"cust_id": cid, "name": info["name"], "group": info["group"]}
        for cid, info in SELLERS.items()
    ]

    return {
        "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "sellers":    sellers_meta,
        "geral_monthly":       clean_rows(geral_m),
        "geral_daily":         clean_rows(geral_d),
        "logistica_monthly":   clean_rows(log_m),
        "ads_monthly":         clean_rows(ads_m),
        "investimentos_monthly": clean_rows(inv_m),
        "buybox_monthly":      clean_rows(bb_m),
        "catalogo_items":      clean_rows(cat),
    }


# ── HTML template ─────────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MeliPro Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
  --ml-yellow:#FFE600;--ml-blue:#2D3277;--ml-blue2:#3483FA;
  --bg:#F5F5F5;--card:#fff;--txt:#333;--muted:#666;
  --green:#00A650;--red:#E83C49;--border:#E0E0E0;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Proxima Nova',Arial,sans-serif;background:var(--bg);color:var(--txt);font-size:14px}

/* Header */
.header{background:var(--ml-yellow);padding:12px 24px;display:flex;align-items:center;gap:16px;box-shadow:0 2px 4px rgba(0,0,0,.12)}
.logo{height:38px}
.header-title{font-size:20px;font-weight:700;color:var(--ml-blue);letter-spacing:-.3px}
.header-sub{font-size:12px;color:var(--ml-blue);opacity:.7;margin-top:2px}
.updated{margin-left:auto;font-size:11px;color:var(--ml-blue);opacity:.6}

/* Controls */
.controls{background:#fff;border-bottom:1px solid var(--border);padding:10px 24px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.ctrl-label{font-size:12px;font-weight:600;color:var(--muted);margin-right:4px}
.btn-group{display:flex;gap:4px}
.btn{padding:5px 12px;border:1px solid var(--border);border-radius:20px;background:#fff;cursor:pointer;font-size:12px;color:var(--txt);transition:all .15s}
.btn:hover{background:var(--ml-yellow);border-color:var(--ml-yellow);color:var(--ml-blue)}
.btn.active{background:var(--ml-blue);color:#fff;border-color:var(--ml-blue)}
select.sel{padding:5px 10px;border:1px solid var(--border);border-radius:20px;font-size:12px;outline:none;cursor:pointer;background:#fff;color:var(--txt)}

/* Tabs */
.tabs{display:flex;background:#fff;border-bottom:2px solid var(--border);padding:0 24px;gap:0}
.tab{padding:12px 20px;cursor:pointer;font-size:13px;font-weight:600;color:var(--muted);border-bottom:3px solid transparent;margin-bottom:-2px;transition:all .15s}
.tab:hover{color:var(--ml-blue)}
.tab.active{color:var(--ml-blue);border-bottom-color:var(--ml-blue2)}

/* Seller sub-tabs */
.seller-tabs{display:flex;background:#F8F8F8;border-bottom:1px solid var(--border);padding:0 24px;gap:0;overflow-x:auto}
.stab{padding:8px 14px;cursor:pointer;font-size:12px;font-weight:500;color:var(--muted);border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap;transition:all .15s}
.stab:hover{color:var(--ml-blue)}
.stab.active{color:var(--ml-blue2);border-bottom-color:var(--ml-blue2)}

/* Content */
.content{padding:20px 24px;max-width:1600px;margin:0 auto}
.tab-content{display:none}
.tab-content.active{display:block}

/* KPI Cards */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:20px}
.kpi-card{background:var(--card);border-radius:8px;padding:16px 18px;border:1px solid var(--border);box-shadow:0 1px 3px rgba(0,0,0,.06)}
.kpi-label{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.kpi-value{font-size:24px;font-weight:700;color:var(--ml-blue);margin:6px 0 4px}
.kpi-delta{font-size:12px;display:flex;gap:8px}
.delta-pos{color:var(--green)}
.delta-neg{color:var(--red)}
.delta-neu{color:var(--muted)}

/* Charts */
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px;margin-bottom:20px}
.chart-card{background:var(--card);border-radius:8px;padding:16px;border:1px solid var(--border);box-shadow:0 1px 3px rgba(0,0,0,.06)}
.chart-title{font-size:13px;font-weight:700;color:var(--ml-blue);margin-bottom:12px}
.chart-wrap{position:relative;height:240px}

/* Table */
.table-wrap{background:var(--card);border-radius:8px;border:1px solid var(--border);overflow:auto;box-shadow:0 1px 3px rgba(0,0,0,.06);margin-bottom:20px}
table{width:100%;border-collapse:collapse}
thead tr{background:var(--ml-blue);color:#fff}
th{padding:10px 12px;text-align:right;font-size:11px;font-weight:600;letter-spacing:.4px;white-space:nowrap}
th:first-child{text-align:left}
tbody tr{border-bottom:1px solid var(--border);transition:background .1s}
tbody tr:hover{background:#FAFAFA}
td{padding:9px 12px;text-align:right;font-size:12px;white-space:nowrap}
td:first-child{text-align:left;font-weight:500}
.tag-pos{color:var(--green);font-weight:600}
.tag-neg{color:var(--red);font-weight:600}

/* Section divider */
.section-title{font-size:14px;font-weight:700;color:var(--ml-blue);margin:18px 0 10px;display:flex;align-items:center;gap:8px}
.section-title::after{content:'';flex:1;height:1px;background:var(--border)}

.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;background:var(--ml-yellow);color:var(--ml-blue)}

/* Responsive */
@media(max-width:600px){
  .kpi-value{font-size:18px}
  .chart-grid{grid-template-columns:1fr}
  .tab{padding:10px 12px;font-size:12px}
}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <svg class="logo" viewBox="0 0 120 38" xmlns="http://www.w3.org/2000/svg">
    <rect width="120" height="38" rx="6" fill="#2D3277"/>
    <text x="8" y="14" fill="#FFE600" font-family="Arial" font-weight="bold" font-size="9">mercado</text>
    <text x="8" y="27" fill="#FFE600" font-family="Arial" font-weight="bold" font-size="11">livre</text>
    <circle cx="96" cy="19" r="12" fill="#FFE600"/>
    <text x="90" y="24" fill="#2D3277" font-family="Arial" font-weight="bold" font-size="14">M</text>
  </svg>
  <div>
    <div class="header-title">MeliPro Dashboard</div>
    <div class="header-sub">Visão 360° da Carteira</div>
  </div>
  <div class="updated" id="updated-at"></div>
</div>

<!-- Controls -->
<div class="controls">
  <span class="ctrl-label">Período:</span>
  <div class="btn-group" id="period-btns">
    <button class="btn" onclick="setPeriod('day',this)">Dia</button>
    <button class="btn" onclick="setPeriod('week',this)">Semana</button>
    <button class="btn active" onclick="setPeriod('month',this)">Mês</button>
    <button class="btn" onclick="setPeriod('quarter',this)">Trimestre</button>
    <button class="btn" onclick="setPeriod('year',this)">Ano</button>
  </div>
  <span class="ctrl-label" style="margin-left:12px">Seller:</span>
  <select class="sel" id="seller-sel" onchange="setSeller(this.value)"></select>
</div>

<!-- Main Tabs -->
<div class="tabs" id="main-tabs">
  <div class="tab active" onclick="setTab('geral',this)">Geral</div>
  <div class="tab" onclick="setTab('logistica',this)">Fulfillment &amp; Logística</div>
  <div class="tab" onclick="setTab('ads',this)">ADS</div>
  <div class="tab" onclick="setTab('investimentos',this)">Investimentos</div>
  <div class="tab" onclick="setTab('catalogo',this)">Catálogo</div>
</div>

<!-- Seller sub-tabs -->
<div class="seller-tabs" id="seller-tabs"></div>

<!-- TAB: Geral -->
<div class="tab-content active" id="tab-geral">
  <div class="content">
    <div class="kpi-grid" id="kpi-geral"></div>
    <div class="chart-grid">
      <div class="chart-card">
        <div class="chart-title">GMV Mensal (R$)</div>
        <div class="chart-wrap"><canvas id="ch-gmv-mes"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">GMV: MoM vs YoY (%)</div>
        <div class="chart-wrap"><canvas id="ch-gmv-delta"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Unidades Vendidas (SI)</div>
        <div class="chart-wrap"><canvas id="ch-si-mes"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">ASP Médio (R$)</div>
        <div class="chart-wrap"><canvas id="ch-asp-mes"></canvas></div>
      </div>
    </div>
    <div class="section-title">Resumo por Seller</div>
    <div class="table-wrap"><table id="tbl-geral-sellers"></table></div>
  </div>
</div>

<!-- TAB: Logística -->
<div class="tab-content" id="tab-logistica">
  <div class="content">
    <div class="kpi-grid" id="kpi-log"></div>
    <div class="chart-grid">
      <div class="chart-card">
        <div class="chart-title">Mix Logístico — GMV (%)</div>
        <div class="chart-wrap"><canvas id="ch-log-mix"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">%FF por Mês</div>
        <div class="chart-wrap"><canvas id="ch-ff-mes"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">GMV por Tipo Logístico</div>
        <div class="chart-wrap"><canvas id="ch-log-gmv"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">SI por Tipo Logístico</div>
        <div class="chart-wrap"><canvas id="ch-log-si"></canvas></div>
      </div>
    </div>
    <div class="section-title">Detalhe por Seller</div>
    <div class="table-wrap"><table id="tbl-log-sellers"></table></div>
  </div>
</div>

<!-- TAB: ADS -->
<div class="tab-content" id="tab-ads">
  <div class="content">
    <div class="kpi-grid" id="kpi-ads"></div>
    <div class="chart-grid">
      <div class="chart-card">
        <div class="chart-title">Investimento ADS Mensal (R$)</div>
        <div class="chart-wrap"><canvas id="ch-ads-invest"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">ROAS Mensal</div>
        <div class="chart-wrap"><canvas id="ch-roas"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">ADS/GMV % Mensal</div>
        <div class="chart-wrap"><canvas id="ch-ads-perc"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Take Rate ADS (%)</div>
        <div class="chart-wrap"><canvas id="ch-take-rate"></canvas></div>
      </div>
    </div>
    <div class="section-title">Detalhe por Seller</div>
    <div class="table-wrap"><table id="tbl-ads-sellers"></table></div>
  </div>
</div>

<!-- TAB: Investimentos -->
<div class="tab-content" id="tab-investimentos">
  <div class="content">
    <div class="kpi-grid" id="kpi-inv"></div>
    <div class="chart-grid">
      <div class="chart-card">
        <div class="chart-title">Investimentos Totais Mensais (R$)</div>
        <div class="chart-wrap"><canvas id="ch-inv-total"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Mix de Investimentos (%)</div>
        <div class="chart-wrap"><canvas id="ch-inv-mix"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Cupons por Mês (R$)</div>
        <div class="chart-wrap"><canvas id="ch-cupons"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Rebates por Mês (R$)</div>
        <div class="chart-wrap"><canvas id="ch-rebates"></canvas></div>
      </div>
    </div>
    <div class="section-title">Detalhe por Seller</div>
    <div class="table-wrap"><table id="tbl-inv-sellers"></table></div>
  </div>
</div>

<!-- TAB: Catálogo -->
<div class="tab-content" id="tab-catalogo">
  <div class="content">
    <div class="section-title">Top Itens por Seller — Últimos 3 meses</div>
    <div class="table-wrap"><table id="tbl-catalogo"></table></div>
  </div>
</div>

<script>
// ── Raw data injected by Python ───────────────────────────────────────────
const RAW = __DATA_PLACEHOLDER__;

// ── State ─────────────────────────────────────────────────────────────────
let state = { period: 'month', seller: 'all', tab: 'geral' };
const charts = {};

// ── Sellers ───────────────────────────────────────────────────────────────
const SELLERS = RAW.sellers;
const GROUPS  = [...new Set(SELLERS.map(s => s.group))];

function sellerIds(selVal) {
  if (selVal === 'all') return SELLERS.map(s => s.cust_id);
  if (GROUPS.includes(selVal)) return SELLERS.filter(s => s.group === selVal).map(s => s.cust_id);
  return [parseInt(selVal)];
}

function sellerLabel(cust_id) {
  return SELLERS.find(s => s.cust_id === cust_id)?.name || cust_id;
}

// ── Period filtering ───────────────────────────────────────────────────────
function periodCutoff(period) {
  const now = new Date();
  switch(period) {
    case 'day':    return new Date(now - 2*86400000).toISOString().slice(0,10);
    case 'week':   return new Date(now - 7*86400000).toISOString().slice(0,10);
    case 'month':  return formatMonth(new Date(now.getFullYear(), now.getMonth()-1, 1));
    case 'quarter':return formatMonth(new Date(now.getFullYear(), now.getMonth()-3, 1));
    case 'year':   return formatMonth(new Date(now.getFullYear()-1, now.getMonth(), 1));
  }
}

function formatMonth(d) { return d.toISOString().slice(0,7); }

function filterRows(rows, ids, period, dateField='mes') {
  const cut = periodCutoff(period);
  return rows.filter(r => sellerIds(ids === 'all' ? 'all' : ids).includes(r.cust_id)
                        && r[dateField] >= cut);
}

function groupBySeller(rows, fields) {
  const out = {};
  const ids = sellerIds(state.seller);
  rows.filter(r => ids.includes(r.cust_id)).forEach(r => {
    if (!out[r.cust_id]) { out[r.cust_id] = {}; fields.forEach(f => out[r.cust_id][f] = 0); }
    fields.forEach(f => out[r.cust_id][f] += (r[f] || 0));
  });
  return out;
}

function aggregateByMonth(rows, fields) {
  const ids = sellerIds(state.seller);
  const cut  = periodCutoff(state.period);
  const out  = {};
  rows.filter(r => ids.includes(r.cust_id) && r.mes >= cut).forEach(r => {
    if (!out[r.mes]) { out[r.mes] = {}; fields.forEach(f => out[r.mes][f] = 0); }
    fields.forEach(f => out[r.mes][f] += (r[f] || 0));
  });
  return out;
}

function aggregateByDay(rows, fields) {
  const ids = sellerIds(state.seller);
  const cut  = periodCutoff(state.period);
  const out  = {};
  rows.filter(r => ids.includes(r.cust_id) && r.dia >= cut).forEach(r => {
    if (!out[r.dia]) { out[r.dia] = {}; fields.forEach(f => out[r.dia][f] = 0); }
    fields.forEach(f => out[r.dia][f] += (r[f] || 0));
  });
  return out;
}

// ── Formatting helpers ─────────────────────────────────────────────────────
const fmtBRL  = v => v == null ? '-' : 'R$ ' + v.toLocaleString('pt-BR',{minimumFractionDigits:0,maximumFractionDigits:0});
const fmtPct  = v => v == null || !isFinite(v) ? '-' : v.toFixed(1) + '%';
const fmtNum  = v => v == null ? '-' : v.toLocaleString('pt-BR');
const fmtDec  = v => v == null ? '-' : v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});

function deltaHtml(pct) {
  if (pct == null || !isFinite(pct)) return '<span class="delta-neu">—</span>';
  const cls = pct >= 0 ? 'delta-pos' : 'delta-neg';
  const arrow = pct >= 0 ? '▲' : '▼';
  return `<span class="${cls}">${arrow} ${Math.abs(pct).toFixed(1)}%</span>`;
}

// ── Chart.js helpers ────────────────────────────────────────────────────────
const ML_COLORS = ['#3483FA','#FFE600','#00A650','#E83C49','#FF7733','#9B59B6','#1ABC9C','#E67E22'];
const ML_COLORS_ALPHA = ML_COLORS.map(c => c + 'CC');

function makeChart(id, type, labels, datasets, opts={}) {
  if (charts[id]) charts[id].destroy();
  const ctx = document.getElementById(id);
  if (!ctx) return;
  charts[id] = new Chart(ctx, {
    type,
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: datasets.length > 1, labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: type === 'bar' || type === 'line' ? {
        x: { ticks: { font: { size: 10 } }, grid: { display: false } },
        y: { ticks: { font: { size: 10 }, callback: opts.yFmt || null }, grid: { color: '#F0F0F0' } }
      } : {},
      ...opts.extra
    }
  });
}

// ── KPI builder ─────────────────────────────────────────────────────────────
function kpiCard(label, value, mom, yoy) {
  return `<div class="kpi-card">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value">${value}</div>
    <div class="kpi-delta">
      <span>MoM: ${deltaHtml(mom)}</span>
      <span>YoY: ${deltaHtml(yoy)}</span>
    </div>
  </div>`;
}

function calcDeltas(monthlyMap, field) {
  const months = Object.keys(monthlyMap).sort();
  if (months.length < 2) return { mom: null, yoy: null };
  const last   = months[months.length - 1];
  const prev   = months[months.length - 2];
  const lastYY = months.find(m => m.slice(0,4) === String(parseInt(last.slice(0,4))-1) && m.slice(5) === last.slice(5));
  const vLast  = monthlyMap[last]?.[field] || 0;
  const vPrev  = monthlyMap[prev]?.[field] || 0;
  const vYY    = lastYY ? (monthlyMap[lastYY]?.[field] || 0) : null;
  const mom    = vPrev ? ((vLast - vPrev) / vPrev) * 100 : null;
  const yoy    = vYY  ? ((vLast - vYY)   / vYY)   * 100 : null;
  return { mom, yoy };
}

// ── RENDER: Geral ─────────────────────────────────────────────────────────
function renderGeral() {
  const monthly = aggregateByMonth(RAW.geral_monthly, ['gmv','si']);
  const months  = Object.keys(monthly).sort();
  const gmvLast = monthly[months[months.length-1]]?.gmv || 0;
  const siLast  = monthly[months[months.length-1]]?.si  || 0;
  const aspLast = siLast ? gmvLast / siLast : 0;
  const gd = calcDeltas(monthly, 'gmv');
  const sd = calcDeltas(monthly, 'si');
  const aspM = aggregateByMonth(RAW.geral_monthly, ['gmv','si']);
  const aspMonths = Object.keys(aspM).sort();
  const aspPrev = aspMonths.length > 1
    ? (aspM[aspMonths[aspMonths.length-2]]?.gmv / (aspM[aspMonths[aspMonths.length-2]]?.si || 1)) : 0;
  const aspYYKey = aspMonths.find(m => m.slice(0,4) === String(parseInt(aspMonths[aspMonths.length-1].slice(0,4))-1) && m.slice(5) === aspMonths[aspMonths.length-1].slice(5));
  const aspYY = aspYYKey ? (aspM[aspYYKey]?.gmv / (aspM[aspYYKey]?.si || 1)) : null;
  const aspMomPct = aspPrev ? ((aspLast - aspPrev)/aspPrev)*100 : null;
  const aspYoyPct = aspYY  ? ((aspLast - aspYY)/aspYY)*100 : null;

  document.getElementById('kpi-geral').innerHTML =
    kpiCard('GMV',   fmtBRL(gmvLast), gd.mom, gd.yoy) +
    kpiCard('SI (Unidades)', fmtNum(siLast), sd.mom, sd.yoy) +
    kpiCard('ASP',   fmtBRL(aspLast), aspMomPct, aspYoyPct) +
    `<div class="kpi-card"><div class="kpi-label">Sellers Ativos</div>
     <div class="kpi-value" style="font-size:28px">${sellerIds(state.seller).length}</div>
     <div class="kpi-delta"><span class="delta-neu">Carteira MeliPro</span></div></div>`;

  // GMV chart
  makeChart('ch-gmv-mes','bar', months.slice(-13),
    [{ label:'GMV', data: months.slice(-13).map(m=>monthly[m]?.gmv||0),
       backgroundColor:'#3483FA', borderRadius:4 }],
    { yFmt: v => 'R$'+v.toLocaleString('pt-BR',{notation:'compact'}) });

  // Delta chart
  const deltaLabels = months.slice(-12);
  const momData = deltaLabels.map((m,i) => {
    const prev = months[months.indexOf(m)-1];
    if (!prev) return null;
    const vL = monthly[m]?.gmv||0, vP = monthly[prev]?.gmv||0;
    return vP ? ((vL-vP)/vP)*100 : null;
  });
  const yoyData = deltaLabels.map(m => {
    const yy = months.find(x => x.slice(0,4)===String(parseInt(m.slice(0,4))-1)&&x.slice(5)===m.slice(5));
    if (!yy) return null;
    const vL = monthly[m]?.gmv||0, vY = monthly[yy]?.gmv||0;
    return vY ? ((vL-vY)/vY)*100 : null;
  });
  makeChart('ch-gmv-delta','line', deltaLabels, [
    { label:'MoM%', data:momData, borderColor:'#3483FA', backgroundColor:'#3483FA33', fill:true, tension:.3, pointRadius:3 },
    { label:'YoY%', data:yoyData, borderColor:'#E83C49', backgroundColor:'#E83C4933', fill:true, tension:.3, pointRadius:3 }
  ], { yFmt: v => v?.toFixed(1)+'%' });

  // SI chart
  makeChart('ch-si-mes','bar', months.slice(-13),
    [{ label:'SI', data:months.slice(-13).map(m=>monthly[m]?.si||0),
       backgroundColor:'#00A650', borderRadius:4 }]);

  // ASP chart
  const aspData = months.slice(-13).map(m => {
    const g=monthly[m]?.gmv||0, s=monthly[m]?.si||0;
    return s ? +(g/s).toFixed(2) : null;
  });
  makeChart('ch-asp-mes','line', months.slice(-13),
    [{ label:'ASP', data:aspData, borderColor:'#FF7733', backgroundColor:'#FF773333', fill:true, tension:.3, pointRadius:3 }],
    { yFmt: v => 'R$'+v?.toLocaleString('pt-BR',{maximumFractionDigits:0}) });

  // Seller summary table
  const byS = groupBySeller(
    RAW.geral_monthly.filter(r => r.mes >= periodCutoff(state.period)),
    ['gmv','si']
  );
  const totalGmv = Object.values(byS).reduce((a,v)=>a+(v.gmv||0),0);
  let html = `<thead><tr>
    <th>Seller</th><th>GMV</th><th>SI</th><th>ASP</th><th>Share GMV</th>
  </tr></thead><tbody>`;
  Object.entries(byS).sort((a,b)=>b[1].gmv-a[1].gmv).forEach(([cid,v])=>{
    const asp = v.si ? v.gmv/v.si : 0;
    const share = totalGmv ? (v.gmv/totalGmv)*100 : 0;
    html += `<tr><td>${sellerLabel(+cid)}</td><td>${fmtBRL(v.gmv)}</td>
      <td>${fmtNum(v.si)}</td><td>${fmtBRL(asp)}</td>
      <td><span class="badge">${fmtPct(share)}</span></td></tr>`;
  });
  html += '</tbody>';
  document.getElementById('tbl-geral-sellers').innerHTML = html;
}

// ── RENDER: Logística ─────────────────────────────────────────────────────
function renderLogistica() {
  const monthly = aggregateByMonth(RAW.logistica_monthly, ['gmv_total','si_total','gmv_ff','si_ff','gmv_xd','si_xd','gmv_ss','si_ss']);
  const months  = Object.keys(monthly).sort();
  const last    = months[months.length-1] || '';
  const l = monthly[last] || {};
  const ffPct  = l.gmv_total ? (l.gmv_ff/l.gmv_total)*100 : 0;
  const xdPct  = l.gmv_total ? (l.gmv_xd/l.gmv_total)*100 : 0;
  const ssPct  = l.gmv_total ? (l.gmv_ss/l.gmv_total)*100 : 0;
  const ffD = calcDeltas(monthly,'gmv_ff');

  document.getElementById('kpi-log').innerHTML =
    kpiCard('%FF (GMV)',  fmtPct(ffPct), ffD.mom, ffD.yoy) +
    kpiCard('GMV FF',    fmtBRL(l.gmv_ff||0), null, null) +
    kpiCard('%XD (GMV)', fmtPct(xdPct), null, null) +
    kpiCard('%SS (GMV)', fmtPct(ssPct), null, null);

  // Mix donut
  makeChart('ch-log-mix','doughnut',
    ['Fulfillment','Cross Docking','Self Service'],
    [{ data:[ffPct,xdPct,ssPct], backgroundColor:['#3483FA','#FFE600','#00A650'], borderWidth:0 }],
    { extra: { plugins:{ legend:{ display:true, position:'bottom' } } } });

  // %FF line
  const ffPerc = months.slice(-13).map(m => {
    const d = monthly[m];
    return d?.gmv_total ? +((d.gmv_ff/d.gmv_total)*100).toFixed(1) : null;
  });
  makeChart('ch-ff-mes','line', months.slice(-13),
    [{ label:'%FF', data:ffPerc, borderColor:'#3483FA', backgroundColor:'#3483FA22', fill:true, tension:.3, pointRadius:3 }],
    { yFmt: v => v?.toFixed(1)+'%' });

  // GMV bars
  makeChart('ch-log-gmv','bar', months.slice(-13), [
    { label:'FF',  data:months.slice(-13).map(m=>monthly[m]?.gmv_ff||0), backgroundColor:'#3483FA', borderRadius:3 },
    { label:'XD',  data:months.slice(-13).map(m=>monthly[m]?.gmv_xd||0), backgroundColor:'#FFE600', borderRadius:3 },
    { label:'SS',  data:months.slice(-13).map(m=>monthly[m]?.gmv_ss||0), backgroundColor:'#00A650', borderRadius:3 },
  ], { extra: { scales: { x:{ stacked:true,grid:{display:false} }, y:{ stacked:true,grid:{color:'#F0F0F0'} } } } });

  // SI bars
  makeChart('ch-log-si','bar', months.slice(-13), [
    { label:'FF',  data:months.slice(-13).map(m=>monthly[m]?.si_ff||0), backgroundColor:'#3483FA', borderRadius:3 },
    { label:'XD',  data:months.slice(-13).map(m=>monthly[m]?.si_xd||0), backgroundColor:'#FFE600', borderRadius:3 },
    { label:'SS',  data:months.slice(-13).map(m=>monthly[m]?.si_ss||0), backgroundColor:'#00A650', borderRadius:3 },
  ], { extra: { scales: { x:{ stacked:true,grid:{display:false} }, y:{ stacked:true,grid:{color:'#F0F0F0'} } } } });

  // Table
  const byS = groupBySeller(
    RAW.logistica_monthly.filter(r => r.mes >= periodCutoff(state.period)),
    ['gmv_total','gmv_ff','gmv_xd','gmv_ss','si_total','si_ff']
  );
  let html = `<thead><tr>
    <th>Seller</th><th>GMV Total</th><th>GMV FF</th><th>%FF</th>
    <th>GMV XD</th><th>%XD</th><th>GMV SS</th><th>%SS</th>
  </tr></thead><tbody>`;
  Object.entries(byS).sort((a,b)=>b[1].gmv_total-a[1].gmv_total).forEach(([cid,v])=>{
    const ff = v.gmv_total ? (v.gmv_ff/v.gmv_total)*100 : 0;
    const xd = v.gmv_total ? (v.gmv_xd/v.gmv_total)*100 : 0;
    const ss = v.gmv_total ? (v.gmv_ss/v.gmv_total)*100 : 0;
    html += `<tr><td>${sellerLabel(+cid)}</td>
      <td>${fmtBRL(v.gmv_total)}</td><td>${fmtBRL(v.gmv_ff)}</td>
      <td class="${ff>=50?'tag-pos':'tag-neg'}">${fmtPct(ff)}</td>
      <td>${fmtBRL(v.gmv_xd)}</td><td>${fmtPct(xd)}</td>
      <td>${fmtBRL(v.gmv_ss)}</td><td>${fmtPct(ss)}</td></tr>`;
  });
  html += '</tbody>';
  document.getElementById('tbl-log-sellers').innerHTML = html;
}

// ── RENDER: ADS ───────────────────────────────────────────────────────────
function renderAds() {
  const monthly = aggregateByMonth(RAW.ads_monthly, ['gmv','ads_invest','gmv_ads']);
  const months  = Object.keys(monthly).sort();
  const last    = months[months.length-1] || '';
  const l = monthly[last] || {};
  const roas    = l.ads_invest ? +(l.gmv_ads / l.ads_invest).toFixed(2) : 0;
  const adsPct  = l.gmv ? (l.ads_invest / l.gmv)*100 : 0;
  const invD    = calcDeltas(monthly,'ads_invest');

  // Take Rate: invest[month] / gmv[month-1]
  const mIdx  = months.indexOf(last);
  const prev  = months[mIdx-1];
  const takeRate = (prev && monthly[prev]?.gmv)
    ? (l.ads_invest / monthly[prev].gmv)*100 : null;

  document.getElementById('kpi-ads').innerHTML =
    kpiCard('Investimento ADS', fmtBRL(l.ads_invest||0), invD.mom, invD.yoy) +
    kpiCard('ROAS',             fmtDec(roas), null, null) +
    kpiCard('ADS/GMV%',        fmtPct(adsPct), null, null) +
    kpiCard('Take Rate ADS',   fmtPct(takeRate), null, null);

  makeChart('ch-ads-invest','bar', months.slice(-13),
    [{ label:'Investimento ADS', data:months.slice(-13).map(m=>monthly[m]?.ads_invest||0),
       backgroundColor:'#9B59B6', borderRadius:4 }],
    { yFmt: v => 'R$'+v.toLocaleString('pt-BR',{notation:'compact'}) });

  const roasData = months.slice(-13).map(m => {
    const d = monthly[m];
    return d?.ads_invest ? +(d.gmv_ads/d.ads_invest).toFixed(2) : null;
  });
  makeChart('ch-roas','line', months.slice(-13),
    [{ label:'ROAS', data:roasData, borderColor:'#1ABC9C', backgroundColor:'#1ABC9C22', fill:true, tension:.3, pointRadius:3 }]);

  const adsPctData = months.slice(-13).map(m => {
    const d = monthly[m];
    return d?.gmv ? +((d.ads_invest/d.gmv)*100).toFixed(2) : null;
  });
  makeChart('ch-ads-perc','line', months.slice(-13),
    [{ label:'ADS/GMV%', data:adsPctData, borderColor:'#E83C49', backgroundColor:'#E83C4922', fill:true, tension:.3, pointRadius:3 }],
    { yFmt: v => v?.toFixed(1)+'%' });

  const takeData = months.slice(-13).map((m,i) => {
    if (i===0) return null;
    const prev = months[months.indexOf(m)-1];
    const gPrev = monthly[prev]?.gmv || 0;
    const iCurr = monthly[m]?.ads_invest || 0;
    return gPrev ? +((iCurr/gPrev)*100).toFixed(2) : null;
  });
  makeChart('ch-take-rate','line', months.slice(-13),
    [{ label:'Take Rate %', data:takeData, borderColor:'#FF7733', backgroundColor:'#FF773322', fill:true, tension:.3, pointRadius:3 }],
    { yFmt: v => v?.toFixed(1)+'%' });

  const byS = groupBySeller(
    RAW.ads_monthly.filter(r => r.mes >= periodCutoff(state.period)),
    ['gmv','ads_invest','gmv_ads']
  );
  let html = `<thead><tr>
    <th>Seller</th><th>GMV</th><th>Invest. ADS</th><th>ROAS</th><th>ADS/GMV%</th>
  </tr></thead><tbody>`;
  Object.entries(byS).sort((a,b)=>b[1].ads_invest-a[1].ads_invest).forEach(([cid,v])=>{
    const roas = v.ads_invest ? +(v.gmv_ads/v.ads_invest).toFixed(2) : 0;
    const pct  = v.gmv ? (v.ads_invest/v.gmv)*100 : 0;
    html += `<tr><td>${sellerLabel(+cid)}</td>
      <td>${fmtBRL(v.gmv)}</td><td>${fmtBRL(v.ads_invest)}</td>
      <td>${fmtDec(roas)}</td><td>${fmtPct(pct)}</td></tr>`;
  });
  html += '</tbody>';
  document.getElementById('tbl-ads-sellers').innerHTML = html;
}

// ── RENDER: Investimentos ─────────────────────────────────────────────────
function renderInvestimentos() {
  const monthly = aggregateByMonth(RAW.investimentos_monthly, ['gmv','cupons','rebate_pre','rebate_outras','total_invest']);
  const months  = Object.keys(monthly).sort();
  const last    = months[months.length-1] || '';
  const l = monthly[last] || {};
  const td = calcDeltas(monthly,'total_invest');

  document.getElementById('kpi-inv').innerHTML =
    kpiCard('Total Investido', fmtBRL(l.total_invest||0), td.mom, td.yoy) +
    kpiCard('Cupons',          fmtBRL(l.cupons||0), null, null) +
    kpiCard('Rebate Pré-neg.', fmtBRL(l.rebate_pre||0), null, null) +
    kpiCard('Rebate Outras',   fmtBRL(l.rebate_outras||0), null, null);

  makeChart('ch-inv-total','bar', months.slice(-13), [
    { label:'Cupons',        data:months.slice(-13).map(m=>monthly[m]?.cupons||0),       backgroundColor:'#FFE600', borderRadius:3 },
    { label:'Rebate Pré',    data:months.slice(-13).map(m=>monthly[m]?.rebate_pre||0),   backgroundColor:'#3483FA', borderRadius:3 },
    { label:'Rebate Outras', data:months.slice(-13).map(m=>monthly[m]?.rebate_outras||0),backgroundColor:'#00A650', borderRadius:3 },
  ], { extra: { scales:{ x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:'#F0F0F0'}} } } });

  const tot = (l.cupons||0)+(l.rebate_pre||0)+(l.rebate_outras||0) || 1;
  makeChart('ch-inv-mix','doughnut',
    ['Cupons','Rebate Pré-neg.','Rebate Outras'],
    [{ data:[l.cupons||0, l.rebate_pre||0, l.rebate_outras||0],
       backgroundColor:['#FFE600','#3483FA','#00A650'], borderWidth:0 }],
    { extra:{ plugins:{ legend:{ display:true,position:'bottom' } } } });

  makeChart('ch-cupons','line', months.slice(-13),
    [{ label:'Cupons', data:months.slice(-13).map(m=>monthly[m]?.cupons||0),
       borderColor:'#FFE600', backgroundColor:'#FFE60022', fill:true, tension:.3, pointRadius:3 }],
    { yFmt: v => 'R$'+v.toLocaleString('pt-BR',{notation:'compact'}) });

  makeChart('ch-rebates','line', months.slice(-13), [
    { label:'Pré-neg.',    data:months.slice(-13).map(m=>monthly[m]?.rebate_pre||0),   borderColor:'#3483FA', backgroundColor:'#3483FA22', fill:false, tension:.3, pointRadius:3 },
    { label:'Outras',      data:months.slice(-13).map(m=>monthly[m]?.rebate_outras||0),borderColor:'#00A650', backgroundColor:'#00A65022', fill:false, tension:.3, pointRadius:3 },
  ], { yFmt: v => 'R$'+v.toLocaleString('pt-BR',{notation:'compact'}) });

  const byS = groupBySeller(
    RAW.investimentos_monthly.filter(r => r.mes >= periodCutoff(state.period)),
    ['gmv','cupons','rebate_pre','rebate_outras','total_invest']
  );
  let html = `<thead><tr>
    <th>Seller</th><th>GMV</th><th>Cupons</th><th>Rebate Pré</th><th>Rebate Outras</th><th>Total Invest.</th><th>Invest/GMV%</th>
  </tr></thead><tbody>`;
  Object.entries(byS).sort((a,b)=>b[1].total_invest-a[1].total_invest).forEach(([cid,v])=>{
    const pct = v.gmv ? (v.total_invest/v.gmv)*100 : 0;
    html += `<tr><td>${sellerLabel(+cid)}</td>
      <td>${fmtBRL(v.gmv)}</td><td>${fmtBRL(v.cupons)}</td>
      <td>${fmtBRL(v.rebate_pre)}</td><td>${fmtBRL(v.rebate_outras)}</td>
      <td><b>${fmtBRL(v.total_invest)}</b></td><td>${fmtPct(pct)}</td></tr>`;
  });
  html += '</tbody>';
  document.getElementById('tbl-inv-sellers').innerHTML = html;
}

// ── RENDER: Catálogo ──────────────────────────────────────────────────────
function renderCatalogo() {
  const ids = sellerIds(state.seller);
  const rows = RAW.catalogo_items.filter(r => ids.includes(r.cust_id));
  const totalGmv = rows.reduce((a,r)=>a+(r.gmv||0),0);

  let html = `<thead><tr>
    <th>Seller</th><th>Item ID</th><th>Título</th><th>GMV</th>
    <th>SI</th><th>ASP</th><th>Share %</th><th>GMV BuyBox</th><th>BB%</th>
  </tr></thead><tbody>`;
  rows.forEach(r => {
    const share = totalGmv ? (r.gmv/totalGmv)*100 : 0;
    const bbPct = r.gmv ? (r.gmv_bb/r.gmv)*100 : 0;
    html += `<tr>
      <td>${sellerLabel(r.cust_id)}</td>
      <td>${r.item_id}</td>
      <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.titulo||''}</td>
      <td>${fmtBRL(r.gmv)}</td><td>${fmtNum(r.si)}</td>
      <td>${fmtBRL(r.asp)}</td>
      <td><span class="badge">${fmtPct(share)}</span></td>
      <td>${fmtBRL(r.gmv_bb)}</td>
      <td class="${bbPct>=50?'tag-pos':'tag-neg'}">${fmtPct(bbPct)}</td>
    </tr>`;
  });
  html += '</tbody>';
  document.getElementById('tbl-catalogo').innerHTML = html;
}

// ── Controls ──────────────────────────────────────────────────────────────
function setPeriod(p, btn) {
  state.period = p;
  document.querySelectorAll('#period-btns .btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  renderAll();
}

function setSeller(val) {
  state.seller = val;
  renderAll();
}

function setTab(tab, el) {
  state.tab = tab;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  document.getElementById('tab-'+tab).classList.add('active');
  renderAll();
}

function renderAll() {
  if (state.tab==='geral')         renderGeral();
  if (state.tab==='logistica')     renderLogistica();
  if (state.tab==='ads')           renderAds();
  if (state.tab==='investimentos') renderInvestimentos();
  if (state.tab==='catalogo')      renderCatalogo();
}

// ── Init ──────────────────────────────────────────────────────────────────
function init() {
  document.getElementById('updated-at').textContent = 'Atualizado: ' + RAW.updated_at;

  // Build seller select
  const sel = document.getElementById('seller-sel');
  sel.innerHTML = '<option value="all">Toda a Carteira</option>';
  GROUPS.forEach(g => {
    const opt = document.createElement('option');
    opt.value = g; opt.textContent = '▸ Grupo: ' + g;
    sel.appendChild(opt);
  });
  SELLERS.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.cust_id; opt.textContent = s.name;
    sel.appendChild(opt);
  });

  renderAll();
}

init();
</script>
</body>
</html>
"""


# ── Main ──────────────────────────────────────────────────────────────────────
def generate():
    dataset = build_dataset()
    data_json = json.dumps(dataset, ensure_ascii=False, default=str)
    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)

    out_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard gerado: {out_path}")

    # Git push para GitHub Pages
    repo_dir = os.path.dirname(__file__)
    try:
        subprocess.run(["git", "add", "index.html"],           cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m",
                        f"chore: atualização automática {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                       cwd=repo_dir, check=True)
        subprocess.run(["git", "push"],                        cwd=repo_dir, check=True)
        print("Push para GitHub Pages concluído.")
    except subprocess.CalledProcessError as e:
        print(f"Git push falhou: {e}")


if __name__ == "__main__":
    generate()
