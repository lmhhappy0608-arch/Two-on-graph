# Step 2 网页只读数据访问层

## 1 任务目标

把现有网页从旧版 Excel 子集迁移到 `data/curriculum.sqlite`，建立独立、只读、可测试的数据访问层和业务服务层。

完成本任务后，网页应能通过稳定接口访问课程、开课记录、先修关系、专业规则和专业完成度。SQL、NetworkX、专业规则求值与 Streamlit 页面展示必须分离。

本任务重点是数据访问和业务逻辑，不包括完整界面重设计、职业数据、校友数据、推荐模型或完整学期排课优化。

## 2 当前问题

现有 `demo.py` 仍读取已经不存在的 `curriculum_subset_math_cs_ds.xlsx`：

```python
file_path = script_dir / "curriculum_subset_math_cs_ds.xlsx"
```

现有页面还存在以下结构问题：

- 课程、关系和专业要求从旧 Excel DataFrame 读取。
- SQL、图模型、规则求值和页面组件没有分层。
- 专业要求仍使用旧列表逻辑，而不是已验收的 `major_rules` 规则树。
- 最短路径展示容易被误解为可执行修课计划。
- 页面代码难以在不启动 Streamlit 的情况下测试。

## 3 总体设计

建议代码结构：

```text
Dii/
├── app/
│   ├── __init__.py
│   ├── database.py
│   ├── course_repository.py
│   ├── graph_service.py
│   ├── prerequisite_service.py
│   └── major_service.py
├── data/
│   ├── curriculum.sqlite
│   └── major_rule_engine.py
├── tests/
│   ├── test_database.py
│   ├── test_course_repository.py
│   ├── test_graph_service.py
│   ├── test_prerequisite_service.py
│   └── test_major_service.py
└── demo.py
```

如果使用不同文件名，仍应保持相同职责边界。

依赖方向：

```text
Streamlit 页面
    ↓
业务服务层
    ↓
只读 Repository
    ↓
curriculum.sqlite
```

页面不能直接拼接 SQL，也不能自行重新实现专业规则求值。

## 4 数据库连接层

### 4.1 只读连接

`app/database.py` 应提供统一连接入口，并使用 SQLite URI 只读模式：

```python
sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
```

连接后启用：

```sql
PRAGMA query_only = ON;
PRAGMA foreign_keys = ON;
```

要求：

- 数据库路径相对项目根目录解析，不能写死用户目录。
- 支持测试时传入临时或指定数据库路径。
- 查询返回结构化字段，而不是依赖列位置的裸元组。
- 所有连接和 cursor 及时关闭。
- 任何服务均不得执行 INSERT、UPDATE、DELETE、DROP、ALTER 或 CREATE。
- 数据库缺失、损坏或 schema 不兼容时返回明确错误。

### 4.2 Schema 检查

启动时至少确认以下表存在：

- `courses`
- `course_aliases`
- `class_sections`
- `graph_edges`
- `major_rules`
- `major_rule_items`
- `major_rule_constraints`

若缺少表，停止加载并指出具体表名。

## 5 课程 Repository

`app/course_repository.py` 负责课程、别名和开课记录查询，不包含页面代码。

### 5.1 课程搜索

建议接口：

```python
search_courses(query: str, limit: int = 20) -> list[CourseSummary]
```

搜索字段：

- 规范课程代码 `courses.course_id`
- 别名 `course_aliases.alias_code`
- 课程名称 `courses.course_name`

要求：

- 大小写不敏感。
- 忽略课程代码中的普通空格。
- 优先级为精确课程代码、精确别名、代码前缀、名称匹配。
- 每门规范课程只返回一次。
- 返回匹配到的别名，方便解释搜索结果。
- 限制最大返回数量，防止空查询加载全部详细数据。

### 5.2 课程代码规范化

建议接口：

```python
resolve_course_code(code: str) -> str | None
```

要求：

- 接受规范代码和合法别名。
- 交叉列课的任一合法代码解析到同一规范节点。
- 未知代码返回 `None` 或明确的 not-found 结果。
- 不使用模糊匹配偷偷替换未知代码。

### 5.3 课程详情

建议接口：

```python
get_course(course_id_or_alias: str) -> CourseDetail | None
```

返回：

- 规范课程代码
- 所有别名
- 课程名称
- 院系
- 层级
- 学分
- 描述
- 先修原文
- 反向限制原文
- 来源
- 数据缺失说明

不得将缺失字段伪造为空字符串后当作真实值。

### 5.4 已记录开课情况

建议接口：

```python
get_recorded_sections(course_id_or_alias: str) -> list[SectionRecord]
```

返回：

- 学期代码和学期名称
- 班号
- section
- component
- session
- 状态
- 开始和结束日期
- 学分

必须使用 `class_sections.canonical_course_id` 查询。

页面和接口只能表达“该课程在这些已记录学期出现过”，不得推断固定的 Fall、Spring 或 Both 开课模式。

## 6 图服务

`app/graph_service.py` 负责从数据库创建 NetworkX 图。

