# -*- coding: utf-8 -*-
"""Excel 单元格底色（填充色）的读取与写回。

业务背景
--------
数据分发用 `DataFrame.to_excel` 导出明细。pandas 只搬运"值"，源表上人工标的
底色（某行标黄=待跟进、某列标红=异常）在导出文件里全部丢失。用户要求：
**源表单元格有颜色，导出的明细仍要保留对应颜色。**

为什么不用 openpyxl 常规读写
--------------------------
1. `load_workbook(read_only=True)` 返回的 ReadOnlyCell 不暴露 fill，拿不到颜色；
2. 常规模式 (`read_only=False`) 会把整表连同样式驻留内存 —— 本项目为 5 万行
   大文件专门改成了流式读取，退回常规模式等于把性能优化全部作废。

所以这里直接解 xlsx 的 OOXML 包：
- `xl/styles.xml` 很小，一次性读：把 cellXfs 索引映射成最终色值；
- `xl/worksheets/sheetN.xml` 用 iterparse 流式扫描，只记录"哪些 (行, 列) 有底色"。

扫描一遍只产出稀疏映射（有颜色的单元格通常远少于总单元格），读写开销可控。

支持范围
--------
- .xlsx / .xlsm 的**实心填充**（patternType=solid）
- 取色支持 `rgb`、`theme`（含 tint 明暗）两种；`indexed` 仅识别 64/65（默认底色）
- 不支持：条件格式带的底色、渐变填充、图片填充、.xls 老格式

不支持的情况一律**静默降级**（返回空映射），不阻断分发主流程 —— 颜色是增强
项，不能因为它让用户整批文件拆不出来。
"""
import os
import re
import zipfile
from xml.etree import ElementTree as ET

# OOXML 命名空间
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DRAW = "http://schemas.openxmlformats.org/drawingml/2006/main"

_REF_RE = re.compile(r"^([A-Za-z]+)(\d+)$")

# Excel 的 theme 索引顺序（0..11）对应的 clrScheme 节点名
_THEME_ORDER = [
    "lt1", "dk1", "lt2", "dk2",
    "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
    "hlink", "folHlink",
]


# ----------------------------------------------------------------------------
# 颜色值处理
# ----------------------------------------------------------------------------
def _norm_hex(value):
    """把 ARGB / RGB 字符串规范成 6 位大写 RGB；非法返回 None。

    注意：这里**有意忽略 alpha 通道**。OOXML 规范里 alpha=00 表示全透明，但
    Excel 的 solid 单元格填充实际按不透明渲染，而 openpyxl 等写入库会把 6 位
    色值统一补成 "00" 前缀（如 FFFF00 -> 00FFFF00）。若按规范把 00 判为透明，
    大量正常底色会被误认为"无填充"，所以只取后 6 位。
    """
    s = str(value or "").strip().upper()
    if len(s) == 8:
        return s[2:]
    if len(s) == 6:
        return s
    return None


def _apply_tint(hex_rgb, tint):
    """theme 色按 tint 调亮/调暗（Excel 用 HLS 亮度，这里用 RGB 线性近似）。

    只影响观感精度，不影响"是否保留颜色"这件事，因此有意从简。
    """
    if not hex_rgb:
        return None
    try:
        tint = float(tint or 0)
    except (TypeError, ValueError):
        tint = 0.0
    if tint == 0:
        return hex_rgb
    try:
        r = int(hex_rgb[0:2], 16)
        g = int(hex_rgb[2:4], 16)
        b = int(hex_rgb[4:6], 16)
    except (ValueError, IndexError):
        return hex_rgb
    if tint > 0:  # 向白色靠拢
        r = int(r + (255 - r) * tint)
        g = int(g + (255 - g) * tint)
        b = int(b + (255 - b) * tint)
    else:  # 向黑色压暗
        k = 1 + tint
        r, g, b = int(r * k), int(g * k), int(b * k)
    return "%02X%02X%02X" % (
        max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    )


