# 智能化数据分析工作台 - 开发文档

> 最后更新：2026-11-12

## 一、项目概述

### 1.1 项目愿景
从「Excel 智能分表脱敏工具」演进为覆盖 **采集 → 清洗 → 处理 → 计算 → 分发** 全链路的本地网页工作台。

### 1.2 核心模块
| 模块 | 状态 | 说明 |
|------|------|------|
| 数据源管理中心 | 🟡 开发中 | 多通道采集、分类管理、数据预览 |
| 数据清洗 | ⚪ 待开发 | 清洗规则、层级视图 |
| 数据处理/计算 | ⚪ 待开发 | SQL计算、表关联、模型计算 |
| 数据分发 | 🟢 已完成 | 分表、脱敏、汇总、子表合并 |
| 运行历史 | ⚪ 待开发 | 采集/分发日志详情 |
| 智能体 | ⚪ 待接入 | AI助手，后续给接口 |

### 1.3 技术栈
- **后端**：Flask + Python 3.12
- **数据库**：MySQL 8.0（测试实例端口 3307，root 无密码）
- **前端**：原生 HTML/CSS/JS（单页应用，无框架）
- **数据处理**：pandas + openpyxl（read_only 流式解析，5万行0.66秒）
- **服务地址**：http://127.0.0.1:18765/

---

## 二、项目结构

```
excel-splitter/
├── app.py                  # Flask 入口，注册蓝图
├── AGENTS.md               # 项目规范（commit + 测试）
├── DEVELOPMENT.md          # 本文档
├── requirements.txt        # Python 依赖
├── 启动工作台.bat           # 一键启动脚本
├── api/
│   ├── collect.py          # 采集通道（Excel/文件夹/代码爬取）
│   ├── sources.py          # 数据源/分类 CRUD、分页、搜索
│   └── distribute.py       # 数据分发（分表/脱敏/汇总）
├── db/
│   ├── connection.py       # MySQL 连接（pymysql + DictCursor）
│   ├── dao.py              # 数据访问层（Category/DataSource/CollectionLog）
│   ├── schema.sql          # 建表脚本
│   └── init_db.py          # 初始化数据库
├── static/
│   ├── sources.js          # 数据源管理前端逻辑
│   ├── sources.css         # 数据源管理样式
│   └── ...                 # 其他模块 JS/CSS
├── templates/
│   └── index.html          # 单页应用主模板
├── tests/
│   ├── test_dao.py         # DAO 层测试
│   ├── test_api.py         # API 层测试
│   └── test_e2e.py         # 端到端测试
├── data/
│   └── sources/            # 采集的数据源文件（xlsx/json）
├── config/
│   └── database.json       # 数据库连接配置（gitignore，不入库）
├── configs/                # 分发配置模板
└── prototypes/             # 高保真原型（gitignore）
```

---

## 三、数据库设计

### 3.1 categories（分类表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK AUTO_INCREMENT | 分类ID |
| name | VARCHAR(100) | 分类名称 |
| description | VARCHAR(500) | 分类描述 |
| sort_order | INT | 排序 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

### 3.2 data_sources（数据源表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK AUTO_INCREMENT | 数据源ID |
| name | VARCHAR(200) | 数据源名称 |
| description | VARCHAR(500) | 描述 |
| category_id | INT NULL | 所属分类（NULL=未分类） |
| channel | VARCHAR(50) | 采集通道：excel/folder/crawler/database |
| file_path | VARCHAR(500) | 源文件路径 |
| config | JSON | 扩展配置（原始文件名、字段列表、爬虫参数等） |
| status | VARCHAR(20) | 状态：ready/pending/failed |
| row_count | INT | 行数 |
| col_count | INT | 列数 |
| sheet_names | JSON | 子表名列表 |
| last_collected_at | DATETIME | 最后采集时间 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

### 3.3 collection_logs（采集日志表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK AUTO_INCREMENT | 日志ID |
| source_id | INT | 关联数据源 |
| status | VARCHAR(20) | success/failed |
| row_count | INT | 采集行数 |
| duration_ms | INT | 耗时(ms) |
| error_msg | TEXT | 错误信息 |
| created_at | DATETIME | 创建时间 |

