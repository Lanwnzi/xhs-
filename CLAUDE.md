# CLAUDE.md

## 项目名称

XHS Comment Insight Agent  
小红书评论洞察与文案选题助手

## 项目定位

本项目面向品牌运营、内容运营、产品运营和新媒体同学，基于小红书公开可见帖子与评论，自动生成用户反馈洞察与文案选题报告。

本项目不再定位为“市场验证系统”，不宣称判断市场规模、销量预测或商业可行性。

核心目标：

- 采集指定关键词下的小红书帖子与评论
- 分析用户在评论区讨论什么
- 提取用户需求、疑问、痛点、购买顾虑和负面反馈
- 识别高互动帖子和高赞评论中的内容机会
- 输出可解释的内容选题价值评分
- 生成 HTML 评论洞察报告
- 通过 FastAPI + Vue 提供可视化入口

---

## 非目标

当前阶段不做：

- 不做市场规模判断
- 不做销量预测
- 不做商业可行性结论
- 不做完整用户画像
- 不做自动发布
- 不做飞书同步
- 不做复杂推荐系统
- 不训练自有模型
- 不做大而全 UI 平台
- 不输出无证据结论
- 不让 LLM 直接生成评分
- 不让 LLM 生成 comment_id / post_id / evidence_id

---

## 阶段优先级

### P0：小红书单平台闭环

- 小红书帖子采集
- 小红书评论采集
- 数据标准化
- 评论语义分析
- 内容选题价值评分
- HTML 报告

### P1：多主题与对照验证

- 多关键词实验
- 不同品类评论洞察对比
- Reddit 或其他平台对照验证

### P2：服务化与前端展示

- FastAPI 接口
- Vue 前端
- 任务状态查询
- 报告预览
- 采集过程监控
- 历史报告查看

### P2.5：内容质量增强

- 评论标注并发化（10 并发，100 条/轮）
- LLM 引导的内容选题生成（ContentIdeationAgent 多角度协作）
- 报告选题建议去模板化

### P3：扩展能力

- 数据库持久化
- 多平台采集
- 自动发布
- 飞书同步
- 图片生成
- 多用户任务队列

---

## 数据合同

所有 Agent 输入输出必须优先使用 Pydantic 模型。

### PostRecord

字段：

- platform
- post_id
- title
- content
- author
- publish_time
- likes
- comments
- favorites
- shares
- url
- tags

说明：  
likes / comments / favorites / shares 可用于帖子互动权重。

### CommentRecord

字段：

- platform
- comment_id
- post_id
- content
- author
- publish_time
- likes
- parent_comment_id

说明：  
likes 可用于高赞评论权重。

### InsightRecord

字段：

- pain_points[]
- user_needs[]
- complaints[]
- solutions[]
- market_signals[]
- sentiment
- evidence_post_ids[]
- evidence_comment_ids[]

字段解释：

| 字段 | 当前含义 |
|---|---|
| pain_points | 用户问题 / 使用痛点 / 决策障碍 |
| user_needs | 用户需求 / 信息需求 / 想确认的问题 |
| complaints | 负面反馈 / 踩坑点 / 不满表达 |
| solutions | 用户提到的产品、品牌、渠道、方法 |
| market_signals | 内容机会信号 / 购买决策信号 / 讨论热度信号 |
| sentiment | 评论区情绪倾向 |
| evidence_post_ids | 相关帖子证据 |
| evidence_comment_ids | 相关评论证据 |

注意：  
`market_signals` 字段名保留，但报告中解释为“内容机会信号 / 购买决策信号”，不再解释为市场规模或商业机会判断。

### ScoreCard

字段：

- demand_intensity
- sentiment_friction
- solution_saturation
- purchase_intent
- freshness
- overall_score
- scoring_reason

字段解释：

| 字段 | 展示名称 |
|---|---|
| demand_intensity | 用户关注强度 |
| sentiment_friction | 负面反馈强度 |
| solution_saturation | 方案提及度 / 内容切入空间 |
| purchase_intent | 购买或行动信号 |
| freshness | 评论时效性 |
| overall_score | 内容选题价值评分 |
| scoring_reason | 评分解释 |

