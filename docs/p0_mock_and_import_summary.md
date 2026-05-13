# P0 阶段实现成果总结

## 1. 项目当前目标

一句话概括：搭建多源 UGC 市场验证系统的基础框架，已实现 P0 mock 数据闭环 + XhsImportAdapter 本地导入能力。系统已完成"采集 -> 标准化 -> 分析（情感 + 洞察）-> 评分 -> 报告生成"的完整工作流闭环，支持两种数据来源模式。

---

## 2. 已实现模块

### 2.1 Pydantic 模型（11 个）

定义于 `src/schemas/records.py`，`src/schemas/__init__.py` 统一导出。

| 模型 | 用途 |
|---|---|
| `PostRecord` | 来自任意平台的单条 UGC 帖子。包含 platform、post_id、title、content、author、publish_time、likes、comments、favorites、shares、url、tags |
| `CommentRecord` | 附属于帖子的一条评论。包含 platform、comment_id、post_id、content、author、publish_time、likes、parent_comment_id |
| `InsightRecord` | 从标准化数据中提取的结构化洞察。每个列表条目必须至少有一个证据 ID 作为支撑。包含 pain_points、user_needs、complaints、solutions、market_signals、sentiment、evidence_post_ids、evidence_comment_ids |
| `ScoreCard` | 基于规则驱动的市场评分结果。所有维度分数为 [0, 1] 范围的浮点数。包含 demand_intensity、sentiment_friction、solution_saturation、purchase_intent、freshness、overall_score、scoring_reason |
| `AnalysisRequest` | 一次完整市场验证运行的输入参数（topic、product_direction、industry_question） |
| `RawDataset` | 标准化前的原始数据容器（posts、comments） |
| `NormalizedDataset` | 清洗/映射后的标准化数据容器（posts、comments） |
| `PostSentiment` | 单条帖子的情感分析结果（post_id、label、score），label 可选值 positive / negative / neutral |
| `CommentSentiment` | 单条评论的情感分析结果（comment_id、label、score），label 可选值 positive / negative / neutral |
| `SentimentResult` | 聚合后的情感分析输出（overall_sentiment、post_sentiments、comment_sentiments） |
| `ReportResult` | 报告生成的输出结果（success、report_path） |

### 2.2 工具层模块

| 文件 | 模块名 | 说明 |
|---|---|---|
| `src/__init__.py` | 包标识 | 仅包含 "UGC Market Validator" 项目名称注释 |
| `src/utils.py` | 工具函数 | `find_project_root()` 从当前文件所在目录向上遍历寻找同时包含 `src/` 和 `data/` 的根目录；`AppPaths` dataclass 统一集中管理 7 个产物路径；`get_app_paths()` 返回全局共享单例 |
| `src/keywords.py` | 关键词集合 | 集中管理情感分析和洞察提取所使用的所有关键词，消除 agent 之间的重复定义。包含 POSITIVE_KEYWORDS（30 个）、NEGATIVE_KEYWORDS（55 个）、PAIN_POINT_KEYWORDS（29 个）、USER_NEED_KEYWORDS（17 个）、COMPLAINT_KEYWORDS（22 个）、SOLUTION_KEYWORDS（17 个）、MARKET_SIGNAL_KEYWORDS（15 个） |

### 2.3 Adapter 层模块

| 文件 | 类 | 说明 |
|---|---|---|
| `src/adapters/base.py` | `BaseAdapter`（ABC） | 平台采集适配器的抽象基类，定义两个抽象方法：`fetch_posts(self, keyword: str, max_count: int = 20) -> list[dict]` 和 `fetch_comments(self, post_id: str, max_count: int = 50) -> list[dict]` |
| `src/adapters/xhs_import_adapter.py` | `XhsImportAdapter(BaseAdapter)` | 从本地 JSON 文件读取小红书数据的适配器。维护 `_POST_FIELD_MAP`（17 个 XHS 字段到 PostRecord 字段的映射）和 `_COMMENT_FIELD_MAP`（14 个映射）。`_normalize_xhs_time()` 支持 Unix 时间戳、ISO 8601、数字字符串等多种时间格式。`fetch_posts()` 按 keyword 做标题/内容简单过滤。支持两种 JSON 结构：含 "posts"/"comments" 顶层键的对象，或纯数组（仅帖子）。 |
| `src/adapters/__init__.py` | 包模块 | 导出 `BaseAdapter` 和 `XhsImportAdapter` |

### 2.4 五个 Agent

#### SourceAgent（`src/agents/source_agent.py`）

docstring 描述："负责采集原始 UGC 数据的 Agent。"
- 接收可选的 adapter 参数；有 adapter 时从 adapter 获取数据，否则从本地 mock JSON 文件读取
- `execute(request: AnalysisRequest) -> RawDataset`
- 将原始字典通过 `PostRecord(**p)` / `CommentRecord(**c)` 校验为 Pydantic 模型
- 持久化到 `data/raw/raw_posts.json` 和 `data/raw/raw_comments.json`