---

## 四、API 文档

### 4.1 分类管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/categories | 分类列表（含各分类数据源统计） |
| POST | /api/categories | 新建分类 |
| PUT | /api/categories/<id> | 更新分类 |
| DELETE | /api/categories/<id> | 删除分类（级联清空数据源分类） |

### 4.2 数据源管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/sources | 数据源列表（支持 category_id/keyword/page/page_size 分页） |
| GET | /api/sources/<id> | 数据源详情 |
| PUT | /api/sources/<id> | 更新数据源（名称/分类/描述） |
| DELETE | /api/sources/<id> | 删除数据源（级联删除日志） |
| GET | /api/sources/<id>/preview | 数据预览（limit 参数） |
| POST | /api/sources/<id>/recollect | 重新采集 |

### 4.3 采集通道
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/collect/excel | Excel 文件上传采集（multipart/form-data） |
| POST | /api/collect/folder | 文件夹批量导入 |
| GET | /api/scan-folder | 扫描文件夹（path/recursive） |
| GET | /api/select-folder | 弹出系统文件夹选择对话框（tkinter） |
| POST | /api/crawler/generate-code | 生成 JS 抓取代码（JSON: name/api_url/limit/concurrency/delay） |
| POST | /api/crawler/import-json | 上传 JSON 解析为数据源（multipart/form-data） |

### 4.4 数据分发
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/distribute/split | 分表（按指定列拆分） |
| POST | /api/distribute/summary | 汇总表（分组/求和/计数） |
| POST | /api/distribute/merge-sheets | 子表合并（加来源列） |

### 4.5 全表脱敏
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/desensitize/scan | 上传工作簿并预扫描所有子表（multipart/form-data: file），返回每个子表命中的敏感列与样例 |
| POST | /api/desensitize/run | 按 `file_id + output_dir` 执行脱敏，输出「一个文件多 sheet」（JSON） |
| POST | /api/browse_folder | 复用分发模块的系统文件夹选择框 |

`scan` 返回 `{ok, file_id, filename, sheets:[{name, rows, hits:[{col, kind, by, ratio, sample_in, sample_out}]}], hit_sheets, total_sheets}`；
`run` 返回 `{ok, out_path, filename, sheets:[{name, rows, cols:[{col,kind,count}], masked}], skipped:[{name,rows}], total_masked, out_sheets, total_sheets}`。

---

## 五、功能开发进度

### 5.1 数据源管理中心 🟡
- [x] 分类 CRUD
- [x] 数据源 CRUD
- [x] Excel 文件采集（支持 .xlsx/.xls/.csv，大文件流式解析）
- [x] 文件夹批量导入（手动输入路径 + 系统对话框选择）
- [x] 文件夹扫描预览（文件列表/大小/修改时间）
- [x] 重新采集
- [x] 数据预览
- [x] 层级结构（第一层分类汇总卡片 + 第二层分类详情）
- [x] 拖拽上传（整个面板支持拖拽）
- [x] 改分类（下拉框弹窗）
- [x] 未分类筛选（category_id=none）
- [x] 分页（每页20/50条切换，上一页/下一页）
- [x] 搜索增强（名称 + 原始文件名模糊匹配）
- [x] 时间修复（datetime 转本地时间字符串，避免8小时偏差）
- [x] 代码爬取通道（生成JS代码 + 上传JSON解析）
- [ ] 数据库连接通道（待接入接口，用户后续给）
- [ ] 敏感配置加密（用户说"测试联通后再加密"）
- [x] 运行历史详情页（统计卡片+筛选+列表+分页+详情弹窗）

### 5.2 数据清洗 🟢
- [x] 清洗任务列表（第一层）
- [x] 新建清洗任务（第二层）
- [x] 格式统一（去除首尾空格、统一大写、统一小写）
- [x] 空值处理（不处理/删除空行/填充指定值）
- [x] 去重（按指定字段，保留第一条）
- [x] 清洗前后对比预览（前20行）
- [x] 执行清洗生成新数据源（非破坏性，原始数据保留）

