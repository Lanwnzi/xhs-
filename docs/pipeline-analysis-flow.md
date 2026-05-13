# XHS Comment Insight Agent — 全流程分析说明书

本文档按 DAG（有向无环图）节点顺序，逐一说明小红书评论洞察与文案选题助手的两条分析链路。每个章节先给出该节点的**输入数据结构 + 输出数据结构**（含逐字段注释），再描述内部详细处理步骤。

---

## 总体架构

系统基于 LangGraph 构建 DAG 工作流，共有 **两条分析模式**，顶部节点相同、中间分支不同、尾部汇合：

```
                          ┌─────────────────────────────┐
                          │         collect              │
                          │        (两种模式共用)          │
                          └─────────────┬───────────────┘
                                        │
                          ┌─────────────▼───────────────┐
                          │        normalize             │
                          │        (两种模式共用)          │
                          └─────────────┬───────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                                       │
            rule 模式                                llm_annotation 模式
                    │                                       │
        ┌───────────▼───────────┐               ┌───────────▼───────────┐
        │      sentiment        │               │   annotate_comments   │
        │    (规则关键词情感)     │               │   (LLM 语义标注)       │
        └───────────┬───────────┘               └───────────┬───────────┘
                    │                                       │
        ┌───────────▼───────────┐               ┌───────────▼───────────┐
        │       insight         │               │sentiment_from_annot.  │
        │   (规则关键词洞察)      │               │  (聚合 → Sentiment)    │
        └───────────┬───────────┘               └───────────┬───────────┘
                    │                                       │
                    │                           ┌───────────▼───────────┐
                    │                           │ insight_from_annot.   │
                    │                           │  (聚合 → Insight)      │
                    │                           └───────────┬───────────┘
                    │                                       │
                    └───────────────────┬───────────────────┘
                                        │
                          ┌─────────────▼───────────────┐
                          │           score              │
                          │        (规则评分)             │
                          └─────────────┬───────────────┘
                                        │
                          ┌─────────────▼───────────────┐
                          │          report              │
                          │       (HTML 报告生成)         │
                          └─────────────┬───────────────┘
                                        │
                          ┌─────────────▼───────────────┐
                          │    human_review_gate         │
                          │   (人工审核门控, 可选)         │
                          └─────────────┬───────────────┘
                                        │
                          ┌─────────────▼───────────────┐
                          │     final_decision           │
                          │       (最终决策)              │
                          └─────────────────────────────┘
```

两条模式的分支点：`normalize` 之后 —
- **rule 模式**：走 `sentiment` → `insight`，两者都使用纯关键词规则匹配。
- **llm_annotation 模式**：走 `annotate_comments` → `sentiment_from_annotations` → `insight_from_annotations`，由 LLM 进行评论级语义标注后再聚合成标准情感/洞察结果。

---

## 全局输入：AnalysisRequest

这是用户提交分析的入口参数，贯穿整个 DAG 的 state，所有节点都能读取。

```
AnalysisRequest {
    topic: str              // 搜索关键词，如 "控油洗发水"
    product_direction: str  // 产品方向描述，如 "控油蓬松洗发水"
    industry_question: str  // 行业问题/分析意图，如 "用户是否愿意为控油蓬松功能支付更高溢价"
}
```

---

## 节点 1：collect（数据采集）

### 所属模式

rule / llm_annotation 共用。

### 输入

```
AnalysisRequest {
    topic: str              // 搜索关键词
    product_direction: str  // 产品方向
    industry_question: str  // 行业问题
}
```

### 输出

```
RawDataset {
    posts: list[PostRecord]        // 原始帖子列表
    comments: list[CommentRecord]  // 原始评论列表
}

PostRecord {
    platform: str              // 平台标识，如 "xhs"
    post_id: str               // 帖子唯一 ID
    title: str                 // 帖子标题
    content: str               // 帖子正文
    author: str                // 作者昵称
    publish_time: str          // 发布时间（原始格式）
    likes: int = 0             // 点赞数
    comments: int = 0          // 评论数（帖子互动计数）
    favorites: int = 0         // 收藏数
    shares: int = 0            // 分享数
    url: str = ""              // 帖子链接
    tags: list[str] = []       // 标签/话题
}

CommentRecord {
    platform: str                  // 平台标识，如 "xhs"
    comment_id: str                // 评论唯一 ID
    post_id: str                   // 所属帖子 ID
    content: str                   // 评论内容
    author: str                    // 评论者昵称
    publish_time: str              // 发布时间（原始格式）
    likes: int = 0                 // 点赞数
    parent_comment_id: str | None  // 父评论 ID（回复链），无则为 null
}
```

