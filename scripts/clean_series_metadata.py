import sqlite3
import re
import logging
from pathlib import Path

# Configuração de logging baseada no projeto
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger('clean_series')

db_path = Path(__file__).parent.parent / 'data' / 'characters.db'

def process_row(name, series, tags_raw=""):
    if not series and tags_raw:
        # Fallback to the 2nd tag as the series (which is standard for Danbooru formatting)
        tag_parts = [t.strip() for t in tags_raw.split(',')]
        if len(tag_parts) >= 2:
            series = tag_parts[1].title()

    if not series:
        return name, series
        
    s_clean = series.replace(chr(92), '')
    n_clean = name.replace(chr(92), '')
    
    m_series = re.findall(r'\(([^)]+)\)', s_clean)
    
    # Se não há parênteses, apenas title() a série
    if not m_series:
        # Resolve 'fate / ...' etc
        return name, series.strip().title()
        
    # Tratamentos especiais
    last_paren = m_series[-1]
    last_paren_lower = last_paren.lower().strip()
    ignore_list = ['game', 'series', 'anime', 'manga', 'utaite', 'novel', 'visual novel', 'movie', 'cosplay', 'vtuber', 'character']

    n_base = re.sub(r'\s*\([^)]+\)', '', n_clean).strip().title()

    if last_paren_lower in ignore_list:
        true_series = s_clean.split('(')[0].strip().title()
        if len(m_series) >= 2:
            costume = m_series[-2].title()
            new_name = f"{n_base} ({costume})"
        else:
            new_name = n_base
    else:
        true_series = last_paren.title()
        if len(m_series) >= 2:
            costume = m_series[-2].title()
            new_name = f"{n_base} ({costume})"
        else:
            new_name = n_base
            
    # Ajustes finais para não quebrar nomes sem parênteses extras onde o name limpo for muito curto ou der bug.
    if len(new_name) < 2:
        new_name = name

    # Hack pra coisas aninhadas "kokoa-chan \(pan \(mimi\)\)"
    if ')' in new_name and '(' not in new_name:
        new_name = new_name.replace(')', '')
        
    return new_name, true_series

def main():
    if not db_path.exists():
        logger.error(f"Banco de dados não encontrado: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    
    c.execute('SELECT id, name, series, tags FROM characters')
    rows = c.fetchall()

    logger.info(f"Analisando {len(rows)} personagens...")

    updates = []
    
    for row in rows:
        char_id, name, series, tags_raw = row
        
        new_name, new_series = process_row(name, series, tags_raw)
        
        # Validar se de fato houve mudança
        if new_series != series or new_name != name:
            updates.append((new_name, new_series, char_id))
    
    if updates:
        logger.info(f"Foram encontradas {len(updates)} tuplas passíveis de limpeza/agrupamento.")
        
        c.executemany("UPDATE characters SET name = ?, series = ? WHERE id = ?", updates)
        conn.commit()
        logger.info("Banco atualizado com sucesso!")
    else:
        logger.info("Nenhum dado sujo encontrado para limpar.")

    conn.close()

if __name__ == '__main__':
    main()
