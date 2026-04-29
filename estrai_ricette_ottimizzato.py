#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Estrazione Ricette ottimizzata - Pattern-based (NO LLM)

Identifica ricette usando il separatore:
  Titolo ricetta (con fonte)
  Data/timestamp

Estratto veloce e diretto in PostgreSQL.
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pdfplumber
import psycopg2
from psycopg2 import sql
import re
import json
import logging
import os
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from dotenv import load_dotenv
from tqdm import tqdm

# ============================================================================
# CONFIGURAZIONE
# ============================================================================

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'postgres'),
    'database': os.getenv('DB_NAME', 'ricette_db'),
    'port': int(os.getenv('DB_PORT', 5432))
}

PDF_PATH = 'ricette.pdf'
CHECKPOINT_FILE = 'checkpoint.json'
LOG_FILE = 'estrai_ricette_ottimizzato.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class RecipePage:
    """Una singola ricetta potrebbe occupare più pagine"""
    page_num: int
    text: str

@dataclass
class Recipe:
    titolo: str
    data: str = ""
    fonte_url: str = ""
    ingredienti: str = ""
    istruzioni: str = ""
    categoria: str = "Altro"
    
    def to_dict(self):
        return {
            'titolo': self.titolo,
            'data': self.data,
            'fonte_url': self.fonte_url,
            'ingredienti': self.ingredienti,
            'istruzioni': self.istruzioni,
            'categoria': self.categoria
        }

# ============================================================================
# PATTERN-BASED EXTRACTOR
# ============================================================================

