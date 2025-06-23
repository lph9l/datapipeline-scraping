# dags/master_etl.py

from airflow import DAG
from airflow.operators.python import BranchPythonOperator
from airflow.operators.dummy import DummyOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from datetime import datetime, timedelta
import logging

default_args = {
    'owner': 'you',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    dag_id='master_etl',
    default_args=default_args,
    description='Orquesta Scraping → Procesamiento → Almacenamiento con misma execution_date',
    start_date=datetime(2025, 6, 1),
    schedule_interval='@daily',
    catchup=False,
) as dag:

    trigger_scraping = TriggerDagRunOperator(
        task_id='trigger_scraping_etl',
        trigger_dag_id='scraping_etl',
        execution_date='{{ execution_date }}',
        reset_dag_run=True,
        wait_for_completion=True,
        poke_interval=10,
    )

    def branch_by_changes(**ctx):
        ti = ctx['ti']
        todetail = ti.xcom_pull(
            dag_id='scraping_etl',
            task_ids='task_delta',
            key='proyectos_todetail'
        ) or []
        logging.info(f"[master_etl] Changes in scraping_etl.task_delta: {len(todetail)}")
        return 'trigger_processing_etl' if todetail else 'end_no_changes'

    check_changes = BranchPythonOperator(
        task_id='check_changes',
        python_callable=branch_by_changes,
        provide_context=True,
    )

    end_no_changes = DummyOperator(task_id='end_no_changes')

    trigger_processing = TriggerDagRunOperator(
        task_id='trigger_processing_etl',
        trigger_dag_id='processing_etl',
        execution_date='{{ execution_date }}',
        reset_dag_run=True,
        wait_for_completion=True,
        poke_interval=10,
    )

    trigger_storage = TriggerDagRunOperator(
        task_id='trigger_storage_etl',
        trigger_dag_id='storage_etl',
        execution_date='{{ execution_date }}',
        reset_dag_run=True,
        wait_for_completion=True,
        poke_interval=10,
    )

    trigger_scraping >> check_changes
    check_changes >> end_no_changes
    check_changes >> trigger_processing >> trigger_storage
