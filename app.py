# -*- coding: utf-8 -*-
"""
Excel 智能分表脱敏工作台（本地网页版）
流程：选文件 -> 选子表 -> 勾保留字段 -> 勾脱敏字段(每列可选规则)
      -> 选拆分列 -> 写文件名后缀 -> 选输出文件夹 -> 一键拆分
数据全程只在本机处理，不上传外网。
"""
import os
import re
import uuid
import json
import threading
import traceback

import pandas as pd
from flask import Flask, request, jsonify, render_template

from api.sources import bp as sources_bp
from api.collect import bp as collect_bp
from api.logs import bp as logs_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
CONFIG_DIR = os.path.join(BASE_DIR, "configs")  # 保存的拆分配置模板（JSON）
os.makedirs(CONFIG_DIR, exist_ok=True)

app = Flask(__name__)

app.register_blueprint(sources_bp, url_prefix="/api")
app.register_blueprint(collect_bp, url_prefix="/api")
app.register_blueprint(logs_bp, url_prefix="/api")
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 最大 512MB

_tk_lock = threading.Lock()


# ----------------------------------------------------------------------------
# 脱敏引擎
# ----------------------------------------------------------------------------
def _digits(s: str) -> str:
    return re.sub(r"\D", "", str(s))


def mask_phone(v):
    """手机号：保留前3后4，其余位用 *（标准11位 => 138****5678）"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    d = _digits(s)
    if len(d) >= 7:
        return d[:3] + "*" * (len(d) - 7) + d[-4:]
    return "*" * len(s)  # 异常号码：整体遮罩


def mask_idcard(v):
    """身份证：保留前4后4，其余用 *（18位 => 3307**********1234）"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    if len(s) >= 8:
        return s[:4] + "*" * (len(s) - 8) + s[-4:]
    return "*" * len(s)


def mask_name(v):
    """姓名：保留姓（第一个字符），其余用 *"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    if len(s) == 1:
        return s
    return s[0] + "*" * (len(s) - 1)


def mask_address(v):
    """详细地址：保留到区/县(县级市)，其后统一打 ****"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    # 先定位省级（省 / 自治区 / 特别行政区 / 直辖市的第一个“市”）
    prov = re.search(r"^.*?(省|自治区|特别行政区|市)", s)
    start = prov.end() if prov else 0
    rest = s[start:]
    head = None
    m = re.search(r"^.*?[区县旗]", rest)
    if m:
        head = s[: start + len(m.group(0))]
    else:
        # 没有区/县：按“市”判断，取到县级市（省内地级市之后的第二个市）
        city_idx = [i for i, c in enumerate(rest) if c == "市"]
        if len(city_idx) >= 2:
            head = s[: start + city_idx[1] + 1]
        elif len(city_idx) == 1:
            head = s[: start + city_idx[0] + 1]
    if not head:
        head = s[: min(6, len(s))]  # 兜底：保留前 6 字
    if len(head) >= len(s):
        return s  # 本身就没有更细的地址，原样返回
    return head + "****"


def mask_keep_ab(v, a=0, b=0):
    """通用：保留前 a 位、后 b 位，其余用 *"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    a, b = int(a or 0), int(b or 0)
    if len(s) <= a + b:
        return "*" * len(s)
    return s[:a] + "*" * (len(s) - a - b) + (s[-b:] if b else "")


def mask_replace(v, text="***"):
    """整列非空值统一替换为指定文字"""
    if v is None:
        return v
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    return text or "***"


RULES = {
    "phone": ("手机号(前3后4)", mask_phone),
    "idcard": ("身份证(前4后4)", mask_idcard),
    "address": ("详细地址(保留到区县)", mask_address),
    "name": ("姓名(留姓)", mask_name),
}


def apply_mask(series: pd.Series, rule: dict) -> pd.Series:
    t = rule.get("type")
    if t == "keep_ab":
        return series.map(lambda x: mask_keep_ab(x, rule.get("a", 0), rule.get("b", 0)))
    if t == "replace":
        return series.map(lambda x: mask_replace(x, rule.get("text", "***")))
    fn = RULES.get(t, (None, mask_replace))[1]
    return series.map(fn)


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def _safe_filename(name: str) -> str:
    """清洗 Windows 非法文件名字符"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(name)).strip(" .")
    return name or "未命名"