class PatternExtractor:
    """Estrae ricette usando pattern di separazione"""
    
    # Pattern semplice: linea che inizia con giorno della settimana = data
    # Il titolo è tutto quello PRIMA della data
    DATA_PATTERN = re.compile(
        r'^((?:lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica|\w+day)[^\n]*\d{1,2}[:\-/]\d{2})',
        re.MULTILINE | re.IGNORECASE
    )
    
    # Ricerca URL (fonte)
    URL_PATTERN = re.compile(r'https?://[^\s\|]+')
    
    # Ricerca ingredienti
    INGREDIENTS_MARKER = re.compile(r'[Ii]ngredient[i]*\s*:?', re.IGNORECASE)
    PREPARATION_MARKER = re.compile(r'[Pp]reparazion[e]*\s*:?|[Ii]struction[s]*', re.IGNORECASE)
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        
    def extract_all(self, max_pages: Optional[int] = None) -> List[Recipe]:
        """Estrae tutte le ricette dal PDF"""
        logger.info(f"Lettura {self.pdf_path}...")
        
        recipes = []
        pages_text = []
        
        with pdfplumber.open(self.pdf_path) as pdf:
            total_pages = len(pdf.pages)
            if max_pages:
                total_pages = min(total_pages, max_pages)
            
            logger.info(f"Pagine da leggere: {total_pages}")
            
            # Estrai testo da tutte le pagine
            for page_num in range(total_pages):
                page = pdf.pages[page_num]
                text = page.extract_text()
                if text:
                    pages_text.append(text)
        
        # Combina tutto il testo
        full_text = '\n'.join(pages_text)
        
        # Dividi in ricette usando il pattern
        recipes = self._split_by_header(full_text)
        
        logger.info(f"Estratte {len(recipes)} ricette")
        return recipes
    
    def _split_by_header(self, text: str) -> List[Recipe]:
        """Divide il testo in ricette usando il pattern data (separatore)"""
        recipes = []
        
        # Trova tutte le date (inizio di ricette)
        matches = list(self.DATA_PATTERN.finditer(text))
        
        logger.info(f"Found {len(matches)} potential recipe dates")
        
        for idx, match in enumerate(matches):
            try:
                # La data è il separatore
                data = match.group(1).strip()
                
                # Il titolo è tutto il testo PRIMA della data, fino alla ricetta precedente
                start_pos = matches[idx - 1].end() if idx > 0 else 0
                end_pos = match.start()
                
                titolo_raw = text[start_pos:end_pos].strip()
                # Prendi solo l'ultima linea come titolo (le precedenti appartengono alla ricetta prima)
                titolo = titolo_raw.split('\n')[-1].strip() if titolo_raw else ""
                
                # Il testo della ricetta va dalla data al prossimo match
                recipe_start = match.end()
                recipe_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
                
                recipe_text = text[recipe_start:recipe_end].strip()
                
                # Estrai componenti
                url_match = self.URL_PATTERN.search(recipe_text)
                fonte_url = url_match.group(0) if url_match else ""
                
                ingredienti, istruzioni = self._extract_sections(recipe_text)
                
                categoria = self._categorize(titolo)
                
                recipe = Recipe(
                    titolo=titolo,
                    data=data,
                    fonte_url=fonte_url,
                    ingredienti=ingredienti,
                    istruzioni=istruzioni,
                    categoria=categoria
                )
                
                if titolo and len(titolo) > 3:
                    recipes.append(recipe)
                    
            except Exception as e:
                logger.warning(f"Errore parsing ricetta #{idx}: {e}")
        
        return recipes
    
    def _extract_sections(self, text: str) -> Tuple[str, str]:
        """Estrae ingredienti e istruzioni dal testo della ricetta"""
        ingredienti = ""
        istruzioni = ""
        
        # Limita a primi 2000 caratteri per velocità
        text_limited = text[:2000]
        
        # Cerca marca di ingredienti
        ing_match = self.INGREDIENTS_MARKER.search(text_limited)
        prep_match = self.PREPARATION_MARKER.search(text_limited)
        
        if ing_match and prep_match:
            if ing_match.start() < prep_match.start():
                ingredienti = text[ing_match.end():prep_match.start()].strip()
                istruzioni = text[prep_match.end():].strip()
            else:
                istruzioni = text[ing_match.end():].strip()
        elif ing_match:
            ingredienti = text[ing_match.end():].strip()
        elif prep_match:
            istruzioni = text[prep_match.end():].strip()
        else:
            # Se non trova sezioni, usa tutto il testo come istruzioni
            istruzioni = text_limited.strip()
        
        # Limita lunghezza
        ingredienti = ingredienti[:1000] if ingredienti else ""
        istruzioni = istruzioni[:3000] if istruzioni else ""
        
        return ingredienti, istruzioni
    
    @staticmethod
    def _categorize(titolo: str) -> str:
        """Categorizza la ricetta dal titolo (euristico semplice)"""
        title_lower = titolo.lower()
        
        if any(word in title_lower for word in ['antipasto', 'antipasti', 'aperitivo', 'stuzzichino']):
            return 'Antipasti'
        elif any(word in title_lower for word in ['pasta', 'risotto', 'minestrone', 'zuppa', 'primo']):
            return 'Primi'
        elif any(word in title_lower for word in ['carne', 'pesce', 'pollo', 'secondo', 'bistecca']):
            return 'Secondi'
        elif any(word in title_lower for word in ['verdura', 'insalata', 'contorno', 'patata']):
            return 'Contorni'
        elif any(word in title_lower for word in ['dolce', 'dolci', 'cake', 'torta', 'biscotto', 'dessert', 'mousse']):
            return 'Dolci'
        elif any(word in title_lower for word in ['drink', 'cocktail', 'bevanda', 'succo', 'bibita']):
            return 'Bevande'
        else:
            return 'Altro'

# ============================================================================
# DATABASE
# ============================================================================

