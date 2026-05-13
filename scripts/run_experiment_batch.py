"""
警告：此脚本已弃用，由 LangGraph 批量实验取代。

请使用：
    python scripts/run_langgraph_experiment_batch.py

当前入口保持兼容，内部转发至 LangGraph 版本。
"""

from __future__ import annotations

import os
import sys
import warnings

# 确保项目根目录在 sys.path 中，以便 scripts 包能被正确导入
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

if __name__ == "__main__":
    warnings.warn(
        "run_experiment_batch.py 已弃用，请使用 run_langgraph_experiment_batch.py",
        DeprecationWarning,
        stacklevel=2,
    )
    print("转发至 LangGraph 批量实验...\n")
    # 导入并执行 LangGraph 版本
    from scripts.run_langgraph_experiment_batch import main
    sys.exit(main())
