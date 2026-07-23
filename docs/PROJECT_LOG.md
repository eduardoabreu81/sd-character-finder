# PROJECT_LOG

### [2026-07-23] Character Catalogue v2 — Validation, Recovery, and Local Prompts

**What changed:**
- Added `data/characters.manifest.json` as the authority for packaged-database
  size, SHA-256, schema, table counts, and provider counts.
- Added startup validation covering the manifest checksum, schema v5,
  `PRAGMA quick_check`, foreign keys, core table counts, and source counts.
- Added verified catalogue recovery through WebUI settings and an in-tab error
  banner. Downloads are restricted to trusted GitHub HTTPS hosts, validated in a
  temporary file, and installed with an atomic replace only after every check passes.
- Added source-specific local prompt overrides to `data/user_overrides_v2.json`
  schema v3. The override records the source prompt hash and is ignored with a
  visible review state if a later catalogue changes its base prompt.
- Added **Save prompt** and **Source prompt** actions. Saving a prompt never
  mutates `source_records.prompt_raw`; Danbooru, e621, and Anima overrides remain
  independent.
- Kept **Save lookup tag** as a Danbooru-only live-query override and kept
  Danbooru availability based on actual source representations.
- Changed runtime series display policy to prefer a verified official English
  title, with original transcription, Japanese title, and all provider titles
  retained as searchable aliases.
- Rebuilt the packaged catalogue and generated the matching recovery manifest.

**Validation results:**
- Rebuilt 39,008 variations and 59,508 representations.
- Verified all 36,492 Anima prompts and detected zero prompt changes across all
  59,508 source records.
- Selected official English display names for 1,070 accepted series. `pokemon`
  now displays as `Pokemon`; `Pocket Monsters` and `ポケットモンスター` remain
  searchable aliases.
- The rebuilt 82,882,560-byte catalogue has SHA-256
  `8e1efa43e801d05ad5672ff0b0642e8a35b7d1485f191f6b83164eca5879271a`.
- SQLite integrity passed, foreign-key errors remained zero, and all 24 automated
  tests passed.
- A real Hex Maniac override test removed only `large breasts` from the Danbooru
  effective prompt, preserved `huge breasts`, left the Anima prompt unchanged,
  and left the packaged catalogue validation healthy.

**Known validation boundary:**
- The complete UI still requires testing in the user's remote A1111/Forge host.
  Local Gradio 6.9.0 rejects the project's existing Gradio 3/4 Dataframe
  `height` argument and is not a representative visual runtime.

**Files changed:**
- `data/characters.db`
- `data/characters.manifest.json`
- `wildcard_creator/catalog_health.py`
- `wildcard_creator/character_db.py`
- `wildcard_creator/ui.py`
- `scripts/build_character_catalog_v2.py`
- `scripts/generate_catalog_manifest.py`
- `scripts/wildcard_creator.py`
- `tests/test_build_character_catalog_v2.py`
- `tests/test_catalog_health.py`
- `.gitignore`
- `README.md`

### [2026-07-23] Character Catalogue v2 — Clean Runtime Branch

**What changed:**
- Created `feat/canonical-characters-v2` as a clean-install branch with no legacy
  database toggle or compatibility adapter.
- Upgraded the catalogue builder to schema v5 and materialized three explicit
  runtime layers: canonical characters, reviewed character variations, and
  source-specific representations.
- Each representation points to exactly one immutable source record containing
  its original prompt, trigger, image, rank, and provider metadata.
- Replaced the legacy runtime database reader with a query-only v2 reader.
  Searches now return one variation and hydrate all available representations,
  while source filters select the matching prompt/image bundle.
- Added availability filtering for reviewed exclusives, source-only candidates,
  and multi-source variations. Provisional source-only rows are not presented as
  reviewed exclusives.
- Added the representation selector to the character card. Switching Danbooru,
  e621, or Anima updates the prompt, trigger, image, and active metadata together.
- Added canonical/variation/source badges, representation-specific thumbnail
  cache keys, and a result-scroll reset for new searches.
- Moved manual Danbooru lookup tags to `data/user_overrides_v2.json`. Saving a
  lookup tag can no longer overwrite a provider prompt.
- Replaced the branch's packaged `data/characters.db` with the schema-v5
  catalogue. The ignored legacy input remains local only under `data/generated/`
  for repeatable rebuilds.

