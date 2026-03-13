# PROJECT_LOG — Histórico técnico orientado a IA

## Escopo atual do projeto

- Extensão SD WebUI (A1111 / Forge) — **single-tab: browser de personagens Danbooru**
- 20.016 personagens indexados em SQLite local (`data/characters.db`, 7.2 MB, incluso no repo)
- Busca por nome/tag e filtro por série; card com thumbnail, campos nome/série/tags, Send to Generate / Copy Tags
- **Nova seção "Search Danbooru Live"** — busca personagens fora do banco local via API Danbooru, exibe tags mais frequentes por categoria com checkboxes, monta prompt editável e envia para txt2img
- Módulos `pack_manager` e `recipe_engine` presentes no código mas desconectados da UI (mantidos para compatibilidade e testes)
- Modo standalone (`python -m wildcard_creator.ui`) para desenvolvimento local sem GPU/WebUI
- **Versão atual:** `v1.1.0`

## Regras de versionamento (Semantic Versioning vX.Y.Z)

| Campo | Tipo | Quando usar |
|---|---|---|
| **X** (major) | Quebra de arquitetura | Mudança incompatível com versões anteriores. Ex.: troca de DB schema, reestruturação de API. |
| **Y** (minor) | Nova feature | Nova funcionalidade retrocompatível. Ex.: novo filtro, novo botão de ação. |
| **Z** (patch) | Bug fix / estabilidade | Correção que não altera comportamento esperado. Ex.: crash fix, seletor CSS errado. |

## Visão rápida de estado

- **Stack principal:** Python 3.10+, Gradio 4.x (nativo do WebUI), sqlite3 (stdlib), requests, beautifulsoup4
- **Status de auth:** Sem autenticação de usuário — extensão roda localmente dentro do WebUI
- **Status de testes:** `tests/test_user_journey.py` — 29 testes (pack_manager + recipe_engine). Todos passando
- **Status de deploy:** Extensão instalável via `git clone` na pasta `extensions/` do WebUI. Compatível com A1111, Forge, Forge Classic (neo)
- **Principais features implementadas:** Browser de 20.016 personagens Danbooru, busca por nome/tag, filtro por série, card com thumbnail, Send to Generate (JS), Copy Tags (JS com fallback HTTP), busca live Danbooru com checkboxes de tags por categoria

---

## Linha do tempo de mudanças

### [2026-03-13] Reset da busca no browser de personagens

**O que foi feito:**
- Adicionado botão `✖ Clear` na barra de busca principal do browser de personagens
- O reset agora limpa texto de busca, filtros, tabela de resultados, seleção atual do card e estados auxiliares ligados ao personagem
- Mantida compatibilidade prática com Gradio 3 e 4 usando retornos simples e `gr.update(...)`

**Arquivos alterados:**
- `wildcard_creator/ui.py` — botão e handler de reset da busca
- `docs/PROJECT_LOG.md` — esta entrada

**Decisões técnicas:**
- O botão limpa apenas o estado da busca e do card atual; não altera a pasta-alvo de wildcard para evitar resetar preferência do usuário sem necessidade
- O handler zera também as sugestões de extra tags para não deixar estado residual de uma seleção anterior

**Impactos e pontos de atenção:**
- O comportamento esperado passa a ser: após `Clear`, a tela volta ao estado inicial da busca sem disparar nova consulta ao banco
- Se houver diferença pontual entre Gradio 3 e 4 no `Dataframe`, o fallback continua seguro porque o estado interno da lista de resultados também é resetado

### [2026-03-12] UI Settings: Danbooru credentials for broader live search

**O que foi feito:**
- Credenciais Danbooru migradas da aba da ferramenta para o **Settings nativo do WebUI** (A1111 / Forge)
- Registradas duas opções em `script_callbacks.on_ui_settings`: `sdcf_danbooru_login` e `sdcf_danbooru_api_key`
- Campos da busca live continuam pré-preenchidos, agora lendo `shared.opts` em vez de arquivo local

**Arquivos alterados:**
- `scripts/wildcard_creator.py` — registro das opções no Settings nativo do WebUI
- `wildcard_creator/ui.py` — consumo dos valores de `shared.opts` na busca live

