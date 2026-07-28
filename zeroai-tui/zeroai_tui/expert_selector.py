"""
zeroai-tui: Expert Selector
"""
from typing import Optional, Callable, Dict, List
from .terminal import Terminal, Color
from .renderer import get_renderer, Style
from .components import Component
from .rich_components import Panel


class ExpertSelector(Component):
    """Expert selector component"""
    
    def __init__(self, 
                 experts: Dict[str, Dict],
                 on_select: Optional[Callable] = None,
                 id: Optional[str] = None):
        super().__init__(id)
        self.experts = experts
        self.on_select = on_select
        self._visible = False
        self._selected_index = 0
        self._filter_text = ""
        self._filtered_experts = list(experts.keys())
    
    def show(self):
        """Show the selector"""
        self._visible = True
        self._selected_index = 0
        self._filter_text = ""
        self._filtered_experts = list(self.experts.keys())
    
    def hide(self):
        """Hide the selector"""
        self._visible = False
    
    def handle_key(self, key: str) -> bool:
        """Handle key input"""
        if not self._visible:
            return False
        
        if key == '\x1b':
            # ESC - close selector
            self.hide()
            return True
        elif key == 'k' or key == '\x1b[A':
            # Up
            self._selected_index = max(0, self._selected_index - 1)
            return True
        elif key == 'j' or key == '\x1b[B':
            # Down
            self._selected_index = min(len(self._filtered_experts) - 1, self._selected_index + 1)
            return True
        elif key == '\r' or key == '\n':
            # Enter - select expert
            if self._filtered_experts:
                selected = self._filtered_experts[self._selected_index]
                if self.on_select:
                    self.on_select(selected)
                self.hide()
                return True
        elif key == '\x7f':
            # Backspace
            self._filter_text = self._filter_text[:-1]
            self._update_filter()
            return True
        elif len(key) == 1 and key.isprintable():
            # Filter
            self._filter_text += key
            self._update_filter()
            return True
        
        return False
    
    def _update_filter(self):
        """Update filtered experts list"""
        if not self._filter_text:
            self._filtered_experts = list(self.experts.keys())
        else:
            filter_lower = self._filter_text.lower()
            self._filtered_experts = [
                name for name in self.experts.keys()
                if filter_lower in name.lower()
            ]
        self._selected_index = min(self._selected_index, max(0, len(self._filtered_experts) - 1))
    
    def render(self):
        """Render the selector"""
        if not self._visible:
            return

        renderer = get_renderer()
        row, col, width, height = self.y, self.x, self.width, self.height

        # Draw panel
        panel_width = min(50, width - 4)
        panel_height = min(20, height - 4)
        panel = Panel(title="Select Expert")
        panel.set_geometry(col + 2, row + 1, panel_width, panel_height)
        panel.render()

        # Draw filter
        y = row + 3
        if y < row + height - 3:
            filter_text = f"Filter: {self._filter_text}_"
            renderer.write(y, col + 4, filter_text, Style(bold=True, fg=Color.CYAN))
            y += 1

        # Draw experts
        for i, expert_name in enumerate(self._filtered_experts):
            if y >= row + height - 3:
                break

            is_selected = (i == self._selected_index)
            expert_config = self.experts.get(expert_name, {})
            description = expert_config.get("description", "")[:30]

            # Expert name
            name_style = Style(bold=True, fg=Color.BRIGHT_YELLOW if is_selected else Color.WHITE)
            renderer.write(y, col + 4, f"{expert_name}", name_style)

            # Description
            if description:
                desc_style = Style(fg=Color.DIM)
                renderer.write(y, col + 20, description, desc_style)

            y += 1

        # Draw help
        if y < row + height - 2:
            help_text = "↑↓:Navigate Enter:Select ESC:Cancel Type:Filter"
            renderer.write(y, col + 4, help_text, Style(fg=Color.DIM))
