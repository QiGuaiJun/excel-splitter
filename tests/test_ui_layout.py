# -*- coding: utf-8 -*-
"""前端布局 / 组件交互回归测试。

这里锁定的是几类真实发生过的"组件显示不完整 / 点了没反应"缺陷，
改动前端时如果把它们改回去，这些断言会立刻失败：

1. 面板淡入动画依赖 opacity —— 浏览器节流动画时整页停在 opacity:0，看着像空白页。
2. renderFields 用全局 ``.fcard`` 选择器 —— 会选中步骤 3 的汇总卡（复选框是 .gchk），
   取到 null 后在绑定 onchange 时抛错，步骤 2 渲染中断。
3. 模块 init 在 sources.js 加载期用 ``typeof CL_init`` 判断 —— 那时 clean.js / calc.js /
   logs.js 还没加载，永远是 false，导致三个模块进入后列表从不渲染。
4. 汇总设置的标题 / 单选项 / 说明在窄容器里被压成竖排（flex 不换行、标题没有 nowrap）。
5. 运行历史表头用固定 180px + 1fr 列宽 —— 窄容器下 1fr 被压到 0，"数据源"竖排成三行。
6. 脱敏正则输入框过窄 —— 正则表达式被截断，看不出自己填了什么。
7. 清洗 / 计算 / 运行历史在接口失败时整块留白，没有任何提示。

只做静态断言，不依赖 MySQL 与运行中的服务，任何环境都能跑。
"""

from pathlib import Path
import re

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_HTML = BASE_DIR / "templates" / "index.html"
LOGS_CSS = BASE_DIR / "static" / "logs.css"
CLEAN_CSS = BASE_DIR / "static" / "clean.css"
CALC_CSS = BASE_DIR / "static" / "calc.css"
SOURCES_JS = BASE_DIR / "static" / "sources.js"
CLEAN_JS = BASE_DIR / "static" / "clean.js"
CALC_JS = BASE_DIR / "static" / "calc.js"
LOGS_JS = BASE_DIR / "static" / "logs.js"


def _read(path: Path) -> str:
    assert path.exists(), f"文件不存在：{path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 整页可见性


def test_panel_fade_animation_does_not_depend_on_opacity():
    """面板淡入只能做位移，不能靠 opacity —— 否则动画卡住时整页不可见。"""
    html = _read(INDEX_HTML)
    fade_block = html.split("@keyframes fade", 1)[1].split("}", 1)[0]
    assert "opacity" not in fade_block, "面板动画不要用 opacity，否则可能整页空白"


def test_page_head_is_flex_row():
    """模块页头要有 flex 布局，标题与右侧操作按钮才能同行。"""
    html = _read(INDEX_HTML)
    assert ".page-head{display:flex" in html.replace(" ", "")
    assert ".page-sub{" in html


# ---------------------------------------------------------------- 字段与脱敏


def test_render_fields_binds_only_field_grid_cards():
    """字段卡的点击 / 勾选事件只能绑定在 #fieldGrid 内，避免选中步骤 3 的汇总卡。"""
    html = _read(INDEX_HTML)
    assert 'document.querySelectorAll("#fieldGrid .fcard")' in html
    assert 'document.querySelectorAll(".fcard")' not in html


def test_regex_input_is_wide_enough():
    """正则输入框宽度足够显示完整正则（历史缺陷：172px 把正则截断）。"""
    html = _read(INDEX_HTML)
    line = [l for l in html.splitlines() if ".opt-extra input.re" in l][0]
    width = int(line.split("width:", 1)[1].split("px", 1)[0])
    assert width >= 240, f"正则输入框只有 {width}px，会把正则表达式截断"


def test_lab_title_wraps_without_squeezing():
    """.sub-block 的标题不能因为提示文字太长而被压成竖排。"""
    html = _read(INDEX_HTML)
    assert ".sub-block .lab{" in html
    block = html.split(".sub-block .lab{", 1)[1].split("}", 1)[0]
    assert "flex-wrap:wrap" in block
    assert ".sub-block .lab .lab-t{" in html
    title_block = html.split(".sub-block .lab .lab-t{", 1)[1].split("}", 1)[0]
    assert "white-space:nowrap" in title_block
    # 三处带提示的标题都要包 lab-t
    assert html.count('class="lab-t"') >= 3


# ---------------------------------------------------------------- 汇总设置


def test_sum_toggle_wraps_and_labels_do_not_squeeze():
    """汇总设置顶部的开关行要能换行，标题与单选项不能被压成竖排。"""
    html = _read(INDEX_HTML)
    block = html.split(".sum-toggle{", 1)[1].split("}", 1)[0]
    assert "flex-wrap:wrap" in block
    assert ".sum-toggle .sum-label{" in html
    label_block = html.split(".sum-toggle .sum-label{", 1)[1].split("}", 1)[0]
    assert "white-space:nowrap" in label_block


def test_summary_grid_falls_back_to_single_column():
    """汇总设置两栏在窄视口要退化成单列，否则右侧预览被压得只剩两百像素。"""
    html = _read(INDEX_HTML)
    assert ".sum-grid{" in html
    assert re.search(
        r"@media\s*\(max-width:1280px\)\s*\{\s*\.sum-grid\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\)",
        html,
    ), "汇总设置缺少窄屏单列回退"


# ---------------------------------------------------------------- 配置模板栏


def test_template_select_can_shrink():
    """模板栏下拉框要能收缩，否则删除按钮会被挤到第二行。"""
    html = _read(INDEX_HTML)
    line = [l for l in html.splitlines() if l.startswith(".tplbar select{")][0]
    assert "flex:1" in line and "max-width:240px" in line


# ---------------------------------------------------------------- 运行历史


def test_log_table_columns_are_shrinkable():
    """运行历史列宽不能再是固定 180px + 1fr，否则窄容器里表头文字竖排。"""
    css = _read(LOGS_CSS)
    header = css.split(".log-header {", 1)[1].split("}", 1)[0]
    assert "180px" not in header
    assert "minmax(0, 1fr)" in header
    assert "white-space: nowrap" in css
    assert ".log-pagination:empty" in css, "空分页容器不应留下一条空白占位条"


# ---------------------------------------------------------------- 空态与失败提示


def test_module_init_resolved_by_name_at_runtime():
    """模块 init 必须在点击时按名字解析，不能在加载期用 typeof 求值。"""
    js = _read(SOURCES_JS)
    assert 'initName: "CL_init"' in js
    assert 'initName: "CA_init"' in js
    assert 'initName: "LOG_init"' in js
    assert 'typeof window[cfg.initName] === "function"' in js


def test_task_lists_render_visible_error_when_api_fails():
    """清洗 / 计算 / 运行历史接口失败时要给出可见提示，不能整块留白。"""
    for path in (CLEAN_JS, CALC_JS, LOGS_JS):
        js = _read(path)
        assert "renderLoadError" in js, f"{path.name} 缺少接口失败时的可见提示"
        assert "empty-state" in js, f"{path.name} 空态样式没有复用统一类"


def test_clean_and_calc_workspaces_collapse_on_narrow_viewport():
    """清洗 / 计算的配置区与预览区在窄视口要上下排列。"""
    for path in (CLEAN_CSS, CALC_CSS):
        css = _read(path)
        assert "max-width: 1180px" in css, f"{path.name} 缺少窄屏单列回退"
        assert "minmax(0, 1fr)" in css
