---
name: planning-and-backlog
description: 当设计方案已经明确，用户希望开始落地实现、拆解开发任务、安排优先级、组织 backlog、确定里程碑、划分阶段或准备进入编码时，必须使用本 skill。本 skill 用于把经过确认的设计转化为可执行的任务清单、开发顺序、依赖关系、验收标准和阶段目标，禁止在没有计划的情况下直接进入大规模实现。
---

# Planning and Backlog

## 核心定位

本 skill 用于把已经确认的设计方案，拆解成可执行的开发计划和 backlog。

它负责回答以下问题：

- 现在到底先做什么？
- 任务应该如何拆分？
- 哪些任务必须先完成？
- 哪些任务可以后做？
- 哪些任务属于 P0 / P1 / P2？
- 每个任务的完成标准是什么？
- 下一步应该交给哪个 agent 或 skill？

本项目是一个多源 UGC 市场验证系统，核心闭环为：

collect -> normalize -> analyze -> score -> render_report

所有计划拆解都必须围绕这个闭环进行。

## 适用场景

当出现以下情况时，必须使用本 skill：

- design-and-discovery 已完成，准备进入开发
- 用户说“下一步怎么做”
- 用户说“帮我拆一下开发计划”
- 用户说“帮我列 backlog”
- 用户说“先做哪些模块”
- 用户说“从 0-1 怎么搭”
- 用户说“帮我安排开发顺序”
- 用户说“帮我拆分迭代”
- 用户说“帮我规划 P0 / P1 / P2”
- 用户说“这个系统先实现哪一部分”

## 最高优先级规则

在完成计划拆解之前，禁止：

- 一次性铺开实现所有模块
- 无优先级地同时开发多个核心模块
- 在没有依赖分析的情况下直接调用 developer-agent 大量写代码
- 跳过 P0 直接做 P1 / P2
- 把大任务原样丢给实现阶段
- 没有验收标准就开始开发

如果用户明确要求“直接开始写代码”，也应先给出一个最小任务计划，然后再进入实现。

## 计划拆解前必须满足的条件

进入 planning-and-backlog 之前，应尽量满足以下条件：

- 已通过 design-and-discovery 明确目标
- 已明确非目标
- 已明确输入输出
- 已明确关键模块边界
- 已有推荐方案
- 用户已确认方案或默认接受推荐方案

如果这些条件不满足，应先返回 design-and-discovery，而不是强行拆任务。

## 本项目的计划原则

### 1. 始终优先最小闭环

本项目的计划拆解优先级固定为：

### P0
- mock 数据闭环
- 小红书采集
- 评论分析
- ScoreCard
- HTML 报告

### P1
- Reddit 对照验证
- 多平台比较

### P2
- 飞书同步
- 发布能力
- 图片生成

如果 P0 没有完成，原则上不能把主要精力放在 P1 / P2。

### 2. 先基础合同，再业务逻辑

开发顺序优先考虑：

1. 项目结构
2. CLAUDE.md
3. schema
4. adapter
5. agents
6. pipeline
7. scoring
8. report
9. tests
10. 优化和扩展

禁止先写报告、后补 schema。

禁止先写复杂 Agent、后补数据合同。

### 3. 先串行依赖，后并行优化

必须先识别依赖关系。

例如：

- 没有 schema，不能稳定实现 Agent
- 没有 normalized data，不能稳定做 insight
- 没有 insight 和 sentiment，不能稳定评分
- 没有 scorecard，不能稳定生成 report

所以很多核心任务必须串行，而不是并行硬做。

### 4. 每个任务必须足够小

任务拆解后，每个任务都应该足够具体，最好满足：

- 能说明输入
- 能说明输出
- 能说明涉及文件
- 能说明完成条件
- 能说明是否需要测试

错误示例：

- “完成市场分析系统”
- “实现全部 Agent”
- “做完报告”

正确示例：

- “定义 PostRecord / CommentRecord / InsightRecord / ScoreCard 四个 Pydantic 模型”
- “实现 mock 数据读取器并输出 raw_posts.json”
- “实现 NormalizeAgent，把 mock 原始数据转成 normalized_posts.json”
- “实现 ScoreCard 规则函数并生成 scorecard.json”
- “实现 report.html 模板渲染”

## 标准拆解流程

### 第一步：明确当前阶段

先判断当前任务属于：

- P0
- P1
- P2

再判断当前重点属于哪个模块：

- docs
- schema
- adapter
- agent
- pipeline
- scoring
- report
- tests
- config

### 第二步：识别里程碑

对于本项目，常见里程碑可以定义为：

#### 里程碑 M1：项目骨架完成
- 项目目录建立
- CLAUDE.md 建立
- skills / agents 建立
- 基础依赖准备

#### 里程碑 M2：数据合同完成
- PostRecord
- CommentRecord
- InsightRecord
- ScoreCard
- 输入输出约束明确

#### 里程碑 M3：mock 闭环跑通
- raw_posts.json
- normalized_posts.json
- insights.json
- scorecard.json
- report.html

#### 里程碑 M4：小红书真实数据接入
- xhs adapter
- SourceAgent 接入
- 评论采集
- 与 normalize 流程对接

#### 里程碑 M5：多平台扩展
- Reddit adapter
- 多平台比较
- 平台间分析对照

### 第三步：把里程碑拆成任务

每个里程碑都要拆成更小任务。

例如 M3 mock 闭环可以拆成：

1. 创建 mock 输入数据
2. 实现 raw 数据加载
3. 实现 NormalizeAgent
4. 实现 InsightAgent
5. 实现 SentimentAgent
6. 实现 ScoringAgent
7. 实现 ReportAgent
8. 增加最小验证脚本
9. 验证 5 个产物均可生成

### 第四步：识别依赖关系

每个任务都要标注依赖关系。

例如：

- 实现 NormalizeAgent
  - 依赖：schema 完成、mock 数据存在

- 实现 InsightAgent
  - 依赖：NormalizeAgent 可输出标准化数据

- 实现 ScoringAgent
  - 依赖：InsightAgent 和 SentimentAgent 输出可用

- 实现 ReportAgent
  - 依赖：insights.json 和 scorecard.json 可生成

### 第五步：定义验收标准

每个任务必须能被判断“是否完成”。

例如：

任务：定义 ScoreCard schema  
验收标准：
- 存在 `src/schemas/records.py`
- 包含指定字段
- 能通过 import
- 能完成实例化

任务：实现 ReportAgent  
验收标准：
- 能读取 scorecard.json 和 insights.json
- 能输出 `data/outputs/report.html`
- HTML 中包含报告规范要求的字段

## backlog 输出规范

输出 backlog 时，建议按以下层级组织：

### 一级：阶段
- P0 / P1 / P2

### 二级：里程碑
- M1 / M2 / M3 ...

### 三级：任务
- T1 / T2 / T3 ...

### 四级：验收项
- A1 / A2 / A3 ...

## 标准输出格式

当用户要求拆计划时，使用以下格式：

```text
当前判断：
- 阶段：
- 当前目标：
- 是否已完成设计确认：

推荐开发顺序：
1. 
2. 
3. 

里程碑拆解：

M1：
- 目标：
- 任务：
  - T1：
  - T2：
  - T3：
- 依赖：
- 验收标准：

M2：
- 目标：
- 任务：
  - T1：
  - T2：
  - T3：
- 依赖：
- 验收标准：

M3：
- 目标：
- 任务：
  - T1：
  - T2：
  - T3：
- 依赖：
- 验收标准：

当前建议先做：
- 

原因：
- 

是否进入 tdd-discipline 或 delegation：
- 