### 详细步骤

1. **选择采集方式**
   - 若有 Adapter（如 `XhsPlaywrightAdapter`）：调用 `adapter.fetch_posts(keyword)` 获取帖子列表，然后对每条帖子调用 `adapter.fetch_comments(post_id)` 获取评论。
   - 若无 Adapter（mock 模式）：从 `data/raw/raw_posts.json` 和 `data/raw/raw_comments.json` 读取本地 JSON 文件。

2. **数据组装与校验**
   - 将每个帖子字典构造为 `PostRecord` Pydantic 模型。
   - 将每条评论字典构造为 `CommentRecord` Pydantic 模型。
   - 利用 Pydantic 的 `strict=False` 模式，允许原始平台字段的宽松输入。

3. **持久化**
   - 将 `RawDataset` 中的帖子和评论分别写入 `data/raw/raw_posts.json` 和 `data/raw/raw_comments.json`（或 job 目录下的对应路径）。

4. **技术约束**
   - 当使用 Playwright Adapter 时，Sync API 必须在独立线程中执行，不得在 FastAPI asyncio event loop 中直接调用。
   - 不在此节点做任何分析、总结或评分。
   - API key / cookie / token 不得写入日志或产物。

---

## 节点 2：normalize（数据标准化）

### 所属模式

rule / llm_annotation 共用。

### 输入

```
RawDataset {
    posts: list[PostRecord]        // 原始帖子
    comments: list[CommentRecord]  // 原始评论
}
```

### 输出

```
NormalizedDataset {
    posts: list[PostRecord]        // 标准化后的帖子
    comments: list[CommentRecord]  // 标准化后的评论
}

// PostRecord 与 CommentRecord 结构同节点 1，
// 区别在于所有字段已经过 trim、去重、时间标准化处理。
```

### 详细步骤

1. **帖子清洗（_clean_posts）**
   - 对每条帖子的 `content` 字段做 `strip()`，去除首尾空白。
   - 移除 `strip()` 后为空的帖子。
   - 按 `post_id` 去重：同一 ID 只保留首次出现的记录。
   - 对 `title`、`author`、`url` 同样执行 `strip()`。
   - 调用 `_normalize_time()` 将 `publish_time` 标准化为 ISO 8601 `YYYY-MM-DDTHH:MM:SS` 格式。

2. **评论清洗（_clean_comments）**
   - 对每条评论的 `content` 字段做 `strip()`。
   - 移除 `strip()` 后为空的评论。
   - 按 `comment_id` 去重。
   - 对 `author` 同上执行 `strip()`。
   - 调用 `_normalize_time()` 标准化 `publish_time`。

3. **孤儿评论移除（_link_comments_to_posts）**
   - 收集所有存活帖子的 `post_id`。
   - 删除 `post_id` 不在存活帖子集合中的评论（孤儿评论），并记录 warning。

4. **时间标准化（_normalize_time）**
   支持的输入格式：
   - 已是 ISO 8601 格式 → 原样返回
   - `YYYY-MM-DD HH:MM:SS`（空格分隔）→ 转换为 T 分隔
   - `YYYY/MM/DD HH:MM:SS` → 转换
   - `YYYY-MM-DD HH:MM` → 补齐秒数
   - Unix 时间戳（整数/浮点数）→ 转换为 ISO
   - `MM-DD地区`（小红书评论常见格式，如 "03-25广东"）→ 补当年年份
   - `昨天 HH:MM地区` → 计算昨天的日期
   - `YYYY-MM-DD`（纯日期）→ 补齐时分秒
   - 无法解析的格式 → 记录 warning，原样保留

5. **空数据集校验**
   - 若清洗后帖子和评论双双为空，抛出 `ValueError`。

