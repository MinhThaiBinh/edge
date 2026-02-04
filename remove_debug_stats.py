import os

path = 'app/engine/logic.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

target = '        print(f">>> [DEBUG] Aggregated {len(records)} records for {m_code} in shift {shift_info[\'shiftcode\']}")\n'

if target in content:
    content = content.replace(target, '')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Removed debug print from get_current_shift_stats")
