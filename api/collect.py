# -*- coding: utf-8 -*-
"""采集通道：Excel 上传解析、文件夹批量导入、重新采集、数据预览。"""
import os
import time
import uuid
import json
from flask import Blueprint, request, jsonify
from openpyxl import load_workbook

from db.dao import DataSourceDAO, CollectionLogDAO
from api.paths_config import SOURCES_DIR

bp = Blueprint("collect", __name__)

ALLOWED_EXTS = {".xlsx", ".xls", ".csv"}


# ----------------------------------------------------------------------------
# Excel 解析工具
# ----------------------------------------------------------------------------
def inspect_excel(file_path):
    """解析 Excel/CSV 文件，返回子表列表、总行数、总列数。

    Returns:
        dict: {
            "sheets": [{"name": str, "rows": int, "cols": int, "columns": [str]}],
            "total_rows": int,
            "total_cols": int,
        }
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        return _inspect_csv(file_path)
    return _inspect_xlsx(file_path)


def _inspect_xlsx(file_path):
    wb = load_workbook(file_path, read_only=True, data_only=True)
    sheets = []
    total_rows = 0
    total_cols = 0
    for name in wb.sheetnames:
        ws = wb[name]
        max_row = ws.max_row or 0
        max_col = ws.max_column or 0
        # 读取第一行作为字段名
        columns = []
        if max_row >= 1:
            for row in ws.iter_rows(min_row=1, max_row=1, max_col=max_col, values_only=True):
                columns = [str(c).strip() if c is not None else "" for c in row]
                break
        # 过滤空列名
        valid_cols = [c for c in columns if c]
        data_rows = max(max_row - 1, 0)
        sheets.append({
            "name": name,
            "rows": data_rows,
            "cols": len(valid_cols) or max_col,
            "columns": valid_cols,
        })
        total_rows += data_rows
        total_cols = max(total_cols, len(valid_cols) or max_col)
    wb.close()
    return {"sheets": sheets, "total_rows": total_rows, "total_cols": total_cols}


def _inspect_csv(file_path):
    import csv
    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return {"sheets": [{"name": "Sheet1", "rows": 0, "cols": 0, "columns": []}],
                "total_rows": 0, "total_cols": 0}
    columns = [c.strip() for c in rows[0]]
    valid_cols = [c for c in columns if c]
    return {
        "sheets": [{
            "name": "Sheet1",
            "rows": len(rows) - 1,
            "cols": len(valid_cols) or len(columns),
            "columns": valid_cols,
        }],
        "total_rows": len(rows) - 1,
        "total_cols": len(valid_cols) or len(columns),
    }


def save_uploaded_file(file_storage):
    """保存上传的文件到 data/sources/，返回绝对路径。"""
    original_name = file_storage.filename or "upload.xlsx"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_EXTS:
        ext = ".xlsx"
    safe_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(SOURCES_DIR, safe_name)
    file_storage.save(save_path)
    return save_path, original_name


# ----------------------------------------------------------------------------
# 路由
# ----------------------------------------------------------------------------
@bp.route("/collect/excel", methods=["POST"])
def collect_excel():
    """上传 Excel 文件并登记为数据源。

    Form-data: file (必填), name (可选, 默认文件名), category_id (可选)
    """
    start = time.time()
    if "file" not in request.files:
        return jsonify({"ok": False, "msg": "未上传文件"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400

    try:
        save_path, original_name = save_uploaded_file(file)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"文件保存失败: {e}"}), 500

    name = (request.form.get("name") or os.path.splitext(original_name)[0]).strip()
    category_id = request.form.get("category_id", type=int)

    # 解析
    try:
        info = inspect_excel(save_path)
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return jsonify({"ok": False, "msg": f"文件解析失败: {e}", "duration_ms": duration}), 400

    # 登记数据源
    sid = DataSourceDAO.create(
        name=name,
        channel="excel",
        category_id=category_id,
        file_path=save_path,
        config={"original_name": original_name},
        status="ready",
    )
    DataSourceDAO.update_collect_result(
        sid,
        row_count=info["total_rows"],
        col_count=info["total_cols"],
        sheet_names=[s["name"] for s in info["sheets"]],
        status="ready",
    )
    duration = int((time.time() - start) * 1000)
    CollectionLogDAO.create(sid, "success", row_count=info["total_rows"], duration_ms=duration)

    ds = DataSourceDAO.get_by_id(sid)
    ds["sheets_detail"] = info["sheets"]
    return jsonify({"ok": True, "data": ds, "duration_ms": duration})


def _human_size(size_bytes):
    """字节数转人类可读格式。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