**Decisões técnicas:**
- Não persistir credenciais em arquivo da extensão; a fonte única passa a ser o Settings do WebUI
- API key configurada como campo de senha (`type=password`) no painel de configurações
- Em modo standalone (sem `modules.shared`), a UI faz fallback para campos vazios

**Impactos e pontos de atenção:**
- O ganho de limite depende de credenciais válidas do Danbooru
- Cada ambiente (máquina/RunPod) mantém suas credenciais no próprio Settings do WebUI

### [2026-03-12] Batch resolver mode for `danbooru_tag` backfill

**O que foi feito:**
- `scripts/resolve_danbooru_tags.py` agora suporta execução em lotes determinísticos com `--limit` e `--offset`, ordenados por `id`
- Adicionado `--summary-only` para rodar em background sem imprimir uma linha por personagem; a saída fica reduzida ao cabeçalho e resumo final
- Adicionados modos explícitos `--csv-only` e `--api-only` para separar o backfill em duas fases: dump local primeiro, API depois
- O lookup do CSV passou a indexar também a coluna de aliases do dump, não apenas `tag_name`
- Em `--api-only`, `--csv` passou a ser obrigatório; resultados da API são canônicos apenas se existirem no CSV
- Mantido `--sample` apenas para teste de cobertura; agora ele é mutuamente exclusivo com `--limit/--offset`
- Ajustado retry de erro 429 para preservar o lookup CSV no segundo `resolve_one()`
- Otimizado o fluxo de resolução: o script tenta primeiro os lookups CSV diretos e só então consulta alias de copyright na API

**Arquivos alterados:**
- `scripts/resolve_danbooru_tags.py` — modo batch real, saída resumida e ajuste do fluxo CSV/API
- `docs/PROJECT_LOG.md` — esta entrada

**Decisões técnicas:**
- Lotes são definidos após aplicar o filtro de `--resume`, o que facilita retomar o processamento pendente sem recalcular IDs manualmente
- A ordenação por `id` torna os lotes previsíveis e repetíveis; `sample` continua separado por ser ferramenta de projeção, não de escrita
- `--summary-only` foi adicionado para reduzir ruído em execuções longas e facilitar acompanhamento por terminal em background
- No modo `--csv-only`, o script não faz nenhuma chamada de rede; apenas matches diretos do dump local são gravados
- Aliases presentes no dump CSV agora resolvem para a tag canônica na própria fase 1, aumentando cobertura sem depender da API
- No modo `--api-only`, a API é usada apenas como busca; o resultado final só é aceito se mapear para nome canônico do CSV

**Impactos e pontos de atenção:**
- `--offset` atua sobre o conjunto já filtrado por `--resume`; se novas linhas forem preenchidas entre execuções, o próximo offset deve ser recalculado no universo pendente
- Para execução massiva local, o fluxo recomendado passa a ser: fase 1 com `--csv-only --resume --limit 500 --summary-only`; fase 2 com `--api-only --resume --limit 500 --summary-only`
- Para auditoria de qualidade, é recomendado rodar com saída completa em `--dry-run` e filtrar `\[not_found\]` em tela antes de persistir lote por lote

### [2026-03-12] DB quality fix + Live Danbooru Search (v1.1.0)

**O que foi feito:**
- Aplicado `scripts/fix_truncated_tags.py` no banco: 3.936 personagens corrigidos (2.369 trailing comma, 1.330 completados por prefixo, 237 fragmentos de 1-2 chars removidos)
- Lógica do script refinada: tags raras (< 500 posts) mas presentes no CSV são mantidas; apenas lixo de 1-2 chars é removido
- Adicionados dois novos métodos em `danbooru.py`: `search_character_tags()` (busca tags do tipo character na API) e `fetch_character_post_tags()` (coleta tags mais frequentes dos posts de um personagem)
- Nova seção "Search Danbooru Live" em `ui.py`: input de nome → Radio de candidatos → CheckboxGroup por categoria (character, general, copyright) → prompt editável → Send/Copy

