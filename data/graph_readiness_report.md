# 建图前数据质量报告

审计对象是 `data/curriculum.sqlite`。开课记录仍只表示 2025 Fall、2026 Spring、2026 Fall、2027 Spring 里实际出现过的课节。没有填写 Fall/Spring/Both，也没有把某一次开课写成以后每次都会开。

## 164 个开课代码

精确比对时，课表里有 164 个 `course_code` 不等于课程表的 `course_id`。处理结果：交叉列课号 60、重复印刷的交叉列课 1、独立于 MATH101 的半门课 2、从手册正文恢复 2、仅课表有记录 99。

- 交叉列课号对到手册里唯一的 `A/B` 课号。例如课表里的 `COMPSCI309` 和 `STATS302` 都指向 `COMPSCI309/STATS302`。
- `MEDIART405` 同时出现在两行完全相同的手册记录里。图上只保留 `HUM405/MEDIART405`，`GCULS405` 和 `MEDIART405/GCULS405` 也指向它。
- `MATH101A` 和 `MATH101B` 不并进 `MATH101`。课表里它们分别是 2 学分的微分和积分，手册里的 `MATH101` 是 4 学分的 Introductory Calculus。
- `MUSIC210` 和 `MUSIC211` 从被串进上一门课的手册正文里恢复。
- 其余代码在 2025-26 手册课程表里没有条目。它们按课表标题和学分建成课程节点，先修留空。

现在每个开课代码都能通过 `course_aliases` 找到课程节点，并写进 `class_sections.canonical_course_id`。非自身别名 {'duplicate_entry': 1, 'slash_part': 124}。

## 11 条源课程不存在的关系

这 11 条原来的来源是 `CHEM101`、`MATH205`、`ARHU200`、`GCHINA306`、`MUSIC210`、`POLSCI398-2`、`PSYCH304`、`EAP14`。

- `CHEM101` 保留为 `BIOL411/GLHLTH411` 的先修。手册没有 CHEM 101 的课程条目，所以节点没有课名。
- `MATH205` 保留两条：`MATH206` 的反向限制，以及 `MATH306` 先修里 “MATH 203 or MATH 205” 的一个选项。手册没有 MATH 205 的课程条目。
- `ARHU200` 的两条边删除。它不是课。
- `GCHINA306`、`MUSIC210`、`POLSCI398-2`、`PSYCH304` 都是被串进上一门课的真实课程。指向上一门课的边删除，课程本身按手册补回。
- `PSYCH304` 的手册先修是 PSYCH 101，以及 STATS 101 或 MATH 206。这三条边已经写入。
- `POLSCI398-2` 的手册先修是 GCHINA 108 或 POLSCI 101 或任课教师同意。同意不是节点，所以这条边不是硬性先修。
- `MUSIC210` 的先修是任课教师同意，没有边。
- `EAP14` 的两条边删除，不建课。

另外在逻辑核对里排除了 4 条原句不是先修的边：`GLHLTH312` 的推荐和串入课程，`PHYS306` 的 encouraged，`SOSC320` 的 highly encouraged。先修字段已改回手册原句的课程是 GCHINA305、PSYCH205、POLSCI398-1、MUSIC20、WOC290、GLHLTH312、WOC206。改前文字在 `course_text_repairs`。

排除的关系：

