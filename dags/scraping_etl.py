# dags/scraping_etl.py

from airflow.models import Variable
from airflow import DAG
from airflow.operators.python import PythonOperator, ShortCircuitOperator
from datetime import datetime, timedelta
import logging
import json
from src.storage import (
    ensure_raw_table,
    fetch_existing_checksums,
    upsert_raw
)
from src.scrapers.config_loader import load_country_config
from src.scrapers.scraper import DynamicScraper

default_args = {
    'owner': 'you',
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}


# Leemos el país desde la variable de entorno
COUNTRY = Variable.get('COUNTRY', default_var='colombia').lower()
CONFIG_YML = f"configs/{COUNTRY}.yml"
_cfg            = load_country_config(CONFIG_YML)['storage']
RAW_LOOKUP_KEY  = _cfg['raw'].get('lookup_key', 'no_camara')

with DAG(
    dag_id='scraping_etl',
    default_args=default_args,
    description='Scraping incremental con checksum',
    start_date=datetime(2025, 6, 1),
    schedule_interval=None,   # sólo vía trigger
    catchup=False,
) as dag:

    def task_scrape(ti, **kwargs):
        ds = DynamicScraper(CONFIG_YML)
        proyectos = ds.run_list()
        logging.info(f"[task_scrape] Projects scraped: {len(proyectos)}")

        top_20 = proyectos[:50]
        for i, p in enumerate(top_20, 1):
            resumen = f"{i}. {p}"
            logging.info(resumen)

        ti.xcom_push(key='proyectos_raw', value=top_20)

    def task_delta(ti, **kwargs):
        ds = DynamicScraper(CONFIG_YML)
        proyectos = ti.xcom_pull(task_ids='task_scrape', key='proyectos_raw') or []
        logging.info(f"[task_delta] Incoming raw count: {len(proyectos)}")

        ensure_raw_table()
        existing = fetch_existing_checksums()

        to_detail, bypass, raw_records = [], [], []
        for p in proyectos:
            pid = p.get(RAW_LOOKUP_KEY,'').strip()   # usa tu lookup_key real
            ch  = p.get('row_hash') or ds._compute_checksum(p)
            # aquí guardamos bajo la clave dinámica
            raw_records.append({RAW_LOOKUP_KEY: pid, 'row_hash': ch})

            if pid not in existing or existing[pid] != ch:
                to_detail.append(p)
            else:
                bypass.append(p)

        logging.info(f"[task_delta] to_detail: {len(to_detail)}, bypass: {len(bypass)}")
        ti.xcom_push(key='proyectos_todetail', value=to_detail)
        ti.xcom_push(key='proyectos_bypass',  value=bypass)
        ti.xcom_push(key='raw_records',      value=raw_records)

    def check_changes(ti, **kwargs):
        to_detail = ti.xcom_pull(task_ids='task_delta', key='proyectos_todetail') or []
        has = len(to_detail) > 0
        logging.info(f"[check_changes] Changes present? {has}")
        return has


    def task_upsert_raw(ti, **kwargs):
        # Cambia el key a 'proyectos_raw' para que coincida con lo que empujas arriba
        records = ti.xcom_pull(task_ids='task_delta', key='raw_records') or []
        logging.info(f"[task_upsert_raw] Received {len(records)} raw records")

        valid = [
            r for r in records
            if isinstance(r.get(RAW_LOOKUP_KEY), str) and r[RAW_LOOKUP_KEY].strip()
        ]
        logging.info(f"[task_upsert_raw] Upserting {len(valid)} valid raw records (of {len(records)})")

        upsert_raw(valid)


    def task_detail(ti, **kwargs):
        ds = DynamicScraper(CONFIG_YML)
        to_detail = ti.xcom_pull(task_ids='task_delta', key='proyectos_todetail') or []
        logging.info(f"[task_detail] Detailing {len(to_detail)} projects")
        proyectos_det = ds.run_detail(to_detail)
        logging.info(f"[task_detail] Detailed: {len(proyectos_det)}")
        for i, p in enumerate(proyectos_det, 1):
            resumen = f"{i}. {p}"
            logging.info(resumen)
        ti.xcom_push(key='proyectos_det', value=proyectos_det)

    def task_merge(ti, **kwargs):
        det    = ti.xcom_pull(task_ids='task_detail', key='proyectos_det') or []
        bypass = ti.xcom_pull(task_ids='task_delta', key='proyectos_bypass') or []
        logging.info(f"[task_merge] detail: {len(det)}, bypass: {len(bypass)}")
        merged = det + bypass
        logging.info(f"[task_merge] Merged total: {len(merged)}")
        ti.xcom_push(key='proyectos_cleanlist', value=merged)

    t1 = PythonOperator(task_id='task_scrape',    python_callable=task_scrape)
    t2 = PythonOperator(task_id='task_delta',     python_callable=task_delta)
    t_check = ShortCircuitOperator(
        task_id='check_changes',
        python_callable=check_changes
    )
    t3 = PythonOperator(task_id='task_upsert_raw', python_callable=task_upsert_raw)
    t4 = PythonOperator(task_id='task_detail',    python_callable=task_detail)
    t5 = PythonOperator(task_id='task_merge',     python_callable=task_merge)

    t1 >> t2 >> t_check >> t3 >> t4 >> t5
