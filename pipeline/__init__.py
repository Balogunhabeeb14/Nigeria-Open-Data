"""
Naija Open Data – Ingestion Pipeline
=======================================
A production-grade, modular data pipeline that ingests open data about Nigeria,
maps it to a Common Data Model (CDM), and publishes it to CKAN and a data warehouse.

Package layout
--------------
connectors/   – one module per data source (API + bulk download)
transforms/   – raw → CDM mapping logic
quality/      – schema validation + sanity checks
db/           – database I/O (SQLAlchemy, manifest table, CDM upserts)
scrapers/     – last-resort HTML scrapers (clearly isolated)
flows/        – Prefect orchestration flows (entry points)
"""