### 5.3 数据计算 🟢
- [x] 计算任务列表（第一层）
- [x] SQL计算（内存SQLite，标准SQL语法，预览+保存）
- [x] 表关联（LEFT/RIGHT/INNER/OUTER JOIN，可视化配置，预览+保存）
- [x] 计算结果保存为新数据源

### 5.4 运行历史 🟢
- [x] 近7天统计卡片（总次数/成功/失败/平均耗时）
- [x] 状态筛选（全部/成功/失败）
- [x] 日志列表（时间/数据源/通道/状态/行数/耗时）
- [x] 分页（每页20/50/100条）
- [x] 详情弹窗（完整参数+错误信息）

### 5.5 数据分发 🟢
- [x] Excel 分表（按指定列拆分多份）
- [x] 字段选择（横向卡片布局，左上角单选框）
- [x] 字段脱敏（手机号中间4位、身份证保留首尾、地址保留到区县）
- [x] 正则表达式脱敏（按正则定位文本内片段，只动片段、其余文字原样保留）
- [x] 汇总表（分组维度/求和/计数，文本字段默认分组，数值字段才展示汇总方式）
- [x] 子表合并（加"来源"列，来源名称可自定义编辑）
- [x] 配置模板（全局生效）
- [x] 输出文件自动列宽行高
- [x] 明细表自动按文本字段排序
- [x] 脏数据处理（中止并列真实行号）
- [x] 仅汇总不输出明细
- [x] 明细保留源表单元格底色（.xlsx/.xlsm 实心填充；自动排序后不串行）
- [x] 汇总表标签红色（Excel tabColor，明细标签保持默认，发给对方后一眼区分）
- [x] 汇总字段可拖拽调顺序（按住维度卡 / 指标行拖到目标位置，预览与导出列顺序跟随）
- [x] 表头冻结（导出 Excel 明细与汇总首行 freeze_panes="A2"；网页预览表头 sticky 吸顶）

#### 汇总字段排序 + 表头冻结的实现要点
- **顺序落在哪**：前端用 `S.sumOrderDim`（文本维度）与 `S.sumOrderNum`（数值指标）两个数组
  保存用户手调的顺序；`orderList()` 每次渲染把顺序对齐到当前字段集合（新字段追加末尾、
  已删除的剔除），所以换文件 / 改保留字段都不会把顺序带乱。
- **拖拽而不是按钮**：`enableDragSort(container, selector, key)` 用 pointer 事件自己实现拖拽。
  最初试过原生 HTML5 drag，但卡片大部分面积是 select，浏览器从控件上起手会直接取消拖动，
  用户实测就是"拖不动"，所以换掉。现在：`pointerdown` 只排除 `input/select/textarea/button`
  （这些控件上按下要能正常勾选、改类型、输列名），其余区域（左侧把手、字段名、卡片空白）
  都能起手；移动超过 5px 才进入拖拽态并加 `.dragging`，避免点一下就误判。
- **拖动过程只给指示、松手才落位**：第一版是 `pointermove` 里直接 `insertBefore` 让卡片实时
  让位，卡片在鼠标下方来回跳、很难对准，用户反馈"拖动不方便"。现在改为：`pointermove` 只用
  `document.elementFromPoint()` 判断落在哪张卡的上半区 / 下半区，给那张卡加 `.drop-before` /
  `.drop-after`（卡片是左/右边缘高亮，指标行是上/下边缘高亮）作为插入位置提示；`pointerup`
  时才真正 `insertBefore`，再把 DOM 顺序写回 `S[key]` 并 `renderSum()`。没有明确落点时保持原样，
  `pointercancel` 不写顺序，避免误改。
- **监听只绑一次**：容器是常驻元素、`innerHTML` 每次重绘，所以 pointerdown 挂容器、
  pointermove / pointerup 挂 document，并用 `container.__sortBound` 去重，`key` /
  `selector` 存在容器上复用，否则每次重绘都会叠加一层监听、一次拖拽触发多轮重渲染。