### 6.1 建图规则

建议接口：

```python
build_curriculum_graph() -> nx.DiGraph
```

要求：

- 先从课程节点表加入全部课程，确保孤立节点不会丢失。
- 边方向为先修课程指向目标课程。
- 只把适合图结构的关系加入图。
- 边属性保留：
  - `relation_type`
  - `group_id`
  - `logic_within_group`
  - `group_relation`
  - `strict`
  - `issue`
  - `raw_clause`
- 节点属性至少包括课程名称、院系、层级和学分。
- 不能因为重复 `add_edge` 静默覆盖语义不同的平行关系。

如果同一对节点可能存在多种不同关系，应选择 `MultiDiGraph`，或者在导入前证明当前数据中不会发生语义冲突。

### 6.2 图完整性

加载时检查：

- 所有边端点存在。
- 课程节点数量与规范课程节点数量一致。
- 不意外丢失孤立节点。
- 严格边和非严格边数量与数据库一致。
- 图类型和方向明确。

### 6.3 局部子图

建议接口：

```python
get_prerequisite_subgraph(course_id: str, max_depth: int | None = None)
```

要求：

- 只返回目标课程的上游依赖区域。
- 支持深度限制。
- 防止循环遍历。
- 返回节点和边的原始语义属性。
- 不默认绘制全校824个节点。

## 7 先修规则服务

`app/prerequisite_service.py` 负责先修条件求值，不能仅依赖 NetworkX 最短路径。

### 7.1 直接先修规则

建议接口：

```python
get_prerequisite_rule(course_id_or_alias: str) -> PrerequisiteRule
```

返回：

- 严格先修分组
- 先修或共修分组
- 非严格候选或层级约束
- 反向限制
- 原始条款

### 7.2 解锁判断

建议接口：

```python
evaluate_prerequisites(
    target_course: str,
    completed_courses: list[str],
    concurrent_courses: list[str] | None = None,
) -> PrerequisiteEvaluation
```

要求：

- 输入课程先通过别名表规范化。
- `strict = 1` 且 `issue = 'ok'` 的规则可决定解锁。
- 组内 AND 需要全部满足。
- 组内 OR 满足一个即可。
- 组间按 `group_relation` 合并。
- `prerequisite_or_corequisite` 可以由已修或当学期并修满足。
- `strict = 0` 只能显示为提示，不能单独阻止解锁。
- 反向限制单独返回，不能混入先修 AND/OR 分组。
- 任课教师同意、年级和未结构化条件应作为人工确认项。

返回至少包括：

- `status`: satisfied、unsatisfied、needs_manual_review
- 已满足分组
- 未满足分组
- 可选满足路径
- 非严格提示
- 反向限制冲突
- 原文和数据来源

### 7.3 递归依赖

建议接口：

```python
get_recursive_requirements(
    target_course: str,
    completed_courses: list[str],
    max_depth: int | None = None,
) -> RequirementTree
```

要求：

- 标记已完成、缺失、OR 分支、共修和人工确认条件。
- 使用 visited 或路径状态避免循环。
- 同一课程在不同 OR 分支出现时保留必要语义，但展示层可以去重。
- 不把一条图路径当作完整可执行计划。

## 8 专业规则服务

`app/major_service.py` 负责专业列表、规则加载和完成度求值。

### 8.1 专业列表

建议接口：

```python
list_majors() -> list[str]
```

要求：

- 返回39个专业或公共要求范围。
- 名称排序稳定。

### 8.2 专业规则

建议接口：

```python
get_major_rules(major: str) -> MajorRuleSet
```

规则分类：

- `status = 'verified' AND operator != 'ADVISORY' AND counts_toward_completion = 1`：计入完成度。
- `operator = 'ADVISORY'`：只展示为推荐选修。
- `status = 'blocked'`：返回无法自动判断及原因。

必须通过现有 `data/major_rule_engine.py` 求值，不能在网页层重新实现规则。

### 8.3 专业完成度

建议接口：

```python
evaluate_major_progress(
    major: str,
    completed_courses: list[str],
) -> MajorProgress
```

返回：

- 专业名称
- 规则总数
- 已满足规则
- 未满足规则
- blocked 规则
- 推荐选修
- 已计入课程
- 剩余门数或学分
- 规则原文和印刷页码

要求：

- 支持 ALL、CHOOSE、ANY、QUOTA 和嵌套子规则。
- 交叉列课只能计数一次。
- blocked 规则不得返回 satisfied 或 unsatisfied。
- ADVISORY 不进入完成百分比。
- 若仍有 blocked 规则，整体结果必须提示存在无法自动判断项。
- 不宣称这是学校官方学位审核结果。

## 9 数据模型

建议使用 `dataclasses`、TypedDict 或其他明确的数据结构表示接口结果。禁止在页面和测试中依赖含义不明的裸元组。

至少定义：

- `CourseSummary`
- `CourseDetail`
- `SectionRecord`
- `PrerequisiteGroup`
- `PrerequisiteEvaluation`
- `RequirementTreeNode`
- `MajorRuleResult`
- `MajorProgress`

