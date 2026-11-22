# Step 1 专业规则修复与验证

## 1 任务目标

修复专业要求解析器及 35 条高风险专业规则，把 DKU Undergraduate Bulletin 中的专业要求转换为可执行、可追溯、可测试的规则。

完成本任务后，系统应能可靠判断全部专业的要求完成情况，并为网页原型中的专业完成度、专业路线图和候选课程提示提供正确数据。

本任务不包括网页界面开发、校友或职业数据、课程推荐模型以及完整学期排课优化。

## 2 问题范围

当前需要处理两类高风险规则，共 35 条：

1. 21 条已标记为 `partial_count` 或 `partial_unresolved` 的规则。
2. 14 条当前标记为 `executable` 或 `executable_flagged`，但原文语义与数据库编码可能不一致的规则。

主要错误模式包括：

- N 选 K 被编码为全部完成。
- 最低学分要求被编码为课程数量要求或全部完成。
- Cluster、List、Concentration 等分组关系丢失。
- “每组至少一门”等附加约束没有保存。
- 交叉列课被重复计数或无法唯一映射。
- 跨页课程列表解析不完整。
- 课程层级、院系或课程属性约束没有结构化。
- 课程代码笔误、别名或缺失节点尚未解决。

## 3 必须支持的规则类型

### 3.1 全部完成

适用于所有列出的课程都必须完成的要求。

```text
ALL(MATH201, MATH202, MATH206)
```

### 3.2 N 选 K

适用于从候选课程中完成指定门数。

```text
CHOOSE 3 OF {COURSE_A, COURSE_B, COURSE_C, COURSE_D}
```

### 3.3 最低学分

适用于从课程列表中完成指定最低学分。

```text
MIN_CREDITS 8 FROM {COURSE_A, COURSE_B, COURSE_C}
```

必须按课程学分计算，不能用课程门数替代。

### 3.4 分组选择

适用于总门数要求与组内最低要求同时存在的情况。

```text
TOTAL_COURSES >= 3
AND CLUSTER_1 >= 1
AND CLUSTER_2 >= 1
```

### 3.5 方向选择

适用于先选择一个 Concentration，再完成该方向内部要求的情况。

```text
CHOOSE 1 OF {
  CONCENTRATION_A: CHOOSE 3 OF {...},
  CONCENTRATION_B: CHOOSE 3 OF {...},
  CONCENTRATION_C: CHOOSE 3 OF {...}
}
```

不同方向的课程不能混合后误判为完成某一方向。

### 3.6 课程属性约束

适用于按课程层级、院系或其他属性选择课程。

```text
CHOOSE 2 WHERE level IN {300, 400}
```

必要时应组合多个条件：

```text
department = ARTS AND level IN {300, 400}
```

### 3.7 跨院系约束

适用于每个指定院系至少完成一定课程数的情况。

```text
COUNT(department = PHIL) >= 1
AND COUNT(department = RELIG) >= 1
```

### 3.8 替代方案

适用于完成多个方案中的任意一个。

```text
ANY_OF {
  ALL(OPTION_1_COURSES),
  ALL(OPTION_2_COURSES)
}
```

每个方案内部可以继续包含 N 选 K、最低学分或分组约束。

## 4 数据库规则结构

优先采用可表达嵌套逻辑的规则树，不再依赖单行 `rule_kind` 表达全部要求。

### 4.1 major_rules

保存顶层规则及来源信息。

| 字段 | 含义 |
|---|---|
| `rule_id` | 规则编号 |
| `major` | 专业或方向 |
| `category` | Foundation、Disciplinary、Electives 等 |
| `operator` | ALL、ANY、CHOOSE、MIN_CREDITS 等 |
| `required_count` | 最低课程数量 |
| `required_credits` | 最低学分 |
| `status` | verified、partial、blocked |
| `source_phrase` | Bulletin 原文 |
| `source_page` | Bulletin 页码 |
| `note` | 人工修复说明 |

### 4.2 major_rule_items

保存规则包含的课程、课程组或子规则。