- **把手**：卡片 `.fk` 开头、指标行 checkbox 前各放一个六点 SVG（`.grip`，hover 变主色），
  让"这里能拖"一眼看得出来；pointer 方案不依赖 HTML5 drag，触屏设备同样可用。
- **顺序必须传后端**：`sumConf()` 除 groups/sums/counts 外额外产出 `order`（最终列名数组），
  `build_summary()` 末尾 `_apply_order()` 按它重排 DataFrame。只改前端渲染顺序而不传
  `order`，预览会变、导出文件却还是老的——这是最容易漏的一步。
- **合计行跟着走**：「合计」不再固定填 `gcols[0]`，而是落在**重排后最左边的分组列**，
  否则把某个维度拖到第一位后，"合计"会孤零零地待在中间。
- **冻结范围**：`_autofit_ws()` 统一设 `ws.freeze_panes = "A2"`，明细与汇总都生效。
  预览表头用 `#pvThead th{position:sticky;top:0}`；表格是 `border-collapse:collapse`，
  sticky 后 border-bottom 会消失，所以用 `box-shadow:inset 0 -1px 0` 补分隔线。
- **兼容性**：pointer 事件在桌面 Chrome/Edge 与触屏上都有效；不再保留 ↑↓ 按钮，避免两套
  排序入口并存。唯一限制是 select / 输入框上按下不会起拖（要保证控件本身可正常操作），
  所以每张卡都留了把手，从把手或字段名处起手即可。

#### 文件名后缀的智能联想
- 进入第 4 步（或换文件）时，`smartSuffix(源文件名)` 自动填一个可用后缀。规则：去扩展名 →
  去掉 `副本 / copy / 导出…` 尾巴 → 去掉 `(1)(12)` 这类重复标记 → **剥掉文件名里的旧日期**
  （`2026-08-26` / `2026.8.26` / `20260826` / `（0826）` 都识别）→ 末尾统一补**当日**日期
  `（MMDD）`，例如今天是 11 月 16 日就补 `（1116）`。
- **为什么不保留文件名里的日期**：文件往往是上个月的模板（如 `8月企微好友添加进度（0826）`），
  发给别人的是当天这份，日期必须代表本次生成。所以旧日期是"替换"而不是"叠加"，避免出现
  `（0826）（1116）` 这种双日期。
- `S.suffixAuto` 区分"自动联想"和"用户手填"：手填过的值换文件、跨天进第 4 步都不会被动；
  仍是自动值时，每次进第 4 步按当天重算，日期不会停在昨天。第 4 步提供「重新联想」「留空」。
- 输出文件名是 `拆分值 + 后缀 + .xlsx` **直接拼接**，不自动插分隔符；想要 `丽水-11月…` 就在
  后缀里自己写 `-`，界面提示文案已写明这一点。

#### 单元格底色保留的实现要点
- **读取**：`services/excel_style.py` 直接解 OOXML（`styles.xml` 取色 + `iterparse` 流式扫
  `sheetN.xml` 取坐标），不退回 openpyxl 常规模式，避免 5 万行大表整表驻留内存。
  取色支持 `rgb` 与 `theme`（含 tint）；忽略 alpha 通道——openpyxl 会把 6 位色补成
  `00xxxxxx`，按规范当透明会误杀大量正常底色。
- **映射**：`{(子表, Excel行号): {源表列序号: 色值}}`，行号与 `_clean()` 写入的 `__row__` 对齐，
  稀疏存储，只记有颜色的单元格。
- **回写**：`apply_fills()` 在 `to_excel` 之后按**行锚点 + 列位换算**着色。因此
  "只保留部分字段"（列顺序/子集变化）和"明细自动排序"（行序变化）都不会让颜色跟错行。
- **降级**：csv / .xls / 条件格式 / 渐变填充不还原，静默跳过，不阻断拆分主流程。

#### 正则表达式脱敏的实现要点
- **解决的问题**：手机号常常和客户姓名挤在同一格（"张三 13812345678"）。原有的
  `phone` 规则作用于整格，会连同姓名一起处理；正则规则只替换**匹配到的片段**，
  未命中的文字（姓名、备注等）逐字保留。
