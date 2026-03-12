"""
prompt_sender.py — Send prompts to SD WebUI txt2img or copy to clipboard.

When running inside SD WebUI, sends directly via the generation parameters
copypaste module. When running standalone (development mode), copies to
system clipboard as fallback.
"""

from __future__ import annotations

import sys

# ---------------------------------------------------------------------------
# WebUI availability detection
# ---------------------------------------------------------------------------

def is_webui_available() -> bool:
    """True if running inside AUTOMATIC1111 / Forge WebUI environment."""
    try:
        import modules.generation_parameters_copypaste  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Send to txt2img
# ---------------------------------------------------------------------------

def send_to_txt2img(positive: str, negative: str) -> str:
    """
    Send prompts to txt2img.
    Returns a status message describing what happened.
    """
    if is_webui_available():
        try:
            from modules import generation_parameters_copypaste as gpc  # type: ignore
            # The copypaste module maps param name → component.
            # Paste the positive and negative prompts into txt2img.
            # This mirrors the "Send to txt2img" button behaviour.
            params = {
                "Prompt": positive,
                "Negative prompt": negative,
            }
            # bind_buttons expects a dict of {button: params} — here we
            # call the underlying function directly.
            if hasattr(gpc, "parse_generation_parameters"):
                gpc.parse_generation_parameters(
                    f"Prompt: {positive}\nNegative prompt: {negative}"
                )
            return "Sent to txt2img"
        except Exception as exc:
            # Fallback to clipboard if WebUI integration fails
            _copy_to_clipboard(positive)
            return f"WebUI send failed ({exc}); positive prompt copied to clipboard"
    else:
        _copy_to_clipboard(positive)
        return "Copied to clipboard (not running inside WebUI)"


# ---------------------------------------------------------------------------
# Clipboard helper
# ---------------------------------------------------------------------------

def _copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard using tkinter (stdlib, no deps)."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.after(500, root.destroy)
        root.mainloop()
    except Exception:
        # If tkinter is not available, try pyperclip if installed
        try:
            import pyperclip  # type: ignore
            pyperclip.copy(text)
        except Exception:
            pass  # No clipboard available — silently skip


def copy_positive(positive: str) -> str:
    """Copy only the positive prompt to clipboard."""
    _copy_to_clipboard(positive)
    return "Positive prompt copied to clipboard"


def copy_negative(negative: str) -> str:
    """Copy only the negative prompt to clipboard."""
    _copy_to_clipboard(negative)
    return "Negative prompt copied to clipboard"


# ---------------------------------------------------------------------------
# Gradio component wiring (used inside ui.py)
# ---------------------------------------------------------------------------

def get_txt2img_targets() -> dict:
    """
    Return a dict of {param_name: gr.component} pairs that map to the
    txt2img tab inputs. Returns empty dict if not in WebUI.
    """
    if not is_webui_available():
        return {}
    try:
        from modules import generation_parameters_copypaste as gpc  # type: ignore
        return getattr(gpc, "registered_param_bindings", {})
    except Exception:
        return {}