6. **持久化**
   - 写入 `data/normalized/normalized_posts.json` 和 `data/normalized/normalized_comments.json`。

---

## 节点 3A：sentiment（规则关键词情感分析）

### 所属模式

rule 模式专用。

### 输入

```
NormalizedDataset {
    posts: list[PostRecord]        // 标准化帖子
    comments: list[CommentRecord]  // 标准化评论
}
```

### 输出

```
SentimentResult {
    overall_sentiment: str                    // 整体情感倾向：positive / negative / neutral
    post_sentiments: list[PostSentiment]       // 每条帖子的聚合情感
    comment_sentiments: list[CommentSentiment] // 每条评论的情感分类
}

PostSentiment {
    post_id: str     // 帖子 ID
    label: str       // 该帖评论多数情感：positive / negative / neutral
    score: float     // 该帖评论平均情感分数 [0.0, 1.0]
}

CommentSentiment {
    comment_id: str  // 评论 ID
    label: str       // positive / negative / neutral
    score: float     // 情感分数 [0.0, 1.0]，0.5 为中性基准
}
```

### 详细步骤

1. **构建评论-帖子查找表**
   - 按 `post_id` 分组所有评论，形成 `{post_id: [CommentRecord, ...]}`。

2. **评论级情感分类（_classify_comment）**
   - 对每条评论的 `content`，统计命中正向关键词（`POSITIVE_KEYWORDS`，共 31 个）的次数 `pos_count`。
   - 统计命中负向关键词（`NEGATIVE_KEYWORDS`，共 50 个）的次数 `neg_count`。
   - 判定逻辑：
     - `pos_count == 0 && neg_count == 0` → `label = "neutral"`, `score = 0.5`
     - `pos_count > neg_count` → `label = "positive"`, `score = pos_count / (pos_count + neg_count)`
     - `neg_count > pos_count` → `label = "negative"`, `score = neg_count / (pos_count + neg_count)`
     - 二者相等 → `label = "neutral"`, `score = 0.5`

3. **帖子级情感聚合（_aggregate_post_sentiments）**
   - 使用预分类的 `CommentSentiment` 查找表，避免重复计算。
   - 对每条帖子的所有评论：统计多数 `label`，计算平均 `score`。
   - 无评论的帖子 → 默认为 `("neutral", 0.5)`。

4. **整体情感聚合（_aggregate_overall）**
   - 统计所有评论的多数 `label` 作为 `overall_sentiment`。
   - 计算所有评论的平均 `score`。

---

## 节点 3B：annotate_comments（LLM 评论语义标注）

### 所属模式

llm_annotation 模式专用。

### 输入

```
NormalizedDataset {
    posts: list[PostRecord]        // 标准化帖子（提供帖子上下文）
    comments: list[CommentRecord]  // 标准化评论（待标注）
}
```

### 输出

```
list[CommentAnnotationRecord]

CommentAnnotationRecord {
    comment_id: str                  // 评论 ID（由代码绑定）
    post_id: str                     // 所属帖子 ID（由代码绑定）
    sentiment: str                   // positive / negative / neutral / mixed
    pain_point_labels: list[str]     // 用户痛点/困扰标签（LLM 生成）
    need_labels: list[str]           // 用户需求/期望标签（LLM 生成）
    complaint_labels: list[str]      // 负面评价标签（LLM 生成）
    solution_labels: list[str]       // 方案/产品/建议标签（LLM 生成）
    market_signal_labels: list[str]  // 内容选题/购买信号标签（LLM 生成）
    intent_labels: list[str]         // 用户意图标签（LLM 生成）
    reason: str                      // 判断理由（仅用于 debug，不进最终报告）
}
```

### 详细步骤

1. **构建帖子上下文映射（_build_post_context_map）**
   - 对于每条评论所属的帖子，构建 `{post_id: {"title": "...", "content_excerpt": "..."}}`。
   - `content_excerpt` 截取前 500 个字符（或 800 个英文字符），防止 prompt 过长。

2. **按帖子分组 + 批量处理**
   - 将评论按 `post_id` 分组，同帖评论尽量在同一 batch 中，确保 LLM 能获取一致的帖子上下文。
   - 每个 batch 默认最多 10 条评论（`batch_size=10`），每个帖子最多处理 50 条评论（`max_comments=50`）。

