# -*- coding: utf-8 -*-
"""分类与数据源 CRUD 路由。"""
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
    """获取数据源列表，支持 category_id 筛选和 keyword 搜索。"""
    category_id = request.args.get("category_id", type=int)
    keyword = request.args.get("keyword", "").strip() or None
    sources = DataSourceDAO.list_all(category_id=category_id, keyword=keyword)
    return jsonify({
        "ok": True,
        "data": sources,
        "stats": {
            "total": DataSourceDAO.count_all(),
            "ready": DataSourceDAO.count_by_status("ready"),
            "pending": DataSourceDAO.count_by_status("pending"),
            "error": DataSourceDAO.count_by_status("error"),
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