**Build and audit results:**
- Materialized 39,007 canonical characters, 39,008 variations, and 59,508
  source representations.
- Preserved 20,016 Danbooru, 3,000 e621, and 36,492 Anima representations.
- Verified all 36,492 reconstructed Anima prompts and all source prompt hashes.
- Mapped every source record exactly once; foreign-key audit returned zero
  errors and `PRAGMA integrity_check` returned `ok`.
- Reduced redundant search-term materialization so the packaged database is
  approximately 83 MB and remains below GitHub's per-file limit.
- Kept 20,118 multi-source variations, four reviewed Danbooru exclusives, and
  18,886 provisional source-only variations.
- All 17 automated tests pass, including source-specific Astolfo prompt/image
  switching, official search aliases, reviewed exclusivity, immutable prompts,
  and manual variation families.

**Known validation boundary:**
- Visual behavior inside the user's remote A1111/Forge installation cannot be
  tested from the local workspace. The branch must be installed remotely for
  final Gradio layout, event, and theme validation.
- The local `.venv` contains Gradio 6.9.0, while the extension targets the
  Gradio 3/4 versions embedded by supported WebUI hosts; it is unsuitable for a
  representative standalone UI launch.

**Files changed:**
- `data/characters.db`
- `wildcard_creator/character_db.py`
- `wildcard_creator/ui.py`
- `scripts/build_character_catalog_v2.py`
- `tests/test_build_character_catalog_v2.py`
- `style.css`
- `.gitignore`
- `README.md`
- `docs/PROJECT_LOG.md`

### [2026-07-23] Character Catalogue v2 — Series-Title Review Queue

**What changed:**
- Added `scripts/generate_series_title_review.py`, a deterministic read-only exporter
  for all title associations that require human review.
- The CSV includes the canonical copyright, resolution class, provider counts,
  representative characters, candidate AniDB AIDs, exact match evidence, companion
  `x-jat`/`ja`/`en` titles, and links to every candidate.
- Decision fields are deliberately empty. Exporting the queue cannot accept a title,
  choose an AID, modify the staging database, or change a prompt.
- Added regression coverage for all three review classes, deterministic output,
  blank decision fields, candidate evidence, input hashes, and path-collision safety.

**Review results:**
- Exported 159 pending rows: 8 ambiguous exact matches, 35 short-title-only matches,
  and 116 alias-only matches.
- Inspected the eight ambiguous rows as the first calibration batch. Their candidate
  AIDs represent competing adaptations, remakes, seasons, or continuities, while the
  canonical copyright and associated characters span the broader franchise.
- Recommended `umbrella_franchise` for all eight cases. No recommendation has been
  applied; the first batch remains pending explicit approval.

**Files changed:**
- `scripts/generate_series_title_review.py`
- `tests/test_generate_series_title_review.py`
- `docs/PROJECT_LOG.md`

### [2026-07-23] Character Catalogue v2 — Provenance-Bearing Series Titles

**What changed:**
- Upgraded the staging catalogue to schema v4 with `series_titles` and
  `series_title_matches` tables. Titles now retain provider, AniDB AID, language,
  title type, confidence, and the exact catalogue alias used as evidence.
- Added explicit summary fields for original transcription and its language, plus
  romaji, Japanese-script, and official English titles. Romaji/Japanese fields are
  populated only when the dump explicitly identifies the main title as `x-jat`;
  language is never inferred from the text or alphabet.
- Imported accepted AniDB `main`, `official`, `syn`, `short`, `card`, and `kana`
  titles in `x-jat`, `ja`, and `en` as searchable aliases without changing the
  Danbooru copyright key.
- Added `scripts/fetch_anidb_titles.py`, an atomic, validated cache collector with
  a mandatory 24-hour reuse window and no force-refresh option.
- Added regression coverage for Konosuba, tied candidates, alias-only franchise
  matches, non-Japanese main-title semantics, card/kana rows, cache reuse, and
  immutable provider prompts.

**Build results:**
- Parsed the official daily AniDB snapshot containing 16,810 anime and 99,840
  provenance-bearing titles.
- Accepted 1,325 exact, unique copyright-to-title associations. These produced
  6,888 stored title rows and 6,437 searchable title aliases.
