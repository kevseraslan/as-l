from dotenv import load_dotenv; load_dotenv()
import os, re

content = open('app.py', encoding='utf-8').read()
idx = content.find("SQLALCHEMY_DATABASE_URI")
print(content[idx:idx+200])
