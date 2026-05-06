#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 2: Generate final JSON and Markdown files from ricette_split.json
Output:
  - ricette_complete.json  (structured JSON)
  - ricette_markdown/      (directory with .md files)
"""

import sys
import os
import json
import re
import logging
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

INPUT_FILE = 'ricette_split.json'
OUTPUT_JSON = 'ricette_complete.json'
OUTPUT_MD_DIR = 'ricette_markdown'

# Patterns for ingredient parsing
INGREDIENT_LINE = re.compile(
    r'(?:[-\*\u2022]?\s*)?'
    r'(?:[qQ]\.[bB]\.\s*)?'
    r'(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|cl|dl|mg|cc|bicchieri?|cucchiai?|cucchiaini?|fogli?|pizzichi?|gocce|mazzetti?|spicchi?|bustine?|noci?|prese?|tazze?|pezzi?|pugni?|etto|grammi|litri?|millilitri?|chili?|chilogrammi?)?'
    r'\s+(.+?)$',
    re.IGNORECASE
)


def sanitize_filename(name: str) -> str:
    """Convert recipe title to safe filename."""
    # Remove invalid filename chars
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.strip().replace(' ', '_')
    name = re.sub(r'_{2,}', '_', name)
    name = re.sub(r'[^\w\-\u00C0-\u024F]', '', name)
    return name[:80] or "ricetta"


def parse_date(date_str: str) -> str:
    """Parse date string to ISO format."""
    # Remove problematic chars and clean up
    date_str = date_str.strip()
    # Try to normalize: "giovedì 29 dicembre 2016 11:59"
    months_it = {
        'gennaio': '01', 'febbraio': '02', 'marzo': '03', 'aprile': '04',
        'maggio': '05', 'giugno': '06', 'luglio': '07', 'agosto': '08',
        'settembre': '09', 'ottobre': '10', 'novembre': '11', 'dicembre': '12'
    }
    months_en = {
        'january': '01', 'february': '02', 'march': '03', 'april': '04',
        'may': '05', 'june': '06', 'july': '07', 'august': '08',
        'september': '09', 'october': '10', 'november': '11', 'december': '12'
    }
    
    # Extract day name
    day_match = re.match(r'([A-Za-z\u00C0-\u024F]+)', date_str)
    if day_match:
        date_str = date_str[day_match.end():].strip().lstrip(',').strip()
    
    # Format: "29 dicembre 2016 11:59" or "dicembre 19, 2019 1:54"
    m = re.match(r'(\d{1,2})\s+(\w+)\s+(\d{4})\s*(\d{1,2}:\d{2})?', date_str)
    if m:
        day = m.group(1).zfill(2)
        month_name = m.group(2).lower()
        year = m.group(3)
        time_part = m.group(4) or "00:00"
        month = months_it.get(month_name, months_en.get(month_name, "01"))
        return f"{year}-{month}-{day} {time_part}"
    
    # Format: "dicembre 19, 2019 1:54"
    m = re.match(r'(\w+)\s+(\d{1,2}),?\s+(\d{4})\s*(\d{1,2}:\d{2})?', date_str)
    if m:
        month_name = m.group(1).lower()
        day = m.group(2).zfill(2)
        year = m.group(3)
        time_part = m.group(4) or "00:00"
        month = months_it.get(month_name, months_en.get(month_name, "01"))
        return f"{year}-{month}-{day} {time_part}"
    
    return date_str


def parse_ingredients(text: str) -> list:
    """Parse ingredient text into structured list."""
    if not text:
        return []
    
    ingredients = []
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('*') and len(line) < 3:
            continue
        
        # Try to match q.b. ingredients
        qb_match = re.match(r'(?:[-\*\u2022]?\s*)?(.*?)\s+q\.b\.', line, re.IGNORECASE)
        if qb_match and not qb_match.group(1).startswith('http'):
            name = qb_match.group(1).strip().rstrip(',').strip()
            if name and len(name) > 1:
                ingredients.append({
                    "nome": name,
                    "quantita": None,
                    "unita": "q.b.",
                    "note": ""
                })
                continue
        
        # Try to match with quantity and unit
        m = INGREDIENT_LINE.match(line)
        if m and not m.group(3).startswith('http'):
            qty = m.group(1).replace(',', '.')
            unit = m.group(2) or ""
            name = m.group(3).strip().rstrip('.,;')
            if name and len(name) > 1:
                ingredients.append({
                    "nome": name,
                    "quantita": float(qty) if '.' in qty else int(qty),
                    "unita": unit,
                    "note": ""
                })
                continue
        
        # Fallback: add as text ingredient
        clean = line.lstrip('-*\u2022 ').strip()
        if clean and len(clean) > 2 and not clean.startswith('http'):
            ingredients.append({
                "nome": clean,
                "quantita": None,
                "unita": "",
                "note": ""
            })
    
    return ingredients


def generate_markdown(recipe: dict) -> str:
    """Generate Markdown content for a recipe."""
    # Frontmatter
    md = "---\n"
    md += f"title: \"{recipe['titolo']}\"\n"
    md += f"category: \"{recipe['categoria']}\"\n"
    md += f"date: \"{parse_date(recipe.get('data', ''))}\"\n"
    if recipe.get('fonte_url'):
        md += f"source_url: \"{recipe['fonte_url']}\"\n"
    md += f"extracted_at: \"{datetime.now().isoformat()}\"\n"
    md += "---\n\n"
    
    # Title
    md += f"# {recipe['titolo']}\n\n"
    
    # Metadata
    md += "## Informazioni\n\n"
    md += f"- **Categoria**: {recipe['categoria']}\n"
    if recipe.get('data'):
        md += f"- **Data**: {recipe['data']}\n"
    if recipe.get('fonte_url'):
        md += f"- **Fonte**: [{recipe['fonte_url']}]({recipe['fonte_url']})\n"
    md += "\n"
    
    # Ingredients
    if recipe.get('ingredienti_raw'):
        md += "## Ingredienti\n\n"
        ingredients = parse_ingredients(recipe['ingredienti_raw'])
        if ingredients:
            for ing in ingredients:
                if ing['quantita'] and ing['unita']:
                    md += f"- {ing['quantita']} {ing['unita']} {ing['nome']}\n"
                elif ing['unita'] == 'q.b.':
                    md += f"- {ing['nome']} q.b.\n"
                else:
                    md += f"- {ing['nome']}\n"
        else:
            md += f"{recipe['ingredienti_raw']}\n"
        md += "\n"
    
    # Instructions
    if recipe.get('testo_completo'):
        # Strip ingredients section from instructions
        testo = recipe['testo_completo']
        ing_idx = re.search(r'[Ii]ngredienti\s*[:\n]', testo)
        if ing_idx:
            testo = testo[ing_idx.end():]
        
        md += "## Preparazione\n\n"
        # Try to format steps
        lines = testo.split('\n')
        step_num = 1
        for line in lines:
            line = line.strip()
            if not line or line.startswith('http'):
                continue
            if line.lower().startswith(('preparazione', 'procedimento', 'step by step')):
                continue
            # Check if it looks like a step number
            step_match = re.match(r'(\d+)[.)]?\s*(.*)', line)
            if step_match:
                md += f"{step_match.group(0)}\n\n"
            else:
                md += f"{line}\n\n"
    
    return md


def main():
    logger.info("=" * 60)
    logger.info("STEP 2: GENERATING JSON + MARKDOWN OUTPUTS")
    logger.info("=" * 60)
    
    # Load split recipes
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        recipes = json.load(f)
    
    logger.info(f"Caricate {len(recipes)} ricette da {INPUT_FILE}")
    
    # Update date format and add structured ingredients
    complete_recipes = []
    for recipe in recipes:
        ingredients_parsed = parse_ingredients(recipe.get('ingredienti_raw', ''))
        
        complete = {
            "titolo": recipe["titolo"],
            "categoria": recipe.get("categoria", "Altro"),
            "data": parse_date(recipe.get("data", "")),
            "data_raw": recipe.get("data", ""),
            "fonte_url": recipe.get("fonte_url", ""),
            "ingredienti": ingredients_parsed,
            "ingredienti_raw": recipe.get("ingredienti_raw", ""),
            "istruzioni": recipe.get("testo_completo", ""),
        }
        complete_recipes.append(complete)
    
    # Save JSON
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(complete_recipes, f, ensure_ascii=False, indent=2)
    logger.info(f"Salvato {OUTPUT_JSON} ({len(complete_recipes)} ricette)")
    
    # Create Markdown directory
    os.makedirs(OUTPUT_MD_DIR, exist_ok=True)
    
    md_files = []
    for recipe in complete_recipes:
        md_content = generate_markdown(recipe)
        filename = sanitize_filename(recipe['titolo']) + '.md'
        filepath = os.path.join(OUTPUT_MD_DIR, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        md_files.append(filename)
    
    logger.info(f"Salvati {len(md_files)} file Markdown in {OUTPUT_MD_DIR}/")
    
    # Create index
    index_path = os.path.join(OUTPUT_MD_DIR, 'README.md')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write("# Indice Ricette\n\n")
        f.write(f"Totale ricette: **{len(complete_recipes)}**\n\n")
        f.write("| # | Titolo | Categoria | Fonte |\n")
        f.write("|---|--------|-----------|-------|\n")
        for idx, recipe in enumerate(complete_recipes, 1):
            md_name = sanitize_filename(recipe['titolo']) + '.md'
            url_display = recipe['fonte_url'][:40] if recipe['fonte_url'] else "-"
            f.write(f"| {idx} | [{recipe['titolo']}]({md_name}) | {recipe['categoria']} | {url_display} |\n")
    
    logger.info(f"Creato indice in {index_path}")
    
    # Preview summary
    logger.info("\n--- RIEPILOGO ---")
    logger.info(f"JSON: {OUTPUT_JSON}")
    logger.info(f"Markdown: {len(md_files)} file in {OUTPUT_MD_DIR}/")
    
    cat_counts = {}
    for r in complete_recipes:
        cat = r['categoria']
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    logger.info(f"\nPer categoria:")
    for cat, count in sorted(cat_counts.items()):
        logger.info(f"  {cat}: {count}")
    
    with_url = sum(1 for r in complete_recipes if r['fonte_url'])
    with_ingredients = sum(1 for r in complete_recipes if r['ingredienti'])
    logger.info(f"\nRicette con URL fonte: {with_url}/{len(complete_recipes)}")
    logger.info(f"Ricette con ingredienti strutturati: {with_ingredients}/{len(complete_recipes)}")


if __name__ == '__main__':
    main()