**Arquivos alterados:**
- `data/characters.db` — 3.936 tags corrigidas
- `scripts/fix_truncated_tags.py` — lógica de remoção ajustada (MIN_KEEP_LEN preserva tags raras)
- `wildcard_creator/danbooru.py` — adicionados `search_character_tags()` e `fetch_character_post_tags()`
- `wildcard_creator/ui.py` — nova seção live search, import de `DanbooruDB`
- `docs/PROJECT_LOG.md` — esta entrada

**Decisões técnicas:**
- Live search usa `DanbooruDB` instanciada dentro do handler (não singleton) pois não tem CSV carregado — só usa a API
- Tags são agrupadas por categoria (character=4, general=0, copyright=3); artistas (1) e meta (5) são ignorados
- Checkboxes inicializam com tudo selecionado por padrão (character e copyright) e top 15 general tags
- Sem credenciais: funciona anonimamente com limite de 100 posts e 2 req/s do Danbooru
- Prompt assemblado automaticamente ao alterar qualquer checkbox, mas é editável pelo usuário antes de enviar

**Impactos e pontos de atenção:**
- `fetch_character_post_tags` faz uma chamada HTTP ao clicar em um candidato — pode ser lento em conexões ruins
- Danbooru anônimo limita a 2 req/s; se o usuário clicar rápido pode receber 429; tratar com mensagem de erro amigável no futuro
- `data/characters.db` agora tem tags limpas — sem risco de regressão pois o fix é idempotente

### [2026-03-12] Fix: integração com SD WebUI Forge Classic (neo) e botões funcionais

**O que foi feito:**
- Corrigido `scripts/wildcard_creator.py`: callback `on_ui_tabs` agora retorna lista de tuplas `[(blocks, "Danbooru Characters", "sd_character_finder")]` em vez do `gr.Blocks` diretamente (erro `TypeError: 'Blocks' object is not iterable`)
- Removido wrapper `gr.Tab(...)` de dentro de `_build_characters_tab()` — o WebUI já cria o tab externo via tupla; ter tab aninhado no `gr.Blocks` fazia a aba renderizar vazia
- Renomeada função `_build_characters_tab()` → `_build_characters_content()` para refletir que não cria mais o tab wrapper
- Aba renomeada de `🎭 Characters` para `Danbooru Characters`
- Botão **Send to Generate**: reimplementado via JavaScript (`gradioApp().querySelector('#txt2img_prompt textarea')`) — substitui a abordagem via `modules.generation_parameters_copypaste` que não funcionava
- Botão **Copy Tags**: reimplementado via JavaScript com duplo fallback: `navigator.clipboard.writeText()` (HTTPS/localhost) → `execCommand('copy')` via textarea temporário (HTTP em rede local)
- Removida dependência de `prompt_sender.copy_positive()` / `tkinter` nos handlers de UI — tkinter não funciona em servidor Linux headless (RunPod e ambientes similares)

**Arquivos alterados:**
- `scripts/wildcard_creator.py` — retorno correto do on_ui_tabs + nome da aba
- `wildcard_creator/ui.py` — remoção do gr.Tab wrapper, Send e Copy via JS

**Decisões técnicas:**
- JS direto no browser é a abordagem correta para interagir com o DOM do WebUI — independe do servidor e funciona em qualquer ambiente (local, LAN, RunPod, Gradio share)
- `execCommand('copy')` é deprecated mas ainda amplamente suportado; necessário para HTTP sem `isSecureContext`
- `prompt_sender.py` mantido no código (usado por outros casos) mas desacoplado dos handlers principais da UI

**Impactos e pontos de atenção:**
- A aba só aparece após `git pull` + reinício do WebUI
- Compatible com A1111, Forge, Forge Classic (neo) — qualquer fork que siga o padrão `on_ui_tabs`

---

### [2026-03-12] Rename: YAML Wildcard Creator → SD Character Finder

**O que foi feito:**
- Projeto renomeado para **SD Character Finder** (`sd-character-finder`)
- `README.md` reescrito para refletir o escopo atual: browser de personagens, sem menção a Pack Editor / Recipe Editor
- Título da UI atualizado: `# 🃏 YAML Wildcard Creator` → `# 🎭 SD Character Finder`
- `AGENTS.md` e `copilot-instructions.md` atualizados com novo nome e slug

