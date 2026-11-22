# 专业规则测试报告

运行 `python3 data/run_major_rule_tests.py`。数据库以只读方式打开。

- 计入完成度的 verified 规则：227 条，覆盖 39 个专业。查询条件是 `status = 'verified' AND operator != 'ADVISORY' AND counts_toward_completion = 1`。
- 推荐选修 ADVISORY：31 条，不计入完成度。
- blocked：1 条。现行表保留旧规则 18，签名作品的另一种学分拆法，印刷页 92。
- partial：0 条。现行 259 条规则都有印刷页码。
- 被替代的旧规则 19, 21, 23, 27, 28, 31 在 `major_rules_history`，共 6 条。艺术方向的替代规则在印刷页 102，媒体方向在印刷页 107。
- 只读测试 670 条，失败 0 条。

## 案例文件

`data/major_rule_tests.json` 保存全部案例。`origin` 为 `hand` 的是高风险规则的手工案例，`standard` 的是其余现行规则的标准案例。案例带有规则签名。规则内容变化后，只读运行会失败，需要重新执行 `python3 data/run_major_rule_tests.py --write-catalog`。
