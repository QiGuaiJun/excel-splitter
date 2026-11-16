# -*- coding: utf-8 -*-
"""汇总构建器。

来源背景：原本在 api/distribute.py（build_summary，约 50 行）。
本批把业务规则搬到 services 层，分发路由只做调用。
"""
import pandas as pd


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


def _apply_order(res: pd.DataFrame, order) -> pd.DataFrame:
    """按前端给定的列顺序重排；未出现在 order 里的列按原顺序跟在后面。"""
    cols = [str(o) for o in (order or [])]
    picked = [c for c in dict.fromkeys(cols) if c in res.columns]
    if not picked:
        return res
    rest = [c for c in res.columns if c not in picked]
    return res[picked + rest]


def build_summary(sub: pd.DataFrame, scfg: dict):
    """聚合：计数(行数/去重)+求和，末行合计；支持分组列别名；无分组时整表一行总计。

    scfg 结构：
    {
      "groups":  [{"col": "健康顾问", "label": "顾问姓名"}],
      "sums":    [{"col": "金额", "label": "金额合计"}],
      "counts":  [{"col": "订单号", "label": "订单数", "distinct": true}],
      "order":   ["顾问姓名", "金额合计", "订单数"],   # 可选，最终列顺序
      "sort_label": "金额合计",
      "sort_desc":  true,
    }
    """
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

    if not gcols:
        # 无分组维度：整张表只输出一行总计
        return _apply_order(pd.DataFrame([_whole_row(work)])[metric_cols], scfg.get("order"))

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
    disp_g = [galias[g] for g in gcols]
    order = [str(o) for o in (scfg.get("order") or [])]
    # 「合计」始终落在重排后最左边的分组列（用户把某个维度拖到前面时也跟着走）
    first_disp = next((o for o in order if o in disp_g), disp_g[0])
    for g in gcols:
        total[g] = ""
    total[alias2col.get(first_disp, first_disp)] = "合计"
    res = pd.concat([res, pd.DataFrame([total])], ignore_index=True)
    res = res[gcols + metric_cols].rename(columns=galias)
    return _apply_order(res, scfg.get("order"))