def _excel_row_number(i: int) -> int:
    """DataFrame 下标 -> Excel 实际行号（第1行为表头）"""
    return i + 2


def _is_multi_value(v: str):
    """检测一格内疑似多个值（含常见分隔符且能分成多段）"""
    s = str(v).strip()
    if not s:
        return False
    parts = re.split(r"[,，、;；/|\+\n\r]+", s)
    parts = [p.strip() for p in parts if p.strip()]
    return len(parts) > 1


def _to_num(s: pd.Series) -> pd.Series:
    """把 '￥1,200.50元' 之类的文本安全转成数值，转不了的变 NaN。"""
    cleaned = (
        s.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("，", "", regex=False)
        .str.replace("¥", "", regex=False)
        .str.replace("￥", "", regex=False)
        .str.replace("元", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


_ID_WORDS = re.compile(r"手机|电话|身份证|证件|编号|编码|单号|流水|卡号|账号|税号|工号|学号|邮编|号码|号|码")


def _col_meta(cols, df_sample):
    """根据采样数据判定每列类型：numeric=多为数字；measure=可求和的真实数值（排除数字编号）。
    unique=该列不同取值数（用于推荐“最有区分度”的分组维度）。"""
    meta = {}
    for c in cols:
        ne = df_sample[c].astype(str).str.strip()
        ne = ne[ne != ""]
        ratio = float(pd.notna(_to_num(ne)).mean()) if len(ne) else 0.0
        numeric = ratio >= 0.8
        is_id = bool(_ID_WORDS.search(str(c))) or re.search(r"(^|[^a-z])id([^a-z]|$)", str(c).lower()) is not None
        uniq = int(ne.nunique()) if len(ne) else 0
        meta[c] = {"numeric": numeric, "measure": bool(numeric and not is_id), "unique": uniq}
    return meta


def _sheet_to_df(wb, name, nrows=None):
    """openpyxl 流式只读：把单个子表读成字符串 DataFrame，大文件不整体入内存。"""
    ws = wb[name]
    it = ws.iter_rows(values_only=True)
    try:
        header = next(it)
    except StopIteration:
        return pd.DataFrame()
    # 只保留“表头非空”的列；表头为空的列视为无数据列，连同其下内容一并忽略
    keep_idx = [i for i, h in enumerate(header) if h is not None and str(h).strip() != ""]
    if not keep_idx:
        return pd.DataFrame()
    # 列名去重：重复列名（如两个“备注”）统一改成 列名、列名.1 …
    cols = []
    seen = {}
    for i in keep_idx:
        name = str(header[i]).strip()
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        cols.append(name)
    data = []
    excel_rows = []
    empty_streak = 0
    valid_count = 0
    for i, row in enumerate(it):
        if row is None:
            continue
        vals = list(row)
        picked = []
        has_value = False
        for ci in keep_idx:
            v = vals[ci] if ci < len(vals) else None
            sv = "" if v is None else str(v).strip()
            if sv != "":
                has_value = True
            picked.append("" if v is None else str(v))
        if not has_value:
            # 整行全空：跳过；连续 100 行全空视为表尾（Excel 已用范围常虚标到百万行）
            empty_streak += 1
            if empty_streak >= 100:
                break
            continue
        empty_streak = 0
        data.append(picked)
        excel_rows.append(i + 2)  # 表头为第1行，首个数据行=第2行
        valid_count += 1
        if nrows is not None and valid_count >= nrows:
            break
    frame = pd.DataFrame(data, columns=cols)
    frame.index = excel_rows  # 用 Excel 真实行号做下标，便于脏数据定位
    return frame


def _clean(d):
    """清洗 DataFrame：去掉空表头列、全空行，列名去空白，转字符串，保留 Excel 真实行号。"""
    d = d.loc[
        :,
        [c for c in d.columns if str(c).strip() != "" and not str(c).startswith("Unnamed:")],
    ]
    d = d.dropna(how="all")
    d.columns = [str(c).strip() for c in d.columns]
    d = d.fillna("")
    d["__row__"] = [int(i) for i in d.index]  # 保留 Excel 真实行号
    return d


# ----------------------------------------------------------------------------
# 数据读取缓存：预览与拆分共用，大文件只解析一次
# ----------------------------------------------------------------------------
_df_cache = {}
_CACHE_MAX = 2


def _prepare_df(path, file_id, ext, merge_sheets, source_col=None, source_map=None):
    """读取并合并所选子表（含多表合并的「来源」列），带进程内缓存。"""
    cached = _df_cache.get(file_id)
    if cached is not None:
        return cached
    frames = []
    if ext in (".xlsx", ".xlsm"):
        # 流式只读：一次打开，逐张读取选中子表
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            for name in merge_sheets:
                frames.append(_clean(_sheet_to_df(wb, name)))
        finally:
            wb.close()
    else:
        for name in merge_sheets:
            d = pd.read_excel(path, sheet_name=name, dtype=str)
            d.index = [int(i) + 2 for i in d.index]
            frames.append(_clean(d))
    add_source = len(merge_sheets) > 1
    if add_source:
        df = pd.concat(frames, keys=merge_sheets, sort=False)
        # 来源列名 / 每张子表的来源值均可自定义
        src_col = str(source_col or "来源").strip() or "来源"
        if src_col in df.columns:
            src_col = src_col + "_合并"
        src_map = source_map or {}
        sheet_names = df.index.get_level_values(0)
        df[src_col] = [str(src_map.get(str(s), s)) for s in sheet_names]
        df = df.reset_index(drop=True)
    else:
        src_col = None
        df = pd.concat(frames, ignore_index=True, sort=False)
    df = df.fillna("")
    # 全部按字符串并去除两端空格
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    result = (df, (add_source, src_col, source_map or {}))
    _df_cache[file_id] = result
    while len(_df_cache) > _CACHE_MAX:
        _df_cache.pop(next(iter(_df_cache)))
    return result


def build_summary(sub: pd.DataFrame, scfg: dict):
    """聚合：计数(行数/去重)+求和，末行合计；支持分组列别名；无分组时整表一行总计。"""
    groups = scfg.get("groups") or []
    graw = [g for g in groups if g.get("col") in sub.columns]
    gcols = [g["col"] for g in graw]
    galias = {}
    for g in graw:
        al = str(g.get("label") or "").strip()
        galias[g["col"]] = al if al else g["col"]
    sums = [s for s in (scfg.get("sums") or []) if s.get("col") in sub.columns]
    counts = [c for c in (scfg.get("counts") or []) if c.get("col") in sub.columns]

    work = sub.copy()
    agg, label_order = {}, []
    for c in counts:
        lab = c.get("label") or (c["col"] + ("数" if c.get("distinct") else "行数"))
        agg[lab] = (c["col"], "nunique" if c.get("distinct") else "count")
        label_order.append(("count", lab))
    for idx, s in enumerate(sums):
        lab = s.get("label") or (s["col"] + "合计")
        key = f"__num_{idx}"
        work[key] = _to_num(work[s["col"]])
        agg[lab] = (key, "sum")
        label_order.append(("sum", lab))
    if not agg:
        return None

    metric_cols = [lab for _, lab in label_order]

    def _whole_row(frame):
        row = {}
        for kind, lab in label_order:
            col, how = agg[lab]
            if how == "sum":
                row[lab] = round(float(pd.to_numeric(frame[col], errors="coerce").sum()), 2)
            elif how == "nunique":
                row[lab] = int(frame[col].nunique())
            else:
                row[lab] = int(frame[col].count())
        return row

    if not gcols:  # 无分组维度：整张表只输出一行总计
        return pd.DataFrame([_whole_row(work)])[metric_cols]

    res = work.groupby(gcols, dropna=False, sort=False).agg(**agg).reset_index()
    for kind, lab in label_order:
        if kind == "sum":
            res[lab] = pd.to_numeric(res[lab], errors="coerce").fillna(0).round(2)
        else:
            res[lab] = pd.to_numeric(res[lab], errors="coerce").fillna(0).astype(int)

    sort_label = scfg.get("sort_label") or ""
    sort_desc = bool(scfg.get("sort_desc", True))
    alias2col = {a: c for c, a in galias.items()}
    if sort_label in metric_cols:
        sort_key = sort_label
    elif sort_label in galias.values():
        sort_key = alias2col[sort_label]
    else:
        sort_key = None
    if sort_key is not None:
        res = res.sort_values(
            by=sort_key, ascending=not sort_desc, kind="mergesort"
        ).reset_index(drop=True)

    total = _whole_row(work)
    for _gi, g in enumerate(gcols):
        total[g] = "合计" if _gi == 0 else ""
    res = pd.concat([res, pd.DataFrame([total])], ignore_index=True)
    res = res[gcols + metric_cols].rename(columns=galias)
    return res


def _autofit_ws(ws, bold_last=False):
    """列宽按内容自适应（中文按双宽度）、表头加粗、行高自动；可选末行加粗。"""
    from openpyxl.styles import Font

    for cell in ws[1]:
        cell.font = Font(bold=True)
    if bold_last and ws.max_row >= 2:
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)

    widths = {}
    for ridx, row in enumerate(ws.iter_rows()):
        if ridx > 400:  # 最多采样 400 行估算宽度，兼顾大表性能
            break
        for c in row:
            if c.value is None:
                continue
            w = 0
            for line in str(c.value).split("\n"):
                w = max(w, sum(2 if ord(ch) > 127 else 1 for ch in line))
            widths[c.column_letter] = max(widths.get(c.column_letter, 9), w + 3)
    for letter, w in widths.items():
        ws.column_dimensions[letter].width = min(max(w, 9), 52)
    ws.row_dimensions[1].height = 22  # 表头略高；数据行保持自动行高


# ----------------------------------------------------------------------------
# 页面
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/inspect", methods=["POST"])
def inspect():
    """上传 Excel，返回所有子表及其字段名"""
    f = request.files.get("file")
    if not f:
        return jsonify(ok=False, msg="未收到文件"), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".xlsx", ".xlsm", ".xls"):
        return jsonify(ok=False, msg="仅支持 .xlsx/.xlsm/.xls 文件"), 400

    file_id = uuid.uuid4().hex + ext
    path = os.path.join(UPLOAD_DIR, file_id)
    f.save(path)

    try:
        sheets = []
        if ext in (".xlsx", ".xlsm"):
            # 流式只读：只取表头 + 前 300 行，大文件也能秒开，不整体载入内存
            from openpyxl import load_workbook

            wb = load_workbook(path, read_only=True, data_only=True)
            try:
                for name in wb.sheetnames:
                    sample = _sheet_to_df(wb, name, nrows=300)
                    cols = [str(c) for c in sample.columns]
                    col_meta = (
                        _col_meta(cols, sample)
                        if len(sample)
                        else {c: {"numeric": False, "measure": False} for c in cols}
                    )
                    preview = sample.head(3).values.tolist()
                    sheets.append(
                        {"name": name, "columns": cols, "preview": preview, "colMeta": col_meta}
                    )
            finally:
                wb.close()
        else:  # .xls 老格式回退 pandas
            xl = pd.ExcelFile(path)
            for name in xl.sheet_names:
                sample = pd.read_excel(path, sheet_name=name, nrows=300, dtype=str)
                sample = sample.loc[
                    :,
                    [c for c in sample.columns if str(c).strip() != "" and not str(c).startswith("Unnamed:")],
                ]
                sample = sample.fillna("")
                cols = [str(c).strip() for c in sample.columns]
                col_meta = _col_meta(cols, sample)
                preview = sample.head(3).astype(str).values.tolist()
                sheets.append(
                    {"name": name, "columns": cols, "preview": preview, "colMeta": col_meta}
                )
        return jsonify(ok=True, file_id=file_id, filename=f.filename, sheets=sheets)
    except Exception as e:
        return jsonify(ok=False, msg=f"读取失败：{e}"), 500