**Arquivos alterados:**
- `README.md` — reescrito
- `AGENTS.md` — visão geral e objetivo
- `wildcard_creator/ui.py` — título da página
- `.github/copilot-instructions.md` — nome do projeto

**Decisões técnicas:**
- Pasta do repositório mantida como `YAML-wildcard-creator` até eventual rename no GitHub
- Módulo Python mantido como `wildcard_creator` para não quebrar imports existentes

---

### [2026-03-12] Remoção das tabs Pack Editor, Recipe Editor e Generate — app agora single-tab

**O que foi feito:**
- Removidos de `ui.py`: funções `_build_generate_tab()`, `_build_pack_editor_tab()`, `_build_recipe_editor_tab()` e todos os helpers dependentes (`_packs`, `_recipes`, `_categories`, `_recipe_entries`)
- Removidos imports não mais necessários: `yaml`, `pack_manager`, `recipe_engine`, `danbooru`
- `build_ui()` agora chama apenas `_build_characters_tab()`
- App é single-tab: somente `🎭 Characters` permanece
- 29/29 testes continuam passando (testes cobrem `pack_manager` e `recipe_engine`, que não foram removidos — só foram desacoplados da UI)

**Arquivos alterados:**
- `wildcard_creator/ui.py` — reduzido de ~600 para 175 linhas

**Decisões técnicas:**
- `pack_manager.py` e `recipe_engine.py` permanecem no projeto (módulos estáveis, usados pelos testes), só foram desconectados da UI
- O DB de personagens (`data/characters.db`) já estava com `is_populated()` retornando True — nenhuma regressão no conteúdo

**Impactos e pontos de atenção:**
- Pack creation/editing e recipe preview não são mais acessíveis via UI
- A funcionalidade de geração de prompts foi removida da UI (mas o engine está intacto)

---

### [2026-03-12] Feature: 🎭 Character Browser (scraper + DB + UI tab)

**O que foi feito:**
- Criado `scripts/scrape_characters.py`: scraper para os 20.016 personagens do site downloadmost.com (834 páginas). Rate limit 1 req/s, retomável via `--resume`, testável com `--pages N`. Parse de `<div class="card">` com BS4.
- Criado `wildcard_creator/character_db.py`: `CharacterDB` com SQLite stdlib. Métodos: `search(query, series_filter, limit)`, `get(name)`, `list_series()`, `count()`, `is_populated()`. Singleton via `get_character_db()`.
- Adicionada tab `🎭 Characters` em `ui.py`: busca + filtro por série, tabela de resultados, card com thumbnail lazy-load (URL da origem), campos nome/série/tags, botões "Send to Generate" e "Copy Tags". Se o DB não existir, exibe instrução de como popular.
- Atualizado `install.py`: adiciona `beautifulsoup4`
- Atualizado `.gitignore`: ignora `data/characters.db` (arquivo gerado localmente)

**Arquivos criados:**
- `scripts/scrape_characters.py`
- `wildcard_creator/character_db.py`

**Arquivos alterados:**
- `wildcard_creator/ui.py` — nova tab `_build_characters_tab()`
- `install.py` — adiciona `beautifulsoup4`
- `.gitignore` — ignora `data/characters.db`

**Decisões técnicas:**
- SQLite (stdlib) escolhido sobre CSV/YAML: índices em `name` e `series`, busca LIKE eficiente, ~3-5MB para 20k registros
- Thumbnails lazy-load da URL de origem (sem download em massa): zero custo de disco, funcional offline graciosamente
- robots.txt do site: `User-agent: * Allow: /` — scraping geral permitido
- Danbooru API descartada para este propósito: requereria 20k requests vs 834 do scraper do site
- `gr.Image(height=280)` sem `show_download_button` (parâmetro indisponível no Gradio local)

**Impactos e pontos de atenção:**
- `data/characters.db` precisa ser gerado uma vez com `python scripts/scrape_characters.py` (~14 min)
- Tab renderiza mensagem de instrução se o DB não existir (sem crash)
- `beautifulsoup4` adicionado ao `install.py` — será instalado automaticamente no WebUI no próximo start

