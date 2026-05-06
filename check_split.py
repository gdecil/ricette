import json

with open('ricette_split.json', 'r', encoding='utf-8') as f:
    recipes = json.load(f)

print(f"Totale ricette trovate: {len(recipes)}")
print("---")
for i, r in enumerate(recipes):
    print(f"{i+1:3d}. [{r['categoria']:10s}] Data: {r['data'][:40]:40s} -> {r['titolo'][:60]}")