@app.route("/api/browse_folder", methods=["POST"])
def browse_folder():
    """弹出系统文件夹选择框（本地程序能力）"""
    if not _tk_lock.acquire(blocking=False):
        return jsonify(ok=False, msg="选择框已打开，请先在弹出的窗口中选择"), 409
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askdirectory(title="选择拆分文件的输出文件夹")
        root.destroy()
        if path:
            return jsonify(ok=True, path=path)
        return jsonify(ok=False, msg="已取消选择"), 200
    except Exception as e:
        return jsonify(ok=False, msg=f"无法弹出选择窗口：{e}，可直接粘贴文件夹路径"), 200
    finally:
        _tk_lock.release()


@app.route("/api/split", methods=["POST"])
def split():
    """按配置执行拆分"""
    cfg = request.get_json(force=True, silent=True) or {}
    file_id = cfg.get("file_id", "")
    sheet = cfg.get("sheet", "")
    keep = cfg.get("keep_columns", []) or []
    masks = cfg.get("mask", {}) or {}
    split_col = cfg.get("split_column", "")
    suffix = str(cfg.get("suffix", "") or "").strip()
    out_dir = str(cfg.get("output_dir", "") or "").strip()

    # 安全校验 file_id，防止路径穿越
    if not re.fullmatch(r"[a-f0-9]{32}\.(xlsx|xlsm|xls)", file_id):
        return jsonify(ok=False, msg="文件标识无效，请重新选择文件"), 400
    path = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.exists(path):
        return jsonify(ok=False, msg="源文件已失效，请重新选择"), 400
    if not keep:
        return jsonify(ok=False, msg="请至少勾选一个要保留的字段"), 400
    if not split_col:
        return jsonify(ok=False, msg="请选择拆分字段"), 400
    if not out_dir:
        return jsonify(ok=False, msg="请选择输出文件夹"), 400
    if not os.path.isdir(out_dir):
        return jsonify(ok=False, msg=f"输出文件夹不存在：{out_dir}"), 400

    log = []
    try:
        ext = os.path.splitext(file_id)[1]
        merge_sheets = cfg.get("sheets") or ([sheet] if sheet else [])
        merge_sheets = [str(s) for s in merge_sheets if s]
        if not merge_sheets:
            return jsonify(ok=False, msg="请选择要处理的子表"), 400

        df, meta = _prepare_df(path, file_id, ext, merge_sheets, cfg.get("source_col"), cfg.get("source_map"))
        add_source, src_col, _ = meta

        missing = [c for c in keep if c not in df.columns]
        if missing:
            return jsonify(ok=False, msg=f"字段不存在：{missing}"), 400
        if split_col not in keep:
            return jsonify(ok=False, msg="拆分字段必须包含在保留字段中"), 400

        # ---------- 脏数据预检：拆分列为空 / 一格多值 => 整体失败 ----------
        problems = []
        for i in range(len(df)):
            v = str(df[split_col].iloc[i])
            row_no = int(df["__row__"].iloc[i])
            sheet_name = str(df[src_col].iloc[i]) if src_col else ""
            if v == "" or v.lower() == "nan":
                problems.append(
                    {"row": row_no, "sheet": sheet_name, "value": "", "reason": "拆分字段为空"}
                )
            elif _is_multi_value(v):
                problems.append(
                    {"row": row_no, "sheet": sheet_name, "value": v,
                     "reason": "一格内含多个值(疑似分隔符)"}
                )
        if problems:
            log.append(f"预检发现 {len(problems)} 条脏数据，已中止，未生成任何文件。")
            return jsonify(
                ok=False,
                aborted=True,
                msg="拆分字段存在脏数据，已中止（未生成任何文件）",
                problems=problems[:200],
                problem_total=len(problems),
                log=log,
            )

        sconf = cfg.get("summary") or {}
        do_summary = bool(sconf.get("enabled"))
        include_detail = bool(cfg.get("include_detail", True))

        # ---------- 脱敏（在副本上进行，原始 df 留给汇总统计，保证金额/单数准确）----------
        dfm = df.copy()
        mask_info = []
        for col, rule in masks.items():
            if col in keep and rule.get("type"):
                dfm[col] = apply_mask(dfm[col], rule)
                label = RULES.get(rule["type"], (rule["type"], None))[0]
                if rule["type"] == "keep_ab":
                    label = f"保留前{rule.get('a',0)}后{rule.get('b',0)}位"
                elif rule["type"] == "replace":
                    label = f"替换为“{rule.get('text','***')}”"
                mask_info.append(f"{col}：{label}")

        # ---------- 明细自动排序键：文本维度列（分组字段优先），数值/脱敏列不参与 ----------
        def _text_like(c):
            if c in masks:
                return False
            ne = df[c][df[c].astype(str).str.strip() != ""]
            if len(ne) == 0:
                return False
            return pd.to_numeric(ne, errors="coerce").notna().mean() < 0.8

        text_cols = [c for c in keep if _text_like(c)]
        priority = [g.get("col") for g in (sconf.get("groups") or [])] if do_summary else []
        sort_cols = [c for c in priority if c in text_cols] + [
            c for c in text_cols if c not in priority
        ]

        # ---------- 分组拆分 ----------
        groups = []
        values = list(dict.fromkeys(df[split_col].tolist()))  # 保持出现顺序
        used_names = {}
        for val in values:
            detail = dfm[dfm[split_col] == val][keep].copy()
            if sort_cols:  # 自动按文本维度排序，同类行聚在一起
                detail = detail.sort_values(
                    by=sort_cols, kind="mergesort", na_position="last"
                ).reset_index(drop=True)
            summary_df = (
                build_summary(df[df[split_col] == val], sconf) if do_summary else None
            )
            base = _safe_filename(val)
            fname = f"{base}{suffix}.xlsx"
            # 防止不同值清洗后重名覆盖
            if fname in used_names:
                used_names[fname] += 1
                fname = f"{base}{suffix}_{used_names[fname]}.xlsx"
            else:
                used_names[fname] = 1
            fpath = os.path.join(out_dir, fname)
            try:
                write_detail = include_detail or summary_df is None  # 兜底：无汇总时必须写明细
                with pd.ExcelWriter(fpath, engine="openpyxl") as writer:
                    if write_detail:
                        detail.to_excel(writer, index=False, sheet_name="明细")
                        ws = writer.sheets["明细"]
                        # 脱敏列设为文本格式，杜绝手机号/身份证科学计数法
                        for idx, col in enumerate(keep, start=1):
                            if col in masks:
                                letter = ws.cell(row=1, column=idx).column_letter
                                for cell in ws[letter]:
                                    cell.number_format = "@"
                        _autofit_ws(ws)  # 明细列宽行高自适应
                    if summary_df is not None:
                        summary_df.to_excel(writer, index=False, sheet_name="汇总")
                        _autofit_ws(writer.sheets["汇总"], bold_last=True)
            except Exception as e:
                log.append(f"写入 {fname} 失败：{e}")
                return jsonify(ok=False, msg=f"写入文件失败：{e}", log=log), 500
            groups.append(
                {
                    "value": val,
                    "rows": len(detail),
                    "file": fname,
                    "has_summary": summary_df is not None,
                    "has_detail": write_detail,
                }
            )

        log.append(f"共拆分 {len(groups)} 份，合计 {int(sum(g['rows'] for g in groups))} 行。")
        if do_summary and any(g["has_summary"] for g in groups):
            if include_detail:
                log.append("每份文件含「明细」「汇总」两个 Sheet。")
            else:
                log.append("按设置仅输出「汇总」Sheet（不含明细）。")
        if mask_info:
            log.append("已脱敏：" + "；".join(mask_info))
        log.append(f"输出文件夹：{out_dir}")
        return jsonify(
            ok=True,
            total=len(groups),
            rows=int(len(df)),
            groups=groups,
            output_dir=out_dir,
            log=log,
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False, msg=f"处理异常：{e}", log=log), 500
    finally:
        _df_cache.pop(file_id, None)  # 拆分完成即释放缓存