3. **构建 Prompt（_build_batch_prompt）**
   - 使用 `_ANNOTATION_PROMPT_TEMPLATE` 模板，包含：
     - 关键词上下文
     - 帖子标题 + 正文摘要
     - 评论 JSON 数组（每条含 `index`、`content`、`likes`）
   - Prompt 明确要求：结合帖子上下文判断，不要泛化；label 为 4-15 字短中文短语；只输出 JSON。

4. **调用 LLM**
   - 通过 `BaseLLMClient.generate_json()` 发送 prompt，获取原始 JSON。
   - LLM 失败或输出格式非法时，回退到规则版 SentimentAgent + InsightAgent。

5. **解析 & 校验（_parse_annotations）**
   - 调用 `filter_forbidden_scores()` 过滤禁止出现的评分字段（如果 LLM 违规输出评分，移除之）。
   - 校验项（任一失败则抛异常）：
     - 必须有 `annotations` 字段且为 list。
     - `annotations` 长度必须与输入 batch 一致。
     - 每条 annotation 必须有合法的 `index`，且 index 在范围内、无重复。
     - `sentiment` 必须在 `{positive, negative, neutral, mixed}` 中。
   - 逐条绑定：`comment_id` 和 `post_id` 从原始 `CommentRecord` 赋值（LLM 不生成 ID）。

6. **输出**
   - 返回 `list[CommentAnnotationRecord]`，存入 state 供下游聚合。

---

## 节点 4A：insight（规则关键词洞察提取）

### 所属模式

rule 模式专用。

### 输入

```
NormalizedDataset {
    posts: list[PostRecord]        // 标准化帖子
    comments: list[CommentRecord]  // 标准化评论
}

SentimentResult {
    overall_sentiment: str                    // 整体情感
    post_sentiments: list[PostSentiment]       // 帖子级情感
    comment_sentiments: list[CommentSentiment] // 评论级情感
}
```

### 输出

```
InsightRecord {
    pain_points: list[str]          // 用户痛点/使用障碍
    user_needs: list[str]           // 用户需求/信息需求
    complaints: list[str]           // 负面反馈/不满表达
    solutions: list[str]            // 用户提及的产品/方案/品牌
    market_signals: list[str]       // 内容机会信号/购买决策信号
    sentiment: str                  // 整体情感倾向（从 SentimentResult 继承）
    evidence_post_ids: list[str]    // 支撑洞察的帖子 ID 列表
    evidence_comment_ids: list[str] // 支撑洞察的评论 ID 列表
}
```

### 详细步骤

1. **洞察关键词收集（_collect_insights）**
   - 初始化 5 个类别的字典结构：`pain_points`、`user_needs`、`complaints`、`solutions`、`market_signals`。
   - 每个类别下以匹配到的关键词为 key，value 为 `{post_ids: set, comment_ids: set}`。
   - **扫描帖子**：对每条帖子的 `title + " " + content`（转为小写），逐一匹配 5 个关键词列表（共约 100+ 个关键词）。命中时将 `post_id` 加入对应关键词的 `post_ids`。
   - **扫描评论**：对每条评论的 `content`（转为小写），同上述逻辑匹配。命中时将 `comment_id` 加入对应关键词的 `comment_ids`。

2. **构建 InsightRecord（_build_insight）**
   - 每个类别下的匹配关键词列表（去重）即为该类别的洞察条目。
   - 收集所有类别的 `evidence_post_ids` 和 `evidence_comment_ids`（去重并排序）。
   - 从 `SentimentResult.overall_sentiment` 继承整体情感。
   - 所有列表排序以保证确定性输出。

3. **持久化**
   - 写入 `data/outputs/insights.json`。

4. **边界条件**
   - 若 3 个核心类别（pain_points / user_needs / complaints）全部为空，记录 warning（不抛异常）。
   - 每条洞察条目必须至少有一条 `evidence_post_ids` 或 `evidence_comment_ids`。

---

## 节点 4B/5B：sentiment_from_annotations + insight_from_annotations（标注聚合）

### 所属模式

llm_annotation 模式专用。

