#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script di analisi del PDF per capire la struttura delle ricette
"""

import pdfplumber
import re
from collections import Counter

PDF_PATH = 'ricette.pdf'

print("=" * 70)
print("ANALISI STRUTTURA PDF")
print("=" * 70)

with pdfplumber.open(PDF_PATH) as pdf:
    print(f"\nTotale pagine: {len(pdf.pages)}")
    
    # Analizza prime 5 pagine
    print("\n--- PRIME 5 PAGINE ---")
    for page_num in range(min(5, len(pdf.pages))):
        page = pdf.pages[page_num]
        text = page.extract_text()
        if text:
            print(f"\nPagina {page_num + 1}:")
            print(f"  Lunghezza: {len(text)} caratteri")
            lines = text.split('\n')
            print(f"  Righe: {len(lines)}")
            print(f"  Prime 5 righe:")
            for i, line in enumerate(lines[:5]):
                print(f"    {i+1}: {line[:80]}")
    
    # Cerca pattern comuni
    print("\n--- RICERCA PATTERN ---")
    patterns = {
        'titolo ricetta': r'titolo ricetta',
        'ingredienti': r'ingredienti',
        'preparazione': r'preparazione|istruzioni',
        'tempo': r'tempo|minuti|ore',
        'porzioni': r'porzioni|persone',
        'MAIUSCOLE SINGOLE': r'^[A-Z][A-Z\s]+$',
    }
    
    found_patterns = {name: 0 for name in patterns}
    sample_matches = {name: [] for name in patterns}
    
    for page_num in range(min(50, len(pdf.pages))):
        page = pdf.pages[page_num]
        text = page.extract_text()
        if not text:
            continue
        
        for name, pattern in patterns.items():
            if name == 'MAIUSCOLE SINGOLE':
                for line in text.split('\n'):
                    if re.match(pattern, line.strip()):
                        found_patterns[name] += 1
                        if len(sample_matches[name]) < 3:
                            sample_matches[name].append(line.strip()[:60])
            else:
                matches = re.findall(pattern, text, re.IGNORECASE)
                found_patterns[name] += len(matches)
                if len(sample_matches[name]) < 3 and matches:
                    sample_matches[name].extend(matches[:2])
    
    print("\nPattern trovati (prime 50 pagine):")
    for name, count in found_patterns.items():
        print(f"  {name}: {count} occorrenze")
        if sample_matches[name]:
            print(f"    Esempi: {sample_matches[name][:2]}")
    
    # Analizza separatori possibili
    print("\n--- SEPARATORI POSSIBILI ---")
    
    # Controlla righe vuote
    empty_line_count = 0
    double_newline_count = 0
    for page_num in range(min(50, len(pdf.pages))):
        page = pdf.pages[page_num]
        text = page.extract_text()
        if text:
            lines = text.split('\n')
            empty_line_count += len([l for l in lines if l.strip() == ''])
            double_newline_count += text.count('\n\n')
    
    print(f"  Righe vuote (prime 50 pagine): {empty_line_count}")
    print(f"  Doppi newline: {double_newline_count}")
    
    # Estima ricette
    print("\n--- STIMA RICETTE ---")
    
    # Prova a contare possibili ricette
    chunk_count = 0
    for page_num in range(len(pdf.pages)):
        page = pdf.pages[page_num]
        text = page.extract_text()
        if text and len(text.strip()) > 100:
            # Conta blocchi potenziali
            if page_num == 0:
                chunk_count += 1
            elif page_num < 20:
                chunk_count += 1
    
    # Analizza campionamento: pagine con molto testo vs poco
    dense_pages = 0
    sparse_pages = 0
    avg_text_len = 0
    
    for page_num in range(len(pdf.pages)):
        page = pdf.pages[page_num]
        text = page.extract_text()
        if text:
            avg_text_len += len(text)
            if len(text) > 2000:
                dense_pages += 1
            elif len(text) < 500:
                sparse_pages += 1
    
    avg_text_len = avg_text_len / len(pdf.pages) if pdf.pages else 0
    
    print(f"  Pagine dense (>2000 car): {dense_pages}")
    print(f"  Pagine sparse (<500 car): {sparse_pages}")
    print(f"  Media caratteri per pagina: {avg_text_len:.0f}")
    
    # Stima conservativa
    estimated_recipes = max(dense_pages, len(pdf.pages) // 10)
    print(f"\n  STIMA RICETTE (conservativa): ~{estimated_recipes} ricette")

print("\n" + "=" * 70)
print("ANALISI COMPLETATA")
print("=" * 70)