- **默认匹配式**：`(?<!\d)1[3-9]\d{9}(?!\d)`——11 位手机号，且前后不能紧贴数字。
  这个 lookaround 很关键：裸写 `1[3-9]\d{9}` 会从 18 位身份证
  `330782199001011234` 中间截出一段当手机号打星。
- **处理方式**：`a`/`b` 控制命中片段保留前 a 后 b 个字符（默认 3/4 → 中间 4 位打星）。
  一格里多个号会全部处理；不命中的单元格原样不动。
- **自定义**：`pattern` 可改成任意正则，脱敏逻辑一致（只对命中片段生效）。
- **校验**：路由在脱敏前先 `compile_pattern`，正则非法直接 400 并指出是哪个字段，
  不会"静默没脱敏"或退化成整列替换。
- **apply_mask 分支**：`regex` 必须在 `apply_mask` 里显式分支，否则会被未知类型的
  兜底逻辑吃掉（整列变成 `***`）。
- **模板**：`mask[列]` 的 `pattern/a/b` 随配置模板一起存取，套用模板时一并回填。

### 5.6 导航结构 🟢
- [x] 左侧分组导航（数据链路/运维）
- [x] 数据分发可展开6子步骤
- [x] 数据清洗/数据计算/运行历史 加「即将上线」占位

### 5.7 全局 UI 布局与交互 🟢
- [x] 模块页头标题与操作按钮同行（`.page-head`）
- [x] 汇总设置窄屏单列回退（`.sum-grid`，视口 ≤1280px）
- [x] 运行历史表格列宽可收缩，表头不再竖排
- [x] 清洗 / 计算 / 运行历史 接口失败时显示可见错误态与「重试」
- [x] 清洗 / 计算 配置区与预览区窄屏上下排列（视口 ≤1180px）
- [x] 浏览器标签页图标（内联 SVG，消除 `/favicon.ico` 404）

#### 布局实现要点（改动前必看）
- **面板动画不能依赖 opacity**：`.panel.show` 的 `@keyframes fade` 只做 `translateY` 位移。
  历史缺陷：`from{opacity:0}` 在浏览器节流动画时会让整个面板停在透明状态，
  表现为"点了菜单，页面一片空白但 DOM 里明明有内容"。
- **选择器要限定作用域**：`renderFields()` 必须用 `#fieldGrid .fcard`。步骤 3 的汇总卡
  也带 `.fcard`，但复选框是 `.gchk`；全局选择器会让 `.keep` 取到 null 并抛错，
  导致步骤 2 渲染中断（从步骤 3 退回步骤 2 必现）。
- **模块 init 用字符串惰性解析**：`sources.js` 先于 `clean.js/calc.js/logs.js` 加载，
  在加载期写 `typeof CL_init === "function"` 恒为 false。必须在 `goModule()` 里用
  `window[cfg.initName]` 现取，否则三个模块进入后列表永不渲染。
- **窄屏断点依据内容区宽度**：内容区 = 视口 − 侧边栏 250 − 左右内边距 80。
  两栏布局（380 + 剩余）在视口 < 1180 时右栏会小于 400px，必须退化单列。
- **接口失败要有可见出口**：`/api/*` 依赖 MySQL，数据库未启动时返回 500 且无响应体。
  列表模块统一 `renderLoadError()`，不要只留一块空白。
- **模板改动需要重启服务**：Flask 非 debug 模式下 Jinja 缓存模板，改 `templates/*.html`
  后必须重启 `app.py` 才生效；`static/*` 刷新页面即可。

### 5.8 全表脱敏 🟢

独立功能页（左侧导航「数据链路 → 全表脱敏」），不进入 6 步分发流程：
上传一个多子表工作簿 → 自动识别每个子表里的敏感列 → 一键脱敏 → 输出「一个文件多 sheet」，
无敏感信息的子表不输出，全程不需要逐列配置。