这两个节点都使用 `AnnotationAggregator`，从 `CommentAnnotationRecord` 列表中分别聚合出 `SentimentResult` 和 `InsightRecord`。区别在于调用不同的聚合方法。

### 输入（两个节点相同）

```
list[CommentAnnotationRecord]    // 来自 annotate_comments 节点的 LLM 标注列表
NormalizedDataset                // 辅助提供 posts/comments 的完整列表
```

### 输出

**sentiment_from_annotations 输出：**

```
SentimentResult {
    overall_sentiment: str                    // positive / negative / neutral / mixed
    post_sentiments: list[PostSentiment]       // 按帖子聚合的情感
    comment_sentiments: list[CommentSentiment] // 按评论映射的情感
}
```

**insight_from_annotations 输出：**

```
InsightRecord {
    pain_points: list[str]          // 从 annotation.pain_point_labels 聚合
    user_needs: list[str]           // 从 annotation.need_labels 聚合
    complaints: list[str]           // 从 annotation.complaint_labels 聚合
    solutions: list[str]            // 从 annotation.solution_labels 聚合
    market_signals: list[str]       // 从 annotation.market_signal_labels + intent_labels 聚合
    sentiment: str                  // 多数 sentiment
    evidence_post_ids: list[str]    // 所有被标注评论的 post_id
    evidence_comment_ids: list[str] // 所有被标注评论的 comment_id
}
```

### 详细步骤

**sentiment_from_annotations（to_sentiment_result）：**

1. **评论级情感映射**：遍历每条 `CommentAnnotationRecord`，将其 LLM 标注的 `sentiment` 映射为 `CommentSentiment`：
   - `"positive"` → `("positive", 1.0)`
   - `"negative"` → `("negative", 1.0)`
   - 其他 → `("neutral", 0.5)`

2. **帖子级情感聚合**：按 `post_id` 分组所有 annotation，统计每条帖子的多数 `sentiment`。

3. **整体情感聚合**：统计所有 annotation 的多数 `sentiment`。特殊处理：若 `positive` 和 `negative` 分别是第一和第二，且它们的数量差 ≤ 1，则 `overall = "mixed"`。

**insight_from_annotations（to_insight_record）：**

1. **标签聚合**：遍历每条 annotation，将其各 label 列表直接 append 到对应类别的总列表中。
   - `pain_point_labels` → `pain_points`
   - `need_labels` → `user_needs`
   - `complaint_labels` → `complaints`
   - `solution_labels` → `solutions`
   - `market_signal_labels` + `intent_labels` → `market_signals`
   - 对每个 label 做 `strip()`，跳过空字符串。

2. **证据绑定**：每条 annotation 的 `comment_id` 和 `post_id` 即为 evidence。不重复添加。

3. **不做的事**：不做 label 去重、不做同义词映射、不做聚类、不做低频过滤。原始 label 由 LLM 保证质量。

4. **持久化**：`insight_from_annotations_node` 额外将聚合结果持久化到 `data/outputs/insights.json`。

---

## 节点 5/6：score（规则评分）

### 所属模式

rule / llm_annotation 共用。

### 输入

```
InsightRecord {
    pain_points: list[str]
    user_needs: list[str]
    complaints: list[str]
    solutions: list[str]
    market_signals: list[str]
    sentiment: str
    evidence_post_ids: list[str]
    evidence_comment_ids: list[str]
}

NormalizedDataset {
    posts: list[PostRecord]
    comments: list[CommentRecord]
}

SentimentResult {
    overall_sentiment: str
    post_sentiments: list[PostSentiment]
    comment_sentiments: list[CommentSentiment]
}
```

### 输出

```
ScoreCard {
    demand_intensity: float        // 用户关注强度 [0.0, 1.0]
    sentiment_friction: float      // 负面反馈强度 [0.0, 1.0]
    solution_saturation: float     // 方案饱和/内容切入空间 [0.0, 1.0]
    purchase_intent: float         // 购买/行动信号 [0.0, 1.0]
    freshness: float               // 评论时效性 [0.0, 1.0]
    overall_score: float           // 内容选题价值综合评分 [0.0, 1.0]
    scoring_reason: str            // 逐维度评分解释（多行文本）
}
```

### 详细步骤

