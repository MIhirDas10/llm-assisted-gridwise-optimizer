import json
d = json.load(open('BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json', encoding='utf-8'))
print('Cases:', len(d['cases']))
for c in d['cases']:
    print(c['id'], '|', c['label'])
    print('  notes:', c['input']['operator_notes'])
    print('  directives:')
    for e in c['expected_output']['directive_interpretation']:
        print('   ', e['note_index'], e['directive_type'], e.get('structured_adjustment'))
    print('  totals:', {k: c['expected_output'][k] for k in ['total_grid_kwh', 'total_cost_bdt', 'peak_grid_kwh']})
    print()
