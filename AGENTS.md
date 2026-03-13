# AGENTS.md

## Visão geral

**Projeto:** SD Character Finder (`sd-character-finder`)

**Objetivo:** Extensão para SD WebUI (AUTOMATIC1111 / Forge / Forge Neo) para navegar em um banco de 20 mil+ personagens Danbooru e enviar suas tags de prompt diretamente para o txt2img.

**Público-alvo:** Usuários de SD que querem encontrar rapidamente as tags corretas de personagens anime/jogo para seus prompts.

**Modo de uso principal:** Extensão instalada no SD WebUI (registrada via `script_callbacks.on_ui_tabs`). Também roda em modo standalone local para desenvolvimento sem GPU.

**Estado atual:** Single-tab — apenas o browser de personagens está ativo na UI. Arquitetura simplificada focada exclusivamente em consultar o banco de personagens e enviar prompts as UIs do SD. Módulos relacionados a criação de pacotes ("packs") e de receitas foram removidos para reduzir complexidade.

---

## Tech stack

| Camada | Tecnologia | Versão |
|---|---|---|
| **UI** | Gradio | ≥ 4.x (SD WebUI Forge nativo) |
| **Backend** | Python | 3.10+ |
| **Serialização** | PyYAML | ≥ 6.0 |
| **HTTP / Danbooru API** | requests | ≥ 2.31 |
| **WebUI integration** | modules.script_callbacks, modules.generation_parameters_copypaste | A1111 / Forge |
| **Storage** | Sistema de arquivos local (`pathlib.Path`) | — |
| **Empacotamento** | (removido, foco apenas em search/export) | — |
| **Deploy** | SD WebUI Extensions (git clone) ou RunPod remoto | — |

**Libs críticas instaladas via `install.py`:** `pyyaml`, `requests`  
`gradio` já está disponível pelo SD WebUI — não instalar manualmente.

---

## Comandos de desenvolvimento

### Standalone (sem SD WebUI / sem GPU)
```bash
pip install gradio beautifulsoup4 requests
python -m wildcard_creator.ui          # porta padrão 7861
python -m wildcard_creator.ui 7862     # porta customizada
```
Acesse: **http://127.0.0.1:7861**

### Smoke test dos módulos core
```bash
python -c "
import sys; sys.path.insert(0, '.')
from wildcard_creator import character_db as cdb
db = cdb.get_character_db()
print('populated:', db.is_populated())
print('count:', db.count())
print('sample:', db.search('miku', limit=3))
"
```

### Build/export de um pack
```python
from wildcard_creator.pack_manager import export_pack_zip
zip_bytes = export_pack_zip("my_pack")
open("my_pack.zip", "wb").write(zip_bytes)
```

### Deploy no RunPod
1. Fazer push do repositório
2. No RunPod: `git clone` na pasta `extensions/` do SD WebUI
3. Reiniciar o WebUI

---

## Arquitetura de alto nível

### Estrutura de pastas

```
sd-character-finder/                ← raiz da extensão SD WebUI
├── install.py                      ← pip install pyyaml + requests ao iniciar WebUI
├── scripts/
│   └── wildcard_creator.py         ← PONTO DE ENTRADA: registra on_ui_tabs()
├── wildcard_creator/               ← pacote Python principal
│   ├── __init__.py
│   ├── character_db.py             ← CRUD SQLite: busca, filtro, card
│   ├── danbooru.py                 ← API client + CSV local (tags)
│   ├── pack_manager.py             ← CRUD de packs (desconectado da UI)
│   ├── recipe_engine.py            ← engine de receitas (desconectado)
│   ├── prompt_sender.py            ← send to txt2img ou clipboard fallback
│   └── ui.py                       ← UI Gradio single-tab: Characters
├── packs/                          ← dados de usuário (gitignore recomendado)
│   └── example_sfw/               ← pack de exemplo (herdado, não usado na UI)
│       ├── pack.json
│       ├── styles.csv
│       ├── wildcards/              ← .txt por categoria
│       └── recipes/                ← .yaml por recipe
├── data/
│   ├── characters.db               ← SQLite principal (20.016 chars)
│   └── danbooru_tags.csv           ← ~200 tags curadas (offline fallback)
└── README.md
```

### Como os módulos se conectam

```
scripts/wildcard_creator.py
  └─ on_ui_tabs() → wildcard_creator/ui.py → build_ui()
                        ├─ character_db.py   (busca SQLite)
                        ├─ danbooru.py       (API live opcional)
                        └─ prompt_sender.py  (envio ao txt2img)
```

### Fluxo de dados principal (UI atual)

1. **Busca**: usuário digita query + filtros → `character_db.search()` → resultados em tabela
2. **Seleção**: clique na linha → `on_row_select()` preenche card com tags do DB
3. **Envio**: botões usam JS para injetar tags no `#txt2img_prompt` ou copiar para clipboard
4. **Enriquecimento opcional**: accordion "Extra tags" → `danbooru.fetch_character_post_tags()` → checkboxes → aplicar com ordenação NovelAI-like

