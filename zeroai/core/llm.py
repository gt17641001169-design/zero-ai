"""LLM client wrapper for ZeroAI"""
import asyncio
from typing import Optional, Dict, Any, List, AsyncGenerator
from openai import OpenAI, AsyncOpenAI
from .config import get_config


class LLMClient:
    """Wrapper for LLM API calls"""
    
    def __init__(self, model_key: str):
        """Initialize LLM client with model configuration"""
        self.config = get_config()
        self.model_key = model_key
        self._model_config = self.config.get_model_config(model_key)
        self._client = None
        self._async_client = None
    
    @property
    def client(self) -> OpenAI:
        """Get synchronous OpenAI client"""
        if self._client is None:
            self._client = OpenAI(
                base_url=self._model_config["base_url"],
                api_key=self._model_config["api_key"]
            )
        return self._client
    
    @property
    def async_client(self) -> AsyncOpenAI:
        """Get asynchronous OpenAI client"""
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                base_url=self._model_config["base_url"],
                api_key=self._model_config["api_key"]
            )
        return self._async_client
    
    @property
    def model(self) -> str:
        """Get model name"""
        return self._model_config["model"]
    
    def chat_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False
    ) -> Optional[str]:
        """Synchronous chat completion"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream
            )
            
            if stream:
                # For streaming, return generator
                return self._handle_stream_sync(response)
            else:
                return response.choices[0].message.content
                
        except Exception as e:
            print(f"LLM call failed: {e}")
            return None
    
    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False,
        timeout: float = 30
    ) -> Optional[str]:
        """Asynchronous chat completion"""
        try:
            response = await asyncio.wait_for(
                self.async_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=stream
                ),
                timeout=timeout
            )
            
            if stream:
                # For streaming, return async generator
                return self._handle_stream_async(response)
            else:
                return response.choices[0].message.content
                
        except asyncio.TimeoutError:
            print(f"LLM call timed out after {timeout}s")
            return None
        except Exception as e:
            print(f"LLM call failed: {e}")
            return None
    
    async def chat_with_messages(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False,
        timeout: float = 60
    ) -> Optional[str]:
        """Chat completion with custom messages"""
        try:
            response = await asyncio.wait_for(
                self.async_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=stream
                ),
                timeout=timeout
            )
            
            if stream:
                return self._handle_stream_async(response)
            else:
                return response.choices[0].message.content
                
        except asyncio.TimeoutError:
            print(f"LLM call timed out after {timeout}s")
            return None
        except Exception as e:
            print(f"LLM call failed: {e}")
            return None
    
    def _handle_stream_sync(self, response) -> str:
        """Handle synchronous streaming response"""
        content = ""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content += chunk.choices[0].delta.content
        return content

    async def _handle_stream_async(self, response) -> AsyncGenerator[str, None]:
        """Handle asynchronous streaming response"""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ========================================================================
    # 阶段 M.1：Embedding API 对接（GLM embedding-3）
    # ========================================================================

    async def embed(
        self,
        texts: List[str],
        dimensions: int = 1024,
        timeout: float = 30,
    ) -> List[List[float]]:
        """异步生成文本嵌入向量（阶段 M.1）

        使用 GLM embedding-3 模型，支持 256/512/1024/2048 维。
        自动批量处理（单次最多 64 条），避免 API 限流。

        Args:
            texts: 待嵌入的文本列表
            dimensions: 输出维度（256/512/1024/2048）
            timeout: 单次请求超时秒数

        Returns:
            嵌入向量列表，shape=(len(texts), dimensions)
            失败时返回空列表

        Raises:
            RuntimeError: API 调用失败
        """
        if not texts:
            return []

        # 批量处理（单次最多 64 条，GLM 限制）
        batch_size = 64
        all_vectors: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                resp = await asyncio.wait_for(
                    self.async_client.embeddings.create(
                        model="embedding-3",
                        input=batch,
                        dimensions=dimensions,
                    ),
                    timeout=timeout,
                )
                # 按 index 排序确保顺序正确
                sorted_data = sorted(resp.data, key=lambda x: x.index)
                for item in sorted_data:
                    all_vectors.append(item.embedding)
            except asyncio.TimeoutError:
                raise RuntimeError(f"Embedding API 超时（{timeout}s）")
            except Exception as e:
                raise RuntimeError(f"Embedding API 调用失败: {e}")

        return all_vectors

    def embed_sync(
        self,
        texts: List[str],
        dimensions: int = 1024,
    ) -> List[List[float]]:
        """同步生成文本嵌入向量（阶段 M.1）

        同 embed() 的同步版本，用于无法 await 的场景。

        Args:
            texts: 待嵌入的文本列表
            dimensions: 输出维度

        Returns:
            嵌入向量列表，失败时返回空列表
        """
        if not texts:
            return []

        batch_size = 64
        all_vectors: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                resp = self.client.embeddings.create(
                    model="embedding-3",
                    input=batch,
                    dimensions=dimensions,
                )
                sorted_data = sorted(resp.data, key=lambda x: x.index)
                for item in sorted_data:
                    all_vectors.append(item.embedding)
            except Exception as e:
                print(f"Embedding API 调用失败: {e}")
                return []

        return all_vectors

    async def embed_one(
        self,
        text: str,
        dimensions: int = 1024,
    ) -> List[float]:
        """嵌入单条文本（便捷方法）

        Args:
            text: 待嵌入文本
            dimensions: 输出维度

        Returns:
            嵌入向量，失败时返回空列表
        """
        vectors = await self.embed([text], dimensions=dimensions)
        return vectors[0] if vectors else []


class MultiModelClient:
    """Client for multi-model expert collaboration"""
    
    def __init__(self):
        self.config = get_config()
        self._clients = {}
    
    def get_client(self, model_key: str) -> LLMClient:
        """Get or create client for model"""
        if model_key not in self._clients:
            self._clients[model_key] = LLMClient(model_key)
        return self._clients[model_key]
    
    async def call_expert(
        self,
        expert_key: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = True
    ) -> Optional[str]:
        """Call a specific expert with messages"""
        expert_config = self.config.get_expert_config(expert_key)
        model_key = expert_config["model_key"]
        client = self.get_client(model_key)
        
        return await client.chat_with_messages(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream
        )
    
    async def call_experts_parallel(
        self,
        expert_keys: List[str],
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> Dict[str, Optional[str]]:
        """Call multiple experts in parallel"""
        tasks = {}
        for expert_key in expert_keys:
            tasks[expert_key] = self.call_expert(
                expert_key=expert_key,
                messages=messages.copy(),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False
            )
        
        results = {}
        for expert_key, task in tasks.items():
            try:
                results[expert_key] = await task
            except Exception as e:
                print(f"Expert {expert_key} failed: {e}")
                results[expert_key] = None
        
        return results


# Global multi-model client instance
_multi_model_client: Optional[MultiModelClient] = None


def get_multi_model_client() -> MultiModelClient:
    """Get global multi-model client instance"""
    global _multi_model_client
    if _multi_model_client is None:
        _multi_model_client = MultiModelClient()
    return _multi_model_client