---

### [2026-03-11] Testes de jornada do usuário + bugfix save_category

**O que foi feito:**
- Criado `tests/test_user_journey.py` com 29 testes cobrindo o fluxo completo: criar pack → adicionar categorias → criar recipe → gerar prompts → exportar zip
- Corrigido bug em `pack_manager.save_category()`: categorias aninhadas (ex: `hair/color`) falhavam com `FileNotFoundError` porque o diretório intermediário (`hair/`) não era criado. Adicionado `pos_path.parent.mkdir(parents=True, exist_ok=True)` antes de `write_text()`
- Testes isolados via `monkeypatch.setattr(pm, "get_packs_dir", ...)` → toda I/O de arquivo vai para `tmp_path` temporário do pytest
- Resultado final: **29/29 testes passando**

**Arquivos alterados:**
- `wildcard_creator/pack_manager.py` — fix `save_category()`: mkdir antes de write para subcategorias
- `tests/test_user_journey.py` — criado (29 testes, 5 classes por passo da jornada)
- `docs/PROJECT_LOG.md` — esta entrada + backlog atualizado

**Decisões técnicas:**
- Fixture `isolated_packs` com `autouse=True` em cada classe garante isolamento sem necessidade de conftest.py adicional
- Testar via jornada do usuário (não por módulo) cobre integração real entre `pack_manager` e `recipe_engine`
- Bug de mkdir não afetava o `example_sfw` (pré-existente no repo) mas afetaria qualquer novo pack criado pelo usuário com subcategorias

**Impactos e pontos de atenção:**
- Bug corrigido existia desde a criação do projeto — qualquer criação de categoria aninhada via UI também estava falhando silenciosamente (erro aparecia no status handler da UI)
- `neg_path.parent` dispensa mkdir extra pois é o mesmo diretório de `pos_path.parent`

---

### [2026-03-11] Snapshot inicial — Documentação do estado atual

> Repositório sem histórico git no momento da análise. Snapshot baseado em leitura direta dos arquivos.

**Arquivos principais criados/existentes:**

```
YAML-wildcard-creator/
├── install.py                          # pip install pyyaml + requests via launch.run_pip
├── scripts/
│   └── wildcard_creator.py             # on_ui_tabs() — ponto de entrada do WebUI
├── wildcard_creator/
│   ├── __init__.py
│   ├── pack_manager.py                 # CRUD completo: packs, categorias, recipes, CSV, zip (~260 linhas)
│   ├── recipe_engine.py                # resolução __tokens__, YAML parsing, roll (~200 linhas)
│   ├── danbooru.py                     # DanbooruDB: CSV local + API live (~200 linhas)
│   ├── prompt_sender.py                # send_to_txt2img() com fallback clipboard
│   └── ui.py                           # 3 tabs Gradio 4.x (~500 linhas)
├── packs/example_sfw/
│   ├── pack.json                       # metadata: name, version, description, rating, author
│   ├── styles.csv                      # 8 estilos pré-definidos (5 colunas)
│   ├── wildcards/                      # 9 categorias: base, body, camera, eyes/color,
│   │   ├── base.txt + base_negative.txt   hair/color, hair/style, lighting, outfit, scene
│   │   ├── hair/color.txt + hair/style.txt
│   │   └── eyes/color.txt (+ etc.)
│   └── recipes/
│       ├── portrait_girl.yaml          # 4 entradas: Simple Portrait, Casual Outdoor, Fashion, Fantasy
│       └── fantasy_character.yaml      # 5 entradas: Warrior, Mage, Rogue, Healer, Archer
└── data/
    └── danbooru_tags.csv               # 195 tags curadas (hair, eyes, outfit, scene, lighting, poses)
```

**Decisões arquiteturais identificadas:**

