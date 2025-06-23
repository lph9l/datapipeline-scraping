# dags/storage_etl.py

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import logging

from src.storage import ensure_final_table, store_projects

default_args = {
    'owner': 'you',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    dag_id='storage_etl',
    default_args=default_args,
    description='Almacenamiento final en PostgreSQL',
    start_date=datetime(2025, 6, 1),
    schedule_interval=None,  # sólo vía trigger
    catchup=False,
) as dag:

    def task_store(ti, **kwargs):
        # 1) Aseguramos que la tabla exista
        ensure_final_table()

        # 2) Recuperamos la XCom de procesamiento, incluso si fue en otra fecha
        proyectos = ti.xcom_pull(
            dag_id='processing_etl',
            task_ids='task_classify',
            key='proyectos_clas',
            include_prior_dates=True
        )
        logging.info(f"[task_store] Raw XCom from 'processing_etl.task_classify': {proyectos!r}")

        proyectos = proyectos or []
        logging.info(f"[task_store] Storing {len(proyectos)} projects into 'proyectos' table")

        # 3) Ejecutamos el almacenamiento
        store_projects(proyectos)

    t1 = PythonOperator(
        task_id='task_store',
        python_callable=task_store
    )
