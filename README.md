# Pipeline de Scraping de Proyectos de Ley en LATAM

Este repositorio contiene un **pipeline de scraping** diseñado para extraer, procesar y almacenar de forma incremental **proyectos de ley publicados en portales oficiales** de LATAM (actualmente Colombia y Perú). El sistema es resiliente, escalable y fácilmente configurable para incorporar nuevos países o portales.

## 📋 Tabla de Contenidos

1. [Descripción](#descripción)
2. [Características Principales](#características-principales)
3. [Arquitectura y Componentes](#arquitectura-y-componentes)
4. [Estructura del Repositorio](#estructura-del-repositorio)
5. [Requisitos](#requisitos)
6. [Configuración](#configuración)
7. [Instalación y Despliegue](#instalación-y-despliegue)
8. [Uso del Pipeline](#uso-del-pipeline)
9. [Pruebas y Calidad de Código](#pruebas-y-calidad-de-código)
10. [Contribuciones](#contribuciones)
11. [Licencia](#licencia)

---

## Descripción

Este pipeline automatiza la **extracción** de listados y detalles de proyectos de ley de portales oficiales, su **procesamiento** (limpieza, normalización y clasificación), y su **almacenamiento** incremental en una base de datos PostgreSQL. Además, enriquece cada proyecto con la clasificación por sector económico mediante la **API de Gemini**.

## Características Principales

- **Scrapers por País**: Módulos independientes para Colombia y Perú (configurables via YAML).
- **Rotación de Proxies y User‑Agents**: Evita bloqueos y distribuye la carga de peticiones.
- **Orquestación con Airflow**: Definición de DAGs modulares (`master_etl`, `scraping_etl`, `processing_etl`, `storage_etl`).
- **Enriquecimiento con API Gemini**: Clasificación por sector usando reglas locales y llamadas batch a Gemini.
- **Almacenamiento Incremental**: Detección de duplicados mediante checksum y upserts en tablas raw y final.
- **Logging y Monitoreo**: Logs en JSON, alertas en Slack, métricas en Prometheus y dashboard en Grafana.
- **Pruebas Unitarias**: Cobertura >80% en módulos críticos, fixtures y mocks con pytest y respx.
- **Despliegue Dockerizado**: Contenedores Airflow y PostgreSQL coordinados con Docker Compose.

## Arquitectura y Componentes

1. **Scrapers** (`src/scrapers/`):
   - `ScraperBase` define la interfaz genérica.
   - `GenericListParser` y `GenericDetailParser` para parseo configurable.
   - `DynamicScraper` orquesta fetch, parse y control de duplicados.
2. **Proxy Manager** (`src/scrapers/network/`):
   - Gestión y validación de proxies gratuitos.
   - Rotación de User‑Agents y lógica de retries con tenacity.
3. **Orquestación (Airflow)** (`dags/`):
   - DAGs modulares para scraping, procesamiento y almacenamiento.
   - Tareas con PythonOperator, TaskGroup y Branching.
4. **Clasificación** (`src/classifier.py`):
   - Reglas locales + API Gemini.
   - Batch processing y validación de categorías.
5. **Almacenamiento** (`src/storage.py`):
   - Adaptadores PostgreSQL.
   - Upserts incremental en tablas `raw_projects` y `final_projects`.
6. **Configuración** (`configs/`):
   - YAML por país (`colombia.yml`, `peru.yml`) y `classifier.yml`.
7. **Pruebas** (`test/`):
   - pytest, mocks con respx, fixtures HTML.

## Estructura del Repositorio

```plain
├── dags/                     # Definición de DAGs de Airflow
├── configs/                  # Archivos YAML de configuración
│   ├── colombia.yml
│   ├── peru.yml
│   └── classifier.yml
├── src/
│   ├── scrapers/             # Implementaciones de ScraperBase
│       ├── network/          # Proxy Manager y HTTP Client
│   ├── classifier.py         # Lógica de clasificación sectorial
│   └── storage.py            # Adaptadores y funciones de upsert
├── test/                     # Pruebas unitarias y fixtures
├── Dockerfile                # Definición de imagen base Airflow + pipeline
├── docker-compose.yml        # Orquestación de servicios
├── Makefile                  # Tareas comunes (build, up, etc.)
├── requirements.txt          # Dependencias Python
└── README.md                 # Este documento
```

## Requisitos

- Docker ≥ 20.10 y Docker Compose ≥ 1.29
- Make
- Python 3.9 (para desarrollo local)
- Variables de entorno definidas en `.env`

## Configuración

1. Clona el repositorio:
   ```bash
   git clone https://github.com/lph9l/scraping-datapipeline.git
   cd scraping-datapipeline
   ```
2. Copia el ejemplo de variables:
   ```bash
   cp .env.example .env
   ```
3. Edita `.env` con:
   ```dotenv
   COUNTRY=colombia        # o "peru"
   GEMINI_API_KEY=<tu_api_key>
   ```

## Instalación y Despliegue

Construye la imagen y levanta los servicios:
```bash
make build      # Construye con Dockerfile
make up         # Levanta Airflow y Postgres con docker-compose
```
En desarrollo local, también puedes:
```bash
docker-compose run --rm webserver airflow db init
docker-compose run --rm webserver \
  airflow users create \
    --username admin \
    --password admin \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@example.com
```

## Uso del Pipeline

1. Accede a la interfaz de Airflow en `http://localhost:8080`.
2. Crea una variable de entorno de Airflow con:
   ```dotenv
   COUNTRY=colombia        # o "peru"
   ```
3. Trigger manual del DAG `master_etl` o espera su ejecución programada.
4. Revisa logs, métricas en Airflow y estado de los dags.
5. Consulta datos almacenados en PostgreSQL via `psql` o pgAdmin.

## Pruebas y Calidad de Código

Ejecuta el suite de tests:
```bash
pytest -q
```
Se utilizan:
- **pytest** para pruebas unitarias.
- **respx** y fixtures HTML para mockear respuestas HTTP.
- **flake8**, **black** e **isort** integrados en pre-commit.

## Contribuciones

1. Haz un fork del proyecto.
2. Crea una rama (`git checkout -b feature/nueva-funcionalidad`).
3. Realiza tus cambios y agrega pruebas.
4. Asegúrate de pasar los tests y linters.
5. Abre un Pull Request describiendo tu aporte.

## Licencia

Este proyecto está bajo la [Licencia MIT](LICENSE).

---

