with open(r"C:\Users\kevse\OneDrive\Desktop\girisim\ReviseMeSon\app.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "completion_rate =" in line or "performance_grade" in line:
        print(f"Line {i+1}: {line.strip()}")