- [x] 敏感类型：手机号 / 身份证 / 银行卡 / 邮箱 / 详细地址（姓名有意不脱敏）
- [x] 列名 + 内容双重判断（列名命中即处理；列名不明显时内容命中率 ≥ 80% 才处理）
- [x] 只替换敏感片段，同格其他文字保留（「张三13812345678」→「张三138****5678」）
- [x] 格式完全保留（列宽、行高、底色、字体、冻结窗格、合并单元格）
- [x] 每次手动选输出文件夹，文件名 `{原文件名}_已脱敏.xlsx`，重名追加 `_2`
- [x] 页面汇总：输出几个子表、每个子表哪些列脱了多少格、跳过了几个子表

#### 实现要点（改动前必看）
- **必须用 openpyxl 常规模式（`read_only=False`）**。`read_only` 的 `ReadOnlyCell` 拿不到
  fill、无法就地写回；而 `services/excel_style.py` 那套「解 OOXML 包补底色」只在
  pandas `to_excel` 之后需要，全表脱敏是不换引擎的原地改值，样式天然保留，不要绕路。
- **预扫描用 read_only 流式读**（`scan_workbook`），只读前 300 行做内容判定，5 万行大表也能秒回；
  执行阶段再 `load_workbook` 常规模式。两阶段共用 `services/detect.py`，保证"预览看到的"
  就是"执行改的"。
- **身份证 / 银行卡的严格校验只在"内容判定"时启用**：`mask_text(..., strict=True)` 要求
  身份证校验位、银行卡 Luhn 通过，避免把 18 位流水号、16 位订单号当敏感号打掉；
  列名命中的列走 `strict=False`，假号、测试数据也照样打码。
- **姓名列不进脱敏清单**：`detect_sheet()` 主动过滤 `kind=name`。业务要求名单能认出人，
  「姓名+手机号」同格时靠手机号的正则片段替换，只动号码。
- **打码后统一写文本格式**（`cell.number_format = "@"`）：含 `*` 的值本身是文本，
  但原列若是数值格式，Excel 会把长数字显示成科学计数法。
- **阈值 0.8 而非 0.5**：自由文本列（备注、说明）偶尔出现一个号码很正常，
  半数命中就整列打星会误伤正常内容。
- **.xls 直接拒绝**并提示另存 xlsx：老格式无法做格式级改写。
- **前端 init 走 `DES_init`**，在 `static/sources.js` 的 `MODULES` 里声明
  `initName: "DES_init"`，由 `goModule()` 惰性解析（与其他模块同一套机制）。

---

## 六、开发路线图（下一步计划）

### 阶段一：数据源管理中心完善（当前）
1. **数据库连接通道**：等待用户提供接口后接入
2. **敏感配置加密**：数据库连接配置加密存储
3. **运行历史详情页**：采集日志列表 + 详情查看
4. **已知问题修复**：改分类按钮点击无反应（待确认是否已解决）

### 阶段二：数据清洗模块
1. 第一层：清洗任务汇总（哪些表完成了清洗、清洗规则是什么）
2. 第二层：数据源 + 清洗规则配置
3. 清洗规则：去重、空值处理、格式统一、异常值过滤
4. 清洗结果预览 + 对比

### 阶段三：数据处理/计算模块
1. SQL 计算（用户写 SQL，基于已有的数据源查询生成新表）
2. 表格关联（LEFT JOIN / INNER JOIN，生成新字段）
3. 模型计算（占位，后续接入）
4. 计算结果分类管理

### 阶段四：智能体接入
1. AI 助手，理解项目背景和功能
2. 自然语言操作（"帮我把会员表按市场拆分"）
3. 数据分析（"分析本月各市场订单趋势"）
4. 等待用户提供接口

---

## 七、已知问题

### 7.1 改分类按钮点击无反应
- **现象**：数据源卡片上的「改分类」按钮点击后无响应
- **状态**：已改为下拉框弹窗，待用户确认是否解决
- **优先级**：中

### 7.2 大文件加载性能
- **现象**：5万行 Excel 采集已优化到0.66秒，但前端预览大量数据可能卡顿
- **状态**：采集端已优化，预览端限制行数
- **优先级**：低

