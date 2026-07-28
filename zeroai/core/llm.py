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
