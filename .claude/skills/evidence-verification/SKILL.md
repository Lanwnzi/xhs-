---
name: evidence-verification
description: 当准备声称任务完成、bug 已修复、测试通过、报告生成成功、洞察可靠、评分可信、市场结论成立或准备进入下一阶段时，必须使用本 skill。本 skill 要求先提供工程验证证据和业务证据链，再允许做完成性结论。适用于小红书 UGC 市场验证系统中的测试验证、产物验证、ScoreCard 验证、Insight 证据链验证和 HTML 报告可信性检查。
---

# Evidence Verification

## 核心定位

本 skill 用于防止 Claude Code 在没有证据的情况下声称：

- 完成了
- 修好了
- 测试通过了
- 报告生成了
- 评分可信
- 市场机会明显
- 用户需求强烈

本项目中，证据分为两类：

```text
1. 工程验证证据
- 测试命令
- 运行输出
- 退出码
- 生成文件
- diff 结果

2. 业务证据链
- evidence_post_ids
- evidence_comment_ids
- 原始帖子
- 原始评论
- insight 与证据的对应关系
- scorecard 与统计指标的对应关系
```

铁律：

```text
没有验证命令，不说测试通过。
没有输出文件，不说产物生成。
没有 evidence，不说市场结论。
没有规则计算，不说评分可信。
```

---

## 适用场景

以下场景必须使用本 skill：

- 准备说“完成了”
- 准备说“修好了”
- 准备说“测试通过”
- 准备说“pipeline 跑通”
- 准备说“report.html 已生成”
- 准备说“ScoreCard 可信”
- 准备说“洞察有依据”
- 准备说“市场机会明显”
- 准备进入下一个 backlog task
- developer-agent 完成任务后
- review-requesting 之前
- 提交代码或合并前

---

# 第一部分：工程验证

## 1. 完成性声明前必须运行命令

在声称任何任务完成前，必须先回答：

```text
要证明这个结论，需要运行什么命令？
```

常见结论与验证命令：

| 声称 | 必须验证 |
|---|---|
| schema 可用 | `pytest tests/test_schemas.py` |
| scoring 可用 | `pytest tests/test_scoring_agent.py` |
| report 可用 | `pytest tests/test_report_agent.py` |
| pipeline 跑通 | `pytest tests/test_pipeline_e2e.py` |
| 全部测试通过 | `pytest` |
| report.html 生成 | 检查文件存在且内容包含规定章节 |
| bug 修复 | 复现 bug 的 regression test 通过 |

禁止：

```text
应该可以了。
看起来没问题。
我已经修好了。
理论上能跑。
```

---

## 2. 必须读取输出结果

运行命令后必须检查：

- exit code
- passed 数量
- failed 数量
- error 数量
- warning 是否影响结果
- 输出文件是否真的存在
- 文件内容是否符合预期

示例：

```text
验证命令：
pytest tests/test_pipeline_e2e.py

验证结果：
- 1 passed
- 0 failed
- 0 errors
- 退出码：0

结论：
- pipeline_e2e 测试通过。
```

如果没有运行命令，只能说：

```text
尚未验证，不能声称通过。
```

---

## 3. 产物验证

完成一次主题分析后，必须确认以下文件存在：

```text
data/raw/raw_posts.json
data/normalized/normalized_posts.json
data/outputs/insights.json
data/outputs/scorecard.json
data/outputs/report.html
```

检查内容：

```text
raw_posts.json：
- 是否有帖子数据
- 是否有评论数据

normalized_posts.json：
- 是否符合 PostRecord / CommentRecord

insights.json：
- 是否有 pain_points / user_needs / complaints / solutions / market_signals
- 是否有 evidence_post_ids / evidence_comment_ids

scorecard.json：
- 是否包含 demand_intensity / sentiment_friction / solution_saturation / purchase_intent / freshness / overall_score
- 分数是否在 0-100
- scoring_reason 是否存在

report.html：
- 是否包含项目主题
- 是否包含评分总览
- 是否包含评分拆解
- 是否包含用户需求
- 是否包含负面反馈
- 是否包含替代方案
- 是否包含高频关键词
- 是否包含代表性证据
- 是否包含建议切入点
- 是否包含风险提示
```

---

# 第二部分：业务证据链验证

## 1. Insight 必须有证据

每一类洞察都必须能追溯到帖子或评论：

- pain_points
- user_needs
- complaints
- solutions
- market_signals

最低要求：

```text
每条 InsightRecord 至少包含：
- evidence_post_ids 非空
或
- evidence_comment_ids 非空
```

如果没有 evidence，不能输出：

- 市场机会
- 用户需求强烈
- 购买意愿明显
- 适合切入
- 用户痛点集中

只能输出：

```text
当前样本证据不足，只能作为初步观察，不能形成确定性市场结论。
```

---

## 2. Evidence ID 必须真实存在

必须验证：

```text
evidence_post_ids 中的 ID 是否存在于 normalized_posts.json
evidence_comment_ids 中的 ID 是否存在于 normalized_posts.json 或 comments 数据中
```

禁止：

- 编造 evidence id
- 使用不存在的 post_id
- 使用不存在的 comment_id
- 用空 evidence 支撑市场结论

---

## 3. 代表性证据必须和结论匹配

不能出现：

