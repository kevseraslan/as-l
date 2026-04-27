# -*- coding: utf-8 -*-
import os
import re

templates_dir = r"c:\Users\kevse\OneDrive\Desktop\girisim\ReviseMeSon\templates"
files_to_update = [
    ("index.html", "index", "Panel"),
    ("today_questions.html", "today_questions", "Bugünün Soruları"),
    ("past_questions.html", "past_questions", "Geçmiş Sorular"),
    ("hedefleyici.html", "hedefleyici", "Gelişim Raporu"),
    ("timer.html", "timer", "Study Sessions"),
    ("settings.html", "settings", "Ayarlar ve Profil"),
    ("add_question.html", "add_question", "Soru Ekle"),
    ("favorites.html", "favorites", "Favoriler")
]

for filename, active_tag, title in files_to_update:
    filepath = os.path.join(templates_dir, filename)
    if not os.path.exists(filepath): continue
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Replace aside
    aside_pattern = re.compile(r'<aside\b[^>]*>.*?</aside>', re.DOTALL)
    new_aside = f"{{% set active_page = '{active_tag}' %}}\n{{% include 'components/sidebar_modern.html' %}}"
    content = aside_pattern.sub(new_aside, content, count=1)
    
    # Replace header
    header_pattern = re.compile(r'<header\b[^>]*>.*?</header>', re.DOTALL)
    new_header = f"{{% block header_title %}}{title}{{% endblock %}}\n{{% include 'components/header_modern.html' %}}"
    content = header_pattern.sub(new_header, content, count=1)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Updated {filename}")
