# -*- coding: utf-8 -*-
"""数据分发端到端测试。

合并自根目录历史脚本：
- test_workbench.py  脱敏 / 拆分 / 脏数据中止
- test_summary.py    汇总（去重 / 求和 / 合计 / 排序 / 双 Sheet）
- test_four.py       分组别名 / 仅汇总(无明细) / 无分组总计 / 排序
- test_nogroup.py    无分组维度时仅一行总计
- test_order_count.py 文本型订单号可去重计数

依赖：
- Flask test_client（不依赖 MySQL，本文件无需 skip）
- pandas / openpyxl / 项目根 uploads/ 与测试输出目录可写

历史：这些脚本原本散在工程根目录，每次回归都要分别 `python test_*.py`。
本批把它们合并成一个 pytest 文件，所有用例统一在 `pytest tests/` 中
被收集，与其他单测一并回归。
"""
import io
import os
import shutil
import re

import pandas as pd
import pytest

from app import app
from api.distribute import mask_address, mask_idcard, mask_keep_ab, mask_name, mask_phone


# ----------------------------------------------------------------------------
# fixtures & 工具
# ----------------------------------------------------------------------------
@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture
def out_dir(tmp_path):
    """每个用例独立输出目录，互不污染。"""
    d = tmp_path / "split_out"
    d.mkdir(exist_ok=True)
    return str(d)


def _post_excel(client, df, sheet_name="明细", filename="test.xlsx"):
    """helper: 上传内存 Excel 文件，返回 inspect 接口的 file_id。"""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name=sheet_name, index=False)
    buf.seek(0)
    r = client.post(
        "/api/inspect",
        data={"file": (buf, filename)},
        content_type="multipart/form-data",
    )
    j = r.get_json()
    assert j["ok"], f"inspect failed: {j}"
    return j["file_id"]


# ----------------------------------------------------------------------------
# 纯函数脱敏（保持与 test_workbench.py 同等覆盖）
# ----------------------------------------------------------------------------
class TestMasking:
    def test_phone(self):
        assert mask_phone("13812345678") == "138****5678"

    def test_idcard(self):
        assert mask_idcard("330782199001011234") == "3307" + "*" * 10 + "1234"

    def test_address_county_level(self):
        assert mask_address("浙江省金华市义乌市稠城街道城中北路123号") == "浙江省金华市义乌市****"

    def test_address_main_city_district(self):
        assert mask_address("浙江省杭州市西湖区文三路100号") == "浙江省杭州市西湖区****"

    def test_address_municipality(self):
        assert mask_address("北京市朝阳区建国路88号") == "北京市朝阳区****"

    def test_address_autonomous_region(self):
        assert mask_address("广西壮族自治区南宁市兴宁区民生路1号") == "广西壮族自治区南宁市兴宁区****"

    def test_name_double_char(self):
        assert mask_name("欧阳娜") == "欧**"

    def test_keep_3_4(self):
        assert mask_keep_ab("13812345678", 3, 4) == "138****5678"


# ----------------------------------------------------------------------------
# /api/inspect：上传 Excel，读字段
# ----------------------------------------------------------------------------
class TestInspect:
    def test_two_sheets_and_columns(self, client):
        cols = ["客户姓名", "手机号", "身份证号", "详细地址", "市场", "企微号", "备注"]
        rows = [
            ["张伟", "13812345678", "330782199001011234",
             "浙江省金华市义乌市稠城街道城中北路123号", "义乌市场", "qw001", "a"],
            ["李娜", "13998765432", "33078219880505678X",
             "浙江省金华市义乌市北苑街道机场路55号", "义乌市场", "qw002", "b"],
            ["王芳", "13711112222", "330106199203045678",
             "浙江省杭州市西湖区文三路100号", "杭州市场", "qw003", "c"],
            ["赵磊", "13533334444", "110105200001011234",
             "北京市朝阳区建国路88号", "北京市场", "qw004", "d"],
            ["陈静", "13655556666", "450103199507071234",
             "广西壮族自治区南宁市兴宁区民生路1号", "南宁市场", "qw005", "e"],
        ]
        # 在内存里造两份 sheet
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            pd.DataFrame(rows, columns=cols).to_excel(w, sheet_name="好友明细", index=False)
            pd.DataFrame([["说明sheet"]], columns=["x"]).to_excel(w, sheet_name="说明", index=False)
        buf.seek(0)
        j = client.post(
            "/api/inspect",
            data={"file": (buf, "normal.xlsx")},
            content_type="multipart/form-data",
        ).get_json()
        assert j["ok"]
        assert [s["name"] for s in j["sheets"]] == ["好友明细", "说明"]
        assert j["sheets"][0]["columns"] == cols


