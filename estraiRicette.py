import sys
import os
# Fix encoding per Windows CMD
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import pdfplumber
import psycopg2
from psycopg2 import sql
import re
import json
import logging
import time
from functools import wraps
import google.genai as genai
from tqdm import tqdm
from typing import Dict, Any, List, Optional

# --- Configurazione del Logger ---
logging.basicConfig(
    filename='processamento_ricette.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'
)

# --- Implementazione Rate Limiter ---
class RateLimiter:
    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self.interval = 60.0 / requests_per_minute
        self.last_request = 0

    def wait(self):
        elapsed = time.time() - self.last_request
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_request = time.time()

def rate_limited(limiter: RateLimiter):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter.wait()
            return func(*args, **kwargs)
        return wrapper
    return decorator


class RecipePipeline:
    CHECKPOINT_FILE = "checkpoint.json"

    def __init__(self, db_config: Dict[str, str], model, limiter: RateLimiter):
        self.db_config = db_config
        self.model = model
        self.limiter = limiter
        # PATTERN CORRETTO PER IL TUO PDF
        self.header_pattern = re.compile(r"^(.+?):?\s*(?:\||$)", re.MULTILINE)
        self.date_pattern = re.compile(r"data di inserimento:\s*(.*)", re.IGNORECASE)
        self.time_pattern = re.compile(r"(\d+):(\d+)")
        self.processed_titles: List[str] = self._load_checkpoint()
        
        # Decoriamo il metodo LLM con rate limiting
        self.get_llm_categorization = rate_limited(limiter)(self._get_llm_categorization)

    def _load_checkpoint(self) -> List[str]:
        if os.path.exists(self.CHECKPOINT_FILE):
            try:
                with open(self.CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                    titles = json.load(f)
                    logging.info(f"Caricato checkpoint: {len(titles)} ricette già processate.")
                    return titles
            except json.JSONDecodeError as e:
                logging.warning(f"File di checkpoint corrotto: {e}. Inizio da zero.")
                return []
        return []

    def _save_checkpoint(self, title: str):
        if title not in self.processed_titles:
            self.processed_titles.append(title)
        
        temp_file = self.CHECKPOINT_FILE + ".tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.processed_titles, f, indent=2)
            os.replace(temp_file, self.CHECKPOINT_FILE)
        except Exception as e:
            logging.error(f"Errore salvataggio checkpoint: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def init_database(self):
        conn = None
        try:
            conn = psycopg2.connect(
                host=self.db_config['host'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                dbname='postgres'
            )
            conn.autocommit = True
            
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (self.db_config['database'],))
                if not cur.fetchone():
                    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.db_config['database'])))
                    print(f"OK Database {self.db_config['database']} creato")
            
            conn.close()
            
            conn = psycopg2.connect(**self.db_config)
            
            with conn.cursor() as cur:
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
                
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ricette_titolo ON ricette(titolo)")
                
            conn.commit()
            print("OK Tabelle database pronte")
            
        except Exception as e:
            logging.error(f"Errore inizializzazione database: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def _get_llm_categorization(self, text: str) -> Dict[str, Any]:
        prompt = f"""
        Analizza questa ricetta e restituisci UN SOLO OGGETTO JSON VALIDO:
        
        Testo ricetta:
        {text[:4000]}
        
        Formato JSON:
        {{
          "refined_title": "Titolo pulito",
          "category": "Antipasti/Primi/Secondi/Contorni/Dolci/Bevande/Altro",
          "tempo_preparazione": numero_minuti,
          "tempo_cottura": numero_minuti,
          "porzioni": numero_intero,
          "difficolta": "Facile/Media/Difficile",
          "fonte_url": "url oppure null",
          "ingredienti": [
            {{ "nome": "nome", "quantita": numero, "unita_misura": "g/ml", "note": "note", "ordine": 1 }}
          ],
          "immagini": []
        }}
        """
        
        try:
            response = self.model.generate_content(prompt)
            cleaned = response.text.strip()
            if cleaned.startswith('```json'): cleaned = cleaned[7:]
            if cleaned.endswith('```'): cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
        except Exception as e:
            logging.warning(f"Fallita estrazione LLM: {e}")
            return {
                "refined_title": text.split('\n')[0].strip(),
                "category": "Altro",
                "tempo_preparazione": 0,
                "tempo_cottura": 0,
                "porzioni": 4,
                "difficolta": "Media",
                "fonte_url": None,
                "ingredienti": [],
                "immagini": []
            }

    def save_to_db(self, recipe_data: Dict[str, Any], ingredients: List = None, images: List = None):
        conn = None
        try:
            conn = psycopg2.connect(**self.db_config)
            
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ricette 
                    (titolo, categoria, istruzioni, tempo_preparazione, tempo_cottura, porzioni, difficolta, fonte_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (titolo) DO NOTHING
                    RETURNING id
                """, (
                    recipe_data['title'],
                    recipe_data['category'],
                    recipe_data['instructions'],
                    recipe_data.get('tempo_preparazione', 0),
                    recipe_data.get('tempo_cottura', 0),
                    recipe_data.get('porzioni', 4),
                    recipe_data.get('difficolta', 'Media'),
                    recipe_data.get('fonte_url')
                ))
                
                result = cur.fetchone()
                if not result:
                    return
                
                ricetta_id = result[0]
                logging.info(f"Ricetta '{recipe_data['title']}' salvata ID {ricetta_id}")

                if ingredients:
                    for ing in ingredients:
                        cur.execute("""
                            INSERT INTO ricette_ingredienti
                            (ricetta_id, nome, quantita, unita_misura, note, ordine)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            ricetta_id,
                            ing.get('nome', ''),
                            ing.get('quantita'),
                            ing.get('unita_misura'),
                            ing.get('note'),
                            ing.get('ordine', 0)
                        ))
                    
            conn.commit()
            
        except Exception as e:
            logging.error(f"Errore salvataggio ricetta: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def process_recipe_block(self, block_text: str, pbar: tqdm = None):
        title_match = self.header_pattern.search(block_text)
        raw_title = title_match.group(1).strip() if title_match else "Senza Titolo"
        
        if raw_title in self.processed_titles:
            return

        try:
            llm_data = self.get_llm_categorization(block_text)
            
            self.save_to_db({
                "title": llm_data.get("refined_title", raw_title),
                "category": llm_data.get("category", "Altro"),
                "instructions": block_text,
                "tempo_preparazione": llm_data.get("tempo_preparazione", 0),
                "tempo_cottura": llm_data.get("tempo_cottura", 0),
                "porzioni": llm_data.get("porzioni", 4),
                "difficolta": llm_data.get("difficolta", "Media"),
                "fonte_url": llm_data.get("fonte_url")
            },
            ingredients=llm_data.get("ingredienti", [])
            )
            
            self._save_checkpoint(raw_title)
            print(f"✅ Inserita: {raw_title[:40]}")

        except Exception as e:
            logging.error(f"ERRORE: Impossibile processare '{raw_title}': {e}")

    def run(self, pdf_path: str, max_pages: int = 30):
        logging.info(f"Lettura prime {max_pages} pagine PDF")
        current_block = ""
        
        with pdfplumber.open(pdf_path) as pdf:
            pagine_da_leggere = min(len(pdf.pages), max_pages)
            
            with tqdm(total=pagine_da_leggere, desc="Caricamento PDF", unit="pag") as pbar:
                for page_num in range(pagine_da_leggere):
                    page = pdf.pages[page_num]
                    text = page.extract_text()
                    if not text:
                        pbar.update(1)
                        continue

                    if self.header_pattern.search(text):
                        if current_block:
                            self.process_recipe_block(current_block, pbar)
                        current_block = text
                    else:
                        current_block += "\n" + text
                    
                    pbar.update(1)

                if current_block:
                    self.process_recipe_block(current_block, pbar)

        print(f"\nOK Elaborazione prime {pagine_da_leggere} pagine completata!")


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    DB_PARAMS = {
        "host": os.getenv("DB_HOST", "localhost"),
        "database": os.getenv("DB_NAME", "cucina"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "pwd")
    }
    
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "INSERISCI_LA_TUA_CHIAVE_QUI")
    
    model = None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.0-flash')
        limiter = RateLimiter(requests_per_minute=15)
    except Exception as e:
        limiter = RateLimiter(1)
    
    pipeline = RecipePipeline(DB_PARAMS, model, limiter)
    
    print("=== Pipeline Estrazione Ricette ===")
    print("1. Inizializza Database")
    print("2. Elabora PRIME 30 PAGINE del PDF")
    print("3. Esegui tutto")
    
    scelta = input("\nScegli operazione (default 3): ").strip() or "3"
    
    if scelta == "1" or scelta == "3":
        pipeline.init_database()
    
    if scelta == "2" or scelta == "3":
        pipeline.run("Ricette.pdf", max_pages=30)
    
    print("\n✅ Operazioni completate!")