@bp.route("/scan-folder", methods=["GET"])
def scan_folder():
    """扫描文件夹下的 Excel/CSV 文件，返回文件列表预览（不导入）。

    Query: path（文件夹路径）, recursive（是否递归，默认 false）
    """
    folder_path = (request.args.get("path") or "").strip()
    recursive = request.args.get("recursive", "false").lower() == "true"
    if not folder_path or not os.path.isdir(folder_path):
        return jsonify({"ok": False, "msg": "文件夹路径无效"}), 400

    files = []
    if recursive:
        for root, _, fnames in os.walk(folder_path):
            for fn in fnames:
                if os.path.splitext(fn)[1].lower() in ALLOWED_EXTS:
                    fp = os.path.join(root, fn)
                    stat = os.stat(fp)
                    files.append({
                        "name": fn,
                        "relative_path": os.path.relpath(fp, folder_path),
                        "size": stat.st_size,
                        "size_human": _human_size(stat.st_size),
                        "mtime_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                    })
    else:
        for fn in os.listdir(folder_path):
            fp = os.path.join(folder_path, fn)
            if os.path.isfile(fp) and os.path.splitext(fn)[1].lower() in ALLOWED_EXTS:
                stat = os.stat(fp)
                files.append({
                    "name": fn,
                    "relative_path": fn,
                    "size": stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "mtime_str": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                })

    files.sort(key=lambda x: x["mtime_str"], reverse=True)
    return jsonify({"ok": True, "files": files, "total": len(files)})


@bp.route("/collect/folder", methods=["POST"])
def collect_folder():
    """批量导入文件夹下的所有 Excel/CSV。

    JSON: {folder_path, category_id(可选), recursive(可选,默认false)}
    """
    data = request.get_json(force=True, silent=True) or {}
    folder_path = (data.get("folder_path") or "").strip()
    if not folder_path or not os.path.isdir(folder_path):
        return jsonify({"ok": False, "msg": "文件夹路径无效"}), 400

    category_id = data.get("category_id")
    recursive = bool(data.get("recursive", False))

    # 收集文件
    files = []
    if recursive:
        for root, _, fnames in os.walk(folder_path):
            for fn in fnames:
                if os.path.splitext(fn)[1].lower() in ALLOWED_EXTS:
                    files.append(os.path.join(root, fn))
    else:
        for fn in os.listdir(folder_path):
            fp = os.path.join(folder_path, fn)
            if os.path.isfile(fp) and os.path.splitext(fn)[1].lower() in ALLOWED_EXTS:
                files.append(fp)

    if not files:
        return jsonify({"ok": False, "msg": "文件夹中没有 Excel/CSV 文件"}), 400

    # 逐个导入
    results = []
    for fp in files:
        start = time.time()
        name = os.path.splitext(os.path.basename(fp))[0]
        try:
            info = inspect_excel(fp)
            sid = DataSourceDAO.create(
                name=name, channel="excel", category_id=category_id,
                file_path=fp, config={"source": "folder_import"}, status="ready",
            )
            DataSourceDAO.update_collect_result(
                sid, row_count=info["total_rows"], col_count=info["total_cols"],
                sheet_names=[s["name"] for s in info["sheets"]], status="ready",
            )
            duration = int((time.time() - start) * 1000)
            CollectionLogDAO.create(sid, "success", row_count=info["total_rows"], duration_ms=duration)
            results.append({"name": name, "ok": True, "rows": info["total_rows"], "id": sid})
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            results.append({"name": name, "ok": False, "error": str(e), "duration_ms": duration})

    success_count = sum(1 for r in results if r["ok"])
    return jsonify({
        "ok": True,
        "total": len(files),
        "success": success_count,
        "failed": len(files) - success_count,
        "results": results,
    })


@bp.route("/sources/<int:sid>/collect", methods=["POST"])
def recollect(sid):
    """重新采集数据源。"""
    ds = DataSourceDAO.get_by_id(sid)
    if not ds:
        return jsonify({"ok": False, "msg": "数据源不存在"}), 404
    if ds["channel"] in ("database", "crawler"):
        return jsonify({"ok": False, "msg": f"{ds['channel']} 通道待接入接口，暂不可用"}), 400
    if not ds.get("file_path") or not os.path.isfile(ds["file_path"]):
        return jsonify({"ok": False, "msg": "源文件不存在或已被移动"}), 400

    start = time.time()
    try:
        info = inspect_excel(ds["file_path"])
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        DataSourceDAO.update(sid, status="error")
        CollectionLogDAO.create(sid, "failed", error_msg=str(e), duration_ms=duration)
        return jsonify({"ok": False, "msg": f"重新采集失败: {e}"}), 400

    DataSourceDAO.update_collect_result(
        sid, row_count=info["total_rows"], col_count=info["total_cols"],
        sheet_names=[s["name"] for s in info["sheets"]], status="ready",
    )
    duration = int((time.time() - start) * 1000)
    CollectionLogDAO.create(sid, "success", row_count=info["total_rows"], duration_ms=duration)
    return jsonify({"ok": True, "data": DataSourceDAO.get_by_id(sid), "duration_ms": duration})


@bp.route("/sources/<int:sid>/preview", methods=["GET"])
def preview_source(sid):
    """预览数据源的某个子表前 N 行。

    Query: sheet (子表名, 默认第一个), limit (默认50)
    """
    ds = DataSourceDAO.get_by_id(sid)
    if not ds:
        return jsonify({"ok": False, "msg": "数据源不存在"}), 404
    if not ds.get("file_path") or not os.path.isfile(ds["file_path"]):
        return jsonify({"ok": False, "msg": "源文件不存在"}), 400

    sheet_name = request.args.get("sheet", "").strip()
    limit = min(request.args.get("limit", 50, type=int), 500)

    ext = os.path.splitext(ds["file_path"])[1].lower()
    try:
        if ext == ".csv":
            columns, rows = _preview_csv(ds["file_path"], limit)
        else:
            columns, rows = _preview_xlsx(ds["file_path"], sheet_name, limit)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"预览失败: {e}"}), 400

    return jsonify({"ok": True, "columns": columns, "rows": rows, "sheet": sheet_name or "Sheet1"})


