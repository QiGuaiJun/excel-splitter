# -*- coding: utf-8 -*-
"""工作台自测：造数据 -> 调接口 -> 校验脱敏/拆分/脏数据中止"""
import os
import sys
import shutil
from io import BytesIO
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_OUT = os.path.join(BASE, "test_out")
shutil.rmtree(TEST_OUT, ignore_errors=True)
os.makedirs(TEST_OUT, exist_ok=True)

fail = 0
def check(name, cond, extra=""):
    global fail
    print(("[通过] " if cond else "[失败] ") + name + (f"  -> {extra}" if extra else ""))
    if not cond:
        fail += 1

# ---------- 1. 脱敏函数单测 ----------
check("手机号 138****5678", A.mask_phone("13812345678") == "138****5678", A.mask_phone("13812345678"))
check("身份证 前4后4", A.mask_idcard("330782199001011234") == "3307" + "*"*10 + "1234", A.mask_idcard("330782199001011234"))
check("地址-县级市义乌", A.mask_address("浙江省金华市义乌市稠城街道城中北路123号") == "浙江省金华市义乌市****", A.mask_address("浙江省金华市义乌市稠城街道城中北路123号"))
check("地址-杭州西湖区", A.mask_address("浙江省杭州市西湖区文三路100号") == "浙江省杭州市西湖区****", A.mask_address("浙江省杭州市西湖区文三路100号"))
check("地址-北京朝阳区", A.mask_address("北京市朝阳区建国路88号") == "北京市朝阳区****", A.mask_address("北京市朝阳区建国路88号"))
check("地址-自治区南宁兴宁区", A.mask_address("广西壮族自治区南宁市兴宁区民生路1号") == "广西壮族自治区南宁市兴宁区****", A.mask_address("广西壮族自治区南宁市兴宁区民生路1号"))
check("姓名留姓", A.mask_name("欧阳娜") == "欧**", A.mask_name("欧阳娜"))
check("留前3后4", A.mask_keep_ab("13812345678", 3, 4) == "138****5678")

# ---------- 2. 造正常测试表 ----------
cols = ["客户姓名","手机号","身份证号","详细地址","市场","企微号","备注"]
rows = [
 ["张伟","13812345678","330782199001011234","浙江省金华市义乌市稠城街道城中北路123号","义乌市场","qw001","a"],
 ["李娜","13998765432","33078219880505678X","浙江省金华市义乌市北苑街道机场路55号","义乌市场","qw002","b"],
 ["王芳","13711112222","330106199203045678","浙江省杭州市西湖区文三路100号","杭州市场","qw003","c"],
 ["赵磊","13533334444","110105200001011234","北京市朝阳区建国路88号","北京市场","qw004","d"],
 ["陈静","13655556666","450103199507071234","广西壮族自治区南宁市兴宁区民生路1号","南宁市场","qw005","e"],
]
normal_path = os.path.join(BASE, "test_normal.xlsx")
with pd.ExcelWriter(normal_path, engine="openpyxl") as w:
    pd.DataFrame(rows, columns=cols).to_excel(w, sheet_name="好友明细", index=False)
    pd.DataFrame([["说明sheet"]], columns=["x"]).to_excel(w, sheet_name="说明", index=False)

client = A.app.test_client()

def upload(path):
    with open(path,"rb") as fp:
        data = {"file": (BytesIO(fp.read()), os.path.basename(path))}
    return client.post("/api/inspect", data=data, content_type="multipart/form-data").get_json()

j = upload(normal_path)
check("inspect 成功", j and j.get("ok") is True)
check("读出两个子表", [s["name"] for s in j["sheets"]] == ["好友明细","说明"], str([s["name"] for s in j["sheets"]]))
check("读出7个字段", j["sheets"][0]["columns"] == cols, str(j["sheets"][0]["columns"]))

# ---------- 3. 正常拆分 ----------
payload = {
    "file_id": j["file_id"], "sheet": "好友明细",
    "keep_columns": ["客户姓名","手机号","身份证号","详细地址","市场"],
    "mask": {"手机号":{"type":"phone"},"身份证号":{"type":"idcard"},"详细地址":{"type":"address"}},
    "split_column": "市场", "suffix": "8月测试（0826）", "output_dir": TEST_OUT
}
r = client.post("/api/split", json=payload).get_json()
check("split 成功", r.get("ok") is True, str(r.get("msg")))
check("拆成4份", r.get("total") == 4, str(r.get("total")))
files = sorted(os.listdir(TEST_OUT))
check("文件名=市场+后缀", "义乌市场8月测试（0826）.xlsx" in files, str(files))

yw = pd.read_excel(os.path.join(TEST_OUT,"义乌市场8月测试（0826）.xlsx"), dtype=str)
check("义乌文件2行", len(yw)==2, str(len(yw)))
check("只含保留的5列(删除字段生效)", list(yw.columns)==payload["keep_columns"], str(list(yw.columns)))
row0 = yw.iloc[0].to_dict()
check("义乌手机号脱敏", row0["手机号"]=="138****5678", str(row0["手机号"]))
check("义乌身份证脱敏", row0["身份证号"]=="3307**********1234", str(row0["身份证号"]))
check("义乌地址脱敏到县级市", row0["详细地址"]=="浙江省金华市义乌市****", str(row0["详细地址"]))
check("拆分列值正确保留", set(yw["市场"])=={"义乌市场"})

bj = pd.read_excel(os.path.join(TEST_OUT,"北京市场8月测试（0826）.xlsx"), dtype=str).iloc[0]
check("北京地址脱敏", bj["详细地址"]=="北京市朝阳区****", str(bj["详细地址"]))
nn = pd.read_excel(os.path.join(TEST_OUT,"南宁市场8月测试（0826）.xlsx"), dtype=str).iloc[0]
check("自治区地址脱敏", nn["详细地址"]=="广西壮族自治区南宁市兴宁区****", str(nn["详细地址"]))

# ---------- 4. 脏数据：空值 + 一格多值 -> 中止 ----------
dirty = rows + [
 ["空值","13800000000","330782200001011234","浙江省金华市东阳市横店镇","","qw006","f"],
 ["多值","13800000001","330782200001011235","浙江省金华市兰溪市","义乌市场,杭州市场","qw007","g"],
]
dirty_path = os.path.join(BASE,"test_dirty.xlsx")
pd.DataFrame(dirty, columns=cols).to_excel(dirty_path, sheet_name="好友明细", index=False)
jd = upload(dirty_path)
shutil.rmtree(TEST_OUT); os.makedirs(TEST_OUT)  # 清空输出目录
payload2 = dict(payload); payload2["file_id"]=jd["file_id"]
rd = client.post("/api/split", json=payload2).get_json()
check("脏数据整体中止", rd.get("ok") is False and rd.get("aborted") is True, str(rd.get("msg")))
check("中止时不生成任何文件", os.listdir(TEST_OUT)==[], str(os.listdir(TEST_OUT)))
check("报出2条问题", rd.get("problem_total")==2, str(rd.get("problems")))
check("问题行号正确(空值在第7行)", any(p["row"]==7 and p["reason"]=="拆分字段为空" for p in rd["problems"]), str(rd["problems"]))
check("识别一格多值", any("多个值" in p["reason"] for p in rd["problems"]), str(rd["problems"]))

print("\n" + ("="*40))
if fail:
    print(f"存在 {fail} 项未通过，请修复")
    sys.exit(1)
print("全部测试通过 ✓")
