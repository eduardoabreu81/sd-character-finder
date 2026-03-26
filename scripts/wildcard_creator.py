"""
SD WebUI extension entry point for Wildcard Creator.
Registers the Wildcard Creator tab via script_callbacks.
"""
import os
import sys

import gradio as gr

# Ensure the extension root is on the path so wildcard_creator package is importable
_ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ext_dir not in sys.path:
    sys.path.insert(0, _ext_dir)

try:
    from modules import script_callbacks, shared

    def on_ui_tabs():
        from wildcard_creator.ui import build_ui
        blocks = build_ui()
        return [(blocks, "Danbooru Characters", "sd_character_finder")]

    def on_ui_settings():
        section = ("sd_character_finder", "SD Character Finder")
        shared.opts.add_option(
            "sdcf_danbooru_login",
            shared.OptionInfo(
                "",
                "Danbooru login",
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_danbooru_api_key",
            shared.OptionInfo(
                "",
                "Danbooru API key (Optional)",
                section=section,
                component=gr.Textbox,
                component_args={"type": "password"},
            ),
        )
        shared.opts.add_option(
            "sdcf_search_limit",
            shared.OptionInfo(
                30,
                "Character results per page (max 30)",
                component=gr.Slider,
                component_args={"minimum": 5, "maximum": 30, "step": 1},
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_gallery_thumb_size",
            shared.OptionInfo(
                160,
                "Gallery thumbnail size (px)",
                component=gr.Slider,
                component_args={"minimum": 100, "maximum": 350, "step": 10},
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_gallery_columns",
            shared.OptionInfo(
                5,
                "Gallery cards per row",
                component=gr.Slider,
                component_args={"minimum": 2, "maximum": 12, "step": 1},
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_add_deduplicate",
            shared.OptionInfo(
                True,
                "Add to txt2img: Deduplicate incoming tags",
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_live_n_posts",
            shared.OptionInfo(
                120,
                "Live API: Number of posts to check",
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_live_top_n",
            shared.OptionInfo(
                40,
                "Live API: Number of top tags to return",
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_live_min_freq",
            shared.OptionInfo(
                0.08,
                "Live API: Minimum tag frequency",
                component=gr.Slider,
                component_args={"minimum": 0.0, "maximum": 1.0, "step": 0.01},
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_default_wildcards_path",
            shared.OptionInfo(
                "",
                "Default folder for exported wildcards (absolute path or relative to sd-webui root)",
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_scraper_rate_limit",
            shared.OptionInfo(
                1.0,
                "API rate limit (seconds between requests)",
                component=gr.Slider,
                component_args={"minimum": 0.0, "maximum": 10.0, "step": 0.1},
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_live_cache_ttl",
            shared.OptionInfo(
                1800,
                "Live API Cache TTL (seconds)",
                section=section,
            ),
        )
        shared.opts.add_option(
            "sdcf_debug_logging",
            shared.OptionInfo(
                False,
                "Enable debug logging",
                section=section,
            ),
        )

    script_callbacks.on_ui_tabs(on_ui_tabs)
    script_callbacks.on_ui_settings(on_ui_settings)

except Exception as e:
    print(f"[WildcardCreator] Failed to register tab: {e}")
