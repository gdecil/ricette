#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Estrazione Ricette da PDF → PostgreSQL con Ollama LLM (Locale)

Script per estrarre ricette da ricette.pdf e inserirle in PostgreSQL.
Usa Ollama (qwen3-coder:30b) per parsing intelligente in italiano.

Vantaggi:
- LLM locale (gratis, offline, niente API key)
- Parsing strutturato con prompt in italiano
- Batch insert efficiente
- Checkpoint per evitare duplicati
- Retry logic con backoff
- Progress tracking
"""

import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import pdfplumber
import psycopg2
from psycopg2 import sql
import re
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import requests
from tqdm import tqdm
from pathlib import Path
from dotenv import load_dotenv
import traceback

# ============================================================================
# CONFIGURAZIONE
# ============================================================================

load_dotenv()

# Database config
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'postgres'),
    'database': os.getenv('DB_NAME', 'ricette_db'),
    'port': int(os.getenv('DB_PORT', 5432))
}

# Ollama config
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen3-coder:30b')
OLLAMA_TIMEOUT = int(os.getenv('OLLAMA_TIMEOUT', 120))  # secondi

# File paths
PDF_PATH = 'ricette.pdf'
CHECKPOINT_FILE = 'checkpoint.json'
LOG_FILE = 'estrai_ricette_ollama.log'

# Batch config
BATCH_SIZE = 50
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
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
class Ingrediente:
    nome: str
    quantita: Optional[float] = None
    unita_misura: Optional[str] = None
    note: Optional[str] = None
    ordine: int = 0

    def to_dict(self):
        return {
            'nome': self.nome,
            'quantita': self.quantita,
            'unita_misura': self.unita_misura,
            'note': self.note,
            'ordine': self.ordine
        }

@dataclass
class Ricetta:
    titolo: str
    categoria: str = 'Altro'
    istruzioni: str = ''
    tempo_preparazione: int = 0
    tempo_cottura: int = 0
    porzioni: int = 4
    difficolta: str = 'Media'
    fonte_url: Optional[str] = None
    ingredienti: List[Ingrediente] = None

    def __post_init__(self):
        if self.ingredienti is None:
            self.ingredienti = []

    def to_dict(self):
        return {
            'titolo': self.titolo,
            'categoria': self.categoria,
            'istruzioni': self.istruzioni,
            'tempo_preparazione': self.tempo_preparazione,
            'tempo_cottura': self.tempo_cottura,
            'porzioni': self.porzioni,
            'difficolta': self.difficolta,
            'fonte_url': self.fonte_url,
            'ingredienti': [ing.to_dict() for ing in self.ingredienti]
        }

# ============================================================================
# OLLAMA CLIENT
# ============================================================================

class OllamaClient:
    """Client per comunicare con Ollama LLM locale"""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_MODEL):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self._check_connectivity()

    def _check_connectivity(self):
        """Verifica che Ollama sia online e il modello disponibile"""
        try:
            response = requests.get(f'{self.base_url}/api/tags', timeout=5)
            response.raise_for_status()
            models = response.json().get('models', [])
            model_names = [m['name'] for m in models]
            
            if self.model not in model_names:
                logger.error(f"Modello {self.model} non trovato in Ollama")
                logger.info(f"Modelli disponibili: {model_names}")
                raise RuntimeError(f"Modello {self.model} non disponibile")
            
            logger.info(f"[OK] Ollama online con modello {self.model}")
        except Exception as e:
            logger.error(f"[ERROR] Ollama non raggiungibile o modello non disponibile: {e}")
            raise

    def parse_recipe(self, text: str, retries: int = MAX_RETRIES) -> Optional[Dict[str, Any]]:
        """
        Usa Ollama per parsare un blocco di testo ricetta.
        Ritorna dict strutturato con ingredienti, tempi, categoria, etc.
        """
        prompt = self._build_prompt(text)
        
        for attempt in range(1, retries + 1):
            try:
                response = requests.post(
                    f'{self.base_url}/api/generate',
                    json={
                        'model': self.model,
                        'prompt': prompt,
                        'stream': False,
                        'temperature': 0.3,  # Bassa temp per parsing strutturato
                    },
                    timeout=OLLAMA_TIMEOUT
                )
                response.raise_for_status()
                
                result = response.json()
                generated_text = result.get('response', '').strip()
                
                # Estrai JSON dalla risposta
                parsed = self._extract_json(generated_text)
                if parsed:
                    logger.debug(f"[OK] Parsing riuscito: {parsed.get('refined_title', 'N/A')}")
                    return parsed
                else:
                    logger.warning(f"Nessun JSON trovato in risposta Ollama (tentativo {attempt}/{retries})")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout Ollama (tentativo {attempt}/{retries})")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Errore Ollama (tentativo {attempt}/{retries}): {e}")
            except Exception as e:
                logger.warning(f"Errore parsing (tentativo {attempt}/{retries}): {e}")
            
            if attempt < retries:
                wait_time = RETRY_BACKOFF_SECONDS ** attempt
                logger.debug(f"Retry in {wait_time}s...")
                time.sleep(wait_time)
        
        logger.error(f"Parsing fallito dopo {retries} tentativi")
        return None

    @staticmethod
    def _build_prompt(text: str) -> str:
        """Costruisce il prompt per Ollama in italiano"""
        text_chunk = text[:2000].strip()  # Limita lunghezza per efficienza
        
        return f"""Sei un esperto di ricette italiane. Analizza il seguente testo di ricetta ed estrai i dati strutturati.