字段命名应稳定，并明确区分：

- 缺失值与空字符串
- 真实0与未知
- `not_applicable`、`blocked` 和 `unsatisfied`
- 已观察开课与预测开课

## 10 缓存边界

Streamlit 可以缓存：

- 数据库路径和只读 Repository。
- 已构建的静态 NetworkX 图。
- 专业规则树。

不得缓存：

- 与具体学生已修课程相关的求值结果，除非缓存键完整包含输入。
- 打开的 SQLite connection 或 cursor 跨线程共享。
- 旧数据库文件被替换后的过期内容。

建议以数据库文件修改时间或版本字段作为缓存失效依据。

## 11 自动测试

### 11.1 数据库测试

- 只读连接可以执行 SELECT。
- 写入语句被拒绝。
- 缺少数据库文件时给出明确错误。
- 缺少必需表时给出 schema 错误。

### 11.2 课程查询测试

- 规范课程代码精确搜索。
- 小写和带空格代码搜索。
- 别名解析。
- 交叉列课不会重复返回。
- 未知课程返回 not found。
- 名称关键词搜索。
- 四个已记录学期的开课记录查询。

### 11.3 图测试

- 节点数量与数据库一致。
- 边端点全部存在。
- 孤立节点被保留。
- 边方向正确。
- 严格和非严格属性保留。
- 局部子图不包含无关节点。

### 11.4 先修求值测试

- 单一先修。
- AND 组合。
- OR 组合。
- 组内 AND 与组间 OR 的嵌套情况。
- 先修或共修。
- strict 0 不单独阻止解锁。
- 反向限制冲突。
- 未知课程。
- 递归依赖去重和循环防护。

建议至少使用报告中已经人工核对的课程作为测试样例：

- `MATH206`
- `STATS202`
- `STATS303`
- `COMPSCI203`
- `COMPSCI306`

### 11.5 专业完成度测试

- 39个专业均可加载。
- 空已修列表不会错误显示完成。
- 全部候选课程输入可满足相应 verified 规则。
- ALL、CHOOSE、ANY、QUOTA 分别有正反案例。
- ADVISORY 不计入完成度。
- blocked 返回无法自动判断。
- 交叉列课不重复计数。
- 与 `data/major_rule_tests.json` 的670条测试兼容。

## 12 与现有 demo.py 的迁移

本阶段不要求完整重写页面，但应完成以下迁移：

1. 删除对 `curriculum_subset_math_cs_ds.xlsx` 的运行时依赖。
2. 页面课程选择器改为调用课程 Repository。
3. 课程详情改为调用 `get_course` 和 `get_recorded_sections`。
4. 先修面板改为调用先修规则服务。
5. 专业完成度改为调用专业规则服务。
6. 旧的 DataFrame 专业解析函数不再参与生产逻辑。
7. 旧的最短路径可以保留为结构探索功能，但必须明确标记“不是修课计划”。
8. 全校网络图默认不加载或绘制。

## 13 交付物

本任务完成时应产生：

1. `app/database.py`
2. `app/course_repository.py`
3. `app/graph_service.py`
4. `app/prerequisite_service.py`
5. `app/major_service.py`
6. 所需的数据模型文件或模块
7. `tests/` 下对应的自动测试
8. 已迁移到 SQLite 接口的 `demo.py`
9. `data/task_step2_report.md`，记录实现范围、测试结果、限制和下一阶段建议

## 14 验收标准

只有同时满足以下条件，本任务才算完成：

- [ ] 所有数据库访问使用只读模式。
- [ ] 数据访问代码不依赖用户机器的绝对路径。
- [ ] 必需数据库表在启动时得到验证。
- [ ] `demo.py` 不再读取旧 Excel 子集。
- [ ] 页面不直接执行 SQL。
- [ ] 数据访问层不依赖 Streamlit。
- [ ] 824个规范课程节点均可查询。
- [ ] 所有课程别名和开课代码均可解析。
- [ ] 图关系端点全部存在。
- [ ] 孤立课程节点不会因从边表建图而丢失。
- [ ] 严格边、非严格边和反向限制被区分处理。
- [ ] AND、OR、先修或共修逻辑通过自动测试。
- [ ] strict 0 关系不会单独阻止课程解锁。
- [ ] 课程搜索、课程详情和开课记录接口通过测试。
- [ ] 39个专业均可查询。
- [ ] 专业完成度使用现有规则引擎。
- [ ] ALL、CHOOSE、ANY、QUOTA 和嵌套规则通过测试。
- [ ] ADVISORY 不计入完成度。
- [ ] blocked 不返回确定完成状态。
- [ ] 交叉列课不会重复计数。
- [ ] 与670条持久化专业规则测试兼容。
- [ ] 核心服务可以在不启动 Streamlit 的情况下测试。
- [ ] 自动测试全部通过。
- [ ] 没有写入或修改 `curriculum.sqlite`。

完成本任务后进入 Step 3：重构网页信息架构和视觉界面，并把页面完整接入这些服务。