def _preview_xlsx(file_path, sheet_name, limit):
    wb = load_workbook(file_path, read_only=True, data_only=True)
    if sheet_name and sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    else:
        ws = wb[wb.sheetnames[0]]
    max_col = ws.max_column or 0
    rows_iter = ws.iter_rows(max_row=limit + 1, max_col=max_col, values_only=True)
    all_rows = list(rows_iter)
    wb.close()
    if not all_rows:
        return [], []
    columns = [str(c).strip() if c is not None else f"列{i+1}" for i, c in enumerate(all_rows[0])]
    data_rows = []
    for r in all_rows[1:]:
        data_rows.append([("" if v is None else v) for v in r])
    return columns, data_rows


def _preview_csv(file_path, limit):
    import csv
    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        all_rows = []
        for i, row in enumerate(reader):
            if i > limit:
                break
            all_rows.append(row)
    if not all_rows:
        return [], []
    columns = [c.strip() for c in all_rows[0]]
    data_rows = [r for r in all_rows[1:]]
    return columns, data_rows

# ----------------------------------------------------------------------------
# 代码爬取通道
# ----------------------------------------------------------------------------
CRAWLER_JS_TEMPLATE = r"""// ============================================================
// 森宇后台数据抓取代码（由工作台生成）
// 使用方法：
//   1. 在浏览器中登录森宇后台，打开目标模块页面
//   2. 按 F12 打开控制台，粘贴本代码并回车
//   3. 等待抓取完成，浏览器自动下载 JSON 文件
//   4. 把下载的 JSON 文件上传到工作台
// ============================================================
(async () => {
  const API = '__API_URL__';
  const LIMIT = __LIMIT__;
  const CONCURRENCY = __CONCURRENCY__;
  const DELAY = __DELAY__;
  const OUTPUT_NAME = '__OUTPUT_NAME__';

  console.log('[抓取] 开始，目标:', API);
  const r0 = await fetch(API + '?page=1&limit=' + LIMIT, {
    credentials: 'include',
    headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json, text/javascript, */*; q=0.01'}
  });
  const j0 = await r0.json();
  const TOTAL = j0.count || 0;
  const totalPages = Math.ceil(TOTAL / LIMIT);
  console.log('[抓取] 总数:', TOTAL, '总页数:', totalPages);
  if (TOTAL === 0) { alert('未抓取到数据，请确认已登录且目标模块URL正确'); return; }

  const pageData = {};
  let idx = 0, doneCount = 0;
  async function fetchPage(page) {
    for (let retry = 0; retry < 4; retry++) {
      try {
        const resp = await fetch(API + '?page=' + page + '&limit=' + LIMIT, {
          credentials: 'include',
          headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json, text/javascript, */*; q=0.01'}
        });
        const json = await resp.json();
        if (json.code === 0 && json.data) return json.data;
      } catch (e) {
        console.warn('[抓取] 第' + page + '页失败，重试' + (retry + 1) + '/4');
        await new Promise(r => setTimeout(r, 2000));
      }
    }
    return [];
  }
  const workers = [];
  for (let w = 0; w < CONCURRENCY; w++) {
    workers.push((async () => {
      while (idx < totalPages) {
        const page = ++idx;
        pageData[page] = await fetchPage(page);
        doneCount++;
        console.log('[抓取] 进度: ' + doneCount + '/' + totalPages);
        await new Promise(r => setTimeout(r, DELAY));
      }
    })());
  }
  await Promise.all(workers);

  const allData = [];
  for (let p = 1; p <= totalPages; p++) { if (pageData[p]) allData.push(...pageData[p]); }
  console.log('[抓取] 完成，共', allData.length, '条');

  const blob = new Blob([JSON.stringify(allData, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = OUTPUT_NAME + '.json';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  alert('抓取完成！共 ' + allData.length + ' 条数据，已下载 ' + OUTPUT_NAME + '.json\\n请上传到工作台。');
})();
"""