#### NormalizeAgent（`src/agents/normalize_agent.py`）

docstring 描述："负责清洗和标准化原始 UGC 数据的 Agent。"
- `execute(dataset: RawDataset) -> NormalizedDataset`
- 执行：去除内容字段首尾空白、移除空白内容记录、按 ID 去重、时间标准化为 ISO 8601、清理孤立评论
- 持久化到 `data/normalized/normalized_posts.json` 和 `data/normalized/normalized_comments.json`

#### SentimentAgent（`src/agents/sentiment_agent.py`）

docstring 描述："负责基于关键词的情感分类的 Agent。"
- `execute(dataset: NormalizedDataset) -> SentimentResult`
- 评论级：使用 POSITIVE_KEYWORDS / NEGATIVE_KEYWORDS 匹配计数，输出 positive / negative / neutral
- 帖子级：基于评论的情感按多数标签聚合
- 整体级：从所有评论情感聚合整体情感

#### InsightAgent（`src/agents/insight_agent.py`）

docstring 描述："负责从 UGC 数据中提取结构化洞察的 Agent。"
- `execute(dataset: NormalizedDataset, sentiment: SentimentResult) -> InsightRecord`
- 扫描帖子和评论，匹配 5 类洞察关键词（pain_points、user_needs、complaints、solutions、market_signals）
- 每条洞察收集证据 post_ids 和 comment_ids
- 持久化到 `data/outputs/insights.json`

#### ScoringAgent（`src/agents/scoring_agent.py`）

docstring 描述："负责基于规则的市场评分的 Agent。"
- `execute(insight: InsightRecord, dataset: NormalizedDataset, sentiment: SentimentResult) -> ScoreCard`
- 调用 `src/scoring/rules.py` 中的 6 个纯规则函数计算各维度分数
- 持久化到 `data/outputs/scorecard.json`

### 2.5 评分规则函数（6 个）

定义于 `src/scoring/rules.py`。

| 函数 | 规则逻辑 |
|---|---|
| `calc_demand_intensity(insight)` | 每个 user_need 加 0.15（上限 0.6），每个 market_signal 加 0.1（上限 0.4），总分上限 1.0 |
| `calc_sentiment_friction(insight, sentiment)` | 负面情感加 0.4、中性加 0.2、正面加 0.0；每个 complaint 或 pain_point 加 0.05（上限 0.6），总分上限 1.0 |
| `calc_solution_saturation(insight)` | 0 个为 0.0；1-2 为 0.2；3-4 为 0.5；5-7 为 0.7；8+ 为 0.9 |
| `calc_purchase_intent(insight)` | 每个购买相关关键词（`_PURCHASE_KEYWORDS` 集合共 16 个词）+0.2，上限 1.0 |
| `calc_freshness(dataset)` | 按最新帖子发布时间距今天数：1 月内 1.0；3 月内 0.8；6 月内 0.5；12 月内 0.2；更早 0.1；无帖子返回 0.1 |
| `calc_overall(...)` | 加权平均：需求强度 0.30 + 负面摩擦 0.25 + 方案饱和 0.15 + 购买意向 0.20 + 时效性 0.10，生成 scoring_reason 文本 |

### 2.6 报告生成能力

`ReportAgent`（`src/reports/report_agent.py`）docstring 描述："负责生成 HTML 市场验证报告的 Agent。"

- `execute(insight, scorecard, dataset, topic, product_direction) -> ReportResult`
- 生成内联 CSS 的自包含 HTML 报告，包含 CLAUDE.md 要求的全部 10 个章节：
  1. 项目主题（主题词、产品方向、数据来源、帖子数和评论数）
  2. 评分总览（综合评分数值、等级标签、等级说明文字）
  3. 评分拆解（5 个维度 + 综合评分行的表格，含分数颜色和评分依据）
  4. 用户需求（user_needs 关键词标签列表）
  5. 负面反馈（complaints + pain_points 合并去重标签列表）
  6. 替代方案（solutions 关键词标签列表）
  7. 高频关键词（TOP 10 关键词频次排名，含频次进度条）
  8. 代表性证据（最多 3 条证据帖子和最多 5 条证据评论的卡片展示）
  9. 建议切入点（基于评分和洞察的策略建议）
  10. 风险提示（基于评分和洞察的风险警告）
- 用户原文使用 `html.escape()` 转义
- 辅助函数：`_derive_topic()`、`_dedup_ordered()`、`_compute_keyword_freq()`、`_collect_evidence()`、`_extract_reason()`、`_generate_suggestions()`、`_generate_risk_warnings()`

### 2.7 流程编排