**调用 5 个独立规则函数 + 1 个综合函数：**

1. **需求强度评分（calc_demand_intensity）**
   - 子维度 1：`need_score = log1p(user_needs 数量) / log1p(20)`，权重 0.6
   - 子维度 2：`signal_score = log1p(market_signals 数量) / log1p(20)`，权重 0.4
   - `demand_intensity = min(need_score * 0.6 + signal_score * 0.4, 1.0)`
   - 使用 `log1p` 平滑：前几个需求贡献大，后面边际递减，避免少数爆款需求直接打满。

2. **负面摩擦评分（calc_sentiment_friction）**
   - 情感基础分：`negative` → 0.4, `neutral` → 0.2, `positive` → 0.0
   - 投诉/痛点加成：每个 complaint 或 pain_point 加 0.05，上限 0.6
   - `sentiment_friction = min(sentiment_base + complaint_score, 1.0)`

3. **方案饱和度评分（calc_solution_saturation）**
   - 根据 solutions 数量分档：
     - 0 个 → 0.0
     - 1-2 个 → 0.2
     - 3-4 个 → 0.5
     - 5-7 个 → 0.7
     - 8+ 个 → 0.9
   - 注意：此分数越高表示用户提到方案越多，内容切入空间越小（在综合评分中取反向）。

4. **购买意向评分（calc_purchase_intent）**
   - 遍历 `market_signals`，统计其中命中购买关键词（"多少钱"、"哪里买"、"想买"、"链接"、"求链接"、"下单" 等共 14 个）的数量。
   - 每个购买信号 +0.2，`purchase_intent = min(count * 0.2, 1.0)`

5. **时效性评分（calc_freshness）**
   - 取所有帖子中 `publish_time` 的最新时间。
   - 距今天数 → 月数换算（除以 30.44）：
     - ≤ 1 个月 → 1.0
     - ≤ 3 个月 → 0.8
     - ≤ 6 个月 → 0.5
     - ≤ 12 个月 → 0.2
     - \> 12 个月 → 0.1
   - 无帖子或无可用时间 → 0.1

6. **综合评分 & 理由生成（calc_overall）**
   - 权重分配：

     | 维度 | 权重 | 说明 |
     |------|------|------|
     | demand_intensity | 0.30 | 用户关注强度 |
     | sentiment_friction | 0.25 | 负面反馈强度 |
     | 机会空间 (= 1 - solution_saturation) | 0.15 | 内容切入空间（饱和度反向） |
     | purchase_intent | 0.20 | 购买/行动信号 |
     | freshness | 0.10 | 数据时效 |

   - `overall_score = Σ(维度 × 权重)`
   - `scoring_reason` 逐行输出每个维度的计算依据。

7. **持久化**
   - 写入 `data/outputs/scorecard.json`。

---

## 节点 6/7：report（HTML 报告生成）

### 所属模式

rule / llm_annotation 共用。

### 输入

```
InsightRecord {
    pain_points: list[str]
    user_needs: list[str]
    complaints: list[str]
    solutions: list[str]
    market_signals: list[str]
    sentiment: str
    evidence_post_ids: list[str]
    evidence_comment_ids: list[str]
}

ScoreCard {
    demand_intensity: float
    sentiment_friction: float
    solution_saturation: float
    purchase_intent: float
    freshness: float
    overall_score: float
    scoring_reason: str
}

NormalizedDataset {
    posts: list[PostRecord]
    comments: list[CommentRecord]
}

topic: str = ""              // 搜索关键词
product_direction: str = ""  // 产品方向
```

### 输出

```
ReportResult {
    success: bool        // 是否生成成功
    report_path: str     // 报告文件路径，如 "data/outputs/report.html"
}
```

### 详细步骤

1. **主题/方向推断（_derive_topic）**
   - 若未传入 topic 或 product_direction，从第一条帖子的标题/内容中推断。

2. **评分等级判定**
   - overall_score ≥ 0.8 → "优秀"（绿色）
   - overall_score ≥ 0.6 → "良好"（黄色）
   - overall_score ≥ 0.4 → "一般"（橙色）
   - overall_score < 0.4 → "较差"（红色）

