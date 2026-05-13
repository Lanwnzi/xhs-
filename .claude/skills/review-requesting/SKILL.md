---
name: review-requesting
description: 当完成一个开发任务、实现主要功能、修改核心模块、准备进入下一个任务、准备合并代码或需要确认实现是否符合要求时，必须使用本 skill。本 skill 用于发起审查流程，要求先进行 spec-compliance-review，再进行 code-quality-review，并根据审查结果决定是否返工。
---

# Review Requesting

## 核心定位

本 skill 用于在完成开发任务后，发起正式审查。

它不负责写代码。

它负责回答：

- 当前任务是否应该进入 review？
- 应该请求哪个 reviewer？
- reviewer 需要哪些上下文？
- review 不通过时如何处理？
- 什么时候可以进入下一个任务？

本项目采用双审查机制：

1. spec-compliance-reviewer
2. code-quality-reviewer

必须先做规范一致性审查，再做代码质量审查。

## 适用场景

以下情况必须使用本 skill：

- developer-agent 完成一个任务后
- 完成一个 P0 功能后
- 修改 schema 后
- 修改 Agent 逻辑后
- 修改 scoring 规则后
- 修改 report 生成逻辑后
- 修改 pipeline 后
- 修复复杂 bug 后
- 准备进入下一个 backlog task 前
- 准备提交或合并前

## 审查顺序

固定顺序：

```text
developer-agent 完成实现
        ↓
spec-compliance-reviewer 审查
        ↓
code-quality-reviewer 审查
        ↓
全部通过后进入下一个任务