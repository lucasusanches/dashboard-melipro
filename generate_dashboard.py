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
from decimal import Decimal
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
          AND ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND ORD_CLOSED_DT < CURRENT_DATE()
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
          AND ORD_CLOSED_DT < CURRENT_DATE()
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
          AND ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND ORD_CLOSED_DT < CURRENT_DATE()
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
          AND ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND ORD_CLOSED_DT < CURRENT_DATE()
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
          AND ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND ORD_CLOSED_DT < CURRENT_DATE()
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
          AND ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND ORD_CLOSED_DT < CURRENT_DATE()
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
          AND ORD_CLOSED_DT < CURRENT_DATE()
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
        if isinstance(obj, Decimal):
            return float(obj)
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
HTML_TEMPLATE = ""'<!DOCTYPE html>\n<html lang="pt-BR">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Dashboard MeliPro - Lucas Sanches</title>\n<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>\n<style>\n:root{\n  --ml-yellow:#FFE600;--ml-blue:#2D3277;--ml-blue2:#3483FA;\n  --bg:#F5F5F5;--card:#fff;--txt:#333;--muted:#777;\n  --green:#00A650;--red:#E83C49;--border:#E0E0E0;\n  --sidebar-w:200px;\n}\n*{box-sizing:border-box;margin:0;padding:0}\nbody{font-family:\'Proxima Nova\',Arial,sans-serif;background:var(--bg);color:var(--txt);font-size:14px;height:100vh;display:flex;flex-direction:column}\n.header{background:var(--ml-yellow);padding:10px 20px;display:flex;align-items:center;gap:14px;box-shadow:0 2px 4px rgba(0,0,0,.12);flex-shrink:0}\n.logo{height:44px;object-fit:contain}\n.header-title{font-size:18px;font-weight:700;color:var(--ml-blue)}\n.header-sub{font-size:11px;color:var(--ml-blue);opacity:.7;margin-top:1px}\n.updated{margin-left:auto;font-size:11px;color:var(--ml-blue);opacity:.6;white-space:nowrap}\n.period-bar{background:#fff;border-bottom:1px solid var(--border);padding:8px 20px;display:flex;gap:6px;align-items:center;flex-shrink:0;flex-wrap:wrap}\n.period-label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-right:2px}\n.btn{padding:5px 13px;border:1px solid var(--border);border-radius:20px;background:#fff;cursor:pointer;font-size:12px;color:var(--txt);transition:all .15s;white-space:nowrap}\n.btn:hover{background:#f0f0f0}\n.btn.active{background:var(--ml-blue);color:#fff;border-color:var(--ml-blue)}\n.btn.custom-btn{border-style:dashed}\n.btn.custom-btn.active{border-style:solid}\n.custom-wrap{position:relative;display:inline-block}\n.custom-dropdown{display:none;position:absolute;top:calc(100% + 6px);left:0;background:#fff;border:1px solid var(--border);border-radius:8px;padding:14px;box-shadow:0 4px 16px rgba(0,0,0,.12);z-index:100;min-width:280px}\n.custom-dropdown.open{display:block}\n.custom-dropdown label{font-size:11px;font-weight:700;color:var(--muted);display:block;margin-bottom:3px;margin-top:10px}\n.custom-dropdown label:first-child{margin-top:0}\n.custom-dropdown input[type=date]{width:100%;border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px;outline:none}\n.custom-dropdown .apply-btn{margin-top:12px;width:100%;padding:8px;background:var(--ml-blue);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600}\n.quick-btns{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:4px}\n.quick-btn{padding:4px 10px;border:1px solid var(--border);border-radius:12px;background:#fff;cursor:pointer;font-size:11px;color:var(--txt)}\n.quick-btn:hover{background:var(--ml-yellow);border-color:var(--ml-yellow)}\n.layout{display:flex;flex:1;overflow:hidden}\n.sidebar{width:var(--sidebar-w);background:#fff;border-right:1px solid var(--border);overflow-y:auto;flex-shrink:0;padding:8px 0;transition:width .2s,padding .2s}\n.sidebar.collapsed{width:0;padding:0;border:none}\n.sb-toggle{width:18px;background:#F0F0F0;border:none;cursor:pointer;font-size:11px;color:var(--muted);flex-shrink:0;display:flex;align-items:center;justify-content:center;border-right:1px solid var(--border);transition:background .15s}\n.sb-toggle:hover{background:var(--ml-yellow);color:var(--ml-blue)}\n.s-item{padding:9px 16px;cursor:pointer;font-size:13px;color:var(--txt);display:flex;align-items:center;gap:8px;transition:all .15s;border-left:3px solid transparent}\n.s-item:hover{background:#F5F5F5}\n.s-item.active{background:#EEF4FF;color:var(--ml-blue);font-weight:700;border-left-color:var(--ml-blue2)}\n.s-divider{height:1px;background:var(--border);margin:6px 12px}\n.s-group-header{padding:8px 16px;cursor:pointer;font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;display:flex;align-items:center;gap:6px;border-left:3px solid transparent;user-select:none}\n.s-group-header:hover{background:#F5F5F5}\n.s-group-header.active{background:#EEF4FF;color:var(--ml-blue);border-left-color:var(--ml-blue2)}\n.s-arrow{font-size:10px;transition:transform .2s;display:inline-block;cursor:pointer;padding:2px 4px}\n.s-arrow.open{transform:rotate(90deg)}\n.s-sub{padding:7px 16px 7px 32px;cursor:pointer;font-size:12px;color:var(--muted);border-left:3px solid transparent;transition:all .15s}\n.s-sub:hover{background:#F5F5F5;color:var(--txt)}\n.s-sub.active{background:#EEF4FF;color:var(--ml-blue);font-weight:600;border-left-color:var(--ml-blue2)}\n.main{flex:1;display:flex;flex-direction:column;overflow:hidden}\n.main-tabs{display:flex;background:#fff;border-bottom:2px solid var(--border);flex-shrink:0;padding:0 20px;overflow-x:auto}\n.tab{padding:11px 18px;cursor:pointer;font-size:13px;font-weight:600;color:var(--muted);border-bottom:3px solid transparent;margin-bottom:-2px;white-space:nowrap;transition:all .15s}\n.tab:hover{color:var(--ml-blue)}\n.tab.active{color:var(--ml-blue);border-bottom-color:var(--ml-blue2)}\n.main-content{flex:1;overflow-y:auto;padding:18px 20px}\n.tab-content{display:none}\n.tab-content.active{display:block}\n.period-badge{display:inline-block;background:var(--ml-blue);color:#fff;font-size:11px;font-weight:700;padding:2px 10px;border-radius:10px;margin-bottom:14px}\n.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}\n.kpi-card{background:var(--card);border-radius:8px;padding:14px 16px;border:1px solid var(--border);box-shadow:0 1px 3px rgba(0,0,0,.05)}\n.kpi-label{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}\n.kpi-value{font-size:22px;font-weight:700;color:var(--ml-blue);margin:5px 0 4px;line-height:1}\n.kpi-delta{font-size:11px;display:flex;gap:8px;flex-wrap:wrap}\n.dp{color:var(--green);font-weight:600}\n.dn{color:var(--red);font-weight:600}\n.dn0{color:var(--muted)}\n.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px;margin-bottom:18px}\n.chart-card{background:var(--card);border-radius:8px;padding:14px;border:1px solid var(--border);box-shadow:0 1px 3px rgba(0,0,0,.05)}\n.chart-title{font-size:12px;font-weight:700;color:var(--ml-blue);margin-bottom:10px}\n.chart-wrap{position:relative;height:220px}\n.table-wrap{background:var(--card);border-radius:8px;border:1px solid var(--border);overflow:auto;box-shadow:0 1px 3px rgba(0,0,0,.05);margin-bottom:18px}\n.section-title{font-size:13px;font-weight:700;color:var(--ml-blue);margin:16px 0 8px;display:flex;align-items:center;gap:8px}\n.section-title::after{content:\'\';flex:1;height:1px;background:var(--border)}\ntable{width:100%;border-collapse:collapse}\nthead tr{background:var(--ml-blue);color:#fff}\nth{padding:9px 11px;text-align:right;font-size:11px;font-weight:600;letter-spacing:.3px;white-space:nowrap}\nth:first-child{text-align:left}\ntbody tr{border-bottom:1px solid var(--border)}\ntbody tr:hover{background:#FAFAFA}\ntd{padding:8px 11px;text-align:right;font-size:12px;white-space:nowrap}\ntd:first-child{text-align:left;font-weight:500}\n.tag-pos{color:var(--green);font-weight:600}\n.tag-neg{color:var(--red);font-weight:600}\n.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;background:var(--ml-yellow);color:var(--ml-blue)}\n</style>\n</head>\n<body>\n<div class="header">\n  <img class="logo" src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA0MDAgNDYwIiB3aWR0aD0iNDAwIiBoZWlnaHQ9IjQ2MCI+CiAgPGRlZnM+CiAgICA8Y2xpcFBhdGggaWQ9Im92YWwtY2xpcCI+CiAgICAgIDxlbGxpcHNlIGN4PSIyMDAiIGN5PSIxNjUiIHJ4PSIxNzIiIHJ5PSIxMzIiLz4KICAgIDwvY2xpcFBhdGg+CiAgPC9kZWZzPgogIDwhLS0gT3ZhbCB3aGl0ZSBiYXNlIC0tPgogIDxlbGxpcHNlIGN4PSIyMDAiIGN5PSIxNjUiIHJ4PSIxNzIiIHJ5PSIxMzIiIGZpbGw9IiNmZmZmZmYiLz4KICA8IS0tIFllbGxvdyBsb3dlciBmaWxsIC0tPgogIDxyZWN0IHg9IjI4IiB5PSIxNzgiIHdpZHRoPSIzNDQiIGhlaWdodD0iMTE5IiBmaWxsPSIjRkZFNjAwIiBjbGlwLXBhdGg9InVybCgjb3ZhbC1jbGlwKSIvPgogIDwhLS0gRGFyayBibHVlIGJvcmRlciAtLT4KICA8ZWxsaXBzZSBjeD0iMjAwIiBjeT0iMTY1IiByeD0iMTcyIiByeT0iMTMyIiBmaWxsPSJub25lIiBzdHJva2U9IiMyRDMyNzciIHN0cm9rZS13aWR0aD0iMTYiLz4KCiAgPCEtLSBIYW5kc2hha2Ugc2lsaG91ZXR0ZSAoc2ltcGxpZmllZCBmYWl0aGZ1bCByZXByZXNlbnRhdGlvbikgLS0+CiAgPCEtLSBMZWZ0IGFybS9oYW5kIGZyb20gbGVmdCAtLT4KICA8cGF0aCBkPSJNNTAgMTcwIFE3MCAxNDggOTUgMTUyIEwxMTggMTQ0IEwxNDAgMTM4IEwxNTggMTQyIFExNjggMTQ4IDE2NiAxNjIKICAgICAgICAgICBMMTQ4IDE2MCBMMTMwIDE1NiBMMTE0IDE1OCBROTggMTY0IDg2IDE3OCBRNzAgMTg2IDUwIDE3NiBaIgogICAgICAgIGZpbGw9IiNmZmZmZmYiLz4KICA8IS0tIFJpZ2h0IGFybS9oYW5kIGZyb20gcmlnaHQgLS0+CiAgPHBhdGggZD0iTTM1MCAxNzAgUTMzMCAxNDggMzA1IDE1MiBMMjgyIDE0NCBMMjYwIDEzOCBMMjQyIDE0MiBRMjMyIDE0OCAyMzQgMTYyCiAgICAgICAgICAgTDI1MiAxNjAgTDI3MCAxNTYgTDI4NiAxNTggUTMwMiAxNjQgMzE0IDE3OCBRMzMwIDE4NiAzNTAgMTc2IFoiCiAgICAgICAgZmlsbD0iI2ZmZmZmZiIvPgogIDwhLS0gQ2VudGVyIGNsYXNwZWQgaGFuZHMgLS0+CiAgPGVsbGlwc2UgY3g9IjIwMCIgY3k9IjE1NSIgcng9IjQyIiByeT0iMjYiIGZpbGw9IiNmZmZmZmYiLz4KICA8IS0tIEtudWNrbGVzIGxlZnQgLS0+CiAgPGNpcmNsZSBjeD0iMTY0IiBjeT0iMTY2IiByPSI3IiBmaWxsPSIjZmZmZmZmIi8+CiAgPGNpcmNsZSBjeD0iMTUyIiBjeT0iMTcyIiByPSI2IiBmaWxsPSIjZmZmZmZmIi8+CiAgPGNpcmNsZSBjeD0iMTQwIiBjeT0iMTc0IiByPSI1LjUiIGZpbGw9IiNmZmZmZmYiLz4KICA8IS0tIEtudWNrbGVzIHJpZ2h0IC0tPgogIDxjaXJjbGUgY3g9IjIzNiIgY3k9IjE2NiIgcj0iNyIgZmlsbD0iI2ZmZmZmZiIvPgogIDxjaXJjbGUgY3g9IjI0OCIgY3k9IjE3MiIgcj0iNiIgZmlsbD0iI2ZmZmZmZiIvPgogIDxjaXJjbGUgY3g9IjI2MCIgY3k9IjE3NCIgcj0iNS41IiBmaWxsPSIjZmZmZmZmIi8+CiAgPCEtLSBUaHVtYiBsZWZ0IC0tPgogIDxlbGxpcHNlIGN4PSIxNzQiIGN5PSIxNDAiIHJ4PSI4IiByeT0iMTQiIGZpbGw9IiNmZmZmZmYiIHRyYW5zZm9ybT0icm90YXRlKC0yNSwxNzQsMTQwKSIvPgogIDwhLS0gVGh1bWIgcmlnaHQgLS0+CiAgPGVsbGlwc2UgY3g9IjIyNiIgY3k9IjE0MCIgcng9IjgiIHJ5PSIxNCIgZmlsbD0iI2ZmZmZmZiIgdHJhbnNmb3JtPSJyb3RhdGUoMjUsMjI2LDE0MCkiLz4KCiAgPCEtLSBUZXh0OiBtZXJjYWRvIC0tPgogIDx0ZXh0IHg9IjIwMCIgeT0iMzU4IgogICAgdGV4dC1hbmNob3I9Im1pZGRsZSIKICAgIGZvbnQtZmFtaWx5PSInQXJpYWwgQmxhY2snLCdBcmlhbCcsJ0hlbHZldGljYScsc2Fucy1zZXJpZiIKICAgIGZvbnQtd2VpZ2h0PSI5MDAiCiAgICBmb250LXNpemU9IjcyIgogICAgbGV0dGVyLXNwYWNpbmc9Ii0xIgogICAgZmlsbD0iIzJEMzI3NyI+bWVyY2FkbzwvdGV4dD4KICA8IS0tIFRleHQ6IGxpdnJlIC0tPgogIDx0ZXh0IHg9IjIwMCIgeT0iNDQwIgogICAgdGV4dC1hbmNob3I9Im1pZGRsZSIKICAgIGZvbnQtZmFtaWx5PSInQXJpYWwgQmxhY2snLCdBcmlhbCcsJ0hlbHZldGljYScsc2Fucy1zZXJpZiIKICAgIGZvbnQtd2VpZ2h0PSI5MDAiCiAgICBmb250LXNpemU9IjgwIgogICAgbGV0dGVyLXNwYWNpbmc9Ii0xIgogICAgZmlsbD0iIzJEMzI3NyI+bGl2cmU8L3RleHQ+Cjwvc3ZnPg==" alt="Mercado Livre">\n  <div><div class="header-title">Dashboard MeliPro — Lucas Sanches</div>\n  <div class="header-sub">Visão 360° da Carteira</div></div>\n  <div class="updated" id="updated-at"></div>\n</div>\n<div class="period-bar">\n  <span class="period-label">Período:</span>\n  <button class="btn" onclick="setPeriod(\'day\',this)">Dia</button>\n  <button class="btn" onclick="setPeriod(\'week\',this)">Semana</button>\n  <button class="btn active" onclick="setPeriod(\'month\',this)">Mês</button>\n  <button class="btn" onclick="setPeriod(\'quarter\',this)">Trimestre</button>\n  <button class="btn" onclick="setPeriod(\'year\',this)">Ano</button>\n  <div class="custom-wrap">\n    <button class="btn custom-btn" id="custom-btn" onclick="toggleCustom()">&#128197; Personalizado</button>\n    <div class="custom-dropdown" id="custom-dropdown">\n      <div class="quick-btns">\n        <button class="quick-btn" onclick="quickPick(\'yesterday\')">Ontem</button>\n        <button class="quick-btn" onclick="quickPick(\'last-week\')">Sem. passada</button>\n        <button class="quick-btn" onclick="quickPick(\'this-month\')">Este mês</button>\n        <button class="quick-btn" onclick="quickPick(\'last-month\')">Mês passado</button>\n        <button class="quick-btn" onclick="quickPick(\'this-quarter\')">Este trimestre</button>\n        <button class="quick-btn" onclick="quickPick(\'this-year\')">Este ano</button>\n      </div>\n      <label>De</label><input type="date" id="custom-start">\n      <label>Até</label><input type="date" id="custom-end">\n      <button class="apply-btn" onclick="applyCustom()">Aplicar</button>\n    </div>\n  </div>\n</div>\n<div class="layout">\n  <nav class="sidebar" id="sidebar"></nav>\n  <button class="sb-toggle" id="sb-toggle" onclick="toggleSidebar()" title="Ocultar/exibir carteira">&#9664;</button>\n  <div class="main">\n    <div class="main-tabs">\n      <div class="tab active" onclick="setTab(\'geral\',this)">Geral</div>\n      <div class="tab" onclick="setTab(\'logistica\',this)">Fulfillment &amp; Logística</div>\n      <div class="tab" onclick="setTab(\'ads\',this)">ADS</div>\n      <div class="tab" onclick="setTab(\'investimentos\',this)">Investimentos</div>\n      <div class="tab" onclick="setTab(\'catalogo\',this)">Catálogo</div>\n    </div>\n    <div class="main-content">\n      <div class="tab-content active" id="tab-geral">\n        <div id="period-badge-geral" class="period-badge"></div>\n        <div class="kpi-grid" id="kpi-geral"></div>\n        <div class="chart-grid">\n          <div class="chart-card"><div class="chart-title">GMV Mensal (R$)</div><div class="chart-wrap"><canvas id="ch-gmv-mes"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">Variação GMV — MoM vs YoY (%)</div><div class="chart-wrap"><canvas id="ch-gmv-delta"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">Unidades Vendidas (SI)</div><div class="chart-wrap"><canvas id="ch-si-mes"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">ASP Médio (R$)</div><div class="chart-wrap"><canvas id="ch-asp-mes"></canvas></div></div>\n        </div>\n        <div class="section-title">Resumo por Seller</div>\n        <div class="table-wrap"><table id="tbl-geral-sellers"></table></div>\n      </div>\n      <div class="tab-content" id="tab-logistica">\n        <div id="period-badge-log" class="period-badge"></div>\n        <div class="kpi-grid" id="kpi-log"></div>\n        <div class="chart-grid">\n          <div class="chart-card"><div class="chart-title">Mix Logístico — GMV (%)</div><div class="chart-wrap"><canvas id="ch-log-mix"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">%FF por Mês</div><div class="chart-wrap"><canvas id="ch-ff-mes"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">GMV por Tipo Logístico</div><div class="chart-wrap"><canvas id="ch-log-gmv"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">SI por Tipo Logístico</div><div class="chart-wrap"><canvas id="ch-log-si"></canvas></div></div>\n        </div>\n        <div class="section-title">Detalhe por Seller</div>\n        <div class="table-wrap"><table id="tbl-log-sellers"></table></div>\n      </div>\n      <div class="tab-content" id="tab-ads">\n        <div id="period-badge-ads" class="period-badge"></div>\n        <div class="kpi-grid" id="kpi-ads"></div>\n        <div class="chart-grid">\n          <div class="chart-card"><div class="chart-title">Investimento ADS Mensal (R$)</div><div class="chart-wrap"><canvas id="ch-ads-invest"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">ROAS Mensal</div><div class="chart-wrap"><canvas id="ch-roas"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">ADS/GMV % Mensal</div><div class="chart-wrap"><canvas id="ch-ads-perc"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">Take Rate ADS (%)</div><div class="chart-wrap"><canvas id="ch-take-rate"></canvas></div></div>\n        </div>\n        <div class="section-title">Detalhe por Seller</div>\n        <div class="table-wrap"><table id="tbl-ads-sellers"></table></div>\n      </div>\n      <div class="tab-content" id="tab-investimentos">\n        <div id="period-badge-inv" class="period-badge"></div>\n        <div class="kpi-grid" id="kpi-inv"></div>\n        <div class="chart-grid">\n          <div class="chart-card"><div class="chart-title">Investimentos Totais Mensais (R$)</div><div class="chart-wrap"><canvas id="ch-inv-total"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">Mix de Investimentos</div><div class="chart-wrap"><canvas id="ch-inv-mix"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">Cupons por Mês (R$)</div><div class="chart-wrap"><canvas id="ch-cupons"></canvas></div></div>\n          <div class="chart-card"><div class="chart-title">Rebates por Mês (R$)</div><div class="chart-wrap"><canvas id="ch-rebates"></canvas></div></div>\n        </div>\n        <div class="section-title">Detalhe por Seller</div>\n        <div class="table-wrap"><table id="tbl-inv-sellers"></table></div>\n      </div>\n      <div class="tab-content" id="tab-catalogo">\n        <div class="section-title">Top Itêns por Seller — Últimos 3 meses</div>\n        <div class="table-wrap"><table id="tbl-catalogo"></table></div>\n      </div>\n    </div>\n  </div>\n</div>\n<script>\nconst RAW = __DATA_PLACEHOLDER__;\nconst state = { period:\'month\', seller:\'all\', tab:\'geral\', customStart:null, customEnd:null };\nconst charts = {}, groupOpen = {};\nconst SELLERS = RAW.sellers;\nconst GROUP_COUNTS = {};\nSELLERS.forEach(s => { GROUP_COUNTS[s.group] = (GROUP_COUNTS[s.group]||0)+1; });\nconst MULTI_GROUPS = Object.keys(GROUP_COUNTS).filter(g => GROUP_COUNTS[g] > 1);\nfunction sellerIds(val){\n  if(val===\'all\') return SELLERS.map(s=>String(s.cust_id));\n  if(MULTI_GROUPS.includes(String(val))) return SELLERS.filter(s=>s.group===val).map(s=>String(s.cust_id));\n  return [String(val)];\n}\nfunction sellerLabel(cid){\n  return SELLERS.find(s=>String(s.cust_id)===String(cid))?.name||cid;\n}\nfunction buildSidebar(){\n  let html=\'\', active=String(state.seller);\n  html+=`<div class="s-item ${active===\'all\'?\'active\':\'\'}" onclick="setSeller(\'all\')">&#9673; Toda a Carteira</div>`;\n  html+=\'<div class="s-divider"></div>\';\n  const done=new Set();\n  const sorted=[...SELLERS].sort((a,b)=>a.name.localeCompare(b.name,\'pt-BR\'));\n  sorted.forEach(s=>{\n    if(MULTI_GROUPS.includes(s.group)){\n      if(!done.has(s.group)){\n        done.add(s.group);\n        const ga=active===s.group, isOpen=groupOpen[s.group]!==false;\n        html+=`<div class="s-group-header ${ga?\'active\':\'\'}" onclick="setSeller(\'${s.group}\')">`\n             +`<span class="s-arrow ${isOpen?\'open\':\'\'}" onclick="event.stopPropagation();toggleGroup(\'${s.group}\')">&#9658;</span> ${s.group}</div>`;\n        sorted.filter(x=>x.group===s.group).sort((a,b)=>a.name.localeCompare(b.name,\'pt-BR\')).forEach(sub=>{\n          const hidden=isOpen?\'\':`style="display:none"`;\n          html+=`<div class="s-sub ${active==String(sub.cust_id)?\'active\':\'\'}" ${hidden} onclick="setSeller(${sub.cust_id})">${sub.name}</div>`;\n        });\n      }\n    } else {\n      html+=`<div class="s-item ${active==String(s.cust_id)?\'active\':\'\'}" onclick="setSeller(${s.cust_id})">${s.name}</div>`;\n    }\n  });\n  document.getElementById(\'sidebar\').innerHTML=html;\n}\nfunction toggleGroup(g){groupOpen[g]=groupOpen[g]===false?true:false;buildSidebar();}\nfunction toggleSidebar(){\n  const sb=document.getElementById(\'sidebar\'),btn=document.getElementById(\'sb-toggle\');\n  sb.classList.toggle(\'collapsed\');\n  btn.textContent=sb.classList.contains(\'collapsed\')?\'►\':\'◄\';\n}\nconst fmtDate=d=>d.toISOString().slice(0,10);\nconst fmtMonth=(y,m)=>`${y}-${String(m+1).padStart(2,\'0\')}`;\nconst addDays=(d,n)=>{const r=new Date(d);r.setDate(r.getDate()+n);return r;};\nfunction getPeriodConfig(){\n  const now=new Date(),yr=now.getFullYear(),mo=now.getMonth(),p=state.period;\n  if(p===\'custom\'&&state.customStart){\n    const s=state.customStart,e=state.customEnd||state.customStart;\n    const sD=new Date(s+\'T12:00:00\'),eD=new Date(e+\'T12:00:00\');\n    const currM=[],cur=new Date(sD.getFullYear(),sD.getMonth(),1);\n    const last=new Date(eD.getFullYear(),eD.getMonth(),1);\n    while(cur<=last){currM.push(fmtMonth(cur.getFullYear(),cur.getMonth()));cur=new Date(cur.getFullYear(),cur.getMonth()+1,1);}\n    const momM=currM.map(m=>{const y=parseInt(m.slice(0,4)),mo2=parseInt(m.slice(5))-1;return mo2===0?fmtMonth(y-1,11):fmtMonth(y,mo2-1);});\n    const yoyM=currM.map(m=>fmtMonth(parseInt(m.slice(0,4))-1,parseInt(m.slice(5))-1));\n    return {type:\'custom\',gran:\'monthly\',curr:currM,prevMoM:momM,prevYoY:yoyM,\n      label:`${s} → ${e}`,showD1:true,showD2:true,d1Label:\'MoM\',d2Label:\'YoY\'};\n  }\n  if(p===\'day\'){\n    const d1=fmtDate(addDays(now,-1)),d2=fmtDate(addDays(now,-2));\n    return {type:\'day\',gran:\'daily\',curr:[d1,d1],prev:[d2,d2],label:`D-1 (${d1})`,prevLabel:\'vs D-2\',showD1:true,showD2:false};\n  }\n  if(p===\'week\'){\n    const dow=now.getDay(),toSat=dow===6?7:dow+1;\n    const wEnd=addDays(now,-toSat),wStart=addDays(wEnd,-6);\n    const pwEnd=addDays(wStart,-1),pwStart=addDays(pwEnd,-6);\n    const fw=d=>d.toLocaleDateString(\'pt-BR\',{day:\'2-digit\',month:\'2-digit\'});\n    return {type:\'week\',gran:\'daily\',curr:[fmtDate(wStart),fmtDate(wEnd)],prev:[fmtDate(pwStart),fmtDate(pwEnd)],\n      label:`Sem. ${fw(wStart)}-${fw(wEnd)}`,prevLabel:\'vs Sem. ant.\',showD1:true,showD2:false};\n  }\n  if(p===\'month\'){\n    const cm=fmtMonth(yr,mo),pm=mo===0?[yr-1,11]:[yr,mo-1];\n    return {type:\'month\',gran:\'monthly\',curr:[cm],prevMoM:[fmtMonth(pm[0],pm[1])],prevYoY:[fmtMonth(yr-1,mo)],\n      label:cm,showD1:true,showD2:true,d1Label:\'MoM\',d2Label:\'YoY\'};\n  }\n  if(p===\'quarter\'){\n    const q=Math.floor(mo/3),curr=[];\n    for(let i=q*3;i<=mo;i++) curr.push(fmtMonth(yr,i));\n    const pqY=q===0?yr-1:yr,pqQ=q===0?3:q-1;\n    const pqMeses=curr.map((_,i)=>fmtMonth(pqY,pqQ*3+i));\n    const pyMeses=curr.map(m=>fmtMonth(yr-1,parseInt(m.slice(5))-1));\n    return {type:\'quarter\',gran:\'monthly\',curr,prevQoQ:pqMeses,prevYoY:pyMeses,\n      label:`Q${q+1} ${yr}`,showD1:true,showD2:true,d1Label:\'QoQ\',d2Label:\'YoY\'};\n  }\n  if(p===\'year\'){\n    const ytd=[],py=[];\n    for(let i=0;i<=mo;i++){ytd.push(fmtMonth(yr,i));py.push(fmtMonth(yr-1,i));}\n    return {type:\'year\',gran:\'monthly\',curr:ytd,prevYoY:py,label:`${yr} YTD`,showD1:false,showD2:true,d2Label:\'YoY\'};\n  }\n}\nfunction setBadge(id,pc){const el=document.getElementById(id);if(el)el.textContent=pc.label||\'\';}\nfunction aggAllMonths(rows,fields){\n  const ids=sellerIds(state.seller),out={};\n  rows.filter(r=>ids.includes(String(r.cust_id))).forEach(r=>{\n    if(!out[r.mes]){out[r.mes]={};fields.forEach(f=>out[r.mes][f]=0);}\n    fields.forEach(f=>out[r.mes][f]+=(Number(r[f])||0));\n  }); return out;\n}\nfunction aggCurrentYear(rows,fields){\n  const ids=sellerIds(state.seller),yr=String(new Date().getFullYear()),out={};\n  rows.filter(r=>ids.includes(String(r.cust_id))&&r.mes.startsWith(yr)).forEach(r=>{\n    if(!out[r.mes]){out[r.mes]={};fields.forEach(f=>out[r.mes][f]=0);}\n    fields.forEach(f=>out[r.mes][f]+=(Number(r[f])||0));\n  }); return out;\n}\nfunction sumMeses(allM,meses,field){return (meses||[]).reduce((a,m)=>a+(allM[m]?.[field]||0),0);}\nfunction sumDailyRange(start,end,field){\n  const ids=sellerIds(state.seller);\n  return RAW.geral_daily.filter(r=>ids.includes(String(r.cust_id))&&r.dia>=start&&r.dia<=end)\n    .reduce((a,r)=>a+(Number(r[field])||0),0);\n}\nfunction aggBySeller(rows,meses,fields){\n  const ids=sellerIds(state.seller),out={};\n  rows.filter(r=>ids.includes(String(r.cust_id))&&(meses||[]).includes(r.mes)).forEach(r=>{\n    if(!out[r.cust_id]){out[r.cust_id]={};fields.forEach(f=>out[r.cust_id][f]=0);}\n    fields.forEach(f=>out[r.cust_id][f]+=(Number(r[f])||0));\n  }); return out;\n}\nfunction computeKPI(pc,allM,field){\n  let value,d1=null,d2=null;\n  if(pc.gran===\'daily\'){\n    value=sumDailyRange(pc.curr[0],pc.curr[1],field);\n    if(pc.prev){const p=sumDailyRange(pc.prev[0],pc.prev[1],field);d1=p?((value-p)/p)*100:null;}\n  } else {\n    value=sumMeses(allM,pc.curr,field);\n    if(pc.prevMoM){const p=sumMeses(allM,pc.prevMoM,field);d1=p?((value-p)/p)*100:null;}\n    else if(pc.prevQoQ){const p=sumMeses(allM,pc.prevQoQ,field);d1=p?((value-p)/p)*100:null;}\n    if(pc.prevYoY){const p=sumMeses(allM,pc.prevYoY,field);d2=p?((value-p)/p)*100:null;}\n  }\n  return {value,d1,d2};\n}\nconst fmtBRL=v=>v==null?\'-\':\'R$\xa0\'+(+v).toLocaleString(\'pt-BR\',{minimumFractionDigits:0,maximumFractionDigits:0});\nconst fmtPct=v=>(v==null||!isFinite(v))?\'-\':(+v).toFixed(1)+\'%\';\nconst fmtNum=v=>v==null?\'-\':(+v).toLocaleString(\'pt-BR\');\nconst fmtDec=v=>v==null?\'-\':(+v).toLocaleString(\'pt-BR\',{minimumFractionDigits:2,maximumFractionDigits:2});\nfunction dHtml(pct,label){\n  if(pct==null||!isFinite(pct)) return `<span class="dn0">${label}: —</span>`;\n  const cls=pct>=0?\'dp\':\'dn\',arr=pct>=0?\'▲\':\'▼\';\n  return `<span class="${cls}">${label}: ${arr}${Math.abs(pct).toFixed(1)}%</span>`;\n}\nfunction kpiCard(label,value,pc,d1,d2){\n  let dh=\'\';\n  if(pc.showD1&&d1!=null) dh+=dHtml(d1,pc.d1Label||pc.prevLabel||\'vs ant.\');\n  if(pc.showD2&&d2!=null) dh+=dHtml(d2,pc.d2Label||\'YoY\');\n  if(!dh) dh=\'<span class="dn0">—</span>\';\n  return `<div class="kpi-card"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div><div class="kpi-delta">${dh}</div></div>`;\n}\nfunction makeChart(id,type,labels,datasets,opts={}){\n  if(charts[id])charts[id].destroy();\n  const ctx=document.getElementById(id);if(!ctx)return;\n  charts[id]=new Chart(ctx,{type,data:{labels,datasets},options:{\n    responsive:true,maintainAspectRatio:false,\n    plugins:{legend:{display:datasets.length>1,labels:{boxWidth:12,font:{size:11}}}},\n    scales:type===\'doughnut\'?{}:{\n      x:{ticks:{font:{size:10}},grid:{display:false}},\n      y:{ticks:{font:{size:10},callback:opts.yFmt||null},grid:{color:\'#F0F0F0\'}}\n    },...(opts.extra||{})\n  }});\n}\nfunction renderGeral(){\n  const pc=getPeriodConfig(),allM=aggAllMonths(RAW.geral_monthly,[\'gmv\',\'si\']);\n  setBadge(\'period-badge-geral\',pc);\n  const gmv=computeKPI(pc,allM,\'gmv\'),si=computeKPI(pc,allM,\'si\');\n  const aspVal=si.value?gmv.value/si.value:0;\n  const aspPrev=pc.gran===\'monthly\'&&pc.prevMoM?(()=>{const g=sumMeses(allM,pc.prevMoM,\'gmv\'),s=sumMeses(allM,pc.prevMoM,\'si\');return s?g/s:null;})():null;\n  const aspYY=pc.gran===\'monthly\'&&pc.prevYoY?(()=>{const g=sumMeses(allM,pc.prevYoY,\'gmv\'),s=sumMeses(allM,pc.prevYoY,\'si\');return s?g/s:null;})():null;\n  const aspD1=aspPrev?((aspVal-aspPrev)/aspPrev)*100:null;\n  const aspD2=aspYY?((aspVal-aspYY)/aspYY)*100:null;\n  document.getElementById(\'kpi-geral\').innerHTML=\n    kpiCard(\'GMV\',fmtBRL(gmv.value),pc,gmv.d1,gmv.d2)+\n    kpiCard(\'SI (Unidades)\',fmtNum(si.value),pc,si.d1,si.d2)+\n    kpiCard(\'ASP\',fmtBRL(aspVal),pc,aspD1,aspD2);\n  const cy=aggCurrentYear(RAW.geral_monthly,[\'gmv\',\'si\']),cym=Object.keys(cy).sort();\n  const allM2=aggAllMonths(RAW.geral_monthly,[\'gmv\',\'si\']),allM2k=Object.keys(allM2).sort();\n  makeChart(\'ch-gmv-mes\',\'bar\',cym,[{label:\'GMV\',data:cym.map(m=>cy[m]?.gmv||0),backgroundColor:\'#3483FA\',borderRadius:4}],{yFmt:v=>\'R$\'+v.toLocaleString(\'pt-BR\',{notation:\'compact\'})});\n  const momArr=cym.map(m=>{const p=allM2k[allM2k.indexOf(m)-1];if(!p)return null;const l=allM2[m]?.gmv||0,pv=allM2[p]?.gmv||0;return pv?+((l-pv)/pv*100).toFixed(1):null;});\n  const yoyArr=cym.map(m=>{const yy=allM2k.find(x=>x.slice(0,4)===String(parseInt(m.slice(0,4))-1)&&x.slice(5)===m.slice(5));if(!yy)return null;const l=allM2[m]?.gmv||0,y=allM2[yy]?.gmv||0;return y?+((l-y)/y*100).toFixed(1):null;});\n  makeChart(\'ch-gmv-delta\',\'line\',cym,[{label:\'MoM%\',data:momArr,borderColor:\'#3483FA\',backgroundColor:\'#3483FA22\',fill:true,tension:.3,pointRadius:3},{label:\'YoY%\',data:yoyArr,borderColor:\'#E83C49\',backgroundColor:\'#E83C4922\',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>v?.toFixed(1)+\'%\'});\n  makeChart(\'ch-si-mes\',\'bar\',cym,[{label:\'SI\',data:cym.map(m=>cy[m]?.si||0),backgroundColor:\'#00A650\',borderRadius:4}]);\n  makeChart(\'ch-asp-mes\',\'line\',cym,[{label:\'ASP\',data:cym.map(m=>{const g=cy[m]?.gmv||0,s=cy[m]?.si||0;return s?+(g/s).toFixed(2):null;}),borderColor:\'#FF7733\',backgroundColor:\'#FF773322\',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>\'R$\'+v?.toLocaleString(\'pt-BR\',{maximumFractionDigits:0})});\n  const mT=pc.gran===\'daily\'?null:(pc.curr||[]);\n  const byS=pc.gran===\'daily\'?(()=>{\n    const ids=sellerIds(state.seller),out={};\n    RAW.geral_daily.filter(r=>ids.includes(String(r.cust_id))&&r.dia>=pc.curr[0]&&r.dia<=pc.curr[1]).forEach(r=>{\n      const k=String(r.cust_id);\n      if(!out[k]){out[k]={gmv:0,si:0};}\n      out[k].gmv+=(Number(r.gmv)||0);out[k].si+=(Number(r.si)||0);\n    }); return out;\n  })():aggBySeller(RAW.geral_monthly,mT,[\'gmv\',\'si\']);\n  const tG=Object.values(byS).reduce((a,v)=>a+(v.gmv||0),0);\n  let h=`<thead><tr><th>Seller</th><th>GMV</th><th>SI</th><th>ASP</th><th>Share GMV</th></tr></thead><tbody>`;\n  Object.entries(byS).sort((a,b)=>b[1].gmv-a[1].gmv).forEach(([cid,v])=>{\n    const asp=v.si?v.gmv/v.si:0,share=tG?(v.gmv/tG)*100:0;\n    h+=`<tr><td>${sellerLabel(cid)}</td><td>${fmtBRL(v.gmv)}</td><td>${fmtNum(v.si)}</td><td>${fmtBRL(asp)}</td><td><span class="badge">${fmtPct(share)}</span></td></tr>`;\n  });\n  document.getElementById(\'tbl-geral-sellers\').innerHTML=h+\'</tbody>\';\n}\nfunction renderLogistica(){\n  const pc=getPeriodConfig(),allM=aggAllMonths(RAW.logistica_monthly,[\'gmv_total\',\'gmv_ff\',\'si_ff\',\'gmv_xd\',\'si_xd\',\'gmv_ss\',\'si_ss\']);\n  setBadge(\'period-badge-log\',pc);\n  const meses=pc.gran===\'daily\'?[]:pc.curr||[];\n  const gmvT=sumMeses(allM,meses,\'gmv_total\')||1;\n  const ffV=sumMeses(allM,meses,\'gmv_ff\'),xdV=sumMeses(allM,meses,\'gmv_xd\'),ssV=sumMeses(allM,meses,\'gmv_ss\');\n  const ffP=(ffV/gmvT)*100,xdP=(xdV/gmvT)*100,ssP=(ssV/gmvT)*100;\n  const ffK=computeKPI(pc,allM,\'gmv_ff\');\n  document.getElementById(\'kpi-log\').innerHTML=\n    `<div class="kpi-card"><div class="kpi-label">%FF (GMV)</div><div class="kpi-value">${fmtPct(ffP)}</div><div class="kpi-delta">${dHtml(ffK.d1,pc.d1Label||pc.prevLabel||\'vs ant.\')}</div></div>`+\n    `<div class="kpi-card"><div class="kpi-label">GMV FF</div><div class="kpi-value">${fmtBRL(ffK.value)}</div><div class="kpi-delta"><span class="dn0">—</span></div></div>`+\n    `<div class="kpi-card"><div class="kpi-label">%XD (GMV)</div><div class="kpi-value">${fmtPct(xdP)}</div><div class="kpi-delta"><span class="dn0">—</span></div></div>`+\n    `<div class="kpi-card"><div class="kpi-label">%SS (GMV)</div><div class="kpi-value">${fmtPct(ssP)}</div><div class="kpi-delta"><span class="dn0">—</span></div></div>`;\n  const cy=aggCurrentYear(RAW.logistica_monthly,[\'gmv_total\',\'gmv_ff\',\'si_ff\',\'gmv_xd\',\'si_xd\',\'gmv_ss\',\'si_ss\']),cym=Object.keys(cy).sort();\n  makeChart(\'ch-log-mix\',\'doughnut\',[\'Fulfillment\',\'Cross Docking\',\'Self Service\'],[{data:[ffP,xdP,ssP],backgroundColor:[\'#3483FA\',\'#FFE600\',\'#00A650\'],borderWidth:0}],{extra:{plugins:{legend:{display:true,position:\'bottom\'}}}});\n  makeChart(\'ch-ff-mes\',\'line\',cym,[{label:\'%FF\',data:cym.map(m=>{const d=cy[m];return d?.gmv_total?+((d.gmv_ff/d.gmv_total)*100).toFixed(1):null;}),borderColor:\'#3483FA\',backgroundColor:\'#3483FA22\',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>v?.toFixed(1)+\'%\'});\n  makeChart(\'ch-log-gmv\',\'bar\',cym,[{label:\'FF\',data:cym.map(m=>cy[m]?.gmv_ff||0),backgroundColor:\'#3483FA\',borderRadius:3},{label:\'XD\',data:cym.map(m=>cy[m]?.gmv_xd||0),backgroundColor:\'#FFE600\',borderRadius:3},{label:\'SS\',data:cym.map(m=>cy[m]?.gmv_ss||0),backgroundColor:\'#00A650\',borderRadius:3}],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:\'#F0F0F0\'}}}}});\n  makeChart(\'ch-log-si\',\'bar\',cym,[{label:\'FF\',data:cym.map(m=>cy[m]?.si_ff||0),backgroundColor:\'#3483FA\',borderRadius:3},{label:\'XD\',data:cym.map(m=>cy[m]?.si_xd||0),backgroundColor:\'#FFE600\',borderRadius:3},{label:\'SS\',data:cym.map(m=>cy[m]?.si_ss||0),backgroundColor:\'#00A650\',borderRadius:3}],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:\'#F0F0F0\'}}}}});\n  const bySL=aggBySeller(RAW.logistica_monthly,meses,[\'gmv_total\',\'gmv_ff\',\'gmv_xd\',\'gmv_ss\',\'si_total\',\'si_ff\']);\n  let h=`<thead><tr><th>Seller</th><th>GMV Total</th><th>GMV FF</th><th>%FF</th><th>GMV XD</th><th>%XD</th><th>GMV SS</th><th>%SS</th></tr></thead><tbody>`;\n  Object.entries(bySL).sort((a,b)=>b[1].gmv_total-a[1].gmv_total).forEach(([cid,v])=>{\n    const ff=v.gmv_total?(v.gmv_ff/v.gmv_total)*100:0,xd=v.gmv_total?(v.gmv_xd/v.gmv_total)*100:0,ss=v.gmv_total?(v.gmv_ss/v.gmv_total)*100:0;\n    h+=`<tr><td>${sellerLabel(cid)}</td><td>${fmtBRL(v.gmv_total)}</td><td>${fmtBRL(v.gmv_ff)}</td><td class="${ff>=50?\'tag-pos\':\'tag-neg\'}">${fmtPct(ff)}</td><td>${fmtBRL(v.gmv_xd)}</td><td>${fmtPct(xd)}</td><td>${fmtBRL(v.gmv_ss)}</td><td>${fmtPct(ss)}</td></tr>`;\n  });\n  document.getElementById(\'tbl-log-sellers\').innerHTML=h+\'</tbody>\';\n}\nfunction renderAds(){\n  const pc=getPeriodConfig(),allM=aggAllMonths(RAW.ads_monthly,[\'gmv\',\'ads_invest\',\'gmv_ads\']);\n  setBadge(\'period-badge-ads\',pc);\n  const meses=pc.gran===\'daily\'?[]:pc.curr||[];\n  const invK=computeKPI(pc,allM,\'ads_invest\'),invV=invK.value;\n  const gmvV=sumMeses(allM,meses,\'gmv\'),adsgV=sumMeses(allM,meses,\'gmv_ads\');\n  const roas=invV?+(adsgV/invV).toFixed(2):0,adsPct=gmvV?(invV/gmvV)*100:0;\n  const allMk=Object.keys(allM).sort(),lastM=meses[meses.length-1]||\'\';\n  const prevM=allMk[allMk.indexOf(lastM)-1];\n  const takeRate=prevM&&allM[prevM]?.gmv?(invV/allM[prevM].gmv)*100:null;\n  document.getElementById(\'kpi-ads\').innerHTML=\n    kpiCard(\'Investimento ADS\',fmtBRL(invV),pc,invK.d1,invK.d2)+\n    `<div class="kpi-card"><div class="kpi-label">ROAS</div><div class="kpi-value">${fmtDec(roas)}</div><div class="kpi-delta"><span class="dn0">—</span></div></div>`+\n    `<div class="kpi-card"><div class="kpi-label">ADS/GMV%</div><div class="kpi-value">${fmtPct(adsPct)}</div><div class="kpi-delta"><span class="dn0">—</span></div></div>`+\n    `<div class="kpi-card"><div class="kpi-label">Take Rate ADS</div><div class="kpi-value">${fmtPct(takeRate)}</div><div class="kpi-delta"><span class="dn0">Invest÷GMV(M-1)</span></div></div>`;\n  const cy=aggCurrentYear(RAW.ads_monthly,[\'gmv\',\'ads_invest\',\'gmv_ads\']),cym=Object.keys(cy).sort();\n  const allM2=aggAllMonths(RAW.ads_monthly,[\'gmv\']),allMk2=Object.keys(allM2).sort();\n  makeChart(\'ch-ads-invest\',\'bar\',cym,[{label:\'Investimento ADS\',data:cym.map(m=>cy[m]?.ads_invest||0),backgroundColor:\'#9B59B6\',borderRadius:4}],{yFmt:v=>\'R$\'+v.toLocaleString(\'pt-BR\',{notation:\'compact\'})});\n  makeChart(\'ch-roas\',\'line\',cym,[{label:\'ROAS\',data:cym.map(m=>{const d=cy[m];return d?.ads_invest?+(d.gmv_ads/d.ads_invest).toFixed(2):null;}),borderColor:\'#1ABC9C\',backgroundColor:\'#1ABC9C22\',fill:true,tension:.3,pointRadius:3}]);\n  makeChart(\'ch-ads-perc\',\'line\',cym,[{label:\'ADS/GMV%\',data:cym.map(m=>{const d=cy[m];return d?.gmv?+((d.ads_invest/d.gmv)*100).toFixed(2):null;}),borderColor:\'#E83C49\',backgroundColor:\'#E83C4922\',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>v?.toFixed(1)+\'%\'});\n  makeChart(\'ch-take-rate\',\'line\',cym,[{label:\'Take Rate %\',data:cym.map(m=>{const p=allMk2[allMk2.indexOf(m)-1];const gp=allM2[p]?.gmv||0,ic=cy[m]?.ads_invest||0;return gp?+((ic/gp)*100).toFixed(2):null;}),borderColor:\'#FF7733\',backgroundColor:\'#FF773322\',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>v?.toFixed(1)+\'%\'});\n  const bySA=aggBySeller(RAW.ads_monthly,meses,[\'gmv\',\'ads_invest\',\'gmv_ads\']);\n  let h=`<thead><tr><th>Seller</th><th>GMV</th><th>Invest. ADS</th><th>ROAS</th><th>ADS/GMV%</th></tr></thead><tbody>`;\n  Object.entries(bySA).sort((a,b)=>b[1].ads_invest-a[1].ads_invest).forEach(([cid,v])=>{\n    const r=v.ads_invest?+(v.gmv_ads/v.ads_invest).toFixed(2):0,p2=v.gmv?(v.ads_invest/v.gmv)*100:0;\n    h+=`<tr><td>${sellerLabel(cid)}</td><td>${fmtBRL(v.gmv)}</td><td>${fmtBRL(v.ads_invest)}</td><td>${fmtDec(r)}</td><td>${fmtPct(p2)}</td></tr>`;\n  });\n  document.getElementById(\'tbl-ads-sellers\').innerHTML=h+\'</tbody>\';\n}\nfunction renderInvestimentos(){\n  const pc=getPeriodConfig(),allM=aggAllMonths(RAW.investimentos_monthly,[\'gmv\',\'cupons\',\'rebate_pre\',\'rebate_outras\',\'total_invest\']);\n  setBadge(\'period-badge-inv\',pc);\n  const meses=pc.gran===\'daily\'?[]:pc.curr||[];\n  const invK=computeKPI(pc,allM,\'total_invest\');\n  const li={cupons:sumMeses(allM,meses,\'cupons\'),rebate_pre:sumMeses(allM,meses,\'rebate_pre\'),rebate_outras:sumMeses(allM,meses,\'rebate_outras\'),total_invest:invK.value};\n  document.getElementById(\'kpi-inv\').innerHTML=\n    kpiCard(\'Total Investido\',fmtBRL(li.total_invest),pc,invK.d1,invK.d2)+\n    `<div class="kpi-card"><div class="kpi-label">Cupons</div><div class="kpi-value">${fmtBRL(li.cupons)}</div><div class="kpi-delta"><span class="dn0">—</span></div></div>`+\n    `<div class="kpi-card"><div class="kpi-label">Rebate Pré-neg.</div><div class="kpi-value">${fmtBRL(li.rebate_pre)}</div><div class="kpi-delta"><span class="dn0">—</span></div></div>`+\n    `<div class="kpi-card"><div class="kpi-label">Rebate Outras</div><div class="kpi-value">${fmtBRL(li.rebate_outras)}</div><div class="kpi-delta"><span class="dn0">—</span></div></div>`;\n  const cy=aggCurrentYear(RAW.investimentos_monthly,[\'gmv\',\'cupons\',\'rebate_pre\',\'rebate_outras\',\'total_invest\']),cym=Object.keys(cy).sort();\n  makeChart(\'ch-inv-total\',\'bar\',cym,[{label:\'Cupons\',data:cym.map(m=>cy[m]?.cupons||0),backgroundColor:\'#FFE600\',borderRadius:3},{label:\'Rebate Pré\',data:cym.map(m=>cy[m]?.rebate_pre||0),backgroundColor:\'#3483FA\',borderRadius:3},{label:\'Rebate Outras\',data:cym.map(m=>cy[m]?.rebate_outras||0),backgroundColor:\'#00A650\',borderRadius:3}],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:\'#F0F0F0\'}}}}});\n  makeChart(\'ch-inv-mix\',\'doughnut\',[\'Cupons\',\'Rebate Pré-neg.\',\'Rebate Outras\'],[{data:[li.cupons,li.rebate_pre,li.rebate_outras],backgroundColor:[\'#FFE600\',\'#3483FA\',\'#00A650\'],borderWidth:0}],{extra:{plugins:{legend:{display:true,position:\'bottom\'}}}});\n  makeChart(\'ch-cupons\',\'line\',cym,[{label:\'Cupons\',data:cym.map(m=>cy[m]?.cupons||0),borderColor:\'#E67E22\',backgroundColor:\'#E67E2222\',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>\'R$\'+v.toLocaleString(\'pt-BR\',{notation:\'compact\'})});\n  makeChart(\'ch-rebates\',\'line\',cym,[{label:\'Pré-neg.\',data:cym.map(m=>cy[m]?.rebate_pre||0),borderColor:\'#3483FA\',fill:false,tension:.3,pointRadius:3},{label:\'Outras\',data:cym.map(m=>cy[m]?.rebate_outras||0),borderColor:\'#00A650\',fill:false,tension:.3,pointRadius:3}],{yFmt:v=>\'R$\'+v.toLocaleString(\'pt-BR\',{notation:\'compact\'})});\n  const bySI=aggBySeller(RAW.investimentos_monthly,meses,[\'gmv\',\'cupons\',\'rebate_pre\',\'rebate_outras\',\'total_invest\']);\n  let h=`<thead><tr><th>Seller</th><th>GMV</th><th>Cupons</th><th>Rebate Pré</th><th>Rebate Outras</th><th>Total Invest.</th><th>Invest/GMV%</th></tr></thead><tbody>`;\n  Object.entries(bySI).sort((a,b)=>b[1].total_invest-a[1].total_invest).forEach(([cid,v])=>{\n    const p2=v.gmv?(v.total_invest/v.gmv)*100:0;\n    h+=`<tr><td>${sellerLabel(cid)}</td><td>${fmtBRL(v.gmv)}</td><td>${fmtBRL(v.cupons)}</td><td>${fmtBRL(v.rebate_pre)}</td><td>${fmtBRL(v.rebate_outras)}</td><td><b>${fmtBRL(v.total_invest)}</b></td><td>${fmtPct(p2)}</td></tr>`;\n  });\n  document.getElementById(\'tbl-inv-sellers\').innerHTML=h+\'</tbody>\';\n}\nfunction renderCatalogo(){\n  const ids=sellerIds(state.seller),rows=RAW.catalogo_items.filter(r=>ids.includes(String(r.cust_id)));\n  const tG=rows.reduce((a,r)=>a+(Number(r.gmv)||0),0);\n  let h=`<thead><tr><th>Seller</th><th>Item ID</th><th>Título</th><th>GMV</th><th>SI</th><th>ASP</th><th>Share %</th><th>GMV BB</th><th>BB%</th></tr></thead><tbody>`;\n  rows.forEach(r=>{\n    const share=tG?(Number(r.gmv)/tG)*100:0,bbPct=Number(r.gmv)?(Number(r.gmv_bb)/Number(r.gmv))*100:0;\n    h+=`<tr><td>${sellerLabel(r.cust_id)}</td><td>${r.item_id}</td><td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.titulo||\'\'}</td><td>${fmtBRL(r.gmv)}</td><td>${fmtNum(r.si)}</td><td>${fmtBRL(r.asp)}</td><td><span class="badge">${fmtPct(share)}</span></td><td>${fmtBRL(r.gmv_bb)}</td><td class="${bbPct>=50?\'tag-pos\':\'tag-neg\'}">${fmtPct(bbPct)}</td></tr>`;\n  });\n  document.getElementById(\'tbl-catalogo\').innerHTML=h+\'</tbody>\';\n}\nfunction setPeriod(p,btn){\n  state.period=p;\n  document.querySelectorAll(\'.period-bar .btn:not(.custom-btn)\').forEach(b=>b.classList.remove(\'active\'));\n  if(btn)btn.classList.add(\'active\');\n  document.getElementById(\'custom-btn\').classList.remove(\'active\');\n  document.getElementById(\'custom-dropdown\').classList.remove(\'open\');\n  renderAll();\n}\nfunction setSeller(val){\n  state.seller=MULTI_GROUPS.includes(String(val))?String(val):(val===\'all\'?\'all\':Number(val));\n  buildSidebar();renderAll();\n}\nfunction setTab(tab,el){\n  state.tab=tab;\n  document.querySelectorAll(\'.tab\').forEach(t=>t.classList.remove(\'active\'));\n  if(el)el.classList.add(\'active\');\n  document.querySelectorAll(\'.tab-content\').forEach(t=>t.classList.remove(\'active\'));\n  document.getElementById(\'tab-\'+tab).classList.add(\'active\');\n  renderAll();\n}\nfunction toggleCustom(){document.getElementById(\'custom-dropdown\').classList.toggle(\'open\');}\nfunction applyCustom(){\n  const s=document.getElementById(\'custom-start\').value,e=document.getElementById(\'custom-end\').value;\n  if(!s)return;\n  state.period=\'custom\';state.customStart=s;state.customEnd=e||s;\n  document.querySelectorAll(\'.period-bar .btn:not(.custom-btn)\').forEach(b=>b.classList.remove(\'active\'));\n  document.getElementById(\'custom-btn\').classList.add(\'active\');\n  document.getElementById(\'custom-dropdown\').classList.remove(\'open\');\n  renderAll();\n}\nfunction quickPick(key){\n  const now=new Date(),fD=d=>d.toISOString().slice(0,10),dow=now.getDay();let s,e;\n  if(key===\'yesterday\'){const d=addDays(now,-1);s=e=fD(d);}\n  else if(key===\'last-week\'){const toSat=dow===6?7:dow+1,wEnd=addDays(now,-toSat);s=fD(addDays(wEnd,-6));e=fD(wEnd);}\n  else if(key===\'this-month\'){s=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,\'0\')}-01`;e=fD(now);}\n  else if(key===\'last-month\'){const pm=now.getMonth()===0?new Date(now.getFullYear()-1,11,1):new Date(now.getFullYear(),now.getMonth()-1,1);s=fD(pm);e=fD(new Date(pm.getFullYear(),pm.getMonth()+1,0));}\n  else if(key===\'this-quarter\'){const q=Math.floor(now.getMonth()/3);s=`${now.getFullYear()}-${String(q*3+1).padStart(2,\'0\')}-01`;e=fD(now);}\n  else if(key===\'this-year\'){s=`${now.getFullYear()}-01-01`;e=fD(now);}\n  if(s){document.getElementById(\'custom-start\').value=s;document.getElementById(\'custom-end\').value=e||s;}\n}\ndocument.addEventListener(\'click\',e=>{\n  const w=document.querySelector(\'.custom-wrap\');\n  if(w&&!w.contains(e.target))document.getElementById(\'custom-dropdown\').classList.remove(\'open\');\n});\nfunction renderAll(){\n  if(state.tab===\'geral\')         renderGeral();\n  if(state.tab===\'logistica\')     renderLogistica();\n  if(state.tab===\'ads\')           renderAds();\n  if(state.tab===\'investimentos\') renderInvestimentos();\n  if(state.tab===\'catalogo\')      renderCatalogo();\n}\ndocument.getElementById(\'updated-at\').textContent=\'Atualizado: \'+RAW.updated_at;\nbuildSidebar();\nrenderAll();\n</script>\n</body>\n</html>\n'""


# ── Main ──────────────────────────────────────────────────────────────────────
def generate():
    dataset = build_dataset()
    data_json = json.dumps(dataset, ensure_ascii=False, default=str)
    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)

    out_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard gerado: {out_path}")

    repo_dir = os.path.dirname(__file__)
    try:
        subprocess.run(["git", "add", "index.html"], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m",
                        f"chore: atualiza\u00e7\u00e3o autom\u00e1tica {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
                       cwd=repo_dir, check=True)
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)
        print("Push para GitHub Pages conclu\u00eddo.")
    except subprocess.CalledProcessError as e:
        print(f"Git push falhou: {e}")


if __name__ == "__main__":
    generate()