ScoreCard 只衡量评论区信号强度和内容选题价值，不代表市场规模、销量预测或商业可行性。

### TopicSuggestion

ContentIdeationAgent 输出的单条关键词相关内容选题建议。

字段：

- direction: str — 选题方向（如"高频关注方向""高频疑问""典型痛点"）
- title: str — 建议标题（非模板化，结合具体洞察词）
- evidence: str — 数据依据（引用真实评论或帖子内容）
- content_angle: str — 可操作的文案角度

### TitleSuggestion

ContentIdeationAgent 输出的单条热点选题与文案定制建议。

字段：

- direction: str — 选题方向（如"学习路线与入门指南""高频疑问解答""常见误区与避坑"）
- title: str — 建议标题（非模板化，结合具体洞察词和内容策略）
- evidence: str — 数据依据（引用真实评论内容、用户需求或痛点）
- content_angle: str — 具体文案角度和执行建议

### ContentIdeationResult

ContentIdeationAgent 的最终输出。

字段：

- topic_suggestions: list[TopicSuggestion] — 关键词相关内容选题建议（3-5 条）
- custom_title_suggestions: list[TitleSuggestion] — 热点选题与文案定制建议（3-5 条）
- generation_mode: str — "single_llm" | "multi_perspective"
- perspectives_used: list[str] — 实际使用的思考角度列表

---

## Agent 分工

### SourceAgent

只负责采集。

允许：

- 小红书帖子采集
- 小红书评论采集
- 保存 raw_posts.json
- 保存 raw_comments.json

禁止：

- 不做总结
- 不做评分
- 不生成报告
- 不输出市场结论

### NormalizeAgent

负责标准化。

职责：

- 字段映射
- 清洗
- 去重
- 时间标准化
- 输出 normalized_posts.json
- 输出 normalized_comments.json

禁止：

- 不做需求分析
- 不做情感判断
- 不做评分

### LLMCommentAnalyzerAgent

负责评论级语义标注。

职责：

- sentiment
- pain_point_labels
- need_labels
- complaint_labels
- solution_labels
- market_signal_labels
- intent_labels
- reason

要求：

- LLM 只生成 index、sentiment、labels、reason
- comment_id / post_id / evidence_id 由代码绑定
- LLM 不生成评分
- LLM 不判断市场规模或商业可行性

#### 并发标注规范（P2 性能优化）

当前每批 10 条串行调用 LLM，效率低。需改为并发模式：

- 使用 `concurrent.futures.ThreadPoolExecutor`（或 asyncio + 独立 event loop 线程），最大并发数 = 10
- 每个并发 worker 持有独立的 LLM client 实例（线程安全）
- 每轮并发：10 个 LLM 同时启动，每个处理 10 条数据 → 一轮处理 100 条
- 按 post_id 分组后，所有组内评论展平为全局列表，按 batch_size=10 切片
- 最后一轮动态调整：例如总共 93 条 → 前 9 轮各 10 条，最后一轮 3 条，只启动 1 个 worker
- 单 batch 失败不回滚整轮：失败 batch 记录 error log，fallback 到规则版 SentimentAgent 对该 batch 的评论做标注
- 并发轮次之间串行（上一轮全部完成后才启动下一轮），保证顺序可追溯
- 结果按原始 index 排序后写入 comment_annotations

实现要点：
- `LLMCommentAnalyzerAgent` 新增 `execute_concurrent()` 方法，保留原 `execute()` 作为兼容
- `create_annotate_comments_node` 通过参数选择串行/并发模式
- 并发模式下 max_comments 限制仍然生效（截断后并发处理）

### AnnotationAggregator

负责将评论级标注聚合为 InsightRecord。

职责：

- labels 聚合为 pain_points / user_needs / complaints / solutions / market_signals
- 聚合 sentiment
- 绑定 evidence_post_ids / evidence_comment_ids

要求：

- evidence 必须来自真实 PostRecord / CommentRecord
- 不允许凭空生成证据
- 原始评论存在但洞察为空时必须记录 warning

