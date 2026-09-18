import sys, re
from pypdf import PdfReader
path = sys.argv[1]
r = PdfReader(path)
texts = []
for p in r.pages:
    t = p.extract_text() or ''
    t = t.replace('\r', '\n')
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n\s*\n+', '\n\n', t)
    texts.append(t)
print('\n\n===PAGE_BREAK===\n\n'.join(texts))
