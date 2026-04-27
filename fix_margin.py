import re

files = [
    r"c:\Users\kevse\OneDrive\Desktop\girisim\ReviseMeSon\templates\settings.html",
    r"c:\Users\kevse\OneDrive\Desktop\girisim\ReviseMeSon\templates\chat.html"
]

for filepath in files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # for settings and chat html which use flex content setup
    # add ml-64 to main div
    content = content.replace('<div class="flex-1 flex flex-col h-screen', '<div class="flex-1 flex flex-col h-screen md:ml-64')
    content = content.replace('<main class="flex-1 flex flex-col', '<main class="flex-1 flex flex-col md:ml-64')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
