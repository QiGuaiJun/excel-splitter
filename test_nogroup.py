# -*- coding: utf-8 -*-
import os, shutil
from io import BytesIO
from openpyxl import Workbook, load_workbook
import app

shutil.rmtree("_ng", ignore_errors=True); os.makedirs("_ng")
wb = Workbook(); ws = wb.active; ws.title = "S"
ws.append(["归属市场", "订单号", "金额"])
ws.append(["义乌", "DD001", "100"])
ws.append(["义乌", "DD001", "200"])
ws.append(["义乌", "DD002", "50"])
ws.append(["义乌", "DD003", "30"])
wb.save("_ng.xlsx")
c = app.app.test_client()
with open("_ng.xlsx", "rb") as f:
    j = c.post("/api/inspect", data={"file": (BytesIO(f.read()), "_ng.xlsx")},
               content_type="multipart/form-data").get_json()

# 场景：无分组维度，只对订单号去重计数 + 金额求和
r = c.post("/api/split", json={
    "file_id": j["file_id"], "sheet": "S",
    "keep_columns": ["归属市场", "订单号", "金额"],
    "mask": {}, "split_column": "归属市场", "suffix": "",
    "output_dir": os.path.abspath("_ng"),
    "summary": {"enabled": True, "groups": [],
                "sums": [{"col": "金额", "label": "金额合计"}],
                "counts": [{"col": "订单号", "label": "订单数", "distinct": True}]}}).get_json()
print("ok=", r.get("ok"), r.get("msg"))
sm = load_workbook(os.path.join("_ng", "义乌.xlsx"))["汇总"]
for row in sm.iter_rows(values_only=True):
    print("汇总:", row)
rows = list(sm.iter_rows(values_only=True))
assert rows[0] == ("订单数", "金额合计"), rows[0]
assert rows[1] == (3, 380), rows[1]  # 3 个不同订单；金额 100+200+50+30=380
assert len(rows) == 2, "无分组应只有表头+一行总计"
print("[结论] 无分组维度时，汇总只输出一行总计：订单数=3，金额=380 ✓")
