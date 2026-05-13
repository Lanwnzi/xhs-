---
name: forensic-debugging
description: 当小红书采集、评论抓取、数据标准化、Pydantic 校验、Agent 执行、ScoreCard 评分、HTML 报告生成、pytest 测试或 pipeline 主流程出现 bug、失败、异常行为时，必须使用本 skill。本 skill 要求先复现、收集证据、定位根因，再做最小修复，禁止没有根因就直接改代码。
---

# Forensic Debugging

## 核心原则

本 skill 用于小红书 UGC 市场验证系统的系统化调试。

铁律：

```text
没有复现，不修复。
没有证据，不猜测。
没有根因，不改代码。
没有验证，不说修好了。
```

本项目主流程：

```text
collect -> normalize -> analyze -> score -> render_report
```

调试时必须先判断问题发生在哪一层：

- collect：小红书采集、评论抓取、Cookie、接口返回
- normalize：字段映射、清洗、去重、时间标准化、Pydantic 校验
- analyze：痛点、需求、抱怨、替代方案、市场信号抽取
- sentiment：评论级、帖子级、主题级情感聚合
- score：ScoreCard 规则评分
- render_report：HTML 报告生成
- tests：pytest 或最小验收脚本

---

## 适用场景

出现以下问题时必须使用：

- 小红书采集为空
- 评论为空
- Cookie / 登录失效
- 返回 403 / 401 / 429
- 返回 HTML 而不是 JSON
- raw_posts.json 有数据，但 normalized_posts.json 为空
- Pydantic validation error
- post_id / comment_id 缺失或重复
- Insight 没有 evidence
- Sentiment 全部是 neutral
- ScoreCard 分数超过 100 或低于 0
- overall_score 不是规则计算
- report.html 没生成
- pytest 失败
- pipeline_e2e 失败

---

## 四步调试流程

## Step 1：复现问题

先记录：

```text
问题：
复现命令：
输入数据：
是否稳定复现：
错误类型：
错误文件：
错误行号：
关键日志：
```

推荐命令：

```bash
pytest tests/test_schemas.py
pytest tests/test_normalize_agent.py
pytest tests/test_scoring_agent.py
pytest tests/test_report_agent.py
pytest tests/test_pipeline_e2e.py
```

如果是完整流程：

```bash
python -m src.pipeline.run_pipeline --topic "减脂早餐" --use-mock
```

禁止：

```text
我觉得应该是……
看起来像是……
先改一下试试……
```

---

## Step 2：定位失败层

必须沿数据流检查：

```text
1. collect 层：
- 小红书原始数据是否拿到？
- 状态码是什么？
- 返回 JSON 还是 HTML？
- raw_posts.json 是否存在？

2. adapter 层：
- 小红书字段是否正确映射？
- note_id 是否映射为 post_id？
- 点赞数 "1.2万" 是否转成 int？

3. normalize 层：
- 是否通过 Pydantic？
- 是否被去重误删？
- normalized_posts.json 是否写出？

4. analyze 层：
- insight 是否有 pain_points / user_needs？
- 是否有 evidence_post_ids / evidence_comment_ids？

5. score 层：
- 分数是否在 0-100？
- overall_score 是否由规则函数计算？

6. report 层：
- insights.json 是否存在？
- scorecard.json 是否存在？
- report.html 是否生成？
```

---

## Step 3：提出单一根因假设

一次只提出一个假设。

格式：

```text
假设：
- 

依据：
- 

验证方式：
- 
```

示例：

```text
假设：
- normalized_posts.json 为空，是因为小红书原始字段 note_id 没有映射到 PostRecord.post_id。

依据：
- raw 数据中存在 note_id，但 adapter 输出 post_id 为空。

验证方式：
- 打印 adapter 输出样例，检查 post_id 是否为空。
```

禁止一次性同时改：

- schema
- adapter
- NormalizeAgent
- pipeline
- report

---

## Step 4：最小修复与验证

确认根因后才能修复。

修复要求：

- 只改根因相关代码
- 先补失败测试
- 再写最小修复
- 修复后重新运行相关测试
- 不能绕过 Pydantic
- 不能用默认值掩盖数据问题
- 不能让 LLM 重新打分
- 不能无证据输出市场结论

示例测试：

```python
from src.adapters.xhs_adapter import parse_xhs_count


def test_parse_xhs_count_handles_wan_unit():
    assert parse_xhs_count("1.2万") == 12000
```

修复后至少运行：

```bash
pytest tests/test_normalize_agent.py
pytest tests/test_pipeline_e2e.py
```

---

## 小红书常见问题定位表

### 1. 小红书采集为空

优先检查：

- Cookie 是否有效
- 是否需要登录
- 是否被限流
- 请求头是否缺失
- 返回是否为风控页面
- 搜索关键词是否正确
- adapter 是否解析错字段

必须保留：

```text
状态码：
请求 URL：
返回内容前 500 字：
```

---

### 2. raw_posts.json 有数据，但 normalized_posts.json 为空

优先检查：

- 原始字段名
- adapter 映射
- post_id 是否为空
- content 是否为空
- 去重逻辑
- Pydantic 校验错误
- 输出路径

典型根因：

```text
小红书原始字段 note_id 没有映射到 post_id。
```

---

### 3. Pydantic 校验失败

优先检查：

- 哪个字段失败
- schema 要求什么类型
- 实际输入是什么类型
- 是否应该在 adapter / normalize 层转换

禁止：

```text
把字段改成 Any 来绕过校验。
```

---

### 4. Insight 没有 evidence

优先检查：

- 输入数据是否有 post_id / comment_id
- InsightAgent 是否保留 evidence
- Prompt 是否要求输出证据
- 后处理是否把 evidence 过滤掉

禁止：

```text
手动补一个假的 evidence id。
```

---

### 5. ScoreCard 分数异常

优先检查：

- 单项分是否 clamp 到 0-100
- 权重和是否为 1
- 样本量不足是否降权
- solution_saturation 是否反向计算
- overall_score 是否由规则函数计算

禁止：

```text
让 LLM 重新给一个合理分数。
```

---

### 6. report.html 没生成

优先检查：

- insights.json 是否存在
- scorecard.json 是否存在
- 模板路径是否正确
- 输出路径是否正确
- Jinja2 是否报错

禁止：

```text
在 ReportAgent 中重新计算评分。
```

---

## 标准输出格式

遇到 bug 时按这个格式输出：

```text
问题概述：
- 

失败阶段：
- collect / normalize / analyze / sentiment / score / render_report / tests

复现方式：
- 

错误证据：
- 

数据流追踪：
1. collect：
2. adapter：
3. normalize：
4. analyze：
5. score：
6. report：

根因假设：
- 

验证方式：
- 

确认根因：
- 

最小修复：
- 

新增测试：
- 

验证结果：
- 

是否允许进入 review-requesting：
- 是 / 否
```

---

## 最终原则

- 先复现，后修复
- 先证据，后判断
- 先根因，后代码
- 一次只验证一个假设
- 一次只修一个根因
- 三次修复失败，停止 patch，回到设计审查
- 不绕过 schema
- 不用 LLM 掩盖评分问题
- 不用报告文案掩盖证据不足