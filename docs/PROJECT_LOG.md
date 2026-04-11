# PROJECT_LOG

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
