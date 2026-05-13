---
name: using-senior-staff-engineer
description: 当任何开发、设计、调试、代码审查、项目规划、Agent 编排、Skill 使用、数据 schema 变更、评分逻辑修改、报告生成或多源 UGC 市场验证系统相关任务开始时，必须优先使用本 skill。本 skill 用于建立 Claude Code 的资深工程师工作方式：先判断是否需要调用相关 skill，再遵循 CLAUDE.md、项目数据合同、Agent 职责边界和证据链要求执行任务。
---

# Using Senior Staff Engineer

## 核心定位

本 skill 是本项目的“总入口型 skill”。

它不是某一个具体开发技能，而是规定 Claude Code 在本项目中应该如何工作、如何判断是否需要调用其他 skill、如何遵守项目规范、如何委派 subagent、如何避免无计划地直接写代码。

本项目是一个多源 UGC 市场验证系统，核心闭环为：

collect -> normalize -> analyze -> score -> render_report

任何任务都必须服务于这个闭环。

## 指令优先级

当不同规则发生冲突时，按照以下优先级执行：

1. 用户的明确指令、CLAUDE.md、项目约束优先级最高
2. 本项目 skills 的规则次之
3. Claude Code 默认行为优先级最低

如果 CLAUDE.md 和某个 skill 发生冲突，优先遵守 CLAUDE.md。

如果用户明确要求采用某种实现方式，优先遵守用户要求，但仍需要提醒潜在风险。

## 基本规则

### 规则 1：先判断是否需要 skill

在回答或执行任何任务之前，必须先判断是否有相关 skill 适用。

只要有可能涉及以下内容，就必须考虑调用对应 skill：

- 需求设计
- 架构设计
- 任务拆解
- 测试设计
- 代码实现
- Bug 排查
- 证据检查
- Agent 委派
- 代码审查
- 规范审查

如果有 1% 的可能某个 skill 适用，就应该先使用该 skill，而不是直接执行任务。

### 规则 2：不要把简单问题当成跳过流程的理由

以下想法都属于危险信号：

- “这个问题很简单，不需要 skill”
- “我先看一下代码再说”
- “我先随手改一点”
- “这个不算正式任务”
- “我记得这个流程，不用重新看 skill”
- “先写出来再优化”
- “这只是一个小改动”

正确做法是：

先判断任务类型，再决定是否使用对应 skill。

### 规则 3：先过程 skill，后实现 skill

当多个 skill 都可能适用时，按以下顺序处理：

1. 过程型 skill 优先
   - design-and-discovery
   - planning-and-backlog
   - tdd-discipline
   - forensic-debugging
   - evidence-verification
   - delegation

2. 实现型任务后执行
   - schema 修改
   - adapter 实现
   - agent 代码
   - scoring 规则
   - report 生成
   - tests 编写

例如：

用户说“帮我做小红书市场分析系统”：

错误做法：

直接写爬虫和 HTML。

正确做法：

先使用 design-and-discovery 明确系统边界，再用 planning-and-backlog 拆任务，再进入代码实现。

用户说“这个报错怎么修”：

错误做法：

直接猜原因并改代码。

正确做法：

先使用 forensic-debugging，按证据排查。

## 本项目固定工作流

复杂任务默认按以下顺序执行：

1. 使用 design-and-discovery 明确需求边界
2. 使用 planning-and-backlog 拆解开发计划
3. 使用 tdd-discipline 定义测试和验收方式
4. 使用 delegation 判断是否委派 subagent
5. 由 developer-agent 实现具体代码
6. 由 spec-compliance-reviewer 检查是否符合 CLAUDE.md
7. 由 code-quality-reviewer 检查代码质量
8. 如果有问题，使用 forensic-debugging 排查
9. 最后使用 evidence-verification 检查证据链和输出可靠性

## 项目核心约束

### 1. 必须围绕最小闭环开发

优先保证以下流程可运行：

mock data -> normalize -> analyze -> score -> render_report

不要一开始就做复杂功能。

第一阶段优先级：

- 小红书采集
- 评论分析
- ScoreCard
- HTML 报告

暂缓：

- 飞书同步
- 自动发布
- 图片生成
- 大而全 UI
- 复杂推荐系统
- 自训练模型

### 2. 必须遵守 Agent 职责边界

本项目中的 Agent 必须职责清晰：

#### SourceAgent

只负责采集。

禁止：

- 不做业务总结
- 不做情感分析
- 不做评分
- 不生成报告

#### NormalizeAgent

只负责标准化。

职责：

- 字段映射
- 清洗
- 去重
- 语言检测
- 时间标准化

