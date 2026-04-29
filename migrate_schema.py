#!/usr/bin/env python3
"""
Migrazione schema: Aggiunge colonna fonte_url se manca
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'postgres'),
    'database': os.getenv('DB_NAME', 'ricette_db'),
    'port': int(os.getenv('DB_PORT', 5432))
}

print("Controllo schema database...")

conn = psycopg2.connect(**DB_CONFIG)
try:
    with conn.cursor() as cur:
        # Controlla se colonna fonte_url esiste
        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name='ricette' AND column_name='fonte_url'
        """)
        
        if cur.fetchone():
            print("✓ Colonna fonte_url esiste già")
        else:
            print("✗ Colonna fonte_url non trovata - aggiungo...")
            cur.execute("""
                ALTER TABLE ricette ADD COLUMN fonte_url VARCHAR(500)
            """)
            conn.commit()
            print("✓ Colonna fonte_url aggiunta")
    
    # Elenca le colonne della tabella ricette
    print("\nColonne attuali della tabella 'ricette':")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type FROM information_schema.columns 
            WHERE table_name='ricette' ORDER BY ordinal_position
        """)
        for col_name, data_type in cur.fetchall():
            print(f"  - {col_name}: {data_type}")

finally:
    conn.close()

print("\n✓ Verifica schema completata")
