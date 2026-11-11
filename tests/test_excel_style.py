# -*- coding: utf-8 -*-
"""单元格底色读取 / 回写的单元测试，以及分发明细保留底色的端到端测试。

覆盖点：
1. OOXML 底色解析（rgb 实心填充、表头行、单格）
2. 无颜色 / 非 xlsx / 文件不存在时的静默降级
3. apply_fills 按行锚点 + 列位换算写回
4. /api/split 导出明细后底色仍在，且**排序改变行序时不串行**
"""
import io
import os

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

from services.excel_style import apply_fills, count_fills, read_fill_map
from app import app

HEADER_BLUE = "D9E1F2"
ROW_YELLOW = "FFFF00"
ROW_GREEN = "00B050"
CELL_RED = "FF0000"


def _rgb(cell):
    """取单元格底色的 6 位 RGB（openpyxl 回读时是 8 位 ARGB，前缀不定）。"""
    value = cell.fill.start_color.rgb
    return str(value)[-6:].upper() if value else ""


@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / "split_out"
    d.mkdir(exist_ok=True)
    return str(d)


def _make_colored_book():
    """表头标蓝、第2行整行标黄、C4 单格标红。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    ws.append(["市场", "顾问", "金额"])
    ws.append(["义乌", "王顾问", 100])
    ws.append(["金华", "李顾问", 200])
    ws.append(["义乌", "赵顾问", 300])
    for c in ws[1]:
        c.fill = PatternFill("solid", fgColor=HEADER_BLUE)
    for c in ws[2]:
        c.fill = PatternFill("solid", fgColor=ROW_YELLOW)
    ws["C4"].fill = PatternFill("solid", fgColor=CELL_RED)
    return wb


@pytest.fixture
def colored_path(tmp_path):
    path = str(tmp_path / "colored.xlsx")
    _make_colored_book().save(path)
    return path


# ----------------------------------------------------------------------------
# read_fill_map
# ----------------------------------------------------------------------------
class TestReadFillMap:
    def test_reads_solid_fills_by_row(self, colored_path):
        fm = read_fill_map(colored_path, ["明细"])
        # 表头第 1 行三列都是蓝
        assert fm[("明细", 1)] == {1: HEADER_BLUE, 2: HEADER_BLUE, 3: HEADER_BLUE}
        # 第 2 行整行黄
        assert fm[("明细", 2)] == {1: ROW_YELLOW, 2: ROW_YELLOW, 3: ROW_YELLOW}
        # C4 单格红
        assert fm[("明细", 4)] == {3: CELL_RED}
        # 未着色的第 3 行不出现
        assert ("明细", 3) not in fm

    def test_count_fills(self, colored_path):
        assert count_fills(read_fill_map(colored_path, ["明细"])) == 7

    def test_only_requested_sheets(self, colored_path):
        assert read_fill_map(colored_path, ["不存在"]) == {}

    def test_plain_file_returns_empty(self, tmp_path):
        path = str(tmp_path / "plain.xlsx")
        pd.DataFrame({"a": [1, 2]}).to_excel(path, index=False)
        assert read_fill_map(path, ["Sheet1"]) == {}

    def test_non_xlsx_or_missing_returns_empty(self, tmp_path):
        assert read_fill_map(str(tmp_path / "missing.xlsx"), ["S"]) == {}
        csv = tmp_path / "a.csv"
        csv.write_text("a,b\n1,2\n", encoding="utf-8")
        assert read_fill_map(str(csv), ["S"]) == {}


# ----------------------------------------------------------------------------
# apply_fills
# ----------------------------------------------------------------------------
class TestApplyFills:
    def test_paints_matching_cells_only(self, colored_path):
        fm = read_fill_map(colored_path, ["明细"])
        wb = Workbook()
        ws = wb.active
        ws.append(["市场", "顾问", "金额"])       # 第 1 行
        ws.append(["义乌", "王顾问", 100])        # 第 2 行 <- 源表第 2 行
        ws.append(["义乌", "赵顾问", 300])        # 第 3 行 <- 源表第 4 行
        painted = apply_fills(
            ws, fm,
            row_keys=[("明细", 2), ("明细", 4)],
            columns=["市场", "顾问", "金额"],
            col_pos={"明细": {"市场": 1, "顾问": 2, "金额": 3}},
            header_key=("明细", 1),
        )
        assert painted == 7  # 表头 3 + 整行 3 + 单格 1
        assert _rgb(ws["A1"]) == HEADER_BLUE
        # 第 2 行整行黄
        assert _rgb(ws["A2"]) == ROW_YELLOW
        assert _rgb(ws["C2"]) == ROW_YELLOW
        # 第 3 行来自源表第 4 行：只有金额格红，A/B 无色
        assert _rgb(ws["C3"]) == CELL_RED
        assert ws["A3"].fill.fill_type in (None, "none")

    def test_column_subset_keeps_source_position(self, colored_path):
        """只保留部分字段时，颜色要落在"原列位"对应的新列，不能按新顺序平移。"""
        fm = read_fill_map(colored_path, ["明细"])
        wb = Workbook()
        ws = wb.active
        ws.append(["金额", "市场"])   # 只保留 3 号和 1 号列，且顺序颠倒
        ws.append(["100", "义乌"])    # <- 源表第 2 行，原 A/B/C 全黄
        apply_fills(
            ws, fm,
            row_keys=[("明细", 2)],
            columns=["金额", "市场"],
            col_pos={"明细": {"市场": 1, "顾问": 2, "金额": 3}},
        )
        assert _rgb(ws["A2"]) == ROW_YELLOW  # 金额(原C)
        assert _rgb(ws["B2"]) == ROW_YELLOW  # 市场(原A)

    def test_empty_inputs_are_noop(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["a"])
        assert apply_fills(ws, {}, [], ["a"], {}) == 0


# ----------------------------------------------------------------------------
# 端到端：/api/split 导出的明细保留底色
# ----------------------------------------------------------------------------
@pytest.mark.integration
class TestSplitKeepsFills:
    def _upload(self, client, wb, filename="colored.xlsx"):
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        j = client.post(
            "/api/inspect", data={"file": (buf, filename)},
            content_type="multipart/form-data",
        ).get_json()
        assert j["ok"], j
        return j["file_id"]

    def test_detail_keeps_row_colors(self, client, out_dir):
        file_id = self._upload(client, _make_colored_book())
        payload = {
            "file_id": file_id, "sheet": "明细",
            "keep_columns": ["市场", "顾问", "金额"],
            "split_column": "市场", "suffix": "_导出",
            "output_dir": out_dir,
        }
        r = client.post("/api/split", json=payload).get_json()
        assert r["ok"], r.get("msg")
        assert any("沿用" in line for line in r["log"])

        wb = load_workbook(os.path.join(out_dir, "义乌_导出.xlsx"))
        ws = wb["明细"]
        # 义乌两份明细分别来自源表第 2、4 行
        assert _rgb(ws["A2"]) == ROW_YELLOW
        assert _rgb(ws["C3"]) == CELL_RED
        assert _rgb(ws["A1"]) == HEADER_BLUE

    def test_colors_follow_rows_after_auto_sort(self, client, out_dir):
        """自动排序会重排行序，底色必须跟着行走，不能按位置平移。"""
        wb = Workbook()
        ws = wb.active
        ws.title = "明细"
        ws.append(["市场", "顾问", "金额"])
        ws.append(["义乌", "B", 100])   # 源表第 2 行，标黄
        ws.append(["义乌", "A", 200])   # 源表第 3 行，标绿
        for c in ws[2]:
            c.fill = PatternFill("solid", fgColor=ROW_YELLOW)
        for c in ws[3]:
            c.fill = PatternFill("solid", fgColor=ROW_GREEN)

        file_id = self._upload(client, wb, "sort.xlsx")
        r = client.post("/api/split", json={
            "file_id": file_id, "sheet": "明细",
            "keep_columns": ["市场", "顾问", "金额"],
            "split_column": "市场", "suffix": "_s",
            "output_dir": out_dir,
        }).get_json()
        assert r["ok"], r.get("msg")

        out = load_workbook(os.path.join(out_dir, "义乌_s.xlsx"))
        ws2 = out["明细"]
        # 排序后 A 在前：第 2 行应为 A 且是绿色（源第 3 行），第 3 行 B 黄色
        assert ws2["B2"].value == "A"
        assert _rgb(ws2["A2"]) == ROW_GREEN
        assert ws2["B3"].value == "B"
        assert _rgb(ws2["A3"]) == ROW_YELLOW
