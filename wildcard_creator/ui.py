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
            char_tags_out = gr.Textbox(label="Prompt tags", lines=4, interactive=True, elem_id="char_finder_tags_out")
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
            return gr.update(value="⚠️ No tags to send")
        return gr.update(value="✅ Sent to txt2img")

    def do_copy_tags(tags):
        if not tags:
            return gr.update(value="⚠️ No tags to copy")
        return gr.update(value="✅ Copied to clipboard")

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
    # Section 1.5 — Manual validation for pending danbooru_tag
    # =========================================================
    gr.Markdown("---\n### Manual Validation (Pending Danbooru Tags)")

    pending_limit = 200

    def _load_pending_rows():
        return cdb.list_pending_danbooru(limit=pending_limit)

    def _pending_choices(rows):
        choices = []
        for r in rows:
            series = r.get("series") or ""
            choices.append(f"{r['id']} | {r['name']} | {series}")
        return choices

    _pending_rows = _load_pending_rows()
    _pending_count = cdb.pending_danbooru_count()
    _pending_choices_init = _pending_choices(_pending_rows)

    pending_status = gr.Markdown(
        f"Pending manual review: **{_pending_count}** "
        f"(showing up to {pending_limit} in the selector)"
    )
    pending_rows_state = gr.State(_pending_rows)

    with gr.Row():
        pending_selector = gr.Dropdown(
            label="Pending entries",
            choices=_pending_choices_init,
            value=_pending_choices_init[0] if _pending_choices_init else None,
            interactive=True,
        )
        btn_pending_refresh = gr.Button("Refresh pending")

    with gr.Row():
        pending_id = gr.Textbox(label="ID", interactive=False, lines=1)
        pending_name = gr.Textbox(label="Name", interactive=False, lines=1)
        pending_series = gr.Textbox(label="Series", interactive=False, lines=1)

    pending_danbooru_tag = gr.Textbox(
        label="danbooru_tag (manual)",
        placeholder="Canonical tag with spaces, e.g. hoshino (first year) (blue archive)",
        lines=2,
        interactive=True,
    )
    with gr.Row():
        btn_pending_save = gr.Button("Save manual tag", variant="primary")
        btn_pending_next = gr.Button("Save and next")
    pending_save_status = gr.Textbox(label="", interactive=False, max_lines=1)

    def _pick_pending(choice_label, rows):
        if not choice_label or not rows:
            return "", "", "", ""
        char_id_str = choice_label.split("|", 1)[0].strip()
        try:
            char_id = int(char_id_str)
        except Exception:
            return "", "", "", ""
        for r in rows:
            if int(r["id"]) == char_id:
                return str(r["id"]), r["name"], r.get("series") or "", ""
        return "", "", "", ""

    def _reload_pending_after_save(select_next=False):
        rows = _load_pending_rows()
        choices = _pending_choices(rows)
        next_value = choices[0] if (select_next and choices) else None
        count = cdb.pending_danbooru_count()
        return (
            rows,
            gr.update(choices=choices, value=next_value),
            f"Pending manual review: **{count}** (showing up to {pending_limit} in the selector)",
        )

    def _save_pending(char_id_text, manual_tag):
        char_id_text = (char_id_text or "").strip()
        manual_tag = (manual_tag or "").strip()
        if not char_id_text:
            return gr.update(value="⚠️ Select a pending row first")
        if not manual_tag:
            return gr.update(value="⚠️ Enter a danbooru_tag first")
        try:
            char_id = int(char_id_text)
        except Exception:
            return gr.update(value="❌ Invalid character ID")
        ok = cdb.save_danbooru_tag(char_id, manual_tag)
        if not ok:
            return gr.update(value="❌ Failed to save")
        return gr.update(value="✅ Saved")

    def _save_and_next(char_id_text, manual_tag):
        status = _save_pending(char_id_text, manual_tag)
        status_text = status["value"] if isinstance(status, dict) else ""
        if not status_text.startswith("✅"):
            return (
                status,
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
            )

        rows, selector_update, count_md = _reload_pending_after_save(select_next=True)
        if not rows:
            return (
                status,
                rows,
                selector_update,
                count_md,
                "",
                "",
            )
        next_choice = selector_update["value"]
        pid, pname, pseries, _ = _pick_pending(next_choice, rows)
        return (
            status,
            rows,
            selector_update,
            count_md,
            pid,
            pname,
            pseries,
            "",
        )

    pending_selector.change(
        _pick_pending,
        inputs=[pending_selector, pending_rows_state],
        outputs=[pending_id, pending_name, pending_series, pending_danbooru_tag],
    )

    btn_pending_refresh.click(
        lambda: _reload_pending_after_save(select_next=False),
        inputs=[],
        outputs=[pending_rows_state, pending_selector, pending_status],
    )

    btn_pending_save.click(
        _save_pending,
        inputs=[pending_id, pending_danbooru_tag],
        outputs=[pending_save_status],
    ).then(
        lambda: _reload_pending_after_save(select_next=False),
        inputs=[],
        outputs=[pending_rows_state, pending_selector, pending_status],
    )

    btn_pending_next.click(
        _save_and_next,
        inputs=[pending_id, pending_danbooru_tag],
        outputs=[
            pending_save_status,
            pending_rows_state,
            pending_selector,
            pending_status,
            pending_id,
            pending_name,
            pending_series,
            pending_danbooru_tag,
        ],
    )

    if _pending_choices_init:
        _pid, _pname, _pseries, _ = _pick_pending(_pending_choices_init[0], _pending_rows)
        pending_id.value = _pid
        pending_name.value = _pname
        pending_series.value = _pseries

    # =========================================================
    # Section 2 — Live Danbooru Search (characters outside DB)
    # =========================================================
    gr.Markdown("---\n### 🔎 Search Danbooru Live\n*Find characters not in the local database, or get extra tag suggestions.*")

    _saved_login, _saved_api_key = _get_default_danbooru_auth()

    with gr.Row():
        with gr.Column(scale=3):
            live_search_input = gr.Textbox(
                label="Character name",
                placeholder="e.g. frieren, lala satalin deviluke, rem…",
                lines=1,
            )
        with gr.Column(scale=1, min_width=200):
            live_login = gr.Textbox(
                label="Danbooru login (optional)",
                lines=1,
                placeholder="username",
                value=_saved_login,
            )
        with gr.Column(scale=1, min_width=200):
            live_apikey = gr.Textbox(
                label="API key (optional)",
                lines=1,
                placeholder="key",
                type="password",
                value=_saved_api_key,
            )
        with gr.Column(scale=1, min_width=120):
            btn_live_search = gr.Button("🔍 Search", variant="primary")

    live_status = gr.Textbox(label="", interactive=False, max_lines=1, visible=False)

    # Character candidates (when multiple matches returned)
    live_candidates = gr.Radio(
        label="Matching characters — select one",
        choices=[],
        visible=False,
        interactive=True,
    )
    live_candidates_state = gr.State([])  # list of {tag, raw_tag, post_count}

    # Tag checkboxes (per category)
    with gr.Accordion("Suggested tags", open=True, visible=False) as live_tags_accordion:
        gr.Markdown("Check the tags you want to include in the prompt. Ordered by frequency in Danbooru posts.")
        with gr.Row():
            with gr.Column():
                live_tags_character = gr.CheckboxGroup(label="Character", choices=[], interactive=True, visible=False)
            with gr.Column():
                live_tags_general = gr.CheckboxGroup(label="General", choices=[], interactive=True, visible=False)
            with gr.Column():
                live_tags_copyright = gr.CheckboxGroup(label="Series / Copyright", choices=[], interactive=True, visible=False)

        live_prompt_out = gr.Textbox(
            label="Assembled prompt — edit freely before sending",
            lines=3,
            interactive=True,
            placeholder="Select tags above to assemble prompt…",
        )
        with gr.Row():
            btn_live_send = gr.Button("➡️ Send to Generate", variant="primary")
            btn_live_copy = gr.Button("📋 Copy Tags")
        live_send_status = gr.Textbox(label="", interactive=False, max_lines=1)

    # ----- helpers -----

    _live_db = DanbooruDB()

    def _do_live_search(query, login, api_key):
        query = query.strip()
        if not query:
            return (
                gr.update(value="⚠️ Enter a character name first", visible=True),
                gr.update(choices=[], visible=False),
                [],
                gr.update(visible=False),
            )
        try:
            candidates = _live_db.search_character_tags(query, login=login, api_key=api_key, limit=10)
        except Exception as exc:
            return (
                gr.update(value=f"❌ {exc}", visible=True),
                gr.update(choices=[], visible=False),
                [],
                gr.update(visible=False),
            )
        if not candidates:
            return (
                gr.update(value="⚠️ No characters found on Danbooru.", visible=True),
                gr.update(choices=[], visible=False),
                [],
                gr.update(visible=False),
            )
        choices = [f"{c['tag']}  ({c['post_count']:,} posts)" for c in candidates]
        return (
            gr.update(value=f"✅ Found {len(candidates)} match(es). Select one below.", visible=True),
            gr.update(choices=choices, value=choices[0], visible=True),
            candidates,
            gr.update(visible=False),
        )

    def _do_load_candidate(choice_label, candidates, login, api_key):
        if not choice_label or not candidates:
            return (
                gr.update(choices=[], visible=False),
                gr.update(choices=[], visible=False),
                gr.update(choices=[], visible=False),
                gr.update(visible=False),
                "",
            )
        # find selected candidate by label prefix
        raw_tag = None
        for c in candidates:
            if choice_label.startswith(c["tag"]):
                raw_tag = c["raw_tag"]
                break
        if not raw_tag:
            return (
                gr.update(choices=[], visible=False),
                gr.update(choices=[], visible=False),
                gr.update(choices=[], visible=False),
                gr.update(visible=False),
                "",
            )
        try:
            tags = _live_db.fetch_character_post_tags(raw_tag, login=login, api_key=api_key)
        except Exception as exc:
            return (
                gr.update(choices=[], visible=False),
                gr.update(choices=[], visible=False),
                gr.update(choices=[], visible=False),
                gr.update(visible=False),
                f"❌ {exc}",
            )

        char_tags  = [t["tag"] for t in tags if t["category"] == 4]
        gen_tags   = [t["tag"] for t in tags if t["category"] == 0]
        copy_tags  = [t["tag"] for t in tags if t["category"] == 3]

        human_name = raw_tag.replace("_", " ")
        initial_prompt = ", ".join([human_name] + char_tags[:3] + gen_tags[:10])

        return (
            gr.update(choices=char_tags, value=char_tags, visible=bool(char_tags)),
            gr.update(choices=gen_tags,  value=gen_tags[:15],  visible=bool(gen_tags)),
            gr.update(choices=copy_tags, value=copy_tags, visible=bool(copy_tags)),
            gr.update(visible=True),
            initial_prompt,
        )

    def _assemble_prompt(char_sel, gen_sel, copy_sel):
        parts = list(char_sel or []) + list(gen_sel or []) + list(copy_sel or [])
        return gr.update(value=", ".join(parts))

    def do_live_send(tags):
        if not tags:
            return gr.update(value="⚠️ No tags to send")
        return gr.update(value="✅ Sent to txt2img")

    def do_live_copy(tags):
        if not tags:
            return gr.update(value="⚠️ No tags to copy")
        return gr.update(value="✅ Copied to clipboard")

    # ----- events -----

    btn_live_search.click(
        _do_live_search,
        inputs=[live_search_input, live_login, live_apikey],
        outputs=[live_status, live_candidates, live_candidates_state, live_tags_accordion],
    )
    live_search_input.submit(
        _do_live_search,
        inputs=[live_search_input, live_login, live_apikey],
        outputs=[live_status, live_candidates, live_candidates_state, live_tags_accordion],
    )

    live_candidates.change(
        _do_load_candidate,
        inputs=[live_candidates, live_candidates_state, live_login, live_apikey],
        outputs=[live_tags_character, live_tags_general, live_tags_copyright, live_tags_accordion, live_send_status],
    )

    for chk in [live_tags_character, live_tags_general, live_tags_copyright]:
        chk.change(
            _assemble_prompt,
            inputs=[live_tags_character, live_tags_general, live_tags_copyright],
            outputs=[live_prompt_out],
        )

    btn_live_send.click(
        fn=do_live_send,
        inputs=[live_prompt_out],
        outputs=[live_send_status],
        js="""(tags) => {
            const promptEl = gradioApp().querySelector('#txt2img_prompt textarea');
            if (promptEl && tags) {
                promptEl.value = tags;
                promptEl.dispatchEvent(new Event('input', {bubbles: true}));
            }
            return [tags];
        }"""
    )
    btn_live_copy.click(
        fn=do_live_copy,
        inputs=[live_prompt_out],
        outputs=[live_send_status],
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