- **`pack_manager` 100% stateless** — todas as funções leem diretamente do disco a cada chamada; zero cache em memória. Garante consistência mas implica I/O repetitivo.
- **Singleton lazy `get_db()`** — único estado global permitido; carrega `data/danbooru_tags.csv` na primeira chamada e reutiliza. Aceitável pois o CSV não muda em runtime.
- **Gradio 4.x: sem `.change` no load** — contornado pré-populando `value=` e `choices=` no construtor dos dropdowns (calculado em build time). Não usar `blocks.load()` para este caso.
- **`modules.*` sempre dentro de `try/except`** — única forma de coexistir em standalone e WebUI sem condicionais de runtime.
- **`_pick_variant()` com fallback visual** — se o arquivo `.txt` não existir, retorna `(categoria)` como string em vez de crashar ou retornar string vazia.
- **YAML recipe: 3 formatos suportados** — Format A (lista com string), Format B (lista com `{negative: ...}`), Format C (dict com `positive`/`negative`). `_flatten_recipes()` recursivo trata qualquer nesting.
- **`save_category()` assinatura revisada** — aceita `description` como terceiro argumento opcional na UI mas `pack_manager.save_category()` na v atual aceita apenas `(pack, cat, variants, neg_variants)`. A UI passa 5 args — **divergência ativa** (ver Pontos Sensíveis).

**Convenções de código observadas:**

- Todos os paths via `pathlib.Path` — nunca `os.path.join` ou concatenação de strings
- Encoding `"utf-8"` explícito em todos os `read_text` / `write_text`
- Event handlers Gradio retornam `gr.update(...)` — nunca valores nus
- Imports de `modules.*` isolados em `try/except ImportError`
- Variantes limpas: `[l for l in text.splitlines() if l.strip()]` — sem linhas vazias

**Pontos sensíveis identificados:**

1. **Divergência `save_category` na UI** — `ui.py` chama `pm.save_category(pack, cat, variants, neg_variants, desc)` com 5 argumentos, mas `pack_manager.save_category()` aceita apenas 4 (sem `desc`). Isso causa `TypeError` ao salvar. **Precisa corrigir.**

2. **Cross-pack refs não implementadas** — `recipe_engine.py` documenta `__pack:category__` no docstring mas `_pick_variant()` não trata o caso. Se um YAML usar essa sintaxe, retornará `(pack:category)` silenciosamente.

3. **`delete_pack` não exposto na UI** — `pack_manager.delete_pack()` existe mas não há botão nem handler em `ui.py`. Risco de confusão para o usuário.

4. **`send_to_txt2img` incompleto no WebUI** — `prompt_sender.py` tenta `gpc.parse_generation_parameters()` mas a função não preenche os campos txt2img diretamente. Precisa usar `modules.generation_parameters_copypaste.paste_field_names` ou `modules.txt2img` components binding.

5. **Validação de YAML ausente antes de salvar** — `save_recipe_raw()` grava o conteúdo bruto sem validar YAML. Um YAML malformado no editor causa `parse_recipe_yaml()` retornando `{"__error__": "..."}` só no momento do roll.

6. **Gradio Code component** — `gr.Code(language="yaml")` pode não existir em todas as versões de Gradio 4.x do Forge. Se o WebUI usar Gradio < 4.4, quebra silenciosamente.

---

## Backlog técnico / próximas melhorias

| # | Item | Prioridade | Arquivo |
|---|---|---|---|
| 1 | ~~**Corrigir `save_category` — 5 args vs 4**~~ ✅ | ~~🔴 crítico~~ | `pack_manager.py` + `ui.py` |
| 2 | Teste real no Forge via RunPod | 🔴 alta | — |
| 3 | `send_to_txt2img` funcional no WebUI | 🟠 média | `prompt_sender.py` |
| 4 | Validar YAML antes de salvar recipe | 🟠 média | `ui.py` tab Recipe Editor |
| 5 | Implementar cross-pack refs `__pack:category__` | 🟡 média | `recipe_engine.py` |
| 6 | Expor `delete_pack` na UI | 🟡 baixa | `ui.py` tab Pack Editor |
| 7 | Batch import de TXT packs existentes | 🟡 baixa | `pack_manager.py` |
| 8 | `.card` + thumbnail (wildcard-gallery compat) | ⚪ v2 | `pack_manager.py` |
| ~~9~~ | ~~Adicionar pytest com ao menos smoke tests~~ ✅ | ~~⚪ v2~~ | `tests/` |