3. **数据准备**
   - 合并 complaints + pain_points → 去重后作为负面反馈列表。
   - 计算帖子/评论中的关键词频率 TOP N。
   - 收集有证据的帖子和评论代表性样本。

4. **生成 12 个 HTML 章节**

   | 序号 | 章节标题 | 内容说明 |
   |------|---------|---------|
   | 1 | 采集概览 | 主题词、产品方向、数据来源、帖子数、评论数 |
   | 2 | 评论区讨论摘要 | 基于情感分析的评论区整体氛围描述 |
   | 3 | 用户核心关注点 | user_needs 标签列表 + 高频评论主题聚类 |
   | 4 | 用户高频疑问 | 从评论中提取的用户疑问/信息需求 |
   | 5 | 高互动内容信号 | 高赞评论、高互动帖子的内容机会信号 |
   | 6 | 正负向反馈总结 | complaints + pain_points 汇总展示 |
   | 7 | 购买/行动信号 | 购买意向关键词命中展示（含具体评论引用） |
   | 8 | 可写文案方向 | 基于洞察的选题思路建议 |
   | 9 | 推荐标题/选题角度 | 具体的文案标题建议 |
   | 10 | 代表评论证据 | 引用真实评论原文（经过 html.escape 转义）作为证据 |
   | 11 | 内容选题价值评分 | ScoreCard 各维度可视化 + scoring_reason 展示 |
   | 12 | 数据局限说明 | 声明本报告基于有限样本，不代表市场规模/销量预测/商业可行性 |

5. **输出限制**
   - 所有用户原文使用 `html.escape()` 转义防止 XSS。
   - 不重新计算评分，不重新抓取数据，不编造证据。
   - 报告标题固定为"小红书评论区用户反馈与文案选题报告"。
   - 数据局限说明为强制章节，不可省略。

6. **持久化**
   - 写入 `data/outputs/report.html`（内联 CSS + 完整自包含 HTML）。

---

## 节点 7/8：human_review_gate（人工审核门控）

### 所属模式

rule / llm_annotation 共用（可选启用）。

### 输入

```
UGCGraphState 中包含：
    report_path: str                // 已生成的报告路径
    human_review_required: bool     // 是否启用人工审核
    request.topic: str              // 搜索关键词
```

### 输出

```
HumanReviewRecord {
    status: str                     // "approved" / "rejected"
    approved: bool                  // 是否通过
    reviewer: str                   // 审核人标识，如 "human"
    comments: str                   // 审核意见
    reasons: list[str]              // 审批/驳回理由
    revision_instructions: list[str] // 修订指令
    created_at: str                 // 创建时间（ISO 8601）
    updated_at: str                 // 更新时间（ISO 8601）
}
```

### 详细步骤

1. **触发 interrupt**
   - 调用 LangGraph 的 `interrupt()` 函数，暂停图执行。
   - interrupt payload 包含：
     - `type`: `"human_report_review"`
     - `keyword`: 当前主题词
     - `report_path`: 报告文件路径
     - `message`: "请人工审核报告，选择 approve 或 reject。"

2. **等待人工决策**
   - 图暂停，等待外部通过 `Command(resume=...)` 恢复。
   - resume 数据包含：`approved`、`reviewer`、`comments`、`reasons`、`revision_instructions`。

3. **构建审核记录**
   - 根据 `approved` 设置 `status` 为 `"approved"` 或 `"rejected"`。
   - 时间戳取当前时刻。

4. **条件路由**
   - 通过 `should_human_review()` 函数判断：若 `human_review_required=False`，跳过此节点直接进入 `final_decision`。

---

## 节点 8/9：final_decision（最终决策）

### 所属模式

rule / llm_annotation 共用。

### 输入

```
UGCGraphState 中包含：
    human_review_record: HumanReviewRecord | None  // 人工审核记录（如有）
    report_generated: bool                         // 报告是否已生成
```

### 输出

```
FinalReviewResult {
    agent_passed: bool     // Agent 审核是否通过（当前 P5.1 预留，默认为 true）
    human_approved: bool   // 人工审核是否通过
    final_passed: bool     // 最终是否通过 = agent_passed AND human_approved
    reasons: list[str]     // 未通过的原因列表
}
```

### 详细步骤