### 7.3 数据源中心分类相关（待集中修）
- **现象 1**：数据源卡片的「改分类」按钮偶发点击无反应
- **现象 2**：「分类外面看一个，点进去看还是两个」——分类卡片计数与分类内列表数量不一致
- **现象 3**：把文件改分类到「会员信息」后，又自己跑回「未分类」
- **已定位根因（现象 2）**：`static/sources.js` 的 `renderCategories()` 用 `SRC.sources`
  统计分类卡片的 `total / ready / pending / error`，而 `SRC.sources` 只装**当前页**
  （默认 20 条）。所以卡片上的数字本质是"这一页里各分类各有几条"，不是全量。
  实测：全库 152 个数据源、未分类 151 个，卡片却显示「20 个」。
- **修复建议**：后端 `/api/categories` 补 `uncategorized_count`（或返回按状态分组的
  `stats`），前端分类卡直接读接口值，不要再从当前页数据累加。现象 1 / 3 需要同时
  检查 `SRC_confirmChangeCategory` 的异常分支与 `SRC.loadSources` 的刷新时序。
- **状态**：用户已确认先记录、后续集中修复，本轮未动
- **优先级**：中

### 7.4 本地 MySQL 未启动时的表现
- **现象**：数据源 / 清洗 / 计算 / 运行历史 的列表接口返回 500 且无响应体
- **状态**：前端已补可见错误态与「重试」；根因仍是测试实例未启动
  （启动方式见 9.1），不属于代码缺陷
- **优先级**：低

---

## 八、开发规范

1. **每次改动必须 git commit**，message 说明本次改了什么
2. **每次改动必须编写/更新测试**，交付前确保所有测试通过
3. **时间处理**：DAO 层统一将 datetime 转为本地时间字符串，避免时区偏差
4. **大文件处理**：使用 openpyxl read_only 流式解析，避免内存溢出
5. **前端 JS**：修改后必须用 `node --check` 验证语法
6. **API 设计**：统一返回 `{ok: bool, msg?: str, data?: any}` 格式
7. **pytest 类级初始化**：普通测试类只认 `setup_class` / `teardown_class`；
   写成 `setUpClass` 不会执行，类属性会一直是 `None`（表现为"前置数据不存在"整段 skip）。
   另外 pytest 每个用例新建实例，跨用例的状态必须挂类属性，且测试数据要唯一命名 + 兜底清理。
8. **DAO 返回类型**：`DictCursor.fetchall()` 返回 tuple，对外暴露的 DAO 方法统一转 list。
9. 详见 AGENTS.md

---

## 九、启动方式

### 9.1 启动 MySQL（测试实例）
测试实例已注册为 Windows 服务 **`MySQLTest3307`**（端口 3307、`datadir=D:/mysql/test-instance/data`、
配置文件 `D:/mysql/test-instance/my.ini`），随系统自动启动。

```powershell
Get-Service -Name MySQLTest3307        # 查看状态
Start-Service -Name MySQLTest3307      # 启动
Restart-Service -Name MySQLTest3307    # 重启
```

**两个坑（都踩过）**：
- `my.ini` 里的路径必须写正斜杠或双反斜杠。MySQL 选项文件会把 `\t`、`\n` 当转义，
  写成 `D:\mysql\test-instance\data` 会被解析成 `D:\mysql<TAB>est-instance\data`，
  服务启动时报 `Failed to set datadir ... Invalid argument`。
- 不要再用 `Start-Process mysqld ...` 临时起实例：进程会随命令所在的会话结束被回收，
  跑一阵子就悄悄挂掉（日志里连 shutdown 记录都没有），表现是测试突然全部 skip、
  页面显示"列表读取失败"。要长期可用就走服务。

### 9.2 启动工作台
```bash
cd D:\ProjectDevelopment\excel-splitter
python app.py
```
或双击 `启动工作台.bat`

### 9.3 运行测试
```bash
python tests/test_dao.py
python tests/test_api.py
python tests/test_e2e.py
```
