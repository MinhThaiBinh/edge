import os

path = 'app/engine/logic.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '        summary = {'
new_code = '        print(f">>> [DEBUG] Aggregated {len(records)} records for {m_code} in shift {shift_info[\'shiftcode\']}")\n        summary = {'

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Added debug print to get_current_shift_stats")