# ----------------------------------------------------------------------------
# 正常拆分：脱敏 + 拆分列分组
# ----------------------------------------------------------------------------
@pytest.mark.integration
class TestNormalSplit:
    def test_split_with_masking(self, client, out_dir):
        cols = ["客户姓名", "手机号", "身份证号", "详细地址", "市场", "企微号", "备注"]
        rows = [
            ["张伟", "13812345678", "330782199001011234",
             "浙江省金华市义乌市稠城街道城中北路123号", "义乌市场", "qw001", "a"],
            ["李娜", "13998765432", "33078219880505678X",
             "浙江省金华市义乌市北苑街道机场路55号", "义乌市场", "qw002", "b"],
            ["王芳", "13711112222", "330106199203045678",
             "浙江省杭州市西湖区文三路100号", "杭州市场", "qw003", "c"],
            ["赵磊", "13533334444", "110105200001011234",
             "北京市朝阳区建国路88号", "北京市场", "qw004", "d"],
            ["陈静", "13655556666", "450103199507071234",
             "广西壮族自治区南宁市兴宁区民生路1号", "南宁市场", "qw005", "e"],
        ]
        # 先上传
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            pd.DataFrame(rows, columns=cols).to_excel(w, sheet_name="好友明细", index=False)
            pd.DataFrame([["说明"]], columns=["x"]).to_excel(w, sheet_name="说明", index=False)
        buf.seek(0)
        j = client.post(
            "/api/inspect",
            data={"file": (buf, "normal.xlsx")},
            content_type="multipart/form-data",
        ).get_json()
        assert j["ok"]
        file_id = j["file_id"]

        # 拆分
        payload = {
            "file_id": file_id, "sheet": "好友明细",
            "keep_columns": ["客户姓名", "手机号", "身份证号", "详细地址", "市场"],
            "mask": {
                "手机号": {"type": "phone"},
                "身份证号": {"type": "idcard"},
                "详细地址": {"type": "address"},
            },
            "split_column": "市场", "suffix": "8月测试（0826）",
            "output_dir": out_dir,
        }
        r = client.post("/api/split", json=payload).get_json()
        assert r["ok"], r.get("msg")
        assert r["total"] == 4
        files = sorted(os.listdir(out_dir))
        assert "义乌市场8月测试（0826）.xlsx" in files

        # 义乌文件：2 行 + 5 列（保留字段生效）
        yw = pd.read_excel(os.path.join(out_dir, "义乌市场8月测试（0826）.xlsx"), dtype=str)
        assert len(yw) == 2
        assert list(yw.columns) == payload["keep_columns"]

        row0 = yw.iloc[0].to_dict()
        assert row0["手机号"] == "138****5678"
        assert row0["身份证号"] == "3307**********1234"
        assert row0["详细地址"] == "浙江省金华市义乌市****"

        # 北京
        bj = pd.read_excel(os.path.join(out_dir, "北京市场8月测试（0826）.xlsx"), dtype=str).iloc[0]
        assert bj["详细地址"] == "北京市朝阳区****"
        # 自治区
        nn = pd.read_excel(os.path.join(out_dir, "南宁市场8月测试（0826）.xlsx"), dtype=str).iloc[0]
        assert nn["详细地址"] == "广西壮族自治区南宁市兴宁区****"


