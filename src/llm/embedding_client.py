"""
OpenAI-compatible embedding API 客户端。

用于 CommentClusterAgent 获取评论内容的向量表示。
遵循现有 LLM 客户端的风格，使用 httpx 发送请求。

配置环境变量：
    EMBEDDING_PROVIDER
    EMBEDDING_BASE_URL
    EMBEDDING_API_KEY
    EMBEDDING_MODEL
    EMBEDDING_TIMEOUT (默认 30)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """OpenAI-compatible embedding API 客户端。

    通过 POST /embeddings 接口获取文本向量。
    不把 API key 打印到日志中。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """调用 embedding API，返回向量列表。

        参数：
            texts: 要编码的文本列表。

        返回：
            向量列表（每个文本对应一个向量），失败时返回 None。
        """
        if not texts:
            return []

        url = f"{self.base_url}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": self.model,
            "input": texts,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()

            # 提取 embeddings
            embeddings_data = data.get("data", [])
            # 按 index 排序以确保顺序与输入一致
            embeddings_data.sort(key=lambda x: x.get("index", 0))
            vectors = [item["embedding"] for item in embeddings_data]

            logger.debug(
                "EmbeddingClient: 成功获取 %d 个向量，维度=%d",
                len(vectors),
                len(vectors[0]) if vectors else 0,
            )
            return vectors

        except httpx.TimeoutException:
            logger.warning("EmbeddingClient: 请求超时 (timeout=%ds)", self.timeout)
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(
                "EmbeddingClient: HTTP 错误 status=%s", e.response.status_code
            )
            return None
        except Exception as e:
            logger.warning("EmbeddingClient: 请求异常: %s", e)
            return None

    def embed_one(self, text: str) -> Optional[list[float]]:
        """编码单条文本。

        参数：
            text: 要编码的文本。

        返回：
            向量，失败时返回 None。
        """
        vectors = self.embed([text])
        if vectors and len(vectors) > 0:
            return vectors[0]
        return None


def create_embedding_client_from_env() -> Optional[EmbeddingClient]:
    """从环境变量创建 EmbeddingClient。

    当 COMMENT_CLUSTERING_ENABLED=false 或缺少 API key 时返回 None。
    不打印 API key 到日志。
    """
    enabled = os.getenv("COMMENT_CLUSTERING_ENABLED", "true").lower()
    if enabled not in ("true", "1", "yes"):
        logger.info("Comment clustering disabled via COMMENT_CLUSTERING_ENABLED")
        return None

    base_url = os.getenv("EMBEDDING_BASE_URL", "")
    api_key = os.getenv("EMBEDDING_API_KEY", "")
    model = os.getenv("EMBEDDING_MODEL", "")
    timeout = int(os.getenv("EMBEDDING_TIMEOUT", "30"))

    if not base_url or not api_key or not model:
        logger.warning(
            "EmbeddingClient: 缺少必需环境变量 "
            "(EMBEDDING_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL)"
        )
        return None

    return EmbeddingClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
    )
