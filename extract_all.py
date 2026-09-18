import sys, re
import pdfplumber

def extract(path):
    pages = []
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            t = p.extract_text() or ''
            pages.append(t)
    return '\n\n===PAGE_BREAK===\n\n'.join(pages)

pairs = [
    ('BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.pdf', 'problem2.txt'),
    ('BUP_CSE_FEST_2026_Participant_Guide_&_Evaluation_Rubric_GridWise_LLM.pdf', 'rubric2.txt'),
]
for f, o in pairs:
    print('Processing', f, file=sys.stderr)
    t = extract(f)
    with open(o, 'w', encoding='utf-8') as fh:
        fh.write(t)
    print('  wrote', o, 'lines=', len(t.splitlines()), 'chars=', len(t), file=sys.stderr)
