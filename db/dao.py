# -*- coding: utf-8 -*-
"""数据访问层（DAO）：categories / data_sources / collection_logs 的 CRUD。"""
import json
from datetime import datetime
from db.connection import get_connection


class BaseDAO:
    """DAO 基类：封装连接获取。"""

    @staticmethod
    def _conn():
        return get_connection()


class CategoryDAO(BaseDAO):
    """数据源分类 DAO。"""

    @staticmethod
    def list_all():
        """获取全部分类，按 sort 升序、id 升序。"""
        sql = "SELECT * FROM categories ORDER BY sort ASC, id ASC"
        with CategoryDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchall()

    @staticmethod
    def get_by_id(category_id):
        sql = "SELECT * FROM categories WHERE id = %s"
        with CategoryDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (category_id,))
                return cur.fetchone()

    @staticmethod
    def get_by_name(name):
        sql = "SELECT * FROM categories WHERE name = %s"
        with CategoryDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (name,))
                return cur.fetchone()

    @staticmethod
    def create(name, sort=0):
        """新建分类，返回新 ID。"""
        sql = "INSERT INTO categories (name, sort) VALUES (%s, %s)"
        with CategoryDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (name, sort))
                conn.commit()
                return cur.lastrowid

    @staticmethod
    def update(category_id, name=None, sort=None):
        """更新分类，仅更新传入的非 None 字段。"""
        sets, params = [], []
        if name is not None:
            sets.append("name = %s"); params.append(name)
        if sort is not None:
            sets.append("sort = %s"); params.append(sort)
        if not sets:
            return False
        params.append(category_id)
        sql = f"UPDATE categories SET {', '.join(sets)} WHERE id = %s"
        with CategoryDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
                return cur.rowcount > 0

    @staticmethod
    def count_sources(category_id):
        """统计该分类下的数据源数量。"""
        sql = "SELECT COUNT(*) AS cnt FROM data_sources WHERE category_id = %s"
        with CategoryDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (category_id,))
                return cur.fetchone()["cnt"]

    @staticmethod
    def delete(category_id):
        """删除分类（仅当该分类下无数据源时）。返回是否成功。"""
        if CategoryDAO.count_sources(category_id) > 0:
            return False
        sql = "DELETE FROM categories WHERE id = %s"
        with CategoryDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (category_id,))
                conn.commit()
                return cur.rowcount > 0


class DataSourceDAO(BaseDAO):
    """数据源 DAO。"""

    @staticmethod
    def list_all(category_id=None, keyword=None, filter_null=False):
        """获取数据源列表，支持按分类筛选和关键词搜索（名称模糊匹配）。
        filter_null=True 时筛选 category_id IS NULL（未分类）。"""
        sql = "SELECT ds.*, c.name AS category_name FROM data_sources ds LEFT JOIN categories c ON ds.category_id = c.id WHERE 1=1"
        params = []
        if filter_null:
            sql += " AND ds.category_id IS NULL"
        elif category_id is not None:
            sql += " AND ds.category_id = %s"
            params.append(category_id)
        if keyword:
            sql += " AND ds.name LIKE %s"
            params.append(f"%{keyword}%")
        sql += " ORDER BY ds.updated_at DESC, ds.id DESC"
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        # 反序列化 JSON 字段
        for r in rows:
            DataSourceDAO._deserialize(r)
        return rows

    @staticmethod
    def get_by_id(source_id):
        sql = "SELECT ds.*, c.name AS category_name FROM data_sources ds LEFT JOIN categories c ON ds.category_id = c.id WHERE ds.id = %s"
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (source_id,))
                row = cur.fetchone()
        if row:
            DataSourceDAO._deserialize(row)
        return row

    @staticmethod
    def _deserialize(row):
        """将 MySQL JSON 字段反序列化为 Python 对象。"""
        for key in ("config", "sheet_names"):
            val = row.get(key)
            if isinstance(val, str):
                try:
                    row[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass

    @staticmethod
    def create(name, channel, category_id=None, file_path=None, config=None,
               status="pending"):
        """新建数据源，返回新 ID。"""
        config_json = json.dumps(config, ensure_ascii=False) if config is not None else None
        sql = ("INSERT INTO data_sources (name, channel, category_id, file_path, config, status) "
               "VALUES (%s, %s, %s, %s, %s, %s)")
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (name, channel, category_id, file_path, config_json, status))
                conn.commit()
                return cur.lastrowid

    @staticmethod
    def update(source_id, **fields):
        """更新数据源。category_id 允许设置为 None（清空分类）。"""
        allowed = {"name", "channel", "category_id", "file_path", "config",
                   "row_count", "col_count", "sheet_names", "status"}
        nullable = {"category_id"}  # 允许显式设为 NULL 的字段
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
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
                return True  # 执行成功即返回 True（相同值更新也视为成功）

    @staticmethod
    def update_collect_result(source_id, row_count, col_count, sheet_names=None, status="ready"):
        """采集完成后更新行数、列数、子表列表、状态和最后采集时间。"""
        sheets_json = json.dumps(sheet_names, ensure_ascii=False) if sheet_names else None
        sql = ("UPDATE data_sources SET row_count=%s, col_count=%s, sheet_names=%s, "
               "status=%s, last_collected_at=%s WHERE id=%s")
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (row_count, col_count, sheets_json, status, datetime.now(), source_id))
                conn.commit()
                return cur.rowcount > 0

    @staticmethod
    def delete(source_id):
        """删除数据源（collection_logs 级联删除）。"""
        sql = "DELETE FROM data_sources WHERE id = %s"
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (source_id,))
                conn.commit()
                return cur.rowcount > 0

    @staticmethod
    def count_all():
        sql = "SELECT COUNT(*) AS cnt FROM data_sources"
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchone()["cnt"]

    @staticmethod
    def count_by_status(status):
        sql = "SELECT COUNT(*) AS cnt FROM data_sources WHERE status = %s"
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (status,))
                return cur.fetchone()["cnt"]


class CollectionLogDAO(BaseDAO):
    """采集日志 DAO。"""

    @staticmethod
    def list_by_source(source_id, limit=50):
        sql = "SELECT * FROM collection_logs WHERE source_id = %s ORDER BY created_at DESC, id DESC LIMIT %s"
        with CollectionLogDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (source_id, limit))
                return cur.fetchall()

    @staticmethod
    def create(source_id, status, row_count=0, error_msg=None, duration_ms=0):
        sql = ("INSERT INTO collection_logs (source_id, status, row_count, error_msg, duration_ms) "
               "VALUES (%s, %s, %s, %s, %s)")
        with CollectionLogDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (source_id, status, row_count, error_msg, duration_ms))
                conn.commit()
                return cur.lastrowid

    @staticmethod
    def get_by_id(log_id):
        sql = "SELECT * FROM collection_logs WHERE id = %s"
        with CollectionLogDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (log_id,))
                return cur.fetchone()
