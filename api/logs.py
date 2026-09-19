# -*- coding: utf-8 -*-
"""运行历史 API：采集/分发日志列表、统计、详情。"""
from flask import Blueprint, request, jsonify
from db.dao import CollectionLogDAO

bp = Blueprint("logs", __name__)


@bp.route("/logs", methods=["GET"])
def list_logs():
    """日志列表，支持分页和筛选。

    参数：page(默认1), page_size(默认20), status(success/failed), start_date, end_date
    """
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 20, type=int)
    status = request.args.get("status")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    rows, total = CollectionLogDAO.list_all(
        page=page, page_size=page_size,
        status=status, start_date=start_date, end_date=end_date,
    )
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1

    return jsonify({
        "ok": True,
        "data": rows,
        "pagination": {"page": page, "page_size": page_size, "total": total, "total_pages": total_pages},
    })


@bp.route("/logs/stats", methods=["GET"])
def logs_stats():
    """近7天日志统计。"""
    stats = CollectionLogDAO.get_stats()
    return jsonify({"ok": True, "data": stats})


@bp.route("/logs/<int:log_id>", methods=["GET"])
def get_log(log_id):
    """日志详情。"""
    log = CollectionLogDAO.get_by_id(log_id)
    if not log:
        return jsonify({"ok": False, "msg": "日志不存在"}), 404
    return jsonify({"ok": True, "data": log})
