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
import time
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
    time.sleep(5)
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


def q_logistica_daily():
    """Logistica por tipo por seller por dia - ultimos 90 dias."""
    ff = "', '".join(FF_TYPES)
    xd = "', '".join(XD_TYPES)
    ss = "', '".join(SS_TYPES)
    return run(f"""
        SELECT
            CAST(ORD_CLOSED_DT AS STRING)                                            AS dia,
            CUS_CUST_ID_SEL                                                          AS cust_id,
            ROUND(SUM(GMV_LC),2)                                                     AS gmv_total,
            ROUND(SUM(CASE WHEN LOGISTIC_TYPE IN ('{ff}') THEN GMV_LC ELSE 0 END),2) AS gmv_ff,
            ROUND(SUM(CASE WHEN LOGISTIC_TYPE IN ('{xd}') THEN GMV_LC ELSE 0 END),2) AS gmv_xd,
            ROUND(SUM(CASE WHEN LOGISTIC_TYPE IN ('{ss}') THEN GMV_LC ELSE 0 END),2) AS gmv_ss
        FROM {TABLE}
        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
          AND GMV_FLG = TRUE
          AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
          AND ORD_CLOSED_DT < CURRENT_DATE()
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_ads_daily():
    """ADS por seller por dia - ultimos 90 dias - BT_ADS_PADS_METRICS_DAILY."""
    return run(f"""
        SELECT
            CAST(EVENT_LOCAL_DT AS STRING)         AS dia,
            SELLER_ID                              AS cust_id,
            ROUND(SUM(ADS_COST_AMT_LC),2)          AS ads_invest,
            ROUND(SUM(TOUCHPOINT_GMV_LC),2)        AS gmv_ads,
            SUM(CLICKS_BILLED_QTY)                 AS clicks
        FROM `meli-bi-data.WHOWNER.BT_ADS_PADS_METRICS_DAILY`
        WHERE SELLER_ID IN ({IDS_STR})
          AND SIT_SITE_ID = 'MLB'
          AND EVENT_LOCAL_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
          AND EVENT_LOCAL_DT < CURRENT_DATE()
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_investimentos_daily():
    """Investimentos 3 grupos por seller por dia - ultimos 90 dias."""
    return run(f"""
        SELECT
            CAST(ORD_CLOSED_DT AS STRING)   AS dia,
            CUS_CUST_ID_SEL                 AS cust_id,
            ROUND(SUM(CASE WHEN DXI_CAMPAIGN_SUBTYPE = 'PRE_ACORDO' THEN COALESCE(DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS g1_pre_acordo,
            ROUND(SUM(COALESCE(DOD_INVESTMENT_LC,0)),2)        AS g1_dod,
            ROUND(SUM(COALESCE(LIGHTNING_INVESTMENT_LC,0)),2)  AS g1_relampago,
            ROUND(SUM(CASE WHEN PRICING_MATCHING_FLG = TRUE THEN COALESCE(DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS g2_price_matching,
            ROUND(SUM(CASE WHEN SMART_CAMPAIGN_FLG   = TRUE THEN COALESCE(DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS g2_smart,
            ROUND(SUM(COALESCE(AUTOMATIC_CAMPAIGN_INVESTMENT_LC,0)),2) AS g2_automaticas,
            ROUND(SUM(CASE WHEN CPN_SELLER_FLG = FALSE THEN COALESCE(CPN_AMOUNT_LC,0) ELSE 0 END),2) AS g3_cupons_ml
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
    """ADS: investimento e GMV atribuido por seller por mes -- BT_ADS_PADS_METRICS_DAILY."""
    return run(f"""
        SELECT
            FORMAT_DATE('%Y-%m', EVENT_LOCAL_DT)       AS mes,
            SELLER_ID                                   AS cust_id,
            ROUND(SUM(ADS_COST_AMT_LC), 2)             AS ads_invest,
            ROUND(SUM(TOUCHPOINT_GMV_LC), 2)           AS gmv_ads,
            SUM(CLICKS_BILLED_QTY)                     AS clicks
        FROM `meli-bi-data.WHOWNER.BT_ADS_PADS_METRICS_DAILY`
        WHERE SELLER_ID IN ({IDS_STR})
          AND SIT_SITE_ID = 'MLB'
          AND EVENT_LOCAL_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND EVENT_LOCAL_DT < CURRENT_DATE()
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_investimentos_monthly():
    """Investimentos em 3 grupos por seller por mes."""
    return run(f"""
        SELECT
            FORMAT_DATE('%Y-%m', ORD_CLOSED_DT)   AS mes,
            CUS_CUST_ID_SEL                        AS cust_id,
            ROUND(SUM(GMV_LC), 2)                  AS gmv,
            -- Grupo 1: Comercial (Pandora)
            ROUND(SUM(CASE WHEN DXI_CAMPAIGN_SUBTYPE = 'PRE_ACORDO' THEN COALESCE(DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS g1_pre_acordo,
            ROUND(SUM(COALESCE(DOD_INVESTMENT_LC,0)),2)        AS g1_dod,
            ROUND(SUM(COALESCE(LIGHTNING_INVESTMENT_LC,0)),2)  AS g1_relampago,
            -- Grupo 2: Central de Promocoes
            ROUND(SUM(CASE WHEN PRICING_MATCHING_FLG = TRUE THEN COALESCE(DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS g2_price_matching,
            ROUND(SUM(CASE WHEN SMART_CAMPAIGN_FLG   = TRUE THEN COALESCE(DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS g2_smart,
            ROUND(SUM(COALESCE(AUTOMATIC_CAMPAIGN_INVESTMENT_LC,0)),2) AS g2_automaticas,
            -- Grupo 3: Cupons ML
            ROUND(SUM(CASE WHEN CPN_SELLER_FLG = FALSE THEN COALESCE(CPN_AMOUNT_LC,0) ELSE 0 END),2) AS g3_cupons_ml
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


def q_seller_reputation():
    """Reputacao atual dos sellers da carteira."""
    return run(f"""
        SELECT
            CUS_CUST_ID_SEL                                AS cust_id,
            REP_CURRENT_LEVEL,
            REP_REAL_LEVEL,
            ROUND(REP_CLAIMS_RATE*100, 2)                  AS claims_pct,
            ROUND(REP_DELAYED_HT_RATE*100, 2)              AS delay_pct,
            ROUND(REP_SELLER_CANCELLATIONS_RATE*100, 2)    AS cancel_pct,
            CAST(REP_3_MTH_TX AS INT64)                    AS orders_3m
        FROM `meli-bi-data.WHOWNER.BT_REP_SELLER_REPUTATION`
        WHERE SIT_SITE_ID = 'MLB'
          AND CUS_CUST_ID_SEL IN ({IDS_STR})
    """)


def q_visitas_monthly():
    """Visitas por seller por mes -- BT_VISITS_ITEM."""
    return run(f"""
        SELECT
            FORMAT_DATE('%Y-%m', TIM_DAY)   AS mes,
            CUS_CUST_ID_SEL                 AS cust_id,
            SUM(QTY_PAGEVIEWS)              AS visits,
            SUM(QTY_PAGEVIEWS_VIP)          AS visits_vip
        FROM `meli-bi-data.WHOWNER.BT_VISITS_ITEM`
        WHERE SIT_SITE_ID = 'MLB'
          AND CUS_CUST_ID_SEL IN ({IDS_STR})
          AND TIM_DAY >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND TIM_DAY < CURRENT_DATE()
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_visitas_daily():
    """Visitas por seller por dia -- ultimos 90 dias."""
    return run(f"""
        SELECT
            CAST(TIM_DAY AS STRING)         AS dia,
            CUS_CUST_ID_SEL                 AS cust_id,
            SUM(QTY_PAGEVIEWS)              AS visits
        FROM `meli-bi-data.WHOWNER.BT_VISITS_ITEM`
        WHERE SIT_SITE_ID = 'MLB'
          AND CUS_CUST_ID_SEL IN ({IDS_STR})
          AND TIM_DAY >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
          AND TIM_DAY < CURRENT_DATE()
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)


def q_visitas_items():
    """Top 50 itens por visitas por seller -- ultimos 90 dias."""
    return run(f"""
        SELECT
            CUS_CUST_ID_SEL                 AS cust_id,
            ITE_ITEM_ID                     AS item_id,
            SUM(QTY_PAGEVIEWS)              AS visits,
            SUM(QTY_PAGEVIEWS_VIP)          AS visits_vip
        FROM `meli-bi-data.WHOWNER.BT_VISITS_ITEM`
        WHERE SIT_SITE_ID = 'MLB'
          AND CUS_CUST_ID_SEL IN ({IDS_STR})
          AND TIM_DAY >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
          AND TIM_DAY < CURRENT_DATE()
        GROUP BY 1, 2
        QUALIFY ROW_NUMBER() OVER (PARTITION BY CUS_CUST_ID_SEL ORDER BY SUM(QTY_VISITS) DESC) <= 50
        ORDER BY 1, 3 DESC
    """)


def q_bpc_aurora():
    """BPC e Aurora: competitividade de preco por item -- BT_COM_FAVORABILITY + LK_PRICING_TOOLS_BPC_AURORA_ITEMS_AUDIT."""
    ids_q = "'383523670','794123311','568773774','70123968','2355501248','638325656','1802758219','700583148'"
    return run(f"""
        WITH last_day AS (
            SELECT MAX(TIM_DAY) AS max_day
            FROM `meli-bi-data.WHOWNER.BT_COM_FAVORABILITY`
            WHERE FAVORABILITY_TYPE = 'BOX_MATCH_SELLER' AND SIT_SITE_ID = 'MLB'
              AND FLG_BULKY = 'false' AND TIM_DAY >= CURRENT_DATE() - 15
        ),
        bpc AS (
            SELECT CAST(H.CUS_CUST_ID_SEL AS STRING) AS SELLER_ID,
                CAST(H.MELI_ID AS STRING) AS MELI_ID,
                ROUND(SUM(H.VISITS_MATCH), 2) AS VISITS_MATCH,
                ROUND(SUM(CASE WHEN H.PRICE_MELI > 0 AND H.COMP_PRICE_RIVAL > 0
                                AND H.PRICE_MELI > 1.03 * H.COMP_PRICE_RIVAL
                               THEN H.VISITS_MATCH ELSE 0 END), 2) AS VISITS_EXP3
            FROM `meli-bi-data.WHOWNER.BT_COM_FAVORABILITY` AS H
            WHERE H.FAVORABILITY_TYPE = 'BOX_MATCH_SELLER' AND H.SIT_SITE_ID = 'MLB'
              AND H.FLG_BULKY = 'false' AND H.TIM_DAY >= CURRENT_DATE() - 15
              AND CAST(H.CUS_CUST_ID_SEL AS STRING) IN ({ids_q})
            GROUP BY 1, 2 HAVING SUM(H.VISITS_MATCH) > 0
        ),
        items_last_day AS (
            SELECT CAST(H.CUS_CUST_ID_SEL AS STRING) AS SELLER_ID,
                CAST(H.MELI_ID AS STRING) AS MELI_ID,
                CAST(H.ITE_ITEM_ID AS STRING) AS ITE_ITEM_ID,
                H.PRICE_MELI, H.COMP_PRICE_RIVAL,
                H.COMP_RIVAL_NAME_WINNER AS COMP_RIVAL_NAME,
                H.COMP_URL_WINNER AS COMP_URL, H.PERMALINK, H.TITLE,
                ROW_NUMBER() OVER (
                    PARTITION BY H.CUS_CUST_ID_SEL, H.MELI_ID, H.ITE_ITEM_ID
                    ORDER BY H.COMP_PRICE_RIVAL ASC
                ) AS rn
            FROM `meli-bi-data.WHOWNER.BT_COM_FAVORABILITY` H
            CROSS JOIN last_day
            WHERE H.FAVORABILITY_TYPE = 'BOX_MATCH_SELLER' AND H.SIT_SITE_ID = 'MLB'
              AND H.FLG_BULKY = 'false' AND H.TIM_DAY = last_day.max_day
              AND CAST(H.CUS_CUST_ID_SEL AS STRING) IN ({ids_q})
        ),
        audit_items AS (
            SELECT CAST(VALUE.SELLER_ID AS STRING) AS SELLER_ID,
                VALUE.ITEM_ID AS ITEM_ID, VALUE.ITEM_PRICE AS PRICE_MELI,
                VALUE.TARGET_PRICE, VALUE.COMP_RIVAL_NAME, VALUE.COMP_URL,
                VALUE.PERMALINK, VALUE.IS_OFFENDER, VALUE.SELLER_QUALIFICATION
            FROM `meli-bi-data.WHOWNER.LK_PRICING_TOOLS_BPC_AURORA_ITEMS_AUDIT`
            WHERE DATE(ARRIVAL_DATE) >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
              AND CAST(VALUE.SELLER_ID AS STRING) IN ({ids_q})
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY VALUE.ITEM_ID, VALUE.SELLER_ID ORDER BY ARRIVAL_DATE DESC
            ) = 1
        )
        SELECT b.SELLER_ID, i.ITE_ITEM_ID, b.VISITS_MATCH, b.VISITS_EXP3,
            COALESCE(a.PRICE_MELI, i.PRICE_MELI)             AS PRICE_MELI,
            COALESCE(a.TARGET_PRICE, i.COMP_PRICE_RIVAL)     AS COMP_PRICE_RIVAL_MIN,
            COALESCE(a.COMP_RIVAL_NAME, i.COMP_RIVAL_NAME)   AS COMP_RIVAL_NAME,
            COALESCE(a.COMP_URL, i.COMP_URL)                  AS COMP_URL,
            COALESCE(a.PERMALINK, i.PERMALINK)                AS PERMALINK,
            i.TITLE, a.SELLER_QUALIFICATION,
            CASE WHEN COALESCE(a.PRICE_MELI, i.PRICE_MELI) > 0
                  AND COALESCE(a.TARGET_PRICE, i.COMP_PRICE_RIVAL) > 0
                  AND COALESCE(a.PRICE_MELI, i.PRICE_MELI) > 1.03 * COALESCE(a.TARGET_PRICE, i.COMP_PRICE_RIVAL)
                 THEN 'Nao Competitivo' ELSE 'Competitivo' END AS CLASSIFICACAO
        FROM bpc b
        JOIN items_last_day i ON b.SELLER_ID = i.SELLER_ID AND b.MELI_ID = i.MELI_ID AND i.rn = 1
        LEFT JOIN audit_items a
            ON CONCAT('MLB', i.ITE_ITEM_ID) = a.ITEM_ID AND b.SELLER_ID = a.SELLER_ID
        ORDER BY b.SELLER_ID, b.VISITS_EXP3 DESC
        LIMIT 500
    """)


def q_campanhas():
    """Campanhas por item/seller -- LK_MKP_CAMPAIGN_ITEM_OPTIN + LK_MKP_CAMPAIGNS_ELEGIBLE_ITEMS."""
    return run(f"""
        SELECT
            o.TYPE                         AS tipo,
            o.DS                           AS data,
            o.CUS_CUST_ID_SEL             AS cust_id,
            o.ITE_ITEM_ID                  AS item_id,
            o.ITEM_CANDIDATE_FLG           AS elegivel,
            o.ITEM_WITH_OFFER_FLG          AS opt_in,
            ROUND(e.ITE_CAM_FIRST_TAG_PRICE, 2) AS preco_inicial,
            ROUND(e.ITE_CAM_TAG_PRICE, 2)  AS preco_final,
            e.ITE_CAM_TAG_STATUS           AS status_campanha,
            ROUND(o.ITEM_TGMV_L30D, 2)    AS gmv_l30d
        FROM `meli-bi-data.WHOWNER.LK_MKP_CAMPAIGN_ITEM_OPTIN` o
        LEFT JOIN `meli-bi-data.WHOWNER.LK_MKP_CAMPAIGNS_ELEGIBLE_ITEMS` e
            ON o.PROMOTION_ID = e.CAM_CAMPAIGN_ID AND o.ITE_ITEM_ID = e.ITE_ITEM_ID
        WHERE o.SIT_SITE_ID = 'MLB'
          AND o.CUS_CUST_ID_SEL IN ({IDS_STR})
          AND o.DS >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
        AND o.ITEM_CANDIDATE_FLG = TRUE
        ORDER BY o.CUS_CUST_ID_SEL, o.DS DESC, o.ITEM_WITH_OFFER_FLG DESC, o.TYPE, o.ITE_ITEM_ID
        LIMIT 1500
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
    print("  -> Logistica diaria...")
    log_d    = q_logistica_daily()
    print("  → ADS...")
    ads_m    = q_ads_monthly()
    print("  -> ADS diario...")
    ads_d    = q_ads_daily()
    print("  → Investimentos...")
    inv_m    = q_investimentos_monthly()
    print("  -> Investimentos diario...")
    inv_d    = q_investimentos_daily()
    print("  → BuyBox...")
    bb_m     = q_buybox_monthly()
    print("  → Catálogo top itens...")
    cat      = q_catalogo_top_items()
    print("  -> Reputacao sellers...")
    rep      = q_seller_reputation()
    print("  -> Visitas mensal...")
    vis_m    = q_visitas_monthly()
    print("  -> Visitas diario...")
    vis_d    = q_visitas_daily()
    print("  -> Visitas por item...")
    vis_i    = q_visitas_items()
    print("  -> BPC e Aurora...")
    bpc      = q_bpc_aurora()
    print("  -> Campanhas...")
    camp     = q_campanhas()
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
        "logistica_daily":     clean_rows(log_d),
        "ads_monthly":         clean_rows(ads_m),
        "ads_daily":           clean_rows(ads_d),
        "investimentos_monthly": clean_rows(inv_m),
        "investimentos_daily": clean_rows(inv_d),
        "buybox_monthly":      clean_rows(bb_m),
        "catalogo_items":      clean_rows(cat),
        "seller_reputation":   clean_rows(rep),
        "visitas_monthly":     clean_rows(vis_m),
        "visitas_daily":       clean_rows(vis_d),
        "visitas_items":       clean_rows(vis_i),
        "bpc_aurora":          clean_rows(bpc),
        "campanhas":           clean_rows(camp),
    }






# ── HTML template ─────────────────────────────────────────────────────────────
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard MeliPro | Lucas Sanches</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
  --ml-yellow:#FFE600;--ml-blue:#2D3277;--ml-blue2:#3483FA;
  --bg:#F5F5F5;--card:#fff;--txt:#333;--muted:#777;
  --green:#00A650;--red:#E83C49;--border:#E0E0E0;
  --sidebar-w:200px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Proxima Nova',Arial,sans-serif;background:var(--bg);color:var(--txt);font-size:14px;height:100vh;display:flex;flex-direction:column}
.header{background:var(--ml-yellow);padding:10px 20px;display:flex;align-items:center;gap:14px;box-shadow:0 2px 4px rgba(0,0,0,.12);flex-shrink:0}
.logo{height:44px;object-fit:contain}
.header-title{font-size:18px;font-weight:700;color:var(--ml-blue)}
.header-sub{font-size:11px;color:var(--ml-blue);opacity:.7;margin-top:1px}
.updated{margin-left:auto;font-size:11px;color:var(--ml-blue);opacity:.6;white-space:nowrap}
.period-bar{background:#fff;border-bottom:1px solid var(--border);padding:8px 20px;display:flex;gap:6px;align-items:center;flex-shrink:0;flex-wrap:wrap}
.period-label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-right:2px}
.btn{padding:5px 13px;border:1px solid var(--border);border-radius:20px;background:#fff;cursor:pointer;font-size:12px;color:var(--txt);transition:all .15s;white-space:nowrap}
.btn:hover{background:#f0f0f0}
.btn.active{background:var(--ml-blue);color:#fff;border-color:var(--ml-blue)}
.btn.custom-btn{border-style:dashed}
.btn.custom-btn.active{border-style:solid}
.custom-wrap{position:relative;display:inline-block}
.custom-dropdown{display:none;position:absolute;top:calc(100% + 6px);left:0;background:#fff;border:1px solid var(--border);border-radius:8px;padding:14px;box-shadow:0 4px 16px rgba(0,0,0,.12);z-index:100;min-width:280px}
.custom-dropdown.open{display:block}
.custom-dropdown label{font-size:11px;font-weight:700;color:var(--muted);display:block;margin-bottom:3px;margin-top:10px}
.custom-dropdown label:first-child{margin-top:0}
.custom-dropdown input[type=date]{width:100%;border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px;outline:none}
.custom-dropdown .apply-btn{margin-top:12px;width:100%;padding:8px;background:var(--ml-blue);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600}
.quick-btns{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:4px}
.quick-btn{padding:4px 10px;border:1px solid var(--border);border-radius:12px;background:#fff;cursor:pointer;font-size:11px;color:var(--txt)}
.quick-btn:hover{background:var(--ml-yellow);border-color:var(--ml-yellow)}
.layout{display:flex;flex:1;overflow:hidden}
.sidebar{width:var(--sidebar-w);background:#fff;border-right:1px solid var(--border);overflow-y:auto;flex-shrink:0;padding:8px 0;transition:width .2s,padding .2s}
.sidebar.collapsed{width:0;padding:0;border:none}
.sb-toggle{width:18px;background:#F0F0F0;border:none;cursor:pointer;font-size:11px;color:var(--muted);flex-shrink:0;display:flex;align-items:center;justify-content:center;border-right:1px solid var(--border);transition:background .15s}
.sb-toggle:hover{background:var(--ml-yellow);color:var(--ml-blue)}
.s-section-title{padding:6px 16px;font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;background:#F8F8F8;}
.s-item{padding:9px 16px;cursor:pointer;font-size:13px;color:var(--txt);display:flex;align-items:center;gap:8px;transition:all .15s;border-left:3px solid transparent}
.s-item:hover{background:#F5F5F5}
.s-item.active{background:#EEF4FF;color:var(--ml-blue);font-weight:700;border-left-color:var(--ml-blue2)}
.s-divider{height:1px;background:var(--border);margin:6px 12px}
.s-group-header{padding:9px 16px;cursor:pointer;font-size:13px;color:var(--txt);display:flex;align-items:center;gap:8px;border-left:3px solid transparent;transition:all .15s;}
.s-group-header:hover{background:#F5F5F5}
.s-group-header.active{background:#EEF4FF;color:var(--ml-blue);border-left-color:var(--ml-blue2)}
.s-arrow{font-size:10px;transition:transform .2s;display:inline-block;cursor:pointer;padding:2px 4px}
.s-arrow.open{transform:rotate(90deg)}
.s-sub{padding:7px 16px 7px 32px;cursor:pointer;font-size:12px;color:var(--muted);border-left:3px solid transparent;transition:all .15s}
.s-sub:hover{background:#F5F5F5;color:var(--txt)}
.s-sub.active{background:#EEF4FF;color:var(--ml-blue);font-weight:600;border-left-color:var(--ml-blue2)}
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.main-tabs{display:flex;background:#fff;border-bottom:2px solid var(--border);flex-shrink:0;padding:0 20px;overflow-x:auto}
.tab{padding:11px 18px;cursor:pointer;font-size:13px;font-weight:600;color:var(--muted);border-bottom:3px solid transparent;margin-bottom:-2px;white-space:nowrap;transition:all .15s}
.tab:hover{color:var(--ml-blue)}
.tab.active{color:var(--ml-blue);border-bottom-color:var(--ml-blue2)}
.main-content{flex:1;overflow-y:auto;padding:18px 20px}
.tab-content{display:none}
.tab-content.active{display:block}
.period-badge{display:inline-block;background:var(--ml-blue);color:#fff;font-size:11px;font-weight:700;padding:2px 10px;border-radius:10px;margin-bottom:14px}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}
.kpi-card{background:var(--card);border-radius:8px;padding:14px 16px;border:1px solid var(--border);box-shadow:0 1px 3px rgba(0,0,0,.05)}
.kpi-label{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.kpi-value{font-size:22px;font-weight:700;color:var(--ml-blue);margin:5px 0 4px;line-height:1}
.kpi-delta{font-size:11px;display:flex;gap:8px;flex-wrap:wrap}
.dp{color:var(--green);font-weight:600}
.dn{color:var(--red);font-weight:600}
.dn0{color:var(--muted)}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px;margin-bottom:18px}
.chart-card{background:var(--card);border-radius:8px;padding:14px;border:1px solid var(--border);box-shadow:0 1px 3px rgba(0,0,0,.05)}
.chart-title{font-size:12px;font-weight:700;color:var(--ml-blue);margin-bottom:10px}
.chart-wrap{position:relative;height:220px}
.table-wrap{background:var(--card);border-radius:8px;border:1px solid var(--border);overflow:auto;box-shadow:0 1px 3px rgba(0,0,0,.05);margin-bottom:18px}
.section-title{font-size:13px;font-weight:700;color:var(--ml-blue);margin:16px 0 8px;display:flex;align-items:center;gap:8px}
.section-title::after{content:'';flex:1;height:1px;background:var(--border)}
table{width:100%;border-collapse:collapse}
thead tr{background:var(--ml-blue);color:#fff}
th{padding:9px 11px;text-align:right;font-size:11px;font-weight:600;letter-spacing:.3px;white-space:nowrap}
th:first-child{text-align:left}
tbody tr{border-bottom:1px solid var(--border)}
tbody tr:hover{background:#FAFAFA}
td{padding:8px 11px;text-align:right;font-size:12px;white-space:nowrap}
td:first-child{text-align:left;font-weight:500}
.tag-pos{color:var(--green);font-weight:600}
.tag-neg{color:var(--red);font-weight:600}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;background:var(--ml-yellow);color:var(--ml-blue)}
</style>
</head>
<body>
<div class="header">
  <img class="logo" src="data:image/png;base64,__LOGO__" alt="Mercado Livre">
  <div><div class="header-title">Dashboard MeliPro | Lucas Sanches</div>
  <div class="header-sub">Vis\u00e3o 360\u00b0 da Carteira</div></div>
  <div class="updated" id="updated-at"></div>
</div>
<div class="layout">
  <nav class="sidebar" id="sidebar"></nav>
  <button class="sb-toggle" id="sb-toggle" onclick="toggleSidebar()" title="Ocultar/exibir carteira">&#9664;</button>
  <div class="main">
    <div class="period-bar">
      <span class="period-label">Per\u00edodo:</span>
      <button class="btn" onclick="setPeriod('day',this)">Dia</button>
      <button class="btn" onclick="setPeriod('week',this)">Semana</button>
      <button class="btn active" onclick="setPeriod('month',this)">M\u00eas</button>
      <button class="btn" onclick="setPeriod('quarter',this)">Trimestre</button>
      <button class="btn" onclick="setPeriod('year',this)">Ano</button>
      <div class="custom-wrap">
        <button class="btn custom-btn" id="custom-btn" onclick="toggleCustom()">&#128197; Personalizado</button>
        <div class="custom-dropdown" id="custom-dropdown">
          <div class="quick-btns">
            <button class="quick-btn" onclick="quickPick('yesterday')">Ontem</button>
            <button class="quick-btn" onclick="quickPick('last-week')">Sem. passada</button>
            <button class="quick-btn" onclick="quickPick('this-month')">Este m\u00eas</button>
            <button class="quick-btn" onclick="quickPick('last-month')">M\u00eas passado</button>
            <button class="quick-btn" onclick="quickPick('this-quarter')">Este trimestre</button>
            <button class="quick-btn" onclick="quickPick('this-year')">Este ano</button>
          </div>
          <label>De</label><input type="date" id="custom-start">
          <label>At\u00e9</label><input type="date" id="custom-end">
          <button class="apply-btn" onclick="applyCustom()">Aplicar</button>
        </div>
      </div>
    </div>
    <div class="main-tabs">
      <div class="tab active" onclick="setTab('geral',this)">Geral</div>
      <div class="tab" onclick="setTab('logistica',this)">Fulfillment &amp; Log\u00edstica</div>
      <div class="tab" onclick="setTab('ads',this)">ADS</div>
      <div class="tab" onclick="setTab('investimentos',this)">Investimentos</div>
      <div class="tab" onclick="setTab('catalogo',this)">Cat\u00e1logo</div>
      <div class="tab" onclick="setTab('visitas',this)">Visitas &amp; Convers\u00e3o</div>
      <div class="tab" onclick="setTab('campanhas',this)">Campanhas</div>
      <div class="tab" onclick="setTab('bpc',this)">BPC</div>
      <div class="tab" onclick="setTab('aurora',this)">Plano Aurora</div>
    </div>
    <div class="main-content">
      <div class="tab-content active" id="tab-geral">
        <div id="period-badge-geral" class="period-badge"></div>
        <div class="section-title">Scorecard por Seller</div>
        <div class="scorecard-grid" id="scorecard-sellers"></div>
        <div class="kpi-grid" id="kpi-geral"></div>
        <div class="chart-grid">
          <div class="chart-card"><div class="chart-title">GMV (R$)</div><div class="chart-wrap"><canvas id="ch-gmv-mes"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">Varia\u00e7\u00e3o GMV \u2014 MoM vs YoY (%)</div><div class="chart-wrap"><canvas id="ch-gmv-delta"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">Unidades Vendidas (SI)</div><div class="chart-wrap"><canvas id="ch-si-mes"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">ASP M\u00e9dio (R$)</div><div class="chart-wrap"><canvas id="ch-asp-mes"></canvas></div></div>
        </div>
        <div class="section-title">Resumo por Seller</div>
        <div class="table-wrap"><table id="tbl-geral-sellers"></table></div>
      </div>
      <div class="tab-content" id="tab-logistica">
        <div id="period-badge-log" class="period-badge"></div>
        <div class="kpi-grid" id="kpi-log"></div>
        <div class="chart-grid">
          <div class="chart-card"><div class="chart-title">Mix Log\u00edstico \u2014 GMV (%)</div><div class="chart-wrap"><canvas id="ch-log-mix"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">%FF por M\u00eas</div><div class="chart-wrap"><canvas id="ch-ff-mes"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">GMV por Tipo Log\u00edstico</div><div class="chart-wrap"><canvas id="ch-log-gmv"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">SI por Tipo Log\u00edstico</div><div class="chart-wrap"><canvas id="ch-log-si"></canvas></div></div>
        </div>
        <div class="section-title">Detalhe por Seller</div>
        <div class="table-wrap"><table id="tbl-log-sellers"></table></div>
      </div>
      <div class="tab-content" id="tab-ads">
        <div id="period-badge-ads" class="period-badge"></div>
        <div class="kpi-grid" id="kpi-ads"></div>
        <div class="chart-grid">
          <div class="chart-card"><div class="chart-title">Investimento ADS (R$)</div><div class="chart-wrap"><canvas id="ch-ads-invest"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">GMV via ADS (R$)</div><div class="chart-wrap"><canvas id="ch-gmv-ads"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">ROAS Mensal</div><div class="chart-wrap"><canvas id="ch-roas"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">ACOS% e ADS/GMV%</div><div class="chart-wrap"><canvas id="ch-ads-perc"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">Take Rate ADS (%)</div><div class="chart-wrap"><canvas id="ch-take-rate"></canvas></div></div>
        </div>
        <div class="section-title">Detalhe por Seller</div>
        <div class="table-wrap"><table id="tbl-ads-sellers"></table></div>
      </div>
      <div class="tab-content" id="tab-investimentos">
        <div id="period-badge-inv" class="period-badge"></div>
        <div class="kpi-grid" id="kpi-inv"></div>
        <div class="chart-grid">
          <div class="chart-card"><div class="chart-title">Investimentos Totais Mensais (R$)</div><div class="chart-wrap"><canvas id="ch-inv-total"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">Mix de Investimentos</div><div class="chart-wrap"><canvas id="ch-inv-mix"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">Cupons por M\u00eas (R$)</div><div class="chart-wrap"><canvas id="ch-cupons"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">Rebates por M\u00eas (R$)</div><div class="chart-wrap"><canvas id="ch-rebates"></canvas></div></div>
        </div>
        <div class="section-title">Detalhe por Seller</div>
        <div class="table-wrap"><table id="tbl-inv-sellers"></table></div>
      </div>
      <div class="tab-content" id="tab-catalogo">
        <div class="section-title">Top It\u00eans por Seller \u2014 \u00daltimos 3 meses</div>
        <div class="table-wrap"><table id="tbl-catalogo"></table></div>
      </div>
      <div class="tab-content" id="tab-visitas">
        <div id="period-badge-visitas" class="period-badge"></div>
        <div class="kpi-grid" id="kpi-visitas"></div>
        <div class="chart-grid">
          <div class="chart-card"><div class="chart-title">Visitas Mensais</div><div class="chart-wrap"><canvas id="ch-vis-mes"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">Conversão (%)</div><div class="chart-wrap"><canvas id="ch-conv-mes"></canvas></div></div>
        </div>
        <div class="section-title">Visitas por Seller</div>
        <div class="table-wrap"><table id="tbl-visitas-sellers"></table></div>
        <div class="section-title">Top Itêns por Visitas (90 dias)</div>
        <div class="table-wrap"><table id="tbl-visitas-items"></table></div>
      </div>
      <div class="tab-content" id="tab-campanhas">
        <div style="background:#FFF8E1;border:1px solid #F9A825;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px;color:#F57F17">
          <b>⚠️ Work in Progress</b> — Dados parciais. A query de campanhas está em ajuste para cobrir todos os sellers corretamente.
        </div>
        <div class="section-title">Resumo por Seller</div>
        <div class="table-wrap"><table id="tbl-camp-sellers"></table></div>
        <div class="section-title">Campanhas por Item (últimos 2 dias)</div>
        <div class="table-wrap"><table id="tbl-camp-items"></table></div>
      </div>
      <div class="tab-content" id="tab-bpc">
        <div class="kpi-grid" id="kpi-bpc"></div>
        <div class="section-title">BPC por Seller</div>
        <div class="table-wrap"><table id="tbl-bpc-sellers"></table></div>
        <div class="section-title">Itêns Não Competitivos (15 dias)</div>
        <div class="table-wrap"><table id="tbl-bpc-items"></table></div>
      </div>
      <div class="tab-content" id="tab-aurora">
        <div class="section-title">Classificação Aurora por Seller</div>
        <div class="table-wrap"><table id="tbl-aurora-sellers"></table></div>
        <div class="section-title">Itêns não competitivos</div>
        <div class="table-wrap"><table id="tbl-aurora-items"></table></div>
      </div>
    </div>
  </div>
</div>
<script>
const RAW = __DATA_PLACEHOLDER__;
const state = { period:'month', seller:'all', tab:'geral', customStart:null, customEnd:null };
const charts = {}, groupOpen = {};
const SELLERS = RAW.sellers;
const GROUP_COUNTS = {};
SELLERS.forEach(s => { GROUP_COUNTS[s.group] = (GROUP_COUNTS[s.group]||0)+1; });
const MULTI_GROUPS = Object.keys(GROUP_COUNTS).filter(g => GROUP_COUNTS[g] > 1);

function sellerIds(val){
  var sv=String(val);
  if(sv==='all') return SELLERS.map(s=>String(s.cust_id));
  if(MULTI_GROUPS.includes(sv)) return SELLERS.filter(s=>String(s.group)===sv).map(s=>String(s.cust_id));
  return [sv];
}
function sellerLabel(cid){
  return SELLERS.find(s=>String(s.cust_id)===String(cid))?.name||cid;
}

function buildSidebar(){
  let html='', active=String(state.seller);
  html+=`<div class="s-section-title">Geral</div>`;
  html+=`<div class="s-item ${active==='all'?'active':''}" onclick="setSeller('all')">&#9673; Toda a Carteira</div>`;
  html+=`<div class="s-section-title">Sellers</div>`;
  const done=new Set();
  const sorted=[...SELLERS].sort((a,b)=>a.name.localeCompare(b.name,'pt-BR'));
  sorted.forEach(s=>{
    if(MULTI_GROUPS.includes(s.group)){
      if(!done.has(s.group)){
        done.add(s.group);
        const ga=active===s.group, isOpen=groupOpen[s.group]!==false;
        html+=`<div class="s-group-header ${ga?'active':''}" onclick="setSeller('${s.group}')">`
             +`<span class="s-arrow ${isOpen?'open':''}" onclick="event.stopPropagation();toggleGroup('${s.group}')">&#9658;</span> ${s.group}</div>`;
        sorted.filter(x=>x.group===s.group).sort((a,b)=>a.name.localeCompare(b.name,'pt-BR')).forEach(sub=>{
          const hidden=isOpen?'':`style="display:none"`;
          html+=`<div class="s-sub ${active==String(sub.cust_id)?'active':''}" ${hidden} onclick="setSeller(${sub.cust_id})">${sub.name}</div>`;
        });
      }
    } else {
      html+=`<div class="s-item ${active==String(s.cust_id)?'active':''}" onclick="setSeller(${s.cust_id})">${s.name}</div>`;
    }
  });
  document.getElementById('sidebar').innerHTML=html;
}
function toggleGroup(g){groupOpen[g]=groupOpen[g]===false?true:false;buildSidebar();}
function toggleSidebar(){
  const sb=document.getElementById('sidebar'),btn=document.getElementById('sb-toggle');
  sb.classList.toggle('collapsed');
  btn.textContent=sb.classList.contains('collapsed')?'\u25ba':'\u25c4';
}

const fmtDate=d=>d.toISOString().slice(0,10);
const fmtMonth=(y,m)=>`${y}-${String(m+1).padStart(2,'0')}`;
const addDays=(d,n)=>{const r=new Date(d);r.setDate(r.getDate()+n);return r;};

function getPeriodConfig(){
  var now=new Date(),yr=now.getFullYear(),mo=now.getMonth(),p=state.period;
  var fD=function(d){return d.toISOString().slice(0,10);};

  if(p==='custom'&&state.customStart){
    var s=state.customStart,e=state.customEnd||state.customStart;
    var sD=new Date(s+'T00:00:00'),eD=new Date(e+'T00:00:00');
    var currM=[],cur=new Date(sD.getFullYear(),sD.getMonth(),1);
    var last=new Date(eD.getFullYear(),eD.getMonth(),1);
    while(cur<=last){currM.push(fmtMonth(cur.getFullYear(),cur.getMonth()));cur=new Date(cur.getFullYear(),cur.getMonth()+1,1);}
    if(!currM.length) currM=[fmtMonth(sD.getFullYear(),sD.getMonth())];
    var prevMoM=currM.map(function(m){var y=parseInt(m.slice(0,4)),mo2=parseInt(m.slice(5))-1;return mo2===0?fmtMonth(y-1,11):fmtMonth(y,mo2-1);});
    var prevYoY=currM.map(function(m){return fmtMonth(parseInt(m.slice(0,4))-1,parseInt(m.slice(5))-1);});
    var lbl=currM.length===1?currM[0]:(currM[0]+' a '+currM[currM.length-1]);
    return {type:'custom',gran:'monthly',curr:currM,prevMoM:prevMoM,prevYoY:prevYoY,
      label:lbl,showD1:true,showD2:true,d1Label:'MoM',d2Label:'YoY',
      chartGran:'monthly',chartMonths:currM};
  }
  if(p==='day'){
    var d1=fD(addDays(now,-1)),d2=fD(addDays(now,-2));
    var chartS=fD(addDays(now,-30));
    return {type:'day',gran:'daily',curr:[d1,d1],prev:[d2,d2],
      label:'D-1 ('+d1+')',prevLabel:'vs D-2',showD1:true,showD2:false,
      chartGran:'daily',chartStart:chartS,chartEnd:d1};
  }
  if(p==='week'){
    var dow=now.getDay(),toSat=dow===6?7:dow+1;
    var wEnd=addDays(now,-toSat),wStart=addDays(wEnd,-6);
    var pwEnd=addDays(wStart,-1),pwStart=addDays(pwEnd,-6);
    var fw=function(d){return d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'});};
    var wkS=fD(addDays(now,-28));
    return {type:'week',gran:'daily',curr:[fD(wStart),fD(wEnd)],prev:[fD(pwStart),fD(pwEnd)],
      label:'Sem. '+fw(wStart)+'-'+fw(wEnd),prevLabel:'vs Sem. ant.',showD1:true,showD2:false,
      chartGran:'daily',chartStart:wkS,chartEnd:fD(addDays(now,-1))};
  }
  if(p==='month'){
    var cm=fmtMonth(yr,mo),pm=mo===0?[yr-1,11]:[yr,mo-1];
    var mStart=cm+'-01', mEnd=fD(addDays(now,-1));
    return {type:'month',gran:'monthly',curr:[cm],prevMoM:[fmtMonth(pm[0],pm[1])],prevYoY:[fmtMonth(yr-1,mo)],
      label:cm,showD1:true,showD2:true,d1Label:'MoM',d2Label:'YoY',
      chartGran:'daily',chartStart:mStart,chartEnd:mEnd};
  }
  if(p==='quarter'){
    var q=Math.floor(mo/3),curr=[];
    for(var qi=q*3;qi<=mo;qi++) curr.push(fmtMonth(yr,qi));
    var pqY=q===0?yr-1:yr,pqQ=q===0?3:q-1;
    var pqMeses=curr.map(function(_,ii){return fmtMonth(pqY,pqQ*3+ii);});
    var pyMeses=curr.map(function(m){return fmtMonth(yr-1,parseInt(m.slice(5))-1);});
    return {type:'quarter',gran:'monthly',curr:curr,prevQoQ:pqMeses,prevYoY:pyMeses,
      label:'Q'+(q+1)+' '+yr,showD1:true,showD2:true,d1Label:'QoQ',d2Label:'YoY',
      chartGran:'monthly',chartMonths:curr};
  }
  if(p==='year'){
    var ytd=[],py=[];
    for(var yi=0;yi<=mo;yi++){ytd.push(fmtMonth(yr,yi));py.push(fmtMonth(yr-1,yi));}
    return {type:'year',gran:'monthly',curr:ytd,prevYoY:py,
      label:yr+' YTD',showD1:false,showD2:true,d2Label:'YoY',
      chartGran:'monthly',chartMonths:ytd};
  }
}
function setBadge(id,pc){const el=document.getElementById(id);if(el)el.textContent=pc.label||'';}

function aggAllMonths(rows,fields){
  const ids=sellerIds(state.seller),out={};
  rows.filter(r=>ids.includes(String(r.cust_id))).forEach(r=>{
    if(!out[r.mes]){out[r.mes]={};fields.forEach(f=>out[r.mes][f]=0);}
    fields.forEach(f=>out[r.mes][f]+=(Number(r[f])||0));
  }); return out;
}
function aggCurrentYear(rows,fields){
  const ids=sellerIds(state.seller),yr=String(new Date().getFullYear()),out={};
  rows.filter(r=>ids.includes(String(r.cust_id))&&r.mes.startsWith(yr)).forEach(r=>{
    if(!out[r.mes]){out[r.mes]={};fields.forEach(f=>out[r.mes][f]=0);}
    fields.forEach(f=>out[r.mes][f]+=(Number(r[f])||0));
  }); return out;
}
function sumMeses(allM,meses,field){return (meses||[]).reduce((a,m)=>a+(allM[m]?.[field]||0),0);}
function sumDailyRange(start,end,field){
  const ids=sellerIds(state.seller);
  return RAW.geral_daily.filter(r=>ids.includes(String(r.cust_id))&&r.dia>=start&&r.dia<=end)
    .reduce((a,r)=>a+(Number(r[field])||0),0);
}
function aggBySeller(rows,meses,fields){
  const ids=sellerIds(state.seller),out={};
  rows.filter(r=>ids.includes(String(r.cust_id))&&(meses||[]).includes(r.mes)).forEach(r=>{
    if(!out[r.cust_id]){out[r.cust_id]={};fields.forEach(f=>out[r.cust_id][f]=0);}
    fields.forEach(f=>out[r.cust_id][f]+=(Number(r[f])||0));
  }); return out;
}

function aggDailyChart(rows,field,start,end){
  var ids=sellerIds(state.seller),agg={};
  rows.filter(function(r){return ids.includes(String(r.cust_id))&&r.dia>=start&&r.dia<=end;})
    .forEach(function(r){agg[r.dia]=(agg[r.dia]||0)+(Number(r[field])||0);});
  var labels=Object.keys(agg).sort();
  return {labels:labels,data:labels.map(function(l){return agg[l];})};
}
function aggDailyChartMulti(rows,fields,start,end){
  var ids=sellerIds(state.seller),agg={};
  rows.filter(function(r){return ids.includes(String(r.cust_id))&&r.dia>=start&&r.dia<=end;})
    .forEach(function(r){
      if(!agg[r.dia]){agg[r.dia]={};fields.forEach(function(f){agg[r.dia][f]=0;});}
      fields.forEach(function(f){agg[r.dia][f]+=(Number(r[f])||0);});
    });
  var labels=Object.keys(agg).sort();
  return {labels:labels,byField:agg};
}
function aggDailyChart(rows,field,start,end){
  var ids=sellerIds(state.seller),agg={};
  rows.filter(function(r){return ids.includes(String(r.cust_id))&&r.dia>=start&&r.dia<=end;})
    .forEach(function(r){agg[r.dia]=(agg[r.dia]||0)+(Number(r[field])||0);});
  var labels=Object.keys(agg).sort();
  return {labels:labels,data:labels.map(function(l){return agg[l];})};
}
function aggDailyChartMulti(rows,fields,start,end){
  var ids=sellerIds(state.seller),agg={};
  rows.filter(function(r){return ids.includes(String(r.cust_id))&&r.dia>=start&&r.dia<=end;})
    .forEach(function(r){
      if(!agg[r.dia]){agg[r.dia]={};fields.forEach(function(f){agg[r.dia][f]=0;});}
      fields.forEach(function(f){agg[r.dia][f]+=(Number(r[f])||0);});
    });
  var labels=Object.keys(agg).sort();
  return {labels:labels,byField:agg};
}
function computeKPI(pc,allM,field){
  let value,d1=null,d2=null;
  if(pc.gran==='daily'){
    value=sumDailyRange(pc.curr[0],pc.curr[1],field);
    if(pc.prev){const p=sumDailyRange(pc.prev[0],pc.prev[1],field);d1=p?((value-p)/p)*100:null;}
    if(pc.momM){const p=sumMeses(allM,pc.momM,field);d1=p?((value-p)/p)*100:null;}
    if(pc.yoyM){const p=sumMeses(allM,pc.yoyM,field);d2=p?((value-p)/p)*100:null;}
  } else {
    value=sumMeses(allM,pc.curr,field);
    if(pc.prevMoM){const p=sumMeses(allM,pc.prevMoM,field);d1=p?((value-p)/p)*100:null;}
    else if(pc.prevQoQ){const p=sumMeses(allM,pc.prevQoQ,field);d1=p?((value-p)/p)*100:null;}
    if(pc.prevYoY){const p=sumMeses(allM,pc.prevYoY,field);d2=p?((value-p)/p)*100:null;}
  }
  return {value,d1,d2};
}

// getChartData: returns {labels, data} for the main GMV/SI/ASP bar charts
function getChartData(pc, allM, rows, field){
  if(pc.gran==='daily'){
    // aggregate daily data by day for the date range
    const ids=sellerIds(state.seller);
    const s=pc.curr[0], e=pc.curr[1];
    const dayMap={};
    rows.filter(r=>ids.includes(String(r.cust_id))&&r.dia>=s&&r.dia<=e).forEach(r=>{
      dayMap[r.dia]=(dayMap[r.dia]||0)+(Number(r[field])||0);
    });
    const labels=Object.keys(dayMap).sort();
    return {labels, data:labels.map(l=>dayMap[l])};
  }
  if(pc.type==='month'){
    // rolling 12 months ending at current month from allM
    const allK=Object.keys(allM).sort();
    const last=allK[allK.length-1];
    const idx=allK.indexOf(last);
    const slice=allK.slice(Math.max(0,idx-11),idx+1);
    return {labels:slice, data:slice.map(m=>allM[m]?.[field]||0)};
  }
  if(pc.type==='quarter'){
    const ms=pc.curr||[];
    return {labels:ms, data:ms.map(m=>allM[m]?.[field]||0)};
  }
  if(pc.type==='year'){
    const yr=String(new Date().getFullYear());
    const ms=Object.keys(allM).filter(m=>m.startsWith(yr)).sort();
    return {labels:ms, data:ms.map(m=>allM[m]?.[field]||0)};
  }
  // custom monthly fallback
  const ms=(pc.currM||pc.curr||[]);
  return {labels:ms, data:ms.map(m=>allM[m]?.[field]||0)};
}

const fmtBRL=v=>v==null?'-':'R$\u00a0'+(+v).toLocaleString('pt-BR',{minimumFractionDigits:0,maximumFractionDigits:0});
const fmtPct=v=>(v==null||!isFinite(v))?'-':(+v).toFixed(1)+'%';
const fmtNum=v=>v==null?'-':(+v).toLocaleString('pt-BR');
const fmtDec=v=>v==null?'-':(+v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
function dHtml(pct,label){
  if(pct==null||!isFinite(pct)) return `<span class="dn0">${label}: \u2014</span>`;
  const cls=pct>=0?'dp':'dn',arr=pct>=0?'\u25b2':'\u25bc';
  return `<span class="${cls}">${label}: ${arr}${Math.abs(pct).toFixed(1)}%</span>`;
}
function kpiCard(label,value,pc,d1,d2){
  let dh='';
  if(pc.showD1&&d1!=null) dh+=dHtml(d1,pc.d1Label||pc.prevLabel||'vs ant.');
  if(pc.showD2&&d2!=null) dh+=dHtml(d2,pc.d2Label||'YoY');
  if(!dh) dh='<span class="dn0">\u2014</span>';
  return `<div class="kpi-card"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div><div class="kpi-delta">${dh}</div></div>`;
}
function makeChart(id,type,labels,datasets,opts={}){
  if(charts[id])charts[id].destroy();
  const ctx=document.getElementById(id);if(!ctx)return;
  charts[id]=new Chart(ctx,{type,data:{labels,datasets},options:{
    responsive:true,maintainAspectRatio:false,
    plugins:{legend:{display:datasets.length>1,labels:{boxWidth:12,font:{size:11}}}},
    scales:type==='doughnut'?{}:{
      x:{ticks:{font:{size:10}},grid:{display:false}},
      y:{ticks:{font:{size:10},callback:opts.yFmt||null},grid:{color:'#F0F0F0'}}
    },...(opts.extra||{})
  }});
}

function renderGeral(){
  renderScorecard();
  var pc=getPeriodConfig(),allM=aggAllMonths(RAW.geral_monthly,['gmv','si']);
  setBadge('period-badge-geral',pc);
  var gmv=computeKPI(pc,allM,'gmv'),si=computeKPI(pc,allM,'si');
  var aspVal=si.value?gmv.value/si.value:0;
  var aspD1=null,aspD2=null;
  if(pc.gran==='daily'){
    if(pc.prev){var gprev=sumDailyRange(pc.prev[0],pc.prev[1],'gmv'),siprev=sumDailyRange(pc.prev[0],pc.prev[1],'si');var ap=siprev?gprev/siprev:null;aspD1=(ap&&aspVal)?((aspVal-ap)/ap)*100:null;}
  } else {
    var ap1=pc.prevMoM?(function(){var g=sumMeses(allM,pc.prevMoM,'gmv'),s=sumMeses(allM,pc.prevMoM,'si');return s?g/s:null;})():pc.prevQoQ?(function(){var g=sumMeses(allM,pc.prevQoQ,'gmv'),s=sumMeses(allM,pc.prevQoQ,'si');return s?g/s:null;})():null;
    var ay1=pc.prevYoY?(function(){var g=sumMeses(allM,pc.prevYoY,'gmv'),s=sumMeses(allM,pc.prevYoY,'si');return s?g/s:null;})():null;
    aspD1=ap1?((aspVal-ap1)/ap1)*100:null;aspD2=ay1?((aspVal-ay1)/ay1)*100:null;
  }
  document.getElementById('kpi-geral').innerHTML=
    kpiCard('GMV',fmtBRL(gmv.value),pc,gmv.d1,gmv.d2)+
    kpiCard('SI (Unidades)',fmtNum(si.value),pc,si.d1,si.d2)+
    kpiCard('ASP',fmtBRL(aspVal),pc,aspD1,aspD2);

  // CHARTS: daily for day/week/month, monthly for quarter/year
  if(pc.chartGran==='daily'){
    var s=pc.chartStart,e=pc.chartEnd;
    var gmvC=aggDailyChart(RAW.geral_daily,'gmv',s,e);
    var siC =aggDailyChart(RAW.geral_daily,'si',s,e);
    makeChart('ch-gmv-mes','bar',gmvC.labels,[{label:'GMV',data:gmvC.data,backgroundColor:'#3483FA',borderRadius:3}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-si-mes','bar',siC.labels,[{label:'SI',data:siC.data,backgroundColor:'#00A650',borderRadius:3}]);
    var aspC=aggDailyChartMulti(RAW.geral_daily,['gmv','si'],s,e);
    makeChart('ch-asp-mes','line',aspC.labels,[{label:'ASP',data:aspC.labels.map(function(d){var g=aspC.byField[d]?.gmv||0,si=aspC.byField[d]?.si||0;return si?+(g/si).toFixed(0):null;}),borderColor:'#FF7733',backgroundColor:'#FF773322',fill:true,tension:.3,pointRadius:2}],{yFmt:v=>'R$'+v?.toLocaleString('pt-BR',{maximumFractionDigits:0})});
  } else {
    var cM=pc.chartMonths||pc.curr;
    makeChart('ch-gmv-mes','bar',cM,[{label:'GMV',data:cM.map(function(m){return allM[m]?.gmv||0;}),backgroundColor:'#3483FA',borderRadius:4}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-si-mes','bar',cM,[{label:'SI',data:cM.map(function(m){return allM[m]?.si||0;}),backgroundColor:'#00A650',borderRadius:4}]);
    makeChart('ch-asp-mes','line',cM,[{label:'ASP',data:cM.map(function(m){var g=allM[m]?.gmv||0,s=allM[m]?.si||0;return s?+(g/s).toFixed(0):null;}),borderColor:'#FF7733',backgroundColor:'#FF773322',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>'R$'+v?.toLocaleString('pt-BR',{maximumFractionDigits:0})});
  }

  // Delta MoM/YoY chart: always last 12 months monthly
  var allM2=aggAllMonths(RAW.geral_monthly,['gmv','si']),allM2k=Object.keys(allM2).sort();
  var last12=allM2k.slice(-12);
  var momArr=last12.map(function(m){var p=allM2k[allM2k.indexOf(m)-1];if(!p)return null;var l=allM2[m]?.gmv||0,pv=allM2[p]?.gmv||0;return pv?+((l-pv)/pv*100).toFixed(1):null;});
  var yoyArr=last12.map(function(m){var yy=allM2k.find(function(x){return x.slice(0,4)===String(parseInt(m.slice(0,4))-1)&&x.slice(5)===m.slice(5);});if(!yy)return null;var l=allM2[m]?.gmv||0,y=allM2[yy]?.gmv||0;return y?+((l-y)/y*100).toFixed(1):null;});
  makeChart('ch-gmv-delta','line',last12,[
    {label:'MoM%',data:momArr,borderColor:'#3483FA',backgroundColor:'#3483FA22',fill:true,tension:.3,pointRadius:2},
    {label:'YoY%',data:yoyArr,borderColor:'#E83C49',backgroundColor:'#E83C4922',fill:true,tension:.3,pointRadius:2}
  ],{yFmt:v=>v?.toFixed(1)+'%'});

  // Seller table
  var mT=pc.gran==='daily'?null:(pc.curr||[]);
  var byS=pc.gran==='daily'?(function(){
    var ids=sellerIds(state.seller),out={};
    RAW.geral_daily.filter(function(r){return ids.includes(String(r.cust_id))&&r.dia>=pc.curr[0]&&r.dia<=pc.curr[1];}).forEach(function(r){
      var k=String(r.cust_id);if(!out[k]){out[k]={gmv:0,si:0};}
      out[k].gmv+=(Number(r.gmv)||0);out[k].si+=(Number(r.si)||0);
    });return out;
  })():aggBySeller(RAW.geral_monthly,mT,['gmv','si']);
  var tG=Object.values(byS).reduce(function(a,v){return a+(v.gmv||0);},0);
  var h='<thead><tr><th>Seller</th><th>GMV</th><th>SI</th><th>ASP</th><th>Share GMV</th></tr></thead><tbody>';
  Object.entries(byS).sort(function(a,b){return b[1].gmv-a[1].gmv;}).forEach(function([cid,v]){
    var asp=v.si?v.gmv/v.si:0,share=tG?(v.gmv/tG)*100:0;
    h+='<tr><td>'+sellerLabel(cid)+'</td><td>'+fmtBRL(v.gmv)+'</td><td>'+fmtNum(v.si)+'</td><td>'+fmtBRL(asp)+'</td><td><span class="badge">'+fmtPct(share)+'</span></td></tr>';
  });
  document.getElementById('tbl-geral-sellers').innerHTML=h+'</tbody>';
}
function renderLogistica(){
  var pc=getPeriodConfig(),allM=aggAllMonths(RAW.logistica_monthly,['gmv_total','gmv_ff','si_ff','gmv_xd','si_xd','gmv_ss','si_ss']);
  setBadge('period-badge-log',pc);
  var meses=pc.gran==='daily'?(pc.currM||[]):(pc.curr||[]);
  var gmvT=sumMeses(allM,meses,'gmv_total')||1;
  var ffV=sumMeses(allM,meses,'gmv_ff'),xdV=sumMeses(allM,meses,'gmv_xd'),ssV=sumMeses(allM,meses,'gmv_ss');
  var ffP=(ffV/gmvT)*100,xdP=(xdV/gmvT)*100,ssP=(ssV/gmvT)*100;
  var ffK=computeKPI(pc,allM,'gmv_ff');
  document.getElementById('kpi-log').innerHTML=
    '<div class="kpi-card"><div class="kpi-label">%FF (GMV)</div><div class="kpi-value">'+fmtPct(ffP)+'</div><div class="kpi-delta">'+dHtml(ffK.d1,pc.d1Label||pc.prevLabel||'vs ant.')+'</div></div>'+
    '<div class="kpi-card"><div class="kpi-label">GMV FF</div><div class="kpi-value">'+fmtBRL(ffK.value)+'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">%XD (GMV)</div><div class="kpi-value">'+fmtPct(xdP)+'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">%SS (GMV)</div><div class="kpi-value">'+fmtPct(ssP)+'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>';

  // CHARTS
  var donut_data=[ffP,xdP,ssP];
  makeChart('ch-log-mix','doughnut',['Fulfillment','Cross Docking','Self Service'],
    [{data:donut_data,backgroundColor:['#3483FA','#FFE600','#00A650'],borderWidth:0}],
    {extra:{plugins:{legend:{display:true,position:'bottom'}}}});

  if(pc.chartGran==='daily'){
    var s=pc.chartStart,e=pc.chartEnd;
    var lc=aggDailyChartMulti(RAW.logistica_daily,['gmv_total','gmv_ff','gmv_xd','gmv_ss'],s,e);
    var lbl=lc.labels;
    makeChart('ch-ff-mes','line',lbl,[{label:'%FF',data:lbl.map(function(d){var t=lc.byField[d]?.gmv_total||0;return t?+((lc.byField[d]?.gmv_ff||0)/t*100).toFixed(1):null;}),borderColor:'#3483FA',backgroundColor:'#3483FA22',fill:true,tension:.3,pointRadius:2}],{yFmt:v=>v?.toFixed(1)+'%'});
    makeChart('ch-log-gmv','bar',lbl,[
      {label:'FF',data:lbl.map(function(d){return lc.byField[d]?.gmv_ff||0;}),backgroundColor:'#3483FA',borderRadius:2},
      {label:'XD',data:lbl.map(function(d){return lc.byField[d]?.gmv_xd||0;}),backgroundColor:'#FFE600',borderRadius:2},
      {label:'SS',data:lbl.map(function(d){return lc.byField[d]?.gmv_ss||0;}),backgroundColor:'#00A650',borderRadius:2}
    ],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:'#F0F0F0'}}}}});
    makeChart('ch-log-si','bar',lbl,[
      {label:'Total SI',data:lbl.map(function(d){var t=lc.byField[d]?.gmv_total||0;return t?+(lc.byField[d]?.gmv_ff/t*100||0).toFixed(1):null;}),backgroundColor:'#3483FA',borderRadius:2}
    ],{yFmt:v=>v?.toFixed(1)+'%'});
  } else {
    var cM=pc.chartMonths||pc.curr;
    makeChart('ch-ff-mes','line',cM,[{label:'%FF',data:cM.map(function(m){var d=allM[m];return d?.gmv_total?+((d.gmv_ff/d.gmv_total)*100).toFixed(1):null;}),borderColor:'#3483FA',backgroundColor:'#3483FA22',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>v?.toFixed(1)+'%'});
    makeChart('ch-log-gmv','bar',cM,[
      {label:'FF',data:cM.map(function(m){return allM[m]?.gmv_ff||0;}),backgroundColor:'#3483FA',borderRadius:3},
      {label:'XD',data:cM.map(function(m){return allM[m]?.gmv_xd||0;}),backgroundColor:'#FFE600',borderRadius:3},
      {label:'SS',data:cM.map(function(m){return allM[m]?.gmv_ss||0;}),backgroundColor:'#00A650',borderRadius:3}
    ],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:'#F0F0F0'}}}}});
    makeChart('ch-log-si','bar',cM,[
      {label:'FF SI',data:cM.map(function(m){return allM[m]?.si_ff||0;}),backgroundColor:'#3483FA',borderRadius:3},
      {label:'XD SI',data:cM.map(function(m){return allM[m]?.si_xd||0;}),backgroundColor:'#FFE600',borderRadius:3},
      {label:'SS SI',data:cM.map(function(m){return allM[m]?.si_ss||0;}),backgroundColor:'#00A650',borderRadius:3}
    ],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:'#F0F0F0'}}}}});
  }

  var bySL=aggBySeller(RAW.logistica_monthly,meses,['gmv_total','gmv_ff','gmv_xd','gmv_ss','si_total','si_ff']);
  var h='<thead><tr><th>Seller</th><th>GMV Total</th><th>GMV FF</th><th>%FF</th><th>GMV XD</th><th>%XD</th><th>GMV SS</th><th>%SS</th></tr></thead><tbody>';
  Object.entries(bySL).sort(function(a,b){return b[1].gmv_total-a[1].gmv_total;}).forEach(function([cid,v]){
    var ff=v.gmv_total?(v.gmv_ff/v.gmv_total)*100:0,xd=v.gmv_total?(v.gmv_xd/v.gmv_total)*100:0,ss=v.gmv_total?(v.gmv_ss/v.gmv_total)*100:0;
    h+='<tr><td>'+sellerLabel(cid)+'</td><td>'+fmtBRL(v.gmv_total)+'</td><td>'+fmtBRL(v.gmv_ff)+'</td><td class="'+(ff>=50?'tag-pos':'tag-neg')+'">'+fmtPct(ff)+'</td><td>'+fmtBRL(v.gmv_xd)+'</td><td>'+fmtPct(xd)+'</td><td>'+fmtBRL(v.gmv_ss)+'</td><td>'+fmtPct(ss)+'</td></tr>';
  });
  document.getElementById('tbl-log-sellers').innerHTML=h+'</tbody>';
}
function renderAds(){
  var pc=getPeriodConfig();
  setBadge('period-badge-ads',pc);
  var meses=pc.gran==='daily'?(pc.currM||[]):(pc.curr||[]);
  var allAds=aggAllMonths(RAW.ads_monthly,['ads_invest','gmv_ads','clicks']);
  var allGmv=aggAllMonths(RAW.geral_monthly,['gmv']);
  var allAdsK=Object.keys(allAds).sort();

  var invV=sumMeses(allAds,meses,'ads_invest'),gmvAdsV=sumMeses(allAds,meses,'gmv_ads'),totalGmvV=sumMeses(allGmv,meses,'gmv');
  var roas=invV?+(gmvAdsV/invV).toFixed(2):0,acos=gmvAdsV?+(invV/gmvAdsV*100).toFixed(2):0,adsgmv=totalGmvV?+(gmvAdsV/totalGmvV*100).toFixed(2):0;
  var lastM=meses[meses.length-1]||'',prevMTR=allAdsK[allAdsK.indexOf(lastM)-1];
  var takeRate=prevMTR&&allGmv[prevMTR]?.gmv?+(invV/allGmv[prevMTR].gmv*100).toFixed(2):null;

  var invK=computeKPI(pc,allAds,'ads_invest'),gmvAdsK=computeKPI(pc,allAds,'gmv_ads');
  function calcMetrics(ms){var inv=sumMeses(allAds,ms,'ads_invest'),g=sumMeses(allAds,ms,'gmv_ads'),tg=sumMeses(allGmv,ms,'gmv');var lm=ms[ms.length-1]||'',pt=allAdsK[allAdsK.indexOf(lm)-1];return{roas:inv?g/inv:0,acos:g?inv/g*100:0,adsgmv:tg?g/tg*100:0,takeRate:pt&&allGmv[pt]?.gmv?inv/allGmv[pt].gmv*100:null};}
  var momM=pc.prevMoM||pc.prevQoQ||null,yoyM=pc.prevYoY||null;
  var momMet=momM?calcMetrics(momM):null,yoyMet=yoyM?calcMetrics(yoyM):null;
  function ppCard(label,value,fmtFn,mV,yV,lowerBetter){
    var dh='';
    if(mV!=null){var d=+(value-(mV||0)).toFixed(1),good=lowerBetter?d<0:d>0;dh+='<span class="'+(good?'dp':'dn')+'">MoM: '+(d>0?'\u25b2':'\u25bc')+Math.abs(d).toFixed(1)+'pp</span> ';}
    if(yV!=null){var d2=+(value-(yV||0)).toFixed(1),good2=lowerBetter?d2<0:d2>0;dh+='<span class="'+(good2?'dp':'dn')+'">YoY: '+(d2>0?'\u25b2':'\u25bc')+Math.abs(d2).toFixed(1)+'pp</span>';}
    if(!dh)dh='<span class="dn0">\u2014</span>';
    return '<div class="kpi-card"><div class="kpi-label">'+label+'</div><div class="kpi-value">'+fmtFn(value)+'</div><div class="kpi-delta">'+dh+'</div></div>';
  }
  document.getElementById('kpi-ads').innerHTML=
    kpiCard('Investimento ADS',fmtBRL(invV),pc,invK.d1,invK.d2)+
    kpiCard('GMV via ADS',fmtBRL(gmvAdsV),pc,gmvAdsK.d1,gmvAdsK.d2)+
    ppCard('ROAS',roas,fmtDec,momMet?momMet.roas:null,yoyMet?yoyMet.roas:null,false)+
    ppCard('ACOS',acos,fmtPct,momMet?momMet.acos:null,yoyMet?yoyMet.acos:null,true)+
    ppCard('ADS/GMV%',adsgmv,fmtPct,momMet?momMet.adsgmv:null,yoyMet?yoyMet.adsgmv:null,false)+
    ppCard('Take Rate ADS',takeRate,fmtPct,momMet?momMet.takeRate:null,yoyMet?yoyMet.takeRate:null,false);

  // CHARTS: daily for day/week/month, monthly for quarter/year/custom
  if(pc.chartGran==='daily'){
    var s=pc.chartStart,e=pc.chartEnd;
    var invC=aggDailyChart(RAW.ads_daily,'ads_invest',s,e);
    var gmvC=aggDailyChart(RAW.ads_daily,'gmv_ads',s,e);
    makeChart('ch-ads-invest','bar',invC.labels,[{label:'Invest. ADS',data:invC.data,backgroundColor:'#9B59B6',borderRadius:3}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-gmv-ads','bar',gmvC.labels,[{label:'GMV via ADS',data:gmvC.data,backgroundColor:'#3483FA',borderRadius:3}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    var adsMC=aggDailyChartMulti(RAW.ads_daily,['ads_invest','gmv_ads'],s,e);
    var glC=aggDailyChartMulti(RAW.geral_daily,['gmv'],s,e);
    makeChart('ch-roas','line',adsMC.labels,[{label:'ROAS',data:adsMC.labels.map(function(d){var i=adsMC.byField[d]?.ads_invest||0,g=adsMC.byField[d]?.gmv_ads||0;return i?+(g/i).toFixed(2):null;}),borderColor:'#1ABC9C',backgroundColor:'#1ABC9C22',fill:true,tension:.3,pointRadius:2}]);
    makeChart('ch-ads-perc','line',adsMC.labels,[
      {label:'ACOS%',data:adsMC.labels.map(function(d){var i=adsMC.byField[d]?.ads_invest||0,g=adsMC.byField[d]?.gmv_ads||0;return g?+(i/g*100).toFixed(2):null;}),borderColor:'#E83C49',fill:false,tension:.3,pointRadius:2},
      {label:'ADS/GMV%',data:adsMC.labels.map(function(d){var g=adsMC.byField[d]?.gmv_ads||0,t=glC.byField[d]?.gmv||0;return t?+(g/t*100).toFixed(2):null;}),borderColor:'#FF7733',fill:false,tension:.3,pointRadius:2}
    ],{yFmt:v=>v?.toFixed(1)+'%'});
  } else {
    var cM=pc.chartMonths||pc.curr||allAdsK.slice(-6);
    makeChart('ch-ads-invest','bar',cM,[{label:'Invest. ADS',data:cM.map(function(m){return allAds[m]?.ads_invest||0;}),backgroundColor:'#9B59B6',borderRadius:4}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-gmv-ads','bar',cM,[{label:'GMV via ADS',data:cM.map(function(m){return allAds[m]?.gmv_ads||0;}),backgroundColor:'#3483FA',borderRadius:4}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-roas','line',cM,[{label:'ROAS',data:cM.map(function(m){var i=allAds[m]?.ads_invest||0,g=allAds[m]?.gmv_ads||0;return i?+(g/i).toFixed(2):null;}),borderColor:'#1ABC9C',backgroundColor:'#1ABC9C22',fill:true,tension:.3,pointRadius:3}]);
    makeChart('ch-ads-perc','line',cM,[
      {label:'ACOS%',data:cM.map(function(m){var i=allAds[m]?.ads_invest||0,g=allAds[m]?.gmv_ads||0;return g?+(i/g*100).toFixed(2):null;}),borderColor:'#E83C49',fill:false,tension:.3,pointRadius:3},
      {label:'ADS/GMV%',data:cM.map(function(m){var g=allAds[m]?.gmv_ads||0,t=allGmv[m]?.gmv||0;return t?+(g/t*100).toFixed(2):null;}),borderColor:'#FF7733',fill:false,tension:.3,pointRadius:3}
    ],{yFmt:v=>v?.toFixed(1)+'%'});
  }
  // Take Rate: always monthly (derived metric)
  makeChart('ch-take-rate','line',allAdsK,[{label:'Take Rate %',data:allAdsK.map(function(m,idx){var prev=allAdsK[idx-1];var inv=allAds[m]?.ads_invest||0,gp=allGmv[prev]?.gmv||0;return gp?+(inv/gp*100).toFixed(2):null;}),borderColor:'#3483FA',backgroundColor:'#3483FA22',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>v?.toFixed(1)+'%'});

  // Seller table
  var bySA=aggBySeller(RAW.ads_monthly,meses,['ads_invest','gmv_ads','clicks']);
  var bySG=aggBySeller(RAW.geral_monthly,meses,['gmv']);
  var bySGprev=aggBySeller(RAW.geral_monthly,prevMTR?[prevMTR]:[],['gmv']);
  var h='<thead><tr><th>Seller</th><th>Invest. ADS</th><th>GMV via ADS</th><th>Clicks</th><th>ROAS</th><th>ACOS</th><th>Take Rate</th><th>ADS/GMV%</th></tr></thead><tbody>';
  Object.entries(bySA).sort(function(a,b){return b[1].ads_invest-a[1].ads_invest;}).forEach(function([cid,v]){
    var g=v.gmv_ads||0,inv=v.ads_invest||0,tg=bySG[cid]?.gmv||0,pg=bySGprev[cid]?.gmv||0;
    var r=inv?+(g/inv).toFixed(2):0,ac=g?+(inv/g*100).toFixed(1):0,ag=tg?+(g/tg*100).toFixed(1):0,tr=pg?+(inv/pg*100).toFixed(1):null;
    h+='<tr><td>'+sellerLabel(cid)+'</td><td>'+fmtBRL(inv)+'</td><td>'+fmtBRL(g)+'</td><td>'+fmtNum(v.clicks)+'</td><td>'+fmtDec(r)+'</td><td>'+fmtPct(ac)+'</td><td>'+fmtPct(tr)+'</td><td>'+fmtPct(ag)+'</td></tr>';
  });
  document.getElementById('tbl-ads-sellers').innerHTML=h+'</tbody>';
}
function renderInvestimentos(){
  var pc=getPeriodConfig();
  var INV_FIELDS=['g1_pre_acordo','g1_dod','g1_relampago','g2_price_matching','g2_smart','g2_automaticas','g3_cupons_ml'];
  var allM=aggAllMonths(RAW.investimentos_monthly,INV_FIELDS);
  setBadge('period-badge-inv',pc);
  var meses=pc.gran==='daily'?(pc.currM||[]):(pc.curr||[]);
  var g1=sumMeses(allM,meses,'g1_pre_acordo')+sumMeses(allM,meses,'g1_dod')+sumMeses(allM,meses,'g1_relampago');
  var g2=sumMeses(allM,meses,'g2_price_matching')+sumMeses(allM,meses,'g2_smart')+sumMeses(allM,meses,'g2_automaticas');
  var g3=sumMeses(allM,meses,'g3_cupons_ml');
  var invTotal=g1+g2+g3;
  document.getElementById('kpi-inv').innerHTML=
    '<div class="kpi-card"><div class="kpi-label">Total Investido</div><div class="kpi-value">'+ fmtBRL(invTotal) +'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">Comercial</div><div class="kpi-value">'+ fmtBRL(g1) +'</div><div class="kpi-delta"><span class="dn0">Pr\u00e9 Acordo + DoD + Rel\u00e2mpago</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">G2 Central Promo\u00e7\u00f5es</div><div class="kpi-value">'+ fmtBRL(g2) +'</div><div class="kpi-delta"><span class="dn0">PM + Smart + Autom\u00e1ticas</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">Cupons ML</div><div class="kpi-value">'+ fmtBRL(g3) +'</div><div class="kpi-delta"><span class="dn0">Investimento via Cupons</span></div></div>';
  var cyI=aggCurrentYear(RAW.investimentos_monthly,INV_FIELDS),cym=Object.keys(cyI).sort();
  var cM=pc.chartMonths||pc.curr;
  if(pc.chartGran==='daily'){
    var s=pc.chartStart,e=pc.chartEnd;
    var totC=aggDailyChart(RAW.investimentos_daily,'total_invest',s,e);
    var invMC=aggDailyChartMulti(RAW.investimentos_daily,['cupons','rebate_pre','rebate_outras'],s,e);
    makeChart('ch-inv-total','bar',totC.labels,[
      {label:'Cupons',data:totC.labels.map(function(d){return invMC.byField[d]?.g3_cupons_ml||0;}),backgroundColor:'#FFE600',borderRadius:2},
      {label:'Rebate Pr\u00e9',data:totC.labels.map(function(d){return (invMC.byField[d]?.g1_pre_acordo||0)+(invMC.byField[d]?.g1_dod||0)+(invMC.byField[d]?.g1_relampago||0);}),backgroundColor:'#3483FA',borderRadius:2},
      {label:'Rebate Outras',data:totC.labels.map(function(d){return (invMC.byField[d]?.g2_price_matching||0)+(invMC.byField[d]?.g2_smart||0)+(invMC.byField[d]?.g2_automaticas||0);}),backgroundColor:'#00A650',borderRadius:2}
    ],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:'#F0F0F0'}}}}});
    makeChart('ch-cupons','line',totC.labels,[{label:'Cupons',data:totC.labels.map(function(d){return invMC.byField[d]?.g3_cupons_ml||0;}),borderColor:'#E67E22',backgroundColor:'#E67E2222',fill:true,tension:.3,pointRadius:2}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-rebates','line',totC.labels,[
      {label:'Pr\u00e9-neg.',data:totC.labels.map(function(d){return (invMC.byField[d]?.g1_pre_acordo||0)+(invMC.byField[d]?.g1_dod||0)+(invMC.byField[d]?.g1_relampago||0);}),borderColor:'#3483FA',fill:false,tension:.3,pointRadius:2},
      {label:'Outras',data:totC.labels.map(function(d){return (invMC.byField[d]?.g2_price_matching||0)+(invMC.byField[d]?.g2_smart||0)+(invMC.byField[d]?.g2_automaticas||0);}),borderColor:'#00A650',fill:false,tension:.3,pointRadius:2}
    ],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
  } else {
    var cM=pc.chartMonths||pc.curr;
    makeChart('ch-inv-total','bar',cM,[
      {label:'Cupons',data:cM.map(function(m){return allM[m]?.cupons||0;}),backgroundColor:'#FFE600',borderRadius:3},
      {label:'Rebate Pr\u00e9',data:cM.map(function(m){return allM[m]?.rebate_pre||0;}),backgroundColor:'#3483FA',borderRadius:3},
      {label:'Rebate Outras',data:cM.map(function(m){return allM[m]?.rebate_outras||0;}),backgroundColor:'#00A650',borderRadius:3}
    ],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:'#F0F0F0'}}}}});
    makeChart('ch-cupons','line',cM,[{label:'Cupons',data:cM.map(function(m){return allM[m]?.cupons||0;}),borderColor:'#E67E22',backgroundColor:'#E67E2222',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-rebates','line',cM,[
      {label:'Pr\u00e9-neg.',data:cM.map(function(m){return allM[m]?.rebate_pre||0;}),borderColor:'#3483FA',fill:false,tension:.3,pointRadius:3},
      {label:'Outras',data:cM.map(function(m){return allM[m]?.rebate_outras||0;}),borderColor:'#00A650',fill:false,tension:.3,pointRadius:3}
    ],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
  }
  // Mix donut: always current period
  makeChart('ch-inv-mix','doughnut',['Cupons','Rebate Pr\u00e9-neg.','Rebate Outras'],
    [{data:[g3,g1,g2],backgroundColor:['#FFE600','#3483FA','#00A650'],borderWidth:0}],
    {extra:{plugins:{legend:{display:true,position:'bottom'}}}});

  var bySI=aggBySeller(RAW.investimentos_monthly,meses,['gmv','g1_pre_acordo','g1_dod','g1_relampago','g2_price_matching','g2_smart','g2_automaticas','g3_cupons_ml']);
  var h='<thead><tr><th>Seller</th><th>GMV</th><th>Cupons</th><th>Rebate Pr\u00e9</th><th>Rebate Outras</th><th>Total Invest.</th><th>Invest/GMV%</th></tr></thead><tbody>';
  Object.entries(bySI).sort(function(a,b){return b[1].total_invest-a[1].total_invest;}).forEach(function([cid,v]){
    var tot2=(v.g1_pre_acordo||0)+(v.g1_dod||0)+(v.g1_relampago||0)+(v.g2_price_matching||0)+(v.g2_smart||0)+(v.g2_automaticas||0)+(v.g3_cupons_ml||0);var p2=v.gmv?(tot2/v.gmv)*100:0;
    h+='<tr><td>'+sellerLabel(cid)+'</td><td>'+fmtBRL(v.gmv)+'</td><td>'+fmtBRL(v.cupons)+'</td><td>'+fmtBRL(v.rebate_pre)+'</td><td>'+fmtBRL(v.rebate_outras)+'</td><td><b>'+fmtBRL(v.total_invest)+'</b></td><td>'+fmtPct(p2)+'</td></tr>';
  });
  document.getElementById('tbl-inv-sellers').innerHTML=h+'</tbody>';
}
function renderCatalogo(){
  const ids=sellerIds(state.seller),rows=RAW.catalogo_items.filter(r=>ids.includes(String(r.cust_id)));
  const tG=rows.reduce((a,r)=>a+(Number(r.gmv)||0),0);
  let h=`<thead><tr><th>Seller</th><th>Item ID</th><th>T\u00edtulo</th><th>GMV</th><th>SI</th><th>ASP</th><th>Share %</th><th>GMV BB</th><th>BB%</th><th>Link</th></tr></thead><tbody>`;
  rows.forEach(r=>{
    const share=tG?(Number(r.gmv)/tG)*100:0,bbPct=Number(r.gmv)?(Number(r.gmv_bb)/Number(r.gmv))*100:0;
    const mlLink=`https://produto.mercadolivre.com.br/MLB-${r.item_id}`;
    h+=`<tr><td>${sellerLabel(r.cust_id)}</td><td>${r.item_id}</td><td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.titulo||''}</td><td>${fmtBRL(r.gmv)}</td><td>${fmtNum(r.si)}</td><td>${fmtBRL(r.asp)}</td><td><span class="badge">${fmtPct(share)}</span></td><td>${fmtBRL(r.gmv_bb)}</td><td class="${bbPct>=50?'tag-pos':'tag-neg'}">${fmtPct(bbPct)}</td><td><a href="${mlLink}" target="_blank" style="color:var(--ml-blue2);text-decoration:none">Ver</a></td></tr>`;
  });
  document.getElementById('tbl-catalogo').innerHTML=h+'</tbody>';
}


function renderScorecard(){
  var el=document.getElementById('scorecard-sellers');
  if(state.seller!=='all'){if(el)el.innerHTML='';return;}
  var now=new Date(),yr=now.getFullYear(),mo=now.getMonth();
  var meses=[fmtMonth(yr,mo)];
  var prevMoScM=mo===0?[fmtMonth(yr-1,11)]:[fmtMonth(yr,mo-1)];
  var prevYoScM=[fmtMonth(yr-1,mo)];
  var rep={};
  (RAW.seller_reputation||[]).forEach(function(r){rep[String(r.cust_id)]=r;});
  var now=new Date(),fD=function(d){return d.toISOString().slice(0,10);};
  var w1e=fD(addDays(now,-1)),w1s=fD(addDays(now,-7));
  var w2e=fD(addDays(now,-8)),w2s=fD(addDays(now,-14));
  function repClass(lv){
    if(!lv) return 'rep-green';
    if(lv.includes('platinum')) return 'rep-platinum';
    if(lv.includes('gold')) return 'rep-gold';
    if(lv==='green') return 'rep-green';
    if(lv==='yellow') return 'rep-yellow';
    if(lv==='orange') return 'rep-orange';
    return 'rep-red';
  }
  function repLabel(lv){
    var m={'green_platinum':'Platinum','green_gold':'Gold','green':'Verde','yellow':'Amarelo','orange':'Laranja','red':'Vermelho'};
    return m[lv]||lv||'-';
  }
  function sumDailySeller(cid,start,end,field){
    return (RAW.geral_daily||[]).filter(function(r){return String(r.cust_id)===cid&&r.dia>=start&&r.dia<=end;})
      .reduce(function(a,r){return a+(Number(r[field])||0);},0);
  }
  var sorted=[...RAW.sellers].sort(function(a,b){return a.name.localeCompare(b.name,'pt-BR');});
  var html='';
  sorted.forEach(function(s){
    var cid=String(s.cust_id);
    var sRows=RAW.geral_monthly.filter(function(r){return String(r.cust_id)===cid;});
    var sAllM=aggAllMonths(sRows,['gmv','si']);
    var gmvCurr=sumMeses(sAllM,meses,'gmv');
    var siCurr=sumMeses(sAllM,meses,'si');
    var asp=siCurr?gmvCurr/siCurr:0;
    var gmvPrev=sumMeses(sAllM,prevMoScM,'gmv');
    var gmvYoy =sumMeses(sAllM,prevYoScM,'gmv');
    var gmvWow1=sumDailySeller(cid,w1s,w1e,'gmv');
    var gmvWow2=sumDailySeller(cid,w2s,w2e,'gmv');
    var momPct=gmvPrev?((gmvCurr-gmvPrev)/gmvPrev*100):null;
    var yoyPct=gmvYoy?((gmvCurr-gmvYoy)/gmvYoy*100):null;
    var wowPct=gmvWow2?((gmvWow1-gmvWow2)/gmvWow2*100):null;
    var r=rep[cid]||{};
    function delta(pct,lbl){
      if(pct==null||!isFinite(pct)) return '';
      var cls=pct>=0?'dp':'dn',arr=pct>=0?'\u25b2':'\u25bc';
      return '<span class="'+cls+'">'+lbl+': '+arr+Math.abs(pct).toFixed(1)+'%</span>';
    }
    html+='<div class="sc-card">'
      +'<div class="sc-card-header">'
      +'<div class="sc-seller-name">'+s.name+'</div>'
      +'<span class="rep-badge '+repClass(r.REP_CURRENT_LEVEL)+'">'+repLabel(r.REP_CURRENT_LEVEL)+'</span>'
      +'</div>'
      +'<div class="sc-gmv">'+fmtBRL(gmvCurr)+'</div>'
      +'<div class="sc-deltas">'+delta(wowPct,'WoW')+delta(momPct,'MoM')+delta(yoyPct,'YoY')+'</div>'
      +'<div class="sc-asp">ASP: '+fmtBRL(asp)+'</div>'
      +(r.claims_pct!=null?'<div class="sc-metrics">'
        +'<div class="sc-metric"><div class="sc-metric-val">'+fmtPct(r.claims_pct)+'</div><div class="sc-metric-lbl">Reclam.</div></div>'
        +'<div class="sc-metric"><div class="sc-metric-val">'+fmtPct(r.delay_pct)+'</div><div class="sc-metric-lbl">Atraso</div></div>'
        +'<div class="sc-metric"><div class="sc-metric-val">'+fmtPct(r.cancel_pct)+'</div><div class="sc-metric-lbl">Cancel.</div></div>'
        +'</div>':'')
      +'</div>';
  });
  var el=document.getElementById('scorecard-sellers');
  if(el) el.innerHTML=html;
}

function renderVisitas(){
  var pc=getPeriodConfig();
  setBadge('period-badge-visitas',pc);
  var meses=pc.gran==='daily'?(pc.currM||[]):(pc.curr||[]);
  var allVis=aggAllMonths(RAW.visitas_monthly,['visits','visits_vip']);
  var allGmv=aggAllMonths(RAW.geral_monthly,['gmv','si']);
  var ids=sellerIds(state.seller);
  var totVis=sumMeses(allVis,meses,'visits');
  var totSI=sumMeses(allGmv,meses,'si');
  var convPct=totVis?+(totSI/totVis*100).toFixed(2):0;
  var visK=computeKPI(pc,allVis,'visits');
  document.getElementById('kpi-visitas').innerHTML=
    kpiCard('Total Visitas',fmtNum(totVis),pc,visK.d1,visK.d2)+
    '<div class="kpi-card"><div class="kpi-label">Convers\u00e3o</div><div class="kpi-value">'+fmtPct(convPct)+'</div><div class="kpi-delta"><span class="dn0">Pedidos / Visitas</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">Pedidos (SI)</div><div class="kpi-value">'+fmtNum(totSI)+'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>';
  var cM=pc.chartMonths||pc.curr;
  makeChart('ch-vis-mes','bar',cM,[{label:'Visitas',data:cM.map(function(m){return allVis[m]?.visits||0;}),backgroundColor:'#3483FA',borderRadius:4}]);
  makeChart('ch-conv-mes','line',cM,[{label:'Convers\u00e3o%',data:cM.map(function(m){var v=allVis[m]?.visits||0,s=allGmv[m]?.si||0;return v?+(s/v*100).toFixed(2):null;}),borderColor:'#00A650',backgroundColor:'#00A65022',fill:true,tension:.3,pointRadius:3}],{yFmt:function(v){return v?.toFixed(1)+'%';}});
  var bySV=aggBySeller(RAW.visitas_monthly,meses,['visits','visits_vip']);
  var bySG=aggBySeller(RAW.geral_monthly,meses,['si']);
  var h='<thead><tr><th>Seller</th><th>Visitas</th><th>Visitas VIP</th><th>Pedidos (SI)</th><th>Convers\u00e3o</th></tr></thead><tbody>';
  Object.entries(bySV).sort(function(a,b){return b[1].visits-a[1].visits;}).forEach(function([cid,v]){
    var si=bySG[cid]?.si||0,cv=v.visits?+(si/v.visits*100).toFixed(1):0;
    h+='<tr><td>'+sellerLabel(cid)+'</td><td>'+fmtNum(v.visits)+'</td><td>'+fmtNum(v.visits_vip)+'</td><td>'+fmtNum(si)+'</td><td>'+fmtPct(cv)+'</td></tr>';
  });
  document.getElementById('tbl-visitas-sellers').innerHTML=h+'</tbody>';
  var itemMap={};
  (RAW.visitas_items||[]).filter(function(r){return ids.includes(String(r.cust_id));}).forEach(function(r){itemMap[r.item_id]={cust_id:r.cust_id,visits:r.visits};});
  var siMap={};
  (RAW.catalogo_items||[]).filter(function(r){return ids.includes(String(r.cust_id));}).forEach(function(r){siMap[r.item_id]={titulo:r.titulo,si:r.si};});
  var iRows=Object.entries(itemMap).sort(function(a,b){return b[1].visits-a[1].visits;}).slice(0,50);
  var h2='<thead><tr><th>Seller</th><th>Item ID</th><th>T\u00edtulo</th><th>Visitas</th><th>Pedidos (SI)</th><th>Convers\u00e3o</th></tr></thead><tbody>';
  iRows.forEach(function([iid,v]){
    var info=siMap[iid]||{titulo:'',si:0};
    var cv=v.visits?+(info.si/v.visits*100).toFixed(1):0;
    h2+='<tr><td>'+sellerLabel(v.cust_id)+'</td><td>'+iid+'</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+info.titulo+'</td><td>'+fmtNum(v.visits)+'</td><td>'+fmtNum(info.si)+'</td><td>'+fmtPct(cv)+'</td></tr>';
  });
  document.getElementById('tbl-visitas-items').innerHTML=h2+'</tbody>';
}

function renderCampanhas(){
  var ids=sellerIds(state.seller);
  var rows=(RAW.campanhas||[]).filter(function(r){return ids.includes(String(r.cust_id));});
  var TYPE_LABELS={TIER_1:'Tier 1',TIER_3:'Tier 3',SMART:'Smart',CUSTOM:'On Demand',PRENEGOTIATED:'Pr\u00e9 Neg.',LIGHTNING:'Rel\u00e2mpago',BANK:'Banco',UNHEALTHY_STOCK:'Unhealthy'};
  var summ={};
  rows.forEach(function(r){var k=String(r.cust_id);if(!summ[k]){summ[k]={eligible:0,optin:0,total:0};}summ[k].total++;if(r.elegivel)summ[k].eligible++;if(r.opt_in)summ[k].optin++;});
  var hs='<thead><tr><th>Seller</th><th>Total Itens</th><th>Eleg\u00edveis</th><th>Opt-In</th><th>% Opt-In/Eleg.</th></tr></thead><tbody>';
  Object.entries(summ).sort(function(a,b){return b[1].eligible-a[1].eligible;}).forEach(function([cid,v]){
    var pct=v.eligible?+(v.optin/v.eligible*100).toFixed(1):0;
    hs+='<tr><td>'+sellerLabel(cid)+'</td><td>'+fmtNum(v.total)+'</td><td>'+fmtNum(v.eligible)+'</td><td>'+fmtNum(v.optin)+'</td><td><span class="badge">'+fmtPct(pct)+'</span></td></tr>';
  });
  document.getElementById('tbl-camp-sellers').innerHTML=hs+'</tbody>';
  var hi='<thead><tr><th>Seller</th><th>Tipo</th><th>Item ID</th><th>Eleg\u00edvel</th><th>Opt-In</th><th>Pre\u00e7o Inicial</th><th>Pre\u00e7o Final</th><th>Desc.%</th><th>GMV L30D</th></tr></thead><tbody>';
  rows.sort(function(a,b){return (b.gmv_l30d||0)-(a.gmv_l30d||0);}).slice(0,500).forEach(function(r){
    var desc=r.preco_inicial&&r.preco_final&&r.preco_inicial>0?+((1-r.preco_final/r.preco_inicial)*100).toFixed(1):null;
    hi+='<tr><td>'+sellerLabel(r.cust_id)+'</td><td><span class="badge">'+(TYPE_LABELS[r.tipo]||r.tipo)+'</span></td><td>'+r.item_id+'</td><td class="'+(r.elegivel?'tag-pos':'tag-neg')+'">'+(r.elegivel?'Sim':'N\u00e3o')+'</td><td class="'+(r.opt_in?'tag-pos':'dn0')+'">'+(r.opt_in?'Sim':'-')+'</td><td>'+fmtBRL(r.preco_inicial)+'</td><td>'+fmtBRL(r.preco_final)+'</td><td>'+(desc!=null?fmtPct(desc):'-')+'</td><td>'+fmtBRL(r.gmv_l30d)+'</td></tr>';
  });
  document.getElementById('tbl-camp-items').innerHTML=hi+'</tbody>';
}

function renderBPC(){
  var ids=sellerIds(state.seller);
  var rows=(RAW.bpc_aurora||[]).filter(function(r){return ids.includes(String(r.SELLER_ID));});
  var summ={};
  rows.forEach(function(r){var k=String(r.SELLER_ID);if(!summ[k]){summ[k]={vis:0,visExp:0,items:0,nonComp:0};}summ[k].vis+=(Number(r.VISITS_MATCH)||0);summ[k].visExp+=(Number(r.VISITS_EXP3)||0);summ[k].items++;if(r.CLASSIFICACAO==='Nao Competitivo')summ[k].nonComp++;});
  var totVis=Object.values(summ).reduce(function(a,v){return a+v.vis;},0);
  var totExp=Object.values(summ).reduce(function(a,v){return a+v.visExp;},0);
  var bpcRate=totVis?+(totExp/totVis*100).toFixed(1):0;
  document.getElementById('kpi-bpc').innerHTML=
    '<div class="kpi-card"><div class="kpi-label">Eventos de Comparação (15d)</div><div class="kpi-value">'+fmtNum(Math.round(totVis))+'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">Eventos: Preço Meli 3%+ acima</div><div class="kpi-value">'+fmtNum(Math.round(totExp))+'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">% Eventos Caros</div><div class="kpi-value">'+fmtPct(bpcRate)+'</div><div class="kpi-delta"><span class="dn0">Pior = mais alto</span></div></div>';
  var hs='<thead><tr><th>Seller</th><th>It\u00eans</th><th>N\u00e3o Comp.</th><th>Visitas Totais</th><th>Visitas Caras</th><th>% Caras</th></tr></thead><tbody>';
  Object.entries(summ).sort(function(a,b){return b[1].visExp-a[1].visExp;}).forEach(function([cid,v]){
    var pct=v.vis?+(v.visExp/v.vis*100).toFixed(1):0;
    hs+='<tr><td>'+sellerLabel(cid)+'</td><td>'+fmtNum(v.items)+'</td><td class="'+(v.nonComp>0?'tag-neg':'tag-pos')+'">'+fmtNum(v.nonComp)+'</td><td>'+fmtNum(Math.round(v.vis))+'</td><td>'+fmtNum(Math.round(v.visExp))+'</td><td class="'+(pct>30?'tag-neg':pct>10?'dp':'tag-pos')+'">'+fmtPct(pct)+'</td></tr>';
  });
  document.getElementById('tbl-bpc-sellers').innerHTML=hs+'</tbody>';
  var hi='<thead><tr><th>Seller</th><th>Item ID</th><th>T\u00edtulo</th><th>Pre\u00e7o Meli</th><th>Pre\u00e7o Rival</th><th>Gap</th><th>Rival</th><th>Visitas</th><th>Vis. Caras</th><th>Link ML</th><th>Link Rival</th></tr></thead><tbody>';
  rows.filter(function(r){return r.CLASSIFICACAO==='Nao Competitivo';}).sort(function(a,b){return (Number(b.VISITS_EXP3)||0)-(Number(a.VISITS_EXP3)||0);}).slice(0,200).forEach(function(r){
    var gap=r.PRICE_MELI&&r.COMP_PRICE_RIVAL_MIN?+((r.PRICE_MELI/r.COMP_PRICE_RIVAL_MIN-1)*100).toFixed(1):null;
    var mlLnk=r.PERMALINK?('<a href="'+r.PERMALINK+'" target="_blank" style="color:var(--ml-blue2)">ML</a>'):'-';
    var riLnk=r.COMP_URL?('<a href="'+r.COMP_URL+'" target="_blank" style="color:var(--red)">Rival</a>'):'-';
    hi+='<tr><td>'+sellerLabel(r.SELLER_ID)+'</td><td>'+r.ITE_ITEM_ID+'</td><td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(r.TITLE||'')+'</td><td>'+fmtBRL(r.PRICE_MELI)+'</td><td>'+fmtBRL(r.COMP_PRICE_RIVAL_MIN)+'</td><td class="tag-neg">'+(gap!=null?'+'+gap.toFixed(1)+'%':'-')+'</td><td>'+(r.COMP_RIVAL_NAME||'-')+'</td><td>'+fmtNum(Math.round(Number(r.VISITS_MATCH)||0))+'</td><td>'+fmtNum(Math.round(Number(r.VISITS_EXP3)||0))+'</td><td>'+mlLnk+'</td><td>'+riLnk+'</td></tr>';
  });
  document.getElementById('tbl-bpc-items').innerHTML=hi+'</tbody>';
}

function renderAurora(){
  var ids=sellerIds(state.seller);
  var rows=(RAW.bpc_aurora||[]).filter(function(r){return ids.includes(String(r.SELLER_ID));});
  var sellerQual={};
  rows.forEach(function(r){if(r.SELLER_QUALIFICATION&&!sellerQual[r.SELLER_ID])sellerQual[r.SELLER_ID]=r.SELLER_QUALIFICATION;});
  var QUAL_ORDER={C1:1,C2:2,C3:3,C4:4,RC:5};
  var QUAL_LABEL={C1:'C1 - Saud\u00e1vel',C2:'C2 - Alerta Pre\u00e7.',C3:'C3 - Cr\u00f4nico',C4:'C4 - Quarentena',RC:'RC - Recupera\u00e7\u00e3o'};
  var QUAL_CLASS={C1:'tag-pos',C2:'dp',C3:'tag-neg',C4:'tag-neg',RC:'dn0'};
  var ELIGIBLE={C1:true,C2:true,C3:false,C4:true,RC:true};
  var hs='<thead><tr><th>Seller</th><th>Classifica\u00e7\u00e3o</th><th>Eleg\u00edvel Benef.</th><th>It\u00eans N\u00e3o Comp.</th></tr></thead><tbody>';
  Object.entries(sellerQual).sort(function(a,b){return (QUAL_ORDER[a[1]]||9)-(QUAL_ORDER[b[1]]||9);}).forEach(function([cid,q]){
    var nonComp=rows.filter(function(r){return String(r.SELLER_ID)===cid&&r.CLASSIFICACAO==='Nao Competitivo';}).length;
    var elig=ELIGIBLE[q]!==undefined?ELIGIBLE[q]:true;
    hs+='<tr><td>'+sellerLabel(cid)+'</td><td class="'+(QUAL_CLASS[q]||'dn0')+'">'+(QUAL_LABEL[q]||q)+'</td><td class="'+(elig?'tag-pos':'tag-neg')+'">'+(elig?'Sim':'N\u00e3o (C3)')+'</td><td>'+fmtNum(nonComp)+'</td></tr>';
  });
  document.getElementById('tbl-aurora-sellers').innerHTML=hs+'</tbody>';
  var hi='<thead><tr><th>Seller</th><th>Item ID</th><th>T\u00edtulo</th><th>Pre\u00e7o Meli</th><th>Pre\u00e7o Rival</th><th>Gap</th><th>Rival</th><th>Status</th><th>Link ML</th><th>Link Rival</th></tr></thead><tbody>';
  rows.filter(function(r){return r.CLASSIFICACAO==='Nao Competitivo';}).sort(function(a,b){return (Number(b.VISITS_EXP3)||0)-(Number(a.VISITS_EXP3)||0);}).slice(0,300).forEach(function(r){
    var gap=r.PRICE_MELI&&r.COMP_PRICE_RIVAL_MIN?+((r.PRICE_MELI/r.COMP_PRICE_RIVAL_MIN-1)*100).toFixed(1):null;
    var mlLnk=r.PERMALINK?('<a href="'+r.PERMALINK+'" target="_blank" style="color:var(--ml-blue2)">ML</a>'):'-';
    var riLnk=r.COMP_URL?('<a href="'+r.COMP_URL+'" target="_blank" style="color:var(--red)">Rival</a>'):'-';
    hi+='<tr><td>'+sellerLabel(r.SELLER_ID)+'</td><td>'+r.ITE_ITEM_ID+'</td><td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(r.TITLE||'')+'</td><td>'+fmtBRL(r.PRICE_MELI)+'</td><td>'+fmtBRL(r.COMP_PRICE_RIVAL_MIN)+'</td><td class="tag-neg">'+(gap!=null?'+'+gap.toFixed(1)+'%':'-')+'</td><td>'+(r.COMP_RIVAL_NAME||'-')+'</td><td class="tag-neg">N\u00e3o Comp.</td><td>'+mlLnk+'</td><td>'+riLnk+'</td></tr>';
  });
  document.getElementById('tbl-aurora-items').innerHTML=hi+'</tbody>';
}
function setPeriod(p,btn){
  state.period=p;
  document.querySelectorAll('.period-bar .btn:not(.custom-btn)').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active');
  document.getElementById('custom-btn').classList.remove('active');
  document.getElementById('custom-dropdown').classList.remove('open');
  renderAll();
}
function setSeller(val){
  var sv=String(val);
  if(sv==='all') state.seller='all';
  else if(MULTI_GROUPS.includes(sv)) state.seller=sv;
  else state.seller=Number(val);
  buildSidebar();renderAll();
}
function setTab(tab,el){
  state.tab=tab;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  if(el)el.classList.add('active');
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  document.getElementById('tab-'+tab).classList.add('active');
  renderAll();
}
function toggleCustom(){document.getElementById('custom-dropdown').classList.toggle('open');}
function applyCustom(){
  const s=document.getElementById('custom-start').value,e=document.getElementById('custom-end').value;
  if(!s)return;
  state.period='custom';state.customStart=s;state.customEnd=e||s;
  document.querySelectorAll('.period-bar .btn:not(.custom-btn)').forEach(b=>b.classList.remove('active'));
  document.getElementById('custom-btn').classList.add('active');
  document.getElementById('custom-dropdown').classList.remove('open');
  renderAll();
}
function quickPick(key){
  const now=new Date(),fD=d=>d.toISOString().slice(0,10),dow=now.getDay();let s,e;
  if(key==='yesterday'){const d=addDays(now,-1);s=e=fD(d);}
  else if(key==='last-week'){const toSat=dow===6?7:dow+1,wEnd=addDays(now,-toSat);s=fD(addDays(wEnd,-6));e=fD(wEnd);}
  else if(key==='this-month'){s=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-01`;e=fD(now);}
  else if(key==='last-month'){const pm=now.getMonth()===0?new Date(now.getFullYear()-1,11,1):new Date(now.getFullYear(),now.getMonth()-1,1);s=fD(pm);e=fD(new Date(pm.getFullYear(),pm.getMonth()+1,0));}
  else if(key==='this-quarter'){const q=Math.floor(now.getMonth()/3);s=`${now.getFullYear()}-${String(q*3+1).padStart(2,'0')}-01`;e=fD(now);}
  else if(key==='this-year'){s=`${now.getFullYear()}-01-01`;e=fD(now);}
  if(s){
    document.getElementById('custom-start').value=s;
    document.getElementById('custom-end').value=e||s;
    applyCustom();
  }
}
document.addEventListener('click',e=>{
  const w=document.querySelector('.custom-wrap');
  if(w&&!w.contains(e.target))document.getElementById('custom-dropdown').classList.remove('open');
});
function renderAll(){
  if(state.tab==='geral')         renderGeral();
  if(state.tab==='logistica')     renderLogistica();
  if(state.tab==='ads')           renderAds();
  if(state.tab==='investimentos') renderInvestimentos();
  if(state.tab==='catalogo')      renderCatalogo();
  if(state.tab==='visitas')       renderVisitas();
  if(state.tab==='campanhas')     renderCampanhas();
  if(state.tab==='bpc')           renderBPC();
  if(state.tab==='aurora')        renderAurora();
}
document.getElementById('updated-at').textContent='Atualizado: '+RAW.updated_at;
buildSidebar();
renderAll();
</script>
</body>
</html>
"""


# ── Main ──────────────────────────────────────────────────────────────────────
def generate():
    dataset = build_dataset()
    data_json = json.dumps(dataset, ensure_ascii=False, default=str)
    import base64 as _b64
    logo_path = os.path.join(os.path.dirname(__file__), "ml-logo.png")
    logo_b64 = _b64.b64encode(open(logo_path, "rb").read()).decode()
    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json).replace("__LOGO__", logo_b64)
    out_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard gerado: {out_path}")
    repo_dir = os.path.dirname(__file__)
    try:
        subprocess.run(["git", "add", "index.html"], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", f"chore: atualização automática {datetime.now().strftime('%Y-%m-%d %H:%M')}"], cwd=repo_dir, check=True)
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)
        print("Push para GitHub Pages concluído.")
    except subprocess.CalledProcessError as e:
        print(f"Git push falhou: {e}")

if __name__ == "__main__":
    generate()