### InsightAgent

负责规则版洞察抽取。

要求：

- 每个洞察必须有 evidence
- 不输出市场规模、商业可行性或销量判断

### SentimentAgent

负责规则版情感分析。

说明：  
情绪只代表当前采集样本，不代表整体用户情绪。

### ScoringAgent

只负责规则评分。

要求：

- LLM 不允许直接输出总分
- 每个分数必须有 scoring_reason
- 评分应结合用户需求、购买信号、负面反馈、评论时效性、帖子互动和评论互动
- scoring_reason 不得宣称市场规模、销量预测或商业可行性

互动权重原则：

- 高互动帖子下的评论更值得关注
- 高赞评论更值得关注
- 使用 log1p 平滑，避免爆款内容完全支配评分
- 0 赞评论不应完全忽略

### ReportAgent

只负责 HTML 报告生成。

允许：

- 读取 insights.json
- 读取 scorecard.json
- 读取 raw / normalized 数据展示代表评论
- 读取 content_ideas.json（由前序节点生成）
- 读取 title_suggestions.json（由前序节点生成）
- 生成 report.html

禁止：

- 不重新计算评分
- 不重新抓取数据
- 不编造证据
- 不宣称市场验证
- 不宣称市场规模、销量预测或商业可行性
- 不自行生成选题建议（应由前序 ContentIdeationAgent 生成后传入）

---

### ContentIdeationAgent（P2 新增）

负责在报告生成前，基于洞察数据、评分结果和原始评论，通过 LLM 生成高质量的内容选题建议。

职责：

- 输入：InsightRecord、ScoreCard、NormalizedDataset、keyword
- 输出：ContentIdeationResult（Pydantic 模型）
  - topic_suggestions: list[TopicSuggestion] — 关键词相关内容选题建议
  - custom_title_suggestions: list[TitleSuggestion] — 热点选题与文案定制建议

要求：

- 每个建议必须有 evidence（来自真实评论或帖子）
- 每个建议必须有 content_angle（具体可操作的文案方向）
- 标题不能是模板化套话，必须结合具体洞察词
- 不输出市场规模、商业可行性判断
- 不编造不存在的评论或数据
- LLM 不生成 evidence_id（由代码绑定）

#### 多角度 LLM 协作模式

ContentIdeationAgent 支持两种运行模式：

**模式 A：单 LLM 综合生成（默认）**
- 一次 LLM 调用，综合所有数据生成 topic_suggestions 和 custom_title_suggestions
- 适合评论量较少（< 50 条）的场景

**模式 B：多角度并行生成（推荐，评论量 ≥ 50 条时启用）**
- 启动 3-5 个 LLM，每个从不同角度思考选题：
  1. **用户痛点角度** — 聚焦 pain_points / complaints，生成避坑、对比、解决方案类选题
  2. **内容创作者角度** — 聚焦 user_needs / market_signals，生成教程、指南、答疑类选题
  3. **搜索与流量角度** — 聚焦高频疑问词和搜索意图，生成 SEO 友好、问答类选题
  4. **热点与趋势角度** — 聚焦高互动帖子和时效性信号，生成热点跟进类选题
  5. **产品与购买角度** — 聚焦 purchase_intent / solutions，生成测评、推荐、清单类选题
- 每个角度输出独立的选题列表
- 合并去重：按 title 相似度去重，保留 evidence 最丰富的版本
- 最终输出 topic_suggestions（3-5 条）和 custom_title_suggestions（3-5 条）

实现要点：
- 角度 4 和 5 为可选（当对应数据不足时跳过）
- 每个角度使用独立 LLM client，并发调用
- 合并策略在代码中执行，不依赖 LLM

---

## 默认工作流

当前正式主工作流由 LangGraph 编排。

rule 模式：

collect -> normalize -> sentiment -> insight -> score -> ideate_content -> render_report

llm_annotation 模式：

collect -> normalize -> annotate_comments -> sentiment_from_annotations -> insight_from_annotations -> score -> ideate_content -> render_report