```text
结论：用户强烈抱怨价格贵
证据：评论只说“挺好看的”
```

必须检查：

```text
结论中的关键词
是否能在证据帖子或评论中找到语义支撑
```

如果证据只是弱相关，应降低结论强度：

```text
强结论：
- 用户普遍认为价格过高。

弱结论：
- 部分评论提到价格敏感，但当前样本不足以判断是否为主流痛点。
```

---

## 4. ScoreCard 必须可追溯

ScoreCard 不能只给分数，必须说明每个分数来自什么统计或规则。

必须验证：

```text
demand_intensity：
- 是否来自帖子数、评论数、需求关键词频次、互动强度等规则

sentiment_friction：
- 是否来自负面评论比例、抱怨密度、痛点强度等规则

solution_saturation：
- 是否来自替代方案数量、竞品提及频率、解决方案重复度等规则

purchase_intent：
- 是否来自购买意图词、询价词、求链接、求推荐等信号

freshness：
- 是否来自发布时间、近期互动、近期评论密度等规则

overall_score：
- 是否由前五项加权计算
```

禁止：

```text
LLM 直接输出 overall_score。
LLM 直接决定 purchase_intent。
LLM 直接裸打分。
```

---

## 5. 报告不得新增无证据结论

ReportAgent 只能读取：

```text
normalized_posts.json
insights.json
scorecard.json
```

ReportAgent 禁止：

- 重新计算评分
- 新增没有 evidence 的市场机会
- 编造用户评论
- 编造数据来源
- 把弱证据写成强结论

报告中的每个“建议切入点”和“风险提示”都必须来自：

- insights.json
- scorecard.json
- 代表性证据

---

# 验证流程

执行 evidence verification 时，按以下顺序：

```text
1. 工程验证
- 跑测试
- 检查产物
- 检查文件内容

2. schema 验证
- PostRecord
- CommentRecord
- InsightRecord
- ScoreCard

3. insight 证据验证
- evidence_post_ids
- evidence_comment_ids
- ID 是否真实存在

4. scorecard 验证
- 规则计算
- 分数范围
- 权重逻辑
- scoring_reason

5. report 验证
- 是否只渲染
- 是否包含规定章节
- 是否存在无证据结论

6. 输出最终结论
- 通过
- 有条件通过
- 不通过
```

---

# 标准输出格式

```text
Evidence Verification 结果：

一、工程验证
- 验证命令：
- 运行结果：
- 退出码：
- 是否通过：

二、产物验证
- raw_posts.json：
- normalized_posts.json：
- insights.json：
- scorecard.json：
- report.html：

三、Insight 证据链
- 是否存在 evidence_post_ids：
- 是否存在 evidence_comment_ids：
- evidence ID 是否真实存在：
- 洞察是否和证据匹配：

四、ScoreCard 证据链
- 是否规则计算：
- 分数是否在 0-100：
- overall_score 是否加权得出：
- scoring_reason 是否存在：

五、Report 证据链
- 是否包含规定章节：
- 是否存在无证据市场结论：
- 是否存在 ReportAgent 重新计算评分：

六、结论
- PASS / PASS_WITH_WARNINGS / FAIL

七、必须修复项
- 

八、可后续优化项
- 
```

---

# 结论等级

## PASS

满足：

- 测试或验证命令通过
- 产物存在
- evidence ID 真实存在
- Insight 和证据匹配
- ScoreCard 规则计算
- Report 无无证据结论

## PASS_WITH_WARNINGS

允许：

- 样本量偏少
- 部分洞察证据较弱
- 报告表达需要更谨慎
- 后续可增强统计指标

但必须明确说明限制。

## FAIL

出现以下任一情况：

- 没有运行验证命令却声称完成
- 关键测试失败
- 关键产物缺失
- Insight 没有 evidence
- evidence ID 不存在
- ScoreCard 由 LLM 直接裸打分
- ReportAgent 重新计算评分
- 报告输出无证据市场机会结论

---

# 禁止事项

禁止说：

```text
应该完成了。
应该没问题。
看起来通过了。
理论上可以。
我认为已经修好。
```

必须说：

```text
已运行 pytest tests/test_pipeline_e2e.py，结果为 1 passed，退出码 0，因此 pipeline_e2e 验证通过。
```

如果没有验证，必须说：

```text
目前尚未运行验证命令，不能声称该任务已完成。
```

---

# 和其他 skills 的关系

## forensic-debugging

forensic-debugging 负责定位和修复问题。

evidence-verification 负责确认修复是否真的有效。

## tdd-discipline

tdd-discipline 负责先写测试。

evidence-verification 负责确认测试是否真的运行并通过。

## review-requesting

review-requesting 负责发起 review。

evidence-verification 应在 review 前或 review 后用于确认事实证据。

## spec-compliance-reviewer

spec-compliance-reviewer 检查是否符合 CLAUDE.md 和职责边界。

evidence-verification 检查完成性声明和业务结论是否有证据。

## code-quality-reviewer

code-quality-reviewer 检查代码质量。

evidence-verification 检查结果是否被验证。

---

# 最终原则

- 先验证，再宣称
- 先证据，再结论
- 先运行命令，再说通过
- 先检查产物，再说生成
- 先检查 evidence，再说市场机会
- 先检查规则计算，再说评分可信
- 没有验证，就只能说“尚未验证”