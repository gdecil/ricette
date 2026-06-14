import pdfplumber
import re

pdf = pdfplumber.open('Ricette.pdf')

# Check first 15 pages for date patterns
print("=== CERCANDO DATE NELLE PRIME PAGINE ===")
found = 0
for i in range(min(50, len(pdf.pages))):
    text = pdf.pages[i].extract_text()
    if not text:
        continue
    
    # Look for lines with date keywords
    for line in text.split('\n'):
        if re.search(r'(?:lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)', line, re.IGNORECASE):
            found += 1
            print(f"PAGE {i}: [{line.strip()[:120]}]")
            if found >= 20:
                break
    if found >= 20:
        break

if found == 0:
    print("NESSUNA DATA TROVATA! Controllo contenuto pagine...")
    for i in range(5):
        text = pdf.pages[i].extract_text()
        if text:
            print(f"\nPAGE {i} FIRST 300 CHARS:")
            print(text[:300])
        else:
            print(f"\nPAGE {i}: NO TEXT")
pdf.close()