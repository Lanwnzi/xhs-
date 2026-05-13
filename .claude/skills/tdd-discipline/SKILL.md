---
name: tdd-discipline
description: 当用户准备实现新功能、修复 bug、重构代码、修改行为、实现 Agent、实现 schema、实现 scoring、实现 report、实现 pipeline 或添加测试时，必须使用本 skill。本 skill 要求在生产代码之前先定义测试、失败用例或最小验收脚本，遵循 Red-Green-Refactor 流程，禁止在没有测试或验收标准的情况下直接写核心业务代码。
---

# TDD Discipline

## 核心定位

本 skill 用于约束 Claude Code 在本项目中遵守测试驱动开发纪律。

核心原则：

先定义期望行为，再实现代码。

也就是：

1. 先写测试或最小验收脚本
2. 先确认测试会失败
3. 再写最小代码让测试通过
4. 最后重构和清理

本项目是一个多源 UGC 市场验证系统，核心闭环为：

collect -> normalize -> analyze -> score -> render_report

只要代码影响这个闭环，就必须先定义测试或验收方式。

## 适用场景

以下任务必须使用本 skill：

- 新增 Pydantic schema
- 修改 PostRecord
- 修改 CommentRecord
- 修改 InsightRecord
- 修改 ScoreCard
- 实现平台 adapter
- 实现 SourceAgent
- 实现 NormalizeAgent
- 实现 InsightAgent
- 实现 SentimentAgent
- 实现 ScoringAgent
- 实现 ReportAgent
- 实现 pipeline 主流程
- 实现 HTML 报告生成
- 修改评分规则
- 修复 bug
- 重构已有代码
- 修改已有行为
- 增加数据清洗逻辑
- 增加证据链校验逻辑

## 例外场景

以下内容可以不强制写自动化测试，但必须有验收清单：

- CLAUDE.md
- skill 文档
- subagent 文档
- README
- 项目说明文档
- 一次性探索脚本
- 临时 mock 数据
- 纯配置文件

即使不写自动化测试，也必须说明：

- 如何人工检查
- 如何判断配置是否生效
- 是否违反 CLAUDE.md
- 是否影响主流程

## 铁律

核心业务代码必须遵守：

```text
没有失败测试，不写生产代码。
没有验收标准，不认为任务完成。