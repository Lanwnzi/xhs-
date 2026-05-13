---
name: delegation
description: 当已经有明确设计、任务计划和验收标准，需要进入具体实现、代码审查、规范审查、计划审查或多 Agent 协作时，必须使用本 skill。本 skill 负责判断是否委派 developer-agent、plan-reviewer、spec-compliance-reviewer、code-quality-reviewer，并规定每个任务必须经过实现、自检、规范审查和代码质量审查。
---

# Delegation

## 核心定位

本 skill 用于执行已经拆解好的开发任务。

它不是用来做需求设计，也不是用来拆 backlog。

它负责回答：

- 当前任务是否足够清晰，可以交给 subagent？
- 应该委派给哪个 subagent？
- subagent 需要哪些上下文？
- 实现后应该如何 review？
- review 不通过时应该如何返工？
- 什么时候才能标记任务完成？

本项目是一个多源 UGC 市场验证系统，核心闭环为：

collect -> normalize -> analyze -> score -> render_report

所有委派任务都必须服务于这个闭环。

## 适用场景

当出现以下情况时，必须使用本 skill：

- planning-and-backlog 已经完成
- tdd-discipline 已经明确测试或验收方式
- 用户要求开始实现代码
- 用户要求让 developer-agent 开发
- 用户要求 reviewer 检查代码
- 用户要求分配任务给不同 agent
- 任务可以拆成独立实现单元
- 需要执行多阶段开发和审查流程

## 不适用场景

以下情况不应该直接进入 delegation：

- 需求还不清楚
- 设计还没有确认
- backlog 还没有拆
- 没有测试或验收标准
- 任务边界太大
- 多个模块强耦合，无法单独实现
- 用户只是询问概念，不需要改代码

这种情况下应回到：

- design-and-discovery
- planning-and-backlog
- tdd-discipline

## 核心原则

### 1. 一个任务，一个 fresh subagent

每个具体实现任务都应该交给一个新的 subagent。

原因：

- 避免上下文污染
- 避免把前一个任务的假设带到下一个任务
- 保证任务聚焦
- 保证 reviewer 能独立判断

错误做法：

- 让一个 developer-agent 一次性完成所有模块
- 让 developer-agent 自己决定需求边界
- 让 developer-agent 继承大量无关上下文

正确做法：

- controller 先整理任务上下文
- 每次只委派一个清晰任务
- 每个任务都提供必要文件、目标、输入输出和验收标准

### 2. 先规范审查，再代码质量审查

每个实现任务完成后，必须按顺序审查：

1. spec-compliance-reviewer
2. code-quality-reviewer

不能反过来。

原因：

- 先确认有没有做对
- 再确认代码写得好不好

如果功能方向都错了，代码质量再好也没有意义。

### 3. reviewer 发现问题必须返工

如果 reviewer 发现问题，不能直接跳过。

流程必须是：

1. reviewer 指出问题
2. developer-agent 修复
3. reviewer 重新审查
4. 直到通过
5. 才能标记任务完成

禁止：

- “差不多就行”
- “这个问题后面再说”
- “先继续下一个任务”
- “reviewer 只是建议，不用改”

### 4. developer-agent 的自检不能代替 reviewer

developer-agent 必须自检，但自检不是最终审查。

必须仍然经过：

- spec-compliance-reviewer
- code-quality-reviewer

### 5. 不要多个实现 subagent 并行改同一批文件

本项目初期不要并行委派多个实现任务。

尤其以下文件容易冲突：

- src/schemas/records.py
- src/pipeline/run_pipeline.py
- src/agents/*
- src/scoring/*
- src/reports/*
- tests/*

默认串行执行：

一个任务完成并 review 通过后，再进入下一个任务。

## 委派前检查

在委派 developer-agent 之前，必须确认：

1. 任务是否来自 planning-and-backlog？
2. 是否已经经过 design-and-discovery？
3. 是否有明确输入？
4. 是否有明确输出？
5. 是否有涉及文件？
6. 是否有测试或验收标准？
7. 是否能在 1-3 个文件内完成？
8. 是否不会破坏 Agent 职责边界？
9. 是否不会绕过 Pydantic schema？
10. 是否不会让 LLM 直接裸打分？
11. 是否不会输出无证据市场结论？

如果任意一项不清楚，应先补充上下文，而不是直接委派。

## 标准委派流程

### Step 1：读取当前任务

从 backlog 或用户指令中提取当前任务。

必须提取：

- 任务名称
- 任务目标
- 所属阶段
- 所属模块
- 依赖条件
- 涉及文件
- 输入
- 输出
- 验收方式

### Step 2：判断是否需要 subagent

判断规则：

#### 使用 developer-agent

适合：

- 写 Python 代码
- 实现 schema
- 实现 adapter
- 实现 agent
- 实现 scoring
- 实现 report
- 实现 pipeline
- 写测试

#### 使用 plan-reviewer

适合：

- 审查开发计划
- 判断任务拆解是否合理
- 判断是否过早做 P1/P2
- 判断是否存在 blocker

#### 使用 spec-compliance-reviewer

适合：

- 检查是否符合 CLAUDE.md
- 检查是否违反 Agent 分工
- 检查是否绕过 schema
- 检查是否无证据输出结论
- 检查是否让 LLM 裸打分

#### 使用 code-quality-reviewer

适合：

- 检查代码质量
- 检查重复逻辑
- 检查命名
- 检查异常处理
- 检查类型标注
- 检查测试覆盖
- 检查模块边界

### Step 3：构造 developer-agent 指令

委派 developer-agent 时，必须提供完整上下文。

指令必须包含：

```text
任务名称：
阶段：
模块：

背景：
目标：
非目标：

输入：
输出：

必须修改的文件：
可能涉及的文件：

必须遵守的规则：
- CLAUDE.md
- Pydantic schema
- Agent 职责边界
- TDD / 验收标准
- 不允许无证据市场结论
- 不允许 LLM 裸打分

验收标准：
- 

完成后输出：
- 修改文件
- 新增函数/类
- 测试结果
- 自检结果
- 风险或疑问