@app.route("/api/preview", methods=["POST"])
def preview():
    """汇总预览：按当前配置返回指定市场（默认数据条数最多）的汇总表，供右侧预览窗实时展示。"""
    cfg = request.get_json(force=True, silent=True) or {}
    file_id = cfg.get("file_id", "")
    if not re.fullmatch(r"[a-f0-9]{32}\.(xlsx|xlsm|xls)", file_id):
        return jsonify(ok=False, msg="文件标识无效，请重新选择文件"), 400
    path = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.exists(path):
        return jsonify(ok=False, msg="源文件已失效，请重新选择"), 400
    sheets = [str(s) for s in (cfg.get("sheets") or []) if s]
    if not sheets:
        return jsonify(ok=False, msg="请先选择要处理的子表"), 400
    split_col = str(cfg.get("split_column") or "").strip()
    if not split_col:
        return jsonify(ok=False, msg="请先选择拆分字段"), 400
    ext = os.path.splitext(file_id)[1]
    try:
        df, _meta = _prepare_df(path, file_id, ext, sheets, cfg.get("source_col"), cfg.get("source_map"))
    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False, msg=f"读取数据失败：{e}"), 500
    if split_col not in df.columns:
        return jsonify(ok=False, msg=f"拆分字段不存在：{split_col}"), 400

    # 市场列表：非空值按行数降序，默认取行数最多的
    vc = df[split_col].value_counts(dropna=False)
    markets = [
        {"value": str(v), "rows": int(c)}
        for v, c in vc.items()
        if str(v).strip() not in ("", "nan", "None")
    ]
    if not markets:
        return jsonify(ok=False, msg="拆分字段没有有效数据"), 400
    cur = str(cfg.get("market") or "").strip()
    if not cur or not any(m["value"] == cur for m in markets):
        cur = markets[0]["value"]

    sconf = cfg.get("summary") or {}
    groups = [g for g in (sconf.get("groups") or []) if g.get("col") in df.columns]
    sums = [s for s in (sconf.get("sums") or []) if s.get("col") in df.columns]
    counts = [c for c in (sconf.get("counts") or []) if c.get("col") in df.columns]
    subset = df[df[split_col] == cur]
    summary = build_summary(subset, sconf) if (sums or counts) else None
    cols, data = [], []
    if summary is not None:
        cols = [str(c) for c in summary.columns]
        data = [[("" if pd.isna(v) else str(v)) for v in row] for row in summary.values]
    return jsonify(ok=True, market=cur, markets=markets, columns=cols, data=data, rows=int(len(subset)))