- 关系 283：bleed。GCHINA 306 是下一门课的标题，不是 GCHINA 305 的先修。手册先修只有 GCHINA 108。
- 关系 297：nonbinding。GLHLTH 312 的原文是 “GLHLTH 101 recommended”，后面接的是下一门课 GLHLTH 408 的简介。
- 关系 298：bleed。BIOL 408/CHEM 408/GLHLTH 408 是串进来的下一门课，不是 GLHLTH 312 的先修。
- 关系 320：false_code。“200-level”被读成课号 ARHU200。手册原文是 ARHU 101，或任意 4 学分的 100/200 级 LIT 课。
- 关系 322：false_code。“200-level”被读成课号 ARHU200。手册原文是 ARHU 101，或任意 4 学分的 100/200 级 LIT 课。
- 关系 410：bleed。MUSIC 210 Orchestra 是下一门课，不是 MUSIC 20 的先修。MUSIC 20 的先修是任课教师同意。
- 关系 441：nonbinding。PHYS 306 对 PHYS 301 的原文是 “is encouraged”，不是先修。PHYS 201 和 MATH 202 仍保留。
- 关系 462：bleed。POLSCI 398-2 是下一门课，不是 POLSCI 398-1 的先修。398-1 的先修是 POLSCI 223 或任课教师同意。
- 关系 467：bleed。PSYCH 304 是下一门课，不是 PSYCH 205 的先修。PSYCH 205 的先修是 PSYCH 101。
- 关系 492：nonbinding。SOSC 320 对 MATH 206 的原文是 “highly encouraged”。STATS 101 和 SOSC 205 仍保留。
- 关系 538：false_code。“EAP 14-week”是校历里的 14 周课，不是课号 EAP14。
- 关系 539：false_code。“EAP 14-week”是校历里的 14 周课，不是课号 EAP14。同一句被写入了两次。

## 逻辑编码

图使用的边共 532 条，其中硬性边 495 条。按类型：{'antirequisite': 20, 'prerequisite': 508, 'prerequisite_or_corequisite': 4}。按完整性：{'level_constraint': 3, 'listed_option': 34, 'ok': 495}。

核对结果：

- AND：多个课号各自成组，组间 `group_relation = and`，组内 `single`。`COMPSCI309/STATS302` 的 MATH 201、MATH 202、MATH 206、COMPSCI 201 是这种编码。
- OR：同一组里 `logic_within_group = or`。`MATH206` 的 “MATH 101 or MATH 105” 是这种编码。
- 组间 OR 加组内 AND：`STATS303` 是（`COMPSCI309/STATS302`）或（MATH 405 且 COMPSCI 201），再加先修或共修 STATS 211，再加 MATH 304 和 MATH 305。
- 先修或共修共 4 条：`COMPSCI203` 的 COMPSCI 201 或 MATH 202，`COMPSCI306` 的 COMPSCI 205，`STATS303` 的 STATS 211。没有单独的 corequisite 类型。
- 反向限制共 20 条，按手册原文的方向保存。互为反向的有 MATH101 与 MATH105、MATH302 与 MATH304、STATS210 与 STATS211、ECON201 与 PUBPOL205、COMPSCI309/STATS302 与 MATH405。CHEM105 只写出不能与 CHEM110 同时算，CHEM110 自己没有反向限制句，所以没有补反向边。COMPSCI101 的 “COMPSCI 201 and STATS 102” 编成两条都要排除的反向限制。

`issue = ok` 且 `strict = 1` 的边可以进入硬性先修判断。`listed_option` 和 `level_constraint` 只说明手册列出了这条路，不能判断学生没选这门课就一定不能上目标课。

## 1,224 条专业要求

全部 1,224 行都进入了迁移前的 `major_rule_courses_legacy`。当时规则共 249 条，状态计数：{'executable': 225, 'executable_flagged': 3, 'partial_count': 11, 'partial_unresolved': 10}。课号对应方式：{'crosslist_superset': 1, 'exact': 1111, 'slash_order': 7, 'slash_part': 86, 'typo': 3, 'unresolved': 16}。交叉列课只是左右顺序不同时，对应到手册里的同一门课，不另建节点。这些 executable 状态已经不在当前的 `major_rules` 里。当前表使用 verified 和 blocked。

规则读法：

- `all`：这一组里的课都要完成。
- `choose`：`choose_k` 是要选的门数，`expected_n` 是原句写出的候选门数。候选门数对不上时，迁移前的状态是 `partial_count`。
- `optional`：选修池。手册这一角色没有最少门数。
- `alternative`：签名作业的 option 1 与 option 2，完成其中一组。