TESTO RICETTA:
{text_chunk}

ISTRUZIONI:
1. Estrai SOLO i dati presenti nel testo (non inventare)
2. Se un campo manca nel testo, omettilo dal JSON
3. Tempo in MINUTI, porzioni in NUMERO INTERO
4. Difficoltà: Facile/Media/Difficile
5. Ingredienti: solo nome, quantita, unita_misura (es: 100, g)
6. Ritorna SOLO JSON valido, niente altro

FORMATO JSON RISPOSTA (ritorna SOLO questo JSON):
{{
  "refined_title": "Titolo ricetta (pulito)",
  "category": "Antipasti/Primi/Secondi/Contorni/Dolci/Bevande/Altro",
  "istruzioni": "Preparazione e cottura (primo paragrafo)",
  "tempo_preparazione": 30,
  "tempo_cottura": 20,
  "porzioni": 4,
  "difficolta": "Media",
  "ingredienti": [
    {{"nome": "olio", "quantita": 3, "unita_misura": "cucchiai"}},
    {{"nome": "sale", "quantita": 1, "unita_misura": "pizzico"}}
  ]
}}"""

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Estrae e valida JSON dalla risposta di Ollama"""
        try:
            # Prova a trovare JSON nel testo
            json_match = re.search(r'\{[\s\S]*\}', text)
            if not json_match:
                return None
            
            json_str = json_match.group()
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.debug(f"JSON non valido: {e}")
            return None

# ============================================================================
# PDF PARSER
# ============================================================================