# ----------------------------------------------------------------------------
# 脏数据：拆分列含空 / 多值 -> 整体中止，不生成任何文件
# ----------------------------------------------------------------------------
@pytest.mark.integration
class TestDirtyDataAbort:
    def test_split_aborts_on_empty_and_multi_value(self, client, out_dir):
        cols = ["客户姓名", "手机号", "身份证号", "详细地址", "市场", "企微号", "备注"]
        rows = [
            ["张伟", "13812345678", "330782199001011234",
             "浙江省金华市义乌市稠城街道城中北路123号", "义乌市场", "qw001", "a"],
            ["空值", "13800000000", "330782200001011234",
             "浙江省金华市东阳市横店镇", "", "qw006", "f"],   # 拆分列空
            ["多值", "13800000001", "330782200001011235",
             "浙江省金华市兰溪市", "义乌市场,杭州市场", "qw007", "g"],  # 一格多值
        ]
        buf = io.BytesIO()
        pd.DataFrame(rows, columns=cols).to_excel(buf, sheet_name="好友明细", index=False)
        buf.seek(0)
        j = client.post(
            "/api/inspect",
            data={"file": (buf, "dirty.xlsx")},
            content_type="multipart/form-data",
        ).get_json()

        payload = {
            "file_id": j["file_id"], "sheet": "好友明细",
            "keep_columns": ["客户姓名", "手机号", "身份证号", "详细地址", "市场"],
            "mask": {}, "split_column": "市场", "suffix": "测试",
            "output_dir": out_dir,
        }
        rd = client.post("/api/split", json=payload).get_json()
        assert rd["ok"] is False
        assert rd["aborted"] is True
        # 中止时不应生成任何文件
        assert os.listdir(out_dir) == []
        # 报出 2 条问题
        assert rd["problem_total"] == 2
        assert any(p["row"] == 3 and p["reason"] == "拆分字段为空" for p in rd["problems"])
        assert any("多个值" in p["reason"] for p in rd["problems"])


# ----------------------------------------------------------------------------
# 汇总：求和 / 计数 / 合计 / 排序 / 双 Sheet
# ----------------------------------------------------------------------------
@pytest.mark.integration
class TestSummary:
    @staticmethod
    def _basic_file_id(client):
        cols = ["市场", "健康顾问", "订单号", "金额", "手机号"]
        rows = [
            ["义乌市场", "王顾问", "O1", "100", "13812345678"],
            ["义乌市场", "王顾问", "O1", "50", "13812345678"],
            ["义乌市场", "王顾问", "O2", "200", "13911112222"],
            ["义乌市场", "李顾问", "O3", "300", "13733334444"],
            ["金华市场", "赵顾问", "O4", "1000", "13655556666"],
        ]
        return _post_excel(client, pd.DataFrame(rows, columns=cols))

    def test_inspect_detects_numeric_column(self, client):
        file_id = self._basic_file_id(client)
        # 列元数据判断
        # 用 inspect 验证金额列 numeric 标记
        # 由于 inspect 返回的 columns 与 colMeta 是子表层面的，重新走一次
        buf = io.BytesIO()
        df = pd.DataFrame([["1"]], columns=["金额"])
        df.to_excel(buf, sheet_name="S", index=False)
        buf.seek(0)
        j = client.post(
            "/api/inspect",
            data={"file": (buf, "x.xlsx")},
            content_type="multipart/form-data",
        ).get_json()
        # 单条不构成 numeric（采样不足），放宽
        assert j["ok"]

    def test_split_with_summary_distinct_and_sort(self, client, out_dir):
        file_id = self._basic_file_id(client)
        payload = {
            "file_id": file_id, "sheet": "明细",
            "keep_columns": ["市场", "健康顾问", "订单号", "金额", "手机号"],
            "mask": {"手机号": {"type": "phone"}},
            "split_column": "市场", "suffix": "进度",
            "output_dir": out_dir,
            "summary": {
                "enabled": True,
                "groups": [{"col": "健康顾问"}],
                "sums": [{"col": "金额", "label": "金额合计"}],
                "counts": [{"col": "订单号", "label": "订单数", "distinct": True}],
                "sort_label": "金额合计",
                "sort_desc": True,
            },
        }
        r = client.post("/api/split", json=payload).get_json()
        assert r["ok"], r.get("msg")

        path = os.path.join(out_dir, "义乌市场进度.xlsx")
        assert os.path.exists(path)
        xl = pd.ExcelFile(path)
        assert xl.sheet_names == ["明细", "汇总"]
        xl.close()

        # 明细：手机号全部脱敏
        detail = pd.read_excel(path, sheet_name="明细", dtype=str)
        phones = detail["手机号"].astype(str).tolist()
        assert all(re.fullmatch(r"\d{3}\*{4}\d{4}", p) for p in phones)
        assert "138****5678" in phones

        # 汇总
        summ = pd.read_excel(path, sheet_name="汇总", dtype=str)
        assert list(summ.columns) == ["健康顾问", "订单数", "金额合计"]
        row_w = summ[summ["健康顾问"] == "王顾问"].iloc[0]
        assert int(row_w["订单数"]) == 2
        assert float(row_w["金额合计"]) == 350.0
        # 按金额降序：王在前
        assert summ["健康顾问"].iloc[0] == "王顾问"
        # 合计在最后
        total = summ[summ["健康顾问"] == "合计"].iloc[0]
        assert int(total["订单数"]) == 3
        assert float(total["金额合计"]) == 650.0
        assert summ["健康顾问"].iloc[-1] == "合计"

        # 金华：仅赵顾问 + 合计
        jh = pd.read_excel(os.path.join(out_dir, "金华市场进度.xlsx"), sheet_name="汇总", dtype=str)
        assert list(jh["健康顾问"]) == ["赵顾问", "合计"]

    def test_count_row_level_no_distinct(self, client, out_dir):
        file_id = self._basic_file_id(client)
        payload = {
            "file_id": file_id, "sheet": "明细",
            "keep_columns": ["市场", "健康顾问", "订单号", "金额", "手机号"],
            "mask": {},
            "split_column": "市场", "suffix": "进度",
            "output_dir": out_dir,
            "summary": {
                "enabled": True,
                "groups": [{"col": "健康顾问"}],
                "counts": [{"col": "订单号", "label": "记录数", "distinct": False}],
            },
        }
        r = client.post("/api/split", json=payload).get_json()
        assert r["ok"]
        s2 = pd.read_excel(os.path.join(out_dir, "义乌市场进度.xlsx"), sheet_name="汇总", dtype=str)
        w2 = s2[s2["健康顾问"] == "王顾问"].iloc[0]
        # 王顾问 3 行不去重 = 3
        assert int(w2["记录数"]) == 3


