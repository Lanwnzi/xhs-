"""API 专用 Pydantic schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class APIAnalyzeRequest(BaseModel):
    """分析请求。"""
    keyword: str = Field(..., min_length=1, description="搜索关键词")
    max_posts: int = Field(default=3, ge=1, description="最大帖子数")
    max_comments: int = Field(default=20, ge=0, description="每帖最大评论数")
    analysis_mode: Literal["rule", "llm_annotation"] = Field(default="rule", description="分析模式")
    mock_llm: bool = Field(default=False, description="是否使用 MockLLMClient")
    headless: bool = Field(default=True, description="Playwright 无头模式")


class APIJobResponse(BaseModel):
    """创建 job 后的即时响应。"""
    job_id: str
    status: str
    message: str
    report_url: str
    data_root: str


class JobRecord(BaseModel):
    """Job 完整记录。"""
    job_id: str
    keyword: str
    keyword_slug: str
    run_id: str
    status: str  # pending / running / completed / failed
    analysis_mode: str = "rule"
    mock_llm: bool = False
    max_posts: int = 3
    max_comments: int = 20
    headless: bool = True
    data_root: str = ""
    report_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    error: Optional[str] = None