- Populated 1,325 original transcriptions, 1,310 Japanese romaji titles, 1,309
  Japanese-script titles, and 1,070 official English titles.
- Kept 8 ambiguous matches, 35 short-title-only matches, 116 alias-only matches,
  and 2,218 unmatched series out of automatic enrichment.
- Revalidated all 59,508 legacy prompt joins with zero prompt mismatches, missing
  rows, or invalid prompt hashes. SQLite integrity and foreign-key checks passed.

**Technical decisions:**
- AniDB IDs are evidence for a title association, not replacements for the
  Danbooru copyright identity and not proof that a franchise equals one anime
  season or adaptation.
- A verified Danbooru alias may confirm an AniDB AID already reached by the
  canonical copyright, but an alias cannot establish the association by itself.
  Cases such as `genshin_impact`, `kirby_(series)`, and other adaptation/franchise
  collisions remain review-only.
- Source-specific Danbooru, Anima, and e621 prompts remain immutable rendering
  artifacts. Series-title enrichment changes only staging metadata and search
  aliases.
- The runtime `data/characters.db` and UI remain unchanged in this phase.

**Files changed:**
- `scripts/build_character_catalog_v2.py`
- `scripts/fetch_anidb_titles.py`
- `tests/test_build_character_catalog_v2.py`
- `tests/test_fetch_anidb_titles.py`
- `docs/PROJECT_LOG.md`

### [2026-07-22] Character Catalogue v2 — Directional Search Alias Integration

**What changed:**
- Upgraded the staging catalogue to schema v3 with a dedicated `character_aliases` table
  and official search aliases in the existing `series_aliases` table.
- Added strict official-cache validation and a one-way import policy to the v2 builder.
  Danbooru alias antecedents are searchable input only; the consequent remains the canonical
  catalogue target and output.
- Updated the alias auditor to distinguish aliases already integrated in the catalogue from
  canonicalization and cross-target decisions that remain pending.
- Added regression coverage proving directional aliases do not create identity relations,
  reverse canonical output, or alter source-specific prompts.

**Audit results:**
- Integrated 6,604 official directional search aliases: 5,219 character aliases and 1,385
  series aliases.
- `yor_forger` exists only as a search alias pointing to the canonical `yor_briar` group;
  no `yor_forger` identity group exists. `konosuba` points to the canonical
  `kono_subarashii_sekai_ni_shukufuku_wo!` series.
- Left 1,306 decisions pending: 1,110 canonicalization candidates and 196 aliases connecting
  two existing catalogue targets. No identities were merged.
- All 59,508 provider prompts still match the legacy source database exactly. SQLite
  integrity and foreign-key checks passed.

**Technical decisions:**
- Searchability and canonical naming are separate concepts. An alias may find a character or
  series but can never replace the official consequent in catalogue output.
- Official aliases are auto-imported only when the antecedent has no catalogue target and the
  consequent already has exactly one target. Every other case remains review-only.

**Files changed:**
- `scripts/build_character_catalog_v2.py`
- `scripts/audit_danbooru_aliases.py`
- `tests/test_build_character_catalog_v2.py`
- `tests/test_audit_danbooru_aliases.py`
- `docs/PROJECT_LOG.md`

### [2026-07-22] Character Catalogue v2 — Official Alias Suggestion Audit

**What changed:**
- Added `scripts/audit_danbooru_aliases.py`, which can cache active official Danbooru
  aliases for character (`category=4`) and copyright (`category=3`) tags in bulk pages,
  then perform all catalogue matching offline.
- Added a separate SQLite suggestion database and a reduced CSV review queue. The staging
  character catalogue is opened read-only; aliases never merge identities, change source
  presence, modify exclusivity, or rewrite prompts.
- Added explicit suggestion classes for safe search aliases, canonicalization candidates,
  cross-target connections, already-resolved targets, and ambiguous official aliases.
- Added regression tests for suggestion classification, duplicate alias rejection, path
  collision safety, pending review status, and catalogue hash preservation.

**Audit results:**
- The existing `data/danbooru_tags.csv` contains only 196 general-category rows and no
  usable character or copyright aliases, so it cannot support identity resolution.
- Cached 16,827 active official aliases: 12,811 character aliases and 4,016 series aliases.
- Generated 7,910 catalogue-relevant suggestions: 6,469 character and 1,441 series.
- Identified 6,604 search-only aliases that point to an existing catalogue target. These
  are excluded from the manual review CSV but remain fully available in the SQLite output.
