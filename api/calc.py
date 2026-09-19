# -*- coding: utf-8 -*-
"""数据计算 API：SQL计算、表关联，生成新数据源。"""
import os
import json
import uuid
import sqlite3
from flask import Blueprint, request, jsonify
import pandas as pd

from db.dao import DataSourceDAO, CollectionLogDAO
from db.connection import BASE_DIR

bp = Blueprint("calc", __name__)

SOURCES_DIR = os.path.join(BASE_DIR, "data", "sources")
os.makedirs(SOURCES_DIR, exist_ok=True)


def _load_dataframe(source_id):
    """根据数据源ID加载 DataFrame。"""
    ds = DataSourceDAO.get_by_id(source_id)
    if not ds:
        return None, "数据源不存在"
    file_path = ds.get("file_path")
    if not file_path or not os.path.exists(file_path):
        return None, "源文件不存在"
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path, dtype=str)
        elif ext == ".csv":
            df = pd.read_csv(file_path, dtype=str, encoding="utf-8-sig")
        elif ext == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            df = pd.DataFrame(data)
        else:
            return None, f"不支持的文件格式: {ext}"
    except Exception as e:
        return None, f"读取文件失败: {str(e)}"
    return df, None


def _save_result(df, result_name, source_id, calc_type, config):
    """保存计算结果为新数据源。"""
    file_id = uuid.uuid4().hex
    save_path = os.path.join(SOURCES_DIR, f"{file_id}.xlsx")
    df.to_excel(save_path, index=False)

    src = DataSourceDAO.get_by_id(source_id) or {}
    sid = DataSourceDAO.create(
        name=result_name, channel="calculated",
        category_id=src.get("category_id"),
        file_path=save_path,
        config={
            "source": "calculation",
            "calc_type": calc_type,
            "original_source_id": source_id,
            "original_source_name": src.get("name"),
            **config,
        },
        status="ready",
    )
    DataSourceDAO.update_collect_result(
        sid, row_count=len(df), col_count=len(df.columns),
        sheet_names=["计算结果"], status="ready",
    )
    CollectionLogDAO.create(sid, "success", row_count=len(df), duration_ms=0)
    return sid


# ----------------------------------------------------------------------------
# SQL 计算
# ----------------------------------------------------------------------------
@bp.route("/calc/sql-preview", methods=["POST"])
def sql_preview():
    """预览 SQL 查询结果。

    JSON: {source_id, sql, table_name(可选,默认'data')}
    SQL 中表名用 {table_name} 引用，例如 SELECT * FROM data WHERE ...
    """
    data = request.get_json(force=True, silent=True) or {}
    source_id = data.get("source_id")
    sql = (data.get("sql") or "").strip()
    table_name = (data.get("table_name") or "data").strip()
    if source_id: source_id = int(source_id)
    if not source_id:
        return jsonify({"ok": False, "msg": "请选择数据源"}), 400
    if not sql:
        return jsonify({"ok": False, "msg": "请输入 SQL 语句"}), 400

    df, err = _load_dataframe(source_id)
    if err:
        return jsonify({"ok": False, "msg": err}), 400

    # 加载到内存 SQLite
    try:
        conn = sqlite3.connect(":memory:")
        df.to_sql(table_name, conn, index=False, if_exists="replace")
        result_df = pd.read_sql_query(sql, conn)
        conn.close()
    except Exception as e:
        return jsonify({"ok": False, "msg": f"SQL 执行失败: {str(e)}"}), 400

    # 取前20行预览
    limit = 20
    columns = result_df.columns.tolist()
    preview_rows = result_df.head(limit).fillna("").values.tolist()

    return jsonify({
        "ok": True,
        "data": {
            "columns": columns,
            "rows": preview_rows,
            "total_rows": len(result_df),
            "total_cols": len(columns),
        },
    })


@bp.route("/calc/sql-execute", methods=["POST"])
def sql_execute():
    """执行 SQL，生成新数据源。

    JSON: {source_id, sql, table_name, result_name}
    """
    data = request.get_json(force=True, silent=True) or {}
    source_id = data.get("source_id")
    sql = (data.get("sql") or "").strip()
    table_name = (data.get("table_name") or "data").strip()
    result_name = (data.get("result_name") or "").strip()
    if source_id: source_id = int(source_id)
    if not source_id:
        return jsonify({"ok": False, "msg": "请选择数据源"}), 400
    if not sql:
        return jsonify({"ok": False, "msg": "请输入 SQL 语句"}), 400

    src = DataSourceDAO.get_by_id(source_id)
    if not src:
        return jsonify({"ok": False, "msg": "数据源不存在"}), 400
    if not result_name:
        result_name = f"{src.get('name', '数据')}_SQL计算"

    df, err = _load_dataframe(source_id)
    if err:
        return jsonify({"ok": False, "msg": err}), 400

    try:
        conn = sqlite3.connect(":memory:")
        df.to_sql(table_name, conn, index=False, if_exists="replace")
        result_df = pd.read_sql_query(sql, conn)
        conn.close()
    except Exception as e:
        return jsonify({"ok": False, "msg": f"SQL 执行失败: {str(e)}"}), 400

    sid = _save_result(result_df, result_name, source_id, "sql", {"sql": sql, "table_name": table_name})

    return jsonify({
        "ok": True,
        "data": {"id": sid, "name": result_name, "row_count": len(result_df), "col_count": len(result_df.columns)},
    })