class PDFRecipeExtractor:
    """Estrae blocchi ricette dal PDF"""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF non trovato: {pdf_path}")
        
        # Pattern per identificare titoli ricette (stesso dello script originale)
        self.header_pattern = re.compile(r"^(.+?):?\s*(?:\||$)", re.MULTILINE)

    def extract_recipe_blocks(self, max_pages: Optional[int] = None) -> List[str]:
        """
        Estrae blocchi di testo corrispondenti a ricette dal PDF.
        Processa pagina per pagina e raggruppa finché non trova un nuovo titolo.
        """
        logger.info(f"Leggendo {self.pdf_path}...")
        
        blocks = []
        with pdfplumber.open(self.pdf_path) as pdf:
            total_pages = len(pdf.pages)
            if max_pages:
                total_pages = min(total_pages, max_pages)
            logger.info(f"Pagine da processare: {total_pages}")
            
            current_block = ""
            
            for page_num in range(total_pages):
                page = pdf.pages[page_num]
                text = page.extract_text()
                if not text:
                    continue
                
                # Controlla se questa pagina contiene un titolo
                if self.header_pattern.search(text):
                    # Se abbiamo un blocco precedente, salvalo
                    if current_block and len(current_block.strip()) > 50:
                        blocks.append(current_block.strip())
                    current_block = text
                else:
                    # Altrimenti, aggiungi a blocco corrente
                    current_block += "\n" + text
            
            # Salva ultimo blocco
            if current_block and len(current_block.strip()) > 50:
                blocks.append(current_block.strip())
        
        logger.info(f"Estratti {len(blocks)} blocchi ricetta dal PDF")
        return blocks

# ============================================================================
# DATABASE
# ============================================================================

