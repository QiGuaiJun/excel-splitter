# -*- coding: utf-8 -*-
"""数据库初始化：读取 schema.sql 并执行建表。"""
import os
from db.connection import get_connection, BASE_DIR

SCHEMA_PATH = os.path.join(BASE_DIR, "db", "schema.sql")


def init_db():
    """执行 schema.sql 建表（IF NOT EXISTS，可重复执行）。"""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # pymysql 不支持一次执行多条语句，按分号拆分
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
        return len(statements)
    finally:
        conn.close()


if __name__ == "__main__":
    n = init_db()
    print(f"数据库初始化完成，执行了 {n} 条语句。")
