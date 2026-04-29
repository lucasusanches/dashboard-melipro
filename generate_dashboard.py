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
    """Catalogo mensal por seller -- desde jan do ano passado."""
    return run(f"""
        SELECT
            FORMAT_DATE('%Y-%m', ORD_CLOSED_DT)                    AS mes,
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
          AND ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND ORD_CLOSED_DT < CURRENT_DATE()
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 4 DESC
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
.logo{height:52px;object-fit:contain;image-rendering:crisp-edges}
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
.scorecard-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin-bottom:20px}
.sc-card{background:var(--card);border-radius:10px;padding:16px;border:1px solid var(--border);box-shadow:0 2px 8px rgba(0,0,0,.08)}
.sc-card-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;gap:8px}
.sc-seller-name{font-size:12px;font-weight:700;color:var(--ml-blue);line-height:1.3}
.rep-badge{padding:3px 8px;border-radius:10px;font-size:10px;font-weight:700;white-space:nowrap;flex-shrink:0}
.rep-platinum{background:#E8F4FD;color:#1565C0}.rep-gold{background:#FFF8E1;color:#F57F17}
.rep-green{background:#E8F5E9;color:#2E7D32}.rep-yellow{background:#FFFDE7;color:#F9A825}
.rep-orange{background:#FFF3E0;color:#E65100}.rep-red{background:#FFEBEE;color:#C62828}
.sc-gmv{font-size:22px;font-weight:700;color:var(--ml-blue);margin:6px 0 4px}
.sc-deltas{display:flex;gap:6px;flex-wrap:wrap;font-size:11px}
.sc-asp{font-size:12px;color:var(--muted);margin-top:4px}
.sc-metrics{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-top:10px;border-top:1px solid var(--border);padding-top:8px}
.sc-metric{text-align:center}
.sc-metric-val{font-size:12px;font-weight:600;color:var(--txt)}
.sc-metric-lbl{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}

</style>
</head>
<body>
<div class="header">
  <img class="logo" src="data:image/webp;base64,UklGRppvAABXRUJQVlA4WAoAAAAQAAAAAQYA5QUAQUxQSNcBAAABPyAQSEMKIWx4RASswCqSrDiFAzCFBf5PA5DEv4WzI/o/ATHd/cO67v6F//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//CP/+q8+2cAVlA4IJxtAAAwHwOdASoCBuYFPm02m0mkIyKhIXNIOIANiWdu/H+P6Z/yFtuc7rH/m/7r+6/gKa57L/gf2X/vP/r/xHzwWF+q/gL+0f7//O/eJ/K8Fuz/NT8l/V/9V/fv3C/vX/////3H/2f/Q/sv+W/uvyW/QH/l/vf3////9Af4n/Lf8Z/bv8p/vv7h/////9XX7Xe7D/Df9z8jvgH/Sf8J/yP8Z+/v/J+qH/df7H/X/v/8w/8j/zP9T/iv858gn9Y/un/U/On44vY+/ej2Bv57/sf/r7Pn/b/bb4ZP2z/+f/B/f//6/ZH/Ov7//3/z////0Af//26+kn6f/4j+3ewL4/+s/5/+0/4L1v61/uJzOYl/x/8Lf0vXL/I95v5l/Bfsn7AX4//OP9D+Z/95+RD7j/gdszb70BfeD61/3f8D7APw/mb/S/6j2AP8b4bXgfeofs98AP8p/xXq5/3H7e+ff9L/2vsL/0H/E+mV////d8Ef2+///7//LX+5H//B/5dZl4hjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhiqvDrv4G6QxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupp//P/6LGW7Tq7+RYg6G4JDLwl5mWYs53vl1/sQ02oSfQRDQmD3DysQjkzqwWvaYY7UNl1icvEMZ3U1ATGIYzupqAmMQxndS2QF/tackncxjO6moCYxDGd1NQExiACPkt9pt+g2/86LeJbBl/Njz/wzA7OgK2Zl4xRa4+fkAslqqbTmdqvGvwr7ooTA6/pDGd1NQExiGM7qagJjEMZ3U0Vs9JsJMAV5jEMZ3U1ATGIYzupp/9FPzgEbOddLt3kaXa6kwBIKQCrR/1pILjrHBvaQ6CqF9w0aRDoMn2puuH7xZmK3JHoup3EaFRbKkAkM5NCLV7a81ng1HQFaJmuGf+WFwS9m+7+Ji/Zq9djFl4PN49l4UiNlS/kZMn6apAvy+BUs1sQukPWpJzddi4vABc/nEN5qgeh4IuDpjME3j2hNPMKiwMNwziJwdyNlDeOFhsckvWuTLFA4t6IeJssJLBT6moCYxDGd1NQEvSDWJl2uYYgbIldDphXej3EgHEQtTcZObSR+0xchQX/0i4RDt9/QMyLvavJqs4QgG/o+M9R762xk/U3NNwMP0rKnB3Oqfh3M5WBILugZg8xSjxxr8xUhnoYJAgTB7IbuLSDpA8rwDskq7ulUUDjj34GCzsU4A/MjPyXZyT9adcpp1oXiCc4pB1JTE1+zFqsAO7ftaI/jVFuMK0eholZih/zU/1pCB/XgIt/Q7MxG8+sD9fL3phv3DQPRxR9N0Qo06oTm2pnUsndDDqv3wxsy0G75zNbNl0yOoTl4hjO6moCYxDE4pR8ZXLYQFjbNkNT1zKukj6HcOsXyuubnKJp/MxO7v+8N/SN63eXjeeaI//Jt+ESsD682R6W2yr9972J06U6fPJmEms7oTa4BbAAg4/4Co+ac4YBwIaQLHRHllvzcltUHwwrAT7fMDwJ26GKeISFHvL2bJ8ehtBudENw/oSGsdnLx6mzZ/qFc/M+KNrKwLgQQfv6kV5F8THuxXwUHQGW32F7R27CO4tHrAZRUSbZJiH2bIPtWQbpI2grTFzn/UhVlkSQH5bZ3GfZk0T7n7KKsK3AN/1Vi6AmMQxndTUBMYOucP7WIyRDcz59nmMejFeprQBtE74jfpfBH1RuwzK6xe119HgrzsappNzP0wQ/XwK+U2YsrUlDVqb9OuztxZEMHfFxCNo3pmzAAkk+iaaFuPomoj4U89f/FAN5ds6+nGycnU1yTHQIW2jMLef6tGEBYe63DBaJMC0O5GqDiDMR5CzMVcCB8qZ9KIV9u3EhSFHup3U1ATGIYzupaHkJpVkbjJyvrMqboCozFhJUkwXhuvGNmAhYolqxbO93bRMzZb6kqkcQXTCWLFM7psXrP48tpx3cICFTNmAn+zkCFSPK9WlaoOLwFleKyUAEik5l5ULM+PgIlAA6B+X55v+KVpZvGEbTw2ACaSTSFoqKaEEUpnXx+oh1J/yEKLTpCOnk0ISD2ZjGr6cO93wRAsvxrDkQ7dEeISXxJg1j4bU+CKe9L7KHKElDGd1NQExiGM6QEqFLzDzRd8GSDgwt/PqxfUW6HEOyNslUSywPsCcBrK4WX8RY1QA9b4ubTaw9g2D9fa1oA/M6N6ZswCJPLb6/kWPWLIr/N6VYrjvCAuOWZFyaLsWARKAANb1ggY/mrQGfjYNQzUl+l+gNQGYEvT3bIF0xJJ6kNgGwI4u1BAsClhY9H3zD8NpR99AA0Lz6XfaNiPXRNp5pSphz2bvhLaoHrirUTGd1NQExiGM7qW1cvyIuLmveMiZqvyvMKkvBLJEkuZjdB/WJkDocQxp4ar8wmqLfQCNQEspcZBtM8LFf/NFIf3m8Vx6JGgnz9YMHA3jECYqmMKMmq6eeT4HtaR2oYfXOSBvYaFua0+kIL9efSrTBxtXvCuc+wHilMlivQo67wGiibnxJ7vRjZugy1Sy6IuJg4p0Njc71kHEYDXYKBanr7rv//vEBAj0FVOkG9gwsz//7xATGd1NQExiGM7qaLyVx2F3T7MEhiq+rtvg3BXIRzFynmhP9npr/W32DoTmXIKKFxAqaLmFYq7dZfGDAy0fAWtWwI9ZT1gFAPN4s1D9u79wH1rf9sQ7/4XmACsmN5fA3XYuSjnOdeXeI8qyvbI30ShRqXHWZePIagJjNhCxPRaOgJjEMZ3U1ATGIYzupbWshVag5th4Pboy8zjumnB/SHFwL7YslUNvj6wSJ0lc7gZ59YIA5tBQSy0xUit0e+u/KOxDpigqt57BAwVny6AjDWMsS/49NtzfuH+4rWOwy9bX80BP26DFMBzyHJiIYzpmBCvSe3MYzupqAmMQxndTUBMYhjO6moCYxGwXlmcPUknDdUujuKFWDTaBdLg0AEwwmcsYaNPtm0tDzhg+JnbkxF6vSuppDhCS60sCQq5YwNqSlSZWaSnTA7/uc8UNWLWrH98AhyZG7dciTgnzBuO5PxdXGsNJChfYo/9w32rup4IiIAiA3/1JIKB9rmhCghvPgwHZ8Xn/Si+U5rxXE/3xArdh9JIy13g9sXEMZ3U1ATGIYzupqAmMQxndTUBMVISlN0GfrHKVGtyNQvR5mPvQkPgqk+Cit+2mPgQ8tOhbTlm2XPE7+NTfHZsSimEWf0s1XbIy6MAjg22/o0VwPJCToHkfkaQ2EC7ycFhmHbfeS4sgF5EsjJT4knmdG9JPoM1LdPdwWCBQbMsNONl4kvfHFX6RAwhHp5n3daI5r1FsABnjRkbQ1y6XK9Rw3SOgVddTupqAmMQxndTUBMYhjO6moCYqkW/tEGXCQQQJxt3fBlArYaHJrIR27UGtnzAAfZBPlgxxv9rBMCVKyJgT8ioGPuMsi3t5wPidbo19e+xLV4GVNFBvSUYlq4AdBnGbeKlAZKcmBO4tvBPU3mbqZDPlC9BGFXKHIYrPDtbGPR4QICAyuboZSWhcBqqikaoojXjoZkKpQIhbg1dM7qagJjEMZ3U1ATGIYzupqAmMP9aUWTZ4S+zQSMf8NTKgxCZc0lpQLDUVAAla302iId9pV4IEKQpWwWQaIpdKZLQeZoWq//zAuPRpN/TqxfxLYWAEg0en7n1LdvBPU3mffVjZKd/XNNvVgtCWQB2Sail7wmnREF1fYnCnrdaATU8QyV4hjO6moCYxDGd1NQExiGM7qag3rYuhCu6RUvPC4heKTINDfmOG0R3UlP3PH4zP+AN939LlZ4duDR04agQCkgsR1l8/M6N6ScADR53hCRr44DQeiuueAIlAAxDQzdMiOOdr2Rb5z1eExo3TAMtYX/z33U1ATGIYzupqAmMQxndTUBMYhjO6b+9RjDIlNI90ohIjF7RYzX64g3lJztMRkeb5UyZDaeIaNUbY7gNglGXu1XgWH5P0pw9Eyr+9cFs91O1HuOlJ8s9uNV0KUStEiDY9d0QrBEyT15BwFXP5NdisUVrqE/3PorBcOUiyHCUfxwlFWuBbf/brox7cxjO6moCYxDGd1NQExiGM7qagJjEMadlGBzZ3kMaLMEaDAo5MGmitw142Sb8csAHxhX+I2m0F4yYzIulcQMONIfLsTkX+0vsuex+fU7qagJjEMZ3U1ATGIYzupqAmMQxndTUYR9BuY/A/4jMZZY1KMUZemB7JcjDES9KHfWnnCI7aNXuwsIZTS0rrMvEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQaI9MhxlgFaT6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhj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" alt="Mercado Livre">
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
    <div id="period-btns" style="display:flex;gap:6px;flex-wrap:wrap"></div>
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
const state = { period:'mtd', seller:'all', tab:'geral', customStart:null, customEnd:null };
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

function buildPeriodButtons(){
  var now=new Date(),mo=now.getMonth();
  var defs=[
    {key:'hoje',label:'Hoje'},
    {key:'mtd', label:'MTD'},
    {key:'q1',  label:'Q1'},
    {key:'q2',  label:'Q2'},
  ];
  if(mo>=6) defs.push({key:'q3',label:'Q3'});
  if(mo>=9) defs.push({key:'q4',label:'Q4'});
  defs.push({key:'ytd',label:'YTD'});
  var container=document.getElementById('period-btns');
  if(!container) return;
  container.innerHTML=defs.map(function(b){
    return '<button class="btn'+(state.period===b.key?' active':'')+'" onclick="setPeriod(''+b.key+'',this)">'+b.label+'</button>';
  }).join('');
}

function getPeriodConfig(){
  var now=new Date(),yr=now.getFullYear(),mo=now.getMonth(),p=state.period;
  var fD=function(d){return d.toISOString().slice(0,10);};
  var d1=fD(addDays(now,-1));

  // Custom filter
  if(p==='custom'&&state.customStart){
    var s=state.customStart,e=state.customEnd||state.customStart;
    var cutoff=fD(addDays(now,-89));
    var sD=new Date(s+'T00:00:00'),eD=new Date(e+'T00:00:00');
    var currM=[],cur=new Date(sD.getFullYear(),sD.getMonth(),1);
    var last=new Date(eD.getFullYear(),eD.getMonth(),1);
    while(cur<=last){currM.push(fmtMonth(cur.getFullYear(),cur.getMonth()));cur=new Date(cur.getFullYear(),cur.getMonth()+1,1);}
    if(!currM.length) currM=[fmtMonth(sD.getFullYear(),sD.getMonth())];
    var prevMoM=currM.map(function(m){var y=parseInt(m.slice(0,4)),mo2=parseInt(m.slice(5))-1;return mo2===0?fmtMonth(y-1,11):fmtMonth(y,mo2-1);});
    var prevYoY=currM.map(function(m){return fmtMonth(parseInt(m.slice(0,4))-1,parseInt(m.slice(5))-1);});
    var lbl=s===e?s:(s+' > '+e);
    // Use daily if within 90 days window, else monthly
    if(s>=cutoff){
      return {type:'custom',gran:'daily',curr:[s,e],currM:currM,prevMoM:prevMoM,prevYoY:prevYoY,
        label:lbl,showD1:true,showD2:true,d1Label:'MoM',d2Label:'YoY',
        chartGran:'daily',chartStart:s,chartEnd:e};
    } else {
      return {type:'custom',gran:'monthly',curr:currM,prevMoM:prevMoM,prevYoY:prevYoY,
        label:lbl,showD1:true,showD2:true,d1Label:'MoM',d2Label:'YoY',
        chartGran:'monthly',chartMonths:currM};
    }
  }

  // Hoje: D-1 vs D-2, charts = last 30 days
  if(p==='hoje'){
    var d2=fD(addDays(now,-2)),chartS=fD(addDays(now,-30));
    return {type:'hoje',gran:'daily',curr:[d1,d1],prev:[d2,d2],
      label:'Hoje ('+d1+')',prevLabel:'vs ontem',showD1:true,showD2:false,
      chartGran:'daily',chartStart:chartS,chartEnd:d1};
  }

  // MTD: 1 do mes ate D-1 (daily), MoM+YoY (monthly comparison)
  if(p==='mtd'){
    var mStart=yr+'-'+String(mo+1).padStart(2,'0')+'-01';
    var pm=mo===0?[yr-1,11]:[yr,mo-1];
    return {type:'mtd',gran:'daily',curr:[mStart,d1],
      currM:[fmtMonth(yr,mo)],prevMoM:[fmtMonth(pm[0],pm[1])],prevYoY:[fmtMonth(yr-1,mo)],
      label:'MTD '+fmtMonth(yr,mo),showD1:true,showD2:true,d1Label:'MoM',d2Label:'YoY',
      chartGran:'daily',chartStart:mStart,chartEnd:d1};
  }

  // Q1: Jan-Mar (monthly)
  if(p==='q1'){
    var q1m=['01','02','03'].map(function(m){return yr+'-'+m;});
    var q1py=['01','02','03'].map(function(m){return (yr-1)+'-'+m;});
    return {type:'q1',gran:'monthly',curr:q1m,prevYoY:q1py,
      label:'Q1 '+yr,showD1:false,showD2:true,d2Label:'YoY',
      chartGran:'monthly',chartMonths:q1m};
  }

  // Q2: Apr-Jun
  if(p==='q2'){
    var capMo=Math.min(mo,5); // cap at June
    var q2m=[];
    for(var i=3;i<=capMo;i++) q2m.push(fmtMonth(yr,i));
    if(!q2m.length) q2m=[fmtMonth(yr,3)];
    var q2py=q2m.map(function(m){return fmtMonth(yr-1,parseInt(m.slice(5))-1);});
    return {type:'q2',gran:'monthly',curr:q2m,prevYoY:q2py,
      label:'Q2 '+yr,showD1:false,showD2:true,d2Label:'YoY',
      chartGran:'monthly',chartMonths:q2m};
  }

  // Q3: Jul-Sep (only available from July)
  if(p==='q3'){
    var capMo3=Math.min(mo,8);
    var q3m=[];
    for(var i=6;i<=capMo3;i++) q3m.push(fmtMonth(yr,i));
    if(!q3m.length) q3m=[fmtMonth(yr,6)];
    var q3py=q3m.map(function(m){return fmtMonth(yr-1,parseInt(m.slice(5))-1);});
    return {type:'q3',gran:'monthly',curr:q3m,prevYoY:q3py,
      label:'Q3 '+yr,showD1:false,showD2:true,d2Label:'YoY',
      chartGran:'monthly',chartMonths:q3m};
  }

  // Q4: Oct-Dec (only from October)
  if(p==='q4'){
    var capMo4=Math.min(mo,11);
    var q4m=[];
    for(var i=9;i<=capMo4;i++) q4m.push(fmtMonth(yr,i));
    if(!q4m.length) q4m=[fmtMonth(yr,9)];
    var q4py=q4m.map(function(m){return fmtMonth(yr-1,parseInt(m.slice(5))-1);});
    return {type:'q4',gran:'monthly',curr:q4m,prevYoY:q4py,
      label:'Q4 '+yr,showD1:false,showD2:true,d2Label:'YoY',
      chartGran:'monthly',chartMonths:q4m};
  }

  // YTD: Jan ate mes atual (monthly)
  if(p==='ytd'){
    var ytd=[],ypy=[];
    for(var i=0;i<=mo;i++){ytd.push(fmtMonth(yr,i));ypy.push(fmtMonth(yr-1,i));}
    return {type:'ytd',gran:'monthly',curr:ytd,prevYoY:ypy,
      label:'YTD '+yr,showD1:false,showD2:true,d2Label:'YoY',
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
  var value,d1=null,d2=null;
  if(pc.gran==='daily'){
    value=sumDailyRange(pc.curr[0],pc.curr[1],field);
    if(pc.prev){var pp=sumDailyRange(pc.prev[0],pc.prev[1],field);d1=pp?((value-pp)/pp)*100:null;}
    if(pc.prevMoM){var pm=sumMeses(allM,pc.prevMoM,field);d1=pm?((value-pm)/pm)*100:null;}
    if(pc.prevYoY){var py=sumMeses(allM,pc.prevYoY,field);d2=py?((value-py)/py)*100:null;}
    if(pc.momM){var pm2=sumMeses(allM,pc.momM,field);d1=pm2?((value-pm2)/pm2)*100:null;}
    if(pc.yoyM){var py2=sumMeses(allM,pc.yoyM,field);d2=py2?((value-py2)/py2)*100:null;}
  } else {
    value=sumMeses(allM,pc.curr,field);
    if(pc.prevMoM){var pmo=sumMeses(allM,pc.prevMoM,field);d1=pmo?((value-pmo)/pmo)*100:null;}
    else if(pc.prevQoQ){var pqq=sumMeses(allM,pc.prevQoQ,field);d1=pqq?((value-pqq)/pqq)*100:null;}
    if(pc.prevYoY){var pyo=sumMeses(allM,pc.prevYoY,field);d2=pyo?((value-pyo)/pyo)*100:null;}
  }
  return {value:value,d1:d1,d2:d2};
}

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
  var pc=getPeriodConfig();
  var ids=sellerIds(state.seller);
  var meses=pc.gran==='daily'?(pc.currM||[]):(pc.curr||[]);
  var itemMap={};
  (RAW.catalogo_items||[]).filter(function(r){
    return ids.includes(String(r.cust_id))&&meses.includes(r.mes);
  }).forEach(function(r){
    var k=String(r.cust_id)+'_'+r.item_id;
    if(!itemMap[k]){itemMap[k]={cust_id:r.cust_id,item_id:r.item_id,titulo:r.titulo,gmv:0,si:0,gmv_bb:0};}
    itemMap[k].gmv+=(Number(r.gmv)||0);
    itemMap[k].si +=(Number(r.si) ||0);
    itemMap[k].gmv_bb+=(Number(r.gmv_bb)||0);
  });
  var rows=Object.values(itemMap).sort(function(a,b){return b.gmv-a.gmv;});
  var sellerCount={};
  rows=rows.filter(function(r){
    sellerCount[r.cust_id]=(sellerCount[r.cust_id]||0)+1;
    return sellerCount[r.cust_id]<=20;
  });
  var tG=rows.reduce(function(a,r){return a+(r.gmv||0);},0);
  var h='<thead><tr><th>Seller</th><th>Item ID</th><th>Título</th><th>GMV</th><th>SI</th><th>ASP</th><th>Share %</th><th>GMV BB</th><th>BB%</th></tr></thead><tbody>';
  rows.forEach(function(r){
    var asp=r.si?r.gmv/r.si:0,share=tG?(r.gmv/tG)*100:0,bbPct=r.gmv?(r.gmv_bb/r.gmv)*100:0;
    h+='<tr><td>'+sellerLabel(r.cust_id)+'</td><td>'+r.item_id+'</td>'
      +'<td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(r.titulo||'')+'</td>'
      +'<td>'+fmtBRL(r.gmv)+'</td><td>'+fmtNum(r.si)+'</td><td>'+fmtBRL(asp)+'</td>'
      +'<td><span class="badge">'+fmtPct(share)+'</span></td>'
      +'<td>'+fmtBRL(r.gmv_bb)+'</td>'
      +'<td class="'+(bbPct>=50?'tag-pos':'tag-neg')+'">'+fmtPct(bbPct)+'</td></tr>';
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
  var fD=function(d){return d.toISOString().slice(0,10);};
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
    var gmvYoy=sumMeses(sAllM,prevYoScM,'gmv');
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
    kpiCard('Total Visitas (PV)',fmtNum(totVis),pc,visK.d1,visK.d2)+
    '<div class="kpi-card"><div class="kpi-label">Convers\u00e3o</div><div class="kpi-value">'+fmtPct(convPct)+'</div><div class="kpi-delta"><span class="dn0">Pedidos / Visitas</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">Pedidos (SI)</div><div class="kpi-value">'+fmtNum(totSI)+'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>';
  var cM=pc.chartMonths||pc.curr;
  if(pc.chartGran==='daily'){
    var vc=aggDailyChart(RAW.visitas_daily,'visits',pc.chartStart,pc.chartEnd);
    makeChart('ch-vis-mes','bar',vc.labels,[{label:'Visitas',data:vc.data,backgroundColor:'#3483FA',borderRadius:4}]);
    var vgc=aggDailyChartMulti(RAW.geral_daily,['si'],pc.chartStart,pc.chartEnd);
    var vdc=aggDailyChartMulti(RAW.visitas_daily,['visits'],pc.chartStart,pc.chartEnd);
    makeChart('ch-conv-mes','line',vc.labels,[{label:'Convers\u00e3o%',data:vc.labels.map(function(d){var v=vdc.byField[d]?.visits||0,s=vgc.byField[d]?.si||0;return v?+(s/v*100).toFixed(2):null;}),borderColor:'#00A650',backgroundColor:'#00A65022',fill:true,tension:.3,pointRadius:3}],{yFmt:function(v){return v?.toFixed(1)+'%';}});
  } else {
    makeChart('ch-vis-mes','bar',cM,[{label:'Visitas',data:cM.map(function(m){return allVis[m]?.visits||0;}),backgroundColor:'#3483FA',borderRadius:4}]);
    makeChart('ch-conv-mes','line',cM,[{label:'Convers\u00e3o%',data:cM.map(function(m){var v=allVis[m]?.visits||0,s=allGmv[m]?.si||0;return v?+(s/v*100).toFixed(2):null;}),borderColor:'#00A650',backgroundColor:'#00A65022',fill:true,tension:.3,pointRadius:3}],{yFmt:function(v){return v?.toFixed(1)+'%';}});
  }
  var bySV=aggBySeller(RAW.visitas_monthly,meses,['visits','visits_vip']);
  var bySG=aggBySeller(RAW.geral_monthly,meses,['si']);
  var h='<thead><tr><th>Seller</th><th>Visitas (PV)</th><th>Visitas VIP</th><th>Pedidos (SI)</th><th>Convers\u00e3o</th></tr></thead><tbody>';
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
    '<div class="kpi-card"><div class="kpi-label">Eventos de Compara\u00e7\u00e3o (15d)</div><div class="kpi-value">'+fmtNum(Math.round(totVis))+'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">Eventos: Pre\u00e7o Meli 3%+</div><div class="kpi-value">'+fmtNum(Math.round(totExp))+'</div><div class="kpi-delta"><span class="dn0">\u2014</span></div></div>'+
    '<div class="kpi-card"><div class="kpi-label">% Eventos Caros</div><div class="kpi-value">'+fmtPct(bpcRate)+'</div><div class="kpi-delta"><span class="dn0">Pior = mais alto</span></div></div>';
  var hs='<thead><tr><th>Seller</th><th>It\u00eans</th><th>N\u00e3o Comp.</th><th>Eventos Compara\u00e7\u00e3o</th><th>Eventos Caros</th><th>% Caros</th></tr></thead><tbody>';
  Object.entries(summ).sort(function(a,b){return b[1].visExp-a[1].visExp;}).forEach(function([cid,v]){
    var pct=v.vis?+(v.visExp/v.vis*100).toFixed(1):0;
    hs+='<tr><td>'+sellerLabel(cid)+'</td><td>'+fmtNum(v.items)+'</td><td class="'+(v.nonComp>0?'tag-neg':'tag-pos')+'">'+fmtNum(v.nonComp)+'</td><td>'+fmtNum(Math.round(v.vis))+'</td><td>'+fmtNum(Math.round(v.visExp))+'</td><td class="'+(pct>30?'tag-neg':pct>10?'dp':'tag-pos')+'">'+fmtPct(pct)+'</td></tr>';
  });
  document.getElementById('tbl-bpc-sellers').innerHTML=hs+'</tbody>';
  var hi='<thead><tr><th>Seller</th><th>Item ID</th><th>T\u00edtulo</th><th>Pre\u00e7o Meli</th><th>Pre\u00e7o Rival</th><th>Gap</th><th>Rival</th><th>Eventos</th><th>Ev. Caros</th><th>Link ML</th><th>Link Rival</th></tr></thead><tbody>';
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
  buildPeriodButtons();
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
buildPeriodButtons();
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
    logo_path = os.path.join(os.path.dirname(__file__), "ml-logo-new.webp")
    logo_b64 = _b64.b64encode(open(logo_path, "rb").read()).decode()
    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json).replace("UklGRppvAABXRUJQVlA4WAoAAAAQAAAAAQYA5QUAQUxQSNcBAAABPyAQSEMKIWx4RASswCqSrDiFAzCFBf5PA5DEv4WzI/o/ATHd/cO67v6F//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//iP//CP/+q8+2cAVlA4IJxtAAAwHwOdASoCBuYFPm02m0mkIyKhIXNIOIANiWdu/H+P6Z/yFtuc7rH/m/7r+6/gKa57L/gf2X/vP/r/xHzwWF+q/gL+0f7//O/eJ/K8Fuz/NT8l/V/9V/fv3C/vX/////3H/2f/Q/sv+W/uvyW/QH/l/vf3////9Af4n/Lf8Z/bv8p/vv7h/////9XX7Xe7D/Df9z8jvgH/Sf8J/yP8Z+/v/J+qH/df7H/X/v/8w/8j/zP9T/iv858gn9Y/un/U/On44vY+/ej2Bv57/sf/r7Pn/b/bb4ZP2z/+f/B/f//6/ZH/Ov7//3/z////0Af//26+kn6f/4j+3ewL4/+s/5/+0/4L1v61/uJzOYl/x/8Lf0vXL/I95v5l/Bfsn7AX4//OP9D+Z/95+RD7j/gdszb70BfeD61/3f8D7APw/mb/S/6j2AP8b4bXgfeofs98AP8p/xXq5/3H7e+ff9L/2vsL/0H/E+mV////d8Ef2+///7//LX+5H//B/5dZl4hjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGI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qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhjO6moCYxDGd1NQExiGM7qagJjEMZ3U1ATGIYzupqAmMQxndTUBMYhj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", logo_b64)
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
