# dags/processing_etl.py

from airflow.models import Variable
import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator, ShortCircuitOperator

from src.scrapers.config_loader import load_country_config
from src.classifier import classify_by_sector

default_args = {
    'owner': 'you',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# Leemos el país desde la variable de entorno
COUNTRY = Variable.get('COUNTRY', default_var='colombia').lower()
CONFIG_YML = f"configs/{COUNTRY}.yml"

with DAG(
    dag_id='processing_etl',
    default_args=default_args,
    description='Limpieza y clasificación SOLO de los proyectos nuevos (to_detail)',
    start_date=datetime(2025, 6, 1),
    schedule_interval=None,  # sólo vía trigger desde master_etl
    catchup=False,
) as dag:

    def fetch_to_detail(**kwargs):
        ti = kwargs['ti']
        proyectos_det = ti.xcom_pull(
            dag_id='scraping_etl',
            task_ids='task_detail',
            key='proyectos_det',
            include_prior_dates=True
        ) or []
        logging.info(f"[processing_etl] Retrieved {len(proyectos_det)} projects from task_detail")
        return len(proyectos_det) > 0

    skip_if_no_new = ShortCircuitOperator(
        task_id='skip_if_no_new',
        python_callable=fetch_to_detail,
        provide_context=True
    )

    def task_clean(ti, **kwargs):
        proyectos = ti.xcom_pull(
            dag_id='scraping_etl',
            task_ids='task_detail',
            key='proyectos_det',
            include_prior_dates=True
        ) or []
        logging.info(f"[task_clean] Cleaning {len(proyectos)} new projects")

        # Ahora cargamos dinámicamente según COUNTRY
        _cfg    = load_country_config(CONFIG_YML)['storage']
        _raw    = _cfg['raw']
        RAW_LOOKUP_KEY = _raw.get('lookup_key', 'no_camara')

        cleaned = []
        for p in proyectos:
            nc = p.get(RAW_LOOKUP_KEY, '').strip()
            if not nc:
                logging.warning(f"[task_clean] Omitiendo sin {RAW_LOOKUP_KEY}: {p.get('titulo','(sin título)')}")
                continue
            p[RAW_LOOKUP_KEY] = nc
            # campos de fecha renombrados genéricos
            p['fecha_cam'] = p.get('fecha_camara') or None
            p['fecha_sen'] = p.get('fecha_senado') or None
            cleaned.append(p)

        logging.info(f"[task_clean] Cleaned count: {len(cleaned)}")
        ti.xcom_push(key='proyectos_clean', value=cleaned)

    def task_classify(ti, **kwargs):
        proyectos = ti.xcom_pull(task_ids='task_clean', key='proyectos_clean') or []
        logging.info(f"[task_classify] Classifying {len(proyectos)} new projects")
        proyectos_clas = classify_by_sector(proyectos)
        logging.info(f"[task_classify] Classified count: {len(proyectos_clas)}")
        ti.xcom_push(key='proyectos_clas', value=proyectos_clas)

    t0 = skip_if_no_new
    t1 = PythonOperator(task_id='task_clean',    python_callable=task_clean)
    t2 = PythonOperator(task_id='task_classify', python_callable=task_classify)

    t0 >> t1 >> t2
