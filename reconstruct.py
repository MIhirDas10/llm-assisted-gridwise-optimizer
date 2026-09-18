"""Reconstruct PDF text by clustering words into lines based on 'top' (y) coords."""
import sys, re
import pdfplumber

def reconstruct(path, out_path):
    pages_text = []
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            words = p.extract_words(use_text_flow=True, keep_blank_chars=False)
            if not words:
                pages_text.append('')
                continue
            # Group words into lines by 'top' (rounded)
            lines_dict = {}
            for w in words:
                key = round(w['top'], 1)
                lines_dict.setdefault(key, []).append(w)
            # Sort lines top->bottom, words left->right
            sorted_tops = sorted(lines_dict.keys())
            page_lines = []
            for top in sorted_tops:
                row = sorted(lines_dict[top], key=lambda x: x['x0'])
                line_text = ' '.join(w['text'] for w in row)
                page_lines.append(line_text)
            pages_text.append('\n'.join(page_lines))
    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write('\n\n===PAGE_BREAK===\n\n'.join(pages_text))
    print('Wrote', out_path, 'pages=', len(pages_text), file=sys.stderr)

pairs = [
    ('BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.pdf', 'problem2.txt'),
    ('BUP_CSE_FEST_2026_Participant_Guide_&_Evaluation_Rubric_GridWise_LLM.pdf', 'rubric2.txt'),
]
for f, o in pairs:
    reconstruct(f, o)