其中 ideate_content 节点（P2 新增）：
- 调用 ContentIdeationAgent，基于前序数据生成高质量选题建议
- 输出 content_ideation_result 写入 state（UGCGraphState 新增字段：content_ideation_result: Optional[ContentIdeationResult]）
- ReportAgent 的 _build_topic_suggestions 和 _build_custom_title_suggestions 改为从 state 读取预生成结果，不再内部拼凑模板
- content_ideation_result 同时持久化为 outputs/content_ideation.json

说明：

- LangGraph 是主工作流
- Pipeline 仅保留为早期 MVP / baseline / 兼容入口
- FastAPI 必须调用 LangGraph，不调用 Pipeline 作为主流程
- ideate_content 节点在两种模式下均插入在 score 与 report 之间

禁止：

- SourceAgent 写业务总结
- ReportAgent 重新计算评分
- 跳过 NormalizeAgent
- 无证据输出结论
- 输出“市场验证成功”“市场机会巨大”等夸大结论

---

## FastAPI 规范

FastAPI 是对外服务入口，主链路：

POST /api/xhs/analyze  
-> 创建 job  
-> data/jobs/{keyword_slug}/{run_id}/  
-> XhsPlaywrightAdapter  
-> LangGraph  
-> ReportAgent  
-> GET /api/reports/{job_id}

要求：

- 每个 job 独立目录
- 不同关键词不互相覆盖
- 同一关键词多次运行不覆盖历史结果
- Playwright Sync API 必须在独立线程中执行
- 不允许在 FastAPI asyncio event loop 中直接调用 sync_playwright
- 不在日志或前端暴露 API key / cookie / token

Job 目录必须包含：

- raw/raw_posts.json
- raw/raw_comments.json
- normalized/normalized_posts.json
- normalized/normalized_comments.json
- outputs/insights.json
- outputs/scorecard.json
- outputs/comment_annotations.json（llm_annotation 模式）
- outputs/content_ideation.json（P2 新增）
- outputs/report.html

推荐调试产物：

- progress.json
- events.json
- snapshots/latest.png

---

## Vue 前端规范

前端是轻量操作入口。

允许：

- 输入关键词
- 设置采集数量
- 提交任务
- 查看任务状态
- 预览报告
- 展示采集日志
- 展示最新截图
- 展示实时采集评论

禁止：

- 不写死 API key
- 不处理 LLM_API_KEY
- 不直接访问小红书
- 不直接调用 LLM
- 不做自动发布
- 不做飞书同步
- 不做复杂多平台分析
- 不做大而全 UI 平台

前端标题使用：

- 小红书评论洞察与文案选题助手
- 或 XHS Comment Insight Agent

避免使用：

- Market Validator
- 市场验证系统
- 市场机会预测

---

## 报告规范

HTML 报告标题：

小红书评论区用户反馈与文案选题报告

报告必须包含：

1. 采集概览
2. 评论区讨论摘要
3. 用户核心关注点
4. 用户高频疑问
5. 高互动内容信号
6. 正负向反馈总结
7. 购买 / 行动信号
8. 关键词相关内容选题建议（由 ContentIdeationAgent 预生成，ReportAgent 渲染）
9. 热点选题与文案定制建议（由 ContentIdeationAgent 预生成，ReportAgent 渲染）
10. 代表评论证据
11. 内容选题价值评分
12. 数据局限说明

第 8、9 节生成规范：

- 不再由 ReportAgent 内部 `_build_topic_suggestions()` / `_build_custom_title_suggestions()` 拼凑模板文字
- 改为由前序 `ideate_content` 节点调用 ContentIdeationAgent 生成，结果写入 state
- ReportAgent 读取 `content_ideation_result`，渲染为 HTML
- 多角度模式下，每条建议标注来源角度（如"用户痛点视角""内容创作者视角"）
- 每个选题建议必须包含：direction / title / evidence / content_angle
- title 不得使用模板化套话（如"关于XX，你不得不知道的几件事"），必须结合具体洞察词
- evidence 必须引用真实评论内容或洞察数据

