# -*- coding: utf-8 -*-
"""全表脱敏：一个工作簿多子表 → 自动识别 + 原地改值 + 格式完全保留。

为什么走 openpyxl 常规模式（read_only=False）
-------------------------------------------
分发模块为了 5 万行大文件能秒开，用的是 read_only 流式读取；但 read_only 的
ReadOnlyCell 拿不到 fill / 列宽 / 合并单元格，也无法就地写回。
「全表脱敏」的核心要求是**格式完全照搬**（颜色、列宽、行高、字体、合并单元格
都保留，只换敏感值），所以这里必须常规模式打开、只改目标单元格的值再 save ——
样式挂在工作表 XML 上，不随值变化，天然保留。

两级入口
--------
- scan_workbook(path)：快速预扫描（read_only，只读前 300 行），产出每个子表
  命中了哪些敏感列、每个列有哪些类型。前端"扫描结果"用它，几秒内返回。
- run_desensitize(src, out, ...)：正式执行（常规模式）。先扫一遍拿到同样的列
  清单，再逐列改值，最后保存。scan 与 run 共用 services/detect.py 的判定逻辑，
  保证"预览看到的"就是"执行改的"。

识别不看列名也生效：买家姓名、买家昵称这类字段里出现手机号，会被逐格片段扫描
抓出来，只打号码、姓名文字保留。
"""
import os
import re

from openpyxl import load_workbook

from services.detect import detect_sheet, mask_text

# 预扫描读多少行做内容判定。60 个非空值已经足够定性，读 300 行留冗余。
SCAN_ROWS = 300


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def safe_filename(name: str) -> str:
    """清洗 Windows 非法文件名字符（与 api/distribute.py 的 _safe_filename 同规则）。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(name)).strip(" .")
    return name or "未命名"


def build_out_path(out_dir: str, src_name: str, suffix: str = "_已脱敏") -> str:
    """生成输出文件路径；重名时追加 _2 / _3，不覆盖用户已有文件。"""
    stem, ext = os.path.splitext(os.path.basename(src_name))
    if ext.lower() not in (".xlsx", ".xlsm"):
        ext = ".xlsx"
    base = safe_filename(stem + suffix)
    path = os.path.join(out_dir, base + ext)
    n = 2
    while os.path.exists(path):
        path = os.path.join(out_dir, f"{base}_{n}{ext}")
        n += 1
    return path


def _header_text(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


# ----------------------------------------------------------------------------
# 预扫描（流式只读，快）
# ----------------------------------------------------------------------------
def scan_workbook(path: str) -> dict:
    """扫描整个工作簿，返回每个子表命中的敏感列。

    返回:
        {
          "sheets": [
            {"name": 表名, "rows": 数据行数, "empty": bool,
             "hits": [{index, col, kind, by, ratio, sample_in, sample_out}, ...]}
          ],
          "hit_sheets": 有敏感列的子表数,
          "total_sheets": 子表总数,
        }
    空表（没有表头或没有数据）也会返回，由调用方决定提示方式。
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        out = []
        for name in wb.sheetnames:
            ws = wb[name]
            headers = []
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    headers = [_header_text(v) for v in row]
                    continue
                if all(v is None or str(v).strip() == "" for v in row):
                    # 跳过整行空白，不算有效数据
                    continue
                rows.append(list(row))
                if len(rows) >= SCAN_ROWS:
                    break

            if not headers or not rows:
                out.append({"name": name, "rows": 0, "empty": True, "hits": []})
                continue

            hits = detect_sheet(headers, rows)
            out.append(
                {
                    "name": name,
                    "rows": int(ws.max_row or 0) - 1 if ws.max_row else 0,
                    "empty": False,
                    "hits": hits,
                }
            )
        hit_sheets = sum(1 for s in out if s["hits"])
        return {"sheets": out, "hit_sheets": hit_sheets, "total_sheets": len(out)}
    finally:
        wb.close()


# ----------------------------------------------------------------------------
# 正式执行（常规模式，保留格式）
# ----------------------------------------------------------------------------
def run_desensitize(src_path: str, out_path: str, plan: dict = None) -> dict:
    """按扫描结果改写敏感列，输出一个新工作簿。

    src_path: 源文件绝对路径
    out_path: 输出文件绝对路径
    plan:     scan_workbook 的返回；不传则现场扫一遍（保证与预览一致）

    返回执行报告（页面汇总用，不写进文件）：
        {
          "ok": bool, "out_path": ..., "filename": ...,
          "sheets": [{"name", "rows", "cols":[{col,kind,count}], "masked": n}],
          "skipped": [{"name", "rows"}],
          "total_masked": n, "out_sheets": n, "total_sheets": n,
        }
    """
    if plan is None:
        plan = scan_workbook(src_path)
    by_sheet = {s["name"]: s for s in plan["sheets"]}

    keep_vba = src_path.lower().endswith(".xlsm")
    wb = load_workbook(src_path, keep_vba=keep_vba)

    report = {
        "ok": True,
        "out_path": out_path,
        "filename": os.path.basename(out_path),
        "sheets": [],
        "skipped": [],
        "total_masked": 0,
        "total_sheets": len(wb.sheetnames),
        "out_sheets": 0,
    }

    try:
        for name in list(wb.sheetnames):
            ws = wb[name]
            info = by_sheet.get(name) or {}
            hits = info.get("hits") or []
            if not hits:
                # 没有敏感信息：不输出这个子表
                report["skipped"].append({"name": name, "rows": info.get("rows", 0)})
                wb.remove(ws)
                continue

            col_report = []
            masked_total = 0
            for h in hits:
                idx = int(h["index"]) + 1
                kinds = h.get("kinds") or []
                if not kinds:
                    continue
                strict_map = {k["kind"]: (k["by"] == "content") for k in kinds}
                count = 0
                # 只遍历这一列，避免 5 万行 × 20 列的全表扫描；
                # 一列里的多个类型在同一次遍历里串行应用。
                for row in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                    cell = row[0]
                    old = cell.value
                    if old is None:
                        continue
                    new = old
                    for k in kinds:
                        new = mask_text(k["kind"], new, strict=strict_map[k["kind"]])
                    if new != old:
                        cell.value = new
                        # 打码后一律是文本（含 *）。原列若是数值格式，Excel 会把
                        # 长数字显示成 1.38E+10 或丢掉前导零，统一改文本格式。
                        try:
                            cell.number_format = "@"
                        except Exception:
                            pass
                        count += 1
                if count:
                    col_report.append(
                        {
                            "col": h["col"],
                            "kinds": [k["kind"] for k in kinds],
                            "count": count,
                        }
                    )
                    masked_total += count

            report["sheets"].append(
                {
                    "name": name,
                    "rows": info.get("rows", max(int(ws.max_row or 1) - 1, 0)),
                    "cols": col_report,
                    "masked": masked_total,
                }
            )
            report["out_sheets"] += 1
            report["total_masked"] += masked_total

        if report["out_sheets"] == 0:
            wb.close()
            return {
                "ok": False,
                "msg": "所有子表都没有检测到敏感信息，未生成文件",
                "sheets": [],
                "skipped": report["skipped"],
                "total_masked": 0,
                "out_sheets": 0,
                "total_sheets": report["total_sheets"],
            }

        wb.save(out_path)
        return report
    finally:
        try:
            wb.close()
        except Exception:
            pass
