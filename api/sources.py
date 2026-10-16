# -*- coding: utf-8 -*-
"""分类与数据源 CRUD 路由。"""
import os
import tkinter as tk
from tkinter import filedialog
from flask import Blueprint, request, jsonify
from db.dao import CategoryDAO, DataSourceDAO

bp = Blueprint("sources", __name__)


# ----------------------------------------------------------------------------
# 分类 CRUD
# ----------------------------------------------------------------------------
@bp.route("/categories", methods=["GET"])
def list_categories():
    """获取全部分类。"""
    cats = CategoryDAO.list_all()
    # 附带每个分类下的数据源数量
    for c in cats:
        c["source_count"] = CategoryDAO.count_sources(c["id"])
    return jsonify({"ok": True, "data": cats})


@bp.route("/categories", methods=["POST"])
def create_category():
    """新建分类。"""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "msg": "分类名称不能为空"}), 400
    if CategoryDAO.get_by_name(name):
        return jsonify({"ok": False, "msg": f"分类「{name}」已存在"}), 400
    sort = int(data.get("sort", 0))
    cid = CategoryDAO.create(name, sort=sort)
    return jsonify({"ok": True, "data": CategoryDAO.get_by_id(cid)})


@bp.route("/categories/<int:cid>", methods=["PUT"])
def update_category(cid):
    """更新分类。"""
    if not CategoryDAO.get_by_id(cid):
        return jsonify({"ok": False, "msg": "分类不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    sort = data.get("sort")
    if name is not None:
        name = name.strip()
        if not name:
            return jsonify({"ok": False, "msg": "分类名称不能为空"}), 400
        existing = CategoryDAO.get_by_name(name)
        if existing and existing["id"] != cid:
            return jsonify({"ok": False, "msg": f"分类「{name}」已存在"}), 400
    ok = CategoryDAO.update(cid, name=name, sort=sort)
    return jsonify({"ok": ok, "data": CategoryDAO.get_by_id(cid) if ok else None})


@bp.route("/categories/<int:cid>", methods=["DELETE"])
def delete_category(cid):
    """删除分类（该分类下无数据源时才可删）。"""
    if not CategoryDAO.get_by_id(cid):
        return jsonify({"ok": False, "msg": "分类不存在"}), 404
    if CategoryDAO.count_sources(cid) > 0:
        return jsonify({"ok": False, "msg": "该分类下仍有数据源，无法删除"}), 400
    ok = CategoryDAO.delete(cid)
    return jsonify({"ok": ok})


# ----------------------------------------------------------------------------
# 数据源 CRUD
# ----------------------------------------------------------------------------
@bp.route("/sources", methods=["GET"])
def list_sources():
    """获取数据源列表，支持分类筛选、关键词搜索、分页。
    category_id=none 表示筛选未分类；page/page_size 控制分页。"""
    cat_param = request.args.get("category_id", type=str)
    keyword = request.args.get("keyword", "").strip() or None
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 20, type=int)
    if page_size not in (20, 50, 100):
        page_size = 20
    filter_null = False
    category_id = None
    if cat_param == "none":
        filter_null = True
    elif cat_param is not None:
        try:
            category_id = int(cat_param)
        except ValueError:
            category_id = None
    sources, total = DataSourceDAO.list_all(
        category_id=category_id, keyword=keyword, filter_null=filter_null,
        page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    return jsonify({
        "ok": True,
        "data": sources,
        "pagination": {"page": page, "page_size": page_size, "total": total, "total_pages": total_pages},
        "stats": {
            "total": DataSourceDAO.count_all(),
            "ready": DataSourceDAO.count_by_status("ready"),
            "pending": DataSourceDAO.count_by_status("pending"),
            "failed": DataSourceDAO.count_by_status("failed"),
        },
    })


@bp.route("/sources/<int:sid>", methods=["GET"])
def get_source(sid):
    """获取数据源详情。"""
    ds = DataSourceDAO.get_by_id(sid)
    if not ds:
        return jsonify({"ok": False, "msg": "数据源不存在"}), 404
    return jsonify({"ok": True, "data": ds})


@bp.route("/sources", methods=["POST"])
def create_source():
    """新建数据源（登记元数据，不执行采集）。"""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    channel = (data.get("channel") or "").strip()
    if not name:
        return jsonify({"ok": False, "msg": "数据源名称不能为空"}), 400
    if channel not in ("excel", "folder", "database", "crawler"):
        return jsonify({"ok": False, "msg": "无效的采集通道"}), 400
    sid = DataSourceDAO.create(
        name=name,
        channel=channel,
        category_id=data.get("category_id"),
        file_path=data.get("file_path"),
        config=data.get("config"),
        status="pending",
    )
    return jsonify({"ok": True, "data": DataSourceDAO.get_by_id(sid)})


@bp.route("/sources/<int:sid>", methods=["PUT"])
def update_source(sid):
    """更新数据源。"""
    if not DataSourceDAO.get_by_id(sid):
        return jsonify({"ok": False, "msg": "数据源不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}
    allowed = ["name", "channel", "category_id", "file_path", "config", "status"]
    fields = {k: v for k, v in data.items() if k in allowed}
    ok = DataSourceDAO.update(sid, **fields)
    return jsonify({"ok": ok, "data": DataSourceDAO.get_by_id(sid) if ok else None})


@bp.route("/sources/<int:sid>", methods=["DELETE"])
def delete_source(sid):
    """删除数据源（collection_logs 级联删除）。"""
    if not DataSourceDAO.get_by_id(sid):
        return jsonify({"ok": False, "msg": "数据源不存在"}), 404
    ok = DataSourceDAO.delete(sid)
    return jsonify({"ok": ok})


# ----------------------------------------------------------------------------
# 数据源 inspect：从已登记数据源读取，返回与 /api/inspect 相同格式
# ----------------------------------------------------------------------------
@bp.route("/sources/<int:sid>/inspect", methods=["GET"])
def inspect_source(sid):
    """读取已登记数据源的子表与字段，返回格式与 /api/inspect 一致。"""
    ds = DataSourceDAO.get_by_id(sid)
    if not ds:
        return jsonify({"ok": False, "msg": "数据源不存在"}), 404
    file_path = ds.get("file_path")
    if not file_path or not os.path.isfile(file_path):
        return jsonify({"ok": False, "msg": "源文件不存在或已被移动"}), 400

    ext = os.path.splitext(file_path)[1].lower()
    sheets = []

    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(file_path, read_only=True, data_only=True)
        try:
            for name in wb.sheetnames:
                ws = wb[name]
                rows = []
                for i, row in enumerate(ws.iter_rows(max_row=301, values_only=True)):
                    rows.append(list(row))
                    if i >= 300:
                        break
                if not rows:
                    sheets.append({"name": name, "columns": [], "preview": [], "colMeta": {}})
                    continue
                raw_cols = [str(c).strip() if c is not None else "" for c in rows[0]]
                valid_idx = [i for i, c in enumerate(raw_cols) if c and not c.startswith("Unnamed")]
                cols = [raw_cols[i] for i in valid_idx]
                # 判断每列是否数值型（前300行样本）
                col_meta = {}
                for ci, col_name in enumerate(cols):
                    orig_i = valid_idx[ci]
                    num_cnt, total = 0, 0
                    for r in rows[1:]:
                        if orig_i < len(r):
                            v = r[orig_i]
                            if v is not None and str(v).strip() != "":
                                total += 1
                                try:
                                    float(v); num_cnt += 1
                                except (ValueError, TypeError):
                                    pass
                    is_num = total > 0 and num_cnt / total > 0.8
                    col_meta[col_name] = {"numeric": is_num, "measure": is_num}
                preview = [[(r[i] if i < len(r) and r[i] is not None else "") for i in valid_idx] for r in rows[1:4]]
                sheets.append({"name": name, "columns": cols, "preview": preview, "colMeta": col_meta})
        finally:
            wb.close()
    elif ext == ".csv":
        import csv
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            rows = []
            for i, row in enumerate(reader):
                rows.append(row)
                if i >= 300:
                    break
        if rows:
            cols = [c.strip() for c in rows[0]]
            col_meta = {c: {"numeric": False, "measure": False} for c in cols}
            preview = rows[1:4]
            sheets.append({"name": "Sheet1", "columns": cols, "preview": preview, "colMeta": col_meta})
        else:
            sheets.append({"name": "Sheet1", "columns": [], "preview": [], "colMeta": {}})
    else:
        return jsonify({"ok": False, "msg": f"不支持的文件格式: {ext}"}), 400

    return jsonify({"ok": True, "file_id": str(sid), "filename": ds["name"], "sheets": sheets})


# ----------------------------------------------------------------------------
# 系统文件夹选择对话框
# ----------------------------------------------------------------------------
@bp.route("/select-folder", methods=["GET"])
def select_folder():
    """弹出系统文件夹选择对话框，返回用户选择的文件夹路径。
    用于本地工作台，Flask 运行在用户本机，可直接调用系统对话框。"""
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    root.attributes("-topmost", True)  # 置顶
    try:
        folder_path = filedialog.askdirectory(title="选择要导入的文件夹")
    finally:
        root.destroy()
    return jsonify({"ok": True, "path": folder_path if folder_path else None})