| 字段 | 含义 |
|---|---|
| `rule_id` | 所属规则 |
| `item_type` | course、group、attribute_filter |
| `course_id` | 规范课程代码 |
| `child_rule_id` | 嵌套子规则编号 |
| `group_name` | Cluster、List 或 Concentration 名称 |
| `resolution` | exact、alias、manual 等 |

### 4.3 major_rule_constraints

保存课程层级、院系、最低数量和最低学分等附加条件。

| 字段 | 含义 |
|---|---|
| `rule_id` | 所属规则 |
| `constraint_type` | min_count、min_credits、department、level 等 |
| `field` | 被约束字段 |
| `operator` | `>=`、`IN`、`=` 等 |
| `value` | 约束值 |

如不修改现有表结构，也必须提供等价的数据表达能力，并保留从新结构到现有表的兼容层。

## 5 实施步骤

### 5.1 建立规则审计清单

从数据库导出以下规则：

- 所有 `partial_count` 规则。
- 所有 `partial_unresolved` 规则。
- 已识别的 14 条可疑 `executable` 或 `executable_flagged` 规则。

每条规则记录：

- `rule_id`
- 专业和分类
- Bulletin 原文及页码
- 当前解析结果
- 预期规则结构
- 涉及的课程和分组
- 发现的问题
- 修复方法
- 人工审核状态

输出文件：`data/major_rule_audit.md`。

### 5.2 优先修复假可执行规则

这类规则当前可能直接产生错误的专业完成度结果，应最先处理。

重点检查：

- Behavioral Science Psychology 的课程集群规则。
- Computation and Design Computer Science 的选择规则。
- Computation and Design Social Policy 的 Methods 与 Concentration 规则。
- Humanities 各方向的课程数量和学分规则。
- Molecular Bioscience 各方向的 N 选 K 规则。

处理要求：

1. 找到 Bulletin 完整原文及页码。
2. 确认候选课程列表的起止位置。
3. 确定按门数、学分、院系、层级还是方向判断。
4. 建立正确的规则树。
5. 编写至少一个满足案例和一个不满足案例。
6. 人工核对后才可将状态设为 `verified`。

### 5.3 修复 partial_count

对 11 条候选数量与原文声明不一致的规则逐条检查：

- PDF 表格是否把一门交叉列课拆成多行。
- 交叉列课是否被重复计数。
- 课程名称换行是否被识别为新课程。
- 课程列表是否跨页。
- `expected_n` 是否从错误文本推断。
- 同一课程的别名是否被当作多个候选项。

完成条件：

```text
规范化后的候选项数量 = Bulletin 声明的候选数量
```

交叉列课必须按一个课程实体计数。

### 5.4 修复 partial_unresolved

对 10 条无法完整解析的规则检查：

- 缺少课程节点的课程代码。
- 课程代码笔误或历史代码。
- 交叉列课无法唯一对应。
- 列表标题或说明文字被误识别为课程。
- 跨页解析导致候选列表不完整。
- 未结构化的院系、层级、学分或分组选课条件。

不能从 Bulletin 或其他权威来源确认的内容不得猜测。无法确认的规则必须设为 `blocked`，保存原文、页码和待确认问题，并从专业完成度计算中排除。

### 5.5 修复规则解析器

解析器至少需要：

- 识别 `choose one/two/three` 等数量表达。
- 识别 `at least N credits`。
- 识别 List、Cluster、Track、Option 和 Concentration 边界。
- 识别“每组至少一门”等附加约束。
- 识别课程层级和院系条件。
- 处理跨页列表和换行。
- 规范化交叉列课但避免重复计数。
- 保留无法自动解析的原文，不静默降级为 `all` 或 `optional`。
- 对不确定结果生成 `partial` 或 `blocked`，不能生成虚假的 `executable`。

### 5.6 重建并审计专业规则

解析器修复后重新生成专业规则，并运行以下检查：

