# -*- coding: utf-8 -*-
import os, shutil
from io import BytesIO
from openpyxl import Workbook, load_workbook
import app

shutil.rmtree("_oc", ignore_errors=True); os.makedirs("_oc")
wb = Workbook(); ws = wb.active; ws.title = "S"
ws.append(["归属市场", "健康顾问", "订单号", "金额"])
ws.append(["义乌", "王顾问", "DD001", "100"])
ws.append(["义乌", "王顾问", "DD001", "200"])  # 同一订单第二行
ws.append(["义乌", "王顾问", "DD002", "50"])
ws.append(["义乌", "李顾问", "DD003", "30"])
wb.save("_oc.xlsx")

c = app.app.test_client()
with open("_oc.xlsx", "rb") as f:
    j = c.post("/api/inspect", data={"file": (BytesIO(f.read()), "_oc.xlsx")},
               content_type="multipart/form-data").get_json()
r = c.post("/api/split", json={
    "file_id": j["file_id"], "sheet": "S",
    "keep_columns": ["归属市场", "健康顾问", "订单号", "金额"],
    "mask": {}, "split_column": "归属市场", "suffix": "",
    "output_dir": os.path.abspath("_oc"),
    "summary": {"enabled": True,
                "groups": [{"col": "健康顾问"}],
                "sums": [{"col": "金额", "label": "金额合计"}],
                "counts": [{"col": "订单号", "label": "订单数", "distinct": True}],
                "sort_label": "金额合计", "sort_desc": True}}).get_json()
print("ok=", r.get("ok"), r.get("msg"))
sm = load_workbook(os.path.join("_oc", "义乌.xlsx"))["汇总"]
for row in sm.iter_rows(values_only=True):
    print(row)
data = {row[0]: row for row in sm.iter_rows(values_only=True)}
hdr = [x.value for x in sm[1]]
iadv, iord, isum = hdr.index("健康顾问"), hdr.index("订单数"), hdr.index("金额合计")
rec = {row[iadv]: (row[iord], row[isum]) for row in sm.iter_rows(min_row=2, values_only=True)}
assert rec["王顾问"] == (2, 350), rec  # DD001/DD002 去重=2，金额 100+200+50=350
assert rec["李顾问"] == (1, 30), rec
print("[结论] 文本订单号可去重计数：王顾问 2 单/350，李顾问 1 单/30 ✓")