### [2026-03-13] Lote 1 & 2: Limpeza, Settings WebUI e Paginação

**O que foi feito:**
- Deleção de códigos mortos (pack_manager, recipe_engine, prompt_sender) para consolidar a extensão como Single-Tab Browser.
- Instalação de utilitários isolados em \wildcard_creator/utils/strings.py\ e hook de \texit\ no \character_db.py\.
- Todas as opções como API Keys, Limites de busca ou TTL e Rate Limits do Danbooru movidos para \shared.opts\ (Settings nativo do WebUI).
- Refatoração total para \logging\ capturar \xc_info\ (resolvendo silenciosos exceptions do DB).
- Implementado sistema nativo de Paginação (com \offset\ e limit no SQLite) na query do Gradio para evitar Dataframes estourando memória com pesquisas de limite alto.
- Cache em memória na fetch das tags extras do Danbooru.

**Arquivos alterados:**
- \wildcard_creator/character_db.py\
- \wildcard_creator/danbooru.py\
- \wildcard_creator/ui.py\
- \scripts/wildcard_creator.py\
- Excluídos: \pack_manager.py\, \ecipe_engine.py\, \prompt_sender.py\.

**Decisões técnicas:**
- Optamos pela paginação manual simples com states (Prev/Next) no Gradio ao invés de paginação complexa via javascript. O estado da página é injetado recursivamente na função de search.


### [2026-03-13] Lote 3: Fix Tag Deduplication and Ordering

**O que foi feito:**
- Normalização de espaços e underscores (\_\ virando espace \ \) garantida antes da deduplicação de tags extras e no JS de 'Add to txt2img'.
- \_order_tags_novelai_like\ foi ajustado para sempre reconhecer strings mesmo quando estão com espaços ao invés de underscore vindos do WebUI.
- \_fetch_extra_tags\ e \_apply_extra_tags\ foram atualizados com a lambda interna \_norm(tag_str)\.

**Arquivos alterados:**
- \wildcard_creator/ui.py\

**Decisões técnicas:**
- Fix bug onde usar 'hatsune miku' e 'hatsune_miku' duplicava o conceito na linha do usuário dependendo se era tag canonica do banco ou live fetch do Danbooru.


### [2026-03-13] Lote 4: Spinners e UX Feedback para Live API

**O que foi feito:**
- A função \_fetch_extra_tags\ foi refatorada de \eturn\ para \yield\ (Generator).
- Antes de iniciar o request longo à Danbooru API, a UI agora emite imediatamente um update no \xtra_status\ indicando: '⏳ Fetching live tags from Danbooru...'
- O UX recebe feedback visual imediato bloqueando cliques impacientes antes do Gradio resolver.

**Arquivos alterados:**
- \wildcard_creator/ui.py\

**Decisões técnicas:**
- Utilizou-se yield contínuo do próprio Gradio para atualizar o status em múltiplos estados de pre-flight em vez de introduzir complexidade side-effects com JS.


### [2026-03-13] Lote 5: Auto-Scrap DB on Startup

**O que foi feito:**
- Se o banco de dados principal de personagens (\characters.db\) não for encontrado ou estiver incompleto (menos de 20k de registros), a extensão agora disparará a função \scrape\ nativa do \scrape_characters.py\ silenciosamente via thread em background (daemon).
- A UI deixou de ter um \
hard
block\ exibindo aviso estático fechado. Ela agora é renderizada normalmente e informa sutilmente que o banco está sendo preenchido caso esteja menor que a quantidade total aceitável.

**Arquivos alterados:**
- \scripts/wildcard_creator.py\
- \wildcard_creator/ui.py\

**Decisões técnicas:**
- Utilizou-se \	hreading.Thread\ do tipo daemon durante o processo de build do UI para evitar que o WebUI pendure na tela de splash. A escrita não paralisa os selects pois o SQLite com timeout cuida do lock. O usuário simplesmente verá os personagens aparecendo conforme a lista progride caso forcem buscam durante o donwload.