- Generated a 1,306-row review queue: 1,110 canonicalization candidates and 196 aliases
  connecting two existing catalogue targets.
- Applied zero automatic merges. SQLite integrity, foreign-key checks, and the unchanged
  staging-catalogue SHA-256 guard all passed.

**Technical decisions:**
- An official alias is positive evidence, not authorization to merge catalogue entities.
- Search-only aliases are separated from decisions that affect identity or canonical tags.
- The API snapshot is stored only under ignored `data/generated/`; credentials are optional,
  read from environment variables when supplied, never written to output or logs.

**Files changed:**
- `scripts/audit_danbooru_aliases.py`
- `tests/test_audit_danbooru_aliases.py`
- `docs/PROJECT_LOG.md`

### [2026-07-22] Character Catalogue v2 — Offline Staging Pipeline

**What changed:**
- Added `scripts/build_character_catalog_v2.py`, an offline and repeatable builder that
  creates `data/generated/characters_v2.db` plus a JSON audit report without modifying
  the runtime `data/characters.db`.
- Preserved provider prompts as immutable source data. DownloadMost/Danbooru and e621
  prompts are copied byte-for-byte from the current database, while every Anima prompt
  is reconstructed from `trigger` + `core_tags` and required to match the bundled Anima
  row exactly before the build may continue.
- Added a relational staging schema for provider records, canonical series, series aliases,
  exact raw-tag groups, build metadata, and review-only identity/variation candidates.
- Added tracked `data/catalog_overrides.json` decisions plus relational audit tables for
  accepted aliases, rejected false matches, character variations, and reviewed exclusivity.
- Replaced positional series guessing with exact Anima copyright matching. A prompt's
  second tag is deliberately not treated as a series.
- Added focused regression tests for source-specific Astolfo prompt escaping, the fail-closed
  Anima prompt-fidelity check, safe output paths, and metadata-only manual overrides.

**Audit results:**
- 59,508 provider records staged: 20,016 Danbooru, 3,000 e621, and 36,492 Anima.
- All 36,492 Anima prompts and all 59,508 legacy-record prompt joins passed with zero
  mismatches; SQLite integrity and foreign-key checks also passed.
- Exact Anima copyright data resolved series metadata for 20,011 Danbooru records and 488
  e621 records. Manual review resolved the remaining five Danbooru records, leaving all
  20,016 Danbooru records resolved and 2,512 e621 records intentionally unresolved.
- 39,009 exact raw-tag groups and 21,544 review candidates were generated. These are
  provisional comparison aids, not final character entities or definitive exclusivity flags.
- The five reviewed Danbooru cases produced four confirmed Danbooru-exclusive source records,
  one accepted cross-provider Yamashiro variant alias, one `variation_of` relation, and four
  rejected false-positive identity candidates.

**Technical decisions:**
- A provider prompt is an immutable rendering artifact. Normalization is allowed only on
  derived matching keys and must never rewrite `prompt_text`.
- Anima `copyright` is useful source metadata, but is not automatically assumed to be the
  definitive original title of a work. Canonical titles and Western/common aliases will be
  populated separately with provenance and confidence.
- Manual catalogue decisions are source-record selectors stored in a tracked JSON artifact.
  The builder rejects missing, duplicate, conflicting, or prompt-mutating overrides.
- No runtime database swap, UI filter, or search behavior changed in this phase. The staged
  database and report are ignored through `data/generated/` until identity resolution and
  review rules are complete.

**Files changed:**
- `scripts/build_character_catalog_v2.py`
- `tests/test_build_character_catalog_v2.py`
- `data/catalog_overrides.json`
- `.gitignore`
- `docs/PROJECT_LOG.md`

### [2026-04-11] v0.5.3 — Hotfix: Startup Crash & Database Lock

**O que foi feito:**
- Removidas as referências órfãs a `page_indicator` e `page_jump_top` nas listas de output do Gradio 4 que levavam a crash imediato `NameError` ao inicializar a UI após a atualização da paginação.
- Modificado o código do `character_db.py` para desligar o journal mode padrão do SQLite (de WAL para DELETE) ao inicializar, e incluído algoritmo de deleção forçada dos arquivos `-wal` e `-shm`. Isso evita conflitos de estado no RunPod quando usuários fazem downloads de updates via `git pull` (já que esses arquivos .wal não eram transacionados pelo Git e corrompiam a base em uso remoto).

