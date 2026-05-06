import re

# Read the PDF file as text
with open("Ricette.pdf", "rb") as f:
    raw = f.read()

# Decode as text - PDFs have readable text interspersed with binary
text = raw.decode("latin-1")

urls = set()

# Pattern: URLs that follow specific keywords
# "From <url>", "Pasted from <url>", "Clipped from: <url>", 
# "Ritagliata da: <url>", "Read more at <url>"
pattern_kw = re.findall(
    r'(?:from\s*[<:]\s*|pasted\s+from\s*[<:]\s*|clipped\s+from\s*:?\s*|ritagliata\s+da\s*:?\s*|read\s+more\s+at\s+)'
    r'(https?://[^\s<>"\']+)', 
    text, 
    re.IGNORECASE
)

for url in pattern_kw:
    url = url.rstrip('.,;:!?)">')
    url = url.rstrip('>')
    # Remove fragment identifiers with # that are not part of the actual URL path
    if url.startswith('http'):
        urls.add(url)

# Pattern: URLs that contain "ricette" or "ricetta" in the URL (case insensitive)
pattern_ricette = re.findall(
    r'https?://[^\s<>"\']*ricett[ae][^\s<>"\']*',
    text,
    re.IGNORECASE
)

for url in pattern_ricette:
    url = url.rstrip('.,;:!?)">')
    url = url.rstrip('>')
    if url.startswith('http'):
        urls.add(url)

# Sort URLs for consistent output
sorted_urls = sorted(urls)

# Write to file
with open("listaUrl.txt", "w", encoding="utf-8") as f:
    for url in sorted_urls:
        f.write(url + "\n")

print(f"Trovati {len(sorted_urls)} URL unici che corrispondono ai criteri")
print("---")
for u in sorted_urls:
    print(u)