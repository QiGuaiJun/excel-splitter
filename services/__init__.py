# -*- coding: utf-8 -*-
"""服务层包。

业务背景：批次 6 引入 services/ 子包，集中放业务级工具。
原代码散布在各 api/*.py：
- _load_dataframe() 在 api/clean.py 和 api/calc.py 完全重复
- JSON config 防御性解析在 api/clean.py / api/calc.py 重复 4 次
- 脱敏引擎在 api/distribute.py（约 90 行可独立测试的纯函数）
- 汇总构建 build_summary() 在 api/distribute.py

按"按职责分层"原则：api/* 是路由层、services/* 是业务逻辑层。
本次只抽 3 个最值得抽的，其余留待后续批次。
"""