# ----------------------------------------------------------------------------
# 包内结构解析
# ----------------------------------------------------------------------------
def _sheet_paths(zf):
    """返回 {sheet 名: 包内 xml 路径}。"""
    out = {}
    try:
        wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
        rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        return out

    rels = {}
    for rel in rel_root:
        rid = rel.get("Id")
        target = rel.get("Target") or ""
        if rid is None or not target:
            continue
        # Target 可能是 "worksheets/sheet1.xml" 或 "/xl/worksheets/sheet1.xml"
        target = target.lstrip("/")
        rels[rid] = target if target.startswith("xl/") else "xl/" + target

    sheets_el = wb_root.find(f"{{{_MAIN}}}sheets")
    if sheets_el is None:
        return out
    for sheet in sheets_el:
        name = sheet.get("name")
        rid = sheet.get(f"{{{_REL}}}id")
        path = rels.get(rid)
        if name and path:
            out[name] = path
    return out


def _theme_palette(zf):
    """读主题调色板，返回按 Excel theme 索引排好序的 6 位色值列表。"""
    names = [n for n in zf.namelist() if n.startswith("xl/theme/") and n.endswith(".xml")]
    if not names:
        return []
    try:
        root = ET.fromstring(zf.read(names[0]))
    except (KeyError, ET.ParseError):
        return []
    scheme = root.find(f".//{{{_DRAW}}}clrScheme")
    if scheme is None:
        return []
    palette = []
    for node_name in _THEME_ORDER:
        node = scheme.find(f"{{{_DRAW}}}{node_name}")
        color = None
        if node is not None:
            srgb = node.find(f"{{{_DRAW}}}srgbClr")
            if srgb is not None:
                color = _norm_hex(srgb.get("val"))
            else:
                sys_clr = node.find(f"{{{_DRAW}}}sysClr")
                if sys_clr is not None:
                    color = _norm_hex(sys_clr.get("lastClr") or sys_clr.get("val"))
        palette.append(color)
    return palette


def _resolve_color(fg_el, theme):
    """把一个 <fgColor> 元素解析成 6 位色值；无法解析返回 None。"""
    if fg_el is None:
        return None

    rgb = fg_el.get("rgb")
    if rgb:
        return _norm_hex(rgb)

    if fg_el.get("indexed") is not None:
        # indexed 走 Excel 56 色旧调色板，现代填充极少用；其中 64/65 是"自动/默认
        # 背景"（视觉上等于无填充）。这里统一不还原，避免把默认底色误画成实色。
        return None

    theme_idx = fg_el.get("theme")
    if theme_idx is not None and theme:
        try:
            idx = int(theme_idx)
        except ValueError:
            return None
        if 0 <= idx < len(theme):
            return _apply_tint(theme[idx], fg_el.get("tint"))
    return None


def _style_fill_colors(zf):
    """返回 cellXfs 索引 -> 6 位色值（不足或无色填 None）的列表。"""
    try:
        root = ET.fromstring(zf.read("xl/styles.xml"))
    except (KeyError, ET.ParseError):
        return []

    theme = _theme_palette(zf)

    fills = []
    fills_el = root.find(f"{{{_MAIN}}}fills")
    if fills_el is not None:
        for fill_el in fills_el.findall(f"{{{_MAIN}}}fill"):
            color = None
            pattern = fill_el.find(f"{{{_MAIN}}}patternFill")
            if pattern is not None:
                ptype = (pattern.get("patternType") or "none").lower()
                if ptype != "none":
                    color = _resolve_color(pattern.find(f"{{{_MAIN}}}fgColor"), theme)
            fills.append(color)

    out = []
    xfs_el = root.find(f"{{{_MAIN}}}cellXfs")
    if xfs_el is not None:
        for xf in xfs_el.findall(f"{{{_MAIN}}}xf"):
            try:
                fill_id = int(xf.get("fillId") or 0)
            except ValueError:
                fill_id = 0
            out.append(fills[fill_id] if 0 <= fill_id < len(fills) else None)
    return out


def _split_ref(ref):
    """"A2" -> (2, 1)；不合法返回 (None, None)。"""
    m = _REF_RE.match(str(ref or "").strip())
    if not m:
        return None, None
    letters, row = m.group(1).upper(), m.group(2)
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - 64)
    try:
        return int(row), col
    except ValueError:
        return None, None