class RecipeDatabase:
    """Gestisce connessione e operazioni su PostgreSQL"""

    def __init__(self, config: Dict[str, str]):
        self.config = config
        self._ensure_tables_exist()

    def _ensure_tables_exist(self):
        """Crea le tabelle se non esistono"""
        conn = None
        try:
            conn = psycopg2.connect(**self.config)
            
            with conn.cursor() as cur:
                # Tabella ricette
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ricette (
                        id SERIAL PRIMARY KEY,
                        titolo VARCHAR(255) UNIQUE NOT NULL,
                        categoria VARCHAR(100) NOT NULL DEFAULT 'Altro',
                        istruzioni TEXT NOT NULL,
                        tempo_preparazione INTEGER DEFAULT 0,
                        tempo_cottura INTEGER DEFAULT 0,
                        porzioni INTEGER DEFAULT 4,
                        difficolta VARCHAR(50) DEFAULT 'Media',
                        fonte_url VARCHAR(500),
                        data_inserimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Tabella ingredienti
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ricette_ingredienti (
                        id SERIAL PRIMARY KEY,
                        ricetta_id INTEGER NOT NULL REFERENCES ricette(id) ON DELETE CASCADE,
                        nome VARCHAR(100) NOT NULL,
                        quantita DECIMAL(10,2),
                        unita_misura VARCHAR(30),
                        note VARCHAR(255),
                        calorie_per_unita INTEGER,
                        ordine INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Tabella immagini (se serve in futuro)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ricette_immagini (
                        id SERIAL PRIMARY KEY,
                        ricetta_id INTEGER NOT NULL REFERENCES ricette(id) ON DELETE CASCADE,
                        url_immagine VARCHAR(500) NOT NULL,
                        descrizione VARCHAR(255),
                        is_principale BOOLEAN DEFAULT false,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Indice per ricerca veloce
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ricette_titolo ON ricette(titolo)")
                
            conn.commit()
            logger.info("[OK] Tabelle database pronte")
        except Exception as e:
            logger.error(f"Errore creazione tabelle: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def insert_recipes(self, recipes: List[Ricetta]) -> Tuple[int, int]:
        """
        Inserisce ricette in batch. Ritorna (inserite, duplicate).
        """
        conn = None
        inserted = 0
        duplicates = 0
        
        try:
            conn = psycopg2.connect(**self.config)
            
            with conn.cursor() as cur:
                for recipe in recipes:
                    try:
                        # Insert ricetta (con ON CONFLICT per gestire duplicati)
                        cur.execute("""
                            INSERT INTO ricette 
                            (titolo, categoria, istruzioni, tempo_preparazione, tempo_cottura, porzioni, difficolta, fonte_url)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (titolo) DO NOTHING
                            RETURNING id
                        """, (
                            recipe.titolo,
                            recipe.categoria,
                            recipe.istruzioni,
                            recipe.tempo_preparazione,
                            recipe.tempo_cottura,
                            recipe.porzioni,
                            recipe.difficolta,
                            recipe.fonte_url
                        ))
                        
                        result = cur.fetchone()
                        if result:
                            ricetta_id = result[0]
                            
                            # Insert ingredienti
                            for ing in recipe.ingredienti:
                                cur.execute("""
                                    INSERT INTO ricette_ingredienti
                                    (ricetta_id, nome, quantita, unita_misura, note, ordine)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                """, (
                                    ricetta_id,
                                    ing.nome,
                                    ing.quantita,
                                    ing.unita_misura,
                                    ing.note,
                                    ing.ordine
                                ))
                            
                            inserted += 1
                        else:
                            duplicates += 1
                    
                    except Exception as e:
                        logger.warning(f"Errore insert {recipe.titolo}: {e}")
                        conn.rollback()
            
            conn.commit()
        except Exception as e:
            logger.error(f"Errore transazione batch: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
        
        return inserted, duplicates

    def get_existing_titles(self) -> set:
        """Ritorna i titoli di ricette già presenti nel DB"""
        conn = None
        try:
            conn = psycopg2.connect(**self.config)
            with conn.cursor() as cur:
                cur.execute("SELECT titolo FROM ricette")
                return {row[0] for row in cur.fetchall()}
        finally:
            if conn:
                conn.close()

# ============================================================================
# CHECKPOINT MANAGER
# ============================================================================

class CheckpointManager:
    """Gestisce il checkpoint JSON per tracciare ricette già elaborate"""

    def __init__(self, checkpoint_file: str = CHECKPOINT_FILE):
        self.checkpoint_file = checkpoint_file
        self.processed_titles = self._load()

    def _load(self) -> List[str]:
        """Carica checkpoint da file"""
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                    titles = json.load(f)
                    logger.info(f"Checkpoint caricato: {len(titles)} ricette già elaborate")
                    return titles
            except Exception as e:
                logger.warning(f"Errore lettura checkpoint: {e}, inizio da zero")
                return []
        return []

    def mark_processed(self, title: str):
        """Segna una ricetta come processata"""
        if title not in self.processed_titles:
            self.processed_titles.append(title)

    def save(self):
        """Salva checkpoint su file"""
        try:
            temp_file = self.checkpoint_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.processed_titles, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.checkpoint_file)
            logger.info(f"Checkpoint salvato: {len(self.processed_titles)} ricette elaborate")
        except Exception as e:
            logger.error(f"Errore salvataggio checkpoint: {e}")

    def is_processed(self, title: str) -> bool:
        """Verifica se una ricetta è già stata processata"""
        return title in self.processed_titles

# ============================================================================
# MAIN PIPELINE
# ============================================================================

class RecipePipeline:
    """Orchestration della pipeline completa"""

    def __init__(self):
        self.ollama = OllamaClient()
        self.extractor = PDFRecipeExtractor(PDF_PATH)
        self.db = RecipeDatabase(DB_CONFIG)
        self.checkpoint = CheckpointManager(CHECKPOINT_FILE)

    def run(self, max_recipes: Optional[int] = None, max_pages: Optional[int] = None):
        """Esegue la pipeline completa"""
        logger.info("=" * 70)
        logger.info("INIZIO ESTRAZIONE RICETTE")
        logger.info("=" * 70)
        
        try:
            # Step 1: Estrai blocchi dal PDF
            blocks = self.extractor.extract_recipe_blocks(max_pages=max_pages)
            if max_recipes:
                blocks = blocks[:max_recipes]
            logger.info(f"Blocchi da processare: {len(blocks)}")
            
            # Step 2: Processa blocchi con Ollama
            recipes = self._parse_blocks(blocks)
            
            if not recipes:
                logger.warning("Nessuna ricetta estratta")
                return
            
            logger.info(f"Ricette parsate da Ollama: {len(recipes)}")
            
            # Step 3: Filtra duplicati usando checkpoint + DB
            recipes_to_save = self._filter_duplicates(recipes)
            logger.info(f"Ricette da salvare (after deduplication): {len(recipes_to_save)}")
            
            if not recipes_to_save:
                logger.info("Nessuna ricetta nuova da salvare")
                return
            
            # Step 4: Batch insert nel DB
            inserted, duplicates = self.db.insert_recipes(recipes_to_save)
            logger.info(f"Inserite: {inserted}, Duplicate nel DB: {duplicates}")
            
            # Step 5: Aggiorna checkpoint
            for recipe in recipes_to_save:
                self.checkpoint.mark_processed(recipe.titolo)
            self.checkpoint.save()
            
            logger.info("=" * 70)
            logger.info("ESTRAZIONE COMPLETATA")
            logger.info("=" * 70)
            
        except Exception as e:
            logger.error(f"Errore pipeline: {e}")
            logger.error(traceback.format_exc())
            raise

    def _parse_blocks(self, blocks: List[str]) -> List[Ricetta]:
        """Processa blocchi con Ollama e ritorna ricette strutturate"""
        recipes = []
        
        with tqdm(total=len(blocks), desc="Parsing blocchi ricetta", unit="block") as pbar:
            for block in blocks:
                try:
                    if not block or len(block) < 50:
                        pbar.update(1)
                        continue
                    
                    # Parse con Ollama
                    parsed = self.ollama.parse_recipe(block)
                    
                    if parsed:
                        recipe = self._dict_to_recipe(parsed)
                        if recipe:
                            recipes.append(recipe)
                    
                    pbar.update(1)
                except Exception as e:
                    logger.error(f"Errore processing block: {e}")
                    pbar.update(1)
        
        return recipes

    @staticmethod
    def _dict_to_recipe(data: Dict[str, Any]) -> Optional[Ricetta]:
        """Converte dict parsato da Ollama in oggetto Ricetta"""
        try:
            title = data.get('refined_title', '').strip()
            if not title or len(title) < 3:
                return None
            
            # Parsing ingredienti
            ingredienti = []
            for idx, ing_data in enumerate(data.get('ingredienti', [])):
                ing = Ingrediente(
                    nome=ing_data.get('nome', '').strip(),
                    quantita=ing_data.get('quantita'),
                    unita_misura=ing_data.get('unita_misura'),
                    note=ing_data.get('note'),
                    ordine=idx
                )
                if ing.nome:
                    ingredienti.append(ing)
            
            recipe = Ricetta(
                titolo=title,
                categoria=data.get('category', 'Altro'),
                istruzioni=data.get('istruzioni', ''),
                tempo_preparazione=int(data.get('tempo_preparazione', 0) or 0),
                tempo_cottura=int(data.get('tempo_cottura', 0) or 0),
                porzioni=int(data.get('porzioni', 4) or 4),
                difficolta=data.get('difficolta', 'Media'),
                ingredienti=ingredienti
            )
            
            return recipe
        except Exception as e:
            logger.error(f"Errore conversione dict→recipe: {e}")
            return None

    def _filter_duplicates(self, recipes: List[Ricetta]) -> List[Ricetta]:
        """Filtra ricette già presenti in checkpoint o DB"""
        existing_titles = self.db.get_existing_titles()
        
        filtered = []
        for recipe in recipes:
            if recipe.titolo not in existing_titles and not self.checkpoint.is_processed(recipe.titolo):
                filtered.append(recipe)
            else:
                logger.debug(f"Ricetta duplicata (già exists): {recipe.titolo}")
        
        return filtered

# ============================================================================
# CLI & MAIN
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Estrai ricette da PDF a PostgreSQL con Ollama')
    parser.add_argument('--max-recipes', type=int, default=None, help='Limita numero ricette da processare (debug)')
    parser.add_argument('--skip-test', action='store_true', help='Salta test connessione')
    
    args = parser.parse_args()
    
    try:
        pipeline = RecipePipeline()
        pipeline.run(max_recipes=args.max_recipes)
    except Exception as e:
        logger.error(f"Errore fatale: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
