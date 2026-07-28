"""
zeroai-tui: Settings Dialog
"""
from typing import Optional, Callable, Dict, Any
from .terminal import Terminal, Color
from .renderer import get_renderer, Style
from .components import Component, Text, Box, Input
from .rich_components import Panel, StatusLine
from .app import App


class SettingsDialog(Component):
    """Settings dialog component"""
    
    def __init__(self, 
                 settings: Dict[str, Any],
                 on_save: Optional[Callable] = None,
                 on_cancel: Optional[Callable] = None,
                 id: Optional[str] = None):
        super().__init__(id)
        self.settings = settings.copy()
        self.on_save = on_save
        self.on_cancel = on_cancel
        self._visible = False
        self._selected_index = 0
        self._editing = False
        self._edit_value = ""
        
        # Settings fields
        self.fields = [
            ("model", "Default Model"),
            ("temperature", "Temperature"),
            ("max_tokens", "Max Tokens"),
            ("theme", "Theme"),
        ]
    
    def show(self):
        """Show the dialog"""
        self._visible = True
        self._selected_index = 0
        self._editing = False
    
    def hide(self):
        """Hide the dialog"""
        self._visible = False
        self._editing = False
    
    def handle_key(self, key: str) -> bool:
        """Handle key input"""
        if not self._visible:
            return False
        
        if self._editing:
            # Edit mode
            if key == '\r' or key == '\n':
                # Save edit
                field_key = self.fields[self._selected_index][0]
                self.settings[field_key] = self._edit_value
                self._editing = False
                return True
            elif key == '\x1b':
                # Cancel edit
                self._editing = False
                return True
            elif key == '\x7f':
                # Backspace
                self._edit_value = self._edit_value[:-1]
                return True
            elif len(key) == 1 and key.isprintable():
                self._edit_value += key
                return True
        else:
            # Navigation mode
            if key == '\x1b':
                # ESC - close dialog
                if self.on_cancel:
                    self.on_cancel()
                self.hide()
                return True
            elif key == 'k' or key == '\x1b[A':
                # Up
                self._selected_index = max(0, self._selected_index - 1)
                return True
            elif key == 'j' or key == '\x1b[B':
                # Down
                self._selected_index = min(len(self.fields) - 1, self._selected_index + 1)
                return True
            elif key == '\r' or key == '\n':
                # Enter - start edit
                self._editing = True
                field_key = self.fields[self._selected_index][0]
                self._edit_value = str(self.settings.get(field_key, ""))
                return True
            elif key == 's':
                # Save
                if self.on_save:
                    self.on_save(self.settings)
                self.hide()
                return True
        
        return False
    
    def render(self):
        """Render the dialog"""
        if not self._visible:
            return

        renderer = get_renderer()
        row, col, width, height = self.y, self.x, self.width, self.height

        # Draw panel
        panel_width = min(60, width - 4)
        panel_height = min(20, height - 4)
        panel = Panel(title="Settings")
        panel.set_geometry(col + 2, row + 1, panel_width, panel_height)
        panel.render()

        # Draw fields
        y = row + 3
        for i, (key, label) in enumerate(self.fields):
            if y >= row + height - 3:
                break

            value = self.settings.get(key, "")
            is_selected = (i == self._selected_index)

            # Label
            label_style = Style(bold=True, fg=Color.CYAN if is_selected else Color.WHITE)
            renderer.write(y, col + 4, f"{label}:", label_style)

            # Value
            if is_selected and self._editing:
                # Edit mode
                value_text = f"> {self._edit_value}_"
                value_style = Style(bold=True, fg=Color.BRIGHT_YELLOW)
            else:
                value_text = f"  {value}"
                value_style = Style(fg=Color.BRIGHT_WHITE if is_selected else Color.WHITE)

            renderer.write(y, col + 25, value_text, value_style)
            y += 1

        # Draw help
        if y < row + height - 2:
            help_text = "↑↓:Navigate Enter:Edit s:Save ESC:Cancel"
            renderer.write(y, col + 4, help_text, Style(fg=Color.DIM))


class SettingsScreen(App):
    """Settings screen"""
    
    def __init__(self, settings: Dict[str, Any]):
        super().__init__()
        self.settings = settings.copy()
        self.dialog = SettingsDialog(
            settings=self.settings,
            on_save=self._on_save,
            on_cancel=self._on_cancel
        )
        self._saved = False
    
    def build(self):
        """Build the screen"""
        return self.dialog
    
    def _on_save(self, settings: Dict[str, Any]):
        """Handle save"""
        self.settings = settings
        self._saved = True
        self.stop()
    
    def _on_cancel(self):
        """Handle cancel"""
        self.stop()
    
    def get_settings(self) -> Dict[str, Any]:
        """Get the settings"""
        return self.settings
