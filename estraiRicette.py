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
        self.header_pattern = re.compile(r"titolo ricetta:\s*(.*)", re.IGNORECASE)
        self.date_pattern = re.compile(r"data di inserimento:\s*(.*)", re.IGNORECASE)
        self.time_pattern = re.compile(r"(\d+):(\d+)")
        self.processed_titles: List[str] = self._load_checkpoint()
        
        # Decoriamo il metodo LLM con rate limiting
        self.get_llm_categorization = rate_limited(limiter)(self._get_llm_categorization)

    def _load_checkpoint(self) -> List[str]:
        """Carica i titoli delle ricette già processate dal file di checkpoint."""
        if os.path.exists(self.CHECKPOINT_FILE):
            try:
                with open(self.CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                    titles = json.load(f)
                    logging.info(f"Caricato checkpoint: {len(titles)} ricette già processate.")
                    return titles
            except json.JSONDecodeError as e:
                logging.warning(f"File di checkpoint corrotto o non valido: {e}. Inizio da zero.")
                return []
        return []

    def _save_checkpoint(self, title: str):
        """Salva il titolo di una ricetta processata e aggiorna il file di checkpoint."""
        if title not in self.processed_titles:
            self.processed_titles.append(title)
        
        temp_file = self.CHECKPOINT_FILE + ".tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.processed_titles, f, indent=2)
            os.replace(temp_file, self.CHECKPOINT_FILE)
            logging.debug(f"Checkpoint aggiornato con '{title}'.")
        except Exception as e:
            logging.error(f"Errore durante il salvataggio del checkpoint per '{title}': {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def init_database(self):
        """Crea il database e le tabelle se non esistono"""
        conn = None
        try:
            # Connetti al database postgres default per creare il database
            conn = psycopg2.connect(
                host=self.db_config['host'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                dbname='postgres'
            )
            conn.autocommit = True
            
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (self.db_config['database'],))
                exists = cur.fetchone()
                
                if not exists:
                    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.db_config['database'])))
                    logging.info(f"Database {self.db_config['database']} creato con successo")
                    print(f"OK Database {self.db_config['database']} creato")
            
            conn.close()
            
            # Ora connettiti al nostro database e crea le tabelle
            conn = psycopg2.connect(**self.db_config)
            
            with conn.cursor() as cur:
                # Tabella ricette principale
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

                # Tabella immagini ricette
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
                
                # Indici
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ricette_titolo ON ricette(titolo)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ricette_categoria ON ricette(categoria)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ingredienti_ricetta ON ricette_ingredienti(ricetta_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_immagini_ricetta ON ricette_immagini(ricetta_id)")
                
            conn.commit()
            logging.info("Tabelle database inizializzate correttamente")
            print("OK Tabelle database pronte")
            
        except Exception as e:
            logging.error(f"Errore inizializzazione database: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def parse_duration(self, text: str) -> int:
        """Estrae il tempo di preparazione in minuti dal testo"""
        total = 0
        
        # Cerca pattern come hh:mm
        match = self.time_pattern.search(text)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            total = hours * 60 + minutes
        
        # Cerca anche parole come "30 minuti"
        minutes_match = re.search(r"(\d+)\s*minuti?", text, re.IGNORECASE)
        if minutes_match:
            total += int(minutes_match.group(1))
            
        hours_match = re.search(r"(\d+)\s*ore?", text, re.IGNORECASE)
        if hours_match:
            total += int(hours_match.group(1)) * 60
            
        return total

    def _get_llm_categorization(self, text: str) -> Dict[str, Any]:
        """Chiama Gemini per estrarre TUTTI i dati strutturati dalla ricetta"""
        prompt = f"""
        Analizza questa ricetta e restituisci UN SOLO OGGETTO JSON VALIDO senza altri caratteri:
        
        Testo ricetta:
        {text[:4000]}
        
        Restituisci esattamente questo formato JSON:
        {{
          "refined_title": "Titolo pulito e formattato correttamente",
          "category": "Una delle seguenti: Antipasti, Primi, Secondi, Contorni, Dolci, Bevande, Altro",
          "tempo_preparazione": numero_minuti,
          "tempo_cottura": numero_minuti,
          "porzioni": numero_intero,
          "difficolta": "Facile, Media, Difficile",
          "fonte_url": "url se presente oppure null",
          "ingredienti": [
            {{
              "nome": "nome ingrediente",
              "quantita": numero_decimale,
              "unita_misura": "g, kg, ml, l, cucchiaio, ecc oppure null",
              "note": "eventuali note oppure null",
              "ordine": numero_intero partendo da 1
            }}
          ],
          "immagini": [
            {{
              "url_immagine": "url immagine se presente",
              "descrizione": "descrizione immagine",
              "is_principale": true/false
            }}
          ]
        }}
        
        NESSUN ALTRO TESTO, SOLO IL JSON PURO E VALIDO.
        """
        
        try:
            response = self.model.generate_content(prompt)
            # Pulisci risposta da eventuali markdown
            cleaned = response.text.strip()
            if cleaned.startswith('```json'):
                cleaned = cleaned[7:]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
                
            return json.loads(cleaned.strip())
            
        except Exception as e:
            logging.warning(f"Fallita estrazione dati LLM: {e}")
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
        """Salva una ricetta completa nel database con ingredienti e immagini"""
        conn = None
        try:
            conn = psycopg2.connect(**self.db_config)
            
            with conn.cursor() as cur:
                # Inserisci ricetta principale
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
                    logging.info(f"Ricetta '{recipe_data['title']}' già presente nel database")
                    return
                
                ricetta_id = result[0]
                logging.info(f"Ricetta '{recipe_data['title']}' salvata con ID {ricetta_id}")

                # Inserisci ingredienti
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

                # Inserisci immagini
                if images:
                    for img in images:
                        cur.execute("""
                            INSERT INTO ricette_immagini
                            (ricetta_id, url_immagine, descrizione, is_principale)
                            VALUES (%s, %s, %s, %s)
                        """, (
                            ricetta_id,
                            img.get('url_immagine', ''),
                            img.get('descrizione'),
                            img.get('is_principale', False)
                        ))
                    
            conn.commit()
            
        except Exception as e:
            logging.error(f"Errore salvataggio ricetta '{recipe_data['title']}': {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def process_recipe_block(self, block_text: str, pbar: tqdm = None):
        title_match = self.header_pattern.search(block_text)
        raw_title = title_match.group(1).strip() if title_match else "Senza Titolo"
        
        # Checkpoint
        if raw_title in self.processed_titles:
            logging.info(f"SKIP: Ricetta '{raw_title}' già presente nel checkpoint. Saltata.")
            if pbar:
                pbar.set_description(f"Saltata: {raw_title[:25]}")
            return

        if pbar:
            pbar.set_description(f"Elaborazione: {raw_title[:25]}")

        try:
            # Chiamata LLM per estrarre TUTTI i dati
            llm_data = self.get_llm_categorization(block_text)
            
            # Salvataggio DB completo
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
            ingredients=llm_data.get("ingredienti", []),
            images=llm_data.get("immagini", [])
            )
            
            # Aggiorna checkpoint
            self._save_checkpoint(raw_title)

        except Exception as e:
            logging.error(f"ERRORE: Impossibile processare completamente la ricetta '{raw_title}'. Dettaglio: {e}")

    def insert_first_5_recipes(self):
        """Estrae e inserisce le PRIME 5 ricette reali dal file PDF come prova"""
        print("\nEstrazione prime 5 ricette reali dal PDF...")
        
        current_block = ""
        ricette_trovate = 0
        limite_ricette = 5
        
        with pdfplumber.open("Ricette.pdf") as pdf:
            with tqdm(total=len(pdf.pages), desc="Lettura PDF", unit="pag") as pbar:
                for page_num, page in enumerate(pdf.pages):
                    if ricette_trovate >= limite_ricette:
                        break
                        
                    text = page.extract_text()
                    if not text:
                        pbar.update(1)
                        continue

                    if self.header_pattern.search(text):
                        if current_block and ricette_trovate < limite_ricette:
                            self.process_recipe_block(current_block)
                            ricette_trovate += 1
                            print(f"OK Ricetta {ricette_trovate}/{limite_ricette} processata")
                        current_block = text
                    else:
                        current_block += "\n" + text
                    
                    pbar.update(1)

                # Processa l'ultima se non abbiamo raggiunto il limite
                if current_block and ricette_trovate < limite_ricette:
                    self.process_recipe_block(current_block)
                    ricette_trovate += 1
                    print(f"OK Ricetta {ricette_trovate}/{limite_ricette} processata")

        print(f"\nOK Inserite {ricette_trovate} ricette reali dal PDF")
        logging.info(f"Inserite {ricette_trovate} ricette reali di prova dal PDF")

    def run(self, pdf_path: str):
        logging.info(f"--- Inizio sessione di elaborazione PDF: {pdf_path} ---")
        current_block = ""
        
        if not os.path.exists(pdf_path):
            error_msg = f"File PDF {pdf_path} non trovato!"
            logging.critical(error_msg)
            print(f"\nERRORE {error_msg}")
            return
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                with tqdm(total=len(pdf.pages), desc="Caricamento PDF", unit="pag") as pbar:
                    for page_num, page in enumerate(pdf.pages):
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
            
            logging.info("--- Fine sessione: Elaborazione completata con successo ---")
            print("\nOK Elaborazione completata con successo! Controlla il log per i dettagli.")
        except Exception as e:
            logging.critical(f"ERRORE DI SISTEMA: Il processo si è interrotto bruscamente. Errore: {e}")
            print(f"\nERRORE Si e' verificato un errore critico. Controlla il file di log per i dettagli.")


if __name__ == "__main__":
    # Carica variabili ambiente da file .env se presente
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Configurazione
    DB_PARAMS = {
        "host": os.getenv("DB_HOST", "localhost"),
        "database": os.getenv("DB_NAME", "cucina"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "pwd")
    }
    
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "INSERISCI_LA_TUA_CHIAVE_QUI")
    
    if GEMINI_API_KEY == "INSERISCI_LA_TUA_CHIAVE_QUI":
        print("\nAVVISO: Imposta la variabile ambiente GEMINI_API_KEY oppure modifica la chiave direttamente nello script")
        print("Senza la chiave API Gemini verra' usata solo l'estrazione base\n")
    
    # Inizializza Gemini
    model = None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.0-flash')
        limiter = RateLimiter(requests_per_minute=15)
    except Exception as e:
        print(f"Avviso: Gemini non inizializzato: {e}")
        limiter = RateLimiter(1)
    
    # Crea pipeline
    pipeline = RecipePipeline(DB_PARAMS, model, limiter)
    
    # Menu operazioni
    print("=== Pipeline Estrazione Ricette ===")
    print("1. Inizializza Database")
    print("2. Inserisci prime 5 ricette reali dal PDF")
    print("3. Elabora TUTTO il PDF ricette.pdf")
    print("4. Esegui tutto")
    
    scelta = input("\nScegli operazione (default 4): ").strip() or "4"
    
    if scelta == "1" or scelta == "4":
        pipeline.init_database()
    
    if scelta == "2" or scelta == "4":
        pipeline.insert_first_5_recipes()
    
    if scelta == "3":
        pipeline.run("Ricette.pdf")
    
    print("\nOK Operazioni completate!")
