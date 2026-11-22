# Step 2 报告

网页的数据入口已经从旧 Excel 子集改到 `data/curriculum.sqlite`。课程、开课记录、先修关系和专业完成度都经过只读服务层。`curriculum.sqlite` 没有被写入。

## 实现范围

- `app/database.py`：项目根目录下的数据库路径，可用参数换测试库。连接使用 `file:...?mode=ro`，并执行 `PRAGMA query_only = ON` 和 `PRAGMA foreign_keys = ON`。缺文件、文件损坏、缺表都会返回明确错误，缺表时带上表名。
- `app/course_repository.py`：课程搜索、别名解析、课程详情、已记录课节。缺失字段保持空值，不写成空字符串。
- `app/graph_service.py`：从 824 个规范课程节点和 `graph_edges` 建 `networkx.MultiDiGraph`。先修方向是先修课指向目标课。
- `app/prerequisite_service.py`：按组求值先修、先修或共修、非严格提示和反向限制。递归树单独展开，不把一条图路径当成修课计划。
- `app/major_service.py`：专业列表和完成度。求值调用 `data/major_rule_engine.py`。
- `app/models.py`：课程、课节、先修、规则结果的数据结构。
- `demo.py`：课程选择、详情、已记录课节、先修面板和专业完成度都调用上述服务。页面不写 SQL。全校网络图不绘制。最短结构路径旁固定写着“这是图上的一条结构路径，不是修课计划。”
- 缓存键是数据库文件的修改时间和大小。服务不缓存某个学生的求值结果，也不把连接交给页面长期持有。

规范课程节点是 `course_aliases.alias_code = course_id` 的 824 门。`courses` 表另有 825 行；多出的 `MEDIART405/GCULS405` 是重复条目，别名指向 `HUM405/MEDIART405`。

当前 532 条边里，没有两条边共用同一对端点。因此普通有向图今天不会盖掉另一条关系。服务仍使用多重有向图，避免以后出现平行关系时被静默覆盖。先修子图只沿 `prerequisite` 和 `prerequisite_or_corequisite` 向上走，反向限制留在全图里，不画成先修。

组间关系按组号从左到右合并。`STATS303` 因而读成（`COMPSCI309/STATS302` 或 MATH 405 且 COMPSCI 201）再加 STATS 211、MATH 304、MATH 305。`strict = 0` 只作为提示，结果不会是 unsatisfied。教师同意、年级、分班和 “or equivalent” 从手册原文标成人工确认，不替学生做决定。

## 测试

`python3 -m pytest tests -q`：42 项通过，用时 0.93 秒。

其中包括：

- 只读连接可以查询，写入语句和 `PRAGMA query_only` 都会拒绝修改。
- 缺文件、损坏文件、缺表都有明确错误。
- 824 个规范课程都能取到详情。全部别名和全部开课代码都能解析到对应规范课程。
- `MATH206` 的代码、空格、小写、课名搜索，以及 `STATS302` 只返回一次 `COMPSCI309/STATS302`。
- `ARHU101` 的课节覆盖 2258、2261、2268、2271 这四个已记录学期。
- 图有 824 个节点、532 条边，端点都在，孤立节点还在，严格边 495 条、非严格边 37 条。`MATH206` 的一层先修子图只有 MATH 101 和 MATH 105，不含反向限制 MATH 205。
- 单一先修、AND、OR、`STATS303` 的组间 OR、先修或共修、strict 0、反向限制、未知课程、递归分支和循环停止。
- 39 个专业都能加载。空已修列表不会显示为完成。ALL、CHOOSE、ANY、QUOTA 有满足和未满足案例。ADVISORY 不计入完成度。All Majors 的 blocked 规则只返回 blocked。交叉列课 `ARTS210/HIST210` 只计一次。
- `data/major_rule_tests.json` 的 670 条案例与规则引擎结果一致。
- 服务模块不导入 Streamlit。`demo.py` 不再读取 `curriculum_subset_math_cs_ds.xlsx`。

测试结束后，`major_rules` 仍是 259 条，`class_sections` 仍是 4424 行，`major_rules_history` 仍是 6 条。没有新增写入记录。

## 页面核对

浏览器工具这次没有连上，所以没有在浏览器里逐项点击。替代核对用的是 Streamlit 自带的 `AppTest`：

- 页面可以跑完，没有异常。
- 搜索 `stats 302` 后页面出现规范课号 `COMPSCI309/STATS302`。
- 专业切到 All Majors 后出现“无法自动判断”和“不是学校官方学位审核结果”。
- 从 MATH 101 到 MATH 206 的结构路径能生成，并带有“不是修课计划”。
- 页面默认说明全校节点不一次画出。

这个 Streamlit 版本的 `AppTest` 不记录 `st.pyplot` 图像，所以局部图有没有画出来，没有在屏幕上确认。启动页面的命令是：

```bash
python3 -m streamlit run demo.py
```

## 限制

- 完成度不是学校官方学位审核。blocked 规则只说明无法自动判断。
- 已记录课节只说明这门课在 2025 Fall、2026 Spring、2026 Fall、2027 Spring 出现过，不预测以后的学期。
- 人工确认来自手册里的许可、年级、分班和 equivalent 字样。它不生成教师批复。
- 最短路径只是先修边上的一条最短结构路径。页面使用 `shortest_path`，不枚举全部简单路径，避免全图搜索卡住。
- 本阶段没有重做视觉界面，也没有加入职业、校友、推荐或学期排课。

## 下一阶段

Step 3 可以在这些服务上重做信息架构和视觉界面。页面继续只调用服务，不把 SQL 或规则求值写回组件。学生输入的求值结果如果要缓存，缓存键必须包含已修课程、并修课程和数据库文件版本。
