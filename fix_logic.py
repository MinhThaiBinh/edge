import os

path = 'app/engine/logic.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the first occurrence of get_current_shift_stats
start_token = 'async def get_current_shift_stats(machinecode: str):'
first_idx = content.find(start_token)
second_idx = content.find(start_token, first_idx + len(start_token))

if second_idx != -1:
    # Remove the second occurrence and the text between them
    # Actually, simpler to just replace the whole duplicated block
    # Finding the end of the first block
    end_token = 'return None'
    first_end = content.find(end_token, first_idx) + len(end_token)
    
    # Check if there is another one
    new_content = content[:first_end] + content[content.find('async def ensure_active_production_records():', second_idx):]
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Cleaned up duplicated function in logic.py")