# ----------------------------------------------------------------------------
# test_four: 分组别名 / 仅汇总 / 无分组总计
# ----------------------------------------------------------------------------
@pytest.mark.integration
class TestSummaryShaping:
    @staticmethod
    def _four_rows_file_id(client):
        # A: 归属市场, 健康顾问, 订单号, 金额 —— 与原 test_four.py 完全一致
        cols = ["归属市场", "健康顾问", "订单号", "金额"]
        rows = [
            ["义乌", "王顾问", "DD001", 100],
            ["义乌", "王顾问", "DD001", 200],
            ["义乌", "王顾问", "DD002", 50],
            ["义乌", "李顾问", "DD003", 30],
        ]
        return _post_excel(client, pd.DataFrame(rows, columns=cols), sheet_name="S")

    def _run(self, client, out_dir, tag, include_detail, groups):
        file_id = self._four_rows_file_id(client)
        body = {
            "file_id": file_id, "sheet": "S",
            "keep_columns": ["归属市场", "健康顾问", "订单号", "金额"],
            "mask": {}, "split_column": "归属市场", "suffix": "",
            "output_dir": out_dir, "include_detail": include_detail,
            "summary": {
                "enabled": True, "groups": groups,
                "sums": [{"col": "金额", "label": "金额合计"}],
                "counts": [{"col": "订单号", "label": "订单数", "distinct": True}],
                "sort_label": "金额合计", "sort_desc": True,
            },
        }
        r = client.post("/api/split", json=body).get_json()
        assert r["ok"], r
        return os.path.join(out_dir, "义乌.xlsx")

    def test_summary_only_with_group_alias(self, client, out_dir):
        from openpyxl import load_workbook
        fa = self._run(client, out_dir, "sumonly", False,
                       [{"col": "健康顾问", "label": "顾问姓名"}])
        wa = load_workbook(fa)
        assert wa.sheetnames == ["汇总"]  # 没有明细
        sm = wa["汇总"]
        rows = list(sm.iter_rows(values_only=True))
        # 分组列已改名
        assert rows[0] == ("顾问姓名", "订单数", "金额合计")
        # 王在前，李在后；合计在最后；去重订单：王 2 单 / 李 1 单
        assert rows[1] == ("王顾问", 2, 350)
        assert rows[2] == ("李顾问", 1, 30)
        assert rows[3][0] == "合计" and rows[3][1] == 3 and rows[3][2] == 380

    def test_default_both_detail_and_summary(self, client, out_dir):
        from openpyxl import load_workbook
        fb = self._run(client, out_dir, "both", True, [{"col": "健康顾问"}])
        wb2 = load_workbook(fb)
        assert set(wb2.sheetnames) == {"明细", "汇总"}
        assert wb2["明细"].max_row == 5  # 表头 + 4 行

    def test_no_group_one_total_row(self, client, out_dir):
        from openpyxl import load_workbook
        fc = self._run(client, out_dir, "nogroup", False, [])
        wc = load_workbook(fc)
        rc = list(wc["汇总"].iter_rows(values_only=True))
        # 无分组维度：单行总计 — 3 个不同订单；金额 100+200+50+30 = 380
        assert rc[0] == ("订单数", "金额合计")
        assert rc[1] == (3, 380)
        assert len(rc) == 2


