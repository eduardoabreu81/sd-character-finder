# Rebuilding and Recovering the Character Catalogue

The packaged catalogue `data/catalog/characters-v2.db` can be recovered two ways:

1. **Redownload** the exact published artifact and verify it against the manifest.
   This is what the extension does automatically and what most situations need.
2. **Rebuild** it from tracked inputs when the published artifact itself has to
   be regenerated (a data correction, a schema change, a new source import).

Both paths end at the same guarantee: a database whose size, SHA-256, schema
version, SQLite integrity, relationships, and record counts match
`data/characters.manifest.json`.

---

## 1. Redownload (verified recovery)

The manifest pins the published artifact:

```json
"download_url": "https://github.com/eduardoabreu81/sd-character-finder/releases/download/v0.7.0/characters-v2-20260724.db"
```

Downloads are restricted to trusted GitHub HTTPS hosts
(`_ALLOWED_DOWNLOAD_HOSTS` in `wildcard_creator/catalog_health.py`), verified by
size and SHA-256 while streaming, validated as a catalogue before installation,
and installed atomically with `os.replace`.

### From the UI

Under **Settings → SD Character Finder**:

- **Automatically redownload the verified character catalogue when validation
  fails** — restores a missing or damaged database on the next startup.
- **Redownload the verified character catalogue on next UI startup** — forces
  one verified redownload, then resets itself.

### From a shell

```bash
python -c "from wildcard_creator.catalog_health import redownload_catalog; print(redownload_catalog())"
```

---

## 2. Rebuild from tracked inputs

### Inputs

| Input | Origin |
|---|---|
| `data/generated/characters_legacy.db` | Byte-identical copy of the tracked `data/characters.db` |
| `data/anima_import/characters.csv` | Tracked AnimaDex character export |
| `data/catalog_overrides.json` | Tracked manual review decisions |
| `data/e621_series_implications.json` | Tracked e621 series evidence |
| `data/generated/anidb_anime_titles.xml.gz` | Downloaded by `scripts/fetch_anidb_titles.py` |
| `data/generated/danbooru_tag_aliases.json` | Cache built by `scripts/audit_danbooru_aliases.py` |

Everything under `data/generated/` is disposable and regenerated on demand. The
first four inputs are tracked, so a clean clone plus the commands below is
enough to reproduce the catalogue.

### Commands

```bash
# 1. Stage the legacy source database the builder reads from.
mkdir -p data/generated
cp data/characters.db data/generated/characters_legacy.db

# 2. Fetch the AniDB official title dump (public, no credentials).
python scripts/fetch_anidb_titles.py

# 3. Optional: refresh the Danbooru alias cache (slow, uses the public API).
#    Skip this to reuse an existing cache.
python scripts/audit_danbooru_aliases.py

# 4. Build the catalogue into data/generated/characters_v2.db.
python scripts/build_character_catalog_v2.py

# 5. Promote it and regenerate the manifest.
cp data/generated/characters_v2.db data/catalog/characters-v2.db
python scripts/generate_catalog_manifest.py

# 6. Verify.
python -m pytest tests -q
```

The builder refuses to emit a database whose AnimaDex prompts differ from the
bundled ones, and it never mutates `data/characters.db`. Danbooru, e621, and
AnimaDex prompts are immutable per-source artifacts; metadata enrichment must
never reformat them.

### Publishing a rebuilt catalogue

`scripts/generate_catalog_manifest.py` writes `download_url` from its
`DEFAULT_DOWNLOAD_URL` constant. When publishing a new catalogue:

1. Bump `DEFAULT_DOWNLOAD_URL` to the release asset URL of the new tag.
2. Regenerate the manifest and commit it with the database.
3. Attach the database to that GitHub release under the same asset name.
4. Confirm `test_bundled_v2_catalogue_matches_its_manifest` passes and that the
   published URL returns the exact bytes and digest the manifest declares.

Release assets are used instead of `raw.githubusercontent.com` URLs so recovery
never depends on a specific commit remaining reachable.

---

## 3. Re-auditing e621 series evidence

`data/e621_series_implications.json` is a tracked *output* of an offline audit,
so rebuilding the catalogue does not require the e621 exports. Regenerate it
only when adopting a newer export:

```bash
# Place the official daily export under data/generated/e621_export/<YYYY-MM-DD>/
python scripts/audit_e621_series.py
```

The audit resolves active aliases and active character-to-copyright
implications offline. Wiki pages and post samples
(`scripts/fetch_e621_post_evidence.py`) are supplementary review evidence, never
a substitute for an unambiguous official relation. Where evidence is
insufficient the series stays empty; generic tags, publishers, and positional
heuristics must never fill one automatically.
