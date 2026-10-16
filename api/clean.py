# -*- coding: utf-8 -*-
"""数据清洗 API：预览清洗结果、执行清洗生成新数据源、清洗任务列表。"""
import os
import json
import uuid
from flask import Blueprint, request, jsonify
import pandas as pd

from db.dao import DataSourceDAO, CollectionLogDAO
from db.connection import BASE_DIR
from services.dataframe_loader import load_dataframe_by_source_id

bp = Blueprint("clean", __name__)

SOURCES_DIR = os.path.join(BASE_DIR, "data", "sources")
os.makedirs(SOURCES_DIR, exist_ok=True)


def _load_dataframe(source_id):
    """根据数据源ID加载 DataFrame（已迁到 services.dataframe_loader）。"""
    ds = DataSourceDAO.get_by_id(source_id)
    if not ds:
        return None, "数据源不存在"
    return load_dataframe_by_source_id(source_id, ds.get("file_path") or "")


def _apply_rules(df, rules):
    """应用清洗规则，返回清洗后的 DataFrame 和变更统计。"""
    stats = {"rows_before": len(df), "rows_after": len(df), "changes": []}

    # 1. 格式统一
    fmt = rules.get("format", {})
    if fmt.get("trim"):
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str).str.strip()
        stats["changes"].append("去除首尾空格")
    if fmt.get("uppercase"):
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str).str.upper()
        stats["changes"].append("统一大写")
    if fmt.get("lowercase"):
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str).str.lower()
        stats["changes"].append("统一小写")

    # 2. 空值处理
    null_rule = rules.get("null", {})
    if null_rule.get("action") == "drop":
        before = len(df)
        subset = null_rule.get("columns") or None
        df = df.dropna(subset=subset, how="any")
        # 同时处理空字符串
        if subset:
            for col in subset:
                if col in df.columns:
                    df = df[df[col].astype(str).str.strip() != ""]
        else:
            df = df.replace("", pd.NA).dropna(how="any")
        stats["changes"].append(f"删除空值行（{before - len(df)}行）")
    elif null_rule.get("action") == "fill":
        fill_value = null_rule.get("fill_value", "")
        df = df.fillna(fill_value)
        df = df.replace("", fill_value)
        stats["changes"].append(f"空值填充为'{fill_value}'")

    # 3. 去重
    dedup = rules.get("dedup", {})
    if dedup.get("enabled"):
        before = len(df)
        subset = dedup.get("columns") or None
        df = df.drop_duplicates(subset=subset, keep="first")
        stats["changes"].append(f"去重（删除{before - len(df)}行）")

    stats["rows_after"] = len(df)
    return df, stats


@bp.route("/clean/preview", methods=["POST"])
def clean_preview():
    """预览清洗结果，返回清洗前后对比（前20行）。

    JSON: {source_id, rules: {format:{trim,uppercase,lowercase}, null:{action,columns,fill_value}, dedup:{enabled,columns}}}
    """
    data = request.get_json(force=True, silent=True) or {}
    source_id = data.get("source_id")
    if source_id: source_id = int(source_id)
    rules = data.get("rules", {})
    if not source_id:
        return jsonify({"ok": False, "msg": "请选择数据源"}), 400

    df, err = _load_dataframe(source_id)
    if err:
        return jsonify({"ok": False, "msg": err}), 400

    df_before = df.copy()
    df_after, stats = _apply_rules(df.copy(), rules)

    # 取前20行对比
    limit = 20
    before_rows = df_before.head(limit).fillna("").values.tolist()
    after_rows = df_after.head(limit).fillna("").values.tolist()
    columns = df_before.columns.tolist()

    return jsonify({
        "ok": True,
        "data": {
            "columns": columns,
            "before": before_rows,
            "after": after_rows,
            "stats": stats,
        },
    })


@bp.route("/clean/execute", methods=["POST"])
def clean_execute():
    """执行清洗，生成新数据源。

    JSON: {source_id, result_name, rules}
    """
    data = request.get_json(force=True, silent=True) or {}
    source_id = data.get("source_id")
    if source_id: source_id = int(source_id)
    result_name = (data.get("result_name") or "").strip()
    rules = data.get("rules", {})
    if not source_id:
        return jsonify({"ok": False, "msg": "请选择数据源"}), 400

    src = DataSourceDAO.get_by_id(source_id)
    if not src:
        return jsonify({"ok": False, "msg": "数据源不存在"}), 400
    if not result_name:
        result_name = f"{src.get('name', '数据')}_清洗后"

    df, err = _load_dataframe(source_id)
    if err:
        return jsonify({"ok": False, "msg": err}), 400

    df_after, stats = _apply_rules(df.copy(), rules)

    # 保存为 Excel
    file_id = uuid.uuid4().hex
    save_path = os.path.join(SOURCES_DIR, f"{file_id}.xlsx")
    df_after.to_excel(save_path, index=False)

    # 创建数据源记录
    sid = DataSourceDAO.create(
        name=result_name, channel="cleaned",
        category_id=src.get("category_id"),
        file_path=save_path,
        config={
            "source": "cleaning",
            "original_source_id": source_id,
            "original_source_name": src.get("name"),
            "rules": rules,
            "stats": stats,
        },
        status="ready",
    )
    DataSourceDAO.update_collect_result(
        sid, row_count=len(df_after), col_count=len(df_after.columns),
        sheet_names=["清洗结果"], status="ready",
    )
    CollectionLogDAO.create(sid, "success", row_count=len(df_after), duration_ms=0)

    return jsonify({
        "ok": True,
        "data": {
            "id": sid, "name": result_name,
            "row_count": len(df_after), "col_count": len(df_after.columns),
            "stats": stats,
        },
    })


@bp.route("/clean/tasks", methods=["GET"])
def clean_tasks():
    """清洗任务列表（所有 channel='cleaned' 的数据源）。"""
    rows, total = DataSourceDAO.list_all(channel_filter="cleaned")
    # 补充清洗统计信息
    for r in rows:
        cfg = r.get("config") or {}
        if isinstance(cfg, str):
            try: cfg = json.loads(cfg)
            except: cfg = {}
        r["clean_stats"] = cfg.get("stats", {})
        r["original_source_name"] = cfg.get("original_source_name", "")
        r["rules_summary"] = ", ".join(cfg.get("stats", {}).get("changes", []))
    return jsonify({"ok": True, "data": rows, "total": total})
