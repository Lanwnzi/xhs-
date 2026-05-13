# XhsPlaywrightAdapter 设计文档

## 概述

XhsPlaywrightAdapter 使用 Playwright 浏览器自动化采集小红书搜索页面和笔记详情页的公开可见内容。

## 数据流

XhsPlaywrightAdapter → SourceAgent → NormalizeAgent → LangGraph → Insight → Score → Report

## 字段映射

### 帖子字段映射

| PostRecord 字段 | 小红书页面字段 | 必填 | 缺失处理 |
|---|---|---|---|
| platform | - | 是 | 固定 "xhs" |
| post_id | note_id | 是 | 跳过该帖子 |
| title | title | 否 | 空字符串 |
| content | desc | 否 | 空字符串 |
| author | nickname | 否 | 空字符串 |
| publish_time | create_time | 否 | 空字符串或采集时间 |
| likes | liked_count | 否 | 0 |
| comments | comment_count | 否 | 0 |
| favorites | collected_count | 否 | 0 |
| shares | share_count | 否 | 0 |
| url | note_url | 否 | 空字符串 |
| tags | tag_list | 否 | [] |

### 评论字段映射

| CommentRecord 字段 | 小红书页面字段 | 必填 | 缺失处理 |
|---|---|---|---|
| platform | - | 是 | 固定 "xhs" |
| comment_id | id | 是 | 跳过该评论 |
| post_id | note_id | 是 | 跳过该评论 |
| content | content | 是 | 跳过该评论 |
| author | nickname | 否 | 空字符串 |
| publish_time | create_time | 否 | 空字符串或采集时间 |
| likes | like_count | 否 | 0 |
| parent_comment_id | parent_comment_id | 否 | null |

## 原始字段与标准字段的关系

Adapter 内部使用原始字段采集，输出时映射为标准字段。下游 Agent 只看到标准字段。

## 首次使用

```bash
pip install playwright
python -m playwright install chromium
```

## 登录态

登录态保存到 data/private/xhs_state.json，使用 Playwright storage_state 机制。

## 与 XhsImportAdapter 的关系

- XhsImportAdapter：离线导入/测试，读取本地 xhs_export.json
- XhsPlaywrightAdapter：实时浏览器可见内容采集

两者都完成字段映射，向下游返回标准字段名 dict。