- 每条 `verified` 规则的课程均能解析到规范课程节点。
- `CHOOSE K OF N` 满足 `K <= N`。
- 原文声明 N 个候选项时，规范化候选数量与 N 一致。
- 最低学分规则具有有效课程学分。
- 分组规则的每个子组均非空。
- 嵌套规则不存在循环引用。
- 同一课程在同一规则中不会因别名重复计数。
- `blocked` 规则不参与完成度计算。
- 每条规则均保存来源原文和页码。

## 6 规则级测试

每条修复后的规则至少包含一个通过案例和一个失败案例。复杂规则需要覆盖所有边界。

### 6.1 正向边界

学生刚好满足最低门数或最低学分，预期为完成。

### 6.2 负向边界

学生少一门课或少一个学分，预期为未完成，并返回准确缺口。

### 6.3 超额完成

学生完成超过最低要求的课程，预期仍为完成。

### 6.4 无关课程

学生完成数量足够但不属于候选池的课程，预期为未完成。

### 6.5 交叉列课

修读任一合法交叉列课代码都应满足同一课程要求，但只能计数一次。

### 6.6 重复计数

同一门课程不能因别名、多列表位置或多条映射重复计入门数或学分。

### 6.7 分组约束

总门数满足但某个必需分组为空时，预期为未完成。

### 6.8 学分规则

使用不同学分课程组合，确认按实际学分计算，而不是按课程门数计算。

### 6.9 方向选择

同一方向内满足要求时应通过；从不同方向混合课程但没有满足任一完整方向时应失败。

### 6.10 被阻塞规则

状态为 `blocked` 的规则必须返回“无法自动判断”和具体原因，不能返回完成或未完成。

## 7 测试数据格式

测试用例可使用 JSON 或 YAML，建议包含：

```yaml
rule_id: 71
major: Computation and Design-Social Policy
case: valid_concentration_selection
completed_courses:
  - COURSE_A
  - COURSE_B
  - COURSE_C
expected:
  status: satisfied
  selected_option: Urban Design
  remaining_courses: 0
```

失败案例：

```yaml
rule_id: 71
major: Computation and Design-Social Policy
case: courses_mixed_across_concentrations
completed_courses:
  - URBAN_COURSE_A
  - MEDIA_COURSE_A
  - POLICY_COURSE_A
expected:
  status: unsatisfied
  reason: Courses do not satisfy one concentration
```

## 8 交付物

本任务完成时应产生：

1. `data/major_rule_audit.md`：35 条高风险规则的人工审计记录。
2. `data/major_rule_tests.json` 或 `data/major_rule_tests.yaml`：规则级测试数据。
3. `data/major_rule_test_report.md`：自动测试结果和剩余阻塞项。
4. 修复后的专业规则解析器及数据库构建逻辑。
5. 更新后的 `data/curriculum.sqlite`。
6. 更新后的 `data/graph_readiness_report.md`，说明专业规则是否达到网页开放条件。

## 9 验收标准

只有同时满足以下条件，本任务才算完成：

- [ ] 35 条高风险规则均有人工核对记录。
- [ ] 所有规则均保留 Bulletin 原文和准确页码。
- [ ] 不再存在语义错误但标记为 `executable` 或 `verified` 的规则。
- [ ] 所有专业均能加载，不发生解析错误。
- [ ] 所有已验证专业要求均能得到正确完成状态。
- [ ] 无法确认的规则被标记为 `blocked`，不参与完成度计算。
- [ ] 交叉列课和别名不会造成重复计数。
- [ ] 课程数量和学分要求分别按正确单位计算。
- [ ] Cluster、List、Option、Concentration 和替代方案可以正确求值。
- [ ] 每条修复规则至少有一个通过测试和一个失败测试。
- [ ] 所有规则级自动测试通过。
- [ ] 数据库审计未发现无法解析的已验证规则引用。
- [ ] 网页仅对 `verified` 规则显示确定的完成度。

完成以上验收前，网页可以继续开发课程搜索、依赖树和严格先修判断，但不能宣称专业完成度已经覆盖全部专业。
