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
from wildcard_creator.danbooru import DanbooruDB


def _get_default_danbooru_auth() -> tuple[str, str]:
    """Read Danbooru credentials from WebUI Settings when available."""
    try:
        from modules import shared  # type: ignore
        login = str(getattr(shared.opts, "sdcf_danbooru_login", "") or "")
        api_key = str(getattr(shared.opts, "sdcf_danbooru_api_key", "") or "")
        return login, api_key
    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# Tab -- Character Browser
# ---------------------------------------------------------------------------

def _build_characters_content():
    """Renders the character browser UI directly into the current Blocks context."""
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
        with gr.Column(scale=1):
            tag_status_filter = gr.Dropdown(
                label="Danbooru tag",
                choices=["All", "Missing Danbooru Tag", "Has Danbooru Tag"],
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

    # Character card
    with gr.Row():
        with gr.Column(scale=1, min_width=260):
            char_image = gr.Image(
                label="Preview",
                height=280,
                interactive=False,
            )
        with gr.Column(scale=2):
            char_name_out = gr.Textbox(label="Character", interactive=False, lines=1)
            char_series_out = gr.Textbox(label="Series", interactive=False, lines=1)
            char_danbooru_tag_out = gr.Textbox(
                label="Danbooru tag (canonical)",
                lines=1,
                interactive=True,
                placeholder="e.g. rosalina (mario)",
            )
            char_tags_out = gr.Textbox(label="Prompt tags", lines=4, interactive=True, elem_id="char_finder_tags_out")
            with gr.Row():
                btn_char_send = gr.Button("➡️ Send to Generate", variant="primary")
                btn_char_copy = gr.Button("📋 Copy Tags")
                btn_char_save_tag = gr.Button("💾 Save Danbooru Tag")
            char_selected_id = gr.State(None)
            char_send_status = gr.Textbox(label="", interactive=False, max_lines=1)

    # ----- Events -----

    def do_search(query, series, tag_status):
        query = (query or "").strip()
        series = (series or "All").strip() or "All"
        tag_status = (tag_status or "All").strip() or "All"
        try:
            results = cdb.search(
                query,
                series_filter=series if series != "All" else None,
                tag_status_filter=tag_status,
                limit=100,
            )
            table = [[r["name"], r["series"] or "", r["rank"]] for r in results]
            return table, results
        except Exception:
            return [], []

    def on_row_select(results_state, evt: gr.SelectData):
        row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        if not results_state or row_idx >= len(results_state):
            return None, "", "", "", "", None
        char = results_state[row_idx]
        canonical_tag = (char.get("danbooru_tag") or "").strip()
        prompt_value = canonical_tag or (char.get("tags") or "")
        return (
            char.get("image_url"),
            char["name"],
            char.get("series") or "",
            canonical_tag,
            prompt_value,
            char.get("id"),
        )

    def save_manual_danbooru_tag(selected_id, manual_tag):
        if not selected_id:
            return gr.update(value="⚠️ Select a character first"), gr.update()
        manual_tag = (manual_tag or "").strip()
        if not manual_tag:
            return gr.update(value="⚠️ Enter a Danbooru tag first"), gr.update()
        ok = cdb.save_danbooru_tag(int(selected_id), manual_tag)
        if not ok:
            return gr.update(value="❌ Failed to save Danbooru tag"), gr.update()
        return gr.update(value="✅ Danbooru tag saved"), gr.update(value=manual_tag)

    def do_send_to_generate(tags):
        if not tags:
            return gr.update(value="⚠️ No tags to send")
        return gr.update(value="✅ Sent to txt2img")

    def do_copy_tags(tags):
        if not tags:
            return gr.update(value="⚠️ No tags to copy")
        return gr.update(value="✅ Copied to clipboard")

    btn_char_search.click(
        do_search,
        inputs=[char_search, char_series, tag_status_filter],
        outputs=[char_results, char_results_state],
    )
    char_search.submit(
        do_search,
        inputs=[char_search, char_series, tag_status_filter],
        outputs=[char_results, char_results_state],
    )
    char_results.select(
        on_row_select,
        inputs=[char_results_state],
        outputs=[char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id],
    )
    btn_char_save_tag.click(
        save_manual_danbooru_tag,
        inputs=[char_selected_id, char_danbooru_tag_out],
        outputs=[char_send_status, char_tags_out],
    )
    btn_char_send.click(
        fn=do_send_to_generate,
        inputs=[char_tags_out],
        outputs=[char_send_status],
        js="""(tags) => {
            const promptEl = gradioApp().querySelector('#txt2img_prompt textarea');
            if (promptEl && tags) {
                promptEl.value = tags;
                promptEl.dispatchEvent(new Event('input', {bubbles: true}));
            }
            return [tags];
        }"""
    )
    btn_char_copy.click(
        fn=do_copy_tags,
        inputs=[char_tags_out],
        outputs=[char_send_status],
        js="""(tags) => {
            if (!tags) return [tags];
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(tags);
            } else {
                const ta = document.createElement('textarea');
                ta.value = tags;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            return [tags];
        }"""
    )

    # =========================================================
    # Extra tags (discrete mode)
    # =========================================================
    with gr.Accordion("Extra tags from Danbooru (optional)", open=False):
        extra_enabled = gr.Checkbox(
            label="Enable extra-tag suggestions for selected character",
            value=False,
        )
        with gr.Row():
            btn_extra_fetch = gr.Button("Fetch extra tags")
            btn_extra_apply = gr.Button("Apply selected extras")
        extra_tag_choices = gr.CheckboxGroup(
            label="Suggested extra tags",
            choices=[],
            value=[],
            interactive=True,
            visible=False,
        )
        extra_status = gr.Textbox(label="", interactive=False, max_lines=1)

    _live_db = DanbooruDB()

    def _fetch_extra_tags(enabled, selected_name, manual_danbooru_tag):
        if not enabled:
            return gr.update(choices=[], value=[], visible=False), gr.update(value="⚠️ Enable extra-tag suggestions first")

        seed = (manual_danbooru_tag or selected_name or "").strip()
        if not seed:
            return gr.update(choices=[], value=[], visible=False), gr.update(value="⚠️ Select a character first")

        login, api_key = _get_default_danbooru_auth()
        try:
            tags = _live_db.fetch_character_post_tags(
                seed,
                login=login,
                api_key=api_key,
                n_posts=120,
                top_n=40,
                min_freq=0.08,
            )
        except Exception as exc:
            return gr.update(choices=[], value=[], visible=False), gr.update(value=f"❌ {exc}")

        extras = [t["tag"] for t in tags if t.get("category") in {0, 3}]
        if not extras:
            return gr.update(choices=[], value=[], visible=False), gr.update(value="⚠️ No useful extra tags found")

        default_selected = extras[:12]
        return (
            gr.update(choices=extras, value=default_selected, visible=True),
            gr.update(value=f"✅ Loaded {len(extras)} extra tags"),
        )

    def _apply_extra_tags(enabled, current_prompt, selected_extras):
        if not enabled:
            return gr.update(), gr.update(value="⚠️ Enable extra-tag suggestions first")

        selected_extras = list(selected_extras or [])
        if not selected_extras:
            return gr.update(), gr.update(value="⚠️ Select at least one extra tag")

        current_parts = [p.strip() for p in (current_prompt or "").split(",") if p.strip()]
        seen = {p.lower() for p in current_parts}
        added = []
        for tag in selected_extras:
            if tag.lower() not in seen:
                current_parts.append(tag)
                seen.add(tag.lower())
                added.append(tag)

        if not added:
            return gr.update(value=", ".join(current_parts)), gr.update(value="ℹ️ All selected tags were already present")

        return (
            gr.update(value=", ".join(current_parts)),
            gr.update(value=f"✅ Added {len(added)} extra tag(s)"),
        )

    btn_extra_fetch.click(
        _fetch_extra_tags,
        inputs=[extra_enabled, char_name_out, char_danbooru_tag_out],
        outputs=[extra_tag_choices, extra_status],
    )

    btn_extra_apply.click(
        _apply_extra_tags,
        inputs=[extra_enabled, char_tags_out, extra_tag_choices],
        outputs=[char_tags_out, extra_status],
    )


# ---------------------------------------------------------------------------

def build_ui() -> gr.Blocks:
    """
    Build the full Gradio UI (attach to SD WebUI via script_callbacks).
    Content renders directly inside Blocks — the WebUI wraps it in a tab via on_ui_tabs tuple.
    """
    with gr.Blocks(analytics_enabled=False) as ui:
        _build_characters_content()
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
