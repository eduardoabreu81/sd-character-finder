"""
SD WebUI extension entry point for Wildcard Creator.
Registers the Wildcard Creator tab via script_callbacks.
"""
import os
import sys

# Ensure the extension root is on the path so wildcard_creator package is importable
_ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ext_dir not in sys.path:
    sys.path.insert(0, _ext_dir)

try:
    from modules import script_callbacks

    def on_ui_tabs():
        from wildcard_creator.ui import build_ui
        blocks = build_ui()
        return [(blocks, "Danbooru Characters", "sd_character_finder")]

    script_callbacks.on_ui_tabs(on_ui_tabs)

except Exception as e:
    print(f"[WildcardCreator] Failed to register tab: {e}")
