import os
import re

directory = r"c:\Users\kevse\OneDrive\Desktop\girisim\ReviseMeSon\templates"

def process_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='latin-1') as f:
            content = f.read()

    original_content = content

    # 1. Increase global font size
    # If there's a head tag, and we haven't added our style yet
    if '<head>' in content and 'html { font-size: 18px;' not in content:
        content = content.replace('</head>', '    <style> html { font-size: 18px !important; } </style>\n</head>')

    # 2. Fix layout to fill the screen
    # Replace common max-width bounds on main wrappers
    content = re.sub(r'max-w-\[1400px\]', 'max-w-full px-4 md:px-8', content)
    content = re.sub(r'max-w-\[1200px\]', 'max-w-full px-4 md:px-8', content)
    
    # Specific replacements for login and register to fill screen
    if 'login.html' in filepath or 'register.html' in filepath:
        content = re.sub(r'max-w-6xl', 'max-w-full px-4 md:px-8', content)
        content = re.sub(r'max-w-7xl', 'max-w-full px-4 md:px-8', content)
        content = re.sub(r'rounded-3xl', 'rounded-none', content)
        content = re.sub(r'p-4', 'p-0', content) # body padding
        content = re.sub(r'lg:h-\[95vh\]', 'min-h-screen', content)
        content = re.sub(r'min-h-\[700px\]', 'min-h-screen', content)
        content = re.sub(r'h-\[95vh\]', 'min-h-screen', content)

    # For profile, chat, add_question, settings etc
    if 'profile.html' in filepath or 'chat.html' in filepath or 'settings.html' in filepath or 'add_question.html' in filepath:
        content = re.sub(r'max-w-4xl', 'max-w-full px-4 md:px-8', content)
        content = re.sub(r'max-w-5xl', 'max-w-full px-4 md:px-8', content)

    # For welcome and category_questions
    if 'welcome.html' in filepath or 'category_questions.html' in filepath:
        content = re.sub(r'max-w-7xl', 'max-w-full px-4 md:px-8', content)

    if content != original_content:
        # Write back with original encoding? Or utf-8. Let's use same as read
        encoding_to_write = 'utf-8' if 'utf-8' in locals() else 'latin-1'
        try:
             with open(filepath, 'w', encoding='utf-8') as f:
                 f.write(content)
        except:
             with open(filepath, 'w', encoding='latin-1') as f:
                 f.write(content)
        print(f"Updated {filepath}")

for root, dirs, files in os.walk(directory):
    for file in files:
        if file.endswith(".html"):
            process_file(os.path.join(root, file))

# Also update base.html explicitly for body font-size
base_path = os.path.join(directory, "base.html")
if os.path.exists(base_path):
    with open(base_path, 'r', encoding='utf-8') as f:
        base_content = f.read()
    
    # Check if font-size: 16px is there, change to 18px
    if 'font-size: 16px;' in base_content:
        base_content = base_content.replace('font-size: 16px;', 'font-size: 18px;')
        with open(base_path, 'w', encoding='utf-8') as f:
            f.write(base_content)
        print(f"Updated body font-size in {base_path}")

print("Done!")