1. **判断审核路径**
   - 若 `human_review_record` 不为 None（人工审核已启用且完成）：
     - `human_approved = human_review_record.approved`
     - `agent_passed = True`（P5.1 预留，后续从 Agent 审核结果读取）
     - `final_passed = agent_passed AND human_approved`
     - 收集未通过原因。
   - 若 `human_review_record` 为 None（人工审核未启用）：
     - 全部设为 `True`，自动通过。

2. **设置最终状态**
   - `state.success = final_review.final_passed`
   - DAG 到此终止。

---

## 附录 A：关键词一览

### A.1 正向情感关键词（POSITIVE_KEYWORDS，31 个）

好用、不错、喜欢、推荐、有效、满意、惊喜、温和、舒服、清爽、回购、效果好、效果最好、真的好用、真的有效、空瓶、很好、还不错、可以、改善、明显、轻薄、透气、水润、持久、细腻、光滑、值得

### A.2 负向情感关键词（NEGATIVE_KEYWORDS，50 个）

不好、失望、差、没用、油腻、刺激、过敏、长痘、发痒、假货、骗人、踩雷、拔草、千万别、干涩、痒、痘痘、屏障受损、过度清洁、没有用、不够、没用了、变多了、治标不治本、太贵、无效、套路、智商税、受不了、不行、好油、好干、太油、干燥、刺痛、泛红、闷痘、堵塞、拔干、厚重、搓泥、难用、伤肤、发红、脱皮、不管用、被坑、浪费钱、不好用、没效果

### A.3 洞察关键词（5 类，共约 100+ 个）

| 类别 | 数量 | 代表关键词 |
|------|------|-----------|
| pain_points | 24 个 | 太贵、不好用、没用、无效、刺激、过敏、长痘... |
| user_needs | 14 个 | 需要、想要、求推荐、有没有、希望、求链接... |
| complaints | 20 个 | 不好、差、骗人、套路、智商税、拔草、假货... |
| solutions | 15 个 | 推荐、试试、建议、搭配、换成、替代... |
| market_signals | 14 个 | 多少钱、哪里买、想买、链接、下单、入手... |

### A.4 购买意图关键词（评分专用，14 个）

多少钱、哪里买、想买、怎么买、下单、链接、求链接、同求、要买、入手、购买、求购、在哪儿、买

---

## 附录 B：产物目录结构

### CLI / 默认 data 模式

```
data/
├── raw/
│   ├── raw_posts.json
│   └── raw_comments.json
├── normalized/
│   ├── normalized_posts.json
│   └── normalized_comments.json
└── outputs/
    ├── insights.json
    ├── scorecard.json
    └── report.html
```

### FastAPI job 模式

```
data/jobs/{keyword_slug}/{run_id}/
├── raw/
│   ├── raw_posts.json
│   └── raw_comments.json
├── normalized/
│   ├── normalized_posts.json
│   └── normalized_comments.json
├── outputs/
│   ├── insights.json
│   ├── scorecard.json
│   └── report.html
├── progress.json
├── events.json
└── snapshots/
    └── latest.png
```

---

## 附录 C：关键设计约束

1. **LLM 职责边界**：LLM 只能生成 `index`、`sentiment`、`labels`、`reason`。`comment_id` / `post_id` / `evidence_id` 由代码绑定。LLM 不生成评分、不判断市场规模或商业可行性。

2. **evidence 约束**：所有 evidence 必须来自真实的 `PostRecord` 或 `CommentRecord`，不允许凭空生成。

3. **报告禁止表述**："市场规模"、"销量预测"、"商业可行性"、"市场验证成功"、"市场机会巨大"等夸大结论禁止出现在任何产物中。

4. **安全约束**：API key / cookie / token 不得写入日志、报告或任何调试产物。用户原文在 HTML 报告中必须经过 `html.escape()` 转义。

5. **Playwright 约束**：Playwright Sync API 必须在独立线程中执行，不得在 FastAPI asyncio event loop 中直接调用。

6. **Agent 越界禁止**：SourceAgent 不做总结/评分；NormalizeAgent 不做需求分析/情感判断；ReportAgent 不重新计算评分/重新抓取数据；ScoringAgent 不调用 LLM 评分。
