---
name: design-and-discovery
description: 当用户提出任何新功能、架构设计、Agent 分工、数据 schema 变更、平台接入、评分规则、报告生成、工作流调整或行为修改时，必须先使用本 skill。该 skill 用于在实现之前完成需求发现、边界澄清、方案比较、数据流设计和验收标准确认，禁止在设计确认前直接写代码或脚手架。
---

# Design and Discovery

## 核心定位

本 skill 用于把一个模糊想法转化为清晰、可实现、可验收的设计方案。

在本项目中，任何开发任务都不能直接从“想做什么”跳到“开始写代码”。

必须先完成：

1. 理解项目上下文
2. 明确用户目标
3. 澄清边界和约束
4. 提出 2-3 个可选方案
5. 推荐一个最小可行方案
6. 明确数据流、模块边界和验收标准
7. 得到用户确认后，再进入 planning-and-backlog

本项目是一个多源 UGC 市场验证系统，核心闭环为：

collect -> normalize -> analyze -> score -> render_report

设计时必须始终围绕这个闭环展开。

## 适用场景

当用户提出以下任务时，必须使用本 skill：

- 新建项目架构
- 修改 CLAUDE.md
- 新增 skill
- 新增 subagent
- 设计 Agent 分工
- 设计数据流
- 新增平台 adapter
- 接入小红书
- 接入 Reddit
- 修改 Pydantic schema
- 设计 NormalizeAgent
- 设计 InsightAgent
- 设计 SentimentAgent
- 设计 ScoringAgent
- 设计 ReportAgent
- 设计 ScoreCard 评分规则
- 设计 HTML 报告结构
- 设计 mock 数据闭环
- 修改主流程 collect -> normalize -> analyze -> score -> render_report
- 做 P0 / P1 / P2 阶段拆分

## 最高优先级规则

在设计完成并获得用户确认之前，禁止：

- 写业务代码
- 创建复杂脚手架
- 修改核心文件
- 实现爬虫
- 实现评分函数
- 实现报告模板
- 调用 developer-agent 直接开发
- 跳到测试实现
- 进入 debugging 流程

如果用户明确要求“直接写代码”，仍然需要先给出一个极简设计确认。

可以很短，但不能跳过。

## 设计前必须理解的项目上下文

设计时必须优先检查或引用以下项目规则：

- CLAUDE.md
- P0 / P1 / P2 优先级
- 统一数据合同
- Agent 分工
- 工作流约束
- 报告规范
- 验收产物

本项目的固定数据合同包括：

- PostRecord
- CommentRecord
- InsightRecord
- ScoreCard

本项目的固定 Agent 包括：

- SourceAgent
- NormalizeAgent
- InsightAgent
- SentimentAgent
- ScoringAgent
- ReportAgent

本项目的固定验收产物包括：

- data/raw/raw_posts.json
- data/normalized/normalized_posts.json
- data/outputs/insights.json
- data/outputs/scorecard.json
- data/outputs/report.html

## 发现阶段流程

### 第一步：理解当前任务

先判断用户当前任务属于哪一类：

- 项目初始化
- 架构设计
- 数据 schema 设计
- adapter 设计
- Agent 设计
- pipeline 设计
- scoring 设计
- report 设计
- 测试设计
- 规范设计
- 阶段规划

并判断任务属于：

- P0
- P1
- P2

### 第二步：判断任务规模

如果任务过大，必须先拆分。

例如：

用户说：

“我要做一个小红书、Reddit、飞书同步、自动发布、图片生成、完整前端 UI 的市场分析系统。”

不能直接设计整个大系统。

应该拆成：

1. P0：mock 数据闭环
2. P0：小红书采集 + 评论分析
3. P0：ScoreCard + HTML 报告
4. P1：Reddit 对照验证
5. P1：多平台比较
6. P2：飞书同步
7. P2：自动发布和图片生成

然后只对当前阶段进行设计。

