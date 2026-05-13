"""ContentIdeationAgent 输出 schema。

TopicSuggestion — 关键词相关内容选题建议
TitleSuggestion — 热点选题与文案定制建议
ContentIdeationResult — ContentIdeationAgent 的最终输出
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TopicSuggestion(BaseModel):
    """单条关键词相关内容选题建议。

    由 ContentIdeationAgent 基于洞察数据和真实评论生成，
    每条建议必须包含可追溯的 evidence。
    """

    direction: str = ""
    title: str = ""
    evidence: str = ""
    content_angle: str = ""


class TitleSuggestion(BaseModel):
    """单条热点选题与文案定制建议。

    由 ContentIdeationAgent 基于洞察数据、评分和内容策略生成，
    标题必须非模板化，结合具体洞察词。
    """

    direction: str = ""
    title: str = ""
    evidence: str = ""
    content_angle: str = ""


class ContentIdeationResult(BaseModel):
    """ContentIdeationAgent 的最终输出。

    包含关键词相关内容选题建议和热点选题与文案定制建议。
    generation_mode 记录生成方式，perspectives_used 记录实际使用的角度。
    """

    topic_suggestions: list[TopicSuggestion] = Field(default_factory=list)
    custom_title_suggestions: list[TitleSuggestion] = Field(default_factory=list)
    generation_mode: str = "single_llm"  # "single_llm" | "multi_perspective"
    perspectives_used: list[str] = Field(default_factory=list)
