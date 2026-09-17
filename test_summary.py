# -*- coding: utf-8 -*-
"""汇总功能自测：去重计数 / 求和 / 合计 / 排序 / 双Sheet / 与脱敏共存"""
import os, sys, shutil
from io import BytesIO
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "test_sum_out")
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT, exist_ok=True)
fail = 0
def check(name, cond, extra=""):
    global fail
    print(("[通过] " if cond else "[失败] ") + name + (f"  -> {extra}" if extra else ""))
    if not cond: fail += 1

# 数据：义乌 A顾问 O1单两行(100+50) O2单200；B顾问 O3单300；金华 C顾问 O4单1000
cols = ["市场","健康顾问","订单号","金额","手机号"]
rows = [
 ["义乌市场","王顾问","O1","100","13812345678"],
 ["义乌市场","王顾问","O1","50","13812345678"],
 ["义乌市场","王顾问","O2","200","13911112222"],
 ["义乌市场","李顾问","O3","300","13733334444"],
 ["金华市场","赵顾问","O4","1000","13655556666"],
]
src = os.path.join(BASE,"test_sum.xlsx")
pd.DataFrame(rows,columns=cols).to_excel(src,sheet_name="明细",index=False)

client = A.app.test_client()
with open(src,"rb") as fp:
    j = client.post("/api/inspect", data={"file":(BytesIO(fp.read()),"test_sum.xlsx")},
                    content_type="multipart/form-data").get_json()
check("inspect ok", j and j.get("ok"))
check("识别金额列为数值型", j["sheets"][0]["colMeta"]["金额"]["numeric"] is True, str(j["sheets"][0]["colMeta"]))

payload = {
 "file_id": j["file_id"], "sheet":"明细",
 "keep_columns": cols,
 "mask": {"手机号":{"type":"phone"}},
 "split_column":"市场", "suffix":"进度", "output_dir":OUT,
 "summary":{
   "enabled":True,
   "groups":[{"col":"健康顾问"}],
   "sums":[{"col":"金额","label":"金额合计"}],
   "counts":[{"col":"订单号","label":"订单数","distinct":True}],
   "sort_label":"金额合计","sort_desc":True
 }
}
r = client.post("/api/split", json=payload).get_json()
check("split ok", r.get("ok"), str(r.get("msg")))

path = os.path.join(OUT,"义乌市场进度.xlsx")
check("义乌文件存在", os.path.exists(path))
xl = pd.ExcelFile(path)
check("含两个Sheet(明细/汇总)", xl.sheet_names==["明细","汇总"], str(xl.sheet_names))
xl.close()

detail = pd.read_excel(path, sheet_name="明细", dtype=str)
check("明细手机号已脱敏", detail["手机号"].iloc[0]=="138****5678", str(detail["手机号"].iloc[0]))

summ = pd.read_excel(path, sheet_name="汇总", dtype=str)
check("汇总列名正确", list(summ.columns)==["健康顾问","订单数","金额合计"], str(list(summ.columns)))
# 王顾问: 去重订单2(O1,O2) 金额350; 李顾问: 订单1 金额300; 按金额降序 王在前
row_w = summ[summ["健康顾问"]=="王顾问"].iloc[0]
check("王顾问去重订单数=2", row_w["订单数"]=="2", str(row_w["订单数"]))
check("王顾问金额合计=350", float(row_w["金额合计"])==350.0, str(row_w["金额合计"]))
check("按金额降序(王在李前)", summ["健康顾问"].iloc[0]=="王顾问", str(list(summ["健康顾问"])))
total = summ[summ["健康顾问"]=="合计"].iloc[0]
check("末行合计订单数=3", total["订单数"]=="3", str(total["订单数"]))
check("末行合计金额=650", float(total["金额合计"])==650.0, str(total["金额合计"]))
check("合计在最后一行", summ["健康顾问"].iloc[-1]=="合计")

jh = pd.read_excel(os.path.join(OUT,"金华市场进度.xlsx"), sheet_name="汇总", dtype=str)
check("金华汇总仅赵顾问+合计", list(jh["健康顾问"])==["赵顾问","合计"], str(list(jh["健康顾问"])))

# 数行数模式（不去重）：王顾问应为3行=3单
payload2 = dict(payload)
payload2["summary"] = {**payload["summary"],
  "counts":[{"col":"订单号","label":"记录数","distinct":False}], "sort_label":"记录数","sort_desc":True}
OUT2 = os.path.join(BASE,"test_sum_out2"); shutil.rmtree(OUT2, ignore_errors=True); os.makedirs(OUT2)
payload2["output_dir"]=OUT2
r2 = client.post("/api/split", json=payload2).get_json()
s2 = pd.read_excel(os.path.join(OUT2,"义乌市场进度.xlsx"), sheet_name="汇总", dtype=str)
w2 = s2[s2["健康顾问"]=="王顾问"].iloc[0]
check("数行数模式 王顾问=3", w2["记录数"]=="3", str(w2["记录数"]))

print("\n"+"="*40)
if fail: print(f"存在 {fail} 项未通过"); sys.exit(1)
print("汇总功能全部测试通过 ✓")
