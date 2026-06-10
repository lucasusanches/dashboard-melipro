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

# ── Lock file (evita execuções paralelas) ─────────────────────────────────────
_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".generate.lock")
_LOCK_STALE_SECONDS = 40 * 60  # considera lock abandonado após 40 min

def _acquire_lock():
    if os.path.exists(_LOCK_FILE):
        try:
            age = time.time() - os.path.getmtime(_LOCK_FILE)
            if age < _LOCK_STALE_SECONDS:
                with open(_LOCK_FILE) as f:
                    pid = f.read().strip()
                print(f"AVISO: outra execução em andamento (PID {pid}, há {age/60:.1f} min). Abortando.")
                sys.exit(1)
            print(f"Lock antigo removido (idle {age/60:.1f} min).")
            os.remove(_LOCK_FILE)
        except OSError:
            pass
    try:
        fd = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        print("AVISO: lock já existe. Abortando para evitar execução paralela.")
        sys.exit(1)

def _release_lock():
    try:
        os.remove(_LOCK_FILE)
    except OSError:
        pass







# Ensure UTF-8 output on Windows + line_buffering para flush imediato em redirecionamento
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)







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



    202725990:  {"name": "Casa Aberta",              "group": "Casa Aberta"},



    701145835:  {"name": "Casa Cab",                 "group": "Casa Aberta"},



    1428239362: {"name": "Fidelitá",                 "group": "Fidelitá"},



    760931003:  {"name": "Nesher",                   "group": "Nesher"},



}







CUST_IDS = list(SELLERS.keys())



IDS_STR  = ",".join(str(x) for x in CUST_IDS)

# Promoções usadas na aba Catálogo (disponibilidade + optin)
PROMO_IDS = [
    'P-MLB17513056',   # Pré-Acordo (lojas originais + novas a partir de jun/26)
    'P-MLB17513052',   # Pré-Acordo (Casa Aberta/Cab/Fidelitá/Nesher — mai/26, válido até 19/07/26)
    'P-MLB17609074', 'P-MLB17609076', 'P-MLB17609088',
    'P-MLB17611022', 'P-MLB17611024', 'P-MLB17611036',
    'P-MLB17611042', 'P-MLB17611044',
    'P-MLB17613004', 'P-MLB17613006',
]
PROMO_IDS_STR = "'" + "', '".join(PROMO_IDS) + "'"

# IDs exclusivos de pré-acordo (sem as campanhas de catálogo)
# Quando P-MLB17513052 expirar (após 19/07/26) basta removê-lo daqui e de PROMO_IDS
PRE_ACORDO_IDS = ['P-MLB17513056', 'P-MLB17513052']
PRE_ACORDO_IDS_STR = "'" + "', '".join(PRE_ACORDO_IDS) + "'"







FF_TYPES      = ("fulfillment",)



XD_TYPES      = ("cross_docking", "xd_drop_off")



SS_TYPES      = ("self_service", "drop_off", "default")







client = bigquery.Client(project=PROJECT)











# ── Query helpers ────────────────────────────────────────────────────────────



def run(sql: str) -> list[dict]:
    import random
    for attempt in range(5):
        try:
            time.sleep(2 + random.uniform(0, 1))   # era 8-12s; 2-3s é suficiente
            rows = list(client.query(sql).result())
            return [dict(r) for r in rows]
        except Exception as e:
            if ('quotaExceeded' in str(e) or 'Quota exceeded' in str(e)) and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f'  Cota BQ, aguardando {wait}s (tentativa {attempt+1}/5)...', flush=True)
                time.sleep(wait)
            else:
                raise











# ── Queries ──────────────────────────────────────────────────────────────────



def q_geral_monthly():



    """GMV, SI, ASP por seller por mês — últimos 25 meses (YoY + MoM)."""



    return run(f"""



        SELECT



            FORMAT_DATE('%Y-%m', ORD_CLOSED_DT)      AS mes,



            CUS_CUST_ID_SEL                           AS cust_id,



            COALESCE(VERTICAL, 'OUTROS')              AS vertical,



            ROUND(SUM(GMV_LC), 2)                     AS gmv,



            SUM(SI)                                   AS si,



            ROUND(SAFE_DIVIDE(SUM(GMV_LC), SUM(SI)), 2) AS asp



        FROM {TABLE}



        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})



          AND GMV_FLG = TRUE



          AND ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)



          AND ORD_CLOSED_DT < CURRENT_DATE()



        GROUP BY 1, 2, 3



        ORDER BY 1, 2



    """)