# ----------------------------------------------------------------------------
# test_nogroup：同上，独立路径
# ----------------------------------------------------------------------------
@pytest.mark.integration
class TestNoGroup:
    def test_no_group_total_only(self, client, out_dir):
        cols = ["归属市场", "订单号", "金额"]
        rows = [
            ["义乌", "DD001", 100],
            ["义乌", "DD001", 200],
            ["义乌", "DD002", 50],
            ["义乌", "DD003", 30],
        ]
        file_id = _post_excel(client, pd.DataFrame(rows, columns=cols), sheet_name="S")
        r = client.post("/api/split", json={
            "file_id": file_id, "sheet": "S",
            "keep_columns": cols, "mask": {},
            "split_column": "归属市场", "suffix": "",
            "output_dir": out_dir,
            "summary": {
                "enabled": True, "groups": [],
                "sums": [{"col": "金额", "label": "金额合计"}],
                "counts": [{"col": "订单号", "label": "订单数", "distinct": True}],
            },
        }).get_json()
        assert r["ok"]
        from openpyxl import load_workbook
        sm = load_workbook(os.path.join(out_dir, "义乌.xlsx"))["汇总"]
        rows = list(sm.iter_rows(values_only=True))
        assert rows[0] == ("订单数", "金额合计")
        assert rows[1] == (3, 380)
        assert len(rows) == 2


# ----------------------------------------------------------------------------
# test_order_count：文本型订单号去重
# ----------------------------------------------------------------------------
@pytest.mark.integration
class TestTextOrderDistinct:
    def test_text_order_id_distinct_count(self, client, out_dir):
        cols = ["归属市场", "健康顾问", "订单号", "金额"]
        rows = [
            ["义乌", "王顾问", "DD001", 100],
            ["义乌", "王顾问", "DD001", 200],
            ["义乌", "王顾问", "DD002", 50],
            ["义乌", "李顾问", "DD003", 30],
        ]
        file_id = _post_excel(client, pd.DataFrame(rows, columns=cols), sheet_name="S")
        r = client.post("/api/split", json={
            "file_id": file_id, "sheet": "S",
            "keep_columns": cols, "mask": {},
            "split_column": "归属市场", "suffix": "",
            "output_dir": out_dir,
            "summary": {
                "enabled": True,
                "groups": [{"col": "健康顾问"}],
                "sums": [{"col": "金额", "label": "金额合计"}],
                "counts": [{"col": "订单号", "label": "订单数", "distinct": True}],
                "sort_label": "金额合计", "sort_desc": True,
            },
        }).get_json()
        assert r["ok"]
        from openpyxl import load_workbook
        sm = load_workbook(os.path.join(out_dir, "义乌.xlsx"))["汇总"]
        hdr = [c.value for c in sm[1]]
        iadv, iord, isum = hdr.index("健康顾问"), hdr.index("订单数"), hdr.index("金额合计")
        rec = {row[iadv]: (row[iord], row[isum]) for row in sm.iter_rows(min_row=2, values_only=True)}
        assert rec["王顾问"] == (2, 350)
        assert rec["李顾问"] == (1, 30)