**Arquivos alterados:**
- `wildcard_creator/ui.py`
- `wildcard_creator/character_db.py`
- `data/characters.db`

**Decisões técnicas:**
- `journal_mode=DELETE` ao invés de `WAL` lida perfeitamente com um projeto cujo banco é primariamente READ-ONLY na mão do usuário final, enquanto garante portabilidade sem artefatos no diretório do repo.
- Commitada a base `.db` definitiva após comando explícito de `PRAGMA wal_checkpoint(TRUNCATE);` para encapsular todas as edições pendentes com os metadados de "Konosuba" no monólito binário transportável pelo Git.

### [2026-04-11] v0.5.2 — History Pagination, Auto-Select & DB Series Rescue

**O que foi feito:**
- Script `clean_series_metadata.py` aprimorado para assumir "resgate de série" quando a coluna `series` for nula, absorvendo a string da 2ª tag.
- `characters.db` limpo. Aproximadamente 709 registros órfãos que estavam fora de qualquer série ganharam sua devida formatação e capitalização de título.
- Aba "Recently Viewed" agora persiste até 100 itens (limite anterior era 20) e conta com um sistema de paginação independente para sua renderização no Gradio.
- Resultado de busca agora se auto-seleciona (auto-select do primeiro item, populando imagem e descrições instantaneamente na tela esquerda).

**Arquivos alterados:**
- `wildcard_creator/ui.py`
- `scripts/clean_series_metadata.py`
- `data/characters.db`
- `README.md`
- `AGENTS.md`

**Decisões técnicas:**
- Optado por realizar as mudanças direto no banco via atualização massiva pre-empacotada. Isso evita trabalho custoso de CPU rodando lógica recursiva pros usuários no start.
- O novo sistema de auto-select imita diretamente um clique por injetar os 8 parâmetros de side-outputs junto aos callbacks do botão "Search" e do Enter.
- As mudanças incrementais encaixam fluentemente na versão Z do `v0.5.2`.

**Impactos e pontos de atenção:**
- Como a listagem recente aumentou para 100 com paginação independente, o estado gerado vai ser um array `recent_chars_state` sensivelmente maior em memória de Gradio. Para a escala do React/Python local isso é insignificante.

### [2026-04-11] v0.5.1 — Global Pagination & Forge State Saving

**O que foi feito:**
- Paginação do sistema (topo e rodapé) foi movida para fora da aba restrita "Search Results", tornando-a visível globalmente para todas as abas (incluindo Favoritos e Histórico).
- Adicionado `elem_id` em todos os inputs essenciais (Search, Series, Dropdowns) para garantir suporte completo ao recurso "Save UI Defaults" do AUTOMATIC1111 e Forge.
- Corrigido o bug onde botões "Clear Search" e "Clear All" deixavam o dropdown de Series quebrado (`None`), agora resetando corretamente para `"All"`.

**Arquivos alterados:**
- `wildcard_creator/ui.py`
- `README.md`
- `AGENTS.md`

**Decisões técnicas:**
- Posicionar a paginação *fora* das abas elimina a necessidade de duplicar lógicas de navegação ou usar Javascript complexo, mantendo a responsividade do Gradio intacta entre o controle de listas e galeria.
- Os IDs de elemento (`elem_id`) fixos permitem que o Forge/WebUI identifique perfeitamente os inputs da extensão no arquivo raiz `ui-config.json` do usuário, possibilitando que o filtro preferido dele sobreviva a reinicializações.

**Impactos e pontos de atenção:**
- Nenhuma regressão detectada. A usabilidade da tabulação agora compartilha harmoniosamente os mesmos botões de paginação, então a reatividade visual entre "clicar page 2 e mudar list view" deve se manter robusta.

### [2026-03-26] v0.5.0 — Favorites, History & Gradio 4 Polish

