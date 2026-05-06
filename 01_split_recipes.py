#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 1: Split PDF into individual recipe blocks
Uses page-by-page approach with "Ricette Page N" as separators
Output: ricette_split.json
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pdfplumber
import re
import json
import logging
from typing import List, Dict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

PDF_PATH = 'Ricette.pdf'
OUTPUT_FILE = 'ricette_split.json'

# Patterns
CATEGORY_NAMES = ['antipasti', 'primi', 'secondi', 'contorni', 'dolci', 'bevande']
PAGE_MARKER = re.compile(r'Ricette\s+Page\s+\d+', re.IGNORECASE)
URL_PATTERN = re.compile(r'https?://[^\s<>"\']+')

FROM_PATTERN = re.compile(
    r'(?:From\s*[<:]\s*|Pasted\s+from\s*[<:]\s*|Clipped\s+from\s*:?\s*'
    r'|Ritagliata\s+da\s*:?\s*|Read\s+more\s+at\s+)'
    r'(https?://[^\s<>"\']+)',
    re.IGNORECASE
)

# Date pattern - more lenient: matches lines with day-of-week + month + year + time
# But also handles no-space-between-year-and-time
DATE_PATTERN = re.compile(
    r'(?:luned[ìi]?|marted[ìi]?|mercoled[ìi]?|gioved[ìi]?|venerd[ìi]?|sabato|domenica'
    r'|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
    r'[,\s]+\d{0,2}[,\s]*'
    r'(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre'
    r'|January|February|March|April|May|June|July|August|September|October|November|December)'
    r'[,\s]+\d{2,4}\s*\d{0,2}:\d{2}',
    re.IGNORECASE
)


def extract_url(text: str) -> str:
    """Extract source URL from text."""
    m = FROM_PATTERN.search(text)
    if m:
        return m.group(1).rstrip('.,;:!?">')
    # Also check standalone ricette URLs
    m = re.search(r'https?://[^\s<>"\']*ricett[ae][^\s<>"\']*', text, re.IGNORECASE)
    if m:
        return m.group(0).rstrip('.,;:!?">')
    return ""


def extract_ingredients(text: str) -> str:
    """Extract ingredients section."""
    m = re.search(r'[Ii]ngredienti\s*[:\n]', text)
    if not m:
        return ""
    start = m.end()
    # End at preparazione/procedimento or end
    end_m = re.search(r'[Pp]reparazion[ei]\s*[:\n]|[Pp]rocedimento\s*[:\n]', text[start:])
    if end_m:
        return text[start:start+end_m.start()].strip()
    return text[start:].strip()


def main():
    logger.info("=" * 60)
    logger.info("STEP 1: SPLITTING PDF INTO RECIPES (Page-by-page)")
    logger.info("=" * 60)
    
    with pdfplumber.open(PDF_PATH) as pdf:
        total_pages = len(pdf.pages)
        logger.info(f"Totale pagine: {total_pages}")
        
        # Strategy: group pages by "Ricette Page N" boundaries
        # Each recipe block spans multiple pages between page markers
        
        all_pages_text = []
        for page_num in range(total_pages):
            text = pdf.pages[page_num].extract_text()
            if text:
                all_pages_text.append((page_num, text))
        
        logger.info(f"Pagine con testo: {len(all_pages_text)}")
        
        # Combine all text, remove page markers
        combined = ''
        for page_num, text in all_pages_text:
            combined += text + '\n'
        
        combined = PAGE_MARKER.sub('', combined)
        
        # Find all date lines - these separate recipes
        date_matches = list(DATE_PATTERN.finditer(combined))
        logger.info(f"Date trovate: {len(date_matches)}")
        
        recipes = []
        current_cat = "Altro"
        
        for idx, m in enumerate(date_matches):
            date_str = m.group().strip()
            date_start = m.start()
            date_end = m.end()
            
            # Boundaries
            if idx + 1 < len(date_matches):
                next_start = date_matches[idx + 1].start()
            else:
                next_start = len(combined)
            
            # Text before date = title area
            prev_end = date_matches[idx - 1].end() if idx > 0 else 0
            title_area = combined[prev_end:date_start].strip()
            
            # Text after date = recipe content
            recipe_text = combined[date_end:next_start].strip()
            
            # Extract title: last meaningful line in title_area
            title = ""
            for line in reversed(title_area.split('\n')):
                line = line.strip()
                if line and len(line) > 2 and not URL_PATTERN.match(line) and not line.startswith('http'):
                    # Check if it's a category header
                    if line.lower().strip() in CATEGORY_NAMES:
                        current_cat = line.lower().strip().capitalize()
                        continue
                    title = line.rstrip('.,:;')
                    break
            
            # Also detect category changes in the recipe text
            for cat_line in recipe_text.split('\n')[:3]:
                if cat_line.strip().lower() in CATEGORY_NAMES:
                    current_cat = cat_line.strip().lower().capitalize()
                    break
            
            # If title still not found, use first line of recipe text
            if not title or len(title) < 3:
                for line in recipe_text.split('\n')[:3]:
                    line = line.strip()
                    if line and len(line) > 3 and not URL_PATTERN.match(line):
                        title = line.rstrip('.,:;')[:100]
                        break
            
            # Make sure long title is cut
            if len(title) > 150:
                title = title[:150]
            
            if title and len(title) >= 2 and not title.lower().strip() in CATEGORY_NAMES:
                fonte_url = extract_url(recipe_text)
                ingredienti = extract_ingredients(recipe_text)
                
                recipe = {
                    "titolo": title,
                    "data": date_str,
                    "categoria": current_cat,
                    "fonte_url": fonte_url,
                    "ingredienti_raw": ingredienti,
                    "testo_completo": recipe_text
                }
                recipes.append(recipe)
        
        logger.info(f"Ricette estratte: {len(recipes)}")
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(recipes, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Salvate in {OUTPUT_FILE}")
        
        # Preview
        logger.info("\n--- ANTEPRIMA ---")
        for i, r in enumerate(recipes[:10]):
            logger.info(f"{i+1}. [{r['categoria']}] {r['titolo'][:60]}")
            if r['fonte_url']:
                logger.info(f"   URL: {r['fonte_url'][:80]}")


if __name__ == '__main__':
    main()