# -*- coding: utf-8 -*-
"""全表脱敏接口。

- POST /api/desensitize/scan  上传一个工作簿，返回每个子表命中的敏感列（预扫描）
- POST /api/desensitize/run   按 file_id + 输出目录执行脱敏，返回页面汇总报告

与分发模块的关系：只借用 uploads 临时目录和「选文件夹」接口（/api/browse_folder），
不改动原有 6 步分发流程，是纯增量功能。
"""
import os
import re
import uuid

from flask import Blueprint, jsonify, request

from api.paths_config import UPLOAD_DIR
from services.desensitize import build_out_path, run_desensitize, scan_workbook

bp = Blueprint("desensitize", __name__)

ALLOWED_EXTS = {".xlsx", ".xlsm", ".xls"}
# file_id 只允许 32 位十六进制 + 白名单扩展名，防路径穿越
FILE_ID_RE = re.compile(r"[a-f0-9]{32}\.(xlsx|xlsm|xls)")


@bp.route("/desensitize/scan", methods=["POST"])
def desensitize_scan():
    """上传文件并预扫描所有子表。"""
    if "file" not in request.files:
        return jsonify(ok=False, msg="未上传文件"), 400
    f = request.files["file"]
    original = f.filename or "upload.xlsx"
    ext = os.path.splitext(original)[1].lower()
    if ext not in ALLOWED_EXTS:
        return jsonify(ok=False, msg="仅支持 .xlsx / .xlsm / .xls 文件"), 400
    if ext == ".xls":
        return (
            jsonify(
                ok=False,
                msg=".xls 老格式不支持格式级改写，请在 Excel 里另存为 .xlsx 后重试",
            ),
            400,
        )

    file_id = uuid.uuid4().hex + ext
    path = os.path.join(UPLOAD_DIR, file_id)
    try:
        f.save(path)
    except Exception as e:
        return jsonify(ok=False, msg=f"文件保存失败：{e}"), 500

    try:
        plan = scan_workbook(path)
    except Exception as e:
        return jsonify(ok=False, msg=f"读取工作簿失败：{e}"), 400

    return jsonify(
        ok=True,
        file_id=file_id,
        filename=original,
        sheets=plan["sheets"],
        hit_sheets=plan["hit_sheets"],
        total_sheets=plan["total_sheets"],
    )


@bp.route("/desensitize/run", methods=["POST"])
def desensitize_run():
    """按预扫描结果执行脱敏，输出「一个文件多 sheet」。"""
    cfg = request.get_json(force=True, silent=True) or {}
    file_id = str(cfg.get("file_id") or "").strip()
    out_dir = str(cfg.get("output_dir") or "").strip()
    filename = str(cfg.get("filename") or "").strip()

    if not FILE_ID_RE.fullmatch(file_id):
        return jsonify(ok=False, msg="文件标识无效，请重新选择文件"), 400
    path = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.exists(path):
        return jsonify(ok=False, msg="源文件已失效，请重新选择"), 400
    if not out_dir:
        return jsonify(ok=False, msg="请先选择输出文件夹"), 400
    if not os.path.isdir(out_dir):
        return jsonify(ok=False, msg=f"输出文件夹不存在：{out_dir}"), 400

    try:
        plan = scan_workbook(path)
    except Exception as e:
        return jsonify(ok=False, msg=f"读取工作簿失败：{e}"), 400

    if plan["hit_sheets"] == 0:
        return (
            jsonify(
                ok=False,
                msg="所有子表都没有检测到敏感信息，未生成文件",
                sheets=[],
                skipped=[{"name": s["name"], "rows": s["rows"]} for s in plan["sheets"]],
                total_masked=0,
                out_sheets=0,
                total_sheets=plan["total_sheets"],
            ),
            200,
        )

    out_path = build_out_path(out_dir, filename or os.path.basename(path))
    try:
        report = run_desensitize(path, out_path, plan)
    except PermissionError:
        return jsonify(ok=False, msg="目标文件被占用（可能正在 Excel 中打开），请关闭后重试"), 400
    except Exception as e:
        return jsonify(ok=False, msg=f"脱敏失败：{e}"), 500

    if not report.get("ok"):
        return jsonify(report), 200
    return jsonify(report)
