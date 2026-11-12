# -*- coding: utf-8 -*-
"""数据访问层（DAO）：categories / data_sources / collection_logs 的 CRUD。

批次 7 简化：引入 cursor() 上下文管理器（自动 connect / commit / rollback /
close），把每个 DAO 方法从 4-5 行样板代码压成 2 行。
"""
import contextlib
import json
from datetime import datetime

import pymysql.cursors

from db.connection import get_connection


# ---------------------------------------------------------------------------
# 连接 & 上下文
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def cursor():
    """自动管理连接的 cursor 上下文管理器。

    用法：
        with cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    行为：
    - 进入时：从连接池取一个 DictCursor 连接；
    - 块内无异常：自动 commit；
    - 块内有异常：自动 rollback 并向上抛；
    - 退出时：总是 close 连接。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _deserialize(row):
    """将 MySQL JSON 字段反序列化，datetime 转本地时间字符串（避免 jsonify 时区错误）。"""
    if not row:
        return
    for key in ("config", "sheet_names"):
        val = row.get(key)
        if isinstance(val, str):
            try:
                row[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    for key in ("created_at", "updated_at", "last_collected_at"):
        val = row.get(key)
        if isinstance(val, datetime):
            row[key] = val.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# CategoryDAO
# ---------------------------------------------------------------------------
class CategoryDAO:
    """数据源分类 DAO。"""

    @staticmethod
    def list_all():
        sql = "SELECT * FROM categories ORDER BY sort ASC, id ASC"
        with cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()

    @staticmethod
    def get_by_id(category_id):
        sql = "SELECT * FROM categories WHERE id = %s"
        with cursor() as cur:
            cur.execute(sql, (category_id,))
            return cur.fetchone()

    @staticmethod
    def get_by_name(name):
        sql = "SELECT * FROM categories WHERE name = %s"
        with cursor() as cur:
            cur.execute(sql, (name,))
            return cur.fetchone()

    @staticmethod
    def create(name, sort=0):
        sql = "INSERT INTO categories (name, sort) VALUES (%s, %s)"
        with cursor() as cur:
            cur.execute(sql, (name, sort))
            return cur.lastrowid

    @staticmethod
    def update(category_id, name=None, sort=None):
        sets, params = [], []
        if name is not None:
            sets.append("name = %s"); params.append(name)
        if sort is not None:
            sets.append("sort = %s"); params.append(sort)
        if not sets:
            return False
        params.append(category_id)
        sql = f"UPDATE categories SET {', '.join(sets)} WHERE id = %s"
        with cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount > 0

    @staticmethod
    def count_sources(category_id):
        sql = "SELECT COUNT(*) AS cnt FROM data_sources WHERE category_id = %s"
        with cursor() as cur:
            cur.execute(sql, (category_id,))
            return cur.fetchone()["cnt"]

    @staticmethod
    def delete(category_id):
        if CategoryDAO.count_sources(category_id) > 0:
            return False
        sql = "DELETE FROM categories WHERE id = %s"
        with cursor() as cur:
            cur.execute(sql, (category_id,))
            return cur.rowcount > 0


# ---------------------------------------------------------------------------
# DataSourceDAO
# ---------------------------------------------------------------------------
class DataSourceDAO:
    """数据源 DAO。"""

    @staticmethod
    def list_all(category_id=None, keyword=None, filter_null=False, page=1, page_size=None, channel_filter=None):
        where = "WHERE 1=1"
        params = []
        if filter_null:
            where += " AND ds.category_id IS NULL"
        elif category_id is not None:
            where += " AND ds.category_id = %s"
            params.append(category_id)
        if keyword:
            where += " AND (ds.name LIKE %s OR ds.config LIKE %s)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if channel_filter:
            where += " AND ds.channel = %s"
            params.append(channel_filter)

        # 总数
        count_sql = f"SELECT COUNT(*) AS cnt FROM data_sources ds LEFT JOIN categories c ON ds.category_id = c.id {where}"
        with cursor() as cur:
            cur.execute(count_sql, params)
            total = cur.fetchone()["cnt"]

        # 数据
        sql = f"SELECT ds.*, c.name AS category_name FROM data_sources ds LEFT JOIN categories c ON ds.category_id = c.id {where} ORDER BY ds.updated_at DESC, ds.id DESC"
        if page_size:
            offset = (page - 1) * page_size
            sql += " LIMIT %s OFFSET %s"
            params.extend([page_size, offset])
        with cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        for r in rows:
            _deserialize(r)
        return rows, total

    @staticmethod
    def get_by_id(source_id):
        sql = "SELECT ds.*, c.name AS category_name FROM data_sources ds LEFT JOIN categories c ON ds.category_id = c.id WHERE ds.id = %s"
        with cursor() as cur:
            cur.execute(sql, (source_id,))
            row = cur.fetchone()
        if row:
            _deserialize(row)
        return row

    @staticmethod
    def create(name, channel, category_id=None, file_path=None, config=None, status="pending"):
        config_json = json.dumps(config, ensure_ascii=False) if config is not None else None
        sql = (
            "INSERT INTO data_sources (name, channel, category_id, file_path, config, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        )
        with cursor() as cur:
            cur.execute(sql, (name, channel, category_id, file_path, config_json, status))
            return cur.lastrowid

    @staticmethod
    def update(source_id, **fields):
        allowed = {"name", "channel", "category_id", "file_path", "config",
                   "row_count", "col_count", "sheet_names", "status"}
        nullable = {"category_id"}
        sets, params = [], []
        for key, val in fields.items():
            if key in allowed and (val is not None or key in nullable):
                if key in ("config", "sheet_names") and val is not None:
                    val = json.dumps(val, ensure_ascii=False)
                sets.append(f"{key} = %s")
                params.append(val)
        if not sets:
            return False
        params.append(source_id)
        sql = f"UPDATE data_sources SET {', '.join(sets)} WHERE id = %s"
        with cursor() as cur:
            cur.execute(sql, params)
            return True

    @staticmethod
    def update_collect_result(source_id, row_count, col_count, sheet_names=None, status="ready"):
        sheets_json = json.dumps(sheet_names, ensure_ascii=False) if sheet_names else None
        sql = (
            "UPDATE data_sources SET row_count=%s, col_count=%s, sheet_names=%s, "
            "status=%s, last_collected_at=%s WHERE id=%s"
        )
        with cursor() as cur:
            cur.execute(sql, (row_count, col_count, sheets_json, status, datetime.now(), source_id))
            return cur.rowcount > 0

    @staticmethod
    def delete(source_id):
        sql = "DELETE FROM data_sources WHERE id = %s"
        with cursor() as cur:
            cur.execute(sql, (source_id,))
            return cur.rowcount > 0

    @staticmethod
    def count_all():
        sql = "SELECT COUNT(*) AS cnt FROM data_sources"
        with cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()["cnt"]

    @staticmethod
    def count_by_status(status):
        sql = "SELECT COUNT(*) AS cnt FROM data_sources WHERE status = %s"
        with cursor() as cur:
            cur.execute(sql, (status,))
            return cur.fetchone()["cnt"]


# ---------------------------------------------------------------------------
# CollectionLogDAO
# ---------------------------------------------------------------------------
class CollectionLogDAO:
    """采集日志 DAO。"""

    @staticmethod
    def list_by_source(source_id, limit=50):
        sql = "SELECT * FROM collection_logs WHERE source_id = %s ORDER BY created_at DESC, id DESC LIMIT %s"
        with cursor() as cur:
            cur.execute(sql, (source_id, limit))
            # DictCursor 的 fetchall() 返回 tuple；统一成 list，调用方才能安全地
            # 做判空 / 追加 / 排序等列表操作（级联删除后这里必须是空列表）。
            return list(cur.fetchall())

    @staticmethod
    def create(source_id, status, row_count=0, error_msg=None, duration_ms=0):
        sql = (
            "INSERT INTO collection_logs (source_id, status, row_count, error_msg, duration_ms) "
            "VALUES (%s, %s, %s, %s, %s)"
        )
        with cursor() as cur:
            cur.execute(sql, (source_id, status, row_count, error_msg, duration_ms))
            return cur.lastrowid

    @staticmethod
    def get_by_id(log_id):
        sql = """SELECT l.*, s.name as source_name, s.channel as source_channel
                 FROM collection_logs l
                 LEFT JOIN data_sources s ON l.source_id = s.id
                 WHERE l.id = %s"""
        with cursor() as cur:
            cur.execute(sql, (log_id,))
            row = cur.fetchone()
        if row:
            row["created_at"] = _fmt_time(row.get("created_at"))
        return row

    @staticmethod
    def list_all(page=1, page_size=20, status=None, start_date=None, end_date=None):
        where = []
        params = []
        if status:
            where.append("l.status = %s")
            params.append(status)
        if start_date:
            where.append("l.created_at >= %s")
            params.append(start_date)
        if end_date:
            where.append("l.created_at <= %s")
            params.append(end_date)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        offset = (page - 1) * page_size

        count_sql = f"SELECT COUNT(*) as cnt FROM collection_logs l{where_sql}"
        list_sql = f"""SELECT l.*, s.name as source_name, s.channel as source_channel
                        FROM collection_logs l
                        LEFT JOIN data_sources s ON l.source_id = s.id
                        {where_sql}
                        ORDER BY l.created_at DESC, l.id DESC
                        LIMIT %s OFFSET %s"""

        with cursor() as cur:
            cur.execute(count_sql, params)
            total = cur.fetchone()["cnt"]
            cur.execute(list_sql, params + [page_size, offset])
            rows = cur.fetchall()
        for r in rows:
            r["created_at"] = _fmt_time(r.get("created_at"))
        return rows, total

    @staticmethod
    def get_stats():
        """获取日志统计：总次数、成功、失败、平均耗时。"""
        sql = """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
                    AVG(duration_ms) as avg_duration
                 FROM collection_logs
                 WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"""
        with cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return {
                "total": row["total"] or 0,
                "success": row["success"] or 0,
                "failed": row["failed"] or 0,
                "avg_duration": round(row["avg_duration"] or 0, 1),
            }


def _fmt_time(val):
    """datetime 转本地时间字符串。"""
    if val is None:
        return None
    if isinstance(val, str):
        return val
    try:
        return val.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(val)
