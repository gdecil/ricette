#!/usr/bin/env python3
import os
import time
import sys

log_file = 'estrai_ottimizzato.log'

print("Monitoraggio estrazione in corso...")
print("=" * 70)

last_lines = []
while True:
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # Mostra ultime 3 linee uniche
        if lines and lines != last_lines:
            last_lines = lines
            print(f"\n[{time.strftime('%H:%M:%S')}] Log updated - Ultime 3 linee:")
            for line in lines[-3:]:
                print(f"  {line.rstrip()}")
        
        # Controlla se completato
        if any('COMPLETATO' in line for line in lines[-10:]):
            print("\n" + "=" * 70)
            print("ESTRAZIONE COMPLETATA!")
            print("=" * 70)
            # Mostra risultato finale
            for line in lines[-5:]:
                print(line.rstrip())
            break
    
    time.sleep(3)
