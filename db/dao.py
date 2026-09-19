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
    def list_all(category_id=None, keyword=None, filter_null=False, page=1, page_size=None):
        """获取数据源列表，支持分类筛选、关键词搜索（名称+原始文件名）、分页。
        filter_null=True 时筛选 category_id IS NULL（未分类）。"""
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
        # 总数
        count_sql = f"SELECT COUNT(*) AS cnt FROM data_sources ds LEFT JOIN categories c ON ds.category_id = c.id {where}"
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(count_sql, params)
                total = cur.fetchone()["cnt"]
        # 数据
        sql = f"SELECT ds.*, c.name AS category_name FROM data_sources ds LEFT JOIN categories c ON ds.category_id = c.id {where} ORDER BY ds.updated_at DESC, ds.id DESC"
        if page_size:
            offset = (page - 1) * page_size
            sql += " LIMIT %s OFFSET %s"
            params.extend([page_size, offset])
        with DataSourceDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        for r in rows:
            DataSourceDAO._deserialize(r)
        return rows, total

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
        """将 MySQL JSON 字段反序列化，datetime 转本地时间字符串（避免 jsonify 时区错误）。"""
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
        sql = """SELECT l.*, s.name as source_name, s.channel as source_channel
                 FROM collection_logs l
                 LEFT JOIN data_sources s ON l.source_id = s.id
                 WHERE l.id = %s"""
        with CollectionLogDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (log_id,))
                row = cur.fetchone()
                if row:
                    row["created_at"] = CollectionLogDAO._fmt_time(row.get("created_at"))
                return row

    @staticmethod
    def list_all(page=1, page_size=20, status=None, start_date=None, end_date=None):
        """全量日志列表，支持分页和筛选，关联数据源名称。"""
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

        with CollectionLogDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(count_sql, params)
                total = cur.fetchone()["cnt"]
                cur.execute(list_sql, params + [page_size, offset])
                rows = cur.fetchall()
                for r in rows:
                    r["created_at"] = CollectionLogDAO._fmt_time(r.get("created_at"))
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
        with CollectionLogDAO._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
                return {
                    "total": row["total"] or 0,
                    "success": row["success"] or 0,
                    "failed": row["failed"] or 0,
                    "avg_duration": round(row["avg_duration"] or 0, 1),
                }

    @staticmethod
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
