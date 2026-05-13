"""报告质量评审的 Pydantic schema。

第一版只做规则检查，不输出数字评分。
LLM 如果接入，也只能输出定性意见，不能直接给分。
"""

from __future__ import annotations

from pydantic import BaseModel


class ReportQualityReview(BaseModel):
    """报告质量评审结果。

    第一版只做规则检查，不输出数字评分。
    LLM 如果接入，也只能输出定性意见，不能直接给分。
    """

    passed: bool = False
    reasons: list[str] = []
    hard_fail_reasons: list[str] = []
    revision_instructions: list[str] = []
    summary: str = ""