# ----------------------------------------------------------------------------
# 表关联
# ----------------------------------------------------------------------------
@bp.route("/calc/merge-preview", methods=["POST"])
def merge_preview():
    """预览表关联结果。

    JSON: {left_source_id, right_source_id, left_on, right_on, how(left/right/inner/outer)}
    """
    data = request.get_json(force=True, silent=True) or {}
    left_id = data.get("left_source_id")
    right_id = data.get("right_source_id")
    left_on = (data.get("left_on") or "").strip()
    right_on = (data.get("right_on") or "").strip()
    how = (data.get("how") or "left").strip()
    if left_id: left_id = int(left_id)
    if right_id: right_id = int(right_id)
    if not left_id or not right_id:
        return jsonify({"ok": False, "msg": "请选择主表和关联表"}), 400
    if not left_on or not right_on:
        return jsonify({"ok": False, "msg": "请选择关联字段"}), 400

    left_df, err = _load_dataframe(left_id)
    if err:
        return jsonify({"ok": False, "msg": f"主表加载失败: {err}"}), 400
    right_df, err = _load_dataframe(right_id)
    if err:
        return jsonify({"ok": False, "msg": f"关联表加载失败: {err}"}), 400

    if left_on not in left_df.columns:
        return jsonify({"ok": False, "msg": f"主表中不存在字段: {left_on}"}), 400
    if right_on not in right_df.columns:
        return jsonify({"ok": False, "msg": f"关联表中不存在字段: {right_on}"}), 400

    try:
        result_df = pd.merge(left_df, right_df, left_on=left_on, right_on=right_on, how=how, suffixes=("_左", "_右"))
    except Exception as e:
        return jsonify({"ok": False, "msg": f"关联失败: {str(e)}"}), 400

    limit = 20
    columns = result_df.columns.tolist()
    preview_rows = result_df.head(limit).fillna("").values.tolist()

    return jsonify({
        "ok": True,
        "data": {
            "columns": columns,
            "rows": preview_rows,
            "total_rows": len(result_df),
            "total_cols": len(columns),
            "left_rows": len(left_df),
            "right_rows": len(right_df),
        },
    })


@bp.route("/calc/merge-execute", methods=["POST"])
def merge_execute():
    """执行表关联，生成新数据源。"""
    data = request.get_json(force=True, silent=True) or {}
    left_id = data.get("left_source_id")
    right_id = data.get("right_source_id")
    left_on = (data.get("left_on") or "").strip()
    right_on = (data.get("right_on") or "").strip()
    how = (data.get("how") or "left").strip()
    result_name = (data.get("result_name") or "").strip()
    if left_id: left_id = int(left_id)
    if right_id: right_id = int(right_id)
    if not left_id or not right_id:
        return jsonify({"ok": False, "msg": "请选择主表和关联表"}), 400

    left_src = DataSourceDAO.get_by_id(left_id) or {}
    right_src = DataSourceDAO.get_by_id(right_id) or {}
    if not result_name:
        result_name = f"{left_src.get('name', '左表')}_关联_{right_src.get('name', '右表')}"

    left_df, err = _load_dataframe(left_id)
    if err:
        return jsonify({"ok": False, "msg": f"主表加载失败: {err}"}), 400
    right_df, err = _load_dataframe(right_id)
    if err:
        return jsonify({"ok": False, "msg": f"关联表加载失败: {err}"}), 400

    try:
        result_df = pd.merge(left_df, right_df, left_on=left_on, right_on=right_on, how=how, suffixes=("_左", "_右"))
    except Exception as e:
        return jsonify({"ok": False, "msg": f"关联失败: {str(e)}"}), 400

    sid = _save_result(result_df, result_name, left_id, "merge", {
        "left_source_id": left_id, "right_source_id": right_id,
        "left_on": left_on, "right_on": right_on, "how": how,
    })

    return jsonify({
        "ok": True,
        "data": {"id": sid, "name": result_name, "row_count": len(result_df), "col_count": len(result_df.columns)},
    })


# ----------------------------------------------------------------------------
# 计算任务列表
# ----------------------------------------------------------------------------
@bp.route("/calc/tasks", methods=["GET"])
def calc_tasks():
    """计算任务列表（所有 channel='calculated' 的数据源）。"""
    rows, total = DataSourceDAO.list_all(channel_filter="calculated")
    for r in rows:
        cfg = r.get("config") or {}
        if isinstance(cfg, str):
            try: cfg = json.loads(cfg)
            except: cfg = {}
        r["calc_type"] = cfg.get("calc_type", "")
        r["original_source_name"] = cfg.get("original_source_name", "")
        type_map = {"sql": "SQL计算", "merge": "表关联"}
        r["calc_type_text"] = type_map.get(cfg.get("calc_type", ""), cfg.get("calc_type", ""))
    return jsonify({"ok": True, "data": rows, "total": total})