@bp.route("/crawler/generate-code", methods=["POST"])
def crawler_generate_code():
    """根据配置生成 JS 抓取代码。"""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    api_url = (data.get("api_url") or "").strip()
    if not name:
        return jsonify({"ok": False, "msg": "请输入数据源名称"}), 400
    if not api_url:
        return jsonify({"ok": False, "msg": "请输入目标模块URL"}), 400
    limit = int(data.get("limit", 100))
    concurrency = int(data.get("concurrency", 2))
    delay = int(data.get("delay", 800))
    code = CRAWLER_JS_TEMPLATE
    code = code.replace("__API_URL__", api_url)
    code = code.replace("__LIMIT__", str(limit))
    code = code.replace("__CONCURRENCY__", str(concurrency))
    code = code.replace("__DELAY__", str(delay))
    code = code.replace("__OUTPUT_NAME__", name)
    return jsonify({"ok": True, "code": code})


@bp.route("/crawler/import-json", methods=["POST"])
def crawler_import_json():
    """上传爬虫抓取的 JSON 文件，解析并保存为数据源。"""
    if "file" not in request.files:
        return jsonify({"ok": False, "msg": "请上传 JSON 文件"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "msg": "文件名为空"}), 400
    name = (request.form.get("name") or os.path.splitext(f.filename)[0]).strip()
    category_id = request.form.get("category_id", type=int)
    try:
        content = f.read().decode("utf-8-sig")
        data = json.loads(content)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"JSON 解析失败: {str(e)}"}), 400
    if not isinstance(data, list):
        return jsonify({"ok": False, "msg": "JSON 必须是数组格式"}), 400
    if not data:
        return jsonify({"ok": False, "msg": "JSON 数组为空"}), 400
    columns = []
    seen = set()
    for row in data:
        if isinstance(row, dict):
            for k in row.keys():
                if k not in seen:
                    seen.add(k)
                    columns.append(str(k))
    row_count = len(data)
    col_count = len(columns)
    file_id = uuid.uuid4().hex
    save_path = os.path.join(SOURCES_DIR, f"{file_id}.json")
    with open(save_path, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)
    sid = DataSourceDAO.create(
        name=name, channel="crawler", category_id=category_id,
        file_path=save_path,
        config={"source": "crawler_import", "original_name": f.filename, "columns": columns},
        status="ready",
    )
    DataSourceDAO.update_collect_result(
        sid, row_count=row_count, col_count=col_count,
        sheet_names=["数据"], status="ready",
    )
    CollectionLogDAO.create(sid, "success", row_count=row_count, duration_ms=0)
    return jsonify({
        "ok": True,
        "data": {"id": sid, "name": name, "row_count": row_count, "col_count": col_count, "columns": columns},
    })