`Pipeline`（`src/pipeline/pipeline.py`）docstring 描述："UGC Market Validator 工作流的编排器。"

- 按 CLAUDE.md 默认顺序编排：`collect -> normalize -> analyze (sentiment -> insight) -> score -> render_report`
- 构造函数支持所有 Agent 的依赖注入（adapter、source_agent、normalize_agent、sentiment_agent、insight_agent、scoring_agent、report_agent）
- 执行结果由 `PipelineResult` 模型记录，包含 7 个产物路径、success 标志、error_message
- 每个阶段记录摘要统计信息

### 2.8 脚本工具

| 文件 | 功能 |
|---|---|
| `scripts/acceptance_check.py` | 验收检查脚本，运行 5 大类 17 项检查。检查函数包括：`check_core_artifacts_exist()`（C1）、`check_evidence_artifacts_exist()`（C2）、`check_normalized_posts_schema()`（C3a）、`check_normalized_comments_schema()`（C3b）、`check_insights_schema()`（C3c）、`check_scorecard_schema()`（C4）、`check_report_html()`（C5） |
| `scripts/run_xhs_import_pipeline.py` | XhsImportAdapter 导入模式运行脚本。初始化 adapter -> 运行完整 Pipeline -> 打印各步骤统计摘要 -> 自动调用 acceptance_check.py 验收 |

---

## 3. 两种运行模式

### 模式一：默认 mock/raw 模式

- `SourceAgent` 无 adapter 时从 `data/raw/raw_posts.json` 和 `data/raw/raw_comments.json` 读取原始数据（字典列表）
- `_execute_with_mock_files()` -> `_load_files()` -> `_assemble()` 将原始字典通过 `PostRecord(**p)` / `CommentRecord(**c)` 校验为 Pydantic 模型
- 走完整 pipeline 流程（normalize -> sentiment -> insight -> score -> report）

### 模式二：XhsImportAdapter 本地导入模式

- `SourceAgent` 注入 `XhsImportAdapter`，从本地 JSON 文件（默认 `data/raw/xhs_export.json`）读取
- `XhsImportAdapter._parse_posts()` / `_parse_comments()` 通过 `_map_fields(raw, field_map)` 执行 XHS 私有字段到标准字段的映射，`_normalize_xhs_time()` 自动处理多种时间格式
- 自动按 `post_id` 为每条帖子拉取评论
- 走完整 pipeline 流程

---

## 4. 两种运行命令

```
# Mock/raw 模式（从 data/raw/raw_posts.json 和 raw_comments.json 读取）
python src/pipeline/pipeline.py

# XhsImportAdapter 导入模式（从 data/raw/xhs_export.json 导入）
python scripts/run_xhs_import_pipeline.py

# 验收检查（独立运行，检查已生成的产物）
python scripts/acceptance_check.py
```

---

## 5. 核心产物路径

根据 `AppPaths`（定义于 `src/utils.py` 第 32-70 行）配置，5 个核心产物 + 2 个证据链文件：

| 产物类型 | 路径 | AppPaths 字段 |
|---|---|---|
| 原始帖子（核心） | `data/raw/raw_posts.json` | `raw_posts_file` |
| 原始评论（证据链） | `data/raw/raw_comments.json` | `raw_comments_file` |
| 标准化帖子（核心） | `data/normalized/normalized_posts.json` | `normalized_posts_file` |
| 标准化评论（证据链） | `data/normalized/normalized_comments.json` | `normalized_comments_file` |
| 洞察结果（核心） | `data/outputs/insights.json` | `insights_file` |
| 评分结果（核心） | `data/outputs/scorecard.json` | `scorecard_file` |
| HTML 报告（核心） | `data/outputs/report.html` | `report_file` |

`AppPaths` 还包含目录字段：`project_root`、`raw_dir`、`normalized_dir`、`outputs_dir`。所有路径通过 `get_app_paths()` 全局单例访问，由 `find_project_root()` 自动计算项目根目录（依据是同时包含 `src/` 和 `data/` 目录的父目录）。

---

## 6. 验收结果

验收脚本 `scripts/acceptance_check.py` 包含 5 大类 17 项检查：

