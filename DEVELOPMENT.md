# 智能化数据分析工作台 - 开发文档

> 最后更新：2026-11-11

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
- [x] 汇总表（分组维度/求和/计数，文本字段默认分组，数值字段才展示汇总方式）
- [x] 子表合并（加"来源"列，来源名称可自定义编辑）
- [x] 配置模板（全局生效）
- [x] 输出文件自动列宽行高
- [x] 明细表自动按文本字段排序
- [x] 脏数据处理（中止并列真实行号）
- [x] 仅汇总不输出明细
- [x] 明细保留源表单元格底色（.xlsx/.xlsm 实心填充；自动排序后不串行）

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

### 5.6 导航结构 🟢
- [x] 左侧分组导航（数据链路/运维）
- [x] 数据分发可展开6子步骤
- [x] 数据清洗/数据计算/运行历史 加「即将上线」占位

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

---

## 八、开发规范

1. **每次改动必须 git commit**，message 说明本次改了什么
2. **每次改动必须编写/更新测试**，交付前确保所有测试通过
3. **时间处理**：DAO 层统一将 datetime 转为本地时间字符串，避免时区偏差
4. **大文件处理**：使用 openpyxl read_only 流式解析，避免内存溢出
5. **前端 JS**：修改后必须用 `node --check` 验证语法
6. **API 设计**：统一返回 `{ok: bool, msg?: str, data?: any}` 格式
7. 详见 AGENTS.md

---

## 九、启动方式

### 9.1 启动 MySQL（测试实例）
```bash
"D:\mysql\mysql\mysql-8.0.44-winx64\bin\mysqld.exe" --datadir="D:\mysql\test-instance\data" --port=3307 --bind-address=127.0.0.1
```

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