报告必须说明：

本报告基于小红书搜索结果与可见评论区内容自动生成，仅用于辅助用户反馈分析和内容选题参考，不代表完整市场规模、整体用户画像、真实销量或商业可行性结论。平台推荐机制、关键词选择、采集数量、帖子互动差异和可见评论范围都会影响分析结果。

报告禁止：

- 不得宣称市场规模
- 不得宣称销量预测
- 不得宣称商业可行性
- 不得输出无证据结论
- 不得把评论区样本当作整体市场结论

---

## Claude Code 工作方式

开发任务默认遵循：

1. design-and-discovery：明确需求边界
2. planning-and-backlog：拆解任务
3. tdd-discipline：先写测试或验收标准
4. developer-agent：实现代码
5. spec-compliance-reviewer：检查是否符合 CLAUDE.md
6. code-quality-reviewer：检查代码质量
7. forensic-debugging：排查问题
8. evidence-verification：检查证据链

任何涉及定位、字段、评分、报告或工作流变化的任务，必须先过 plan-reviewer。

---

## 编码规则

- Python 负责编排、接口、Prompt、报告生成
- LangGraph 负责主工作流编排
- FastAPI 负责服务化接口
- Vue 负责前端展示
- 所有 Agent 输入输出必须优先使用 Pydantic 模型
- 新增平台必须先实现 adapter，再接入主流程
- 新字段必须先更新 schema，再改 Agent 逻辑
- 不允许绕过 schema 直接传 dict 到下游
- 不允许硬编码平台私有字段
- 不允许把 API key、cookie、token 写入日志、报告或调试产物
- 不允许 LLM 直接输出评分
- 不允许 LLM 生成 evidence_id
- 不允许无证据输出结论
- 并发 LLM 调用必须使用独立 client 实例，禁止多线程共享同一个 client
- ContentIdeationAgent 的输出必须经过 evidence 校验（引用的评论/帖子必须存在于原始数据中）

---

## 产物规范

CLI / 默认 data 目录模式：

- data/raw/raw_posts.json
- data/raw/raw_comments.json
- data/normalized/normalized_posts.json
- data/normalized/normalized_comments.json
- data/outputs/insights.json
- data/outputs/scorecard.json
- data/outputs/comment_annotations.json（llm_annotation 模式）
- data/outputs/content_ideation.json（P2 新增，ContentIdeationResult）
- data/outputs/report.html

FastAPI job 模式：

- data/jobs/{keyword_slug}/{run_id}/raw/raw_posts.json
- data/jobs/{keyword_slug}/{run_id}/raw/raw_comments.json
- data/jobs/{keyword_slug}/{run_id}/normalized/normalized_posts.json
- data/jobs/{keyword_slug}/{run_id}/normalized/normalized_comments.json
- data/jobs/{keyword_slug}/{run_id}/outputs/insights.json
- data/jobs/{keyword_slug}/{run_id}/outputs/scorecard.json
- data/jobs/{keyword_slug}/{run_id}/outputs/comment_annotations.json
- data/jobs/{keyword_slug}/{run_id}/outputs/content_ideation.json（P2 新增）
- data/jobs/{keyword_slug}/{run_id}/outputs/report.html

---

## 质量门禁

每次实现后必须检查：

- 是否符合 Pydantic schema
- 是否有测试或最小验收脚本
- 是否能生成核心产物
- 是否存在无证据结论
- 是否存在 Agent 职责越界
- 是否仍然使用 LangGraph 作为主工作流
- 是否避免市场规模或商业可行性夸大表达
- 是否保护 API key / cookie / token
- 是否保留数据局限说明
- 是否不破坏 CLI / FastAPI / 前端主链路
- 并发标注：是否每个 worker 持有独立 LLM client，失败 batch 是否正确 fallback
- 内容选题：ContentIdeationAgent 输出的 evidence 是否可追溯到原始数据
- 内容选题：标题是否避免了模板化套话

---

## 验收标准

后端基础验收：

```bash
python -m compileall src scripts
pytest tests/ -v
python scripts/acceptance_check.py