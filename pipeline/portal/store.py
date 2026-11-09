from sqlalchemy import text
from pipeline.db import warehouse


def engine():
    return warehouse.get_engine()


def one(conn, sql, **params):
    return conn.execute(text(sql), params).mappings().first()


def all_rows(conn, sql, **params):
    return list(conn.execute(text(sql), params).mappings())


def execute(conn, sql, **params):
    return conn.execute(text(sql), params)
