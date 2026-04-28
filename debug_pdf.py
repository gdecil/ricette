import pdfplumber
import re

print("🔍 Analisi PDF Ricette...")

pdf = pdfplumber.open('Ricette.pdf')
print(f"✅ Totale pagine nel PDF: {len(pdf.pages)}")

print("\n📄 Testo prime 3 pagine:")
for i in range(min(3, len(pdf.pages))):
    print(f"\n----- PAGINA {i+1} -----")
    text = pdf.pages[i].extract_text()
    if text:
        print(text[:800])
    else:
        print("❌ NESSUN TESTO ESTRABILE")

print("\n🔎 Ricerca pattern ricette nelle prime 20 pagine:")
pat = re.compile(r"titolo", re.IGNORECASE)
pat_full = re.compile(r"titolo ricetta:\s*(.*)", re.IGNORECASE)

for i in range(min(20, len(pdf.pages))):
    text = pdf.pages[i].extract_text()
    if not text:
        continue
    
    if pat.search(text):
        print(f"\n✅ Pagina {i+1} CONTIENE 'titolo'")
        if pat_full.search(text):
            print(f"  ✅ TROVATA RICETTA: {pat_full.search(text).group(1)}")
        else:
            print(f"  ⚠️  Ha 'titolo' ma non il pattern completo")
            # Mostra le righe che contengono titolo
            for riga in text.split('\n'):
                if 'titolo' in riga.lower():
                    print(f"     -> {riga.strip()}")

pdf.close()
print("\n✅ Analisi completata")