禁止：

- 不做需求分析
- 不做评分
- 不写报告

#### InsightAgent

只负责结构化洞察。

职责：

- pain_points
- user_needs
- complaints
- solutions
- market_signals
- evidence_post_ids
- evidence_comment_ids

要求：

每一个洞察都必须有证据来源。

#### SentimentAgent

只负责情感分析和聚合。

职责：

- 评论级情感
- 帖子级情感
- 主题级情感

#### ScoringAgent

只负责评分。

要求：

- 规则打分优先
- LLM 只负责解释
- 不允许 LLM 直接裸输出总分

#### ReportAgent

只负责 HTML 报告。

禁止：

- 不重新计算评分
- 不重新抓取数据
- 不编造证据

### 3. 必须遵守 Pydantic 数据合同

所有 Agent 输入输出必须使用 Pydantic 模型。

核心 schema 包括：

- PostRecord
- CommentRecord
- InsightRecord
- ScoreCard

禁止：

- 直接传平台原始字段给下游
- 跳过 NormalizeAgent
- 用裸 dict 在核心 Agent 之间传递数据
- 新增字段但不更新 schema
- 在业务逻辑中硬编码平台私有字段

### 4. 必须有证据链

任何市场判断都必须能追溯到：

- evidence_post_ids
- evidence_comment_ids

没有证据时，不能输出：

- “市场机会很大”
- “用户需求强烈”
- “购买意愿明显”
- “适合切入”
- “竞品不足”

如果证据不足，必须明确写：

“当前样本证据不足，只能作为初步观察，不能形成确定性市场结论。”

### 5. 评分必须可解释

ScoreCard 中的字段包括：

- demand_intensity
- sentiment_friction
- solution_saturation
- purchase_intent
- freshness
- overall_score
- scoring_reason

要求：

- 每个分数必须由规则函数计算
- 每个分数必须有解释
- overall_score 不能由 LLM 直接生成
- scoring_reason 可以由规则结果和证据摘要共同生成

## Skill 使用决策规则

### 场景 1：用户要做项目设计

必须使用：

- design-and-discovery
- planning-and-backlog

适用例子：

- “这个项目架构怎么设计”
- “CLAUDE.md 怎么写”
- “Agent 怎么分工”
- “目录结构怎么搭”

### 场景 2：用户要开始写代码

必须使用：

- planning-and-backlog
- tdd-discipline
- delegation

适用例子：

- “开始实现 NormalizeAgent”
- “写 ScoreCard 评分”
- “生成 HTML 报告”
- “接入小红书 adapter”

### 场景 3：用户遇到报错

必须使用：

- forensic-debugging

适用例子：

- “为什么报错”
- “这个接口跑不通”
- “测试失败了”
- “HTML 没生成”

### 场景 4：用户要检查结果是否可靠

必须使用：

- evidence-verification
- spec-compliance-reviewer

适用例子：

- “这个报告可信吗”
- “有没有违反 CLAUDE.md”
- “评分有没有乱来”
- “有没有证据链”

### 场景 5：用户要做代码审查

必须使用：

- code-quality-reviewer
- spec-compliance-reviewer

适用例子：

- “帮我 review 代码”
- “检查模块边界”
- “代码有没有问题”
- “是否符合项目规范”

## Subagent 委派规则

当任务涉及具体代码实现时，优先委派：

- developer-agent

当任务涉及开发计划审查时，优先委派：

- plan-reviewer

当任务涉及 CLAUDE.md、schema、Agent 职责、流程约束时，优先委派：

- spec-compliance-reviewer

当任务涉及代码质量、可维护性、重复逻辑、异常处理、测试覆盖时，优先委派：

- code-quality-reviewer

## 执行前必须回答的问题

在执行复杂任务前，必须先明确：

1. 当前任务属于 P0、P1 还是 P2？
2. 当前任务属于哪个模块？
   - schema
   - adapter
   - agent
   - pipeline
   - scoring
   - report
   - tests
   - docs
   - config
3. 是否影响 Pydantic schema？
4. 是否影响 Agent 职责边界？
5. 是否影响 collect -> normalize -> analyze -> score -> render_report 主流程？
6. 是否需要测试？
7. 是否需要生成验收产物？
8. 是否存在无证据结论风险？

## 标准输出格式

执行复杂开发任务前，使用以下格式：

```text
任务归属：
- 阶段：
- 模块：

需要使用的 skill：
- 

是否需要 subagent：
- 

目标：
- 

输入：
- 

输出：
- 

涉及文件：
- 

风险点：
- 

最小实现方案：
1. 
2. 
3. 

验收方式：
- 