**O que foi feito:**
- Implementado sistema de Favoritos persistente (salvo localmente).
- Adicionadas abas dedicadas para Favoritos e Histórico (Recent Searches), incluindo controles e envio para txt2img.
- Estilização aprimorada no `style.css` para esconder elementos indesejáveis do Dataframe no Gradio 4+ (Svelte Virtual Scroller handles, checks de seleção multipla).
- Barras de rolagem personalizadas (`::-webkit-scrollbar`) integradas dinamicamente com o modo Light/Dark do WebUI via variáveis nativas do Gradio.

**Arquivos alterados:**
- `wildcard_creator/ui.py`
- `wildcard_creator/favorites.py` (novo)
- `wildcard_creator/search_history.py` (novo)
- `style.css`
- `README.md`

**Decisões técnicas:**
- Funcionalidades de estado do usuário (Favoritos e Histórico) utilizam JSONs locais (`data/favorites.json` e `data/search_history.json`) para persistência limpa, não misturando dados de uso com o banco estático `characters.db`.
- Correções visuais baseadas no Svelte foram fixadas via `!important` classes no CSS, contornando a ausência de parâmetros limpos na API do Gradio para ocultar marcadores de linha.
- Scraper automático em background da versão 0.4.1 foi revertido no path 0.4.2 em vista da instabilidade que causava em builds recarregados no RunPod. Git source de verdade tornou-se autoridade sobre a baseline local de dados.

**Impactos e pontos de atenção:**
- O bug visual nativo de salto "bouncing height" do virtual scroller do Gradio 4 permanece sem fix rígido (confinamento no DOM Svelte), no entanto as quebras forçadas de wrap e layout aliviaram a usabilidade.

### [2026-03-26] v0.4.2 — Remove Automatic Scraping on Startup

**O que foi feito:**
- Removido o fluxo de "auto-scrape" automático em background que era ativado na inicialização caso a base local estivesse incompleta.

**Arquivos alterados:**
- scripts/wildcard_creator.py
- wildcard_creator/ui.py

**Decisões técnicas:**
- O auto-scrape gerava concorrência indesejada e tempos de carregamento falsos em ambientes remotos (ex: RunPod). A base de dados (`data/characters.db`) já é controlada pelo Git, portanto o usuário deve apenas realizar o `pull` da base preenchida para evitar a recriação custosa no RunPod.

**Impactos e pontos de atenção:**
- Atualizações na base (novos personagens) deverão ser feitas explicitamente (via CLI script) e commitadas para o versionamento no GitHub. O UI não tentará mais corrigir uma base corrompida ou vazia silenciosamente.

### [2026-03-23] v0.4.1 — Reliability, Dedupe Control & Startup Sync

**O que foi feito:**
- Added optional deduplication toggle for `Add to txt2img` in WebUI Settings.
- Updated `Add to txt2img` flow to support both deduplicated and raw append modes.
- Improved startup auto-scrape consistency to cover Danbooru and e621 under unified DB expectations.
- Improved SQLite runtime resilience (WAL, busy timeout, synchronous normal).
- Improved gallery loading path with reused HTTP session and in-memory data URI caching.

**Arquivos alterados:**
- scripts/wildcard_creator.py
- wildcard_creator/character_db.py
- wildcard_creator/ui.py
- README.md
- docs/PROJECT_LOG.md (local only, ignored)

**Decisões técnicas:**
- Deduplication behavior was made configurable at Settings level to preserve current UX while enabling raw append workflows.
- Startup scrape checks now use per-source counters to align behavior with the unified Danbooru/e621 dataset.
- SQLite pragmas were tuned for better concurrent read/write reliability without changing public DB APIs.
- In-memory thumbnail cache was limited (LRU-like behavior via OrderedDict) to balance performance and memory usage.

**Impactos e pontos de atenção:**
- Changes in startup scraping may increase first-boot background activity when source counts are below thresholds.
- Deduplication toggle affects prompt composition behavior in `Add to txt2img`; users should verify preferred mode.
- SQLite pragmas depend on environment capabilities; fallbacks remain best-effort.

---

## Notas de Manutenção

### Regras de Documentação

> **What's New (apenas a família da minor atual):** A seção "What's New" mantém as entradas da família da minor atual vX.Y.* inteira (ex: se estamos em v0.6.1, ficam v0.6.1 e v0.6.0 no What's New; se estamos em v0.4.0-ex, fica apenas v0.4.0-ex). Versões de famílias anteriores (ex: v0.5.x) pertencem exclusivamente ao Changelog.