# ----------------------------------------------------------------------------
# 配置模板：保存 / 列表 / 加载 / 重命名 / 删除
# 模板只存「可复用的拆分逻辑」，不存源文件与输出文件夹。
# ----------------------------------------------------------------------------
def _tpl_path(name):
    return os.path.join(CONFIG_DIR, _safe_filename(name) + ".json")


def _tpl_read(name):
    path = _tpl_path(name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.route("/api/templates", methods=["GET"])
def templates_list():
    items = []
    for fn in sorted(os.listdir(CONFIG_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            data = _tpl_read(fn[:-5])
            if not data:
                continue
            cfg = data.get("config") or {}
            items.append(
                {
                    "name": data.get("name") or fn[:-5],
                    "updated": data.get("updated", ""),
                    "keep": len(cfg.get("keep_columns") or []),
                    "split": cfg.get("split_column", ""),
                    "suffix": cfg.get("suffix", ""),
                    "summary_on": bool((cfg.get("summary") or {}).get("enabled")),
                }
            )
        except Exception:
            continue
    items.sort(key=lambda x: x["updated"], reverse=True)
    return jsonify(ok=True, templates=items)


@app.route("/api/templates/save", methods=["POST"])
def template_save():
    d = request.get_json(force=True, silent=True) or {}
    name = str(d.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, msg="模板名称不能为空"), 400
    cfg = d.get("config") or {}
    # 只保留可复用字段，杜绝源文件标识 / 输出目录被带进模板
    cfg = {
        "sheets": [str(s) for s in (cfg.get("sheets") or []) if s],
        "source_col": str(cfg.get("source_col") or "来源"),
        "source_map": cfg.get("source_map") or {},
        "keep_columns": [str(c) for c in (cfg.get("keep_columns") or []) if c],
        "mask": cfg.get("mask") or {},
        "split_column": str(cfg.get("split_column") or ""),
        "suffix": str(cfg.get("suffix") or ""),
        "summary": cfg.get("summary") or {},
    }
    from datetime import datetime

    data = {
        "name": name,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": cfg,
    }
    with open(_tpl_path(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return jsonify(ok=True, name=name)


@app.route("/api/templates/load", methods=["POST"])
def template_load():
    d = request.get_json(force=True, silent=True) or {}
    name = str(d.get("name") or "").strip()
    data = _tpl_read(name)
    if not data:
        return jsonify(ok=False, msg=f"模板不存在：{name}"), 404
    return jsonify(
        ok=True, name=name, updated=data.get("updated", ""), config=data.get("config") or {}
    )


@app.route("/api/templates/rename", methods=["POST"])
def template_rename():
    d = request.get_json(force=True, silent=True) or {}
    old_name = str(d.get("old_name") or "").strip()
    new_name = str(d.get("new_name") or "").strip()
    if not old_name or not new_name:
        return jsonify(ok=False, msg="模板名称不能为空"), 400
    old_path = _tpl_path(old_name)
    if not os.path.exists(old_path):
        return jsonify(ok=False, msg=f"模板不存在：{old_name}"), 404
    new_path = _tpl_path(new_name)
    if os.path.exists(new_path) and os.path.abspath(old_path) != os.path.abspath(new_path):
        return jsonify(ok=False, msg=f"已存在同名模板：{new_name}"), 400
    os.rename(old_path, new_path)
    try:  # 同步更新文件内的 name 字段
        data = _tpl_read(new_name)
        if data and data.get("name") != new_name:
            data["name"] = new_name
            with open(new_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return jsonify(ok=True, name=new_name)


@app.route("/api/templates/delete", methods=["POST"])
def template_delete():
    d = request.get_json(force=True, silent=True) or {}
    name = str(d.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, msg="缺少模板名称"), 400
    path = _tpl_path(name)
    if not os.path.exists(path):
        return jsonify(ok=False, msg=f"模板不存在：{name}"), 404
    os.remove(path)
    return jsonify(ok=True)


def _find_free_port(preferred=18765):
    import socket
    for p in [preferred] + list(range(preferred + 1, preferred + 30)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            s.close()
            continue
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


if __name__ == "__main__":
    import webbrowser
    port = _find_free_port(18765)
    url = f"http://127.0.0.1:{port}"
    print(f"工作台已启动：{url}")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    # 本机访问，不开公网
    app.run(host="127.0.0.1", port=port, debug=False)
