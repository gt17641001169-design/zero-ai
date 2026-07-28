"""
ZeroAI Integration: Bridge between zeroai-tui and ZeroAI logic
"""
import sys
import os
import asyncio
from typing import Optional, Callable, Dict, Any

# Add paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from zeroai_tui.zai_chat import ZeroAIChat


class ZeroAIIntegration:
    """Integration layer for ZeroAI"""
    
    def __init__(self):
        self.chat: Optional[ZeroAIChat] = None
        self._generate_callback: Optional[Callable] = None
        self._router = None
        self._llm_client = None
        self._context = None
        self._experts = {}
        
    def init_core(self):
        """Initialize ZeroAI core modules"""
        try:
            from zeroai.core.expert import get_expert_router
            from zeroai.core.llm import get_multi_model_client
            from zeroai.core.context import get_context_manager
            from zeroai.core.config import get_config
            
            self._router = get_expert_router()
            self._llm_client = get_multi_model_client()
            self._context = get_context_manager()
            
            # Load expert configs
            config = get_config()
            self._experts = config._config.get("experts", {})
            
            return True
        except ImportError as e:
            print(f"Warning: Could not import zeroai core: {e}")
            return False
    
    def set_generate_callback(self, callback: Callable):
        """Set the AI generation callback"""
        self._generate_callback = callback
    
    async def generate_response(self, text: str) -> Dict[str, Any]:
        """Generate AI response using expert routing"""
        if not self._router or not self._llm_client:
            return {"expert": "demo", "response": f"Echo: {text}"}
        
        try:
            # Route to expert
            expert_key = await self._router.route_by_glm(text)
            
            # Get expert config
            expert_config = self._experts.get(expert_key, {})
            model_key = expert_config.get("model_key", "glm")
            
            # Build messages
            messages = [
                {"role": "system", "content": expert_config.get("system_prompt", "You are ZeroAI.")},
                {"role": "user", "content": text}
            ]
            
            # Add context
            if self._context:
                context_msgs = self._context.get_messages()
                if context_msgs:
                    messages = context_msgs + messages[-2:]
            
            # Call expert
            response = await self._llm_client.call_expert(
                expert_key=expert_key,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
                stream=False
            )
            
            # Update context
            if self._context:
                self._context.add_message("user", text)
                self._context.add_assistant_message(response or "")
                self._context.compress_if_needed()
            
            return {
                "expert": expert_key,
                "response": response or "No response generated."
            }
            
        except Exception as e:
            return {
                "expert": "error",
                "response": f"Error: {str(e)[:200]}"
            }
    
    def start(self):
        """Start the chat interface"""
        self.chat = ZeroAIChat()
        self.chat.set_callbacks(
            on_send=self._handle_send,
            on_exit=self._handle_exit
        )
        
        # Initialize core
        core_ok = self.init_core()
        
        # Set initial status
        if core_ok:
            self.chat.set_status("Ready | Experts loaded | Ctrl+C to exit")
        else:
            self.chat.set_status("Demo mode | Ctrl+C to exit")
        
        # Run
        self.chat.run()
    
    def _handle_send(self, text: str):
        """Handle user message"""
        if self._generate_callback:
            # Custom callback mode
            try:
                response = self._generate_callback(text)
                self.chat.add_ai_message(response, expert="AI")
            except Exception as e:
                self.chat.add_ai_message(f"Error: {str(e)[:100]}")
            return
        
        # Async generation
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context, use sync wrapper
                result = asyncio.ensure_future(self.generate_response(text))
                # Note: In real implementation, need proper async handling
                self.chat.set_status("Thinking...")
                # For now, use sync fallback
                response = self._sync_generate(text)
                self.chat.add_ai_message(response, expert="AI")
            else:
                result = loop.run_until_complete(self.generate_response(text))
                self.chat.add_ai_message(result["response"], expert=result["expert"])
        except Exception as e:
            # Fallback to sync
            response = self._sync_generate(text)
            self.chat.add_ai_message(response, expert="AI")
    
    def _sync_generate(self, text: str) -> str:
        """Synchronous generation fallback"""
        if self._generate_callback:
            return self._generate_callback(text)
        
        if not self._router or not self._llm_client:
            return f"Echo: {text}"
        
        try:
            # Use sync routing
            expert_key = self._router.route_by_keywords(text)
            expert_config = self._experts.get(expert_key, {})
            
            return f"[{expert_key}] I received your message. (Async generation not available in sync mode)"
        except Exception as e:
            return f"Error: {str(e)[:100]}"
    
    def _handle_exit(self):
        """Handle exit"""
        # Clear context on exit
        if self._context:
            self._context.clear()
        print("Exiting ZeroAI...")


def create_demo_app():
    """Create a demo app for testing"""
    integration = ZeroAIIntegration()
    
    # Simple echo callback for testing
    def echo_callback(text: str) -> str:
        return f"I received your message: {text}"
    
    integration.set_generate_callback(echo_callback)
    return integration


def main():
    """Run integration demo"""
    print("ZeroAI Integration Demo")
    print("=" * 40)
    print("This connects zeroai-tui with ZeroAI logic")
    print("Press Ctrl+C to exit")
    print()
    
    integration = create_demo_app()
    integration.start()


if __name__ == "__main__":
    main()