### 第三步：一次只问一个澄清问题

当需求不清楚时，只问一个问题。

优先使用选择题，而不是连续问多个开放问题。

错误做法：

“你要采集哪些平台？是否需要登录？数据存哪里？评分规则怎么定？报告要什么样？”

正确做法：

“这一步我们先确认范围：你希望当前先做哪一个最小闭环？A. mock 数据闭环；B. 小红书真实采集；C. HTML 报告模板；D. ScoreCard 评分规则。”

### 第四步：提出 2-3 个方案

在真正设计前，必须给出 2-3 个方案，并说明优缺点。

例如：

对于“先搭 UGC 市场验证系统”，可以给出：

方案 A：先做 mock 数据闭环  
优点：最快跑通系统主流程，风险低。  
缺点：暂时没有真实平台数据。

方案 B：先做小红书采集  
优点：更贴近真实业务。  
缺点：容易卡在登录、反爬、Cookie 和接口变化。

方案 C：先做报告与评分  
优点：可以快速展示结果。  
缺点：如果没有标准数据输入，后续容易返工。

推荐：

优先方案 A，因为它先验证架构和数据合同，再替换真实 adapter，最符合工程闭环。

### 第五步：输出设计方案

设计方案必须覆盖：

- 目标
- 非目标
- 输入
- 输出
- 数据流
- 模块边界
- 涉及文件
- 风险点
- 最小实现路径
- 验收标准

## 本项目设计原则

### 1. 先 mock 闭环，后真实平台

任何平台接入之前，优先确认：

mock_posts.json -> NormalizeAgent -> InsightAgent -> SentimentAgent -> ScoringAgent -> ReportAgent

能否跑通。

不要一开始陷入小红书反爬、Cookie、登录和浏览器自动化。

### 2. 先 schema，后 Agent

任何 Agent 设计前，必须先确认输入输出 schema。

如果新增字段，必须先更新：

src/schemas/

再修改：

src/agents/

禁止 Agent 之间直接传递无约束 dict。

### 3. 先 adapter，后 SourceAgent

新增平台时，必须先设计平台 adapter。

例如：

- xhs_adapter.py
- reddit_adapter.py

adapter 负责把平台原始数据转换为中间结构。

SourceAgent 再负责调用 adapter。

禁止把平台字段解析逻辑直接写死在 SourceAgent 里。

### 4. 评分必须规则优先

ScoringAgent 设计时必须明确：

- 每个分数来自哪些字段
- 每个分数如何计算
- 分数范围是多少
- 权重如何组合
- LLM 只解释，不直接打分

禁止设计成：

“让 LLM 看评论后直接输出 overall_score。”

### 5. 报告只渲染，不重算

ReportAgent 设计时必须明确：

输入：

- insights.json
- scorecard.json
- normalized_posts.json

输出：

- report.html

禁止：

- 报告阶段重新计算评分
- 报告阶段新增市场结论
- 报告阶段编造证据

### 6. 没有证据，不输出机会判断

Insight 和 Report 设计时必须保证：

每个市场洞察都能追溯到：

- evidence_post_ids
- evidence_comment_ids

如果证据不足，应输出：

“当前样本证据不足，只能作为初步观察。”

## 标准设计输出格式

当用户提出设计类任务时，使用以下格式：

```text
任务判断：
- 阶段：
- 模块：
- 是否需要设计确认：

当前目标：
- 

非目标：
- 

关键约束：
- 

可选方案：
方案 A：
- 做法：
- 优点：
- 缺点：

方案 B：
- 做法：
- 优点：
- 缺点：

方案 C：
- 做法：
- 优点：
- 缺点：

推荐方案：
- 

推荐理由：
- 

初步设计：
1. 数据输入：
2. 数据输出：
3. 模块边界：
4. 主流程：
5. 涉及文件：
6. 风险点：
7. 验收标准：


是否确认进入 planning-and-backlog？