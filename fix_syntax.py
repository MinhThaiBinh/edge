import os

path = 'app/engine/logic.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the specific syntax error where return None and async def were merged
old_line = "return Noneasync def ensure_active_production_records():"
new_line = "return None\n\nasync def ensure_active_production_records():"

if old_line in content:
    content = content.replace(old_line, new_line)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed syntax error in logic.py")
else:
    # Try another pattern if it's slightly different
    print("Could not find the exact broken line, checking for alternative patterns...")
    if "return Noneasync" in content:
        content = content.replace("return Noneasync", "return None\n\nasync")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("Fixed syntax error with alternative pattern")
    else:
        print("Error pattern not found.")