### Pontos de entrada / saída

| Ponto | Função |
|---|---|
| Entrada WebUI | `scripts/wildcard_creator.py` → `on_ui_tabs()` |
| Entrada standalone | `wildcard_creator/ui.py` → `if __name__ == "__main__"` |
| Saída prompts | JS injection em `#txt2img_prompt` ou clipboard |
| Dados principais | `data/characters.db` (SQLite, incluso no repo) |

---

## Invariantes e restrições críticas

### 1. Compatibilidade SD WebUI
- `modules.*` só existe dentro do WebUI — sempre usar `try/except ImportError` para qualquer import de `modules`
- `install.py` usa `launch.is_installed()` / `launch.run_pip()` — nunca chamar `pip` diretamente
- `gradio` NÃO deve ser instalado como dependência — já vem do WebUI

### 2. Nenhum estado mutável em nível de módulo
- `DanbooruDB` é instanciada como singleton lazy via `get_db()` — aceitável
- Funções de `pack_manager` são stateless (sempre leem do disco)
- Nenhuma variável global mutável fora de `get_db()`

### 3. Nunca lançar exceção para o Gradio callback
- Todos os event handlers em `ui.py` têm `try/except` com retorno de mensagem de erro
- Erros de I/O retornam string `"❌ <motivo>"` para a textbox de status

### 4. Paths sempre via `pathlib.Path`
- `ui._discover_wildcard_dirs()` → Busca pastas na raiz do WebUI
- Nunca concatenar strings para paths

### 5. Configurações Integradas (A partir da v1.2.0)
- Configurações (ex: limite de busca, chaves de API, rates) no `shared.opts`
- Variáveis são registradas em `scripts/wildcard_creator.py` e extraídas de modo fault-tolerant.

### 6. Danbooru API
- Credenciais NUNCA commitadas — usuário insere na UI em campo `type="password"`
- Live API é opcional — extensão funciona 100% offline com `data/danbooru_tags.csv`
- `USEFUL_CATEGORIES = {0, 4}` — apenas tags general + character (evita artists/meta)

### 8. Gradio 4.x
- Usar `gr.update(choices=..., value=...)` nos event handlers (não retornar listas nuas)
- `gr.Code(language="yaml")` para o editor YAML
- Sem workarounds de Gradio 3.x (`gr.Box`, `gr.Variable`, etc.)
- Dropdowns pré-populados com `value=` no construtor — Gradio 4 não dispara `.change` no load

---

## Versionamento

O projeto segue **Semantic Versioning** `vX.Y.Z`:

| Campo | Tipo | Quando usar |
|---|---|---|
| **X** (major) | Quebra de arquitetura | Mudança incompatível com versões anteriores. Ex.: troca de DB schema, reestruturação de API, mudança de motor. |
| **Y** (minor) | Nova feature | Nova funcionalidade retrocompatível. Ex.: novo filtro de busca, novo endpoint, nova ação de botão. |
| **Z** (patch) | Bug fix / estabilidade | Correção que não altera comportamento esperado. Ex.: crash fix, seletor CSS errado, fallback de clipboard. |

**Versão atual:** `v1.2.0`

---

## Documentos fonte a consultar

| Documento | Conteúdo |
|---|---|
| [README.md](README.md) | Features, instalação, formato de pack, compatibilidade |
| [docs/PROJECT_LOG.md](docs/PROJECT_LOG.md) | Histórico de decisões, mudanças por data |
| [AGENTS.md](AGENTS.md) | Este arquivo — visão técnica completa |
| [wildcard_creator/pack_manager.py](wildcard_creator/pack_manager.py) | API completa de CRUD |
| [wildcard_creator/recipe_engine.py](wildcard_creator/recipe_engine.py) | Lógica de resolução de tokens |
| [packs/example_sfw/](packs/example_sfw/) | Pack de referência com estrutura completa |

---

## Padrões de prompting para este projeto

### Antes de qualquer mudança
1. Ler `AGENTS.md` (este arquivo) — invariantes e arquitetura
2. Ler `docs/PROJECT_LOG.md` — última mudança e estado atual
3. Ler `README.md` — features comprometidas com o usuário
4. Resumir em pt-BR: escopo, invariantes relevantes, última mudança

### Workflow obrigatório
```
RESEARCH → PLAN (aguardar aprovação) → EXECUTE → VALIDATE
```

### Ao criar/editar código
- Verificar invariantes 1–8 antes de escrever qualquer linha
- Para event handlers Gradio: sempre `try/except`, sempre retornar `gr.update()`
- Para I/O de arquivos: sempre `pathlib.Path`, sempre `encoding="utf-8"`
- Para imports de `modules.*`: sempre dentro de `try/except`

### Após mudanças significativas
1. Atualizar `docs/PROJECT_LOG.md` com entrada datada em português
2. Se arquitetura/features mudaram, atualizar `AGENTS.md`
3. Se relevante para usuários, sugerir atualização do `README.md`

### Code em inglês, chat em português brasileiro