| 类别 | 检查内容 | 项数 | 说明 |
|---|---|---|---|
| C1 | 5 个核心产物存在性 | 5 项 | 检查原始帖子、标准化帖子、洞察结果、评分结果、HTML 报告文件是否存在于磁盘 |
| C2 | 2 个证据链文件存在性 | 2 项 | 检查原始评论、标准化评论文件是否存在 |
| C3a | 标准化帖子 Pydantic 校验 | 1 项 | `normalized_posts.json` 为数组、非空、每条记录通过 `PostRecord(**item)` 校验 |
| C3b | 标准化评论 Pydantic 校验 | 1 项 | `normalized_comments.json` 为数组、非空、每条记录通过 `CommentRecord(**item)` 校验 |
| C3c | 洞察结果校验 + 证据链 | 1 项 | `insights.json` 通过 `InsightRecord(**data)` 校验，且 `evidence_post_ids` 和 `evidence_comment_ids` 至少一项非空 |
| C4 | 评分结果校验 | 1 项 | `scorecard.json` 通过 `ScoreCard(**data)` 校验，6 个维度字段完整（demand_intensity、sentiment_friction、solution_saturation、purchase_intent、freshness、overall_score），scoring_reason 非空 |
| C5 | HTML 报告完整性 | 6 项 | report.html 存在、非空、大于 1KB、包含 10 个必需章节（项目主题、评分总览、评分拆解、用户需求、负面反馈、替代方案、高频关键词、代表性证据、建议切入点、风险提示），包含 DOCTYPE、html、head、body 等 HTML 结构标签 |

**当前结果：17/17 通过**。

---

## 7. 未实现内容

- 真实小红书爬虫（cookie 管理、签名算法、反爬对抗、IP 代理）
- Reddit 平台对照验证（未实现 `RedditAdapter(BaseAdapter)`）
- 飞书/钉钉自动同步（P2 功能）
- 自动发布能力（P2 功能）
- 图片/可视化生成（P2 功能）
- 自训练 NLP 模型（P2+ 功能）
- 复杂推荐系统（非目标）
- UI 大而全平台（非目标）

---

## 8. 当前架构优势

- **Pydantic 数据合同**：全链路 11 个 Pydantic 模型确保类型安全，所有 Agent 输入输出经过校验，不传递未校验的原始 dict。
- **Adapter 解耦**：新增平台只需实现 `BaseAdapter` 的两个抽象方法（`fetch_posts`、`fetch_comments`），已有的 `SourceAgent` 和 `Pipeline` 无需修改。
- **Pipeline 依赖注入**：所有 Agent 均可在 Pipeline 构造函数中替换（`source_agent`、`normalize_agent`、`sentiment_agent`、`insight_agent`、`scoring_agent`、`report_agent`），便于 mock、独立测试和 A/B 对比。
- **AppPaths 统一配置**：7 个产物路径集中由 `AppPaths` dataclass 管理，`find_project_root()` 自动发现项目根目录，消除路径硬编码和重复计算。
- **证据链**：每条洞察条目有对应的 `evidence_post_ids` 和 `evidence_comment_ids`，可溯源到原始帖子/评论，符合 CLAUDE.md "没有 evidence 不允许输出结论"的要求。
- **规则评分**：6 个纯规则评分函数（确定性打分，不依赖 LLM），每个分数有 `scoring_reason` 解释计算过程，结果可审计可复现。
- **关键词集中管理**：情感关键词（POSITIVE/NEGATIVE）和洞察关键词（PAIN_POINT/USER_NEED/COMPLAINT/SOLUTION/MARKET_SIGNAL）统一在 `src/keywords.py` 中定义，消除 agent 之间的重复。

---

## 9. 下一阶段建议

- 扩充本地真实样本数据集，覆盖更多产品方向和品类
- 校准评分规则权重（`_DEMAND_WEIGHT`、`_FRICTION_WEIGHT` 等），根据实际市场反馈调整
- 增强洞察抽取精度，引入 NER 或分类模型补充关键词匹配
- 设计真实 XHS adapter，处理 cookie 管理、签名算法、反爬策略
- 实现 `RedditAdapter(BaseAdapter)`，接入多平台对照验证

---

## 附录：项目目录树

```
ugc-market-validator/
├── CLAUDE.md
├── docs/
│   └── p0_mock_and_import_summary.md
├── data/
│   ├── raw/
│   │   ├── raw_posts.json
│   │   ├── raw_comments.json
│   │   └── xhs_export.json
│   ├── normalized/
│   │   ├── normalized_posts.json
│   │   └── normalized_comments.json
│   └── outputs/
│       ├── insights.json
│       ├── scorecard.json
│       └── report.html
├── scripts/
│   ├── acceptance_check.py
│   └── run_xhs_import_pipeline.py
└── src/
    ├── __init__.py
    ├── utils.py
    ├── keywords.py
    ├── adapters/
    │   ├── __init__.py
    │   ├── base.py
    │   └── xhs_import_adapter.py
    ├── agents/
    │   ├── __init__.py
    │   ├── source_agent.py
    │   ├── normalize_agent.py
    │   ├── sentiment_agent.py
    │   ├── insight_agent.py
    │   └── scoring_agent.py
    ├── schemas/
    │   ├── __init__.py
    │   └── records.py
    ├── scoring/
    │   ├── __init__.py
    │   └── rules.py
    ├── reports/
    │   ├── __init__.py
    │   └── report_agent.py
    └── pipeline/
        ├── __init__.py
        └── pipeline.py
```
