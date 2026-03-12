"""
ui.py — Gradio UI for the YAML Wildcard Creator SD WebUI extension.

One tab:
  🎭 Characters → browse 20k Danbooru characters, search by name/tag/series,
                    send prompt tags directly to txt2img.

Entry points:
  build_ui()             – used by scripts/wildcard_creator.py (WebUI mode)
  build_standalone_ui()  – direct Gradio launch for local development
"""

from __future__ import annotations

import gradio as gr

from wildcard_creator import prompt_sender
from wildcard_creator.character_db import get_character_db


# ---------------------------------------------------------------------------
# Tab -- Character Browser
# ---------------------------------------------------------------------------

def _build_characters_tab():
    cdb = get_character_db()
    _populated = cdb.is_populated()
    _total = cdb.count() if _populated else 0
    _series_choices = ["All"] + [s for s, _ in cdb.list_series()] if _populated else ["All"]

    _NOT_POPULATED_MSG = (
        "⚠️ Character database not found.\n\n"
        "Run the scraper to populate it:\n"
        "```\npython scripts/scrape_characters.py\n```\n"
        "(~14 min, 834 pages, ~20k characters)"
    )

    with gr.Tab("🎭 Characters"):
        if not _populated:
            gr.Markdown(_NOT_POPULATED_MSG)
            return

        gr.Markdown(
            f"### Browse {_total:,} Danbooru characters\n"
            "Search by name or tag, filter by series, then send to Generate."
        )

        with gr.Row():
            with gr.Column(scale=2):
                char_search = gr.Textbox(
                    label="Search",
                    placeholder="e.g. miku, saber, blue hair…",
                    lines=1,
                )
            with gr.Column(scale=1):
                char_series = gr.Dropdown(
                    label="Series",
                    choices=_series_choices,
                    value="All",
                    interactive=True,
                )
            with gr.Column(scale=1, min_width=100):
                btn_char_search = gr.Button("🔍 Search", variant="primary")

        # Results table
        char_results = gr.Dataframe(
            headers=["name", "series", "rank"],
            datatype=["str", "str", "number"],
            label="Results",
            interactive=False,
            wrap=True,
        )
        char_results_state = gr.State([])  # full result list (with tags/image_url)

        gr.Markdown("---\n*Click a row above to load the character card.*")

        # Character card — always visible
        with gr.Row() as char_card_row:
            with gr.Column(scale=1, min_width=260):
                char_image = gr.Image(
                    label="Preview",
                    height=280,
                    interactive=False,
                )
            with gr.Column(scale=2):
                char_name_out = gr.Textbox(label="Character", interactive=False, lines=1)
                char_series_out = gr.Textbox(label="Series", interactive=False, lines=1)
                char_tags_out = gr.Textbox(label="Prompt tags", lines=4, interactive=True)
                with gr.Row():
                    btn_char_send = gr.Button("➡️ Send to Generate", variant="primary")
                    btn_char_copy = gr.Button("📋 Copy Tags")
                char_send_status = gr.Textbox(label="", interactive=False, max_lines=1)

        # ----- Events -----

        def do_search(query, series):
            results = cdb.search(
                query.strip(),
                series_filter=series if series != "All" else None,
                limit=100,
            )
            table = [[r["name"], r["series"] or "", r["rank"]] for r in results]
            return table, results

        def on_row_select(results_state, evt: gr.SelectData):
            row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
            if not results_state or row_idx >= len(results_state):
                return None, "", "", ""
            char = results_state[row_idx]
            return (
                char.get("image_url"),
                char["name"],
                char.get("series") or "",
                char.get("tags") or "",
            )

        def do_send_to_generate(tags):
            if not tags:
                return "⚠️ No tags to send"
            return prompt_sender.send_to_txt2img(tags, "")

        def do_copy_tags(tags):
            return prompt_sender.copy_positive(tags)

        btn_char_search.click(
            do_search,
            inputs=[char_search, char_series],
            outputs=[char_results, char_results_state],
        )
        char_search.submit(
            do_search,
            inputs=[char_search, char_series],
            outputs=[char_results, char_results_state],
        )
        char_results.select(
            on_row_select,
            inputs=[char_results_state],
            outputs=[char_image, char_name_out, char_series_out, char_tags_out],
        )
        btn_char_send.click(do_send_to_generate, inputs=[char_tags_out], outputs=[char_send_status])
        btn_char_copy.click(do_copy_tags, inputs=[char_tags_out], outputs=[char_send_status])


# ---------------------------------------------------------------------------

def build_ui() -> gr.Blocks:
    """
    Build the full Gradio UI (attach to SD WebUI via script_callbacks).
    """
    with gr.Blocks(analytics_enabled=False) as ui:
        gr.Markdown("# � SD Character Finder")
        _build_characters_tab()
    return ui


def build_standalone_ui() -> gr.Blocks:
    """
    Build a standalone Gradio app for local development (no SD WebUI).
    Launch with: build_standalone_ui().launch(server_port=7861)
    """
    return build_ui()


# ---------------------------------------------------------------------------
# Dev launcher (python -m wildcard_creator.ui)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7861
    app = build_standalone_ui()
    app.launch(server_port=port, server_name="127.0.0.1", share=False)