可执行但做了对应说明的规则：

- Computation and Design-Digital Media / elective：CULANTH202/MEDIA202 写少了交叉列课号，对应到 CULANTH202/GCULS201/MEDIA202。这一组是选修池，手册没有在角色里写出最少门数。
- Computation and Design-Social Policy / required：EHTLDR204 按课号笔误对应到 ETHLDR204
- Humanities-World History / required：HIS212 按课号笔误对应到 HIST212

迁移前标成 partial_count 或 partial_unresolved 的要求，已经按印刷页课表写进现行规则。被替代的艺术、媒体方向旧规则在 `major_rules_history`。

按专业要求表补上课程节点的课号：CULANTH304、LIT298-1、LIT298-2、MEDIART498、RELIG398。

CULANTH209、DIA202、DIA207、ECON311、ETHILDR202、RELIG301、SOCIOL298 仍没有课程节点，也没有挂在现行完成度规则上。

`ENVIR302` 和 `ECON302` 课名、简介、学分都相同，但先修不同，所以没有并成一门。专业要求里的 `ENVIR302/ECON302` 因此仍不能落到一个节点。

图节点里仍有同名且简介相同的课，这次没有合并：

- ECON302 与 ENVIR302：Environmental Economics & Policy

## 建图就绪清单

图节点是 `course_aliases` 里 `alias_code = course_id` 的课，共 824 个。其中 5 个只出现在专业要求表里，课程描述部分没有单独条目。边表是 `graph_edges`。专业规则表是 `major_rules`。某门课在已记录学期里的开课，用 `class_sections.canonical_course_id` 查询。

检查：

- cited_sources_present：pass。仍缺课程节点：无。ARHU200 和 EAP14 不是课程，没有建节点。
- graph_edge_endpoints：pass。端点不在图节点里的边：0
- logic_groups：pass。组内逻辑不一致的组：0
- major_rows_attached：pass。专业要求 1224 行，规则课程 1224 行
- offering_codes_resolve：pass。未解析开课代码 0
- offering_pattern_not_inferred：pass。填写了 offering_pattern 的课程：0

可以开始做的事：

- 用硬性先修边建立有向图。边的方向是先修课指向需要它的课，并带上 `group_id`、`logic_within_group`、`group_relation`。
- 先修判断按组计算：组内 AND 要全部完成，组内 OR 完成一门即可；组间再按 `group_relation` 合并。
- 查询一门课在四次已记录学期中出现过的课节。交叉列课用规范课号，不把出现过一次写成固定开课季节。
- 专业完成度只查询 `status = 'verified' AND operator != 'ADVISORY' AND counts_toward_completion = 1`。39 个专业都有计入完成度的规则。

还不能当作正确结果的事：

- `blocked` 规则不能用来判断毕业要求是否完成。`ADVISORY` 是推荐选修，不计入完成度。
- `strict = 0` 的边不能单独决定一门课有没有解锁。
- 全校节点一次性画在一张图上不可读。图的查看范围应是一门课的先修邻域，或一个专业的规则范围。
- 最短路径不能当作一份可以上课的计划。
- 不要运行 `data/build_curriculum_db.py`。它现在会拒绝覆盖这份已经载入开课记录的数据库。

## 专业规则网页开放条件

- 计入完成度的 verified 规则：227 条，覆盖 39 个专业。查询条件是 `status = 'verified' AND operator != 'ADVISORY' AND counts_toward_completion = 1`。
- 推荐选修 ADVISORY：31 条，不计入完成度。
- blocked：1 条。现行表保留旧规则 18，签名作品的另一种学分拆法，印刷页 92。
- partial：0 条。现行 259 条规则都有印刷页码。
- 被替代的旧规则 19, 21, 23, 27, 28, 31 在 `major_rules_history`，共 6 条。艺术方向的替代规则在印刷页 102，媒体方向在印刷页 107。
- 只读测试 670 条，失败 0 条。