def q_geral_daily():



    """GMV, SI por seller por dia — últimos 90 dias."""



    return run(f"""



        SELECT



            CAST(ORD_CLOSED_DT AS STRING)             AS dia,



            CUS_CUST_ID_SEL                           AS cust_id,



            COALESCE(VERTICAL, 'OUTROS')              AS vertical,



            ROUND(SUM(GMV_LC), 2)                     AS gmv,



            SUM(SI)                                   AS si



        FROM {TABLE}



        WHERE CUS_CUST_ID_SEL IN ({IDS_STR})



          AND GMV_FLG = TRUE



          AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)



          AND ORD_CLOSED_DT < CURRENT_DATE()



        GROUP BY 1, 2, 3



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
            ROUND(SUM(CASE WHEN LOGISTIC_TYPE IN ('{ss}') THEN GMV_LC ELSE 0 END),2) AS gmv_ss,
            SUM(SI)                                                                   AS si_total,
            SUM(CASE WHEN LOGISTIC_TYPE IN ('{ff}') THEN SI ELSE 0 END)              AS si_ff,
            SUM(CASE WHEN LOGISTIC_TYPE IN ('{xd}') THEN SI ELSE 0 END)              AS si_xd,
            SUM(CASE WHEN LOGISTIC_TYPE IN ('{ss}') THEN SI ELSE 0 END)              AS si_ss
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
    """Investimentos 10 tipos por seller por dia - ultimos 90 dias."""
    return run(f"""
        WITH pandora AS (
            SELECT DISTINCT CUS_CUST_ID_SEL, CAST(ITE_ITEM_ID AS STRING) AS item_id
            FROM `meli-bi-data.WHOWNER.LK_MKP_CAMPAIGN_ITEM_OPTIN`
            WHERE SIT_SITE_ID = 'MLB'
              AND PROMOTION_ID IN ({PRE_ACORDO_IDS_STR})
              AND CUS_CUST_ID_SEL IN ({IDS_STR})
              AND ITEM_CANDIDATE_FLG = TRUE
              AND ITE_ITEM_ID != 4015179919
              AND DS >= '2026-01-01'
        )
        SELECT
            CAST(d.ORD_CLOSED_DT AS STRING)  AS dia,
            d.CUS_CUST_ID_SEL                AS cust_id,
            ROUND(SUM(CASE WHEN d.DXI_CAMPAIGN_SUBTYPE = 'PRE_ACORDO' AND p.item_id IS NOT NULL
                           THEN COALESCE(d.DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS pre_acordo,
            ROUND(SUM(COALESCE(d.DOD_INVESTMENT_LC,0)),2)                       AS dod,
            ROUND(SUM(COALESCE(d.LIGHTNING_INVESTMENT_LC,0)),2)                 AS relampago,
            ROUND(SUM(CASE WHEN d.SMART_CAMPAIGN_FLG = TRUE
                           THEN COALESCE(d.DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS sad,
            ROUND(SUM(COALESCE(d.AUTOMATIC_CAMPAIGN_INVESTMENT_LC,0)),2)        AS automaticas,
            ROUND(SUM(CASE WHEN d.DXI_CAMPAIGN_SUBTYPE = 'PRICING_MATCHING'
                           THEN COALESCE(d.DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS pm_cofin,
            ROUND(SUM(CASE WHEN d.DXI_CAMPAIGN_SUBTYPE = 'PRICING_MATCHING_MELI_ALL'
                           THEN COALESCE(d.DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS pm_100,
            ROUND(SUM(CASE WHEN d.DXB_PAYMENT_METHOD = 'PIX'
                           THEN COALESCE(d.DXB_INVESTMENT_LC,0) ELSE 0 END),2) AS pix,
            ROUND(SUM(CASE WHEN d.CPN_SELLER_FLG = FALSE AND d.CPN_SOURCE != 'MARKETING'
                           THEN COALESCE(d.CPN_AMOUNT_LC,0) ELSE 0 END),2)     AS cupom_comercial,
            ROUND(SUM(CASE WHEN d.CPN_SELLER_FLG = FALSE AND d.CPN_SOURCE = 'MARKETING'
                           THEN COALESCE(d.CPN_AMOUNT_LC,0) ELSE 0 END),2)     AS cupom_marketing
        FROM {TABLE} d
        LEFT JOIN pandora p
            ON d.CUS_CUST_ID_SEL = p.CUS_CUST_ID_SEL
           AND CAST(d.ITE_ITEM_ID AS STRING) = p.item_id
        WHERE d.CUS_CUST_ID_SEL IN ({IDS_STR})
          AND d.GMV_FLG = TRUE
          AND d.ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
          AND d.ORD_CLOSED_DT < CURRENT_DATE()
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
    """Investimentos 10 tipos por seller por mes."""
    return run(f"""
        WITH pandora AS (
            SELECT DISTINCT CUS_CUST_ID_SEL, CAST(ITE_ITEM_ID AS STRING) AS item_id
            FROM `meli-bi-data.WHOWNER.LK_MKP_CAMPAIGN_ITEM_OPTIN`
            WHERE SIT_SITE_ID = 'MLB'
              AND PROMOTION_ID IN ({PRE_ACORDO_IDS_STR})
              AND CUS_CUST_ID_SEL IN ({IDS_STR})
              AND ITEM_CANDIDATE_FLG = TRUE
              AND ITE_ITEM_ID != 4015179919
              AND DS >= '2026-01-01'
        )
        SELECT
            FORMAT_DATE('%Y-%m', d.ORD_CLOSED_DT) AS mes,
            d.CUS_CUST_ID_SEL                      AS cust_id,
            ROUND(SUM(d.GMV_LC), 2)                AS gmv,
            -- Pré-Acordo: itens das campanhas pré-acordo (P-MLB17513056 / P-MLB17513052)
            ROUND(SUM(CASE WHEN d.DXI_CAMPAIGN_SUBTYPE = 'PRE_ACORDO' AND p.item_id IS NOT NULL
                           THEN COALESCE(d.DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS pre_acordo,
            ROUND(SUM(COALESCE(d.DOD_INVESTMENT_LC,0)),2)                       AS dod,
            ROUND(SUM(COALESCE(d.LIGHTNING_INVESTMENT_LC,0)),2)                 AS relampago,
            -- SAD (Smart / Automáticas Digitais)
            ROUND(SUM(CASE WHEN d.SMART_CAMPAIGN_FLG = TRUE
                           THEN COALESCE(d.DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS sad,
            -- Automáticas
            ROUND(SUM(COALESCE(d.AUTOMATIC_CAMPAIGN_INVESTMENT_LC,0)),2)        AS automaticas,
            -- PM Cofinanciada
            ROUND(SUM(CASE WHEN d.DXI_CAMPAIGN_SUBTYPE = 'PRICING_MATCHING'
                           THEN COALESCE(d.DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS pm_cofin,
            -- PM 100% Meli
            ROUND(SUM(CASE WHEN d.DXI_CAMPAIGN_SUBTYPE = 'PRICING_MATCHING_MELI_ALL'
                           THEN COALESCE(d.DXI_INVESTMENT_LC,0) ELSE 0 END),2) AS pm_100,
            -- PIX
            ROUND(SUM(CASE WHEN d.DXB_PAYMENT_METHOD = 'PIX'
                           THEN COALESCE(d.DXB_INVESTMENT_LC,0) ELSE 0 END),2) AS pix,
            -- Cupons Comercial (não-marketing)
            ROUND(SUM(CASE WHEN d.CPN_SELLER_FLG = FALSE AND d.CPN_SOURCE != 'MARKETING'
                           THEN COALESCE(d.CPN_AMOUNT_LC,0) ELSE 0 END),2)     AS cupom_comercial,
            -- Cupons Marketing
            ROUND(SUM(CASE WHEN d.CPN_SELLER_FLG = FALSE AND d.CPN_SOURCE = 'MARKETING'
                           THEN COALESCE(d.CPN_AMOUNT_LC,0) ELSE 0 END),2)     AS cupom_marketing
        FROM {TABLE} d
        LEFT JOIN pandora p
            ON d.CUS_CUST_ID_SEL = p.CUS_CUST_ID_SEL
           AND CAST(d.ITE_ITEM_ID AS STRING) = p.item_id
        WHERE d.CUS_CUST_ID_SEL IN ({IDS_STR})
          AND d.GMV_FLG = TRUE
          AND d.ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND d.ORD_CLOSED_DT < CURRENT_DATE()
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)








def q_catalogo_campaigns():
    """Disponibilidade (DM_CAMPAIGN_ID_ITEM) e optin confirmado (LK_ITE_ITEM_PRICES) por item."""
    return run(f"""
        WITH camp_avail AS (
            SELECT DISTINCT
                CAST(SELLER_ID   AS STRING) AS cust_id,
                CAST(ITE_ITEM_ID AS STRING) AS item_id
            FROM `meli-bi-data.WHOWNER.DM_CAMPAIGN_ID_ITEM`
            WHERE SIT_SITE_ID = 'MLB'
              AND CAST(SELLER_ID AS INT64) IN ({IDS_STR})
              AND PROMOTION_ID IN ({PROMO_IDS_STR})
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY PROMOTION_ID, SELLER_ID, ITE_ITEM_ID
                ORDER BY TIM_DATE DESC
            ) = 1
        ),
        optin_conf AS (
            SELECT DISTINCT CAST(ITE_ITEM_ID AS STRING) AS item_id
            FROM `meli-bi-data.WHOWNER.LK_ITE_ITEM_PRICES`
            WHERE SIT_SITE_ID = 'MLB'
              AND CAM_CAMPAIGN_ID IN ({PROMO_IDS_STR})
              AND ITE_ITEM_PRICE_API_STATUS = 'ACTIVE'
        )
        SELECT
            c.cust_id,
            c.item_id,
            1                                                       AS in_campaign,
            MAX(CASE WHEN o.item_id IS NOT NULL THEN 1 ELSE 0 END) AS optin
        FROM camp_avail c
        LEFT JOIN optin_conf o ON c.item_id = o.item_id
        GROUP BY 1, 2, 3
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











def q_catalogo_monthly():
    """Top 50 itens por seller (ranking últimos 3 meses) — agregação mensal + GMV total seller."""
    return run(f"""
        WITH all_seller_gmv AS (
            SELECT
                FORMAT_DATE('%Y-%m', ORD_CLOSED_DT) AS mes,
                CUS_CUST_ID_SEL                      AS cust_id,
                ROUND(SUM(GMV_LC), 2)                AS seller_total_gmv
            FROM {TABLE}
            WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
              AND GMV_FLG = TRUE
              AND ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
              AND ORD_CLOSED_DT < CURRENT_DATE()
            GROUP BY 1, 2
        ),
        top_items AS (
            SELECT CUS_CUST_ID_SEL, ITE_ITEM_ID, MAX(ITE_ITEM_TITLE) AS titulo
            FROM {TABLE}
            WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
              AND GMV_FLG = TRUE
              AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
              AND ORD_CLOSED_DT < CURRENT_DATE()
            GROUP BY 1, 2
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY CUS_CUST_ID_SEL
                ORDER BY SUM(GMV_LC) DESC
            ) <= 50
        )
        SELECT
            FORMAT_DATE('%Y-%m', d.ORD_CLOSED_DT)    AS mes,
            d.CUS_CUST_ID_SEL                         AS cust_id,
            d.ITE_ITEM_ID                             AS item_id,
            t.titulo,
            ROUND(SUM(d.GMV_LC), 2)                   AS gmv,
            SUM(d.SI)                                 AS si,
            MAX(COALESCE(d.VERTICAL, 'OUTROS'))        AS vertical,
            g.seller_total_gmv
        FROM {TABLE} d
        INNER JOIN top_items t
            ON d.CUS_CUST_ID_SEL = t.CUS_CUST_ID_SEL
           AND d.ITE_ITEM_ID     = t.ITE_ITEM_ID
        LEFT JOIN all_seller_gmv g
            ON FORMAT_DATE('%Y-%m', d.ORD_CLOSED_DT) = g.mes
           AND d.CUS_CUST_ID_SEL = g.cust_id
        WHERE d.CUS_CUST_ID_SEL IN ({IDS_STR})
          AND d.GMV_FLG = TRUE
          AND d.ORD_CLOSED_DT >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), YEAR)
          AND d.ORD_CLOSED_DT < CURRENT_DATE()
        GROUP BY 1, 2, 3, 4, 8
        ORDER BY 2, 3, 1
    """)


def q_catalogo_daily():
    """Top 50 itens por seller — agregação diária, últimos 90 dias + GMV total seller."""
    return run(f"""
        WITH all_seller_daily_gmv AS (
            SELECT
                CAST(ORD_CLOSED_DT AS STRING) AS dia,
                CUS_CUST_ID_SEL               AS cust_id,
                ROUND(SUM(GMV_LC), 2)         AS seller_total_gmv
            FROM {TABLE}
            WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
              AND GMV_FLG = TRUE
              AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
              AND ORD_CLOSED_DT < CURRENT_DATE()
            GROUP BY 1, 2
        ),
        top_items AS (
            SELECT CUS_CUST_ID_SEL, ITE_ITEM_ID
            FROM {TABLE}
            WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
              AND GMV_FLG = TRUE
              AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
              AND ORD_CLOSED_DT < CURRENT_DATE()
            GROUP BY 1, 2
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY CUS_CUST_ID_SEL
                ORDER BY SUM(GMV_LC) DESC
            ) <= 50
        )
        SELECT
            CAST(d.ORD_CLOSED_DT AS STRING)           AS dia,
            d.CUS_CUST_ID_SEL                         AS cust_id,
            d.ITE_ITEM_ID                             AS item_id,
            ROUND(SUM(d.GMV_LC), 2)                   AS gmv,
            SUM(d.SI)                                 AS si,
            MAX(COALESCE(d.VERTICAL, 'OUTROS'))        AS vertical,
            g.seller_total_gmv
        FROM {TABLE} d
        INNER JOIN top_items t
            ON d.CUS_CUST_ID_SEL = t.CUS_CUST_ID_SEL
           AND d.ITE_ITEM_ID     = t.ITE_ITEM_ID
        LEFT JOIN all_seller_daily_gmv g
            ON CAST(d.ORD_CLOSED_DT AS STRING) = g.dia
           AND d.CUS_CUST_ID_SEL = g.cust_id
        WHERE d.CUS_CUST_ID_SEL IN ({IDS_STR})
          AND d.GMV_FLG = TRUE
          AND d.ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
          AND d.ORD_CLOSED_DT < CURRENT_DATE()
        GROUP BY 1, 2, 3, 7
        ORDER BY 1, 2, 3
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
    ids_q = "'383523670','794123311','568773774','70123968','2355501248','638325656','1802758219','700583148','202725990','701145835','1428239362','760931003'"
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



def q_pandora_items():
    """Items ATUALMENTE elegíveis na campanha P-MLB17513056.
    Usa QUALIFY ROW_NUMBER() para pegar o registro mais recente por (seller, item) e
    garantir que apenas itens com ITEM_CANDIDATE_FLG=TRUE na data mais recente sejam exibidos.
    preco_negociado = INITIAL_PRICE - DISCOUNT_SELLER
    rebate          = DISCOUNT_MELI_AMOUNT
    preco_final     = INITIAL_PRICE - DISCOUNT_SELLER - DISCOUNT_MELI
    """
    return run(f"""
        WITH optin AS (
            SELECT
                o.TYPE                                        AS tipo,
                o.CUS_CUST_ID_SEL                            AS cust_id,
                CAST(o.ITE_ITEM_ID AS STRING)                AS item_id
            FROM `meli-bi-data.WHOWNER.LK_MKP_CAMPAIGN_ITEM_OPTIN` o
            WHERE o.SIT_SITE_ID = 'MLB'
              AND o.PROMOTION_ID = 'P-MLB17513056'
              AND o.CUS_CUST_ID_SEL IN ({IDS_STR})
              AND o.ITE_ITEM_ID != 4015179919
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY o.CUS_CUST_ID_SEL, o.ITE_ITEM_ID
                ORDER BY o.DS DESC
            ) = 1
              AND o.ITEM_CANDIDATE_FLG = TRUE
        ),
        offers AS (
            SELECT
                CAST(ITE_ITEM_ID AS STRING)                                                    AS item_id,
                ROUND(INITIAL_PRICE - COALESCE(DISCOUNT_SELLER_AMOUNT, 0), 2)                 AS preco_negociado,
                ROUND(COALESCE(DISCOUNT_MELI_AMOUNT, 0), 2)                                   AS rebate,
                ROUND(INITIAL_PRICE - COALESCE(DISCOUNT_MELI_AMOUNT, 0)
                      - COALESCE(DISCOUNT_SELLER_AMOUNT, 0), 2)                               AS preco_final,
                STATUS_ID                                                                      AS status_campanha
            FROM `meli-bi-data.WHOWNER.LK_MKP_PROMOTIONS_OFFERS`
            WHERE PROMOTION_ID = 'P-MLB17513056'
              AND SIT_SITE_ID = 'MLB'
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY ITE_ITEM_ID ORDER BY AUD_UPD_DTTM DESC
            ) = 1
        ),
        titles AS (
            SELECT CAST(ITE_ITEM_ID AS STRING) AS item_id, MAX(ITE_ITEM_TITLE) AS titulo
            FROM {TABLE}
            WHERE CUS_CUST_ID_SEL IN ({IDS_STR})
              AND ORD_CLOSED_DT >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
              AND GMV_FLG = TRUE
            GROUP BY 1
        )
        SELECT
            o.tipo, o.cust_id, o.item_id,
            f.preco_negociado, f.rebate, f.preco_final, f.status_campanha,
            COALESCE(t.titulo, CONCAT('MLB', o.item_id)) AS titulo
        FROM optin o
        LEFT JOIN offers f ON o.item_id = f.item_id
        LEFT JOIN titles t ON o.item_id = t.item_id
        ORDER BY o.cust_id, o.tipo, o.item_id
    """)


def q_pandora_financeiro():
    """GMV e investimento de rebate mensal por item da campanha Pandora."""
    return run(f"""
        WITH pandora AS (
            SELECT DISTINCT CUS_CUST_ID_SEL, CAST(ITE_ITEM_ID AS STRING) AS item_id
            FROM `meli-bi-data.WHOWNER.LK_MKP_CAMPAIGN_ITEM_OPTIN`
            WHERE SIT_SITE_ID = 'MLB'
              AND PROMOTION_ID = 'P-MLB17513056'
              AND CUS_CUST_ID_SEL IN ({IDS_STR})
              AND ITEM_CANDIDATE_FLG = TRUE
              AND ITE_ITEM_ID != 4015179919
              AND DS >= '2026-01-01'
        )
        SELECT
            FORMAT_DATE('%Y-%m', d.ORD_CLOSED_DT)                                   AS mes,
            d.CUS_CUST_ID_SEL                                                        AS cust_id,
            CAST(d.ITE_ITEM_ID AS STRING)                                            AS item_id,
            ROUND(SUM(d.GMV_LC), 2)                                                  AS gmv,
            ROUND(
                SUM(CASE WHEN d.DXI_CAMPAIGN_SUBTYPE = 'PRE_ACORDO'
                         THEN COALESCE(d.DXI_INVESTMENT_LC, 0) ELSE 0 END)
              + SUM(COALESCE(d.DOD_INVESTMENT_LC, 0)), 2)                           AS rebate_invest
        FROM {TABLE} d
        JOIN pandora p
            ON d.CUS_CUST_ID_SEL = p.CUS_CUST_ID_SEL
           AND CAST(d.ITE_ITEM_ID AS STRING) = p.item_id
        WHERE d.CUS_CUST_ID_SEL IN ({IDS_STR})
          AND d.GMV_FLG = TRUE
          AND d.ORD_CLOSED_DT >= '2026-01-01'
          AND d.ORD_CLOSED_DT < CURRENT_DATE()
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """)



def q_pandora_camp():
    """Elegibilidade e optin atuais na campanha P-MLB17513056 (estado ao vivo).
    Usado para o mês corrente; mai/26 usa snapshot congelado (snapshot_mai26.json).
    """
    return run(f"""
        WITH camp_avail AS (
            SELECT DISTINCT CAST(SELLER_ID AS STRING) AS cust_id,
                            CAST(ITE_ITEM_ID AS STRING) AS item_id
            FROM `meli-bi-data.WHOWNER.DM_CAMPAIGN_ID_ITEM`
            WHERE SIT_SITE_ID = 'MLB'
              AND CAST(SELLER_ID AS INT64) IN ({IDS_STR})
              AND PROMOTION_ID = 'P-MLB17513056'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY SELLER_ID, ITE_ITEM_ID ORDER BY TIM_DATE DESC) = 1
        ),
        optin_conf AS (
            SELECT DISTINCT CAST(ITE_ITEM_ID AS STRING) AS item_id
            FROM `meli-bi-data.WHOWNER.LK_ITE_ITEM_PRICES`
            WHERE SIT_SITE_ID = 'MLB'
              AND CAM_CAMPAIGN_ID = 'P-MLB17513056'
              AND ITE_ITEM_PRICE_API_STATUS = 'ACTIVE'
        )
        SELECT c.cust_id, c.item_id, 1 AS elegivel,
               MAX(CASE WHEN o.item_id IS NOT NULL THEN 1 ELSE 0 END) AS optin
        FROM camp_avail c
        LEFT JOIN optin_conf o ON c.item_id = o.item_id
        GROUP BY 1, 2, 3
        ORDER BY 1, 2
    """)


def fetch_vc_pandora(items):
    """Chama Benefits Playground API para cada (item, preco_final, rebate) unico."""
    import urllib.request as _ur
    result = []
    seen = set()
    BP = ("https://benefits-playground.adminml.com/benefits-playground/"
          "dc-calculator/MLB{iid}?price={p}&rebate={r}")
    for row in items:
        iid = str(row.get("item_id", ""))
        pn = row.get("preco_negociado")
        pf = row.get("preco_final")
        if not iid or pn is None or pf is None:
            result.append({"item_id": iid, "preco_final": pf, "rebate": None,
                           "dc_atual": None, "vc_final": None})
            continue
        rebate = max(0.0, round(float(pn) - float(pf), 2))
        key = f"{iid}_{pf}_{rebate}"
        if key in seen:
            continue
        seen.add(key)
        url = BP.format(iid=iid, p=float(pf), r=rebate)
        try:
            req = _ur.Request(url, headers={"User-Agent": "MeliPro-Dashboard/1.0"})
            with _ur.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            dc = data.get("dc_info", {}).get("dc_suggested")
            vc = data.get("new_dc_estimated")
            result.append({
                "item_id": iid, "preco_final": float(pf), "rebate": rebate,
                "dc_atual": round(float(dc) * 100, 2) if dc is not None else None,
                "vc_final": round(float(vc) * 100, 2) if vc is not None else None,
            })
        except Exception as e:
            print(f"  VC API MLB{iid}: {e}")
            result.append({"item_id": iid, "preco_final": float(pf), "rebate": rebate,
                           "dc_atual": None, "vc_final": None})
    return result



def build_dataset() -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print("Consultando BQ...", flush=True)

    # ── Batch 1: 18 queries independentes em paralelo (4 workers) ────────────
    _BATCH1 = {
        'geral_m':  (q_geral_monthly,          'Geral mensal'),
        'geral_d':  (q_geral_daily,             'Geral diário'),
        'log_m':    (q_logistica_monthly,       'Logística mensal'),
        'log_d':    (q_logistica_daily,         'Logística diária'),
        'ads_m':    (q_ads_monthly,             'ADS mensal'),
        'ads_d':    (q_ads_daily,               'ADS diário'),
        'inv_m':    (q_investimentos_monthly,   'Investimentos mensal'),
        'inv_d':    (q_investimentos_daily,     'Investimentos diário'),
        'bb_m':     (q_buybox_monthly,          'BuyBox'),
        'cat_m':    (q_catalogo_monthly,        'Catálogo mensal'),
        'cat_d':    (q_catalogo_daily,          'Catálogo diário'),
        'cat_c':    (q_catalogo_campaigns,      'Catálogo campanhas'),
        'rep':      (q_seller_reputation,       'Reputação'),
        'vis_m':    (q_visitas_monthly,         'Visitas mensal'),
        'vis_d':    (q_visitas_daily,           'Visitas diário'),
        'vis_i':    (q_visitas_items,           'Visitas por item'),
        'bpc':      (q_bpc_aurora,              'BPC e Aurora'),
        'camp':     (q_campanhas,               'Campanhas'),
    }
    R = {}
    with ThreadPoolExecutor(max_workers=4) as _ex:
        _futures = {_ex.submit(fn): (key, lbl) for key, (fn, lbl) in _BATCH1.items()}
        for _fut in as_completed(_futures):
            _key, _lbl = _futures[_fut]
            R[_key] = _fut.result()
            print(f"  ✓ {_lbl}", flush=True)

    # ── Batch 2: Pandora (3 queries independentes em paralelo) ───────────────
    print("  → Pandora (itens + financeiro + camp. em paralelo)...", flush=True)
    _BATCH2 = {
        'pand_items': (q_pandora_items,      'itens'),
        'pand_fin':   (q_pandora_financeiro, 'financeiro'),
        'pand_camp':  (q_pandora_camp,       'camp. Pré-Acordo'),
    }
    with ThreadPoolExecutor(max_workers=3) as _ex:
        _futures = {_ex.submit(fn): (key, lbl) for key, (fn, lbl) in _BATCH2.items()}
        for _fut in as_completed(_futures):
            _key, _lbl = _futures[_fut]
            R[_key] = _fut.result()
            print(f"  ✓ Pandora {_lbl}", flush=True)

    # ── Pandora VC (depende de pand_items) ───────────────────────────────────
    print("  → Pandora VC (Benefits Playground)...", flush=True)
    pand_vc = fetch_vc_pandora(R['pand_items'])
    print("  Consultas concluídas.", flush=True)

    # aliases para facilitar leitura abaixo
    geral_m = R['geral_m']; geral_d = R['geral_d']
    log_m   = R['log_m'];   log_d   = R['log_d']
    ads_m   = R['ads_m'];   ads_d   = R['ads_d']
    inv_m   = R['inv_m'];   inv_d   = R['inv_d']
    bb_m    = R['bb_m'];    cat_m   = R['cat_m']
    cat_d   = R['cat_d'];   cat_c   = R['cat_c']
    rep     = R['rep'];     vis_m   = R['vis_m']
    vis_d   = R['vis_d'];   vis_i   = R['vis_i']
    bpc     = R['bpc'];     camp    = R['camp']
    pand_items = R['pand_items']; pand_fin = R['pand_fin']; pand_camp = R['pand_camp']

    # Convert date/Decimal to serialisable types; strip surrogate chars from strings
    def clean(obj):
        if isinstance(obj, (date, datetime)):
            return str(obj)
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, str):
            # Remove lone surrogates that would break UTF-8 encoding
            return obj.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        return obj

    def clean_rows(rows):
        return [{k: clean(v) for k, v in row.items()} for row in rows]

    # ── Snapshot mai/2026 ────────────────────────────────────────────────────
    # Congela elegibilidade (pandora_camp) e preços VC (pandora_vc) de mai/26
    # na primeira execução de junho, antes que os dados de campanha mudem.
    SNAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshot_mai26.json")
    if os.path.exists(SNAP_FILE):
        with open(SNAP_FILE, encoding="utf-8") as _sf:
            _snap = json.load(_sf)
        camp_mai26 = _snap.get("pandora_camp_mai26", [])
        vc_mai26   = _snap.get("pandora_vc_mai26", [])
        print("  → Snapshot mai/26 carregado.")
    else:
        camp_mai26 = clean_rows(pand_camp)
        vc_mai26   = list(pand_vc)
        _snap = {
            "pandora_camp_mai26": camp_mai26,
            "pandora_vc_mai26":   vc_mai26,
            "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        with open(SNAP_FILE, "w", encoding="utf-8") as _sf:
            json.dump(_snap, _sf, ensure_ascii=False, indent=2)
        print("  → Snapshot mai/26 salvo pela primeira vez.")

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
        "catalogo_monthly":    clean_rows(cat_m),
        "catalogo_daily":      clean_rows(cat_d),
        "catalogo_campaigns":  clean_rows(cat_c),
        "seller_reputation":   clean_rows(rep),
        "visitas_monthly":     clean_rows(vis_m),
        "visitas_daily":       clean_rows(vis_d),
        "visitas_items":       clean_rows(vis_i),
        "bpc_aurora":          clean_rows(bpc),
        "campanhas":           clean_rows(camp),
        "pandora_items":        clean_rows(pand_items),
        "pandora_financeiro":   clean_rows(pand_fin),
        "pandora_vc":           pand_vc,
        "pandora_camp":         clean_rows(pand_camp),
        "pandora_camp_mai26":   camp_mai26,
        "pandora_vc_mai26":     vc_mai26,
        "seller_metas":        SELLER_METAS,
    }

# Metas dos sellers (extraidas do dashboard da carteira MeliPro)
# meta_op = meta operacional negociada (fonte de verdade para periodos abertos)
# meta_fin = plano financeiro anual
SELLER_METAS = {
    "COLIBRI": {
        "meta_op": {"2026-01":175311.6,"2026-02":150000.0,"2026-03":189095.94,"2026-04":187905.61,"2026-05":200000.0},
        "meta_fin": {"2026-01":175311.6,"2026-02":162810.71,"2026-03":189095.94,"2026-04":187905.61,
                     "2026-05":214669.13,"2026-06":234358.66,"2026-07":258771.3,"2026-08":250648.02,
                     "2026-09":273380.92,"2026-10":290507.99,"2026-11":296339.89,"2026-12":235826.08},
    },
    "KAPPESBERG": {
        "meta_op": {"2026-01":988706.85,"2026-02":1300000.0,"2026-03":1500000.0,"2026-04":1600000.0,"2026-05":1879000.0},
        "meta_fin": {"2026-01":988627.96,"2026-02":918132.15,"2026-03":1066361.44,"2026-04":1059648.87,
                     "2026-05":1210575.31,"2026-06":1321609.76,"2026-07":1459279.0,"2026-08":1413469.72,
                     "2026-09":1541666.47,"2026-10":1638250.49,"2026-11":1671138.11,"2026-12":1329884.94},
    },
    "LINEA": {
        "meta_op": {"2026-01":272680.95,"2026-02":200000.0,"2026-03":294121.21,"2026-04":250000.0,"2026-05":300000.0},
        "meta_fin": {"2026-01":272643.81,"2026-02":253202.48,"2026-03":294081.15,"2026-04":292229.96,
                     "2026-05":333852.45,"2026-06":364473.53,"2026-07":402439.95,"2026-08":389806.67,
                     "2026-09":425160.76,"2026-10":451796.71,"2026-11":460866.45,"2026-12":366755.66},
    },
    "Outlet das Fabricas": {
        "meta_op": {"2026-04":11000000.0,"2026-05":12500000.0},
        "meta_fin": {},
    },
    "Moveis Provincia": {
        "meta_op": {"2026-04":650000.0,"2026-05":1045732.0},
        "meta_fin": {},
    },
    "Decorise": {
        "meta_op": {"2026-04":500000.0,"2026-05":430998.0},
        "meta_fin": {},
    },
    "Casa Aberta": {
        "meta_op": {"2026-05":1369869.0},
        "meta_fin": {},
    },
    "Fidelita": {
        "meta_op": {"2026-05":464997.0},
        "meta_fin": {},
    },
    "Nesher": {
        "meta_op": {"2026-05":230000.0},
        "meta_fin": {},
    },
}

# Group name to SELLER_METAS key mapping
GROUP_META_MAP = {
    "COLIBRI":             "COLIBRI",
    "KAPPESBERG":          "KAPPESBERG",
    "LINEA":               "LINEA",
    "Outlet das Fabricas": "Outlet das Fabricas",
    "Moveis Provincia":    "Moveis Provincia",
    "Decorise":            "Decorise",
    "Casa Aberta":         "Casa Aberta",
    "Fidelitá":            "Fidelita",
    "Nesher":              "Nesher",
}


# ── HTML template ─────────────────────────────────────────────────────────────



HTML_TEMPLATE = """\



<!DOCTYPE html>



<html lang="pt-BR">



<head>



<meta charset="UTF-8">



<meta name="viewport" content="width=device-width,initial-scale=1">



<title>Gest\u00e3o MeliPro | Lucas Sanches</title>



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



.period-label{font-size:11px;font-weight:700;color:var(--muted);letter-spacing:.3px;margin-right:2px}



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
.log-type-section{margin-bottom:20px}
.log-type-header{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;padding-bottom:8px;border-bottom:2px solid;margin-bottom:10px}



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
.cat-filter-bar{align-items:center;gap:10px;padding:10px 14px;background:var(--card);border:1px solid var(--ml-blue);border-radius:8px;margin-bottom:14px}
.cat-filter-label{font-size:12px;font-weight:700;color:var(--ml-blue)}
.cat-filter-bar select{padding:5px 10px;border:1px solid var(--border);border-radius:6px;font-size:12px;background:#fff;outline:none;cursor:pointer;color:var(--text)}
.cat-filter-bar select:focus{border-color:var(--ml-blue)}



.section-title{font-size:13px;font-weight:700;color:var(--ml-blue);margin:16px 0 8px;display:flex;align-items:center;gap:8px}



.section-title::after{content:'';flex:1;height:1px;background:var(--border)}



table{width:100%;border-collapse:collapse}



thead tr{background:var(--ml-blue);color:#fff}



th{padding:9px 11px;text-align:right;font-size:11px;font-weight:600;letter-spacing:.3px;white-space:nowrap;cursor:pointer;user-select:none;position:relative}
th::after{content:'';display:inline-block;margin-left:4px;opacity:.35;font-size:9px;vertical-align:middle}
th[data-sort='asc']::after{content:'\25B2';opacity:1}
th[data-sort='desc']::after{content:'\25BC';opacity:1}
th:hover{opacity:.85}
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
.sc-asp{font-size:11px;color:var(--muted);margin-top:4px}
.sc-metrics{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-top:10px;border-top:1px solid var(--border);padding-top:8px}
.sc-metric{text-align:center}
.sc-metric-val{font-size:12px;font-weight:600;color:var(--txt)}
.sc-metric-lbl{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
</style>



</head>



<body>



<div class="header">



  <img class="logo" src="data:image/png;base64,__LOGO__" alt="Mercado Livre">



  <div><div class="header-title">Gest\u00e3o MeliPro | Lucas Sanches</div>



  <div class="header-sub">Vis\u00e3o 360\u00b0 da Carteira</div></div>



  <div class="updated" id="updated-at"></div>



</div>



<div class="layout">



  <nav class="sidebar" id="sidebar"></nav>



  <button class="sb-toggle" id="sb-toggle" onclick="toggleSidebar()" title="Ocultar/exibir carteira">&#9664;</button>



  <div class="main">



    <div class="period-bar">
      <span class="period-label">Per\u00edodo:</span>
      <div id="period-btns" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"></div>
    </div>
    <div class="main-tabs">



      <div class="tab active" onclick="setTab('geral',this)">Geral</div>



      <div class="tab" onclick="setTab('logistica',this)">Fulfillment &amp; Log\u00edstica</div>



      <div class="tab" onclick="setTab('ads',this)">ADS</div>



      <div class="tab" onclick="setTab('investimentos',this)">Investimentos</div>
      <div class="tab" onclick="setTab('pandora',this)">Pandora</div>



      <div class="tab" onclick="setTab('catalogo',this)">Cat\u00e1logo</div>
      <div class="tab" onclick="setTab('visitas',this)">Visitas &amp; Convers\u00e3o</div>
      <div class="tab" onclick="setTab('campanhas',this)">Campanhas</div>
      <div class="tab" onclick="setTab('bpc',this)">BPC</div>
      <div class="tab" onclick="setTab('aurora',this)">Plano Aurora</div>
    </div>
    <div class="main-content">



      <div class="tab-content active" id="tab-geral">
        <div id="period-badge-geral" class="period-badge"></div>
        <div class="cat-filter-bar" style="display:none">
          <span class="cat-filter-label">🏷️ Filtrar por Categoria:</span>
          <select id="cat-sel-geral" onchange="setCatFilter(this.value)">
            <option value="">Todas as categorias</option>
            <option value="FURNISHING &amp; HOUSEWARE">Furnishing &amp; Houseware</option>
          </select>
        </div>
        <div class="section-title">📊 Scorecard por Seller</div>
        <div class="scorecard-grid" id="scorecard-sellers"></div>
        <div class="kpi-grid" id="kpi-geral"></div>
        <div class="chart-grid">



          <div class="chart-card"><div class="chart-title">GMV (R$)</div><div class="chart-wrap"><canvas id="ch-gmv-mes"></canvas></div></div>



          <div class="chart-card"><div class="chart-title">Varia\u00e7\u00e3o GMV \u2014 MoM vs YoY (%)</div><div class="chart-wrap"><canvas id="ch-gmv-delta"></canvas></div></div>



          <div class="chart-card"><div class="chart-title">Unidades Vendidas (SI)</div><div class="chart-wrap"><canvas id="ch-si-mes"></canvas></div></div>



          <div class="chart-card"><div class="chart-title">ASP M\u00e9dio (R$)</div><div class="chart-wrap"><canvas id="ch-asp-mes"></canvas></div></div>



        </div>



        <div class="section-title">📋 Resumo por Seller</div>



        <div class="table-wrap"><table id="tbl-geral-sellers"></table></div>

        <div class="section-title" style="margin-top:28px">🏆 Atingimento de Metas por Mês</div>
        <div class="table-wrap"><table id="tbl-atingimento" style="width:100%;border-collapse:collapse"></table></div>



      </div>



      <div class="tab-content" id="tab-logistica">



        <div id="period-badge-log" class="period-badge"></div>



        <div id="kpi-log"></div>



        <div class="chart-grid">



          <div class="chart-card"><div class="chart-title">Mix Log\u00edstico \u2014 GMV (%)</div><div class="chart-wrap"><canvas id="ch-log-mix"></canvas></div></div>



          <div class="chart-card"><div class="chart-title">%FF por M\u00eas</div><div class="chart-wrap"><canvas id="ch-ff-mes"></canvas></div></div>



          <div class="chart-card"><div class="chart-title">GMV por Tipo Log\u00edstico</div><div class="chart-wrap"><canvas id="ch-log-gmv"></canvas></div></div>



          <div class="chart-card"><div class="chart-title">SI por Tipo Log\u00edstico</div><div class="chart-wrap"><canvas id="ch-log-si"></canvas></div></div>



        </div>



        <div class="section-title">📦 Detalhe por Seller</div>



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



        <div class="section-title">🎯 Detalhe por Seller</div>



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



        <div class="section-title">💰 Detalhe por Seller</div>



        <div class="table-wrap"><table id="tbl-inv-sellers"></table></div>



      </div>



      <div class="tab-content" id="tab-pandora">
        <div id="period-badge-pandora" class="period-badge"></div>
        <div class="kpi-grid" id="kpi-pandora"></div>
        <div class="section-title">🎯 Itens da Campanha P-MLB17513056</div>
        <div class="table-wrap"><table id="tbl-pandora-items"></table></div>
      </div>
      <div class="tab-content" id="tab-catalogo">
        <div id="period-badge-catalogo" class="period-badge"></div>
        <div class="cat-filter-bar" style="display:none">
          <span class="cat-filter-label">&#127991; Filtrar por Categoria:</span>
          <select id="cat-sel-catalogo" onchange="setCatFilter(this.value)">
            <option value="">Todas as categorias</option>
            <option value="FURNISHING &amp; HOUSEWARE">Furnishing &amp; Houseware</option>
          </select>
        </div>
        <div id="cat-summary-cards"></div>
        <div class="section-title">&#11088; Top It&ecirc;ns por Seller &mdash; Top 50 por GMV</div>
        <div class="table-wrap" style="overflow-x:auto"><table id="tbl-catalogo"></table></div>
      </div>
      <div class="tab-content" id="tab-visitas">
        <div id="period-badge-visitas" class="period-badge"></div>
        <div class="kpi-grid" id="kpi-visitas"></div>
        <div class="chart-grid">
          <div class="chart-card"><div class="chart-title">Visitas Mensais</div><div class="chart-wrap"><canvas id="ch-vis-mes"></canvas></div></div>
          <div class="chart-card"><div class="chart-title">Conversão (%)</div><div class="chart-wrap"><canvas id="ch-conv-mes"></canvas></div></div>
        </div>
        <div class="section-title">👁 Visitas por Seller</div>
        <div class="table-wrap"><table id="tbl-visitas-sellers"></table></div>
        <div class="section-title">🔥 Top Itêns por Visitas (90 dias)</div>
        <div class="table-wrap"><table id="tbl-visitas-items"></table></div>
      </div>
      <div class="tab-content" id="tab-campanhas">
        <div style="background:#FFF8E1;border:1px solid #F9A825;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px;color:#F57F17">
          <b>⚠️ Work in Progress</b> — Dados parciais. A query de campanhas está em ajuste para cobrir todos os sellers corretamente.
        </div>
        <div class="section-title">📋 Resumo por Seller</div>
        <div class="table-wrap"><table id="tbl-camp-sellers"></table></div>
        <div class="section-title">🎯 Campanhas por Item (últimos 2 dias)</div>
        <div class="table-wrap"><table id="tbl-camp-items"></table></div>
      </div>
      <div class="tab-content" id="tab-bpc">
        <div class="kpi-grid" id="kpi-bpc"></div>
        <div class="section-title">🏷️ BPC por Seller</div>
        <div class="table-wrap"><table id="tbl-bpc-sellers"></table></div>
        <div class="section-title">🔴 Itêns Não Competitivos (15 dias)</div>
        <div class="table-wrap"><table id="tbl-bpc-items"></table></div>
      </div>
      <div class="tab-content" id="tab-aurora">
        <div class="section-title">⚡ Classificação Aurora por Seller</div>
        <div class="table-wrap"><table id="tbl-aurora-sellers"></table></div>
        <div class="section-title">🔴 Itêns não competitivos</div>
        <div class="table-wrap"><table id="tbl-aurora-items"></table></div>
      </div>
    </div>
  </div>
</div>



<script>



const RAW = __DATA_PLACEHOLDER__;



const state = { period:'month', seller:'all', tab:'geral', customStart:null, customEnd:null, catFilter:null };



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








const MONTH_NAMES=['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];

function buildPeriodButtons(){
  var now=new Date(),yr=now.getFullYear(),mo=now.getMonth();
  var c=document.getElementById('period-btns');
  if(!c) return;
  c.innerHTML='';
  function btn(key,lbl){
    var b=document.createElement('button');
    b.className='btn'+(state.period===key?' active':'');
    b.textContent=lbl;
    b.onclick=(function(k){return function(){setPeriod(k);};})(key);
    c.appendChild(b);
  }
  function sep(){
    var s=document.createElement('span');
    s.textContent='|';
    s.style.cssText='color:#ccc;padding:0 6px;font-size:15px;align-self:center;line-height:1';
    c.appendChild(s);
  }
  btn('dia','Dia'); btn('semana','Semana'); btn('mtd','MTD'); btn('ytd','YTD');
  sep();
  btn('q1','Q1'); btn('q2','Q2');
  if(mo>=6) btn('q3','Q3');
  if(mo>=9) btn('q4','Q4');
  sep();
  for(var i=0;i<mo;i++) btn('m'+(i+1), MONTH_NAMES[i]);
}

function getPeriodConfig(){
  var now=new Date(),yr=now.getFullYear(),mo=now.getMonth(),p=state.period;
  var fD=function(d){return d.toISOString().slice(0,10);};
  var d1=fD(addDays(now,-1));
  if(p==='dia'){
    var d2=fD(addDays(now,-2)),pmDia=mo===0?[yr-1,11]:[yr,mo-1];
    return {type:'dia',gran:'daily',curr:[d1,d1],prev:[d2,d2],
      currM:[fmtMonth(yr,mo)],prevMoM:[fmtMonth(pmDia[0],pmDia[1])],prevYoY:[fmtMonth(yr-1,mo)],
      label:'Dia '+d1,prevLabel:'vs D-2',showD1:true,showD2:false,
      chartGran:'daily',chartStart:fD(addDays(now,-30)),chartEnd:d1};
  }
  if(p==='semana'){
    var dow=now.getDay(),dToSat=dow===6?7:(dow+1);
    var wEnd=addDays(now,-dToSat),wStart=addDays(wEnd,-6);
    var pwEnd=addDays(wStart,-1),pwStart=addDays(pwEnd,-6);
    var fw=function(d){return d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'});};
    var wMo=fmtMonth(wEnd.getFullYear(),wEnd.getMonth());
    var pmSem=wEnd.getMonth()===0?[wEnd.getFullYear()-1,11]:[wEnd.getFullYear(),wEnd.getMonth()-1];
    return {type:'semana',gran:'daily',curr:[fD(wStart),fD(wEnd)],prev:[fD(pwStart),fD(pwEnd)],
      currM:[wMo],prevMoM:[fmtMonth(pmSem[0],pmSem[1])],prevYoY:[fmtMonth(wEnd.getFullYear()-1,wEnd.getMonth())],
      label:'Sem '+fw(wStart)+'-'+fw(wEnd),prevLabel:'vs sem. ant.',showD1:true,showD2:false,
      chartGran:'daily',chartStart:fD(addDays(now,-28)),chartEnd:fD(addDays(now,-1))};
  }
  if(p==='mtd'){
    var mStart=yr+'-'+String(mo+1).padStart(2,'0')+'-01',pmMtd=mo===0?[yr-1,11]:[yr,mo-1];
    var diasP=now.getDate()-1;
    var pmY=pmMtd[0],pmM=pmMtd[1],pmStr=fmtMonth(pmY,pmM);
    var pmDIM=new Date(pmY,pmM+1,0).getDate(),pmEndDay=String(Math.min(diasP,pmDIM)).padStart(2,'0');
    var pyDIM=new Date(yr-1,mo+1,0).getDate();
    return {type:'mtd',gran:'monthly',curr:[fmtMonth(yr,mo)],
      prevMoM:[pmStr],prevYoY:[fmtMonth(yr-1,mo)],
      prevMoMDailyRange:[pmStr+'-01',pmStr+'-'+pmEndDay],
      prevYoYProrate:{months:[fmtMonth(yr-1,mo)],factor:diasP/pyDIM},
      diasPassados:diasP,
      label:'MTD',showD1:true,showD2:true,d1Label:'MoM',d2Label:'YoY',
      chartGran:'daily',chartStart:mStart,chartEnd:d1};
  }
  if(p==='ytd'){
    var ytdM=[],pyM=[];
    for(var yi=0;yi<=mo;yi++){ytdM.push(fmtMonth(yr,yi));pyM.push(fmtMonth(yr-1,yi));}
    return {type:'ytd',gran:'monthly',curr:ytdM,prevYoY:pyM,
      label:'YTD '+yr,showD1:false,showD2:true,d2Label:'YoY',
      chartGran:'monthly',chartMonths:ytdM};
  }
  if(p==='q1'){
    var q1m=[yr+'-01',yr+'-02',yr+'-03'],q1py=[(yr-1)+'-01',(yr-1)+'-02',(yr-1)+'-03'];
    var q4pq=[(yr-1)+'-10',(yr-1)+'-11',(yr-1)+'-12'];
    return {type:'q1',gran:'monthly',curr:q1m,prevYoY:q1py,prevQoQ:q4pq,
      label:'Q1 '+yr,showD1:true,showD2:true,d1Label:'QoQ',d2Label:'YoY',chartGran:'monthly',chartMonths:q1m};
  }
  if(p==='q2'){
    var capQ2=Math.min(mo,5),q2m=[];
    for(var qi2=3;qi2<=capQ2;qi2++) q2m.push(fmtMonth(yr,qi2));
    if(!q2m.length) q2m=[fmtMonth(yr,3)];
    var q2py=q2m.map(function(m){return fmtMonth(yr-1,parseInt(m.slice(5))-1);});
    var q1full=[yr+'-01',yr+'-02',yr+'-03'];
    var prevQoQ_q2=q1full.slice(0,q2m.length);
    return {type:'q2',gran:'monthly',curr:q2m,prevYoY:q2py,prevQoQ:prevQoQ_q2,
      label:'Q2 '+yr,showD1:true,showD2:true,d1Label:'QoQ',d2Label:'YoY',chartGran:'monthly',chartMonths:q2m};
  }
  if(p==='q3'){
    var capQ3=Math.min(mo,8),q3m=[];
    for(var qi3=6;qi3<=capQ3;qi3++) q3m.push(fmtMonth(yr,qi3));
    if(!q3m.length) q3m=[fmtMonth(yr,6)];
    var q3py=q3m.map(function(m){return fmtMonth(yr-1,parseInt(m.slice(5))-1);});
    return {type:'q3',gran:'monthly',curr:q3m,prevYoY:q3py,
      label:'Q3 '+yr,showD1:false,showD2:true,d2Label:'YoY',chartGran:'monthly',chartMonths:q3m};
  }
  if(p==='q4'){
    var capQ4=Math.min(mo,11),q4m=[];
    for(var qi4=9;qi4<=capQ4;qi4++) q4m.push(fmtMonth(yr,qi4));
    if(!q4m.length) q4m=[fmtMonth(yr,9)];
    var q4py=q4m.map(function(m){return fmtMonth(yr-1,parseInt(m.slice(5))-1);});
    return {type:'q4',gran:'monthly',curr:q4m,prevYoY:q4py,
      label:'Q4 '+yr,showD1:false,showD2:true,d2Label:'YoY',chartGran:'monthly',chartMonths:q4m};
  }
  var mMatch=p.match(/^m(\d+)$/);
  if(mMatch){
    var mNum=parseInt(mMatch[1])-1,mStr=fmtMonth(yr,mNum),pyStr=fmtMonth(yr-1,mNum);
    var pmMes=mNum===0?[yr-1,11]:[yr,mNum-1],pmStrM=fmtMonth(pmMes[0],pmMes[1]);
    var lastDayM=new Date(yr,mNum+1,0).getDate();
    var mChartEnd=mNum<mo?mStr+'-'+String(lastDayM).padStart(2,'0'):d1;
    var cfg={type:p,gran:'monthly',curr:[mStr],prevMoM:[pmStrM],prevYoY:[pyStr],
      label:MONTH_NAMES[mNum],showD1:true,showD2:true,d1Label:'MoM',d2Label:'YoY',
      chartGran:'daily',chartStart:mStr+'-01',chartEnd:mChartEnd};
    if(mNum===mo){
      var diasPM=now.getDate()-1,pyDIMm=new Date(yr-1,mNum+1,0).getDate();
      var pmDIMm=new Date(pmMes[0],pmMes[1]+1,0).getDate();
      var pmEndM=String(Math.min(diasPM,pmDIMm)).padStart(2,'0');
      cfg.prevMoMDailyRange=[pmStrM+'-01',pmStrM+'-'+pmEndM];
      cfg.prevYoYProrate={months:[pyStr],factor:diasPM>0?diasPM/pyDIMm:0};
      cfg.diasPassados=diasPM;
    }
    return cfg;
  }
  var mStartFb=yr+'-'+String(mo+1).padStart(2,'0')+'-01',pmFb=mo===0?[yr-1,11]:[yr,mo-1];
  var diasFb=now.getDate()-1,pmStrFb=fmtMonth(pmFb[0],pmFb[1]);
  var pmDIMfb=new Date(pmFb[0],pmFb[1]+1,0).getDate(),pmEndFb=String(Math.min(diasFb,pmDIMfb)).padStart(2,'0');
  var pyDIMfb=new Date(yr-1,mo+1,0).getDate();
  return {type:'mtd',gran:'monthly',curr:[fmtMonth(yr,mo)],
    prevMoM:[pmStrFb],prevYoY:[fmtMonth(yr-1,mo)],
    prevMoMDailyRange:[pmStrFb+'-01',pmStrFb+'-'+pmEndFb],
    prevYoYProrate:{months:[fmtMonth(yr-1,mo)],factor:diasFb>0?diasFb/pyDIMfb:0},
    diasPassados:diasFb,
    label:'MTD',showD1:true,showD2:true,d1Label:'MoM',d2Label:'YoY',
    chartGran:'daily',chartStart:mStartFb,chartEnd:d1};
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



function sumDailyRange(start,end,field,rows){



  const ids=sellerIds(state.seller);



  return (rows||RAW.geral_daily).filter(r=>ids.includes(String(r.cust_id))&&r.dia>=start&&r.dia<=end)



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
function sumDailyFromData(rows,start,end,field){
  var ids=sellerIds(state.seller);
  return (rows||[]).filter(function(r){return ids.includes(String(r.cust_id))&&r.dia>=start&&r.dia<=end;})
    .reduce(function(a,r){return a+(Number(r[field])||0);},0);
}
function aggBySellerDaily(rows,start,end,fields){
  var ids=sellerIds(state.seller),out={};
  (rows||[]).filter(function(r){return ids.includes(String(r.cust_id))&&r.dia>=start&&r.dia<=end;})
    .forEach(function(r){
      var k=String(r.cust_id);
      if(!out[k]){out[k]={};fields.forEach(function(f){out[k][f]=0;});}
      fields.forEach(function(f){out[k][f]+=(Number(r[f])||0);});
    });
  return out;
}
function computeKPI(pc,allM,field,dailyRows){



  let value,d1=null,d2=null;



  if(pc.gran==='daily'){



    value=sumDailyRange(pc.curr[0],pc.curr[1],field,dailyRows);



    if(pc.prev){const p=sumDailyRange(pc.prev[0],pc.prev[1],field,dailyRows);d1=p?((value-p)/p)*100:null;}



    if(pc.momM){const p=sumMeses(allM,pc.momM,field);d1=p?((value-p)/p)*100:null;}



    if(pc.yoyM){const p=sumMeses(allM,pc.yoyM,field);d2=p?((value-p)/p)*100:null;}



  } else {



    value=sumMeses(allM,pc.curr,field);
    if(dailyRows&&pc.prevMoMDailyRange&&pc.diasPassados>0){
      const p=sumDailyFromData(dailyRows,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],field);
      d1=p?((value-p)/p)*100:null;
    } else if(pc.prevMoM){const p=sumMeses(allM,pc.prevMoM,field);d1=p?((value-p)/p)*100:null;}
    else if(pc.prevQoQ){const p=sumMeses(allM,pc.prevQoQ,field);d1=p?((value-p)/p)*100:null;}
    if(pc.prevYoYProrate&&pc.diasPassados>0){
      const py=sumMeses(allM,pc.prevYoYProrate.months,field)*pc.prevYoYProrate.factor;
      d2=py?((value-py)/py)*100:null;
    } else if(pc.prevYoY){const p=sumMeses(allM,pc.prevYoY,field);d2=p?((value-p)/p)*100:null;}



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







// ── Filtro de categoria (Outlet das Fábricas) ────────────────────────────────
var OUTLET_GROUP='Outlet das Fábricas';
function isOutletView(){
  if(state.seller===OUTLET_GROUP)return true;
  var s=(RAW.sellers||[]).find(function(x){return String(x.cust_id)===String(state.seller);});
  return !!(s&&s.group===OUTLET_GROUP);
}
function catRows(rows){
  if(!state.catFilter)return rows;
  return(rows||[]).filter(function(r){return r.vertical===state.catFilter;});
}
function updateCatFilterBar(){
  var show=isOutletView();
  document.querySelectorAll('.cat-filter-bar').forEach(function(bar){
    bar.style.display=show?'flex':'none';
    bar.querySelectorAll('select').forEach(function(sel){
      sel.value=state.catFilter||'';
    });
  });
}
function setCatFilter(val){state.catFilter=(val&&val.length)?val:null;renderAll();}

function renderGeral(){
  renderScorecard();
  renderAtingimento();
  updateCatFilterBar();
  var pc=getPeriodConfig();
  var gM=catRows(RAW.geral_monthly),gD=catRows(RAW.geral_daily);
  var allM=aggAllMonths(gM,['gmv','si']);
  setBadge('period-badge-geral',pc);
  var gmv=computeKPI(pc,allM,'gmv',gD),si=computeKPI(pc,allM,'si',gD);
  var aspVal=si.value?gmv.value/si.value:0;
  var aspD1=null,aspD2=null;
  if(pc.gran==='daily'){
    if(pc.prev){var gprev=sumDailyRange(pc.prev[0],pc.prev[1],'gmv',gD),siprev=sumDailyRange(pc.prev[0],pc.prev[1],'si',gD);var ap=siprev?gprev/siprev:null;aspD1=(ap&&aspVal)?((aspVal-ap)/ap)*100:null;}
  } else {
    var ap1,ay1;
    if(pc.prevMoMDailyRange&&pc.diasPassados>0){
      var gP=sumDailyFromData(gD,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],'gmv');
      var sP=sumDailyFromData(gD,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],'si');
      ap1=sP?gP/sP:null;
    } else {
      ap1=pc.prevMoM?(function(){var g=sumMeses(allM,pc.prevMoM,'gmv'),s=sumMeses(allM,pc.prevMoM,'si');return s?g/s:null;})():pc.prevQoQ?(function(){var g=sumMeses(allM,pc.prevQoQ,'gmv'),s=sumMeses(allM,pc.prevQoQ,'si');return s?g/s:null;})():null;
    }
    if(pc.prevYoYProrate&&pc.diasPassados>0){
      var gY=sumMeses(allM,pc.prevYoYProrate.months,'gmv')*pc.prevYoYProrate.factor;
      var sY=sumMeses(allM,pc.prevYoYProrate.months,'si')*pc.prevYoYProrate.factor;
      ay1=sY?gY/sY:null;
    } else {
      ay1=pc.prevYoY?(function(){var g=sumMeses(allM,pc.prevYoY,'gmv'),s=sumMeses(allM,pc.prevYoY,'si');return s?g/s:null;})():null;
    }
    aspD1=ap1?((aspVal-ap1)/ap1)*100:null;aspD2=ay1?((aspVal-ay1)/ay1)*100:null;
  }
  document.getElementById('kpi-geral').innerHTML=
    kpiCard('GMV',fmtBRL(gmv.value),pc,gmv.d1,gmv.d2)+
    kpiCard('SI (Unidades)',fmtNum(si.value),pc,si.d1,si.d2)+
    kpiCard('ASP',fmtBRL(aspVal),pc,aspD1,aspD2);

  // CHARTS: daily for day/week/month, monthly for quarter/year
  if(pc.chartGran==='daily'){
    var s=pc.chartStart,e=pc.chartEnd;
    var gmvC=aggDailyChart(gD,'gmv',s,e);
    var siC =aggDailyChart(gD,'si',s,e);
    makeChart('ch-gmv-mes','bar',gmvC.labels,[{label:'GMV',data:gmvC.data,backgroundColor:'#3483FA',borderRadius:3}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-si-mes','bar',siC.labels,[{label:'SI',data:siC.data,backgroundColor:'#00A650',borderRadius:3}]);
    var aspC=aggDailyChartMulti(gD,['gmv','si'],s,e);
    makeChart('ch-asp-mes','line',aspC.labels,[{label:'ASP',data:aspC.labels.map(function(d){var g=aspC.byField[d]?.gmv||0,si=aspC.byField[d]?.si||0;return si?+(g/si).toFixed(0):null;}),borderColor:'#FF7733',backgroundColor:'#FF773322',fill:true,tension:.3,pointRadius:2}],{yFmt:v=>'R$'+v?.toLocaleString('pt-BR',{maximumFractionDigits:0})});
  } else {
    var cM=pc.chartMonths||pc.curr;
    makeChart('ch-gmv-mes','bar',cM,[{label:'GMV',data:cM.map(function(m){return allM[m]?.gmv||0;}),backgroundColor:'#3483FA',borderRadius:4}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-si-mes','bar',cM,[{label:'SI',data:cM.map(function(m){return allM[m]?.si||0;}),backgroundColor:'#00A650',borderRadius:4}]);
    makeChart('ch-asp-mes','line',cM,[{label:'ASP',data:cM.map(function(m){var g=allM[m]?.gmv||0,s=allM[m]?.si||0;return s?+(g/s).toFixed(0):null;}),borderColor:'#FF7733',backgroundColor:'#FF773322',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>'R$'+v?.toLocaleString('pt-BR',{maximumFractionDigits:0})});
  }

  // Delta MoM/YoY chart: always last 12 months monthly
  var allM2=aggAllMonths(gM,['gmv','si']),allM2k=Object.keys(allM2).sort();
  var last12=allM2k.slice(-12);
  var momArr=last12.map(function(m){var p=allM2k[allM2k.indexOf(m)-1];if(!p)return null;var l=allM2[m]?.gmv||0,pv=allM2[p]?.gmv||0;return pv?+((l-pv)/pv*100).toFixed(1):null;});
  var yoyArr=last12.map(function(m){var yy=allM2k.find(function(x){return x.slice(0,4)===String(parseInt(m.slice(0,4))-1)&&x.slice(5)===m.slice(5);});if(!yy)return null;var l=allM2[m]?.gmv||0,y=allM2[yy]?.gmv||0;return y?+((l-y)/y*100).toFixed(1):null;});
  makeChart('ch-gmv-delta','line',last12,[
    {label:'MoM%',data:momArr,borderColor:'#3483FA',backgroundColor:'#3483FA22',fill:true,tension:.3,pointRadius:2},
    {label:'YoY%',data:yoyArr,borderColor:'#E83C49',backgroundColor:'#E83C4922',fill:true,tension:.3,pointRadius:2}
  ],{yFmt:v=>v?.toFixed(1)+'%'});

  // Seller table — unified ranking
  var mT=pc.gran==='daily'?null:(pc.curr||[]);
  var byS=pc.gran==='daily'?(function(){
    var ids=sellerIds(state.seller),out={};
    gD.filter(function(r){return ids.includes(String(r.cust_id))&&r.dia>=pc.curr[0]&&r.dia<=pc.curr[1];}).forEach(function(r){
      var k=String(r.cust_id);if(!out[k]){out[k]={gmv:0,si:0};}
      out[k].gmv+=(Number(r.gmv)||0);out[k].si+=(Number(r.si)||0);
    });return out;
  })():aggBySeller(gM,mT,['gmv','si']);
  var byPrevM,byPrevY;
  if(pc.gran!=='daily'&&pc.prevMoMDailyRange&&pc.diasPassados>0){
    byPrevM=aggBySellerDaily(gD,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],['gmv']);
  } else if(pc.gran!=='daily'&&pc.prevMoM){byPrevM=aggBySeller(gM,pc.prevMoM,['gmv']);}
  else if(pc.gran!=='daily'&&pc.prevQoQ){byPrevM=aggBySeller(gM,pc.prevQoQ,['gmv']);}
  else{byPrevM={};}
  if(pc.gran!=='daily'&&pc.prevYoYProrate&&pc.diasPassados>0){
    var byYFull=aggBySeller(gM,pc.prevYoYProrate.months,['gmv']);
    byPrevY={};Object.entries(byYFull).forEach(function([k,v]){byPrevY[k]={gmv:(v.gmv||0)*pc.prevYoYProrate.factor};});
  } else if(pc.gran!=='daily'&&pc.prevYoY){byPrevY=aggBySeller(gM,pc.prevYoY,['gmv']);}
  else{byPrevY={};}
  var tG=Object.values(byS).reduce(function(a,v){return a+(v.gmv||0);},0);
  var thS='padding:9px 10px;font-size:11px;font-weight:700;background:var(--ml-blue);color:#fff;';
  var h='<thead><tr>'
    +'<th style="'+thS+'text-align:left;min-width:140px;border-radius:6px 0 0 0">Seller</th>'
    +'<th style="'+thS+'text-align:right;min-width:110px">GMV</th>'
    +'<th style="'+thS+'text-align:center;min-width:70px">MoM%</th>'
    +'<th style="'+thS+'text-align:center;min-width:70px">YoY%</th>'
    +'<th style="'+thS+'text-align:right;min-width:110px">Meta Op.</th>'
    +'<th style="'+thS+'text-align:center;min-width:70px">% Meta</th>'
    +'<th style="'+thS+'text-align:right;min-width:100px">Projeção</th>'
    +'<th style="'+thS+'text-align:right;min-width:70px">SI</th>'
    +'<th style="'+thS+'text-align:right;min-width:80px">ASP</th>'
    +'<th style="'+thS+'text-align:center;min-width:65px;border-radius:0 6px 0 0">Share</th>'
    +'</tr></thead><tbody>';
  var SMETAS=RAW.seller_metas||{};
  var GROUP_META={'COLIBRI':'COLIBRI','KAPPESBERG':'KAPPESBERG','LINEA':'LINEA',
    'Outlet das Fábricas':'Outlet das Fabricas',
    'Móveis Província':'Moveis Provincia',
    'Decorise':'Decorise',
    'Casa Aberta':'Casa Aberta',
    'Fidelitá':'Fidelita',
    'Nesher':'Nesher'};
  function getMetaForPeriod(groupName,meses){
    var mk=GROUP_META[groupName];
    if(!mk||!SMETAS[mk]) return 0;
    var mop=SMETAS[mk].meta_op||{};
    var mfin=SMETAS[mk].meta_fin||{};
    return (meses||[]).reduce(function(acc,m){var v=mop[m]||mfin[m]||0;return acc+v;},0);
  }
  function metaClass(pct){
    if(!pct) return 'dn0';
    if(pct>=100) return 'tag-pos';
    if(pct>=80) return 'dp';
    return 'tag-neg';
  }
  function deltaCell(pct){
    var td='<td style="text-align:center;font-size:12px;font-weight:600;padding:7px 8px;border-bottom:1px solid var(--border);';
    if(pct===null) return td+'color:var(--muted)">—</td>';
    var c=pct>=0?'var(--green)':'var(--red)',arr=pct>=0?'▲':'▼';
    return td+'color:'+c+'">'+arr+' '+Math.abs(pct).toFixed(1)+'%</td>';
  }
  // Fator de projeção — só faz sentido no MTD
  var _now=new Date();
  var _diasMes=new Date(_now.getFullYear(),_now.getMonth()+1,0).getDate();
  var _diasP=pc.diasPassados||(_now.getDate()-1);
  var fatorProjSel=(pc.type==='mtd'&&_diasP>0)?_diasMes/_diasP:null;

  var entries=Object.entries(byS).sort(function(a,b){return b[1].gmv-a[1].gmv;});
  entries.forEach(function([cid,v],ri){
    var asp=v.si?v.gmv/v.si:0,share=tG?(v.gmv/tG)*100:0;
    var selGroup=(RAW.sellers||[]).find(function(s){return String(s.cust_id)===String(cid);});
    var sg=selGroup?selGroup.group:'';
    var metaV=getMetaForPeriod(sg,mT||[]);
    var metaPct=metaV&&v.gmv?+(v.gmv/metaV*100).toFixed(1):null;
    var pMom=(byPrevM[cid]?.gmv)||0;
    var momPct=pMom?+((v.gmv-pMom)/pMom*100).toFixed(1):null;
    var pYoy=(byPrevY[cid]?.gmv)||0;
    var yoyPct=pYoy?+((v.gmv-pYoy)/pYoy*100).toFixed(1):null;
    var projV=fatorProjSel?v.gmv*fatorProjSel:null;
    var projPct=projV&&metaV?+(projV/metaV*100).toFixed(1):null;
    var projHtml=projV
      ?fmtBRL(projV)+(projPct!=null?' <span class="'+metaClass(projPct)+'" style="font-size:10px">'+projPct+'%</span>':'')
      :'—';
    var bg=ri%2===0?'var(--card)':'#f7f8fa';
    var td='border-bottom:1px solid var(--border);padding:7px 8px;font-size:12px;';
    h+='<tr style="background:'+bg+'">'
      +'<td style="'+td+'font-weight:600;color:var(--ml-blue);text-align:left">'+sellerLabel(cid)+'</td>'
      +'<td style="'+td+'font-weight:700;text-align:right">'+fmtBRL(v.gmv)+'</td>'
      +deltaCell(momPct)+deltaCell(yoyPct)
      +'<td style="'+td+'text-align:right;color:var(--muted)">'+(metaV?fmtBRL(metaV):'—')+'</td>'
      +'<td style="'+td+'text-align:center">'+(metaPct!=null?'<span class="'+metaClass(metaPct)+'">'+metaPct+'%</span>':'—')+'</td>'
      +'<td style="'+td+'text-align:right">'+projHtml+'</td>'
      +'<td style="'+td+'text-align:right;color:var(--muted)">'+fmtNum(v.si)+'</td>'
      +'<td style="'+td+'text-align:right;color:var(--muted)">'+fmtBRL(asp)+'</td>'
      +'<td style="'+td+'text-align:center"><span class="badge">'+fmtPct(share)+'</span></td>'
      +'</tr>';
  });
  document.getElementById('tbl-geral-sellers').innerHTML=h+'</tbody>';
}
function renderLogistica(){
  var pc=getPeriodConfig();
  var allM=aggAllMonths(RAW.logistica_monthly,['gmv_total','si_total','gmv_ff','si_ff','gmv_xd','si_xd','gmv_ss','si_ss']);
  setBadge('period-badge-log',pc);
  var meses=pc.gran==='daily'?(pc.currM||[]):(pc.curr||[]);
  var LFIELDS=['gmv_total','si_total','gmv_ff','si_ff','gmv_xd','si_xd','gmv_ss','si_ss'];
  var lCurr={},lPrev={},_dl=RAW.logistica_daily;
  if(pc.gran==='daily'){
    var _s=pc.curr[0],_e=pc.curr[1];
    LFIELDS.forEach(function(f){lCurr[f]=sumDailyFromData(_dl,_s,_e,f)||0;});
    if(pc.prev){LFIELDS.forEach(function(f){lPrev[f]=sumDailyFromData(_dl,pc.prev[0],pc.prev[1],f)||0;});}  
    else if(pc.momM){LFIELDS.forEach(function(f){lPrev[f]=sumMeses(allM,pc.momM,f)||0;});}
  } else {
    LFIELDS.forEach(function(f){lCurr[f]=sumMeses(allM,pc.curr,f)||0;});
    if(pc.prevMoMDailyRange&&pc.diasPassados>0&&_dl){LFIELDS.forEach(function(f){lPrev[f]=sumDailyFromData(_dl,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],f)||0;});}
    else if(pc.prevMoM){LFIELDS.forEach(function(f){lPrev[f]=sumMeses(allM,pc.prevMoM,f)||0;});}
    else if(pc.prevQoQ){LFIELDS.forEach(function(f){lPrev[f]=sumMeses(allM,pc.prevQoQ,f)||0;});}
  }
  var _lbl=pc.d1Label||'MoM';
  function _pD(v){if(v==null)return '<span class="dn0">—</span>';var c=v>=0?'dp':'dn',a=v>=0?'▲':'▼';return '<span class="'+c+'">'+_lbl+' '+a+Math.abs(v).toFixed(1)+'%</span>';}
  function _ppD(v){if(v==null)return '<span class="dn0">—</span>';var c=v>=0?'dp':'dn',a=v>=0?'▲':'▼';return '<span class="'+c+'">'+_lbl+' '+a+Math.abs(v).toFixed(1)+'pp</span>';}
  function _typeSection(type,label,color){
    var cG=lCurr['gmv_'+type]||0,pG=lPrev['gmv_'+type]||0;
    var cS=lCurr['si_'+type]||0,pS=lPrev['si_'+type]||0;
    var cT=lCurr.gmv_total||1,pT=lPrev.gmv_total||1;
    var asp=cS?cG/cS:null,aspP=pS?pG/pS:null;
    var share=cG/cT*100,shareP=pG/pT*100;
    var dG=pG?(cG-pG)/pG*100:null;
    var dS=pS?(cS-pS)/pS*100:null;
    var dA=aspP&&asp!=null?(asp-aspP)/aspP*100:null;
    var dSh=pT>0?share-shareP:null;
    return '<div class="log-type-section">'
      +'<div class="log-type-header" style="color:'+color+';border-color:'+color+'">'+label+'</div>'
      +'<div class="kpi-grid">'
      +'<div class="kpi-card"><div class="kpi-label">GMV</div><div class="kpi-value">'+fmtBRL(cG)+'</div><div class="kpi-delta">'+_pD(dG)+'</div></div>'
      +'<div class="kpi-card"><div class="kpi-label">SI</div><div class="kpi-value">'+fmtNum(Math.round(cS))+'</div><div class="kpi-delta">'+_pD(dS)+'</div></div>'
      +'<div class="kpi-card"><div class="kpi-label">ASP</div><div class="kpi-value">'+(asp!=null?fmtBRL(asp):'-')+'</div><div class="kpi-delta">'+_pD(dA)+'</div></div>'
      +'<div class="kpi-card"><div class="kpi-label">% Share GMV</div><div class="kpi-value">'+fmtPct(share)+'</div><div class="kpi-delta">'+_ppD(dSh)+'</div></div>'
      +'</div></div>';
  }
  document.getElementById('kpi-log').innerHTML=
    _typeSection('ss','Self Service','#00A650')+
    _typeSection('xd','Cross Docking','#FFB800')+
    _typeSection('ff','Fulfillment','#3483FA');
  var ffP=(lCurr.gmv_ff||0)/(lCurr.gmv_total||1)*100;
  var xdP=(lCurr.gmv_xd||0)/(lCurr.gmv_total||1)*100;
  var ssP=(lCurr.gmv_ss||0)/(lCurr.gmv_total||1)*100;

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

  var bySL=pc.gran==='daily'?aggBySellerDaily(RAW.logistica_daily,pc.curr[0],pc.curr[1],['gmv_total','gmv_ff','gmv_xd','gmv_ss']):aggBySeller(RAW.logistica_monthly,meses,['gmv_total','gmv_ff','gmv_xd','gmv_ss','si_total','si_ff']);
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

  var invV,gmvAdsV,totalGmvV;
  if(pc.gran==='daily'){invV=sumDailyFromData(RAW.ads_daily,pc.curr[0],pc.curr[1],'ads_invest');gmvAdsV=sumDailyFromData(RAW.ads_daily,pc.curr[0],pc.curr[1],'gmv_ads');totalGmvV=sumDailyFromData(RAW.geral_daily,pc.curr[0],pc.curr[1],'gmv');}
  else{invV=sumMeses(allAds,meses,'ads_invest');gmvAdsV=sumMeses(allAds,meses,'gmv_ads');totalGmvV=sumMeses(allGmv,meses,'gmv');}
  var roas=invV?+(gmvAdsV/invV).toFixed(2):0,acos=gmvAdsV?+(invV/gmvAdsV*100).toFixed(2):0,adsgmv=totalGmvV?+(gmvAdsV/totalGmvV*100).toFixed(2):0;
  var lastM=meses[meses.length-1]||'',prevMTR=allAdsK[allAdsK.indexOf(lastM)-1];
  var takeRate=pc.gran!=='daily'&&prevMTR&&allGmv[prevMTR]?.gmv?+(invV/allGmv[prevMTR].gmv*100).toFixed(2):null;

  var invK=pc.gran==='daily'?{value:invV,d1:null,d2:null}:computeKPI(pc,allAds,'ads_invest',RAW.ads_daily);
  var gmvAdsK=pc.gran==='daily'?{value:gmvAdsV,d1:null,d2:null}:computeKPI(pc,allAds,'gmv_ads',RAW.ads_daily);
  function calcMetrics(ms){var inv=sumMeses(allAds,ms,'ads_invest'),g=sumMeses(allAds,ms,'gmv_ads'),tg=sumMeses(allGmv,ms,'gmv');var lm=ms[ms.length-1]||'',pt=allAdsK[allAdsK.indexOf(lm)-1];return{roas:inv?g/inv:0,acos:g?inv/g*100:0,adsgmv:tg?g/tg*100:0,takeRate:pt&&allGmv[pt]?.gmv?inv/allGmv[pt].gmv*100:null};}
  var momMet=null,yoyMet=null;
  if(pc.gran!=='daily'){
    if(pc.prevMoMDailyRange&&pc.diasPassados>0){
      var mInv=sumDailyFromData(RAW.ads_daily,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],'ads_invest');
      var mGmvA=sumDailyFromData(RAW.ads_daily,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],'gmv_ads');
      var mGmvT=sumDailyFromData(RAW.geral_daily,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],'gmv');
      momMet={roas:mInv?mGmvA/mInv:0,acos:mGmvA?mInv/mGmvA*100:0,adsgmv:mGmvT?mGmvA/mGmvT*100:0,takeRate:null};
    } else if(pc.prevMoM||pc.prevQoQ){momMet=calcMetrics(pc.prevMoM||pc.prevQoQ);}
    if(pc.prevYoYProrate&&pc.diasPassados>0){
      var pyM=pc.prevYoYProrate.months,f=pc.prevYoYProrate.factor;
      var yInv=sumMeses(allAds,pyM,'ads_invest')*f,yGmvA=sumMeses(allAds,pyM,'gmv_ads')*f,yGmvT=sumMeses(allGmv,pyM,'gmv')*f;
      yoyMet={roas:yInv?yGmvA/yInv:0,acos:yGmvA?yInv/yGmvA*100:0,adsgmv:yGmvT?yGmvA/yGmvT*100:0,takeRate:null};
    } else if(pc.prevYoY){yoyMet=calcMetrics(pc.prevYoY);}
  }
  function ppCard(label,value,fmtFn,mV,yV,lowerBetter,unit){
    var u=unit||'pp';var decimals=u==='x'?2:1;
    var lm=pc.d1Label||'MoM',ly='YoY';
    var dh='';
    if(mV!=null){var d=+(value-(mV||0)).toFixed(decimals),good=lowerBetter?d<0:d>0;dh+='<span class="'+(good?'dp':'dn')+'">'+lm+': '+(d>0?'\u25b2':'\u25bc')+Math.abs(d).toFixed(decimals)+u+'</span> ';}
    if(yV!=null){var d2=+(value-(yV||0)).toFixed(decimals),good2=lowerBetter?d2<0:d2>0;dh+='<span class="'+(good2?'dp':'dn')+'">'+ly+': '+(d2>0?'\u25b2':'\u25bc')+Math.abs(d2).toFixed(decimals)+u+'</span>';}
    if(!dh)dh='<span class="dn0">\u2014</span>';
    return '<div class="kpi-card"><div class="kpi-label">'+label+'</div><div class="kpi-value">'+fmtFn(value)+'</div><div class="kpi-delta">'+dh+'</div></div>';
  }
  document.getElementById('kpi-ads').innerHTML=
    kpiCard('Investimento ADS',fmtBRL(invV),pc,invK.d1,invK.d2)+
    kpiCard('GMV via ADS',fmtBRL(gmvAdsV),pc,gmvAdsK.d1,gmvAdsK.d2)+
    ppCard('ROAS',roas,fmtDec,momMet?momMet.roas:null,yoyMet?yoyMet.roas:null,false,'x')+
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
  var bySA=pc.gran==='daily'?aggBySellerDaily(RAW.ads_daily,pc.curr[0],pc.curr[1],['ads_invest','gmv_ads','clicks']):aggBySeller(RAW.ads_monthly,meses,['ads_invest','gmv_ads','clicks']);
  var bySG=pc.gran==='daily'?aggBySellerDaily(RAW.geral_daily,pc.curr[0],pc.curr[1],['gmv']):aggBySeller(RAW.geral_monthly,meses,['gmv']);
  var bySGprev=pc.gran!=='daily'&&prevMTR?aggBySeller(RAW.geral_monthly,[prevMTR],['gmv']):{};
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
  var INV_FIELDS=['pre_acordo','dod','relampago','sad','automaticas','pm_cofin','pm_100','pix','cupom_comercial','cupom_marketing'];
  var allM=aggAllMonths(RAW.investimentos_monthly,INV_FIELDS);
  setBadge('period-badge-inv',pc);
  var meses=pc.gran==='daily'?(pc.currM||[]):(pc.curr||[]);
  function _sd(f){return sumDailyFromData(RAW.investimentos_daily,pc.curr[0],pc.curr[1],f);}
  function _sm(f){return sumMeses(allM,meses,f);}
  var isD=pc.gran==='daily';
  var vPA=isD?_sd('pre_acordo'):_sm('pre_acordo');
  var vDod=isD?_sd('dod'):_sm('dod');
  var vRel=isD?_sd('relampago'):_sm('relampago');
  var vSad=isD?_sd('sad'):_sm('sad');
  var vAut=isD?_sd('automaticas'):_sm('automaticas');
  var vPMc=isD?_sd('pm_cofin'):_sm('pm_cofin');
  var vPM1=isD?_sd('pm_100'):_sm('pm_100');
  var vPix=isD?_sd('pix'):_sm('pix');
  var vCpC=isD?_sd('cupom_comercial'):_sm('cupom_comercial');
  var vCpM=isD?_sd('cupom_marketing'):_sm('cupom_marketing');
  var gPre=vPA+vDod+vRel;
  var gCupons=vCpC+vCpM;
  var gOutras=vSad+vAut+vPMc+vPM1+vPix;
  var invTotal=gPre+gOutras+gCupons;
  // MoM prev values \u2014 MTD usa di\u00e1rio, m\u00eas fechado usa mensal, semana/dia sem MoM
  var hasMoM=false,pvPA=0,pvDod=0,pvRel=0,pvSad=0,pvAut=0,pvPMc=0,pvPM1=0,pvPix=0,pvCpC=0,pvCpM=0;
  if(!isD){
    var _getP=null;
    if(pc.prevMoMDailyRange&&pc.diasPassados>0){
      hasMoM=true;
      _getP=function(f){return sumDailyFromData(RAW.investimentos_daily,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],f);};
    } else if(pc.prevMoM){
      hasMoM=true;
      _getP=function(f){return sumMeses(allM,pc.prevMoM,f);};
    } else if(pc.prevQoQ){
      hasMoM=true;
      _getP=function(f){return sumMeses(allM,pc.prevQoQ,f);};
    }
    if(_getP){
      pvPA=_getP('pre_acordo'); pvDod=_getP('dod'); pvRel=_getP('relampago');
      pvSad=_getP('sad'); pvAut=_getP('automaticas'); pvPMc=_getP('pm_cofin');
      pvPM1=_getP('pm_100'); pvPix=_getP('pix'); pvCpC=_getP('cupom_comercial'); pvCpM=_getP('cupom_marketing');
    }
  }
  var pvGPre=pvPA+pvDod+pvRel,pvGCupons=pvCpC+pvCpM,pvGOutras=pvSad+pvAut+pvPMc+pvPM1+pvPix;
  var pvTotal=pvGPre+pvGOutras+pvGCupons;

  function _momBadge(curr,prev){
    var lbl=pc.d1Label||'MoM';
    if(!hasMoM)return'<span class="dn0">\u2014</span>';
    if(!prev)return'<span class="dn0">\u2014 '+lbl+'</span>';
    var d=(curr-prev)/prev*100;
    if(!isFinite(d))return'<span class="dn0">\u2014 '+lbl+'</span>';
    var cls=d>=0?'tag-pos':'tag-neg',sign=d>=0?'+':'';
    return'<span class="'+cls+'">'+sign+d.toFixed(1)+'% '+lbl+'</span>';
  }
  function _kpi(lbl,val,prev,sub){
    return'<div class="kpi-card">'
      +'<div class="kpi-label">'+lbl+'</div>'
      +'<div class="kpi-value">'+fmtBRL(val)+'</div>'
      +'<div class="kpi-delta">'+_momBadge(val,prev)+'</div>'
      +'<div class="kpi-delta"><span class="dn0">'+sub+'</span></div>'
      +'</div>';
  }
  document.getElementById('kpi-inv').innerHTML=
    _kpi('Total Investido',invTotal,pvTotal,'\u2014')+
    _kpi('Pr\u00e9-Acordo',gPre,pvGPre,'Pr\u00e9 Ac. + DoD + Rel\u00e2mpago')+
    _kpi('SAD',vSad,pvSad,'Smart / Aut. Digital')+
    _kpi('Autom\u00e1ticas',vAut,pvAut,'Campanha Autom\u00e1tica')+
    _kpi('PM Cofin.',vPMc,pvPMc,'Price Matching Cofin.')+
    _kpi('PM 100%',vPM1,pvPM1,'Price Matching 100% Meli')+
    _kpi('PIX',vPix,pvPix,'Desconto PIX')+
    _kpi('Cupom Comercial',vCpC,pvCpC,'Cupons n\u00e3o-Marketing')+
    _kpi('Cupom Marketing',vCpM,pvCpM,'Cupons Marketing');
  var cM=pc.chartMonths||pc.curr;
  if(pc.chartGran==='daily'){
    var s=pc.chartStart,e=pc.chartEnd;
    var invMC=aggDailyChartMulti(RAW.investimentos_daily,INV_FIELDS,s,e);
    function _bf(d,f){var row=invMC.byField[d];return (row&&row[f])||0;}
    makeChart('ch-inv-total','bar',invMC.labels,[
      {label:'Cupons',data:invMC.labels.map(function(d){return _bf(d,'cupom_comercial')+_bf(d,'cupom_marketing');}),backgroundColor:'#FFE600',borderRadius:2},
      {label:'Rebate Pr\u00e9',data:invMC.labels.map(function(d){return _bf(d,'pre_acordo')+_bf(d,'dod')+_bf(d,'relampago');}),backgroundColor:'#3483FA',borderRadius:2},
      {label:'Rebate Outras',data:invMC.labels.map(function(d){return _bf(d,'sad')+_bf(d,'automaticas')+_bf(d,'pm_cofin')+_bf(d,'pm_100')+_bf(d,'pix');}),backgroundColor:'#00A650',borderRadius:2}
    ],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:'#F0F0F0'}}}}});
    makeChart('ch-cupons','line',invMC.labels,[{label:'Cupons',data:invMC.labels.map(function(d){return _bf(d,'cupom_comercial')+_bf(d,'cupom_marketing');}),borderColor:'#E67E22',backgroundColor:'#E67E2222',fill:true,tension:.3,pointRadius:2}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-rebates','line',invMC.labels,[
      {label:'Pr\u00e9-neg.',data:invMC.labels.map(function(d){return _bf(d,'pre_acordo')+_bf(d,'dod')+_bf(d,'relampago');}),borderColor:'#3483FA',fill:false,tension:.3,pointRadius:2},
      {label:'Outras',data:invMC.labels.map(function(d){return _bf(d,'sad')+_bf(d,'automaticas')+_bf(d,'pm_cofin')+_bf(d,'pm_100')+_bf(d,'pix');}),borderColor:'#00A650',fill:false,tension:.3,pointRadius:2}
    ],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
  } else {
    makeChart('ch-inv-total','bar',cM,[
      {label:'Cupons',data:cM.map(function(m){return (allM[m]?.cupom_comercial||0)+(allM[m]?.cupom_marketing||0);}),backgroundColor:'#FFE600',borderRadius:3},
      {label:'Rebate Pr\u00e9',data:cM.map(function(m){return (allM[m]?.pre_acordo||0)+(allM[m]?.dod||0)+(allM[m]?.relampago||0);}),backgroundColor:'#3483FA',borderRadius:3},
      {label:'Rebate Outras',data:cM.map(function(m){return (allM[m]?.sad||0)+(allM[m]?.automaticas||0)+(allM[m]?.pm_cofin||0)+(allM[m]?.pm_100||0)+(allM[m]?.pix||0);}),backgroundColor:'#00A650',borderRadius:3}
    ],{extra:{scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:'#F0F0F0'}}}}});
    makeChart('ch-cupons','line',cM,[{label:'Cupons',data:cM.map(function(m){return (allM[m]?.cupom_comercial||0)+(allM[m]?.cupom_marketing||0);}),borderColor:'#E67E22',backgroundColor:'#E67E2222',fill:true,tension:.3,pointRadius:3}],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
    makeChart('ch-rebates','line',cM,[
      {label:'Pr\u00e9-neg.',data:cM.map(function(m){return (allM[m]?.pre_acordo||0)+(allM[m]?.dod||0)+(allM[m]?.relampago||0);}),borderColor:'#3483FA',fill:false,tension:.3,pointRadius:3},
      {label:'Outras',data:cM.map(function(m){return (allM[m]?.sad||0)+(allM[m]?.automaticas||0)+(allM[m]?.pm_cofin||0)+(allM[m]?.pm_100||0)+(allM[m]?.pix||0);}),borderColor:'#00A650',fill:false,tension:.3,pointRadius:3}
    ],{yFmt:v=>'R$'+v.toLocaleString('pt-BR',{notation:'compact'})});
  }
  // Mix donut: always current period
  makeChart('ch-inv-mix','doughnut',['Cupons','Rebate Pr\u00e9-neg.','Rebate Outras'],
    [{data:[gCupons,gPre,gOutras],backgroundColor:['#FFE600','#3483FA','#00A650'],borderWidth:0}],
    {extra:{plugins:{legend:{display:true,position:'bottom'}}}});

  var INV_SEL_FIELDS=['pre_acordo','dod','relampago','sad','automaticas','pm_cofin','pm_100','pix','cupom_comercial','cupom_marketing'];
  var bySI=pc.gran==='daily'?aggBySellerDaily(RAW.investimentos_daily,pc.curr[0],pc.curr[1],INV_SEL_FIELDS):aggBySeller(RAW.investimentos_monthly,meses,['gmv'].concat(INV_SEL_FIELDS));
  var h='<thead><tr><th>Seller</th><th>Pr\u00e9-Acordo</th><th>DoD</th><th>Rel\u00e2mpago</th><th>SAD</th><th>Autom\u00e1ticas</th><th>PM Cofin.</th><th>PM 100%</th><th>PIX</th><th>Cp. Comercial</th><th>Cp. Marketing</th><th>Total</th><th>%GMV</th></tr></thead><tbody>';
  Object.entries(bySI).sort(function(a,b){
    function _t(v){return (v.pre_acordo||0)+(v.dod||0)+(v.relampago||0)+(v.sad||0)+(v.automaticas||0)+(v.pm_cofin||0)+(v.pm_100||0)+(v.pix||0)+(v.cupom_comercial||0)+(v.cupom_marketing||0);}
    return _t(b[1])-_t(a[1]);
  }).forEach(function([cid,v]){
    var tot=(v.pre_acordo||0)+(v.dod||0)+(v.relampago||0)+(v.sad||0)+(v.automaticas||0)+(v.pm_cofin||0)+(v.pm_100||0)+(v.pix||0)+(v.cupom_comercial||0)+(v.cupom_marketing||0);
    var pct=v.gmv?(tot/v.gmv)*100:0;
    h+='<tr>'+
      '<td>'+sellerLabel(cid)+'</td>'+
      '<td>'+fmtBRL(v.pre_acordo||0)+'</td>'+
      '<td>'+fmtBRL(v.dod||0)+'</td>'+
      '<td>'+fmtBRL(v.relampago||0)+'</td>'+
      '<td>'+fmtBRL(v.sad||0)+'</td>'+
      '<td>'+fmtBRL(v.automaticas||0)+'</td>'+
      '<td>'+fmtBRL(v.pm_cofin||0)+'</td>'+
      '<td>'+fmtBRL(v.pm_100||0)+'</td>'+
      '<td>'+fmtBRL(v.pix||0)+'</td>'+
      '<td>'+fmtBRL(v.cupom_comercial||0)+'</td>'+
      '<td>'+fmtBRL(v.cupom_marketing||0)+'</td>'+
      '<td><b>'+fmtBRL(tot)+'</b></td>'+
      '<td>'+fmtPct(pct)+'</td>'+
    '</tr>';
  });
  document.getElementById('tbl-inv-sellers').innerHTML=h+'</tbody>';
}
function renderCatalogo(){
  updateCatFilterBar();
  var pc=getPeriodConfig();
  setBadge('period-badge-catalogo',pc);
  var ids=sellerIds(state.seller);

  // IDs das 3 lojas da Outlet das Fábricas — catálogo fixado em F&H
  var OUTLET_CAT_IDS=['70123968','2355501248','638325656'];

  // Para Outlet: F&H forçado; para os demais: respeita state.catFilter
  function catFilterCatalogo(r){
    if(OUTLET_CAT_IDS.includes(String(r.cust_id)))
      return (r.vertical||'')==='FURNISHING & HOUSEWARE';
    if(state.catFilter) return (r.vertical||'')===state.catFilter;
    return true;
  }

  // Esconde o filtro de categoria SOMENTE na aba catálogo para Outlet
  // (mantém visível nas outras abas, ex: visitas)
  var isOutlet=isOutletView();
  var catTabBar=document.querySelector('#tab-catalogo .cat-filter-bar');
  if(catTabBar) catTabBar.style.display=isOutlet?'none':'';

  // Titulo lookup
  var titleMap={};
  (RAW.catalogo_monthly||[]).forEach(function(r){
    var k=String(r.cust_id)+'|'+String(r.item_id);
    if(!titleMap[k])titleMap[k]=r.titulo||'';
  });

  // Campaign / optin lookup: {item_id -> {in_campaign, optin}}
  var campMap={};
  (RAW.catalogo_campaigns||[]).filter(function(r){return ids.includes(String(r.cust_id));})
    .forEach(function(r){
      var iid=String(r.item_id);
      if(!campMap[iid])campMap[iid]={in_campaign:0,optin:0};
      if(r.in_campaign)campMap[iid].in_campaign=1;
      if(r.optin)campMap[iid].optin=1;
    });

  // Aggregate items from rows filtered by predicate
  function aggItems(rows,filterFn){
    var out={};
    (rows||[]).filter(function(r){return ids.includes(String(r.cust_id));})
              .filter(filterFn)
              .forEach(function(r){
                var k=String(r.cust_id)+'|'+String(r.item_id);
                if(!out[k])out[k]={cust_id:r.cust_id,item_id:r.item_id,
                  titulo:r.titulo||titleMap[k]||'',vertical:r.vertical||'',gmv:0,si:0};
                out[k].gmv+=(Number(r.gmv)||0);
                out[k].si +=(Number(r.si )||0);
              });
    Object.values(out).forEach(function(v){v.asp=v.si?v.gmv/v.si:0;});
    return out;
  }

  // Build {cust_id -> total_gmv} for a period, de-duplicating per (seller, period-unit)
  function buildSellerGmvMap(rows,periodKey,filterFn){
    var seen={},out={};
    (rows||[]).filter(function(r){return ids.includes(String(r.cust_id));})
              .filter(filterFn)
              .forEach(function(r){
                var sk=String(r.cust_id)+'|'+r[periodKey];
                if(!seen[sk]){
                  seen[sk]=true;
                  var cid=String(r.cust_id);
                  out[cid]=(out[cid]||0)+(Number(r.seller_total_gmv)||0);
                }
              });
    return out;
  }

  // Filtragem: Outlet = F&H forçado; outros = catFilter normal
  var catM=(RAW.catalogo_monthly||[]).filter(catFilterCatalogo);
  var catD=(RAW.catalogo_daily  ||[]).filter(catFilterCatalogo);

  var currMap,prevMap,sellerGmvCurr,sellerGmvPrev;
  if(pc.gran==='daily'){
    currMap=aggItems(catD,function(r){return r.dia>=pc.curr[0]&&r.dia<=pc.curr[1];});
    prevMap=pc.prev?aggItems(catD,function(r){return r.dia>=pc.prev[0]&&r.dia<=pc.prev[1];}): {};
    sellerGmvCurr=buildSellerGmvMap(catD,'dia',function(r){return r.dia>=pc.curr[0]&&r.dia<=pc.curr[1];});
    sellerGmvPrev=pc.prev?buildSellerGmvMap(catD,'dia',function(r){return r.dia>=pc.prev[0]&&r.dia<=pc.prev[1];}): {};
  } else {
    currMap=aggItems(catM,function(r){return (pc.curr||[]).includes(r.mes);});
    sellerGmvCurr=buildSellerGmvMap(catM,'mes',function(r){return (pc.curr||[]).includes(r.mes);});
    if(pc.prevMoMDailyRange&&pc.diasPassados>0){
      prevMap=aggItems(catD,function(r){return r.dia>=pc.prevMoMDailyRange[0]&&r.dia<=pc.prevMoMDailyRange[1];});
      sellerGmvPrev=buildSellerGmvMap(catD,'dia',function(r){return r.dia>=pc.prevMoMDailyRange[0]&&r.dia<=pc.prevMoMDailyRange[1];});
    } else if(pc.prevMoM){
      prevMap=aggItems(catM,function(r){return (pc.prevMoM||[]).includes(r.mes);});
      sellerGmvPrev=buildSellerGmvMap(catM,'mes',function(r){return (pc.prevMoM||[]).includes(r.mes);});
    } else if(pc.prevQoQ){
      prevMap=aggItems(catM,function(r){return (pc.prevQoQ||[]).includes(r.mes);});
      sellerGmvPrev=buildSellerGmvMap(catM,'mes',function(r){return (pc.prevQoQ||[]).includes(r.mes);});
    } else if(pc.prevYoY){
      prevMap=aggItems(catM,function(r){return (pc.prevYoY||[]).includes(r.mes);});
      sellerGmvPrev=buildSellerGmvMap(catM,'mes',function(r){return (pc.prevYoY||[]).includes(r.mes);});
    } else {prevMap={};sellerGmvPrev={};}
  }

  // Top 50 itens por GMV (exibi\u00e7\u00e3o na tabela)
  var currItems=Object.values(currMap).sort(function(a,b){return b.gmv-a.gmv;}).slice(0,50);

  function deltaBadge(val,isPP){
    if(val===null||val===undefined||isNaN(val))return '<span style="color:var(--muted)">\u2014</span>';
    var cls=val>=0?'tag-pos':'tag-neg';
    var sign=val>=0?'+':'';
    return '<span class="'+cls+'">'+sign+val.toFixed(1)+(isPP?' pp':'%')+'</span>';
  }

  // \u2500\u2500 Summary cards \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // Totais consolidados dos top-50
  var totCurrGmv=0,totPrevGmv=0,totCurrSi=0,totPrevSi=0;
  currItems.forEach(function(r){
    var p=prevMap[String(r.cust_id)+'|'+String(r.item_id)];
    totCurrGmv+=r.gmv; totCurrSi+=r.si;
    if(p){totPrevGmv+=p.gmv; totPrevSi+=p.si;}
  });
  var totCurrAsp=totCurrSi?totCurrGmv/totCurrSi:0;
  var totPrevAsp=totPrevSi?totPrevGmv/totPrevSi:0;
  // Share consolidado: GMV top-50 / GMV total sellers
  var totalSellerGmvCurr=ids.reduce(function(a,cid){return a+(sellerGmvCurr[cid]||0);},0);
  var totalSellerGmvPrev=ids.reduce(function(a,cid){return a+(sellerGmvPrev[cid]||0);},0);
  var totCurrShare=totalSellerGmvCurr?totCurrGmv/totalSellerGmvCurr*100:0;
  var totPrevShare=totalSellerGmvPrev?totPrevGmv/totalSellerGmvPrev*100:0;
  var dGmvTot =totPrevGmv ?(totCurrGmv -totPrevGmv )/totPrevGmv *100:null;
  var dSiTot  =totPrevSi  ?(totCurrSi  -totPrevSi  )/totPrevSi  *100:null;
  var dAspTot =totPrevAsp ?(totCurrAsp -totPrevAsp )/totPrevAsp *100:null;
  var dShareTot=(totPrevShare>0)?(totCurrShare-totPrevShare):null;
  // Campanha / optin \u2014 itens \u00fanicos do top-50 que est\u00e3o em campanha / com optin
  var currItemIds=new Set(currItems.map(function(r){return String(r.item_id);}));
  var inCampCount=0,optinCount=0;
  Object.keys(campMap).forEach(function(iid){
    if(currItemIds.has(iid)){
      if(campMap[iid].in_campaign)inCampCount++;
      if(campMap[iid].optin)optinCount++;
    }
  });

  function kpiCard(label,curr,prev,delta,isPP,isBRL){
    var fmt=isBRL?fmtBRL:function(v){return v.toFixed(1)+'%';};
    var currFmt=isBRL?fmtBRL(curr):(curr.toFixed(1)+'%');
    var prevFmt=isBRL?fmtBRL(prev):(prev.toFixed(1)+'%');
    var badge=deltaBadge(delta,isPP);
    return '<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px;min-width:130px;flex:1">'
      +'<div style="font-size:11px;color:var(--muted);font-weight:600;margin-bottom:4px">'+label+'</div>'
      +'<div style="font-size:16px;font-weight:700;color:var(--text)">'+currFmt+'</div>'
      +'<div style="font-size:11px;color:var(--muted);margin-top:2px">ant: '+prevFmt+'</div>'
      +'<div style="margin-top:4px">'+badge+'</div>'
      +'</div>';
  }
  function countCard(label,value,sub){
    return '<div style="background:var(--card);border:1px solid var(--ml-blue);border-radius:8px;padding:10px 14px;min-width:130px;flex:1">'
      +'<div style="font-size:11px;color:var(--ml-blue);font-weight:600;margin-bottom:4px">'+label+'</div>'
      +'<div style="font-size:22px;font-weight:700;color:var(--ml-blue)">'+value+'</div>'
      +'<div style="font-size:11px;color:var(--muted);margin-top:2px">'+sub+'</div>'
      +'</div>';
  }

  var cardsHtml='<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px">'
    +kpiCard('\u0394 GMV Top-50',totCurrGmv,totPrevGmv,dGmvTot,false,true)
    +kpiCard('\u0394 SI Top-50',totCurrSi,totPrevSi,dSiTot,false,false)
    +kpiCard('\u0394 ASP Top-50',totCurrAsp,totPrevAsp,dAspTot,false,true)
    +kpiCard('\u0394 Share Top-50',totCurrShare,totPrevShare,dShareTot,true,false)
    +countCard('\ud83c\udfaf Em campanha',inCampCount,'itens \u00fanicos do top-50')
    +countCard('\u2705 Com optin',optinCount,'itens \u00fanicos do top-50')
    +'</div>';

  // \u2500\u2500 Cards acima da tabela \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  document.getElementById('cat-summary-cards').innerHTML=cardsHtml;

  // \u2500\u2500 Tabela \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  var thS='padding:8px 9px;font-size:11px;font-weight:700;background:var(--ml-blue);color:#fff;white-space:nowrap';
  var h='<thead><tr>'
    +'<th style="'+thS+';text-align:left;border-radius:6px 0 0 0">Seller</th>'
    +'<th style="'+thS+'">Item</th>'
    +'<th style="'+thS+';text-align:left;min-width:160px">T\u00edtulo</th>'
    +'<th style="'+thS+';text-align:center">Camp.</th>'
    +'<th style="'+thS+';text-align:center">Optin</th>'
    +'<th style="'+thS+';text-align:right">GMV</th>'
    +'<th style="'+thS+';text-align:right">SI</th>'
    +'<th style="'+thS+';text-align:right">ASP</th>'
    +'<th style="'+thS+';text-align:right">Share%</th>'
    +'<th style="'+thS+';text-align:center">\u0394 GMV</th>'
    +'<th style="'+thS+';text-align:center">\u0394 SI</th>'
    +'<th style="'+thS+';text-align:center">\u0394 ASP</th>'
    +'<th style="'+thS+';text-align:center;border-radius:0 6px 0 0">\u0394 Share</th>'
    +'</tr></thead><tbody>';

  currItems.forEach(function(r){
    var p=prevMap[String(r.cust_id)+'|'+String(r.item_id)];
    var selGmvC=sellerGmvCurr[String(r.cust_id)]||0;
    var selGmvP=sellerGmvPrev[String(r.cust_id)]||0;
    var share  =selGmvC?r.gmv/selGmvC*100:0;
    var pShare =(p&&selGmvP)?p.gmv/selGmvP*100:null;
    var dGmv=(p&&p.gmv)?(r.gmv-p.gmv)/p.gmv*100:null;
    var dSi =(p&&p.si )?(r.si -p.si )/p.si *100:null;
    var dAsp=(p&&p.asp)?(r.asp-p.asp)/p.asp*100:null;
    var dShare=(pShare!==null&&pShare!==undefined)?(share-pShare):null;
    var titulo=r.titulo||titleMap[String(r.cust_id)+'|'+String(r.item_id)]||'';
    var mlLink='https://produto.mercadolivre.com.br/MLB-'+String(r.item_id);
    var camp=campMap[String(r.item_id)]||{in_campaign:0,optin:0};
    var campBadge=camp.in_campaign?'<span class="tag-pos">\u2713</span>':'<span style="color:var(--muted)">\u2014</span>';
    var optinBadge=camp.optin?'<span class="tag-pos">\u2713</span>':'<span style="color:var(--muted)">\u2014</span>';
    h+='<tr>'
      +'<td>'+sellerLabel(r.cust_id)+'</td>'
      +'<td><a href="'+mlLink+'" target="_blank" style="color:var(--ml-blue2)">'+r.item_id+'</a></td>'
      +'<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+titulo+'</td>'
      +'<td style="text-align:center">'+campBadge+'</td>'
      +'<td style="text-align:center">'+optinBadge+'</td>'
      +'<td style="text-align:right">'+fmtBRL(r.gmv)+'</td>'
      +'<td style="text-align:right">'+fmtNum(r.si)+'</td>'
      +'<td style="text-align:right">'+fmtBRL(r.asp)+'</td>'
      +'<td style="text-align:right"><span class="badge">'+fmtPct(share)+'</span></td>'
      +'<td style="text-align:center">'+deltaBadge(dGmv,false)+'</td>'
      +'<td style="text-align:center">'+deltaBadge(dSi ,false)+'</td>'
      +'<td style="text-align:center">'+deltaBadge(dAsp,false)+'</td>'
      +'<td style="text-align:center">'+deltaBadge(dShare,true)+'</td>'
      +'</tr>';
  });
  document.getElementById('tbl-catalogo').innerHTML=h+'</tbody>';
}








function renderScorecard(){
  var el=document.getElementById('scorecard-sellers');
  if(state.seller!=='all'){if(el)el.innerHTML='';return;}
  var now=new Date(),yr=now.getFullYear(),mo=now.getMonth();
  // Exibe scorecard apenas no mês vigente (MTD ou mês atual selecionado explicitamente)
  var currPeriod='m'+(mo+1);
  if(state.period!=='month'&&state.period!=='mtd'&&state.period!==currPeriod){if(el)el.innerHTML='';return;}
  var meses=[fmtMonth(yr,mo)];
  var diasP=now.getDate()-1;
  var pmY=mo===0?yr-1:yr,pmM=mo===0?11:mo-1,pmStr=fmtMonth(pmY,pmM);
  var pmDIM=new Date(pmY,pmM+1,0).getDate(),pmEndDay=String(Math.min(diasP,pmDIM)).padStart(2,'0');
  var prevMoMDailyStart=pmStr+'-01',prevMoMDailyEnd=pmStr+'-'+pmEndDay;
  var prevYoScM=[fmtMonth(yr-1,mo)];
  var pyDIM=new Date(yr-1,mo+1,0).getDate(),yoyFactor=diasP>0?diasP/pyDIM:0;
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
    var gmvPrev=diasP>0?sumDailySeller(cid,prevMoMDailyStart,prevMoMDailyEnd,'gmv'):0;
    var gmvYoyFull=sumMeses(sAllM,prevYoScM,'gmv'),gmvYoy=gmvYoyFull*yoyFactor;
    var gmvWow1=sumDailySeller(cid,w1s,w1e,'gmv');
    var gmvWow2=sumDailySeller(cid,w2s,w2e,'gmv');
    var momPct=gmvPrev?((gmvCurr-gmvPrev)/gmvPrev*100):null;
    var yoyPct=gmvYoy?((gmvCurr-gmvYoy)/gmvYoy*100):null;
    var wowPct=gmvWow2?((gmvWow1-gmvWow2)/gmvWow2*100):null;
    var r=rep[cid]||{};

  // Metas lookup
  var SMETAS=RAW.seller_metas||{};
  var GROUP_META={'COLIBRI':'COLIBRI','KAPPESBERG':'KAPPESBERG','LINEA':'LINEA',
    'Outlet das Fab\u00e1bricas':'Outlet das Fabricas',
    'M\u00f3veis Prov\u00edncia':'Moveis Provincia',
    'Decorise':'Decorise',
    'Casa Aberta':'Casa Aberta',
    'Fidelitá':'Fidelita',
    'Nesher':'Nesher'};
  function getMetaForPeriod(groupName,meses){
    var mk=GROUP_META[groupName];
    if(!mk||!SMETAS[mk]) return 0;
    var mop=SMETAS[mk].meta_op||{};
    var mfin=SMETAS[mk].meta_fin||{};
    return (meses||[]).reduce(function(acc,m){
      var v=mop[m]||mfin[m]||0;
      return acc+v;
    },0);
  }
  function metaClass(pct){
    if(!pct) return 'dn0';
    if(pct>=100) return 'tag-pos';
    if(pct>=80) return 'dp';
    return 'tag-neg';
  }
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
      +(function(){
          var meta=getMetaForPeriod(s.group,meses);
          if(!meta) return '';
          var pct=gmvCurr?+(gmvCurr/meta*100).toFixed(1):0;
          var cls=metaClass(pct);
          var rem=meta-gmvCurr;
          return '<div class="sc-meta" style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">'
            +'<span style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.4px">Meta Operacional</span>'
            +'<div style="display:flex;align-items:center;gap:8px;margin-top:3px">'
            +'<span style="font-size:13px;font-weight:700;color:var(--txt)">'+fmtBRL(meta)+'</span>'
            +'<span class="'+cls+'" style="font-size:12px;font-weight:700">'+pct+'%</span>'
            +'</div>'
            +(rem>0?'<div style="font-size:10px;color:var(--muted);margin-top:1px">Faltam '+fmtBRL(rem)+'</div>':'')
            +'</div>';
        })()
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

function renderAtingimento(){
  var el=document.getElementById('tbl-atingimento');
  if(!el) return;
  var SMETAS=RAW.seller_metas||{};
  var sellers=RAW.sellers||[];
  var allM=RAW.geral_monthly||[];
  // group display name (s.group) → SMETAS key
  var gKeyMap={
    'COLIBRI':'COLIBRI','KAPPESBERG':'KAPPESBERG','LINEA':'LINEA',
    'Outlet das Fábricas':'Outlet das Fabricas',
    'Móveis Província':'Moveis Provincia',
    'Decorise':'Decorise',
    'Casa Aberta':'Casa Aberta',
    'Fidelitá':'Fidelita',
    'Nesher':'Nesher'
  };
  // SMETAS key → display name
  var dispName={
    'COLIBRI':'COLIBRI','KAPPESBERG':'KAPPESBERG','LINEA':'LINEA',
    'Outlet das Fabricas':'Outlet das Fábricas',
    'Moveis Provincia':'Móveis Província',
    'Decorise':'Decorise',
    'Casa Aberta':'Casa Aberta',
    'Fidelita':'Fidelitá',
    'Nesher':'Nesher'
  };
  // collect months that have meta_op in any group
  var mSet={};
  Object.keys(SMETAS).forEach(function(k){
    Object.keys(SMETAS[k].meta_op||{}).forEach(function(m){mSet[m]=1;});
  });
  var months=Object.keys(mSet).sort();
  if(!months.length){el.innerHTML='';return;}
  var now=new Date();
  var currM=now.getFullYear()+'-'+(now.getMonth()<9?'0':'')+(now.getMonth()+1);
  var diasMes=new Date(now.getFullYear(),now.getMonth()+1,0).getDate();
  var diasPassados=now.getDate()-1;
  var fatorProj=diasPassados>0?+(diasMes/diasPassados).toFixed(3):null;
  // cust_id → SMETAS key
  var cidKey={};
  sellers.forEach(function(s){var mk=gKeyMap[s.group];if(mk)cidKey[String(s.cust_id)]=mk;});
  // determine which groups are active for the current seller filter
  var selectedIds=sellerIds(state.seller);
  var activeGroups={};
  sellers.forEach(function(s){
    if(selectedIds.includes(String(s.cust_id))){var mk=gKeyMap[s.group];if(mk)activeGroups[mk]=true;}
  });
  // Outlet das Fabricas: when any of its stores is selected, always aggregate all 3
  // Casa Aberta: same logic — selecting one store always shows both
  var effectiveIds=selectedIds.slice();
  ['Outlet das Fabricas','Casa Aberta'].forEach(function(grpKey){
    if(activeGroups[grpKey]){
      sellers.forEach(function(s){
        if(gKeyMap[s.group]===grpKey&&!effectiveIds.includes(String(s.cust_id)))
          effectiveIds.push(String(s.cust_id));
      });
    }
  });
  // aggregate GMV by (SMETAS key, month) — only for effective sellers
  var gGMV={};
  allM.forEach(function(r){
    if(!effectiveIds.includes(String(r.cust_id))) return;
    var mk=cidKey[String(r.cust_id)];
    if(!mk) return;
    var key=mk+'||'+r.mes;
    gGMV[key]=(gGMV[key]||0)+(Number(r.gmv)||0);
  });
  // show only groups with active sellers
  var groups=Object.keys(SMETAS).filter(function(k){
    return Object.keys(SMETAS[k].meta_op||{}).length>0&&activeGroups[k];
  }).sort(function(a,b){return (dispName[a]||a).localeCompare(dispName[b]||b,'pt-BR');});
  function mLabel(m){
    var p=m.split('-'),mo=parseInt(p[1],10);
    var ns=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
    return (ns[mo-1]||mo)+'/'+p[0].slice(2);
  }
  function pctColor(pct){
    if(pct<=0) return '#aaa';
    if(pct>=100) return 'var(--green)';
    if(pct>=80) return '#F59E0B';
    return 'var(--red)';
  }
  var thBase='padding:9px 10px;font-size:11px;font-weight:700;background:var(--ml-blue);color:#fff;';
  var h='<thead><tr><th style="'+thBase+'text-align:left;min-width:130px;border-radius:6px 0 0 0">Grupo</th>';
  months.forEach(function(m,i){
    var isMtd=m===currM;
    var last=i===months.length-1;
    h+='<th style="'+thBase+'text-align:center;min-width:120px'+(isMtd?';font-style:italic':'')+(last?';border-radius:0 6px 0 0':'')+'">'+mLabel(m)+(isMtd?' *':'')+'</th>';
  });
  h+='</tr></thead><tbody>';
  groups.forEach(function(gk,gi){
    var dn=dispName[gk]||gk;
    var mop=SMETAS[gk].meta_op||{};
    var bg=gi%2===0?'var(--card)':'#f7f8fa';
    h+='<tr style="background:'+bg+'"><td style="font-size:12px;font-weight:700;padding:8px 10px;color:var(--ml-blue);border-bottom:1px solid var(--border)">'+dn+'</td>';
    months.forEach(function(m){
      var meta=mop[m];
      if(!meta){h+='<td style="text-align:center;color:var(--muted);padding:8px;border-bottom:1px solid var(--border)">—</td>';return;}
      var real=gGMV[gk+'||'+m]||0;
      var pct=+(real/meta*100).toFixed(1);
      var col=pctColor(pct);
      var isMtd=m===currM;
      var diff=real-meta;
      var diffHtml=diff>0
        ?'<span style="color:var(--green);font-weight:600">+'+fmtBRL(diff)+'</span>'
        :isMtd
          ?'<span style="color:var(--muted)">-'+fmtBRL(-diff)+'</span>'
          :'<span style="color:var(--red)">-'+fmtBRL(-diff)+'</span>';
      var projLine='';
      if(isMtd&&fatorProj){var pj=real*fatorProj,pjPct=+(pj/meta*100).toFixed(1),pjCol=pctColor(pjPct);projLine='<div style="font-size:9px;margin-top:4px;padding-top:3px;border-top:1px dashed var(--border);color:var(--muted)">Proj: <b style="color:'+pjCol+'">'+fmtBRL(pj)+'</b> ('+pjPct+'%)</div>';}
      h+='<td style="text-align:center;padding:6px 8px;border-bottom:1px solid var(--border)">'
        +'<div style="font-size:17px;font-weight:700;color:'+col+'">'+pct+'%</div>'
        +'<div style="font-size:10px;color:var(--muted);margin-top:2px;line-height:1.5">'
        +fmtBRL(real)+' / '+fmtBRL(meta)+'<br>'+diffHtml+'</div>'
        +projLine
        +'</td>';
    });
    h+='</tr>';
  });
  // Total row
  h+='<tr style="background:#EBF0FF;border-top:2px solid var(--ml-blue)"><td style="font-size:12px;font-weight:700;padding:8px 10px;color:var(--ml-blue);border-bottom:1px solid var(--border)">Total</td>';
  months.forEach(function(m){
    var totReal=0,totMeta=0;
    groups.forEach(function(gk){var meta=(SMETAS[gk].meta_op||{})[m];if(!meta)return;totReal+=(gGMV[gk+'||'+m]||0);totMeta+=meta;});
    if(!totMeta){h+='<td style="text-align:center;color:var(--muted);padding:8px;border-bottom:1px solid var(--border)">—</td>';return;}
    var pct=+(totReal/totMeta*100).toFixed(1),col=pctColor(pct),isMtd=m===currM,diff=totReal-totMeta;
    var diffHtml=diff>0?'<span style="color:var(--green);font-weight:600">+'+fmtBRL(diff)+'</span>':isMtd?'<span style="color:var(--muted)">-'+fmtBRL(-diff)+'</span>':'<span style="color:var(--red)">-'+fmtBRL(-diff)+'</span>';
    var tProjLine='';
    if(isMtd&&fatorProj){var tpj=totReal*fatorProj,tpjPct=+(tpj/totMeta*100).toFixed(1),tpjCol=pctColor(tpjPct);tProjLine='<div style="font-size:9px;margin-top:4px;padding-top:3px;border-top:1px dashed var(--border);color:var(--muted)">Proj: <b style="color:'+tpjCol+'">'+fmtBRL(tpj)+'</b> ('+tpjPct+'%)</div>';}
    h+='<td style="text-align:center;padding:6px 8px;border-bottom:1px solid var(--border)"><div style="font-size:17px;font-weight:700;color:'+col+'">'+pct+'%</div><div style="font-size:10px;color:var(--muted);margin-top:2px;line-height:1.5">'+fmtBRL(totReal)+' / '+fmtBRL(totMeta)+'<br>'+diffHtml+'</div>'+tProjLine+'</td>';
  });
  h+='</tr>';
  h+='</tbody>';
  if(months.indexOf(currM)>=0){
    var fatorStr=fatorProj?' · '+diasPassados+'/'+diasMes+' dias · fator proj. '+fatorProj.toFixed(2)+'x':'';
    h+='<tfoot><tr><td colspan="'+(months.length+1)+'" style="font-size:9px;color:var(--muted);padding:6px 10px">* Mês em curso — dados parciais até D-1'+fatorStr+'</td></tr></tfoot>';
  }
  el.innerHTML=h;
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
  (RAW.catalogo_monthly||[]).filter(function(r){return ids.includes(String(r.cust_id));}).forEach(function(r){
    if(!siMap[r.item_id])siMap[r.item_id]={titulo:r.titulo||'',si:0};
    siMap[r.item_id].si+=(Number(r.si)||0);
    if(!siMap[r.item_id].titulo&&r.titulo)siMap[r.item_id].titulo=r.titulo;
  });
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

function renderPandora(){
  var pc=getPeriodConfig();
  setBadge('period-badge-pandora',pc);
  var mT=pc.gran==='monthly'?pc.curr:pc.currM;
  var ids=sellerIds(state.seller);
  var items=(RAW.pandora_items||[]).filter(function(r){return ids.includes(String(r.cust_id));});
  // Para mai/2026: usar snapshot congelado; para demais períodos: dados ao vivo
  var isMai26=(mT&&mT.length===1&&mT[0]==='2026-05');
  var vcSrc=isMai26&&(RAW.pandora_vc_mai26||[]).length?RAW.pandora_vc_mai26:RAW.pandora_vc;
  var campSrc=isMai26&&(RAW.pandora_camp_mai26||[]).length?RAW.pandora_camp_mai26:RAW.pandora_camp;
  // VC lookup by item_id
  var vcMap={};
  (vcSrc||[]).forEach(function(v){vcMap[v.item_id]=v;});
  // Elegibilidade = item está em pandora_items (já filtrado por P-MLB17513056 ativo)
  // Optin = item tem preço ativo em LK_ITE_ITEM_PRICES (pandora_camp.optin)
  var optinSet={};
  (campSrc||[]).filter(function(r){return ids.includes(String(r.cust_id));})
    .forEach(function(r){if(r.optin)optinSet[String(r.item_id)]=1;});
  // mantém campMap como fallback para compatibilidade
  var campMap={};
  // Financeiro: soma por seller+item nos meses do periodo
  var fin={};
  (RAW.pandora_financeiro||[])
    .filter(function(r){return ids.includes(String(r.cust_id))&&(mT||[]).includes(r.mes);})
    .forEach(function(r){
      var k=String(r.cust_id)+'_'+r.item_id;
      if(!fin[k])fin[k]={gmv:0,rebate_invest:0};
      fin[k].gmv+=(Number(r.gmv)||0);
      fin[k].rebate_invest+=(Number(r.rebate_invest)||0);
    });
  var TYPE_LABELS={'PRENEGOTIATED':'Pré Acordo','PRE_ACORDO':'Pré Acordo','DOD':'Oferta do Dia','LIGHTNING':'Relâmpago'};
  var h='<thead><tr>'
    +'<th>Seller</th><th>Tipo</th><th>Item ID</th><th>Nome</th>'
    +'<th>Elegível</th><th>Optin</th>'
    +'<th>Pr. Negociado</th><th>Rebate</th><th>Pr. Final</th>'
    +'<th>Faturamento</th><th>Invest. Rebate</th>'
    +'<th>DC Atual</th><th>VC Final</th>'
    +'</tr></thead><tbody>';
  items
    .sort(function(a,b){
      var na=sellerLabel(a.cust_id),nb=sellerLabel(b.cust_id);
      if(na!==nb)return na.localeCompare(nb,'pt-BR');
      return (a.tipo||'').localeCompare(b.tipo||'')||(a.titulo||'').localeCompare(b.titulo||'','pt-BR');
    })
    .forEach(function(r){
      var pn=r.preco_negociado,pf=r.preco_final;
      var reb=r.rebate!=null?r.rebate:(pn!=null&&pf!=null)?Math.max(0,+(pn-pf).toFixed(2)):null;
      var vcKey=r.item_id;
      var vc=vcMap[vcKey]||{};
      var fk=String(r.cust_id)+'_'+r.item_id;
      var fv=fin[fk]||{gmv:0,rebate_invest:0};
      var mlUrl='https://produto.mercadolivre.com.br/MLB-'+String(r.item_id);
      var tipoLbl=TYPE_LABELS[r.tipo]||r.tipo||'-';
      var vcCls=vc.vc_final!=null?(vc.vc_final>=3?'tag-pos':vc.vc_final>=1?'dp':'tag-neg'):'dn0';
      var dcCls=vc.dc_atual!=null?(vc.dc_atual>=5?'tag-pos':vc.dc_atual>=2?'dp':'tag-neg'):'dn0';
      var eligBadge='<span class="tag-pos">Sim</span>';
      var optBadge=(r.status_campanha&&r.status_campanha.toLowerCase()==='active')?'<span class="tag-pos">Sim</span>':'<span class="dn0">Não</span>';
      h+='<tr>'
        +'<td>'+sellerLabel(r.cust_id)+'</td>'
        +'<td><span class="badge">'+tipoLbl+'</span></td>'
        +'<td><a href="'+mlUrl+'" target="_blank" style="color:var(--ml-blue2)">'+r.item_id+'</a></td>'
        +'<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(r.titulo||'-')+'</td>'
        +'<td style="text-align:center">'+eligBadge+'</td>'
        +'<td style="text-align:center">'+optBadge+'</td>'
        +'<td>'+(pn!=null?fmtBRL(pn):'-')+'</td>'
        +'<td>'+(reb!=null?fmtBRL(reb):'-')+'</td>'
        +'<td>'+(pf!=null?fmtBRL(pf):'-')+'</td>'
        +'<td>'+(fv.gmv?fmtBRL(fv.gmv):'-')+'</td>'
        +'<td>'+(fv.rebate_invest?fmtBRL(fv.rebate_invest):'-')+'</td>'
        +'<td class="'+dcCls+'">'+(vc.dc_atual!=null?vc.dc_atual.toFixed(1)+'%':'-')+'</td>'
        +'<td class="'+vcCls+'">'+(vc.vc_final!=null?vc.vc_final.toFixed(1)+'%':'-')+'</td>'
        +'</tr>';
    });
  document.getElementById('tbl-pandora-items').innerHTML=h+'</tbody>';
  // KPI cards
  // totInv/totGMV: soma TODO o pandora_financeiro do período (inclui itens históricos
  // que saíram da campanha) — igual ao comportamento original, independente de pandora_items
  var totInv=0,totGMV=0;
  Object.values(fin).forEach(function(fv){totInv+=fv.rebate_invest;totGMV+=fv.gmv;});
  // DC/VC: ponderado apenas pelos itens ativos (com preço conhecido)
  var dcSum=0,vcSum=0,dcCnt=0,vcCnt=0;
  items.forEach(function(r){
    var fk=String(r.cust_id)+'_'+r.item_id;
    var fv=fin[fk]||{gmv:0,rebate_invest:0};
    var vc=vcMap[r.item_id]||{};
    if(vc.dc_atual!=null&&fv.gmv>0){dcSum+=vc.dc_atual*fv.gmv;dcCnt+=fv.gmv;}
    if(vc.vc_final!=null&&fv.gmv>0){vcSum+=vc.vc_final*fv.gmv;vcCnt+=fv.gmv;}
  });
  var budget=100000;
  var pctBudget=budget?+(totInv/budget*100).toFixed(1):0;
  var bCls=pctBudget>=90?'tag-neg':pctBudget>=70?'dp':'tag-pos';
  var dcMedia=dcCnt?+(dcSum/dcCnt).toFixed(2):null;
  var vcMedia=vcCnt?+(vcSum/vcCnt).toFixed(2):null;
  var dcMCls=dcMedia!=null?(dcMedia>=5?'tag-pos':dcMedia>=2?'dp':'tag-neg'):'dn0';
  var vcMCls=vcMedia!=null?(vcMedia>=3?'tag-pos':vcMedia>=1?'dp':'tag-neg'):'dn0';
  var roas=totInv>0?+(totGMV/totInv).toFixed(2):null;
  var roasCls=roas!=null?(roas>=10?'tag-pos':roas>=5?'dp':'tag-neg'):'dn0';
  // Investimento per\u00edodo anterior \u2014 mesmos dias quando MTD, m\u00eas completo quando fechado
  var prevInv=0;
  var invLbl=pc.d1Label||'MoM';
  if(pc.type==='mtd'&&pc.diasPassados>0&&pc.prevMoMDailyRange){
    // MTD: usa dados di\u00e1rios (pre_acordo + dod) para consist\u00eancia com aba Investimentos
    prevInv=sumDailyFromData(RAW.investimentos_daily,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],'pre_acordo')
           +sumDailyFromData(RAW.investimentos_daily,pc.prevMoMDailyRange[0],pc.prevMoMDailyRange[1],'dod');
  }else{
    var mTPrev=pc.prevMoM||pc.prevQoQ||[];
    (RAW.pandora_financeiro||[])
      .filter(function(r){return ids.includes(String(r.cust_id))&&mTPrev.includes(r.mes);})
      .forEach(function(r){prevInv+=(Number(r.rebate_invest)||0);});
  }
  function _invDeltaHtml(curr,prev){
    if(!prev||!curr) return '<span class="dn0">\u2014</span>';
    var d=(curr-prev)/prev*100,cls=d>=0?'dp':'dn',arr=d>=0?'\u25b2':'\u25bc';
    return '<span class="'+cls+'">'+invLbl+': '+arr+Math.abs(d).toFixed(1)+'%</span>';
  }
  var roasCard='<div class="kpi-card"><div class="kpi-label">ROAS Pandora</div>'
    +'<div class="kpi-value '+roasCls+'">'+(roas!=null?roas.toFixed(1)+'x':'-')+'</div>'
    +'<div class="kpi-delta"><span class="dn0">GMV / Invest. Rebate</span></div></div>';
  var dcVcCards=
    '<div class="kpi-card"><div class="kpi-label">DC Atual M\u00e9dio (pond.)</div>'
    +'<div class="kpi-value '+dcMCls+'">'+(dcMedia!=null?dcMedia.toFixed(1)+'%':'-')+'</div>'
    +'<div class="kpi-delta"><span class="dn0">Ponderado por GMV</span></div></div>'
    +'<div class="kpi-card"><div class="kpi-label">VC Final M\u00e9dia (pond.)</div>'
    +'<div class="kpi-value '+vcMCls+'">'+(vcMedia!=null?vcMedia.toFixed(1)+'%':'-')+'</div>'
    +'<div class="kpi-delta"><span class="dn0">Ponderado por GMV</span></div></div>';
  var gmvCard='<div class="kpi-card"><div class="kpi-label">GMV Pandora no Per\u00edodo</div>'
    +'<div class="kpi-value">'+fmtBRL(totGMV)+'</div>'
    +'<div class="kpi-delta"><span class="dn0">'+items.length+' it\u00eans</span></div></div>';
  var kpiHtml;
  if(state.seller==='all'){
    kpiHtml=
      '<div class="kpi-card"><div class="kpi-label">Invest. Rebate no Per\u00edodo</div>'
      +'<div class="kpi-value" style="font-size:20px">'+fmtBRL(totInv)+'</div>'
      +'<div class="kpi-delta">'+_invDeltaHtml(totInv,prevInv)+'<br><span class="dn0">Budget: '+fmtBRL(budget)+'</span></div></div>'
      +'<div class="kpi-card"><div class="kpi-label">% Budget Utilizado</div>'
      +'<div class="kpi-value '+bCls+'">'+fmtPct(pctBudget)+'</div>'
      +'<div class="kpi-delta"><span class="dn0">'+fmtBRL(budget-totInv)+' restante</span></div></div>'
      +gmvCard+roasCard+dcVcCards;
  } else {
    kpiHtml=
      '<div class="kpi-card"><div class="kpi-label">Invest. Rebate no Per\u00edodo</div>'
      +'<div class="kpi-value" style="font-size:20px">'+fmtBRL(totInv)+'</div>'
      +'<div class="kpi-delta">'+_invDeltaHtml(totInv,prevInv)+'</div></div>'
      +gmvCard+roasCard+dcVcCards;
  }
  document.getElementById('kpi-pandora').innerHTML=kpiHtml;
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
function setPeriod(p){
  state.period=p;
  buildPeriodButtons();
  renderAll();
}
function setSeller(val){
  var sv=String(val);
  if(sv==='all') state.seller='all';
  else if(MULTI_GROUPS.includes(sv)) state.seller=sv;
  else state.seller=Number(val);
  state.catFilter=null;
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
  if(state.tab==='pandora')       renderPandora();
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

// Abre links externos via window.open — contorna sandbox do iframe (Grid/GitHub Pages)
document.addEventListener('click',function(e){
  var a=e.target.closest('a[href]');
  if(!a||!a.href)return;
  e.preventDefault();
  e.stopPropagation();
  window.open(a.href,'_blank');
},false);

// ── Ordenação de tabelas ──────────────────────────────────────────────────────
(function(){
  var _col={},_dir={};
  function _num(s){
    // suporta pt-BR: R$ 1.234,56 | 12,3% | — (traço = NaN)
    var c=s.replace(/R\$\s*/g,'').replace(/%/g,'').replace(/\s/g,'')
           .replace(/\./g,'').replace(',','.');
    return parseFloat(c);
  }
  document.addEventListener('click',function(evt){
    var th=evt.target.closest('th');
    if(!th)return;
    var thead=th.closest('thead');
    if(!thead)return;
    var tbl=thead.closest('table');
    if(!tbl)return;
    var tid=tbl.id||Math.random();
    var ths=Array.from(thead.querySelectorAll('th'));
    var ci=ths.indexOf(th);
    var dir=(_col[tid]===ci&&_dir[tid]==='asc')?'desc':'asc';
    _col[tid]=ci; _dir[tid]=dir;
    ths.forEach(function(h,i){
      h.removeAttribute('data-sort');
      if(i===ci)h.setAttribute('data-sort',dir);
    });
    var tbody=tbl.querySelector('tbody');
    if(!tbody)return;
    var rows=Array.from(tbody.querySelectorAll('tr'));
    rows.sort(function(a,b){
      var av=(a.cells[ci]?a.cells[ci].textContent.trim():'');
      var bv=(b.cells[ci]?b.cells[ci].textContent.trim():'');
      var an=_num(av),bn=_num(bv);
      var cmp=(!isNaN(an)&&!isNaN(bn))?(an-bn):av.localeCompare(bv,'pt-BR',{sensitivity:'base'});
      return dir==='asc'?cmp:-cmp;
    });
    rows.forEach(function(r){tbody.appendChild(r);});
  },true);
})();

</script>



</body>



</html>



"""











# ── Main ──────────────────────────────────────────────────────────────────────



def generate():



    dataset = build_dataset()



    data_json = json.dumps(dataset, ensure_ascii=True, default=str)



    import base64 as _b64



    logo_path = os.path.join(os.path.dirname(__file__), "ml-logo.png")



    logo_b64 = _b64.b64encode(open(logo_path, "rb").read()).decode()



    html = HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json).replace("__LOGO__", logo_b64)



    out_path = os.path.join(os.path.dirname(__file__), "index.html")

    # Write atomically: write to temp file first, then rename
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(html)
    import shutil as _sh
    _sh.move(tmp_path, out_path)



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
    _acquire_lock()
    try:
        generate()
    finally:
        _release_lock()



