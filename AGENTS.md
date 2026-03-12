# AGENTS.md

## Visão geral

**Projeto:** SD Character Finder (`sd-character-finder`)

**Objetivo:** Extensão para SD WebUI (AUTOMATIC1111 / Forge) para navegar em um banco de 20 mil+ personagens Danbooru e enviar suas tags de prompt diretamente para o txt2img.

**Público-alvo:** Usuários de SD que querem encontrar rapidamente as tags corretas de personagens anime/jogo para seus prompts.

**Modo de uso principal:** Extensão instalada no SD WebUI (registrada via `script_callbacks.on_ui_tabs`). Também roda em modo standalone local para desenvolvimento sem GPU.

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
| **Empacotamento** | zipfile + io.BytesIO (stdlib) | — |
| **Deploy** | SD WebUI Extensions (git clone) ou RunPod remoto | — |

**Libs críticas instaladas via `install.py`:** `pyyaml`, `requests`  
`gradio` já está disponível pelo SD WebUI — não instalar manualmente.

---

## Comandos de desenvolvimento

### Standalone (sem SD WebUI / sem GPU)
```bash
pip install gradio pyyaml requests
python -m wildcard_creator.ui          # porta padrão 7861
python -m wildcard_creator.ui 7862     # porta customizada
```
Acesse: **http://127.0.0.1:7861**

### Smoke test dos módulos core
```bash
python -c "
import sys; sys.path.insert(0, '.')
from wildcard_creator import pack_manager as pm, recipe_engine as re
from wildcard_creator.danbooru import get_db
print(pm.list_packs())
print(pm.get_all_category_paths('example_sfw'))
print(get_db().tag_count())
pos, neg = re.roll_recipe('example_sfw', 'portrait_girl')
print(pos[:80])
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
│   ├── pack_manager.py             ← CRUD: packs, categorias, receitas, CSV, zip
│   ├── recipe_engine.py            ← resolve __tokens__, roll prompts, parse YAML
│   ├── danbooru.py                 ← DB de tags (CSV local + API live)
│   ├── prompt_sender.py            ← send to txt2img ou clipboard fallback
│   └── ui.py                       ← UI Gradio 3 tabs, build_ui() + build_standalone_ui()
├── packs/                          ← dados de usuário (gitignore recomendado)
│   └── example_sfw/               ← pack de exemplo incluído
│       ├── pack.json
│       ├── styles.csv
│       ├── wildcards/              ← .txt por categoria (subpastas = subcategorias)
│       └── recipes/                ← .yaml por recipe
├── data/
│   └── danbooru_tags.csv           ← ~200 tags curadas, carregadas offline
└── README.md
```

### Como os módulos se conectam

```
scripts/wildcard_creator.py
  └─ on_ui_tabs() → wildcard_creator/ui.py → build_ui()
                        ├─ pack_manager.py   (leitura/escrita de arquivos)
                        ├─ recipe_engine.py  (resolução de __tokens__)
                        ├─ danbooru.py       (busca de tags)
                        └─ prompt_sender.py  (envio para txt2img)
```

### Fluxo de dados principal

1. **Pack Editor**: usuário cria pack → `pack_manager.create_pack()` → cria `packs/<name>/wildcards/` + `recipes/` + `pack.json`
2. **Edição de categoria**: textarea → `pack_manager.save_category()` → grava `<cat>.txt` e `<cat>_negative.txt`
3. **Recipe Editor**: YAML editado → `pack_manager.save_recipe_raw()` → grava `recipes/<name>.yaml`
4. **Generate**: pack + recipe + entry → `recipe_engine.get_recipe_entries()` → `roll_recipe_entry()` → `_pick_variant()` → lê `.txt` aleatoriamente → prompts resolvidos → `prompt_sender.send_to_txt2img()`
5. **Export**: `pack_manager.export_pack_zip()` → `zipfile.ZipFile` em memória → download via `gr.File`

### Pontos de entrada / saída

| Ponto | Função |
|---|---|
| Entrada WebUI | `scripts/wildcard_creator.py` → `on_ui_tabs()` |
| Entrada standalone | `wildcard_creator/ui.py` → `if __name__ == "__main__"` |
| Saída prompts | `prompt_sender.send_to_txt2img()` ou clipboard |
| Saída exportação | `pack_manager.export_pack_zip()` → bytes `.zip` |

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
- `pack_manager._ext_dir()` → `Path(__file__).parent.parent` — raiz da extensão
- `get_packs_dir()` → `_ext_dir() / "packs"` — cria se não existir
- Nunca concatenar strings para paths

### 5. Formato de arquivo do pack (não quebrar)
- `<category>.txt` — variantes positivas, uma por linha
- `<category>_negative.txt` — variantes negativas, one per line  
- `<subcategory/path>.txt` — subpastas suportadas (ex: `hair/color.txt`)
- `recipes/<name>.yaml` — YAML compatível com sd-dynamic-prompts
- `styles.csv` — 5 colunas: `name,prompt,negative_prompt,description,category`
- `pack.json` — metadata JSON com `name, version, description, rating, author`

### 6. Token wildcard `__category__`
- Padrão regex: `__([a-zA-Z0-9_/\-]+)__`
- `hair/color` → lê `wildcards/hair/color.txt`
- Fallback se arquivo não existe: retorna `(category)` como hint visual, sem crash

### 7. Danbooru API
- Credenciais NUNCA commitadas — usuário insere na UI em campo `type="password"`
- Live API é opcional — extensão funciona 100% offline com `data/danbooru_tags.csv`
- `USEFUL_CATEGORIES = {0, 4}` — apenas tags general + character (evita artists/meta)

### 8. Gradio 4.x
- Usar `gr.update(choices=..., value=...)` nos event handlers (não retornar listas nuas)
- `gr.Code(language="yaml")` para o editor YAML
- Sem workarounds de Gradio 3.x (`gr.Box`, `gr.Variable`, etc.)
- Dropdowns pré-populados com `value=` no construtor — Gradio 4 não dispara `.change` no load

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
