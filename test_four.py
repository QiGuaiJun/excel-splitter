# -*- coding: utf-8 -*-
import os, shutil
from io import BytesIO
from openpyxl import Workbook, load_workbook
import app

shutil.rmtree("_t4", ignore_errors=True); os.makedirs("_t4")
wb = Workbook(); ws = wb.active; ws.title = "S"
ws.append(["归属市场", "健康顾问", "订单号", "金额"])
ws.append(["义乌", "王顾问", "DD001", "100"])
ws.append(["义乌", "王顾问", "DD001", "200"])
ws.append(["义乌", "王顾问", "DD002", "50"])
ws.append(["义乌", "李顾问", "DD003", "30"])
wb.save("_t4.xlsx")
c = app.app.test_client()
with open("_t4.xlsx", "rb") as f:
    j = c.post("/api/inspect", data={"file": (BytesIO(f.read()), "_t4.xlsx")},
               content_type="multipart/form-data").get_json()

def run(tag, include_detail, groups):
    out = os.path.abspath("_t4/" + tag); os.makedirs(out, exist_ok=True)
    body = {"file_id": j["file_id"], "sheet": "S",
            "keep_columns": ["归属市场", "健康顾问", "订单号", "金额"],
            "mask": {}, "split_column": "归属市场", "suffix": "",
            "output_dir": out, "include_detail": include_detail,
            "summary": {"enabled": True, "groups": groups,
                        "sums": [{"col": "金额", "label": "金额合计"}],
                        "counts": [{"col": "订单号", "label": "订单数", "distinct": True}],
                        "sort_label": "金额合计", "sort_desc": True}}
    r = c.post("/api/split", json=body).get_json()
    assert r.get("ok"), r
    return os.path.join(out, "义乌.xlsx")

# A: 仅汇总 + 分组别名“顾问姓名”
fa = run("sumonly", False, [{"col": "健康顾问", "label": "顾问姓名"}])
wa = load_workbook(fa)
print("A sheetnames:", wa.sheetnames)
assert wa.sheetnames == ["汇总"], wa.sheetnames  # 没有明细
sm = wa["汇总"]
for row in sm.iter_rows(values_only=True):
    print("  ", row)
rows = list(sm.iter_rows(values_only=True))
assert rows[0] == ("顾问姓名", "订单数", "金额合计"), rows[0]  # 分组列已改名
assert rows[1] == ("王顾问", 2, 350), rows[1]                    # 金额降序王在前
assert rows[2] == ("李顾问", 1, 30), rows[2]
assert rows[3][0] in (None, "") and rows[3][1] == 3 and rows[3][2] == 380, rows[3]

# B: 默认明细+汇总
fb = run("both", True, [{"col": "健康顾问"}])
wb2 = load_workbook(fb)
print("B sheetnames:", wb2.sheetnames)
assert set(wb2.sheetnames) == {"明细", "汇总"}, wb2.sheetnames
assert wb2["明细"].max_row == 5  # 表头+4行

# C: 无分组、只计数/求和 -> 汇总一行总计（回归）
fc = run("nogroup", False, [])
wc = load_workbook(fc)
rc = list(wc["汇总"].iter_rows(values_only=True))
print("C:", rc)
assert rc[0] == ("订单数", "金额合计") and rc[1] == (3, 380), rc

print("[结论] 分组别名 / 仅汇总(无明细) / 无分组总计 / 排序 全部正确 ✓")