class RecipeDB:
    """Gestisce salvataggio in PostgreSQL"""
    
    def __init__(self, config: Dict):
        self.config = config
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Verifica che le tabelle esistano"""
        conn = psycopg2.connect(**self.config)
        try:
            with conn.cursor() as cur:
                # Verifica se tabella ricette esiste
                cur.execute("""
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'ricette'
                """)
                if not cur.fetchone():
                    logger.warning("Tabelle non trovate - esegui prima estraiRicette.py per inizializzarle")
                    raise RuntimeError("Database non inizializzato")
            conn.commit()
        finally:
            conn.close()
    
    def insert_recipe(self, recipe: Recipe) -> bool:
        """Inserisce una ricetta nel DB. Ritorna True se inserita, False se duplicata"""
        conn = psycopg2.connect(**self.config)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ricette 
                    (titolo, categoria, istruzioni, fonte_url)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (titolo) DO NOTHING
                    RETURNING id
                """, (
                    recipe.titolo,
                    recipe.categoria,
                    recipe.istruzioni,
                    recipe.fonte_url
                ))
                
                result = cur.fetchone()
                if result:
                    ricetta_id = result[0]
                    
                    # Inserisci ingredienti se presenti
                    if recipe.ingredienti:
                        self._insert_ingredients(cur, ricetta_id, recipe.ingredienti)
                    
                    conn.commit()
                    return True
                else:
                    # Duplicata - skip
                    return False
        except Exception as e:
            logger.error(f"Errore insert {recipe.titolo}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def _insert_ingredients(self, cursor, ricetta_id: int, ingredienti_text: str):
        """Inserisce ingredienti come testo unico per semplicità"""
        # Per semplicità, salva ingredienti come testo singolo
        # In futuro si potrebbe fare parsing più sofisticato
        lines = ingredienti_text.split('\n')
        
        for idx, line in enumerate(lines):
            line = line.strip()
            if line and len(line) > 2:
                cursor.execute("""
                    INSERT INTO ricette_ingredienti
                    (ricetta_id, nome, ordine)
                    VALUES (%s, %s, %s)
                """, (ricetta_id, line[:100], idx))

# ============================================================================
# CHECKPOINT
# ============================================================================

class Checkpoint:
    """Traccia ricette già elaborate"""
    
    def __init__(self, filepath: str = CHECKPOINT_FILE):
        self.filepath = filepath
        self.titles = self._load()
    
    def _load(self) -> set:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data) if isinstance(data, list) else set()
            except:
                return set()
        return set()
    
    def mark(self, title: str):
        self.titles.add(title)
    
    def has(self, title: str) -> bool:
        return title in self.titles
    
    def save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(list(self.titles), f, indent=2, ensure_ascii=False)

# ============================================================================
# MAIN PIPELINE
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Estrai ricette ottimizzato')
    parser.add_argument('--max-pages', type=int, default=None, help='Max pagine da leggere')
    parser.add_argument('--preview', action='store_true', help='Mostra preview senza salvare')
    
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("ESTRAZIONE RICETTE OTTIMIZZATA (Pattern-based)")
    logger.info("=" * 70)
    
    try:
        # Estrai ricette
        extractor = PatternExtractor(PDF_PATH)
        recipes = extractor.extract_all(max_pages=args.max_pages)
        
        if not recipes:
            logger.warning("Nessuna ricetta estratta")
            return
        
        logger.info(f"\nEstrazione completata: {len(recipes)} ricette trovate")
        
        # Preview (mostra prime 5)
        if args.preview:
            logger.info("\n--- PREVIEW PRIME 5 RICETTE ---")
            for i, recipe in enumerate(recipes[:5]):
                logger.info(f"\n{i+1}. {recipe.titolo}")
                logger.info(f"   Data: {recipe.data}")
                logger.info(f"   Categoria: {recipe.categoria}")
                logger.info(f"   URL: {recipe.fonte_url[:60] if recipe.fonte_url else 'N/A'}")
                if recipe.ingredienti:
                    logger.info(f"   Ingredienti: {recipe.ingredienti[:100]}...")
            return
        
        # Salva nel DB
        checkpoint = Checkpoint()
        db = RecipeDB(DB_CONFIG)
        
        inserted = 0
        duplicates = 0
        
        logger.info("\nSalvataggio nel DB...")
        for recipe in tqdm(recipes, desc="Salvataggio ricette"):
            if checkpoint.has(recipe.titolo):
                duplicates += 1
                continue
            
            if db.insert_recipe(recipe):
                inserted += 1
                checkpoint.mark(recipe.titolo)
        
        checkpoint.save()
        
        logger.info("\n" + "=" * 70)
        logger.info(f"COMPLETATO: {inserted} inserite, {duplicates} duplicate")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"Errore: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
