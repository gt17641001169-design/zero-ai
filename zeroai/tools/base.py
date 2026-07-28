"""Base class for ZeroAI tools"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import inspect


class ToolError(Exception):
    """Base tool error"""
    pass


class ToolExecutionError(ToolError):
    """Tool execution failed"""
    pass


class ToolValidationError(ToolError):
    """Invalid tool parameters"""
    pass


class Tool(ABC):
    """Base class for all tools"""
    
    name: str
    description: str
    parameters: Dict[str, Any]
    
    def __init__(self):
        """Initialize tool"""
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Execute the tool with given parameters"""
        pass
    
    def to_schema(self) -> Dict[str, Any]:
        """Convert tool to OpenAI function schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
    
    def validate_params(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and filter tool parameters"""
        valid_params = set(inspect.signature(self.execute).parameters)
        filtered = {k: v for k, v in args.items() if k in valid_params}
        
        # Check required params
        missing = valid_params - set(filtered.keys())
        if missing:
            # Check if params have defaults
            sig = inspect.signature(self.execute)
            for param_name in missing:
                param = sig.parameters.get(param_name)
                if param and param.default is inspect.Parameter.empty:
                    raise ToolValidationError(f"Missing required parameter: {param_name}")
        
        return filtered


class ToolRegistry:
    """Auto-discover and register tools"""
    
    _tools: Dict[str, Tool] = {}
    
    @classmethod
    def register(cls, tool: Tool):
        """Register a tool"""
        cls._tools[tool.name] = tool
    
    @classmethod
    def get(cls, name: str) -> Optional[Tool]:
        """Get a tool by name"""
        return cls._tools.get(name)
    
    @classmethod
    def get_all(cls) -> Dict[str, Tool]:
        """Get all registered tools"""
        return cls._tools.copy()
    
    @classmethod
    def get_schemas(cls) -> List[Dict[str, Any]]:
        """Get schemas for all registered tools"""
        return [tool.to_schema() for tool in cls._tools.values()]
    
    @classmethod
    def clear(cls):
        """Clear all registered tools"""
        cls._tools.clear()
    
    @classmethod
    def execute_tool(cls, name: str, **kwargs) -> str:
        """Execute a tool by name"""
        tool = cls.get(name)
        if tool is None:
            raise ToolValidationError(f"Unknown tool: {name}")
        
        try:
            validated_args = tool.validate_params(kwargs)
            return tool.execute(**validated_args)
        except ToolValidationError:
            raise
        except Exception as e:
            raise ToolExecutionError(f"Tool execution failed: {e}")


def register_tool(tool_class):
    """Decorator to register a tool class"""
    tool_instance = tool_class()
    ToolRegistry.register(tool_instance)
    return tool_class