def _scan_sheet_fills(zf, xml_path, sheet_name, style_colors):
    """流式扫描单个子表，返回 {(sheet, row): {col_idx: 色值}}。"""
    out = {}
    if not style_colors:
        return out
    try:
        fh = zf.open(xml_path)
    except KeyError:
        return out

    with fh:
        for event, elem in ET.iterparse(fh, events=("end",)):
            tag = elem.tag
            if tag == f"{{{_MAIN}}}c":
                style_idx = elem.get("s")
                ref = elem.get("r")
                if style_idx is not None and ref:
                    try:
                        si = int(style_idx)
                    except ValueError:
                        si = -1
                    color = style_colors[si] if 0 <= si < len(style_colors) else None
                    if color:
                        row, col = _split_ref(ref)
                        if row and col:
                            out.setdefault((sheet_name, row), {})[col] = color
            elif tag == f"{{{_MAIN}}}row":
                # 行处理完即释放，避免整表 XML 在内存里越堆越大
                elem.clear()
    return out


# ----------------------------------------------------------------------------
# 对外接口
# ----------------------------------------------------------------------------
def read_fill_map(path, sheet_names):
    """提取指定子表中"有底色"的单元格。

    Args:
        path: xlsx / xlsm 路径
        sheet_names: 需要处理的子表名列表

    Returns:
        {(sheet_name, excel_row): {col_index(1-based): 'RRGGBB'}}
        excel_row 与分发流程的 `__row__` 对齐（表头为第 1 行）。
        文件不存在、格式不支持、解析失败或没有任何填充色时返回 {}。
    """
    if not path or not os.path.exists(path):
        return {}
    if os.path.splitext(path)[1].lower() not in (".xlsx", ".xlsm"):
        return {}
    names = [str(n) for n in (sheet_names or []) if n]
    if not names:
        return {}
    try:
        with zipfile.ZipFile(path) as zf:
            style_colors = _style_fill_colors(zf)
            if not style_colors:
                return {}
            sheet_paths = _sheet_paths(zf)
            out = {}
            for name in names:
                xml_path = sheet_paths.get(name)
                if xml_path:
                    out.update(_scan_sheet_fills(zf, xml_path, name, style_colors))
            return out
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError):
        return {}


def apply_fills(ws, fill_map, row_keys, columns, col_pos, header_key=None):
    """把源表底色写回目标工作表。

    Args:
        ws: 目标 openpyxl Worksheet
        fill_map: read_fill_map() 的返回值
        row_keys: 新表每个数据行对应的 (sheet_name, excel_row)，顺序与写出顺序一致
        columns: 新表列名（按写出顺序）
        col_pos: {sheet_name: {列名: 源表列索引}}，用于把列名换算成源表列位
        header_key: 表头对应的 (sheet_name, 1)，可选

    Returns:
        实际着色的单元格数量（便于日志展示效果）。
    """
    if not fill_map or not row_keys or not columns:
        return 0

    from openpyxl.styles import PatternFill

    painted = 0

    if header_key:
        colors = fill_map.get(header_key) or {}
        pos = col_pos.get(header_key[0]) or {}
        for j, name in enumerate(columns, start=1):
            idx = pos.get(name)
            color = colors.get(idx) if idx else None
            if color:
                ws.cell(row=1, column=j).fill = PatternFill(
                    fill_type="solid", fgColor=color
                )
                painted += 1

    # 每行只遍历有颜色的映射，避免"无颜色行 × 全部列"的空转
    for i, key in enumerate(row_keys, start=2):
        colors = fill_map.get(key)
        if not colors:
            continue
        pos = col_pos.get(key[0]) or {}
        for j, name in enumerate(columns, start=1):
            idx = pos.get(name)
            if not idx:
                continue
            color = colors.get(idx)
            if color:
                ws.cell(row=i, column=j).fill = PatternFill(
                    fill_type="solid", fgColor=color
                )
                painted += 1
    return painted


def count_fills(fill_map):
    """统计映射中的单元格数量，供接口日志使用。"""
    return sum(len(v) for v in (fill_map or {}).values())
