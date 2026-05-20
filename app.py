from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, render_template_string, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
from flask_cors import CORS

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, and_, or_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from authlib.integrations.flask_client import OAuth
import urllib
from datetime import datetime, timedelta
import threading
import time
import hashlib # hashlib importunu tekrar ekledim
import json
import random # Bu satırı ekledim
import os
from werkzeug.utils import secure_filename
import secrets
import matplotlib.pyplot as plt # Grafik çizmek için
import pandas as pd # Veri işlemek için
import io # Grafik görselini kaydetmek için
import base64 # Grafik görselini base64 olarak encode etmek için
import uuid
import requests # Wikipedia API istekleri için eklendi
import google.generativeai as genai
import PIL.Image
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
# app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'reviseme-development-secret-key-12345')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False # HTTP üzerinde çalıştığımız için False olmalı
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31)

CORS(app, supports_credentials=True, origins=["http://192.168.1.101:5000", "http://localhost:5000", "http://127.0.0.1:5000", "null"]) 
# Alternatif olarak tüm originlere izin ver (credentials ile)
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin:
        # Mükerrer CORS başlıklarını önlemek için doğrudan dictionary ataması kullanıyoruz
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, X-Requested-With'
    return response

# MSSQL bağlantı parametreleri
driver = "ODBC Driver 17 for SQL Server"
server = "MSI\\SQLK"
database = "ReviseMe"

connection_string = f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;TrustServerCertificate=yes;MARS_Connection=yes;"
params = urllib.parse.quote_plus(connection_string)

# SQLAlchemy ayarları
app.config['SQLALCHEMY_DATABASE_URI'] = (
    'mssql+pyodbc://@MSI\\SQLK/ReviseMe?'
    'driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# CSRF koruması
csrf = CSRFProtect(app)
app.config['WTF_CSRF_CHECK_DEFAULT'] = False  # CSRF korumasını isteğe bağlı hale getir

# Mail ayarları
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'inforeviseme@gmail.com'
app.config['MAIL_PASSWORD'] = 'wjkn wyfm dmih rtsl'
app.config['MAIL_DEFAULT_SENDER'] = 'inforeviseme@gmail.com'

# AI-powered short learning feature config/state
SHORTS_UPLOAD_DIR = os.path.join(app.root_path, 'static', 'uploads', 'shorts')
os.makedirs(SHORTS_UPLOAD_DIR, exist_ok=True)
AI_SHORTS_STORE = []

# SendGrid ayarları
app.config['SENDGRID_API_KEY'] = os.getenv('SENDGRID_API_KEY', 'default_sendgrid_api_key')
app.config['SENDGRID_FROM_EMAIL'] = os.getenv('SENDGRID_FROM_EMAIL', 'default_sender@example.com')

# SQLAlchemy nesnesi
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Google OAuth Ayarları
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID', '508094154471-4s5m5pb87hg7oatf84s3g2kt2h5rhprd.apps.googleusercontent.com'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ── MOBİL & API İÇİN ÖZEL YETKİLENDİRME VE GÜVENLİK AYARLARI ──────────────────

@login_manager.unauthorized_handler
def unauthorized():
    """Mobil/API isteklerinde HTML login sayfasına yönlendirmek yerine 401 JSON döndürür."""
    if (request.path.startswith('/api/') or 
        request.is_json or 
        'application/json' in request.headers.get('Accept', '') or 
        request.path in ['/profile', '/add_question', '/save_pomodoro', '/generate_ai_quiz', '/timer', '/hedefleyici']):
        return jsonify({
            "success": False,
            "error": "Unauthorized",
            "message": "Lütfen önce giriş yapın."
        }), 401
    return redirect(url_for('login'))

@app.before_request
def csrf_exempt_for_mobile_and_api():
    """Mobil uygulamadan gelen POST isteklerini CSRF korumasından muaf tutar."""
    exempt_prefixes = [
        '/api/',
        '/mark_completed/',
        '/mark_failed/',
        '/delete_question/',
        '/toggle_favorite/',
        '/add_note/'
    ]
    exempt_exacts = [
        '/profile',
        '/add_question',
        '/save_pomodoro',
        '/generate_ai_quiz',
        '/login',
        '/timer',
        '/hedefleyici'
    ]
    
    path = request.path
    if any(path.startswith(prefix) for prefix in exempt_prefixes) or path in exempt_exacts:
        setattr(request, '_csrf_exempt', True)

mail = Mail(app)

# Database Models
class User(UserMixin, db.Model):
    __tablename__ = 'Users'
    UserId = db.Column(db.Integer, primary_key=True)
    UserName = db.Column(db.String(50), unique=True, nullable=False)
    PasswordHash = db.Column(db.String(128), nullable=False)
    Name = db.Column(db.String(50))
    Surname = db.Column(db.String(50))
    Class = db.Column(db.String(50))
    YearOfBirth = db.Column(db.Integer)
    Area = db.Column(db.String(50))
    Aim = db.Column(db.String(100))
    Email = db.Column(db.String(100))
    PhoneNumber = db.Column(db.String(20))
    GoogleAuthId = db.Column(db.String(100))
    SecurityQuestion = db.Column(db.String(200))
    SecurityAnswer = db.Column(db.String(200))

    def get_id(self):
        return str(self.UserId)
        
    def can_modify(self, question):
        return self.UserId == question.UserId

class Category(db.Model):
    __tablename__ = 'Categories'
    CategoryId = db.Column(db.Integer, primary_key=True)
    Name = db.Column(db.String(50))

    @property
    def question_count(self):
        if hasattr(self, '_question_count'):
            return self._question_count
        return Question.query.filter_by(CategoryId=self.CategoryId).count()

    @question_count.setter
    def question_count(self, value):
        self._question_count = value

class Question(db.Model):
    __tablename__ = 'Questions'
    
    QuestionId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'), nullable=False)
    CategoryId = db.Column(db.Integer, db.ForeignKey('Categories.CategoryId'), nullable=False)

    # Birleştirilmiş ve Standartlaştırılmış Alanlar
    content = db.Column('Content', db.Text, nullable=False) # DB'deki 'Content' sütununa bağlan
    topic = db.Column('Topic', db.String(100)) # DB'deki 'Topic' sütununa bağlan
    difficulty = db.Column('DifficultyLevel', db.String(50), default="Orta") # DB'deki 'DifficultyLevel' sütununa bağlan
    
    PhotoPath = db.Column(db.String(255))
    IsRepeated = db.Column(db.Boolean, default=False)
    RepeatCount = db.Column(db.Integer, default=0)
    Repeat1Date = db.Column(db.DateTime)
    Repeat2Date = db.Column(db.DateTime)
    Repeat3Date = db.Column(db.DateTime)
    IsCompleted = db.Column(db.Boolean, default=False)
    IsViewed = db.Column(db.Boolean, default=False)
    Explanation = db.Column(db.Text)
    ImagePath = db.Column(db.String(255))
    IsHidden = db.Column(db.Boolean, default=False)
    FailedAttempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    status = db.Column(db.String(50), default="unsolved")
    answer = db.Column(db.Text)

    @property
    def id(self):
        return self.QuestionId

    user = db.relationship('User', backref=db.backref('questions', lazy=True))
    category = db.relationship('Category', backref=db.backref('questions', lazy=True))

class Note(db.Model):
    __tablename__ = 'Notes'
    NoteId = db.Column(db.Integer, primary_key=True)
    QuestionId = db.Column(db.Integer, db.ForeignKey('Questions.QuestionId'))
    Content = db.Column(db.Text)
    
    question = db.relationship('Question', backref='notes')

class Favorite(db.Model):
    __tablename__ = 'Favorites'
    FavoriteId = db.Column(db.Integer, primary_key=True)
    QuestionId = db.Column(db.Integer, db.ForeignKey('Questions.QuestionId'), nullable=False)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'), nullable=False)
    
    # İlişkiler
    question = db.relationship('Question', backref='favorites')
    user = db.relationship('User', backref='favorites')

class Notification(db.Model):
    __tablename__ = 'Notifications'
    NotificationId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'))
    NotificationType = db.Column(db.String(50))
    Schedule = db.Column(db.DateTime)
    
    user = db.relationship('User', backref='notifications')

class PasswordResetToken(db.Model):
    __tablename__ = 'PasswordResetTokens'
    TokenId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'), nullable=False)
    Token = db.Column(db.String(100), unique=True, nullable=False)
    ExpiresAt = db.Column(db.DateTime, nullable=False)
    IsUsed = db.Column(db.Boolean, default=False)
    
    user = db.relationship('User', backref='password_reset_tokens')

class TedTalk(db.Model):
    __tablename__ = 'TedTalks'
    TalkId = db.Column(db.Integer, primary_key=True)
    Title = db.Column(db.String(200), nullable=False)
    Speaker = db.Column(db.String(100), nullable=False)
    VideoUrl = db.Column(db.String(500), nullable=False)
    Description = db.Column(db.Text)
    Duration = db.Column(db.String(50))
    Category = db.Column(db.String(100))
    IsWatched = db.Column(db.Boolean, default=False)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'), nullable=False)
    user = db.relationship('User', backref='ted_talks')

class Book(db.Model):
    __tablename__ = 'Books'
    BookId = db.Column(db.Integer, primary_key=True)
    Title = db.Column(db.String(200))
    Author = db.Column(db.String(100))
    CurrentPage = db.Column(db.Integer)
    TotalPages = db.Column(db.Integer)
    StartDate = db.Column(db.DateTime)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'))
    IsCompleted = db.Column(db.Boolean, default=False)  # <-- BUNU EKLE!
    user = db.relationship('User', backref='books')

class PomodoroSession(db.Model):
    __tablename__ = 'PomodoroSessions'
    SessionId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'), nullable=False)
    Duration = db.Column(db.Integer)  # Dakika cinsinden
    Type = db.Column(db.String(50))  # 'pomodoro', 'short_break', 'long_break'
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('pomodoro_sessions', lazy=True))

class BookQuote(db.Model):
    __tablename__ = 'BookQuotes'
    QuoteId = db.Column(db.Integer, primary_key=True)
    BookId = db.Column(db.Integer, db.ForeignKey('Books.BookId'))
    PageNumber = db.Column(db.Integer)
    Content = db.Column(db.Text)
    Note = db.Column(db.Text)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)
    book = db.relationship('Book', backref='quotes')

class ChatMessage(db.Model):
    __tablename__ = 'ChatMessages'
    MessageId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'))
    Content = db.Column(db.Text)
    IsFromAI = db.Column(db.Boolean, default=False)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='chat_messages')

class Task(db.Model):
    __tablename__ = 'Tasks'
    TaskId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'))
    Title = db.Column(db.String(200))
    Description = db.Column(db.Text)
    DueDate = db.Column(db.DateTime)
    Priority = db.Column(db.String(20))  # 'high', 'medium', 'low'
    Category = db.Column(db.String(50))  # 'work', 'personal', 'hobby'
    Status = db.Column(db.String(20))  # 'pending', 'completed'
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)
    CompletedAt = db.Column(db.DateTime)
    user = db.relationship('User', backref='tasks')

class TaskTime(db.Model):
    __tablename__ = 'TaskTimes'
    TimeId = db.Column(db.Integer, primary_key=True)
    TaskId = db.Column(db.Integer, db.ForeignKey('Tasks.TaskId'))
    StartTime = db.Column(db.DateTime)
    EndTime = db.Column(db.DateTime)
    Duration = db.Column(db.Integer)  # Dakika cinsinden
    task = db.relationship('Task', backref='time_records')

class AIShort(db.Model):
    __tablename__ = 'AIShorts'
    ShortId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'), nullable=False)
    QuestionText = db.Column(db.Text, nullable=False)
    Topic = db.Column(db.String(100))
    Subject = db.Column(db.String(50))
    Difficulty = db.Column(db.String(20))
    StepsJson = db.Column(db.Text)  # JSON string of steps
    FinalAnswer = db.Column(db.String(500))
    VoiceoverText = db.Column(db.Text)
    Likes = db.Column(db.Integer, default=0)
    IsBookmarked = db.Column(db.Boolean, default=False)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='ai_shorts')


def _smart_solve(text):
    import re
    # Basit uslu sayi kaliplarini yakala: 2^3, 5^2 vb.
    power_match = re.search(r'(\d+)\s*[\^**]\s*(\d+)', text)
    if power_match:
        base = int(power_match.group(1))
        exp = int(power_match.group(2))
        res = base ** exp
        return {
            "q": f"{base}^{exp} isleminin sonucu kactir?",
            "steps": [f"Taban {base}, us {exp}.", f"{base} sayisini {exp} kere kendisiyle carp.", f"Sonuc: {res}"],
            "ans": str(res)
        }
    # Basit toplama/carpma: 10+5, 4*3
    math_match = re.search(r'(\d+)\s*([\+\-\*\/])\s*(\d+)', text)
    if math_match:
        a = int(math_match.group(1))
        op = math_match.group(2)
        b = int(math_match.group(3))
        if op == '+': res = a + b
        elif op == '-': res = a - b
        elif op == '*': res = a * b
        elif op == '/': res = a / b if b != 0 else "Tanimsiz"
        return {
            "q": f"{a} {op} {b} isleminin sonucu kactir?",
            "steps": [f"{a} ve {b} sayilarini {op} islemine sok.", f"Sonuc: {res}"],
            "ans": str(res)
        }
    return None

def _detect_subject_topic(text_hint):
    text = (text_hint or "").lower()
    if any(k in text for k in ["uslu", "üslü", "taban", "kuvvet"]):
        return "Matematik", "Üslü Sayılar"
    if any(k in text for k in ["integral", "turev", "türev", "matematik", "denklem", "fonksiyon"]):
        return "Matematik", "Fonksiyonlar ve Analiz"
    if any(k in text for k in ["newton", "kuvvet", "fizik", "hiz", "ivme"]):
        return "Fizik", "Kuvvet ve Hareket"
    if any(k in text for k in ["reaksiyon", "kimya", "molekul", "atom"]):
        return "Kimya", "Temel Kimya"
    if any(k in text for k in ["osmanli", "tarih", "inkilap"]):
        return "Tarih", "Tarih ve Medeniyet"
    return "Genel", "Mantık ve Muhakeme"


def _estimate_difficulty(text_hint):
    text = (text_hint or "").lower()
    if len(text) > 220 or any(k in text for k in ["ispat", "zor", "advanced", "proof"]):
        return "zor"
    if len(text) > 80:
        return "orta"
    return "kolay"


def _generate_solution_steps(subject, topic, difficulty):
    return [
        f"Soruyu oku ve {topic} kapsamindaki temel kavramlari tespit et.",
        f"{subject} icin gerekli formulu/yaklasimi sec ve verilenleri yerlestir.",
        "Ara adimlari sadelestir, kritik donusumleri tek tek kontrol et.",
        "Sonucu dogrula ve alternatif cozum yolunu kisaca ozetle.",
        f"Zorluk seviyesi: {difficulty}. Bir benzer soru ile pekistirme yap.",
    ]


def _generate_similar_questions_gemini(original_text, count=1, image_path=None):
    try:
        model = genai.GenerativeModel('gemini-flash-lite-latest')
        
        prompt = f"""
        Aşağıdaki eğitim içeriğini derinlemesine analiz et. 
        Eğer bir görsel varsa görseldeki soruyu çöz, konusunu ve mantığını anla.
        Bu içeriğe 'ikiz' olabilecek (aynı mantık, farklı değerler/hikaye), dikey ekran formatına (Shorts/TikTok) uygun yeni {count} adet soru üret.
        
        Metin İçeriği: {original_text if original_text else 'Görseldeki soruyu analiz et.'}
        
        Yanıtı TAM OLARAK şu JSON şemasında ver (BAŞKA HİÇBİR METİN EKLEME, doğrudan '[' ile başla):
        [
          {{
            "subject": "Ders adı",
            "topic": "Konu adı",
            "difficulty": "kolay/orta/zor",
            "new_question": "Soru metni buraya (BOŞ BIRAKMA!)",
            "solution_steps": ["Adım 1: ...", "Adım 2: ...", "Adım 3: ..."],
            "final_answer": "Net cevap (BOŞ BIRAKMA!)",
            "voiceover": "Seslendirme metni"
          }}
        ]
        
        KRİTİK: 'new_question', 'solution_steps' ve 'final_answer' alanlarını ASLA boş bırakma. Görseli göremiyorsan bile mantıklı bir soru uret.
        """
        
        content_parts = [prompt]
        if image_path and os.path.exists(image_path):
            try:
                img = PIL.Image.open(image_path)
                content_parts.append(img)
            except Exception as img_err:
                print(f"Image Load Error: {img_err}")
        
        response = model.generate_content(content_parts)
        try:
            raw_text = response.text.strip()
        except Exception as text_err:
            print(f"Gemini Text read error: {text_err}")
            return []

        # JSON temizleme (Markdown ve ekstra metinleri ayikla)
        import re
        json_match = re.search(r'[\{\[].*[\}\]]', raw_text, re.DOTALL)
        if json_match:
            json_text = json_match.group(0)
            # Trailing comma temizliği
            json_text = re.sub(r',\s*([\]\}])', r'\1', json_text)
            import json
            try:
                parsed_data = json.loads(json_text)
                if isinstance(parsed_data, list):
                    return parsed_data
                elif isinstance(parsed_data, dict):
                    # dict içindeki ilk liste değerini bulup döndür
                    for val in parsed_data.values():
                        if isinstance(val, list):
                            return val
                return []
            except Exception as json_err:
                print(f"JSON load error: {json_err}. Raw text: {raw_text[:200]}")
                return []
        else:
            print(f"No JSON found in response: {raw_text}")
            return []
    except Exception as e:
        print(f"Gemini Error: {e}")
        return []

def _generate_similar_questions(subject, topic, difficulty, original_text="", count=2, image_path=None):
    # Gemini ile uretmeyi dene
    gemini_results = _generate_similar_questions_gemini(original_text, count, image_path)
    if gemini_results:
        return gemini_results
    
    # Once orijinal metni cozmeye calis (Smart Solve)
    smart_res = _smart_solve(original_text)
    
    # ... rest of the mock logic as fallback ...
    base_templates = {
        "Matematik": {
            "Üslü Sayılar": [
                {"q": "2^3 * 2^4 isleminin sonucu kactir?", "steps": ["Tabanlar ayniysa usler toplanir.", "2^(3+4)", "2^7 = 128"], "ans": "128"},
                {"q": "(3^2)^3 ifadesinin degeri nedir?", "steps": ["Usun ussu alinirken usler carpilir.", "3^(2*3)", "3^6 = 729"], "ans": "729"},
                {"q": "5^0 + 5^1 + 5^2 toplami kactir?", "steps": ["5^0 = 1", "5^1 = 5", "5^2 = 25", "1 + 5 + 25 = 31"], "ans": "31"}
            ],
            "Fonksiyonlar ve Analiz": [
                {"q": "f(x) = x^2 + 3x ise f'(2) degerini bulunuz.", "steps": ["Turev al: f'(x) = 2x + 3", "x yerine 2 koy: 2(2) + 3", "4 + 3 = 7"], "ans": "7"},
                {"q": "log2(32) kactir?", "steps": ["32 = 2^5", "log2(2^5) = 5"], "ans": "5"},
            ],
        },
        "Fizik": {
            "Kuvvet ve Hareket": [
                {"q": "Bir cisim 20m yolu 4s'de alirsa hizi kactir?", "steps": ["V = x / t", "V = 20 / 4", "5 m/s"], "ans": "5 m/s"},
                {"q": "F=10N, m=2kg ise ivme kactir?", "steps": ["a = F / m", "a = 10 / 2", "5 m/s^2"], "ans": "5 m/s^2"}
            ],
        },
        "Biyoloji": {
            "Hücre": [
                {"q": "Bitki ve hayvan hücresi arasındaki en temel fark nedir?", "steps": ["Hücre çeperini kontrol et.", "Kloroplast varlığına bak.", "Koful büyüklüklerini karşılaştır."], "ans": "Hücre çeperi ve kloroplast"},
                {"q": "Mitokondrinin temel görevi nedir?", "steps": ["Enerji üretimini düşün.", "ATP sentezini hatırla.", "Oksijenli solunum merkezidir."], "ans": "ATP Üretimi"}
            ],
            "Genel": [
                {"q": "Fotosentez nerede gerçekleşir?", "steps": ["Işık enerjisini düşün.", "Kloroplast organelini hatırla.", "Karbondioksit ve suyun birleşimi."], "ans": "Kloroplast"}
            ]
        }
    }

    # Default fallback
    generic_templates = {
        "kolay": [{"q": f"{topic} konusunda bir temel soru.", "steps": ["Konuyu analiz et.", "Cozume ulas."], "ans": "Cozuldu."}],
        "orta": [{"q": f"{topic} orta seviye problem.", "steps": ["Verileri isle.", "Formul kullan."], "ans": "Tamamlandi."}],
        "zor": [{"q": f"{topic} ileri duzey soru.", "steps": ["Karmasik analizi yap.", "Sonucu bul."], "ans": "Analiz bitti."}]
    }

    # Konu spesifik templates var mi bak
    subject_topics = base_templates.get(subject, {})
    templates = subject_topics.get(topic, [])
    
    if not templates:
        # Konu bulunamazsa branşın rastgele bir konusunu seç veya branş da yoksa generic
        if subject_topics:
            all_subject_qs = [q for qs in subject_topics.values() for q in qs]
            templates = all_subject_qs
        else:
            templates = generic_templates.get(difficulty, generic_templates["orta"])

    import random
    selected = random.sample(templates, min(len(templates), count))
    
    results = []
    # Eger smart solve basariliysa onu ilk siraya ekle
    if smart_res:
        results.append({
            "questionText": f"Orijinal Soru Cozumu: {smart_res['q']}",
            "steps": smart_res['steps'],
            "finalAnswer": smart_res['ans'],
            "voiceover": f"Yukledigin soruyu analiz ettim. {smart_res['q']} isleminin cozumu soyle: {', '.join(smart_res['steps'])}. Yani cevabimiz {smart_res['ans']}."
        })

    for item in selected:
        results.append({
            "questionText": f"AI Onersisi: {item['q']}",
            "steps": item['steps'],
            "finalAnswer": item['ans'],
            "voiceover": f"Simdi senin icin {topic} konusundan benzer bir soru cozecegim. Sorumuz: {item['q']}. {', '.join(item['steps'])}. Ve sonuc: {item['ans']}."
        })
    
    return results

class TaskReport(db.Model):
    __tablename__ = 'TaskReports'
    ReportId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'))
    ReportDate = db.Column(db.DateTime)
    CompletedTasks = db.Column(db.Integer)
    OverdueTasks = db.Column(db.Integer)
    TotalTimeSpent = db.Column(db.Integer)  # Dakika cinsinden
    ReportContent = db.Column(db.Text)
    user = db.relationship('User', backref='task_reports')

class UserSettings(db.Model):
    __tablename__ = 'UserSettings'
    SettingId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'))
    Theme = db.Column(db.String(20), default='light')  # 'light', 'dark'
    EmailNotifications = db.Column(db.Boolean, default=True)
    RepeatInterval = db.Column(db.Integer, default=1)  # Tekrar aralığı (gün cinsinden)
    user = db.relationship('User', backref='settings')

class Reminder(db.Model):
    __tablename__ = 'Reminders'
    ReminderId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'), nullable=False)
    QuestionId = db.Column(db.Integer, db.ForeignKey('Questions.QuestionId'), nullable=False)
    Frequency = db.Column(db.String(20))  # 'daily', 'weekly', 'monthly'
    Time = db.Column(db.Time)  # Hatırlatma saati
    IsActive = db.Column(db.Boolean, default=True)
    LastSent = db.Column(db.DateTime)
    CreatedAt = db.Column(db.DateTime, default=datetime.now)
    
    user = db.relationship('User', backref='reminders')
    question = db.relationship('Question', backref='reminders')

class Listening(db.Model):
    __tablename__ = 'Listenings'
    ListeningId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(db.Integer, db.ForeignKey('Users.UserId'))
    Title = db.Column(db.String(200))
    IsCompleted = db.Column(db.Boolean, default=False)
    user = db.relationship('User', backref='listenings')

def create_categories():
    categories = [
        {'name': 'Matematik', 'icon': 'math.png'},
        {'name': 'Türk Dili ve Edebiyatı', 'icon': 'literature.png'},
        {'name': 'Felsefe', 'icon': 'philosophy.png'},
        {'name': 'Din', 'icon': 'religion.png'},
        {'name': 'Coğrafya', 'icon': 'geography.png'},
        {'name': 'Fizik', 'icon': 'physics.png'},
        {'name': 'Kimya', 'icon': 'chemistry.png'},
        {'name': 'Biyoloji', 'icon': 'biology.png'},
        {'name': 'Tarih', 'icon': 'history.png'},
        {'name': 'Yabancı Dil', 'icon': 'language.png'}
    ]
    
    for category in categories:
        if not Category.query.filter_by(Name=category['name']).first():
            new_category = Category(Name=category['name'])
            db.session.add(new_category)
    
    try:
        db.session.commit()
        print("Kategoriler başarıyla oluşturuldu.")
    except Exception as e:
        db.session.rollback()
        print(f"Kategori oluşturma hatası: {str(e)}")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/welcome')
def welcome():
    return render_template('welcome_new.html')


@app.route('/api/check_session', methods=['GET'])
def check_session():
    if current_user.is_authenticated:
        return jsonify({
            "success": True,
            "user": {
                "id": current_user.UserId,
                "username": current_user.UserName
            }
        })
    return jsonify({"success": False, "message": "Oturum açılmamış"}), 401

# ─── MOBİL API ──────────────────────────────────────────────────────────────
@app.route('/api/notifications', methods=['GET'])
def api_notifications():
    """
    Mobil uygulama için bildirim listesi.
    Oturum açık kullanıcıya özel dinamik bildirimler üretir;
    oturum yoksa genel örnek bildirimler döner.
    """
    today = datetime.now().date()
    today_str = today.strftime('%Y-%m-%d')
    notifications = []
    notif_id = 1

    if not current_user.is_authenticated:
        if request.is_json or 'application/json' in request.headers.get('Accept', ''):
            return jsonify({"success": False, "message": "Oturum açmanız gerekiyor."}), 401
        return jsonify([]) 
    
    target_user_id = current_user.UserId

    # 1) Bugünün Soruları
    today_questions = Question.query.filter(
        Question.UserId == target_user_id,
        Question.IsCompleted == False,
        Question.IsHidden == False,
        (
            (Question.RepeatCount == 0) & (db.func.cast(Question.Repeat1Date, db.Date) == today)
            |
            (Question.RepeatCount == 1) & (db.func.cast(Question.Repeat2Date, db.Date) == today)
            |
            (Question.RepeatCount == 2) & (db.func.cast(Question.Repeat3Date, db.Date) == today)
        )
    ).all()

    # 2) Geçmiş Sorular
    past_questions = Question.query.filter(
        Question.UserId == target_user_id,
        Question.IsCompleted == False,
        Question.RepeatCount < 3,
        (
            (Question.RepeatCount == 0) & (db.func.cast(Question.Repeat1Date, db.Date) < today)
            |
            (Question.RepeatCount == 1) & (db.func.cast(Question.Repeat2Date, db.Date) < today)
            |
            (Question.RepeatCount == 2) & (db.func.cast(Question.Repeat3Date, db.Date) < today)
        )
    ).all()

    # 3) Performans Analizi
    today_count = len(today_questions)
    past_count = len(past_questions)
    pending_count = today_count + past_count
    
    total_questions = Question.query.filter_by(UserId=target_user_id, IsHidden=False).count()
    
    if total_questions > 0:
        completion_rate = int(((total_questions - pending_count) / total_questions) * 100)
    else:
        completion_rate = 100

    if completion_rate >= 90:
        performance_grade = 'A+'
    elif completion_rate >= 80:
        performance_grade = 'A'
    elif completion_rate >= 70:
        performance_grade = 'B'
    elif completion_rate >= 50:
        performance_grade = 'C'
    else:
        performance_grade = 'D'

    # Yanıt Olarak Dashboard İstatistiklerini Dönüyoruz
    dashboard_data = {
        "username": test_user.UserName if not current_user.is_authenticated else current_user.UserName,
        "today_count": today_count,
        "past_count": past_count,
        "completion_rate": completion_rate,
        "performance_grade": performance_grade
    }

    return jsonify(dashboard_data)

@app.route('/api/today_questions', methods=['GET'])
def api_today_questions():
    """
    Mobil uygulama için bugünün soruları listesi.
    Oturum açık değilse 'ahmet' kullanıcısının verilerini döner (Test kolaylığı için).
    """
    today = datetime.now().date()
    
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Oturum açmanız gerekiyor."}), 401
    
    target_user = current_user
    target_user_id = current_user.UserId

    # Bugünün Soruları Sorgusu (Vadesi bugün veya geçmişte olanlar)
    today_questions = Question.query.filter(
        Question.UserId == target_user_id,
        Question.IsCompleted == False,
        Question.IsHidden == False,
        db.or_(
            db.and_(Question.RepeatCount == 0, db.func.cast(Question.Repeat1Date, db.Date) == today),
            db.and_(Question.RepeatCount == 1, db.func.cast(Question.Repeat2Date, db.Date) == today),
            db.and_(Question.RepeatCount == 2, db.func.cast(Question.Repeat3Date, db.Date) == today)
        )
    ).all()

    # Geçmiş Sorular Sorgusu
    past_questions = Question.query.filter(
        Question.UserId == target_user_id,
        Question.IsCompleted == False,
        Question.RepeatCount < 3,
        (
            (Question.RepeatCount == 0) & (db.func.cast(Question.Repeat1Date, db.Date) < today)
            |
            (Question.RepeatCount == 1) & (db.func.cast(Question.Repeat2Date, db.Date) < today)
            |
            (Question.RepeatCount == 2) & (db.func.cast(Question.Repeat3Date, db.Date) < today)
        )
    ).order_by(Question.Repeat1Date.desc()).all()

    def question_to_dict(q):
        return {
            "id": q.QuestionId,
            "content": q.content,
            "topic": q.topic,
            "category": q.category.Name if q.category else "Genel",
            "difficulty": q.difficulty,
            "image": q.ImagePath or q.PhotoPath,
            "repeat_count": q.RepeatCount,
            "created_at": q.created_at.strftime('%d.%m.%Y') if q.created_at else None
        }

    # Performans Analizi
    total_q_count = Question.query.filter_by(UserId=target_user_id, IsHidden=False).count()
    pending_count = len(today_questions) + len(past_questions)
    
    if total_q_count > 0:
        completion_rate = int(((total_q_count - pending_count) / total_q_count) * 100)
    else:
        completion_rate = 100

    if completion_rate >= 90: performance_grade = 'A+'
    elif completion_rate >= 80: performance_grade = 'A'
    elif completion_rate >= 70: performance_grade = 'B'
    elif completion_rate >= 50: performance_grade = 'C'
    else: performance_grade = 'D'

    # Bugün zaten çözülmüş soruları say
    solved_today_count = Question.query.filter(
        Question.UserId == target_user_id,
        db.or_(
            db.and_(Question.RepeatCount == 1, db.func.cast(Question.Repeat1Date, db.Date) == today),
            db.and_(Question.RepeatCount == 2, db.func.cast(Question.Repeat2Date, db.Date) == today),
            db.and_(Question.RepeatCount == 3, db.func.cast(Question.Repeat3Date, db.Date) == today)
        )
    ).count()

    return jsonify({
        "success": True,
        "username": target_user.UserName,
        "today_questions": [question_to_dict(q) for q in today_questions],
        "past_questions": [question_to_dict(q) for q in past_questions],
        "today_count": len(today_questions),
        "past_count": len(past_questions),
        "solved_today": solved_today_count,
        "completion_rate": completion_rate,
        "performance_grade": performance_grade
    })
# ─── MOBİL API SONU ─────────────────────────────────────────────────────────


@app.route('/api/shorts/videos', methods=['GET'])
@login_required
def get_ai_shorts_videos():
    # Mevcut uretilmis shorts'lari getir
    stored_shorts = AIShort.query.filter_by(UserId=current_user.UserId).order_by(AIShort.CreatedAt.desc()).all()
    
    # Eger hic yoksa veya havuz degistiyse yeni uretim yapalim
    # Not: Kullanıcı "yenile" butonuna basarsa burası tetiklenebilir (ileride eklenebilir)
    if len(stored_shorts) < 2:
        print(f"DEBUG: Generating new shorts for user {current_user.UserId}")
        # Soru havuzundan en yeni 20 soruyu analiz yap (oncelikli olarak yeni eklenenler gelsin)
        user_questions = Question.query.filter_by(UserId=current_user.UserId).order_by(Question.QuestionId.desc()).limit(20).all()
        if user_questions:
            # Rastgele bir referans soru secelim
            ref_q = random.choice(user_questions)
            ref_subject = ref_q.category.Name if ref_q.category else "Genel"
            ref_topic = ref_q.topic or "Genel"
            ref_content = ref_q.content
            
            # Görsel yolunu belirle
            image_path = None
            raw_path = ref_q.ImagePath or ref_q.PhotoPath
            if raw_path:
                # Path normalization: static/ ekle veya absolute yap
                if raw_path.startswith('uploads/'):
                    image_path = os.path.join(app.root_path, 'static', raw_path)
                elif raw_path.startswith('static/uploads/'):
                    image_path = os.path.join(app.root_path, raw_path)
            
            print(f"DEBUG: Reference question ID: {ref_q.QuestionId}, Subject: {ref_subject}, Image: {image_path}")
            
            # Bu sorudan esinlenerek Gemini ile benzer sorular uret
            similar_data = _generate_similar_questions(
                ref_subject, 
                ref_topic, 
                ref_q.difficulty or "orta", 
                original_text=ref_content, 
                count=5,
                image_path=image_path
            )
            
            if similar_data:
                for item in similar_data:
                    import json
                    # Key mapping flexibility (handle variants)
                    q_text = item.get("new_question") or item.get("question") or item.get("questionText") or item.get("text") or "Yeni Soru"
                    s_steps = item.get("solution_steps") or item.get("steps") or item.get("solution") or []
                    f_ans = item.get("final_answer") or item.get("answer") or item.get("ans") or item.get("finalAnswer") or ""
                    
                    new_short = AIShort(
                        UserId=current_user.UserId,
                        QuestionText=q_text,
                        Topic=item.get("topic", ref_topic),
                        Subject=item.get("subject", ref_subject),
                        Difficulty=item.get("difficulty", "orta"),
                        StepsJson=json.dumps(s_steps),
                        FinalAnswer=f_ans,
                        VoiceoverText=item.get("voiceover", "")
                    )
                    db.session.add(new_short)
                db.session.commit()
                print(f"DEBUG: Successfully generated {len(similar_data)} shorts")
            else:
                print("DEBUG: Gemini failed to generate similar questions")
                # Guncel listeyi tekrar cek
                stored_shorts = AIShort.query.filter_by(UserId=current_user.UserId).order_by(AIShort.CreatedAt.desc()).all()

    videos = []
    for s in stored_shorts:
        import json
        videos.append({
            "id": str(s.ShortId),
            "questionText": s.QuestionText,
            "subject": s.Subject,
            "topic": s.Topic,
            "difficulty": s.Difficulty,
            "steps": json.loads(s.StepsJson) if s.StepsJson else [],
            "finalAnswer": s.FinalAnswer,
            "voiceoverText": s.VoiceoverText,
            "likes": s.Likes,
            "bookmarked": s.IsBookmarked,
            "voiceoverReady": True
        })
    
    return jsonify({"videos": videos})

@app.route('/api/shorts/clear', methods=['POST'])
@login_required
def clear_ai_shorts():
    try:
        print(f"DEBUG: Clearing shorts for user {current_user.UserId}")
        AIShort.query.filter_by(UserId=current_user.UserId).delete()
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})


# ─── TYT/AYT Shorts Feed API ──────────────────────────────────────────────────
#
# Strateji:
# 1. Kullanıcının son sorularından konu çıkar (category + topic)
# 2. Gemini bu konuya en uygun TYT/AYT alt konusunu belirler
# 3. Curated TYT/AYT video havuzundan eşleşen videoyu döndür
# 4. Video bulunamazsa rastgele TYT havuzundan video seç
#
# Video ID'leri: Embed iznine sahip, "1 dakikada soru çözümü" formatındaki kanallar
# Kanallar: Tonguç Akademi, Hocalara Geldik, Khan Academy TR, Rehber Matematik vb.

# TYT Matematik – Gerçek "1 Dakikada 1 Soru" formatındaki videolar
_TYT_MAT = [
    {"video_id": "alXUXyBTyrA", "title": "TYT Matematik – 1 Dakika +1 Net 💥"},
    {"video_id": "I-4k1dxMZao", "title": "TYT Matematik – 1 Dakika 1 Net | Video 23"},
    {"video_id": "ZBb_312mVh4", "title": "TYT Matematik – Çıkmış Problem Soru Çözümü"},
    {"video_id": "yhcqD-QQjYw", "title": "TYT Matematik – 1 Dakika 1 Soru"},
    {"video_id": "dbsRUA11hwI", "title": "TYT Matematik – 1dk 1 Zor Soru"},
    {"video_id": "TQeAiHKuIp0", "title": "TYT Matematik – Mutlak Değer Soru Çözümü"},
    # Fallback: 3Blue1Brown görsel matematik
    {"video_id": "aircAruvnKk", "title": "TYT Matematik – Fonksiyon Kavramı"},
    {"video_id": "fNk_zzaMoSs", "title": "TYT Matematik – Vektör Sorusu"},
    {"video_id": "tIeHLnjs5U8", "title": "TYT Matematik – Lineer Denklem"},
    {"video_id": "Ilg3gGewQ5U", "title": "TYT Matematik – Türev Uygulaması"},
]

# TYT Geometri – Gerçek TYT formatı
_TYT_GEO = [
    {"video_id": "llFoR1o9qBs", "title": "TYT Geometri – 1 Dakika +1 Net 💥"},
    {"video_id": "PuDzJQcs0QQ", "title": "TYT Geometri – 1 Dakika 1 Net Video 36"},
    {"video_id": "F47BzAVjXzg", "title": "TYT Geometri – 1 Dakika 1 Net Video 24"},
    {"video_id": "kBaLG2mtRx8", "title": "TYT Geometri – Çıkmış Sorular"},
    {"video_id": "k7RM-ot2NWY", "title": "TYT Geometri – 3D Şekil Sorusu"},
    {"video_id": "WNuIhXo39_k", "title": "TYT Geometri – Çevre ve Alan"},
]

# TYT Fizik – Gerçek "1 dakikada" formatı
_TYT_FIZ = [
    {"video_id": "PnZujz49akE", "title": "TYT Fizik – 1 Dakika 1 Soru Çözümü"},
    {"video_id": "vwYDaRc3tV4", "title": "TYT Fizik – 1 Dakika 1 Soru (2)"},
    {"video_id": "vGClK7w1RPY", "title": "TYT Fizik – 1 Dakika 1 Soru (3)"},
    {"video_id": "Exgc-YReGX8", "title": "TYT Fizik – 1 Dakika 1 Soru (4)"},
    {"video_id": "kDzh4HQ5wkQ", "title": "TYT Fizik – 1 Dakika 1 Soru (5)"},
    {"video_id": "wRCfNl2LxLs", "title": "TYT Fizik – 1 Dakika 1 Soru (6)"},
    {"video_id": "2jEIeD_Iptc", "title": "TYT Fizik – 1 Dakika 1 Soru (7)"},
    {"video_id": "YKVPslaY5vc", "title": "TYT Fizik – 1 Dakika 1 Soru (8)"},
]

# TYT Kimya – Gerçek kısa çözüm videoları
_TYT_KIM = [
    {"video_id": "5bs0Z6beW_I", "title": "TYT Kimya – Milyonda Bir Kısım (ppm)"},
    {"video_id": "K86mQbrnz3Y", "title": "TYT Kimya – Pilde Anot Katot"},
    {"video_id": "o_PQ667QhD4", "title": "TYT Kimya – Periyodik Sistem Sorusu"},
    {"video_id": "yPRX2J3YLqY", "title": "TYT Kimya – 1 Dakika 1 Soru"},
    {"video_id": "BiSHUJNRAGw", "title": "TYT Kimya – Kimya +1 Net"},
    {"video_id": "0RRVV4Diomg", "title": "TYT Kimya – Periyodik Tablo"},
    {"video_id": "L-_LHeMmFq4", "title": "TYT Kimya – Asit Baz Sorusu"},
]

# TYT Biyoloji – Gerçek kısa çözüm videoları
_TYT_BIO = [
    {"video_id": "Kig62YfRUO0", "title": "TYT Biyoloji – 1 Dakika 1 Soru"},
    {"video_id": "HljPI3jqJN8", "title": "TYT Biyoloji – 1 Dakika 1 Soru (2)"},
    {"video_id": "unIG8d_cd2Q", "title": "TYT Biyoloji – 1 Dakika 1 Soru (3)"},
    {"video_id": "7rPPojdw3RY", "title": "TYT Biyoloji – 1 Dakika 1 Soru (4)"},
    {"video_id": "5vvuGk0GXi4", "title": "TYT Biyoloji – 1 Dakika 1 Soru (5)"},
    {"video_id": "r7w9l3fd7Ng", "title": "TYT Biyoloji – Organeller Soru Çözümü"},
    {"video_id": "IQJ4DBkCnco", "title": "TYT Biyoloji – Fotosentez Sorusu"},
    {"video_id": "NNASRkIU5Fw", "title": "TYT Biyoloji – Genetik Sorusu"},
]

# TYT Türkçe/Sosyal
_TYT_SOC = [
    {"video_id": "arj7oStGLkU", "title": "TYT Türkçe – Paragraf Sorusu Analizi"},
    {"video_id": "9D05ej8u-gU", "title": "TYT Tarih – Osmanlı Dönemi Sorusu"},
    {"video_id": "Unzc731iCUY", "title": "TYT Coğrafya – İklim & Yağış Sorusu"},
    {"video_id": "OQR3c3kkQrk", "title": "TYT Felsefe – Mantık Sorusu"},
    {"video_id": "bTR2EQ65bAw", "title": "TYT Türkçe – Anlam Sorusu Çözümü"},
]


# Havuz → kategori eşlemesi
TYT_POOL_MAP = {
    "Matematik": _TYT_MAT,
    "Geometri": _TYT_GEO,
    "Fizik": _TYT_FIZ,
    "Kimya": _TYT_KIM,
    "Biyoloji": _TYT_BIO,
    "Türk Dili ve Edebiyatı": _TYT_SOC,
    "Tarih": _TYT_SOC,
    "Coğrafya": _TYT_SOC,
    "Felsefe": _TYT_SOC,
    "Din": _TYT_SOC,
    "Genel": _TYT_MAT + _TYT_FIZ + _TYT_KIM + _TYT_BIO,
    "Tümü": _TYT_MAT + _TYT_GEO + _TYT_FIZ + _TYT_KIM + _TYT_BIO + _TYT_SOC,
}

# Renk haritası
_COLOR_MAP = {
    "Matematik": "#6C3AFA",
    "Geometri": "#0EA5E9",
    "Fizik": "#E34040",
    "Kimya": "#17A779",
    "Biyoloji": "#F4A019",
    "Türk Dili ve Edebiyatı": "#EC4899",
    "Tarih": "#D97706",
    "Coğrafya": "#059669",
    "Felsefe": "#7C3AED",
    "Din": "#6366F1",
}

# Kaydedilen shorts havuzu (bellek içi)
_SAVED_SHORTS_POOL: list = []

# Kısa önbellek: {user_id → (zaman, [topic_list])}
_USER_TOPIC_CACHE: dict = {}


def _get_user_priority_topics(user_id: int) -> list:
    """Kullanıcının son sorularından öncelikli konuları döndürür."""
    import time
    now = time.time()
    cached = _USER_TOPIC_CACHE.get(user_id)
    if cached and (now - cached[0]) < 120:  # 2 dakika cache
        return cached[1]

    questions = (Question.query
                 .filter_by(UserId=user_id, IsHidden=False)
                 .order_by(Question.QuestionId.desc())
                 .limit(30).all())

    if not questions:
        return []

    # Kategori frekans sayacı
    freq: dict = {}
    for q in questions:
        cat = q.category.Name if q.category else "Genel"
        freq[cat] = freq.get(cat, 0) + 1

    # Sıkça çalışılan konuları büyükten küçüğe listele
    sorted_cats = sorted(freq.keys(), key=lambda k: freq[k], reverse=True)
    _USER_TOPIC_CACHE[user_id] = (now, sorted_cats)
    return sorted_cats


def _gemini_pick_tyt_topic(question_text: str, question_topic: str, category: str) -> dict:
    """
    Gemini'ye kullanıcının sorusunu verip TYT/AYT video için
    en uygun kategori, konu etiketini ve video başlığını ürettirir.
    Returns: {category, sub_topic, title}
    """
    try:
        model = genai.GenerativeModel('gemini-flash-lite-latest')
        prompt = f"""
Bir Türk lise öğrencisinin TYT/AYT sınavına hazırlık sorusu:
Soru: "{question_text[:300] if question_text else ''}"
Konu: {question_topic or 'Bilinmiyor'}
Kategori: {category}

Bu soruya en uygun kısa YouTube video için şu JSON'u üret:
{{
  "category": "Matematik|Geometri|Fizik|Kimya|Biyoloji|Türk Dili ve Edebiyatı|Tarih|Coğrafya|Felsefe",
  "sub_topic": "Örn: Türev, İntegral, Newton, Hücre Bölünmesi vb.",
  "title": "TYT/AYT {kategori} – {konu} Sorusu (1 Dakikada Çözüm)"
}}
Sadece JSON döndür, başka hiçbir şey yazma.
"""
        resp = model.generate_content(prompt)
        text = resp.text.strip()
        import re as _re
        m = _re.search(r'\{.*\}', text, _re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return {"category": category, "sub_topic": question_topic, "title": None}




# ── YouTube Data API v3 Arama (Gerçek TYT/AYT videoları) ────────────────────
# Günlük 10.000 birim kotası var, her arama 100 birim kullanır → 100 arama/gün
# Sonuçlar 1 saat önbelleğe alınır, bu yüzden gerçekte çok az API çağrısı olur.

_YT_SEARCH_CACHE: dict = {}  # {cache_key: (timestamp, [video_list])}
_YT_CACHE_TTL = 3600          # 1 saat


def _youtube_search_tyt(query: str, max_results: int = 15) -> list:
    """
    YouTube Data API v3 ile TYT/AYT kısa video arar.
    - videoDuration=short  → 4 dakikadan kısa (1 dk'lık soru çözümleri için ideal)
    - videoEmbeddable=true → embed edilebilir videolar
    - regionCode=TR        → Türkiye içeriği öncelikli
    YOUTUBE_API_KEY yoksa boş liste döner.
    """
    api_key = os.getenv('YOUTUBE_API_KEY', '').strip()
    if not api_key:
        return []

    cache_key = f"{query}:{max_results}"
    cached = _YT_SEARCH_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _YT_CACHE_TTL:
        print(f"[YT Cache] Hit: {cache_key[:60]}")
        return cached[1]

    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "videoDuration": "short",    # 4 dk altı
                "videoEmbeddable": "true",
                "maxResults": max_results,
                "key": api_key,
                "relevanceLanguage": "tr",
                "regionCode": "TR",
                "safeSearch": "strict",
            },
            timeout=8,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        videos = [
            {
                "video_id": it["id"]["videoId"],
                "title": it["snippet"]["title"],
                "channel": it["snippet"]["channelTitle"],
            }
            for it in items
            if it.get("id", {}).get("videoId")
        ]
        _YT_SEARCH_CACHE[cache_key] = (time.time(), videos)
        print(f"[YT API] Found {len(videos)} videos for: {query[:60]}")
        return videos
    except Exception as e:
        print(f"[YT API Error] {e}")
        return []


def _build_tyt_search_query(category: str, sub_topic: str) -> str:
    """Kategori ve konuya göre YouTube arama sorgusu oluşturur."""
    # TYT için kısa arama kalıpları
    templates = [
        f"TYT {category} {sub_topic} soru çözümü",
        f"AYT {category} {sub_topic} 1 dakika soru",
        f"TYT {sub_topic} konu anlatımı soru",
        f"{category} TYT hızlı soru çözümü {sub_topic}",
    ]
    return random.choice(templates)


@app.route('/api/generate_shorts', methods=['POST'])
def api_generate_shorts():
    """
    Kullanıcının kendi TYT/AYT sorularına göre kişiselleştirilmiş
    '1 Dakikada Soru Çözümü' videoları döndürür.

    Öncelik sırası:
      1. YouTube Data API v3 → gerçek TYT/AYT kısa videoları
      2. Curated fallback pool → embed izinli eğitim videoları
    """
    import time as _time
    payload = request.get_json(silent=True) or {}
    requested_topic = payload.get('topic', 'Tümü').strip()

    chosen_category = requested_topic if requested_topic != 'Tümü' else 'Matematik'
    ai_title = None
    sub_topic = None

    # ── Oturum açık kullanıcı: Kişisel konu analizi ─────────────────────────
    if current_user.is_authenticated:
        priority_topics = _get_user_priority_topics(current_user.UserId)

        if requested_topic == 'Tümü' and priority_topics:
            chosen_category = random.choice(priority_topics[:3]) if len(priority_topics) >= 3 else priority_topics[0]
        elif requested_topic != 'Tümü':
            chosen_category = requested_topic

        # O kategoriden bir soru al, Gemini ile konu + başlık üret
        try:
            cat_obj = Category.query.filter(
                Category.Name.ilike(f'%{chosen_category}%')
            ).first()

            filter_args = [
                Question.UserId == current_user.UserId,
                Question.IsHidden == False,
            ]
            if cat_obj:
                filter_args.append(Question.CategoryId == cat_obj.CategoryId)

            ref_qs = (Question.query
                      .filter(*filter_args)
                      .order_by(Question.QuestionId.desc())
                      .limit(10).all())

            if ref_qs:
                ref_q = random.choice(ref_qs)
                ref_cat = ref_q.category.Name if ref_q.category else chosen_category

                gem = _gemini_pick_tyt_topic(
                    ref_q.content or '',
                    ref_q.topic or '',
                    ref_cat
                )
                chosen_category = gem.get("category", ref_cat)
                sub_topic = gem.get("sub_topic") or ref_q.topic or ref_cat
                ai_title = gem.get("title")
        except Exception as e:
            print(f"[Shorts] Topic resolve error: {e}")

    # ── 1. ÖNCE: YouTube API ile gerçek TYT videosu ara ─────────────────────
    st = sub_topic or chosen_category
    search_q = _build_tyt_search_query(chosen_category, st)
    yt_results = _youtube_search_tyt(search_q)

    video = None
    source = "curated"

    if yt_results:
        # Gerçek YouTube sonucunu kullan
        video = random.choice(yt_results)
        source = "youtube_api"
        if not ai_title:
            ai_title = f"TYT/AYT {chosen_category} – {st} (1 Dk)"
    else:
        # ── 2. FALLBACK: Curated pool ────────────────────────────────────────
        pool = TYT_POOL_MAP.get(chosen_category, TYT_POOL_MAP["Tümü"])
        video = random.choice(pool)
        if not ai_title:
            ai_title = f"TYT/AYT {chosen_category} – {st} (1 Dk Çözüm)"

    color = _COLOR_MAP.get(chosen_category, "#6C3AFA")

    return jsonify({
        "success": True,
        "data": {
            "video_id": video["video_id"],
            "title": ai_title,
            "topic": chosen_category,
            "sub_topic": st,
            "color": color,
            "exam_type": "TYT/AYT",
            "source": source,  # debug için
        }
    })



@app.route('/api/generate', methods=['POST'])
@login_required
def generate_ai_question():
    payload = request.get_json(silent=True) or {}
    original_text = payload.get('question_text', '').strip()
    if not original_text:
        return jsonify({"error": "Soru metni gerekli."}), 400
    
    results = _generate_similar_questions_gemini(original_text, count=1)
    if not results:
        return jsonify({"error": "AI soru uretemedi."}), 500
        
    return jsonify({"generated": results[0]})

@app.route('/api/shorts/upload', methods=['POST'])
def upload_ai_short_question():
    question_text = request.form.get('question_text', '').strip()
    file = request.files.get('question_image')

    if not question_text and (file is None or not file.filename):
        return jsonify({"error": "Lutfen metin veya gorsel soru ekleyin."}), 400

    uploaded_image_url = None
    if file and file.filename:
        safe_name = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        save_path = os.path.join(SHORTS_UPLOAD_DIR, unique_name)
        file.save(save_path)
        uploaded_image_url = url_for('static', filename=f'uploads/shorts/{unique_name}')

    basis_text = question_text if question_text else (file.filename if file else "")
    subject, topic = _detect_subject_topic(basis_text)
    difficulty = _estimate_difficulty(basis_text)
    steps = _generate_solution_steps(subject, topic, difficulty)
    
    # Birden fazla benzer soru uretelim
    similar_data = _generate_similar_questions(subject, topic, difficulty, question_text, count=3)

    new_videos = []
    for item in similar_data:
        new_video = {
            "id": uuid.uuid4().hex,
            "questionText": item["questionText"],
            "sourceQuestionText": question_text if question_text else "Gorsel soru yüklendi",
            "questionImage": None,
            "sourceQuestionImage": uploaded_image_url,
            "subject": subject,
            "topic": topic,
            "difficulty": difficulty,
            "thinkingPauseMs": random.randint(1200, 2500),
            "steps": item["steps"],
            "finalAnswer": item["finalAnswer"],
            "voiceoverText": item["voiceover"],
            "voiceoverReady": True,
            "likes": 0,
            "bookmarked": False,
            "repeatAdded": False,
            "createdAt": datetime.utcnow().isoformat(),
        }
        AI_SHORTS_STORE.insert(0, new_video)
        new_videos.append(new_video)

    return jsonify({"video": new_videos[0], "all_generated": new_videos})

@app.route('/api/shorts/<video_id>/action', methods=['POST'])
def update_ai_short_action(video_id):
    payload = request.get_json(silent=True) or {}
    action = payload.get('action')
    video = next((v for v in AI_SHORTS_STORE if v["id"] == video_id), None)
    if not video:
        return jsonify({"error": "Video bulunamadi."}), 404

    if action == 'like':
        video["likes"] += 1
    elif action == 'bookmark':
        video["bookmarked"] = not video["bookmarked"]
    elif action == 'repeat':
        video["repeatAdded"] = not video["repeatAdded"]
    else:
        return jsonify({"error": "Gecersiz aksiyon."}), 400

    return jsonify({"video": video})

@app.route('/logo.png')
def logo_image():
    # Browser'da `file:///...` engellenebildiği için, görseli HTTP üzerinden servis ediyoruz.
    temp_logo_path = r"C:\Users\kevse\AppData\Local\Temp\62978a70-5105-4047-aff6-80614bd1c953_stitch_advanced_study_question_tracker.zip.953\screen.png"
    if os.path.exists(temp_logo_path):
        return send_file(temp_logo_path, mimetype='image/png')

    # Temp görseli silinmişse, statik klasördeki fallback'i göster.
    fallback_logo_path = os.path.join(app.root_path, 'static', 'uploads', '20260427_215602_logo.png')
    if os.path.exists(fallback_logo_path):
        return send_file(fallback_logo_path, mimetype='image/png')

    return ("Logo bulunamadı.", 404)

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/support')
def support():
    return render_template('support.html')

@app.route('/research')
def research():
    return render_template('research.html')

@app.route('/notifications')
@login_required
def notifications():
    today = datetime.now().date()
    now = datetime.now()

    # Bugünün Soruları
    today_questions = Question.query.filter(
        Question.UserId == current_user.UserId,
        Question.IsCompleted == False,
        Question.IsHidden == False,
        (
            (Question.RepeatCount == 0) & (db.func.cast(Question.Repeat1Date, db.Date) == today)
            |
            (Question.RepeatCount == 1) & (db.func.cast(Question.Repeat2Date, db.Date) == today)
            |
            (Question.RepeatCount == 2) & (db.func.cast(Question.Repeat3Date, db.Date) == today)
        )
    ).all()

    # Geçmiş Sorular
    past_questions = Question.query.filter(
        Question.UserId == current_user.UserId,
        Question.IsCompleted == False,
        Question.RepeatCount < 3,
        (
            (Question.RepeatCount == 0) & (db.func.cast(Question.Repeat1Date, db.Date) < today)
            |
            (Question.RepeatCount == 1) & (db.func.cast(Question.Repeat2Date, db.Date) < today)
            |
            (Question.RepeatCount == 2) & (db.func.cast(Question.Repeat3Date, db.Date) < today)
        )
    ).order_by(Question.Repeat1Date.desc()).all()

    # Eğer mobil uygulama JSON istiyorsa
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        def question_to_dict(q):
            return {
                "id": q.QuestionId,
                "content": q.content,
                "topic": q.topic,
                "category": q.category.Name if q.category else "Genel",
                "difficulty": q.difficulty,
                "image": q.ImagePath or q.PhotoPath,
                "repeat_count": q.RepeatCount,
                "created_at": q.created_at.strftime('%d.%m.%Y') if q.created_at else None
            }
        
        return jsonify({
            "success": True,
            "today_questions": [question_to_dict(q) for q in today_questions],
            "past_questions": [question_to_dict(q) for q in past_questions]
        })
    
    # --- Web için devam eden geri kalan kodlar ---

    # Görev Bildirimleri için verileri çek
    # Vade tarihi geçmiş ve tamamlanmamış görevler
    overdue_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.DueDate < now,
        Task.Status != 'completed'
    ).all()

    # Bugüne ait görevler (vade tarihi bugün olan ve tamamlanmamış)
    today_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.DueDate >= today,
        Task.DueDate < today + timedelta(days=1),
        Task.Status != 'completed'
    ).all()

    # Kitap Bildirimleri için verileri çek
    reading_books = Book.query.filter(
        Book.UserId == current_user.UserId,
        Book.IsCompleted == False
    ).all()

    # Listening Bildirimleri için verileri çek
    reading_listenings = Listening.query.filter(
        Listening.UserId == current_user.UserId,
        Listening.IsCompleted == False
    ).all()

    # Haftalık Performans Analizi için dinamik hesaplama
    pending_count = len(today_questions) + len(past_questions)
    total_questions = Question.query.filter_by(UserId=current_user.UserId, IsHidden=False).count()
    
    if total_questions > 0:
        completion_rate = int(((total_questions - pending_count) / total_questions) * 100)
    else:
        completion_rate = 100

    if completion_rate >= 90:
        performance_grade = 'A+'
    elif completion_rate >= 80:
        performance_grade = 'A'
    elif completion_rate >= 70:
        performance_grade = 'B'
    elif completion_rate >= 50:
        performance_grade = 'C'
    else:
        performance_grade = 'D'

    return render_template(
        'notifications.html',
        today_questions=today_questions,
        past_questions=past_questions,
        overdue_tasks=overdue_tasks,
        today_tasks=today_tasks,
        reading_books=reading_books,
        reading_listenings=reading_listenings,
        completion_rate=completion_rate,
        performance_grade=performance_grade,
        section='takipsistemi',
        show_sidebar=True
    )

@app.route('/mark_notification_read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    # ... existing code ...
    pass

@app.route('/today_questions')
@csrf.exempt
@login_required
def today_questions():
    today = datetime.now().date()
    
    # 1. Henüz çözülmemiş, bugün vadesi gelmiş sorular (sadece bugünün tarihi)
    questions = Question.query.filter(
        Question.UserId == current_user.UserId,
        Question.IsCompleted == False,
        Question.IsHidden == False,
        db.or_(
            db.and_(Question.RepeatCount == 0, db.cast(Question.Repeat1Date, db.Date) == today),
            db.and_(Question.RepeatCount == 1, db.cast(Question.Repeat2Date, db.Date) == today),
            db.and_(Question.RepeatCount == 2, db.cast(Question.Repeat3Date, db.Date) == today)
        )
    ).all()

    # 2. Bugün zaten çözülmüş (tekrarı ilerletilmiş) soruları say
    # Tekrar tarihi bugün olan ve RepeatCount'u artmış soruları buluyoruz
    solved_today_count = Question.query.filter(
        Question.UserId == current_user.UserId,
        db.or_(
            db.and_(Question.RepeatCount == 1, db.cast(Question.Repeat1Date, db.Date) == today),
            db.and_(Question.RepeatCount == 2, db.cast(Question.Repeat2Date, db.Date) == today),
            db.and_(Question.RepeatCount == 3, db.cast(Question.Repeat3Date, db.Date) == today)
        )
    ).count()

    return render_template('today_questions.html', 
                           questions=questions, 
                           solved_today=solved_today_count,
                           active_page='today_questions')

@app.route('/past_questions')
def past_questions():
    print(f"DEBUG: /past_questions request headers: {request.headers}")
    print(f"DEBUG: /past_questions current_user authenticated: {current_user.is_authenticated}")
    if not current_user.is_authenticated:
        if request.is_json or 'application/json' in request.headers.get('Accept', ''):
            return jsonify({"success": False, "message": "Oturum açmanız gerekiyor."}), 401
        return redirect(url_for('login'))
    today = datetime.now().date()
    # Tekrar tarihi bugün veya öncesi olup, tekrar tarihi gününde tamamlanmamış sorular
    questions = Question.query.filter(
        Question.UserId == current_user.UserId,
        Question.IsCompleted == False,
        Question.RepeatCount < 3,
        (
            (Question.RepeatCount == 0) & (db.func.cast(Question.Repeat1Date, db.Date) < today)
            |
            (Question.RepeatCount == 1) & (db.func.cast(Question.Repeat2Date, db.Date) < today)
            |
            (Question.RepeatCount == 2) & (db.func.cast(Question.Repeat3Date, db.Date) < today)
        )
    ).order_by(Question.Repeat1Date.desc()).all()
    # Eğer mobil uygulama JSON istiyorsa
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        def question_to_dict(q):
            # Gecikme süresini hesapla
            delay_days = (today - q.Repeat1Date.date()).days if q.RepeatCount == 0 else \
                         (today - q.Repeat2Date.date()).days if q.RepeatCount == 1 else \
                         (today - q.Repeat3Date.date()).days if q.RepeatCount == 2 else 0
            
            return {
                "id": q.QuestionId,
                "content": q.content,
                "topic": q.topic,
                "category": q.category.Name if q.category else "Genel",
                "difficulty": q.difficulty,
                "image": q.ImagePath or q.PhotoPath,
                "repeat_count": q.RepeatCount,
                "created_at": q.created_at.strftime('%d.%m.%Y') if q.created_at else "Bilinmiyor",
                "delay_days": delay_days
            }
        
        return jsonify({
            "success": True,
            "questions": [question_to_dict(q) for q in questions]
        })

    categories = Category.query.all()
    return render_template('past_questions.html', questions=questions, categories=categories, section='takipsistemi', show_sidebar=True)

@app.route('/reminders')
@login_required
def reminders():
    today = datetime.now().date()
    questions = Question.query.filter(
        Question.UserId == current_user.UserId,
        db.text("CAST([Questions].[Repeat1Date] AS DATE) > :today"),
        Question.IsCompleted == False,
        Question.RepeatCount < 3
    ).params(today=today).order_by(Question.Repeat1Date).all()
    
    categories = Category.query.all()
    return render_template('reminders.html', questions=questions, categories=categories, section='takipsistemi', show_sidebar=True)

@app.route('/set_reminder/<int:question_id>', methods=['POST'])
# ... existing code ...

@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('welcome'))
    
    from datetime import datetime, timedelta
    
    # 1. Genel İstatistikler
    total_q = Question.query.filter_by(UserId=current_user.UserId).count()
    completed_q = Question.query.filter_by(UserId=current_user.UserId, IsCompleted=True).count()
    accuracy = round((completed_q / total_q * 100), 1) if total_q > 0 else 0
    
    # 2. Sınav Geri Sayımı (YKS 2026 - 20 Haziran 10:15)
    exam_date = datetime(2026, 6, 20, 10, 15)
    now = datetime.now()
    diff = exam_date - now
    days_left = (exam_date.date() - now.date()).days
    countdown = {
        'days': max(0, days_left),
        'hours': max(0, diff.seconds // 3600) if diff.total_seconds() > 0 else 0,
        'mins': max(0, (diff.seconds // 60) % 60) if diff.total_seconds() > 0 else 0
    }

    # 3. Haftalık Aktivite (Son 7 gün)
    from sqlalchemy import func
    activity_data = db.session.query(
        func.cast(Question.created_at, db.Date).label('date'),
        func.count('*').label('count')
    ).filter(
        Question.UserId == current_user.UserId,
        Question.created_at >= (datetime.now() - timedelta(days=7))
    ).group_by(func.cast(Question.created_at, db.Date)).all()
    
    days_map = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']
    weekly_activity = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).date()
        day_name = days_map[d.weekday()]
        count = next((act.count for act in activity_data if act.date == d), 0)
        weekly_activity.append({'day': day_name, 'count': count})

    categories = Category.query.all()
    for category in categories:
        category.question_count = Question.query.filter_by(
            UserId=current_user.UserId,
            CategoryId=category.CategoryId,
            IsHidden=False
        ).count()
        
    recent_questions = Question.query.filter_by(UserId=current_user.UserId).order_by(Question.created_at.desc()).limit(5).all()
    
    # Günlük Motivasyon Sözleri
    motivation_messages = [
        "Başarı, her gün tekrarlanan küçük adımların toplamıdır.",
        "Zorluklar seni yıldırmasın; onlar seni güçlendiren basamaklardır.",
        "Bugün atacağın her küçük adım, yarınki büyük başarına açılan kapıdır.",
        "Kendine inan! Zihninde başardığın her şey, gerçeklikte de mümkün olur.",
        "Umutla başla, inançla devam et, azimle bitir.",
        "Geleceğini bugünden inşa ediyorsun, çalışmaya devam et!",
        "Zorlandığın anlar, sınırlarını aştığın ve geliştiğin anlardır.",
        "Başarı hedefe ulaşmak değil, o yolda vazgeçmeden ilerlemektir."
    ]
    motivation_message = random.choice(motivation_messages)
    
    return render_template('index.html', 
                           total_questions=total_q,
                           completed_questions=completed_q,
                           accuracy=accuracy,
                           countdown=countdown,
                           weekly_activity=weekly_activity,
                           categories=categories,
                           recent_questions=recent_questions,
                           motivation_message=motivation_message)

    # Okunan kitap sayısı (mevcut index verisi)
    books_count = Book.query.filter_by(
        UserId=current_user.UserId
    ).count()

    # İzlenen TEDx sayısı (mevcut index verisi)
    ted_talks_count = TedTalk.query.filter_by(
        UserId=current_user.UserId
    ).count()

    # Aktif görev sayısı (mevcut index verisi)
    tasks_count = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status.in_(['new', 'pending'])
    ).count()


    # Motivasyon mesajları (hem eski index hem de questions verisi)
    motivation_messages = [
        "Başarı, küçük adımların toplamıdır!",
        "Her gün bir adım daha ileriye!",
        "Zorlandığında vazgeçme, mola ver ve devam et!",
        "Küçük adımlar büyük başarılar getirir!",
        "Bugün dünden daha iyi ol!",
        "Başarı yolunda ilerliyorsun!",
        "Kendine inan, başarabilirsin!",
        "Her tekrar seni hedefe yaklaştırır!"
    ]
    motivation_message = random.choice(motivation_messages)

    # Kategorileri ve her kategorinin soru sayısını getir
    categories = Category.query.filter(Category.Name != 'İngilizce').all()
    for category in categories:
        category.question_count = Question.query.filter_by(
            UserId=current_user.UserId,
            CategoryId=category.CategoryId,
            IsHidden=False
        ).count()

    # --- Son Aktiviteler İçin Veri Hazırlığı ---
    today = datetime.now().date()
    yesterday = datetime.now() - timedelta(days=1)
    last_7_days = datetime.now() - timedelta(days=7)

    notifications = []

    # 1. Bugünün Soruları
    today_questions_count = Question.query.filter(
        Question.UserId == current_user.UserId,
        Question.IsCompleted == False,
        Question.IsHidden == False,
        or_(
            and_(Question.Repeat1Date != None, db.func.cast(Question.Repeat1Date, db.Date) == today),
            and_(Question.Repeat2Date != None, db.func.cast(Question.Repeat2Date, db.Date) == today),
            and_(Question.Repeat3Date != None, db.func.cast(Question.Repeat3Date, db.Date) == today)
        )
    ).count()
    if today_questions_count > 0:
        notifications.append({
            'icon': 'fas fa-clock',
            'color_class': 'blue', # Renk sınıfı
            'type': 'Bugünün Soruları',
            'msg': f'{today_questions_count} soru çözülmeyi bekliyor',
            'timestamp': None,
        })

    # 2. Görev Tamamlandı (Son 24 saat)
    completed_tasks_last_24h = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed',
        Task.CompletedAt >= yesterday
    ).count()
    if completed_tasks_last_24h > 0:
         notifications.append({
             'icon': 'fas fa-check-circle',
             'color_class': 'green', # Renk sınıfı
             'type': 'Görev Tamamlandı',
             'msg': f'Son 24 saatte tamamlanan {completed_tasks_last_24h} görev',
             'timestamp': None, # İsteğe bağlı olarak son tamamlanma zamanı eklenebilir
         })

    # 3. Yeni Kitap Eklendi (Son 7 gün)
    new_books_last_7_days = Book.query.filter(
        Book.UserId == current_user.UserId,
        Book.StartDate >= last_7_days
    ).count()
    # Bu bölümde kitap bildirimi ekleniyordu, artık tamamen kaldırıldı.

    # 4. Başarı Kazanıldı (Örnek Statik Mesaj)
    # Gerçek bir başarı sistemi olmadığından statik bir mesaj ekliyorum.
    notifications.append({
        'icon': 'fas fa-star',
        'color_class': 'yellow', # Renk sınıfı
        'type': 'Başarı Kazanıldı',
        'msg': 'Düzenli çalışma için +5 puan',
        'timestamp': None,
    })

    # --- Şablonu Render Et ---
    return render_template('index.html',
                         daily_questions_count=daily_questions_count,
                         total_questions_count=total_questions_count,
                         books_count=books_count,
                         ted_talks_count=ted_talks_count,
                         tasks_count=tasks_count,
                         motivation_message=motivation_message,
                         categories=categories,
                         notifications=notifications, # Yeni eklenen bildirim listesi
                         section='takipsistemi',
                         show_sidebar=True
                         )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('welcome_options'))

    if request.method == 'POST':
        try:
            # Form verilerini al
            username = request.form.get('username')
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')
            first_name = request.form.get('name')
            last_name = request.form.get('surname')
            email = request.form.get('email')
            class_level = request.form.get('class_level')
            year_of_birth = request.form.get('year_of_birth')
            area = request.form.get('area')
            aim = request.form.get('aim')
            security_question = request.form.get('security_question')
            security_answer = request.form.get('security_answer')

            # Zorunlu alanları kontrol et
            if not all([username, password, first_name, last_name, email, class_level, year_of_birth, area, aim, security_question, security_answer]):
                flash('Lütfen tüm zorunlu alanları doldurun.', 'error')
                return redirect(url_for('register'))

            # Kullanıcı adı kontrolü
            if User.query.filter_by(UserName=username).first():
                flash('Bu kullanıcı adı zaten kullanılıyor.', 'error')
                return redirect(url_for('register'))

            # E-posta kontrolü
            if User.query.filter_by(Email=email).first():
                flash('Bu e-posta adresi zaten kullanılıyor.', 'error')
                return redirect(url_for('register'))

            # Şifre kontrolü
            if password != confirm_password:
                flash('Şifreler eşleşmiyor.', 'error')
                return redirect(url_for('register'))

            # Şifreyi hashle
            password_hash = hashlib.sha256(password.encode()).hexdigest()

            # Yeni kullanıcı oluştur
            new_user = User(
                UserName=username,
                PasswordHash=password_hash,
                Name=first_name,
                Surname=last_name,
                Email=email,
                Class=class_level,
                YearOfBirth=int(year_of_birth),
                Area=area,
                Aim=aim,
                SecurityQuestion=security_question,
                SecurityAnswer=security_answer
            )

            # Veritabanına kaydet
            db.session.add(new_user)
            db.session.commit()

            flash('Kayıt başarılı! Şimdi giriş yapabilirsiniz.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            db.session.rollback()
            print(f"Kayıt hatası: {str(e)}")  # Hata logla
            flash('Kayıt sırasında bir hata oluştu. Lütfen tekrar deneyin.', 'error')
            return redirect(url_for('register'))

    return render_template('register.html', show_sidebar=False)

@app.route('/api/social_login', methods=['POST'])
@csrf.exempt
def api_social_login():
    try:
        data = request.get_json()
        print(f"DEBUG: Social login request data: {data}")
        if not data:
            return jsonify({'success': False, 'error': 'Veri alınamadı'}), 400
            
        provider = data.get('provider')
        token = data.get('token') # Mobilden gelen Google ID Token
        email = data.get('email')
        name = data.get('name', 'Sosyal Kullanıcı')
        
        # Google Token Doğrulaması
        if provider == 'Google' and token:
            print(f"DEBUG: Verifying Google token...")
            # Google'ın doğrulama endpoint'ine soruyoruz
            verify_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={token}"
            response = requests.get(verify_url)
            
            if response.status_code == 200:
                google_data = response.json()
                email = google_data.get('email')
                name = google_data.get('name', google_data.get('given_name', name))
                print(f"DEBUG: Google token verified for {email}")
            else:
                print(f"ERROR: Google token verification failed: {response.text}")
                return jsonify({'success': False, 'error': 'Geçersiz Google oturumu'}), 401
        
        if not email:
            return jsonify({'success': False, 'error': 'Email bilgisi alınamadı'}), 400
            
        user = User.query.filter_by(Email=email).first()
        print(f"DEBUG: Existing user check for {email}: {'Found' if user else 'Not Found'}")
        
        if not user:
            print(f"DEBUG: Creating new user for {email}")
            username = email.split('@')[0]
            # Kullanıcı adı çakışması kontrolü
            existing_user = User.query.filter_by(UserName=username).first()
            if existing_user:
                username = f"{username}_{random.randint(100, 999)}"
            
            # Username length check (max 50)
            if len(username) > 50:
                username = username[:46] + str(random.randint(1000, 9999))

            print(f"DEBUG: Assigned username: {username}")
                
            user = User(
                UserName=username,
                Email=email,
                Name=name,
                Surname='Soyadı Belirtilmemiş',
                Class='Belirtilmemiş',
                YearOfBirth=2000,
                Area='Belirtilmemiş',
                Aim='Eğitim',
                PhoneNumber='0000000000',
                SecurityQuestion='Sosyal Giriş',
                SecurityAnswer='Sosyal Giriş',
                # Sosyal girişlerde şifre rastgele atanır, kullanıcı şifreyle giriş yapamaz
                PasswordHash=generate_password_hash(os.urandom(24).hex())
            )
            db.session.add(user)
            db.session.commit()
            print(f"DEBUG: New user created successfully: {user.UserId}")
            
        login_user(user, remember=True)
        print(f"DEBUG: Login success for social user: {user.UserName}")
        return jsonify({
            'success': True,
            'message': f'{provider} ile giriş başarılı',
            'user': {
                'id': user.UserId,
                'username': user.UserName,
                'email': user.Email
            }
        })
    except Exception as e:
        print(f"ERROR: Social login failed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/login', methods=['GET', 'POST'])
@csrf.exempt
def login():
    if current_user.is_authenticated:
        if request.is_json or 'application/json' in request.headers.get('Accept', ''):
            return jsonify({"success": True, "message": "Zaten giriş yapılmış"})
        return redirect(url_for('welcome_options'))

    if request.method == 'POST':
        # JSON isteği (Mobil) veya Form isteği (Web) kontrolü
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        elif 'application/json' in request.headers.get('Accept', ''):
            # Accept header'ı JSON ama Content-Type değilse (bazı mobil durumlarda)
            data = request.get_json(force=True, silent=True) or {}
            username = data.get('username') or request.form.get('username')
            password = data.get('password') or request.form.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')
            
        remember = request.form.get('remember') if not request.is_json else False
        user = User.query.filter_by(UserName=username).first()
        print(f"DEBUG: Login attempt for username: {username}")
        if not user:
            print(f"DEBUG: User not found: {username}")
        
        if user and user.PasswordHash == hashlib.sha256(password.encode()).hexdigest():
            login_user(user, remember=True)
            session.permanent = True
            print(f"DEBUG: Login success for user: {username}")
            if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({
                    "success": True, 
                    "message": "Giriş başarılı",
                    "user": {
                        "id": user.UserId,
                        "name": user.Name,
                        "username": user.UserName
                    }
                })
            flash('Başarıyla giriş yaptınız!', 'success')
            return redirect(url_for('welcome_options'))
        else:
            if user:
                print(f"DEBUG: Password mismatch for user: {username}")
            if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({"success": False, "message": "Geçersiz kullanıcı adı veya şifre"}), 401
            flash('Geçersiz kullanıcı adı veya şifre', 'danger')
    return render_template('login.html', show_sidebar=False)

@app.route('/welcome_options') # New route for the welcome options page
@login_required
def welcome_options():
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({"success": True, "message": "Hoş geldiniz"})
    return render_template('welcome_options.html', show_sidebar=False)

@app.route('/welcome_after_login')
@login_required
def welcome_after_login():
    return redirect(url_for('welcome_options'))

@app.route('/hedefleyici')
@csrf.exempt
@login_required
def hedefleyici():
    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())
    
    # İstatistikler
    total_questions = Question.query.filter_by(UserId=current_user.UserId, IsHidden=False).count()
    completed_questions = Question.query.filter_by(UserId=current_user.UserId, IsCompleted=True, IsHidden=False).count()
    
    completed_tasks = Task.query.filter_by(UserId=current_user.UserId, Status='completed').count()
    total_tasks = Task.query.filter_by(UserId=current_user.UserId).count()
    
    total_items = total_questions + total_tasks
    completed_items = completed_questions + completed_tasks
    success_rate = int((completed_items / total_items * 100)) if total_items > 0 else 0
    
    # Kategorilere Göre Performans
    categories = Category.query.all()
    category_stats = []
    for cat in categories:
        q_count = Question.query.filter_by(UserId=current_user.UserId, CategoryId=cat.CategoryId, IsHidden=False).count()
        if q_count > 0:
            c_count = Question.query.filter_by(UserId=current_user.UserId, CategoryId=cat.CategoryId, IsCompleted=True, IsHidden=False).count()
            rate = int((c_count / q_count) * 100)
            category_stats.append({
                'name': cat.Name,
                'total': q_count,
                'completed': c_count,
                'rate': rate
            })
    category_stats.sort(key=lambda x: x['total'], reverse=True)
    all_categories = category_stats # İlk 4 sınırlamasını kaldırıyoruz
    
    # Haftalık Görevler
    tasks_this_week = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed',
        Task.CompletedAt >= start_of_week
    ).count()
    
    # Aktiviteler
    recent_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed'
    ).order_by(Task.CompletedAt.desc()).limit(5).all()
    
    activities = []
    for t in recent_tasks:
        activities.append({
            'title': t.Title,
            'subject': t.Category or 'Genel',
            'date': t.CompletedAt.strftime('%d %b, %H:%M') if t.CompletedAt else 'Bilinmiyor',
            'status': 'Tamamlandı'
        })

    # --- Sistem Önerileri Analizi ---
    recommendations = []
    
    # 1. Çözülemeyen (Zayıf) Konular Analizi
    failed_questions = Question.query.filter(
        Question.UserId == current_user.UserId,
        Question.FailedAttempts > 0
    ).all()
    
    weak_topics = {}
    for q in failed_questions:
        topic_key = q.topic or "Genel"
        weak_topics[topic_key] = weak_topics.get(topic_key, 0) + q.FailedAttempts
    
    # En çok hata yapılan ilk 3 konu
    sorted_weak = sorted(weak_topics.items(), key=lambda x: x[1], reverse=True)[:3]
    for topic, count in sorted_weak:
        recommendations.append({
            'type': 'warning',
            'icon': 'trending_down',
            'title': f'Zayıf Konu: {topic}',
            'desc': f'Bu konuda {count} kez hata yaptın. Konu anlatım videolarına göz atmanı öneririz.'
        })

    # 2. Geciken ve Bugün Bekleyen Tekrarlar (Gerçek Veri)
    overdue_count = Question.query.filter(
        Question.UserId == current_user.UserId,
        Question.IsCompleted == False,
        Question.IsHidden == False,
        db.or_(
            db.and_(Question.RepeatCount == 0, db.cast(Question.Repeat1Date, db.Date) <= today),
            db.and_(Question.RepeatCount == 1, db.cast(Question.Repeat2Date, db.Date) <= today),
            db.and_(Question.RepeatCount == 2, db.cast(Question.Repeat3Date, db.Date) <= today)
        )
    ).count()

    if overdue_count > 0:
        recommendations.append({
            'type': 'danger',
            'icon': 'running_with_errors',
            'title': 'Aksiyon Bekliyor',
            'desc': f'Şu an çözmen gereken {overdue_count} soru birikmiş durumda. Hafızanı tazelemek için harika bir vakit!'
        })

    # 3. Pozitif Geri Bildirim (Başarı Analizi)
    strong_topics = [s for s in all_categories if s['rate'] >= 80 and s['total'] >= 3]
    for strong in strong_topics[:2]: # En iyi 2 konuyu seç
        recommendations.append({
            'type': 'success',
            'icon': 'verified',
            'title': f'Harika: {strong["name"]}',
            'desc': f'Bu konuyu gerçekten anlamış görünüyorsun! Başarı oranın %{strong["rate"]}. Böyle devam et!'
        })

    # Eğer mobil uygulama JSON istiyorsa
    if request.is_json or request.args.get('format') == 'json' or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({
            "success": True,
            "stats": {
                "total_questions": total_questions,
                "completed_questions": completed_questions,
                "success_rate": success_rate,
                "completed_tasks": completed_tasks,
                "tasks_this_week": tasks_this_week,
                "questions_this_week": completed_questions
            },
            "categories": all_categories,
            "activities": activities,
            "recommendations": recommendations
        })

    # 4. Genel Motivasyon / İlerleme
    if success_rate > 80:
        recommendations.append({
            'type': 'success',
            'icon': 'emoji_events',
            'title': 'Zirvedesin!',
            'desc': 'Genel başarı oranınız çok yüksek. Yeni ve daha zorlu hedefler belirlemeye hazırsın.'
        })
    elif total_questions < 5:
        recommendations.append({
            'type': 'info',
            'icon': 'add_circle',
            'title': 'Soru Havuzunu Genişlet',
            'desc': 'Soru havuzuna ne kadar çok soru eklersen, AI seni o kadar iyi tanır ve geliştirir.'
        })

    return render_template('hedefleyici.html', 
                           section='hedefleyici',
                           total_questions=total_questions,
                           completed_questions=completed_questions,
                           completed_tasks=completed_tasks,
                           success_rate=success_rate,
                           top_categories=all_categories, # İsmi top_categories bıraktım template bozulmasın diye
                           tasks_this_week=tasks_this_week,
                           activities=activities,
                           recommendations=recommendations)

@app.route('/kitaplarim')
@login_required
def kitaplarim():
    books = Book.query.filter_by(UserId=current_user.UserId).all()
    return render_template('kitaplarim.html', books=books, section='hedefleyici')

@app.route('/gorevlerim')
@login_required
def gorevlerim():
    filter_type = request.args.get('filter', 'all')
    now = datetime.now()
    # Aktif görevler
    active_tasks = Task.query.filter(Task.UserId == current_user.UserId, Task.Status.in_(['new', 'pending'])).filter(Task.Title != 'Serbest Çalışma').order_by(Task.DueDate).all()
    # Son tamamlanan görevler
    completed_tasks = Task.query.filter_by(UserId=current_user.UserId, Status='completed').filter(Task.Title != 'Serbest Çalışma').order_by(Task.CompletedAt.desc()).all()
    # 24 saatten eski tamamlananları filtrele
    if filter_type == 'completed':
        completed_tasks = [t for t in completed_tasks if t.CompletedAt and (now - t.CompletedAt) <= timedelta(hours=24)]
    if filter_type == 'completed':
        tasks = completed_tasks
    else:
        tasks = active_tasks
    
    # --- Günlük Rapor Verilerini Çek ---
    today = datetime.now().date()
    # Tamamlanan görevler (bugün tamamlananlar)
    completed_tasks_report = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed',
        db.text("CAST([Tasks].[CompletedAt] AS DATE) = :today")
    ).params(today=today).all()
    # Gecikmiş görevler (Status in ['new', 'pending'] ve DueDate < now)
    overdue_tasks_report = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status.in_(['new', 'pending']),
        Task.DueDate < datetime.now()
    ).all()

    # Toplam çalışma süresi (görev türü fark etmeksizin, o günün tüm TaskTime kayıtları)
    # Not: TaskTime modelinin app.py'de tanımlı olması gerekir.
    # TaskTime import edildiğinden emin olun.
    try:
        total_time = db.session.query(db.func.sum(TaskTime.Duration)).join(Task).filter(
            Task.UserId == current_user.UserId,
            db.text("CAST([TaskTimes].[StartTime] AS DATE) = :today")
        ).params(today=today).scalar() or 0
    except: # Eğer TaskTime veya ilişki bulunamazsa hata olmaması için
         total_time = 0

    # Pomodoro süreleri (Serbest Çalışma görevlerinden)
    try:
        pomodoro_time = db.session.query(db.func.sum(TaskTime.Duration)).join(Task).filter(
            Task.UserId == current_user.UserId,
            Task.Title == 'Serbest Çalışma',
            db.text("CAST([TaskTimes].[StartTime] AS DATE) = :today")
        ).params(today=today).scalar() or 0
    except: # Eğer TaskTime veya ilişki bulunamazsa hata olmaması için
        pomodoro_time = 0

    total_tasks_for_rate = len(completed_tasks_report) + len(overdue_tasks_report)
    completion_rate = int((len(completed_tasks_report) / total_tasks_for_rate) * 100) if total_tasks_for_rate > 0 else 0

    # --- Şablonu Render Et ---
    return render_template(
        'gorevlerim.html',
        active_tasks=active_tasks,
        completed_tasks=completed_tasks, # Son 24 saatlik
        tasks=tasks,
        filter=filter_type,
        section='hedefleyici',
        now=now,
        active_page='today_questions'
    )

@app.route('/timer')
@login_required
def timer():
    active_task = Task.query.filter(Task.UserId == current_user.UserId, Task.Status.in_(['new', 'pending'])).order_by(Task.DueDate).first()
    completed_task = Task.query.filter_by(UserId=current_user.UserId, Status='completed').order_by(Task.CompletedAt.desc()).first()
    
    # Geçmiş Pomodoro oturumlarını çek
    pomodoro_history = PomodoroSession.query.filter_by(UserId=current_user.UserId, Type='pomodoro')\
                        .order_by(PomodoroSession.CreatedAt.desc()).limit(10).all()
    
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({
            "success": True,
            "active_task": {
                "id": active_task.TaskId,
                "title": active_task.Title,
                "category": active_task.Category or "Genel"
            } if active_task else None,
            "completed_task": {
                "id": completed_task.TaskId,
                "title": completed_task.Title
            } if completed_task else None,
            "pomodoro_history": [{
                "id": p.SessionId,
                "duration": p.Duration,
                "created_at": p.CreatedAt.strftime('%d.%m.%Y %H:%M') if p.CreatedAt else None
            } for p in pomodoro_history]
        })


    return render_template('timer.html', 
                           active_task=active_task, 
                           completed_task=completed_task,
                           pomodoro_history=pomodoro_history,
                           active_page='timer')

# Listening video linkleri (YouTube video ID'leri)
LISTENING_VIDEO_IDS = [
    'we4KiShNjlA', '26PrgjTboVQ', '2USh8OmgiJE', 'Y681hXWwhQY', 'wkjSBC-_bDA', 'FZDImEiPgMk',
    'g8q-Nq-ajx8', '1iHeeMlOsyc', 'HZd53TJpmoQ', 'JjESWHykTJQ', '5R3WdBE1-JM', 'zsOnAHAY6to',
    'fG7dJ6A3l7w', 'Mqnlb_yj3bY', 'Joc4kJ4M1Bk', 'oTPZWpQ9pbA', '7F1iJZr-p4E', '_5siHrpPnmw',
    'uxtXEuK05-w', 'j8d5kkKfDbo', 'FKwmUNffu7M', 'DsQMLrPdLf8', 'V2eW5jGQe8I', 'qoNRZKgLDhg',
    'vq2x7k_nofw', 'KkrhHUeMjIU', 'h_pvijqmolQ', 'xy27CfuFtJE', 'R_0E8HBxYN8', 'iKzpnVWdZ70',
    'mpxwlItsDA8', 'u6QrbYDsj1g', '7BIp53who2A', 'KLz5u2pH-yM', 'ybQORSQWWdc', '4YHtcINPkjM',
    'UIg6n0ypaHw', 'vP3VOKBcloo', 'TVHePsQLa3w', 'FjU9qyTZ_OU', 'WjFQIP8w5Jw', 'p0SUyXLS-ME',
    'j2PdEQpu5js', 'xGhbhWUqL-w', 's1HxJVusR2w', '3hwEplr-g5w', 'Kmc7TtKkTs4', 'Y5sSvaAKF90',
    'xltewJgQVV0', '8p7HytjrKj4', 'rvZWLTtEyoU', 'Xbv4IIqwW-4', '2zFyz6uO9-0', 'Fez57g8jMNM',
    'wlEuiYq8tcM', 'vdS3QBy9WeU', 'Egn-pNaM27U', 'H4yeMxZ07zY', 'SiQInf3_NIE', 'WsKg6HsoDaw',
    'rQK37u961Eo', 'CcMhB1DD-Gg', 'UEH3oRSgVXQ', '8P_ya85lxzw', '1lNbOH-cvl8', 'MY1Rk1polgM',
    'Tp8xIgyyK7I', 'HZi9ls9emUE', 'WunqZ9SF4hU', 'uhfVT5iAtMM', 'Ag7-U4ga9mA', '5kr5ADrMeYU',
    'tieXTqc15rE', 'UhR-Bn4UII0', 'Oq2bnLC_DXU', 'StEB_wntlZ0', 'tHZRXN_pVi8', 'uEgpgnKNF9Q',
    'TejfD82oLfU', 'rWHGKGS7zSc', 'bywWgD9yJq0', 'JZ_EV9DPtt0', 'VkLIUXjNwYc', 'mLYwM-kdbwM',
    '8XOA3-XwTaQ', 'jDqsNK1hmM8', 'mv3Fx8-O9co', 'v5p7WY9nOJM', 'c5Ppkvg7xHI', 'ACG6qr4waWU',
    'eEBc_QB5VIQ', 'jwAoLZXFLjo', 'bRzP7hwIGWE', 'lC_lCOxR5e0', 'Y3vHuw97AiA', 'DdOburEdIPg',
    'tyvMjvvrq74', 'bJq9kPc_-tw', 'YY1mN_ibteU', 'WBLuy_YU-Zw', 'AJRqLvAZp4Q', '6R0Wy4kwxes',
    'K-9-dtJpZ9c', 'wCgPjVzREqs', 'Z51Q29u4CWc', 'zFpk5FsNndM', 'bizx7atWYkQ', 'vBiBiCdlXes',
    'yz4a2soLDl4', 'WeNuLW5uPGc', 'tD-6xHAHrQ4', 'af7VzZTzmlg', '0YpwaYUGF94', 'DaW-Kha9qAM',
    'AlrXqakHPuk', 'rTSSchYtAXk', 'eXp4Mt1S8Lg', 'Q6MAcmJdYdA', 'MwqWPzDK6Hs', 'dRgwAU7Y4yY',
    '2OjMuGloIRo', 'mEoSi6l99OE', 'OHExziy0xLY', 'TyC762eWXzo', 'jdu6GCU42zU', 'wNJQPn-SLk8',
    'Dk8AAU_UdVk', 'el2iTDgF0y8', 'fgZl4Mp0Y_w', 'VZcW--Wi7mY', 'EiCs_8ZKVJc', '3-icphihD6Y',
    'wAV-vbHLn3Q', 'sm6EtQg-hxw', 'KB4Mn5XHdMc', 'yoFhTmWrYz8', 'fFLLQEFgK6s', 'wgO7yK7NZpg',
    'JFIhleM0Kbo', 'fJoCs5Z_QvE', 'MVGl4QJTZqY', 'ziimjZ-OrgU', 'Eofp060BEnw', 'rCh9MQibJ3c',
    'nQrS3-L9id4', 'kglKCEGytsk', 'oviVRMuVgAs', 'KFajmtdj-J0', 'LrZGtTuMpk8', 'O3tp5Y9lH88',
    'a66Gx6c-ZeE', 'luh9xTJ7ExM', 'l1DLZhZXsw0', '9hus12iCyL8', '5IqtP2fzNlA', 'pIOkrFZ-D1w',
    '5ZQ65RbsAB8', 'Dd3QvqyT2x4', '0VPwGqiWT04', 'w4BvAaL1S3g', 'hGzKWfQOKeQ', '5pxlzf0Tz_0',
    'NODkUzmamP8', 'NhVXCMjhmho', 'fGeQH4_lH3Q', 'l66TJNGKQFQ', 'P0siKVerEUg', 'ZDzklx1T6E0',
    'ipktRrpIjz8', 'Nb7wVCJ68YY', '6Y3rL9LVV9w', '9ifQ3xRz4hM', 'nNlS1lWEiQA', 'k-pl1DwhIFk',
    'Zho2dPAiZ74', '16hzMhzgaM0', 'aq1snwtQUQ4', '9g5X11dH-Lc', 'N3cE1lO8aCE', 'fWzD45xDQDo',
    'DxR2waii1Ck', 'rqPeFokY-T8', 'XMfNMnH8KyQ', '9EKvO6tu7a0', 'rT_zp4KQ4p8', 'MmODCOXX_2c',
    'Y7QvqbwRjLQ', 'fKg0nLaQzn4', 'tYKm_8dXmMc', 'WaQWL1Qr9i8', 'SYh7YSKxL6U', 'HMKqVxiPFVI',
    '_zmMl7T8164', 'r5iFFBpFSlU', 'hM4HYNE32wQ', 'PL90RepTkhk', '1niTruE-PNs', '7ZJxdmEKn0Q',
    'AQSGyV0rh5Y', 't2J-_-v-Spw', 'Z2xcl93o7F0', 'C4vC-Y3USfk', 'a5dR3olXGWU', 'H5BVbrZ64bQ',
    'wcEgBAORLM4', 'A2lIdSnv1Vw', '91liS87P9CY', 'hlsBs3XSDUM', 'XGx13d-QdIM', 'jnFeXaL02Fg',
    'eoXv4JgwjeM', 'RN6HGltVp2A', '8yzy7ucYcII', 'mxwJsvMj7JA', '31FjeWvLIxM', '7L2oJIob6X0',
    'B_TWPas7ZAw', 'WKmsxJkJCqM', 'Iigy0LpJjN4', '5w-zLrlTcY4', 'HKfDfWrCwEA', 'drWlSGryMkY',
    'jkMW1qtz01c', '4KcXgXgSxDI', 'P2UOO6L8rio', 'NGY-HJ_l35E', '8E8DQnmd4zs', 'X5YjfOKBffU',
    'x4HNOP6Ko6Y', '_WHCjv1MRmM', 'd6BGuntMwCM', 'CNoggf2Ibek', '0emVXTaESvs', 'EcTdPfg4wO8',
    'AfNSMykrG1I', 'lJMPosxMV2M', 'OQAS9pqC8V4', '9ry87N2tC_k', 'aA35kVsHuCo', 'jp1FCIQUBkw',
    'xf2RF9vx-G4', 'MrCklBFENkQ', 'COB_5wL_xv4', 'vHtvi6EtGkw', 'WAaAoXsIHvI', '2Z5iHh2omRA',
    'CRFHPkLgAKc', 'RS4MrptnnP8', 'Fxh3HeJvRhw', 'JaGXfJBx0BM', '2K2gB8b7qUw', 'Cn0oOdwryPo',
    'LC_3i_EPd6s', '9mIYleesmSU', 'gu_GfdJpdsA', 'B1hl-eRpGmI', '4pDImFxHNuY', 'gJ0BSnuX1GA',
    'dJZ9CSbGueU', 'atPNphv-NEI', 'cSlPuxN_yws', '1jgT2Wgsox8', 'iNRqZNXsB8k', 'XqZoDfJwNKE',
    'jO8d0wwXyk8', 'WVPcKah4CbA', 'lZIacnbb52Q', 'g2Ki5GeMevU', 's94XlBnJwZU', 'HTdQ8bDEhAQ',
    'Tcf1dbiWKsk', 'f0FkoUFJUo0', 'WbAeqhkL8aA', 'savzorNB_sI', 'gfnyMyCZjqA', '0R9NLQM4ZKA',
    'fVpEwW_4Yt4', 'cr2TXucwjVk', 'DvBWBSl2DKA', 'WcION1-0_VI', 'naB_3XYRtew', 'xZxmMQCZsu4',
    '0UOdAKVdbMo', '-aLUbUMVYAc', 'O3vGss0ELfg', 'iOao1dfGP2s', '8tFbax73NtA', 'hmnW6F3-KqE',
    'Dfc3ZqVwrNc', 'HZpEq-r7_Nw', 'obpKWRcXezA', '9mQkGyApBX0', '3DL3Htt8vck', 'kjVd228S-yQ',
    'lVFXbzzm1Bw', 'AhgRjqgrgkk', 'WUcNXALk_fQ', 'x4xlQTP-XDU', '0E9KurvLzqE', '-Bi-T52-F-s',
    'IKDqlHCOxrg', 'GUGtU7Ii1yk', 'NFZH67BgO5c', 'ZRkEwwOyTa4', 'l22DvDwD6Ow', 'oRhVmbfy1sY',
    '4yiVfwDkntQ', 'o2pdhO76ld4', 'MgoZwkSXzGw', 'ktgDXNML2uI', 'BCzbEQlk3to', 'RNZwLILj0Uw',
    'Engjh-aEevc', '2FqYQaLwWLo', 'adFreL6VqQY', 'ypXp6-MT_Co', 'k_qKbYrOq98', 'o8LAh3AUyXs',
    'vezrsZv5UcE', 'pfJ15WGdoWo', 'as-vRWOmJWU', 'Umb9e-L2DVg', 'GdGcE_-_T8Y', 'NVgpf-SFs0g',
    'aMe78rHCzF0', 'K-Nps59NeBA', 'EBAc4PIQC2Y', 'iHLgOqZ5CXc', '_q8geBY3vPA', 'KNhwmHq1asM',
    'dKUwijDI2KE', 'NwPkZgd6L-o', 'hfNU4h38Iis', 'cMjvx9GfaO0', 'uiSNeh10yPc', 'ObuDxIh89V8',
    'NLj72KSNZoo', 'tOxD9PEH8DU', 'WW4RnT1YuLg', 'URw3ITsBU6s', 'BvNNuSz-EFw', 'z3OykfkE_R0',
    'ZxTpScOY8c4', 'kU65ZNNOPc4', 'gcuCCv-n7YQ', 'RwBO6Hi5FvE', 'Xv5i11wmpQM', 'glK2V-7DJD8',
    'u6Ke0rdjKEg', '9bSMwNO_OCY', '3nw9cWGmI5E', 'xg7OWeR7tr4', '_StSUVR6_ok', 'Ac67KPcSqsM',
    'mQ8P4E7LKqI', 'n5p85sRPTLo', 'uoujHpVJSe8', 'ibQx65L7mcI', 'bLkvQrqkVCI', 'izx0SSLoTls',
    'G_a3ILspt-w', 'Jde-H7WW7BQ', '3fBxa1IEb74', 'xwbAWiqMuNE', 'Dn-uY9q4rLs', 'u6GOoQnJicg',
    '0cg27Y1atuI', 'Nn0QvidINiA', 'ojgogr0St9g', 'tnmgIUxfFE4', '6FY51RKsK3c', '1MqRALnIvWY',
    'SmKTe9okerg', 'gdIskHlqRwc', '69o1qyxZBuw', '360sNcECglc', 'LXw2xdWqkS0', 'lvhEPmiaeMs',
    'NrU4Cx2gAoU', 'l5dsQB0rqms', '-yJj6rYX6H0', 'uziFF8NSxaQ', 'wMQjmpVgor8', 'AhoslePC6yI',
    'hCMKloIx8vk', '95yoKdm5sMk', 'DD9IbPnCxMM', 'z2JsYmGmF8E', 'Pzq2slM4Wu4', 'bq9U_3exOLo',
    'x4qC_ed3dRg', 'NUHIoZFuDAw', 'l31dAwfYjhI', 'RTi-D3ykhqM', 'aOiuSsnWEik', 'bGsUkpvV9_w',
    'KaFF0__DnoM'
]

def get_today_video_ids():
    watched = session.get('watched_listening_videos', [])
    available = [vid for vid in LISTENING_VIDEO_IDS if vid not in watched]
    if len(available) < 2:
        # Tüm videolar izlendiyse sıfırla
        session['watched_listening_videos'] = []
        available = LISTENING_VIDEO_IDS.copy()
    # Her gün aynı 2 video gelsin diye tarihi hashle
    today = datetime.now().strftime('%Y-%m-%d')
    hash_val = sum([ord(c) for c in today])
    available.sort(key=lambda x: (ord(x[0]) + hash_val))
    return available[:2]

@app.route('/listening')
@login_required
def listening():
    video_ids = get_today_video_ids()
    return render_template('listening.html', video_ids=video_ids, section='hedefleyici')

@app.route('/mark_listening_watched', methods=['POST'])
@login_required
def mark_listening_watched():
    data = request.get_json()
    video_id = data.get('video_id')
    if not video_id:
        return jsonify({'success': False, 'error': 'Video ID eksik'}), 400
    watched = session.get('watched_listening_videos', [])
    if video_id not in watched:
        watched.append(video_id)
        session['watched_listening_videos'] = watched
    return jsonify({'success': True})

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        # JSON (Mobil) veya Form (Web) kontrolü
        if request.is_json:
            data = request.get_json()
        elif 'application/json' in request.headers.get('Accept', ''):
            data = request.get_json(force=True, silent=True) or {}
        else:
            data = None

        if data:
            current_user.Name = data.get('name')
            current_user.Surname = data.get('surname')
            current_user.Class = data.get('class')
            current_user.YearOfBirth = data.get('year_of_birth')
            current_user.Email = data.get('email')
            current_user.PhoneNumber = data.get('phone')
            current_user.Area = data.get('area')
            current_user.Aim = data.get('aim')
            new_password = data.get('new_password')
            if new_password:
                current_user.PasswordHash = hashlib.sha256(new_password.encode()).hexdigest()
        else:
            current_user.Name = request.form.get('name')
            current_user.Surname = request.form.get('surname')
            current_user.Class = request.form.get('class')
            current_user.YearOfBirth = request.form.get('year_of_birth')
            current_user.Email = request.form.get('email')
            current_user.PhoneNumber = request.form.get('phone')
            current_user.Area = request.form.get('area')
            current_user.Aim = request.form.get('aim')
            # ... (web şifre güncelleme mantığı devam eder)

        try:
            db.session.commit()
            if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({"success": True, "message": "Profil güncellendi"})
            flash('Profil başarıyla güncellendi.', 'success')
            return redirect(url_for('profile'))
        except Exception as e:
            db.session.rollback()
            if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({"success": False, "error": str(e)}), 500
            flash('Profil güncellenirken hata oluştu.', 'error')

    # GET isteği
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        total_q = Question.query.filter_by(UserId=current_user.UserId).count()
        completed_q = Question.query.filter_by(UserId=current_user.UserId, IsCompleted=True).count()
        success_rate = round((completed_q / total_q * 100) if total_q > 0 else 0)
        
        return jsonify({
            "success": True,
            "user": {
                "name": current_user.Name,
                "surname": current_user.Surname,
                "email": current_user.Email,
                "phone": current_user.PhoneNumber,
                "class": current_user.Class,
                "aim": current_user.Aim,
                "area": current_user.Area,
                "year_of_birth": current_user.YearOfBirth,
                "stats": {
                    "total_questions": total_q,
                    "success_rate": success_rate,
                    "badges": 12 # Şimdilik statik
                }
            }
        })

    return render_template('profile.html', section='takipsistemi', show_sidebar=True)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('welcome'))

@app.route('/add_question', methods=['GET', 'POST'])
@login_required
def add_question():
    if request.method == 'POST':
        try:
            # Handle both JSON and Form data
            if request.is_json:
                data = request.get_json()
                content = data.get('content') or data.get('explanation')
                category = data.get('category')
                topic = data.get('topic')
                difficulty = data.get('difficulty')
                question_image = None
            else:
                content = request.form.get('content') or request.form.get('explanation')
                category = request.form.get('category')
                topic = request.form.get('topic')
                difficulty = request.form.get('difficulty')
                question_image = request.files.get('question_image')

            # Validation
            if not category or not topic or not difficulty:
                if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                    return jsonify({"success": False, "message": "Lütfen tüm zorunlu alanları doldurun."}), 400
                flash('Lütfen tüm zorunlu alanları doldurun.', 'error')
                return redirect(url_for('add_question'))

            content = content if content is not None else ''
            image_path = None
            now = datetime.now()
            # Kullanıcının ayarlarından tekrar aralığını al
            user_settings = UserSettings.query.filter_by(UserId=current_user.UserId).first()
            interval = user_settings.RepeatInterval if user_settings and user_settings.RepeatInterval else 1
            repeat1_date = now
            repeat2_date = now + timedelta(days=interval)
            repeat3_date = now + timedelta(days=interval * 2)

            if question_image and question_image.filename:
                try:
                    filename = secure_filename(question_image.filename)
                    unique_filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{filename}"
                    upload_folder = os.path.join(app.static_folder, 'uploads')
                    if not os.path.exists(upload_folder):
                        os.makedirs(upload_folder)
                    image_path = f"uploads/{unique_filename}"
                    full_path = os.path.join(app.static_folder, 'uploads', unique_filename)
                    question_image.save(full_path)
                except Exception as e:
                    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                        return jsonify({"success": False, "message": "Görsel yüklenirken bir hata oluştu."}), 500
                    flash('Görsel yüklenirken bir hata oluştu.', 'error')

            new_question = Question(
                UserId=current_user.UserId,
                content=content,
                CategoryId=category,
                topic=topic,
                difficulty=difficulty,
                PhotoPath=None,
                IsCompleted=False,
                IsViewed=False,
                IsRepeated=False,
                RepeatCount=0,
                Repeat1Date=repeat1_date,
                Repeat2Date=repeat2_date,
                Repeat3Date=repeat3_date,
                Explanation=None,
                ImagePath=image_path
            )
            db.session.add(new_question)
            db.session.commit()

            # Notification
            new_notification = Notification(
                UserId=current_user.UserId,
                NotificationType='Yeni Soru Eklendi',
                Schedule=datetime.now()
            )
            db.session.add(new_notification)
            db.session.commit()

            if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({
                    "success": True, 
                    "message": "Soru başarıyla eklendi.",
                    "question_id": new_question.QuestionId
                })

            flash('Soru başarıyla eklendi.', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({"success": False, "message": str(e)}), 500
            flash('Soru eklenirken bir hata oluştu: ' + str(e), 'error')
            return redirect(url_for('add_question'))
    # Kategorileri veritabanından çek
    categories = Category.query.order_by(Category.Name).all()
    if not categories:
        # Kategori yoksa otomatik ekle
        create_categories()
        categories = Category.query.order_by(Category.Name).all()
        if not categories:
            flash('Hiç kategori bulunamadı ve otomatik eklenemedi. Lütfen yöneticinize başvurun.', 'error')
            return render_template('add_question.html', categories=[], section='takipsistemi', show_sidebar=True)
    return render_template('add_question.html', categories=categories, section='takipsistemi', show_sidebar=True)

@app.route('/edit_question/<int:question_id>', methods=['GET', 'POST'])
@login_required
def edit_question(question_id):
    question = Question.query.get_or_404(question_id)
    if question.UserId != current_user.UserId:
        flash('Bu soruyu düzenleme yetkiniz yok.')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        question.content = request.form.get('content')
        question.CategoryId = request.form.get('category_id')
        question.difficulty = request.form.get('difficulty')
        
        try:
            db.session.commit()
            flash('Soru başarıyla güncellendi.', 'success')
            return redirect(url_for('view_question', question_id=question_id))
        except Exception as e:
            db.session.rollback()
            flash('Soru güncellenirken bir hata oluştu.')
            return redirect(url_for('edit_question', question_id=question_id))
    
    categories = Category.query.order_by(Category.Name).all()
    return render_template('edit_question.html', question=question, categories=categories, section='takipsistemi', show_sidebar=True)

@app.route('/view_today_question/<int:question_id>')
@login_required
def view_today_question(question_id):
    question = Question.query.get_or_404(question_id)
    if question.UserId != current_user.UserId:
        abort(403) # Kullanıcı sorunun sahibi değilse izin verme
        
    # Notları getir (varsa)
    notes = Note.query.filter_by(QuestionId=question.QuestionId).all()

    # Favori bilgisini kontrol et
    is_favorite = Favorite.query.filter_by(UserId=current_user.UserId, QuestionId=question.QuestionId).first() is not None

    return render_template('view_today_question.html', question=question, notes=notes, is_favorite=is_favorite, section='takipsistemi', show_sidebar=True) # section'ı isteğe göre ayarlayabilirsiniz

@app.route('/view_question/<int:question_id>')
@login_required
def view_question(question_id):
    question = Question.query.get_or_404(question_id)
    if question.UserId != current_user.UserId:
        flash('Bu soruyu görüntüleme yetkiniz yok.', 'error')
        return redirect(url_for('index'))
    
    # Notları getir
    notes = Note.query.filter_by(QuestionId=question_id).order_by(Note.NoteId.desc()).all()
    
    # Favori durumunu kontrol et
    is_favorite = Favorite.query.filter_by(
        QuestionId=question_id,
        UserId=current_user.UserId
    ).first() is not None
    
    # Tekrar durumunu hesapla
    repeat_status = {
        'count': question.RepeatCount,
        'is_completed': question.IsCompleted,
        'is_repeated': question.IsRepeated,
        'dates': {
            'repeat1': question.Repeat1Date,
            'repeat2': question.Repeat2Date,
            'repeat3': question.Repeat3Date
        }
    }
    # section parametresi query string ile gelirse onu kullan, yoksa defaultu kullan
    # section ve category_id parametrelerini al
    section = request.args.get('section', 'all')
    category_id = request.args.get('category_id')
    
    # Eğer kategori belirtilmemişse ama sorunun bir kategorisi varsa otomatik ata
    if not category_id and question.CategoryId:
        category_id = str(question.CategoryId)
        if section == 'all' or not section or section == 'takipsistemi':
            section = 'kategori'

    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        try:
            return jsonify({
                "success": True,
                "question": {
                    "id": question.QuestionId,
                    "content": question.content,
                    "image_path": question.ImagePath if question.ImagePath else None,
                    "category": question.category.Name if question.category else "Genel",
                    "topic": question.topic if question.topic else "Genel",
                    "difficulty": question.difficulty if question.difficulty else "Orta",
                    "answer": question.answer if question.answer else "",
                    "explanation": question.Explanation if question.Explanation else "",
                    "is_favorite": is_favorite,
                    "repeat_count": question.RepeatCount if question.RepeatCount is not None else 0,
                    "is_completed": question.IsCompleted if question.IsCompleted is not None else False,
                    "next_repeat_date": question.Repeat1Date.strftime("%d.%m.%Y") if question.Repeat1Date else "Belirlenmedi",
                    "progress_text": f"{question.RepeatCount}/3 ADIM"
                },
                "notes": [{"id": n.NoteId, "content": n.Content} for n in notes]
            })
        except Exception as e:
            print(f"DEBUG: Question Detail JSON Error: {str(e)}")
            return jsonify({"success": False, "message": str(e)}), 500

    return render_template('view_question.html', 
                         question=question, 
                         notes=notes,
                         is_favorite=is_favorite,
                         repeat_status=repeat_status,
                         section=section,
                         category_id=category_id,
                         show_sidebar=True,
                         active_page='index')

@app.route('/api/dashboard')
@login_required
def api_dashboard():
    from sqlalchemy import func
    
    # 1. Kategoriler ve Soru Sayıları
    categories = Category.query.all()
    pool_data = []
    
    # Her ders için profesyonel ve yüksek çözünürlüklü görseller
    image_map = {
        "Matematik": "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?q=80&w=800",
        "Fizik": "https://images.unsplash.com/photo-1636466497217-26a8cbeaf0aa?q=80&w=800",
        "Kimya": "https://images.unsplash.com/photo-1603126738554-974e7f21d89a?q=80&w=800",
        "Biyoloji": "https://images.unsplash.com/photo-1530026405186-ed1f139313f8?q=80&w=800",
        "Tarih": "https://images.unsplash.com/photo-1461360370896-922624d12aa1?q=80&w=800",
        "Coğrafya": "https://images.unsplash.com/photo-1521295121783-8a321d551ad2?q=80&w=800",
        "Türk Dili ve Edebiyatı": "https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?q=80&w=800",
        "Felsefe": "https://images.unsplash.com/photo-1505664194779-8beaceb93744?q=80&w=800",
        "Din": "https://images.unsplash.com/photo-1542810634-71277d95dcbb?q=80&w=800",
        "Yabancı Dil": "https://images.unsplash.com/photo-1451226428352-cf66bf8a0317?q=80&w=800"
    }

    for cat in categories:
        count = Question.query.filter_by(
            UserId=current_user.UserId, 
            CategoryId=cat.CategoryId,
            IsHidden=False
        ).count()
        
        cat_name_clean = cat.Name.strip()
        
        # Dinamik İkon ve Renk Atama (Branşla Uyumlu)
        subject_styles = {
            "Matematik": {"icon": "calculate", "color": "#7c4dff"},
            "Fizik": {"icon": "wb-sunny", "color": "#10b981"},
            "Kimya": {"icon": "science", "color": "#f59e0b"},
            "Biyoloji": {"icon": "biotech", "color": "#ec4899"},
            "Tarih": {"icon": "history", "color": "#8b5cf6"},
            "Coğrafya": {"icon": "public", "color": "#3b82f6"},
            "Türk Dili ve Edebiyatı": {"icon": "menu-book", "color": "#ef4444"},
            "Felsefe": {"icon": "psychology", "color": "#6366f1"},
            "Din": {"icon": "self-improvement", "color": "#14b8a6"},
            "Yabancı Dil": {"icon": "translate", "color": "#f97316"}
        }
        
        style = subject_styles.get(cat_name_clean, {"icon": "school", "color": "#494455"})
        
        pool_data.append({
            "id": cat.CategoryId,
            "name": cat.Name,
            "count": count,
            "color": style["color"],
            "icon": style["icon"],
            "image": image_map.get(cat_name_clean, "https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?q=80&w=800")
        })

    # 2. Genel İstatistikler
    total_q = Question.query.filter_by(UserId=current_user.UserId).count()
    completed_q = Question.query.filter_by(UserId=current_user.UserId, IsCompleted=True).count()
    accuracy = round((completed_q / total_q * 100), 1) if total_q > 0 else 0

    # 3. Haftalık Aktivite
    activity_data = db.session.query(
        func.cast(Question.created_at, db.Date).label('date'),
        func.count('*').label('count')
    ).filter(
        Question.UserId == current_user.UserId,
        Question.created_at >= (datetime.now() - timedelta(days=7))
    ).group_by(func.cast(Question.created_at, db.Date)).all()
    
    days_map = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt']
    weekly_activity = []
    max_count = max([act.count for act in activity_data] + [1])
    
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).date()
        day_name = days_map[(d.weekday() + 1) % 7]
        count = next((act.count for act in activity_data if act.date == d), 0)
        height = int((count / max_count) * 100) if count > 0 else 20
        
        weekly_activity.append({
            "day": day_name[0], # Sadece ilk harf (P, S, Ç...)
            "height": height,
            "active": d == datetime.now().date(),
            "count": count
        })

    return jsonify({
        "success": True,
        "username": current_user.UserName,
        "pools": pool_data,
        "stats": {
            "total_questions": total_q,
            "success_rate": accuracy,
            "completed_questions": completed_q
        },
        "weekly_activity": weekly_activity
    })

@app.route('/api/category_questions/<int:category_id>')
@login_required
def api_category_questions(category_id):
    questions = Question.query.filter_by(
        UserId=current_user.UserId, 
        CategoryId=category_id,
        IsHidden=False
    ).order_by(Question.created_at.desc()).all()
    
    def question_to_dict(q):
        return {
            "id": q.QuestionId,
            "content": q.content,
            "topic": q.topic,
            "category": q.category.Name if q.category else "Genel",
            "difficulty": q.difficulty,
            "image": q.ImagePath or q.PhotoPath,
            "repeat_count": q.RepeatCount,
            "created_at": q.created_at.strftime('%d.%m.%Y') if q.created_at else "Bilinmiyor"
        }
    
    category = Category.query.get(category_id)
    return jsonify({
        "success": True,
        "category_name": category.Name if category else "Genel",
        "questions": [question_to_dict(q) for q in questions]
    })

@app.route('/api/categories', methods=['GET'])
@login_required
def api_categories():
    categories = Category.query.order_by(Category.Name).all()
    if not categories:
        create_categories()
        categories = Category.query.order_by(Category.Name).all()
        
    return jsonify({
        "success": True,
        "categories": [{"id": c.CategoryId, "name": c.Name} for c in categories]
    })

@app.route('/ai_quiz')
@login_required
def ai_quiz_home():
    return render_template('ai_quiz.html', active_page='ai_quiz')

@app.route('/generate_ai_quiz', methods=['POST'])
@csrf.exempt
@login_required
def generate_ai_quiz():
    try:
        print(f"DEBUG: AI Quiz Request for User: {current_user.UserName} (ID: {current_user.UserId})")
        # 1. Kullanıcının geçmiş sorularını analiz et
        failed_questions = Question.query.filter_by(UserId=current_user.UserId)\
                            .filter(db.or_(Question.FailedAttempts > 0, Question.status == 'failed'))\
                            .order_by(Question.QuestionId.desc()).limit(5).all()
                            
        completed_questions = Question.query.filter_by(UserId=current_user.UserId)\
                            .filter(db.or_(Question.IsCompleted == True, Question.status == 'completed'))\
                            .order_by(Question.QuestionId.desc()).limit(5).all()
        
        # Hiç veri yoksa genel olarak en son çözülenlere bak
        recent_questions = []
        if not failed_questions and not completed_questions:
            recent_questions = Question.query.filter_by(UserId=current_user.UserId)\
                                .order_by(Question.QuestionId.desc()).limit(10).all()
        
        # PROMPT CONTEXT OLUŞTURMA
        if failed_questions or completed_questions:
            failed_str = ""
            if failed_questions:
                failed_str = "ÇÖZEMEDİĞİ VE ZORLANDIĞI SORULAR (Bunların mantığına benzer, eğitici, eksiğini kapatacak sorular hazırla):\n"
                failed_str += "\n".join([f"- Konu: {q.topic}, Zorluk: {getattr(q, 'difficulty', 'Orta')}, İçerik Özeti: {q.content[:80]}..." for q in failed_questions])
                
            completed_str = ""
            if completed_questions:
                completed_str = "BAŞARIYLA TAMAMLADIĞI SORULAR (Bunların konusunu anladığını kanıtlayacak, farklı bakış açısı gerektiren pekiştirici sorular hazırla):\n"
                completed_str += "\n".join([f"- Konu: {q.topic}, Zorluk: {getattr(q, 'difficulty', 'Orta')}, İçerik Özeti: {q.content[:80]}..." for q in completed_questions])
            
            prompt_context = f"{failed_str}\n\n{completed_str}"
            
        elif recent_questions:
            history_str = "\n".join([f"- Konu: {q.topic}, Zorluk: {getattr(q, 'difficulty', 'Orta')}, Soru: {q.content[:50]}..." for q in recent_questions])
            prompt_context = f"Kullanıcının henüz netleşmiş başarı/başarısızlık verisi yok. Ancak üzerinde çalıştığı son konular şunlar:\n{history_str}\n\nLütfen bu konulara benzer seviyede 5 soru hazırla."
            
        else:
            # TAMAMEN YENİ KULLANICI / VERİ YOK
            print(f"DEBUG: No data found for user {current_user.UserId}, using fallback general quiz.")
            prompt_context = "Kullanıcının henüz hiç sorusu yok. Lütfen genel Orta seviye TYT Matematik konularından (Sayılar, Denklemler, Problemler vb.) 5 adet özgün, eğitici çoktan seçmeli soru hazırla."


        # 2. Gemini için Prompt
        prompt = f"""
        Sen uzman bir eğitim koçu ve öğretmensin. Öğrencinin geçmiş performansına dayanarak, ona özel tam 5 adet özgün çoktan seçmeli soru (A, B, C, D şıklarıyla) hazırlayacaksın.
        
        KULLANICI PROFİLİ VE GEÇMİŞİ:
        {prompt_context}
        
        GÖREV:
        1. Kullanıcının "ÇÖZEMEDİĞİ" sorular listesinden yola çıkarak, aynı konularda (eğer Matematik ise matematik, Fizik ise fizik vb.) farklı sayılar/senaryolar içeren eğitici sorular hazırla. Amaç yapamadığı konuyu öğrenmesidir.
        2. Kullanıcının "BAŞARIYLA TAMAMLADIĞI" konulardan, o konuyu tam anlayıp anlamadığını test etmek için konuyu pekiştirici ufak detaylar içeren sorular hazırla.
        3. Sorular açık, net ve hatasız olmalıdır.

        KURALLAR:
        - Yanıtı SADECE saf JSON formatında ver. Başka hiçbir metin veya markdown yazma.
        - 'questions' anahtarı altında bir liste döndür. Her sorunun şu alanları OLMALIDIR:
          "topic": "Soru Hangi Konudan (Örn: Köklü Sayılar)",
          "difficulty": "Zorluk Derecesi (Kolay/Orta/Zor)",
          "question": "Sorunun tam metni",
          "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
          "correct_answer": "Sadece doğru şıkkın HARFİ. Örneğin sadece 'A', 'B', 'C' veya 'D'. Nokta veya parantez kullanma.",
          "explanation": "Doğru cevabın nasıl bulunduğunu açıklayan kısa metin"
        """

        model = genai.GenerativeModel('gemini-flash-lite-latest')
        response = model.generate_content(prompt)
        
        try:
            raw_text = response.text.strip()
        except Exception as text_err:
            raise ValueError(f"Gemini yanıt metni okunamadı (güvenlik filtreleri engellemiş olabilir): {text_err}")

        # JSON kısmını temizleme ve çıkarma
        import re
        json_match = re.search(r'[\{\[].*[\}\]]', raw_text, re.DOTALL)
        if json_match:
            clean_text = json_match.group(0)
        else:
            clean_text = raw_text

        # Trailing comma temizliği (bazı LLM'ler JSON sonlarında virgül bırakabilir)
        clean_text = re.sub(r',\s*([\]\}])', r'\1', clean_text)

        try:
            quiz_data = json.loads(clean_text)
        except Exception as json_err:
            # Fallback: Eğer standart json kütüphanesi hata verirse, tek tırnakları çift tırnağa dönüştürerek basit bir düzeltme deneyelim
            try:
                fixed_text = clean_text.replace("'", '"')
                quiz_data = json.loads(fixed_text)
            except Exception:
                raise ValueError(f"JSON Ayrıştırma Hatası: {json_err}. Ham yanıt: {raw_text[:200]}")

        # Sorular listesini akıllıca bul
        questions_list = None
        if isinstance(quiz_data, list):
            questions_list = quiz_data
        elif isinstance(quiz_data, dict):
            # 'questions' veya benzeri anahtarları ara
            for key in ['questions', 'quiz', 'questions_list', 'sorular']:
                if key in quiz_data and isinstance(quiz_data[key], list):
                    questions_list = quiz_data[key]
                    break
            # Eğer bulunamazsa, dict içindeki ilk liste değerini al
            if not questions_list:
                for val in quiz_data.values():
                    if isinstance(val, list):
                        questions_list = val
                        break

        if not questions_list or not isinstance(questions_list, list):
            raise ValueError(f"JSON içinde geçerli bir soru listesi bulunamadı. Yapı: {type(quiz_data)}")

        # Her soruyu doğrula ve eksik/farklı adlandırılmış alanları sanitize et
        sanitized_questions = []
        for q in questions_list:
            if not isinstance(q, dict):
                continue
            
            # Gerekli alanları temizle ve varsayılan değerleri ata
            topic = q.get('topic') or q.get('subject') or 'Genel Matematik'
            difficulty = q.get('difficulty') or q.get('difficulty_level') or 'Orta'
            question_text = q.get('question') or q.get('text') or q.get('new_question')
            
            # options kontrolü
            options = q.get('options')
            if not isinstance(options, list) or len(options) < 4:
                options = ["A) Seçenek A", "B) Seçenek B", "C) Seçenek C", "D) Seçenek D"]
            
            correct_answer = q.get('correct_answer') or q.get('answer') or 'A'
            explanation = q.get('explanation') or q.get('solution') or ''
            
            sanitized_questions.append({
                'topic': str(topic),
                'difficulty': str(difficulty),
                'question': str(question_text) if question_text else "Soru metni yüklenemedi.",
                'options': [str(opt) for opt in options[:4]],
                'correct_answer': str(correct_answer),
                'explanation': str(explanation)
            })
            
        if not sanitized_questions:
            raise ValueError("Geçerli formatta hiçbir soru ayrıştırılamadı.")
            
        return jsonify({'success': True, 'quiz': sanitized_questions})
        
    except Exception as e:
        error_msg = str(e)
        print(f"Quiz Error: {error_msg}")
        if "429" in error_msg or "quota" in error_msg.lower():
            return jsonify({'success': False, 'error': 'Yapay zeka sunucuları şu an çok yoğun. (Ücretsiz kota sınırına ulaşıldı). Lütfen 1 dakika bekleyip tekrar deneyin.'})
        return jsonify({'success': False, 'error': f'AI Soru Üretemedi: {error_msg}'})

@app.route('/add_note/<int:question_id>', methods=['POST'])
@login_required
def add_note(question_id):
    try:
        data = request.get_json()
        if not data or 'content' not in data:
            return jsonify({'success': False, 'error': 'Not içeriği gerekli.'}), 400

        note = Note(
            QuestionId=question_id,
            Content=data['content']
        )
        db.session.add(note)
        db.session.commit()

        return jsonify({
            'success': True,
            'note': {
                'id': note.NoteId,
                'content': note.Content
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# --- AI SHORTS SYSTEM --- #


@app.route('/ai_shorts')
@login_required
def ai_shorts():
    return render_template('ai_shorts.html', active_page='ai_shorts')

from sqlalchemy import text

@app.route('/api/save_short_to_pool', methods=['POST'])
@login_required
def save_short_to_pool():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Veri alınamadı'}), 400
        
    video_id = data.get('video_id')
    title = data.get('title')
    topic = data.get('topic')
    
    category_name = topic
    if topic == 'Geometri':
        category_name = 'Matematik'
        
    category = Category.query.filter_by(Name=category_name).first()
    if not category:
        category = Category.query.first()
    
    # Kullanıcının ayarlarından tekrar aralığını al
    _settings = UserSettings.query.filter_by(UserId=current_user.UserId).first()
    _interval = _settings.RepeatInterval if _settings and _settings.RepeatInterval else 1
    _now = datetime.now()

    new_question = Question(
        UserId=current_user.UserId,
        CategoryId=category.CategoryId,
        content=f"YouTube Shorts Sorusunu İzle: {title}\nVideo Linki: https://www.youtube.com/shorts/{video_id}",
        topic=topic,
        difficulty="Orta",
        status="unsolved",
        IsCompleted=False,
        IsHidden=False,
        RepeatCount=0,
        Repeat1Date=_now,
        Repeat2Date=_now + timedelta(days=_interval),
        Repeat3Date=_now + timedelta(days=_interval * 2)
    )
    
    try:
        db.session.add(new_question)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500




@app.route('/api/shorts_feed')
@login_required
def shorts_feed():
    return jsonify({'success': True, 'items': []})

@app.route('/delete_question/<int:question_id>', methods=['POST'])
@login_required
def delete_question(question_id):
    try:
        question = Question.query.get_or_404(question_id)
        if question.UserId != current_user.UserId:
            return jsonify({'success': False, 'error': 'Bu işlem için yetkiniz yok.'}), 403

        Favorite.query.filter_by(QuestionId=question_id).delete()
        Note.query.filter_by(QuestionId=question_id).delete()
        Reminder.query.filter_by(QuestionId=question_id).delete()
        
        db.session.delete(question)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
        Note.query.filter_by(QuestionId=question_id).delete()
        Reminder.query.filter_by(QuestionId=question_id).delete()
        
        # Sonra soruyu sil
        db.session.delete(question)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/mark_completed/<int:question_id>', methods=['POST'])
@login_required
def mark_completed(question_id):
    question = Question.query.get_or_404(question_id)
    if question.UserId != current_user.UserId:
        abort(403)

    # Tekrar sayısını artır
    if question.RepeatCount < 3:
        question.RepeatCount += 1

    # Eğer tüm tekrarlar tamamlandıysa soruyu tamamlandı olarak işaretle
    if question.RepeatCount >= 3:
        question.IsCompleted = True
        #question.CompletedAt = datetime.now() # CompletedAt sadece soru tamamen bitince mi set edilmeli? Şimdilik RepeatCount >= 3 olunca set etmiyorum.

    db.session.commit()

    # Kullanıcıyı aynı soru detay sayfasına geri yönlendir yerine JSON yanıtı döndür
    # flash('Tekrar tamamlandı!', 'success') # Flash mesajı istemci tarafında gösterilebilir
    return jsonify({'success': True, 'message': 'Tekrar tamamlandı!'})

@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def api_settings():
    settings = UserSettings.query.filter_by(UserId=current_user.UserId).first()
    if not settings:
        settings = UserSettings(UserId=current_user.UserId)
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "Veri bulunamadı"}), 400
        
        # Ayarları güncelle
        if 'theme' in data:
            settings.Theme = data['theme']
        if 'email_notifications' in data:
            settings.EmailNotifications = data['email_notifications']
        if 'repeat_interval' in data:
            try:
                interval = int(data['repeat_interval'])
                if 1 <= interval <= 30:
                    old_interval = settings.RepeatInterval or 1
                    if old_interval != interval:
                        settings.RepeatInterval = interval
                        # Kullanıcının tamamlanmamış tüm sorularını güncelle
                        uncompleted_questions = Question.query.filter_by(
                            UserId=current_user.UserId,
                            IsCompleted=False
                        ).all()
                        for q in uncompleted_questions:
                            if q.Repeat1Date:
                                # Eski sistemde oluşturulmuş soruları geriye dönük uyumlu hale getirmek için:
                                # Eğer Repeat1Date, created_at tarihinden 1 saatten daha fazla gelecekteyse
                                # o zaman eski sistemdedir ve başlangıç tarihi created_at'tir.
                                # Aksi halde Repeat1Date başlangıç tarihidir.
                                if q.created_at and q.Repeat1Date > q.created_at + timedelta(hours=1):
                                    base_date = q.created_at
                                else:
                                    base_date = q.Repeat1Date
                            elif q.created_at:
                                base_date = q.created_at
                            else:
                                base_date = datetime.now()
                            
                            q.Repeat1Date = base_date
                            q.Repeat2Date = base_date + timedelta(days=interval)
                            q.Repeat3Date = base_date + timedelta(days=interval * 2)
            except (ValueError, TypeError):
                pass
        
        try:
            db.session.commit()
            return jsonify({"success": True, "message": "Ayarlar kaydedildi"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({
        "success": True,
        "settings": {
            "theme": settings.Theme or 'light',
            "email_notifications": settings.EmailNotifications,
            "push_notifications": True, # Şimdilik varsayılan
            "repeat_interval": settings.RepeatInterval or 1
        }
    })

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html', section='takipsistemi', show_sidebar=True)

@app.route('/category/<int:category_id>')
@login_required
def category_questions(category_id):
    category = Category.query.get_or_404(category_id)
    
    # Get the selected topic from the query parameters, default to None
    selected_topic = request.args.get('topic')

    # Base query for questions in this category for the current user, not hidden
    query = Question.query.filter_by(
        UserId=current_user.UserId,
        CategoryId=category_id,
        IsHidden=False
    )
    
    # If a topic is selected, filter the query by topic
    if selected_topic:
        # Handle the case where "Diğer" (Other) is selected for questions with no topic
        if selected_topic == "Diğer":
            query = query.filter(Question.topic == None)
        else:
            query = query.filter_by(topic=selected_topic)

    questions = query.order_by(Question.topic).all()
    
    # Get all unique topics for this category and user (for the filter dropdown)
    all_topics_query = Question.query.with_entities(Question.topic).filter_by(
        UserId=current_user.UserId,
        CategoryId=category_id,
        IsHidden=False
    ).distinct()
    all_topics = [topic[0] if topic[0] is not None else "Diğer" for topic in all_topics_query]
    all_topics.sort() # Sort topics alphabetically

    return render_template('category_questions.html', 
                         category=category, 
                         questions=questions, # Pass filtered questions
                         all_topics=all_topics, # Pass all unique topics for the filter
                         selected_topic=selected_topic, # Pass the currently selected topic
                         section='takipsistemi', # Set section for sidebar
                         show_sidebar=True, # Show sidebar
                         active_page='index'
                         )

@app.route('/favorites')
@csrf.exempt
@login_required
def favorites():
    categories = Category.query.all()
    category_id = request.args.get('category')

    query = Question.query.join(
        Favorite,
        Question.QuestionId == Favorite.QuestionId
    ).filter(
        Favorite.UserId == current_user.UserId
    ).order_by(Question.Repeat1Date)

    if category_id:
        try:
            category_id = int(category_id)
            query = query.filter(Question.CategoryId == category_id)
        except ValueError:
            # Geçersiz kategori ID'si durumunda hata yönetimi veya tüm favorileri gösterme
            flash('Geçersiz kategori seçimi.', 'warning')
            pass # Hata durumunda filtreleme yapma

    questions = query.all()

    # Eğer mobil uygulama JSON istiyorsa
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({
            "success": True,
            "questions": [{
                "id": q.QuestionId,
                "content": q.content,
                "topic": q.topic,
                "category": q.category.Name if q.category else "Genel",
                "difficulty": q.difficulty,
                "image": q.ImagePath or q.PhotoPath,
                "created_at": q.created_at.strftime('%d.%m.%Y') if q.created_at else "Bilinmiyor"
            } for q in questions]
        })

    return render_template('favorites.html', questions=questions, categories=categories, selected_category_id=category_id, section='takipsistemi', show_sidebar=True)

@app.route('/toggle_favorite/<int:question_id>', methods=['POST'])
@login_required
def toggle_favorite(question_id):
    try:
        question = Question.query.get_or_404(question_id)
        if question.UserId != current_user.UserId:
            return jsonify({'success': False, 'error': 'Bu işlem için yetkiniz yok.'}), 403

        # Favori durumunu kontrol et
        favorite = Favorite.query.filter_by(
            QuestionId=question_id,
            UserId=current_user.UserId
        ).first()

        if favorite:
            # Favori varsa sil
            db.session.delete(favorite)
        else:
            # Favori yoksa ekle
            new_favorite = Favorite(
                QuestionId=question_id,
                UserId=current_user.UserId
            )
            db.session.add(new_favorite)
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_reminders')
@login_required
def get_reminders():
    try:
        reminders = Reminder.query.filter_by(
            UserId=current_user.UserId,
            IsActive=True
        ).all()
        
        reminder_list = []
        for reminder in reminders:
            question = Question.query.get(reminder.QuestionId)
            if question and not question.IsCompleted:
                reminder_list.append({
                    'id': reminder.ReminderId,
                    'question_id': reminder.QuestionId,
                    'question_content': question.content[:100] + '...' if len(question.content) > 100 else question.content,
                    'frequency': reminder.Frequency,
                    'time': reminder.Time.strftime('%H:%M'),
                    'category': question.category.Name
                })
        
        return jsonify({'success': True, 'reminders': reminder_list})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_reminder/<int:reminder_id>', methods=['POST'])
@login_required
def delete_reminder(reminder_id):
    try:
        reminder = Reminder.query.get_or_404(reminder_id)
        if reminder.UserId != current_user.UserId:
            return jsonify({'success': False, 'error': 'Bu hatırlatıcıya erişim izniniz yok.'})
        
        db.session.delete(reminder)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

def check_reminders():
    """Hatırlatıcıları kontrol eden ve bildirim gönderen fonksiyon"""
    with app.app_context():
        try:
            now = datetime.now()
            current_time = now.time()
            
            # Aktif hatırlatıcıları al
            reminders = Reminder.query.filter_by(IsActive=True).all()
            
            for reminder in reminders:
                # Son gönderim zamanını kontrol et
                if reminder.LastSent:
                    time_diff = now - reminder.LastSent
                    
                    # Frekansa göre kontrol
                    if reminder.Frequency == 'daily' and time_diff.days < 1:
                        continue
                    elif reminder.Frequency == 'weekly' and time_diff.days < 7:
                        continue
                    elif reminder.Frequency == 'monthly' and time_diff.days < 30:
                        continue
                
                # Hatırlatma saatini kontrol et
                if reminder.Time.hour == current_time.hour and reminder.Time.minute == current_time.minute:
                    # Bildirim gönder
                    question = Question.query.get(reminder.QuestionId)
                    if question and not question.IsCompleted:
                        notification = Notification(
                            UserId=reminder.UserId,
                            NotificationType='reminder',
                            TaskId=None,
                            Schedule=now
                        )
                        db.session.add(notification)
                        reminder.LastSent = now
                        db.session.commit()
                        
                        print(f"Hatırlatma gönderildi: {question.content[:50]}...")
        
        except Exception as e:
            print(f"Hatırlatıcı kontrolü hatası: {str(e)}")

# Hatırlatıcı kontrolü için zamanlanmış görev
def schedule_reminder_check():
    while True:
        check_reminders()
        time.sleep(60)  # Her dakika kontrol et

# Arka planda çalışacak hatırlatıcı thread'ini başlat
reminder_thread = threading.Thread(target=schedule_reminder_check, daemon=True)
reminder_thread.start()

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(Email=email).first()
        
        if user:
            if user.SecurityQuestion and user.SecurityAnswer:
                # Güvenlik sorusu aşamasına yönlendir
                return render_template('forgot_password_security.html', user=user, show_sidebar=False)
            else:
                # Eğer güvenlik sorusu yoksa (eski kullanıcılar), e-posta göndermeyi dene
                try:
                    token = secrets.token_urlsafe(32)
                    reset_token = PasswordResetToken(UserId=user.UserId, Token=token, ExpiresAt=datetime.now() + timedelta(hours=24))
                    db.session.add(reset_token)
                    db.session.commit()
                    
                    reset_url = url_for('reset_password', token=token, _external=True)
                    msg = Message('Şifre Sıfırlama', recipients=[user.Email])
                    msg.body = f'Şifrenizi sıfırlamak için tıklayın: {reset_url}'
                    mail.send(msg)
                    flash('Şifre sıfırlama bağlantısı e-postanıza gönderildi.', 'success')
                    return redirect(url_for('login'))
                except Exception as e:
                    flash(f'E-posta gönderilemedi. Lütfen sistem yöneticisiyle iletişime geçin. Hata: {str(e)}', 'error')
        else:
            flash('Bu e-posta ile kayıtlı kullanıcı bulunamadı.', 'error')
    
    return render_template('forgot_password.html', show_sidebar=False)

@app.route('/save_pomodoro', methods=['POST'])
@login_required
def save_pomodoro():
    data = request.get_json()
    duration = data.get('duration', 25)
    session_type = data.get('type', 'pomodoro')
    
    try:
        new_session = PomodoroSession(
            UserId=current_user.UserId,
            Duration=duration,
            Type=session_type
        )
        db.session.add(new_session)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/login/google')
def login_google():
    redirect_uri = url_for('google_authorize', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/login/google/authorize')
def google_authorize():
    try:
        token = google.authorize_access_token()
        user_info = google.get('https://www.googleapis.com/oauth2/v3/userinfo').json()
        email = user_info.get('email')
        google_id = user_info.get('sub') # sub is the unique ID in OpenID Connect
        
        user = User.query.filter_by(Email=email).first()
        if not user:
            user = User.query.filter_by(GoogleAuthId=google_id).first()
            
        if not user:
            # Rastgele bir kullanıcı adı oluştur
            base_username = email.split('@')[0]
            username = base_username
            counter = 1
            while User.query.filter_by(UserName=username).first():
                username = f"{base_username}{counter}"
                counter += 1
                
            user = User(
                UserName=username,
                Email=email,
                GoogleAuthId=google_id,
                Name=user_info.get('given_name', ''),
                Surname=user_info.get('family_name', ''),
                PasswordHash='google-auth-' + secrets.token_hex(8) # Güvenli geçersiz şifre
            )
            db.session.add(user)
            db.session.commit()
        
        login_user(user)
        flash('Google ile başarıyla giriş yapıldı.', 'success')
        return redirect(url_for('welcome'))
    except Exception as e:
        flash(f'Google girişi sırasında bir hata oluştu: {str(e)}', 'error')
        return redirect(url_for('login'))

@app.route('/verify_security', methods=['POST'])
def verify_security():
    user_id = request.form.get('user_id')
    answer = request.form.get('answer')
    user = User.query.get(user_id)
    
    if user and user.SecurityAnswer == answer:
        token = secrets.token_urlsafe(32)
        reset_token = PasswordResetToken(UserId=user.UserId, Token=token, ExpiresAt=datetime.now() + timedelta(hours=1))
        db.session.add(reset_token)
        db.session.commit()
        return redirect(url_for('reset_password', token=token))
    else:
        flash('Güvenlik sorusu cevabı yanlış.', 'error')
        return redirect(url_for('forgot_password'))
    
    return render_template('forgot_password.html', show_sidebar=False)

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    reset_token = PasswordResetToken.query.filter_by(Token=token, IsUsed=False).first()
    
    if not reset_token or reset_token.ExpiresAt < datetime.now():
        flash('Geçersiz veya süresi dolmuş şifre sıfırlama bağlantısı.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Şifreler eşleşmiyor.', 'error')
            return redirect(url_for('reset_password', token=token))
        
        # Şifreyi güncelle
        user = User.query.get(reset_token.UserId)
        user.PasswordHash = hashlib.sha256(password.encode()).hexdigest()
        
        # Token'ı kullanıldı olarak işaretle
        reset_token.IsUsed = True
        
        db.session.commit()
        flash('Şifreniz başarıyla güncellendi. Şimdi giriş yapabilirsiniz.', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html', show_sidebar=False)

@app.route('/report')
@login_required
def report():
    today = datetime.now().date()
    # Tamamlanan görevler (bugün tamamlananlar)
    completed_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed',
        db.text("CAST([Tasks].[CompletedAt] AS DATE) = :today")
    ).params(today=today).all()
    # Gecikmiş görevler (Status in ['new', 'pending'] ve DueDate < now)
    overdue_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status.in_(['new', 'pending']),
        Task.DueDate < datetime.now()
    ).all()
    # Toplam çalışma süresi (görev türü fark etmeksizin, o günün tüm TaskTime kayıtları)
    total_time = db.session.query(db.func.sum(TaskTime.Duration)).join(Task).filter(
        Task.UserId == current_user.UserId,
        db.text("CAST([TaskTimes].[StartTime] AS DATE) = :today")
    ).params(today=today).scalar() or 0
    # Pomodoro süreleri (Serbest Çalışma görevlerinden)
    pomodoro_time = db.session.query(db.func.sum(TaskTime.Duration)).join(Task).filter(
        Task.UserId == current_user.UserId,
        Task.Title == 'Serbest Çalışma',
        db.text("CAST([TaskTimes].[StartTime] AS DATE) = :today")
    ).params(today=today).scalar() or 0
    total_tasks = len(completed_tasks) + len(overdue_tasks)
    completion_rate = int((len(completed_tasks) / total_tasks) * 100) if total_tasks > 0 else 0
    return render_template(
        'report.html',
        report_date=today.strftime('%d.%m.%Y'),
        completed_count=len(completed_tasks),
        overdue_count=len(overdue_tasks),
        total_time=pomodoro_time,
        completed_tasks=completed_tasks,
        overdue_tasks=overdue_tasks,
        completion_rate=completion_rate,
        section='hedefleyici',
        show_sidebar=False
    )

@app.route('/pomodoro_settings')
@login_required
def pomodoro_settings():
    return render_template('pomodoro_settings.html', section='takipsistemi', show_sidebar=True)

@app.route('/hide_question/<int:question_id>', methods=['POST'])
@login_required
def hide_question(question_id):
    question = Question.query.get_or_404(question_id)
    if question.UserId != current_user.UserId:
        return jsonify({'success': False, 'error': 'Bu işlem için yetkiniz yok'}), 403
    
    try:
        question.IsHidden = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/progress_report')
@csrf.exempt
@login_required
def progress_report():
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Haftalık ve aylık tamamlanan soru/görev
    weekly_questions = Question.query.filter(
        Question.UserId == current_user.UserId,
        Question.IsCompleted == True,
        db.text("CAST([Questions].[CompletedAt] AS DATE) >= :week_ago")
    ).params(week_ago=week_ago).all()
    monthly_questions = Question.query.filter(
        Question.UserId == current_user.UserId,
        Question.IsCompleted == True,
        db.text("CAST([Questions].[CompletedAt] AS DATE) >= :month_ago")
    ).params(month_ago=month_ago).all()

    weekly_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed',
        db.text("CAST([Tasks].[CompletedAt] AS DATE) >= :week_ago")
    ).params(week_ago=week_ago).all()
    monthly_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed',
        db.text("CAST([Tasks].[CompletedAt] AS DATE) >= :month_ago")
    ).params(month_ago=month_ago).all()

    # Kategori bazlı dağılım (haftalık)
    categories = Category.query.all()
    category_stats = []
    for category in categories:
        count = Question.query.filter(
            Question.UserId == current_user.UserId,
            Question.IsCompleted == True,
            Question.CategoryId == category.CategoryId,
            db.text("CAST([Questions].[CompletedAt] AS DATE) >= :week_ago")
        ).params(week_ago=week_ago).count()
        category_stats.append({
            'category': category.Name,
            'count': count
        })

    # Başarı oranı (haftalık)
    total_weekly_questions = Question.query.filter(
        Question.UserId == current_user.UserId,
        db.text("CAST([Questions].[Repeat1Date] AS DATE) >= :week_ago")
    ).params(week_ago=week_ago).count()
    completed_weekly_questions = len(weekly_questions)
    success_rate = int((completed_weekly_questions / total_weekly_questions) * 100) if total_weekly_questions > 0 else 0

    # Öneri ve hedef (en az yapılan kategori)
    min_category = min(category_stats, key=lambda x: x['count']) if category_stats else None
    suggestion = None
    if min_category and min_category['count'] < 5:
        suggestion = f"Bu hafta {min_category['category']} kategorisinde daha fazla soru çözmeye çalış!"
    elif min_category:
        suggestion = f"Harika! Tüm kategorilerde iyi gidiyorsun."

    # Haftalık hedef (örnek: 10 soru)
    weekly_goal = 10
    goal_message = f"Bu hafta en az {weekly_goal} soru çöz!"

    return jsonify({
        'weekly_questions': completed_weekly_questions,
        'monthly_questions': len(monthly_questions),
        'weekly_tasks': len(weekly_tasks),
        'monthly_tasks': len(monthly_tasks),
        'success_rate': success_rate,
        'category_stats': category_stats,
        'suggestion': suggestion,
        'goal_message': goal_message
    })

@app.route('/progress')
@login_required
def progress():
    # Kullanıcının sorularını veritabanından çek
    questions = Question.query.filter_by(UserId=current_user.UserId).all()

    # Veriyi DataFrame formatına dönüştür
    data = []
    for q in questions:
        # Her tekrar tarihi için ayrı bir satır oluştur
        if q.Repeat1Date:
            data.append({'ders': q.category.Name, 'tekrar_no': 1, 'durum': 'tamamlandı' if q.RepeatCount >= 1 else 'kaçırıldı', 'date': q.Repeat1Date})
        if q.Repeat2Date:
            data.append({'ders': q.category.Name, 'tekrar_no': 2, 'durum': 'tamamlandı' if q.RepeatCount >= 2 else 'kaçırıldı', 'date': q.Repeat2Date})
        if q.Repeat3Date:
            data.append({'ders': q.category.Name, 'tekrar_no': 3, 'durum': 'tamamlandı' if q.RepeatCount >= 3 else 'kaçırıldı', 'date': q.Repeat3Date})


    df = pd.DataFrame(data)

    # Tarih sütununu datetime formatına çevir (gerekirse)
    if 'date' in df.columns:
         df['date'] = pd.to_datetime(df['date'])


    # --- İstatistikler ve Karşılaştırma Verileri ---
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday()) # Haftanın başlangıcı (Pazartesi)
    week_ago_start = week_start - timedelta(days=7)
    month_ago_start = today.replace(day=1) # Ayın başlangıcı

    # Mevcut Hafta/Ay Verileri (DataFrame'deki tekrar tarihlerine göre)
    current_week_repeats_df = df[(df['date'].dt.date >= week_start) & (df['date'].dt.date <= today)]
    current_month_repeats_df = df[(df['date'].dt.date >= month_ago_start) & (df['date'].dt.date <= today)]

    # Tamamlanan tekrar sayıları bu hafta/ay içinde tekrar tarihi olanlardan
    current_weekly_completed_repeats_count = current_week_repeats_df[current_week_repeats_df['durum'] == 'tamamlandı'].shape[0]
    current_monthly_completed_repeats_count = current_month_repeats_df[current_month_repeats_df['durum'] == 'tamamlandı'].shape[0]

    # Haftalık/Aylık Görev Verileri (Tamamlananlar - Task modelinde CompletedAt var)
    current_weekly_completed_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed',
        Task.CompletedAt >= datetime.combine(week_start, datetime.min.time()),
        Task.CompletedAt <= datetime.combine(today + timedelta(days=1), datetime.min.time()) # Bugünü de dahil et
    ).count()
    current_monthly_completed_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed',
        Task.CompletedAt >= datetime.combine(month_ago_start, datetime.min.time()),
        Task.CompletedAt <= datetime.combine(today + timedelta(days=1), datetime.min.time()) # Bugünü de dahil et
    ).count()


    # Başarı Oranı (Bu hafta tekrar tarihi olan tekrarların kaçı tamamlandı?)
    total_due_this_week = current_week_repeats_df.shape[0]
    weekly_success_rate = int((current_weekly_completed_repeats_count / total_due_this_week) * 100) if total_due_this_week > 0 else 0


    # Geçmiş Hafta Verileri (DataFrame'deki tekrar tarihlerine göre)
    last_week_repeats_df = df[(df['date'].dt.date >= week_ago_start) & (df['date'].dt.date < week_start)]
    last_week_completed_repeats_count = last_week_repeats_df[last_week_repeats_df['durum'] == 'tamamlandı'].shape[0]

    # Geçmiş Haftalık Görev Verileri (Task modelinde CompletedAt var)
    last_week_completed_tasks = Task.query.filter(
        Task.UserId == current_user.UserId,
        Task.Status == 'completed',
        Task.CompletedAt >= datetime.combine(week_ago_start, datetime.min.time()),
        Task.CompletedAt < datetime.combine(week_start, datetime.min.time())
    ).count()


    # Kategori İstatistikleri (Öneri için - Sadece tamamlanan tekrar sayıları)
    category_completion_counts = df[df['durum'] == 'tamamlandı'].groupby('ders').size().to_dict()

    # En az tekrar tamamlanan kategoriyi bul (Tamamlanan tekrar sayısı en az olan)
    min_category = None
    if category_completion_counts:
        min_category_name = min(category_completion_counts, key=category_completion_counts.get)
        min_category = min_category_name
        # Eğer hiç tekrar tamamlanmadıysa genel bir mesaj ver
        if all(count == 0 for count in category_completion_counts.values()):
             suggestion = "Henüz tekrar tamamlamadınız. Başlamak için bugün tekrar edilmesi gereken sorulara göz atın!"
        else:
            suggestion = f"Bu hafta {min_category} kategorisine daha fazla odaklanmayı düşünebilirsin."
    else:
        suggestion = "Henüz hiç soru eklememiş veya tekrar yapmamışsınız. Hadi ilk sorunuzu ekleyin!"


    # Haftalık Hedef (Örnek)
    weekly_goal = 10 # Haftalık hedef tamamlanan tekrar sayısı olabilir
    goal_message = f"Bu hafta {weekly_goal} tekrar tamamlamayı hedefle!" # Hedef türünü netleştirebiliriz


    # --- Grafik Oluşturma (Mevcut kod) ---
    graph_url = None
    if not df.empty:
        # Her ders için toplam tamamlanan ve kaçırılan tekrar sayısını bul
        # Burada sadece verisi olan dersleri alalım
        ders_stats = df.groupby('ders')['durum'].value_counts().unstack(fill_value=0).dropna(axis=0, how='all')
        dersler = ders_stats.index.tolist()

        if dersler: # Eğer hiç ders istatistiği yoksa grafik çizme
            num_categories = len(dersler)
            # Calculate the number of rows needed for subplots (2 columns)
            num_rows = (num_categories + 1) // 2 # Integer division to get ceiling

            # Adjust figure size based on number of rows, minimum size for single row
            fig_height = max(5, num_rows * 5)
            fig, axs = plt.subplots(num_rows, 2, figsize=(10, fig_height))

            # If only one row, ensure axs is a list
            if num_rows == 1:
                axs = [axs] if isinstance(axs, plt.Axes) else axs
            else:
                axs = axs.flatten()


            # Hide unused subplots if the total number of categories is odd
            for i in range(num_categories, len(axs)):
                fig.delaxes(axs[i])


            for i, ders in enumerate(dersler):
                ax = axs[i]

                # Tamamlanan ve kaçırılan sayıları al
                tamamlanan = ders_stats.loc[ders].get('tamamlandı', 0)
                kaçırılan = ders_stats.loc[ders].get('kaçırıldı', 0)

                # Sadece veri varsa daire grafiği çiz
                if tamamlanan + kaçırılan > 0:
                    labels = ['Tamamlandı', 'Kaçırıldı']
                    sizes = [tamamlanan, kaçırılan]
                    colors = ['#98D8AA', '#FFB5B5'] # Soft renkler: Açık yeşil ve soft kırmızı

                    ax.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140)
                    ax.axis('equal')  # Eşit en boy oranı, dairenin çizgi değil daire olmasına sağlar.

                ax.set_title(f'{ders}') # Ders adını başlık yap
                # Eğer veri yoksa veya sıfırsa grafiğin üzerine "Veri Yok" yazabiliriz
                if tamamlanan + kaçırılan == 0:
                     ax.text(0, 0, "Veri Yok", ha='center', va='center', fontsize=12, color='gray')


            plt.suptitle('Derslere Göre Tekrar Performansı', y=1.02, fontsize=16) # Ana başlığı güncelle
            plt.tight_layout(rect=[0, 0.03, 1, 0.95])

            # Grafiği bir buffer'a kaydet
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            graph_url = base64.b64encode(buf.read()).decode('utf-8')
            plt.close(fig) # Figürü kapat

    # Şablonu render et ve tüm verileri gönder
    return render_template(
        'progress_report.html',
        graph_url=graph_url,
        section='takipsistemi',
        show_sidebar=True,
        # Yeni eklenen veriler
        current_weekly_questions=current_weekly_completed_repeats_count, # Tekrar sayısı olarak güncellendi
        current_monthly_questions=current_monthly_completed_repeats_count, # Tekrar sayısı olarak güncellendi
        current_weekly_tasks=current_weekly_completed_tasks,
        current_monthly_tasks=current_monthly_completed_tasks,
        weekly_success_rate=weekly_success_rate,
        suggestion=suggestion,
        goal_message=goal_message,
        last_week_completed_questions=last_week_completed_repeats_count, # Tekrar sayısı olarak güncellendi
        last_week_completed_tasks=last_week_completed_tasks
    )

@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    try:
        title = request.form.get('title')
        description = request.form.get('description')
        due_date_str = request.form.get('due_date')
        priority = request.form.get('priority')
        category = request.form.get('category')

        # Tarih formatını kontrol et ve dönüştür
        due_date = None
        if due_date_str:
            try:
                # 'YYYY-MM-DDTHH:MM' formatı için uygun dönüşüm
                due_date = datetime.strptime(due_date_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Geçerli bir son tarih formatı girin.', 'error')
                return redirect(url_for('gorevlerim')) # Hata durumunda geri yönlendir

        if not title or not due_date or not priority or not category:
            flash('Lütfen tüm zorunlu alanları (Başlık, Son Tarih, Öncelik, Kategori) doldurun.', 'error')
            return redirect(url_for('gorevlerim')) # Hata durumunda geri yönlendir

        new_task = Task(
            UserId=current_user.UserId,
            Title=title,
            Description=description,
            DueDate=due_date,
            Priority=priority,
            Category=category,
            Status='new', # Yeni görev başlangıçta 'new' durumunda
            CreatedAt=datetime.utcnow()
        )

        db.session.add(new_task)
        db.session.commit()

       

    except Exception as e:
        db.session.rollback()
        flash('Görev eklenirken bir hata oluştu: ' + str(e), 'error')

    return redirect(url_for('gorevlerim'))

@app.route('/update_book_progress/<int:book_id>', methods=['POST'])
@login_required
def update_book_progress(book_id):
    try:
        book = Book.query.get_or_404(book_id)
        if book.UserId != current_user.UserId:
            flash('Bu kitabı güncelleme yetkiniz yok.', 'error')
            return redirect(url_for('kitaplarim'))

        current_page = request.form.get('current_page', type=int)

        if current_page is None or current_page < 0 or current_page > book.TotalPages:
            flash('Geçerli bir sayfa numarası girin.', 'error')
            return redirect(url_for('kitaplarim'))

        book.CurrentPage = current_page
        
        # Eğer mevcut sayfa toplam sayfaya eşitse kitabı tamamlandı olarak işaretle
        if book.CurrentPage == book.TotalPages:
            book.IsCompleted = True

        db.session.commit()
        flash('Kitap ilerlemesi güncellendi.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Kitap ilerlemesi güncellenirken bir hata oluştu: ' + str(e), 'error')

    return redirect(url_for('kitaplarim'))

@app.route('/add_quote/<int:book_id>', methods=['POST'])
@login_required
def add_quote(book_id):
    try:
        book = Book.query.get_or_404(book_id)
        if book.UserId != current_user.UserId:
            flash('Bu kitaba alıntı ekleme yetkiniz yok.', 'error')
            return redirect(url_for('kitaplarim'))

        page_number = request.form.get('page_number', type=int)
        content = request.form.get('content')

        if page_number is None or content is None:
            flash('Sayfa numarası ve alıntı içeriği gerekli.', 'error')
            return redirect(url_for('kitaplarim'))
            
        if page_number <= 0 or page_number > book.TotalPages:
             flash(f'Geçerli bir sayfa numarası girin (1 ile {book.TotalPages} arası).' , 'error')
             return redirect(url_for('kitaplarim'))

        new_quote = BookQuote(
            BookId=book_id,
            PageNumber=page_number,
            Content=content,
            CreatedAt=datetime.utcnow()
        )

        db.session.add(new_quote)
        db.session.commit()

        flash('Alıntı başarıyla eklendi.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Alıntı eklenirken bir hata oluştu: ' + str(e), 'error')

    return redirect(url_for('kitaplarim'))

@app.route('/add_book', methods=['POST'])
@login_required
def add_book():
    try:
        title = request.form.get('title')
        author = request.form.get('author')
        total_pages = request.form.get('total_pages', type=int)

        if not title or not author or total_pages is None or total_pages <= 0:
            flash('Kitap adı, yazar ve toplam sayfa sayısı gerekli.', 'error')
            return redirect(url_for('kitaplarim'))

        new_book = Book(
            UserId=current_user.UserId,
            Title=title,
            Author=author,
            CurrentPage=0,
            TotalPages=total_pages,
            StartDate=datetime.utcnow(),
            IsCompleted=False
        )

        db.session.add(new_book)
        db.session.commit()

        flash('Kitap başarıyla eklendi!', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Kitap eklenirken bir hata oluştu: ' + str(e), 'error')

    return redirect(url_for('kitaplarim'))

@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    task = Task.query.filter_by(TaskId=task_id, UserId=current_user.UserId).first()
    if not task:
        flash('Görev bulunamadı veya yetkiniz yok.', 'error')
        return redirect(url_for('gorevlerim'))
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        due_date_str = request.form.get('due_date')
        priority = request.form.get('priority')
        category = request.form.get('category')
        try:
            if due_date_str:
                task.DueDate = datetime.strptime(due_date_str, '%Y-%m-%dT%H:%M')
            task.Title = title
            task.Description = description
            task.Priority = priority
            task.Category = category
            db.session.commit()
            flash('Görev başarıyla güncellendi!', 'success')
            return redirect(url_for('gorevlerim'))
        except Exception as e:
            db.session.rollback()
            flash('Güncelleme sırasında hata oluştu: ' + str(e), 'error')
    return render_template('edit_task.html', task=task)

@app.route('/delete_task', methods=['POST'])
@login_required
def delete_task():
    import json
    data = request.get_json()
    task_id = data.get('task_id')
    if not task_id:
        return jsonify({'success': False, 'error': 'Görev ID eksik'}), 400
    task = Task.query.filter_by(TaskId=task_id, UserId=current_user.UserId).first()
    if not task:
        return jsonify({'success': False, 'error': 'Görev bulunamadı veya yetkiniz yok'}), 404
    try:
        db.session.delete(task)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_task/<int:task_id>')
@login_required
def get_task(task_id):
    task = Task.query.filter_by(TaskId=task_id, UserId=current_user.UserId).first()
    if not task:
        return jsonify({'success': False, 'error': 'Görev bulunamadı'}), 404
    return jsonify({
        'TaskId': task.TaskId,
        'Title': task.Title,
        'Description': task.Description,
        'DueDate': task.DueDate.strftime('%Y-%m-%dT%H:%M') if task.DueDate else '',
        'Priority': task.Priority,
        'Category': task.Category
    })

@app.route('/edit_task_modal', methods=['POST'])
@login_required
def edit_task_modal():
    task_id = request.form.get('task_id')
    title = request.form.get('title')
    description = request.form.get('description')
    due_date_str = request.form.get('due_date')
    priority = request.form.get('priority')
    category = request.form.get('category')
    task = Task.query.filter_by(TaskId=task_id, UserId=current_user.UserId).first()
    if not task:
        return jsonify({'success': False, 'error': 'Görev bulunamadı'}), 404
    try:
        if due_date_str:
            task.DueDate = datetime.strptime(due_date_str, '%Y-%m-%dT%H:%M')
        task.Title = title
        task.Description = description
        task.Priority = priority
        task.Category = category
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/complete_task/<int:task_id>', methods=['POST'])
@login_required
def complete_task(task_id):
    task = Task.query.filter_by(TaskId=task_id, UserId=current_user.UserId).first()
    if not task:
        return jsonify({'success': False, 'error': 'Görev bulunamadı'}), 404
    try:
        task.Status = 'completed'
        task.CompletedAt = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/update_repeat_count/<int:question_id>', methods=['POST'])
@login_required
def update_repeat_count(question_id):
    question = Question.query.get_or_404(question_id)
    if question.UserId != current_user.UserId:
        return jsonify({'success': False, 'error': 'Bu işlem için yetkiniz yok'}), 403

    today = datetime.now().date()
    # Bugünkü tekrar zaten yapılmış mı kontrolü
    if question.RepeatCount == 0 and question.Repeat1Date and question.Repeat1Date.date() == today:
        if question.RepeatCount > 0:
            return jsonify({'success': False, 'error': 'Bugünkü tekrar zaten tamamlandı.'})
    elif question.RepeatCount == 1 and question.Repeat2Date and question.Repeat2Date.date() == today:
        if question.RepeatCount > 1:
            return jsonify({'success': False, 'error': 'Bugünkü tekrar zaten tamamlandı.'})
    elif question.RepeatCount == 2 and question.Repeat3Date and question.Repeat3Date.date() == today:
        if question.RepeatCount > 2:
            return jsonify({'success': False, 'error': 'Bugünkü tekrar zaten tamamlandı.'})

    updated_dates = {
        'repeat1': question.Repeat1Date.strftime('%d.%m.%Y') if question.Repeat1Date else 'Belirlenmedi',
        'repeat2': question.Repeat2Date.strftime('%d.%m.%Y') if question.Repeat2Date else 'Belirlenmedi',
        'repeat3': question.Repeat3Date.strftime('%d.%m.%Y') if question.Repeat3Date else 'Belirlenmedi',
    }

    if question.RepeatCount == 0:
        question.RepeatCount = 1
    elif question.RepeatCount == 1:
        question.RepeatCount = 2
    elif question.RepeatCount == 2:
        question.RepeatCount = 3
        question.IsCompleted = True
    else:
        return jsonify({'success': False, 'error': 'Zaten tamamlandı.'})

    db.session.commit()

    return jsonify({
        'success': True,
        'repeat_count': question.RepeatCount,
        'is_completed': question.IsCompleted,
        'updated_repeat_dates': updated_dates
    })

@app.route('/mark_failed/<int:question_id>', methods=['POST'])
@login_required
def mark_failed(question_id):
    """Kullanıcı 'Çözemedim' dediğinde çalışır. Tekrarı tamamlar ama hatayı kaydeder."""
    question = Question.query.get_or_404(question_id)
    if question.UserId != current_user.UserId:
        return jsonify({'success': False, 'error': 'Yetkisiz işlem'}), 403

    # Çözemedim sayısını artır
    question.FailedAttempts = (question.FailedAttempts or 0) + 1
    
    # Ancak yine de tekrar sayısını artır (kullanıcı isteği üzerine)
    if question.RepeatCount == 0:
        question.RepeatCount = 1
    elif question.RepeatCount == 1:
        question.RepeatCount = 2
    elif question.RepeatCount == 2:
        question.RepeatCount = 3
        question.IsCompleted = True
    
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': 'Hata kaydedildi, tekrar ilerlemesi güncellendi.',
        'failed_count': question.FailedAttempts,
        'is_completed': question.IsCompleted
    })

@app.context_processor
def inject_notifications():
    if current_user.is_authenticated:
        today = datetime.now().date()
        yesterday = datetime.now() - timedelta(days=1)
        notifications = []

        # Bugünün soruları bildirimi
        today_questions_count = Question.query.filter(
            Question.UserId == current_user.UserId,
            Question.IsCompleted == False,
            Question.IsHidden == False,
            (
                (Question.RepeatCount == 0) & (db.func.cast(Question.Repeat1Date, db.Date) == today)
                |
                (Question.RepeatCount == 1) & (db.func.cast(Question.Repeat2Date, db.Date) == today)
                |
                (Question.RepeatCount == 2) & (db.func.cast(Question.Repeat3Date, db.Date) == today)
            )
        ).count()
        if today_questions_count > 0:
            notifications.append({
                'icon': 'fas fa-clock',
                'color_class': 'blue',
                'type': 'Bugünün Soruları',
                'msg': f'{today_questions_count} soru çözülmeyi bekliyor',
                'timestamp': None,
            })

        # Son 24 saatte tamamlanan görev bildirimi
        completed_tasks_last_24h = Task.query.filter(
            Task.UserId == current_user.UserId,
            Task.Status == 'completed',
            Task.CompletedAt >= yesterday
        ).count()
        if completed_tasks_last_24h > 0:
            notifications.append({
                'icon': 'fas fa-check-circle',
                'color_class': 'green',
                'type': 'Görev Tamamlandı',
                'msg': f'Son 24 saatte tamamlanan {completed_tasks_last_24h} görev',
                'timestamp': None,
            })

        # Okunan kitap bildirimi
        books_count = Book.query.filter_by(
            UserId=current_user.UserId
        ).count()
        # if books_count > 0:
        #     notifications.append({
        #         'icon': 'fas fa-book',
        #         'color_class': 'purple',
        #         'type': 'Kitap',
        #         'msg': f'{books_count} kitap okuyorsun!',
        #         'timestamp': None,
        #     })

        # Motivasyon mesajı
        motivation_messages = [
            "Başarı, küçük adımların toplamıdır!",
            "Her gün bir adım daha ileriye!",
            "Zorlandığında vazgeçme, mola ver ve devam et!",
            "Küçük adımlar büyük başarılar getirir!",
            "Bugün dünden daha iyi ol!",
            "Başarı yolunda ilerliyorsun!",
            "Kendine inan, başarabilirsin!",
            "Her tekrar seni hedefe yaklaştırır!"
        ]
        import random
        motivation_message = random.choice(motivation_messages)
        notifications.append({
            'icon': 'fas fa-lightbulb',
            'color_class': 'yellow',
            'type': 'Motivasyon',
            'msg': motivation_message,
            'timestamp': None,
        })

        notification_count = len(notifications)
        daily_summary = None
        return dict(notifications=notifications, notification_count=notification_count, daily_summary=daily_summary, today_questions_count=today_questions_count)
    return dict(notifications=[], notification_count=0, daily_summary=None, today_questions_count=0)

@app.route('/next_question/<int:current_id>')
@login_required
def next_question(current_id):
    source = request.args.get('source', 'today')
    category_id_str = request.args.get('category_id')
    category_id = None
    if category_id_str and category_id_str.isdigit():
        category_id = int(category_id_str)

    user_id = current_user.UserId
    today = datetime.now().date()

    if source == 'past':
        questions = Question.query.filter(
            Question.UserId == user_id,
            Question.IsCompleted == False,
            Question.RepeatCount < 3,
            Question.QuestionId != current_id
        ).all()
        def get_active_repeat_date(q):
            if q.RepeatCount == 0:
                return q.Repeat1Date.date() if q.Repeat1Date else None
            elif q.RepeatCount == 1:
                return q.Repeat2Date.date() if q.Repeat2Date else None
            elif q.RepeatCount == 2:
                return q.Repeat3Date.date() if q.Repeat3Date else None
            return None
        filtered = []
        for q in questions:
            ard = get_active_repeat_date(q)
            if ard and ard < today:
                filtered.append(q)
        filtered.sort(key=get_active_repeat_date, reverse=True)
        next_question = filtered[0] if filtered else None
    elif source == 'kategori' and category_id:
        # Önce mevcut sorudan sonraki ilk soruyu bul
        next_question = Question.query.filter(
            Question.UserId == user_id,
            Question.CategoryId == category_id,
            Question.QuestionId > current_id
        ).order_by(Question.QuestionId).first()
        if not next_question:
            # Yoksa en küçük QuestionId'li soruya dön
            next_question = Question.query.filter(
                Question.UserId == user_id,
                Question.CategoryId == category_id
            ).order_by(Question.QuestionId).first()
    else:
        # Bugünün soruları (Güvenli Sıralama)
        try:
            query = Question.query.filter(
                Question.UserId == user_id,
                Question.IsCompleted == False,
                Question.IsHidden == False,
                db.or_(
                    db.and_(Question.RepeatCount == 0, db.cast(Question.Repeat1Date, db.Date) <= today),
                    db.and_(Question.RepeatCount == 1, db.cast(Question.Repeat2Date, db.Date) <= today),
                    db.and_(Question.RepeatCount == 2, db.cast(Question.Repeat3Date, db.Date) <= today)
                ),
                Question.QuestionId != current_id
            ).order_by(Question.created_at.asc())
        except:
             query = Question.query.filter(
                Question.UserId == user_id,
                Question.IsCompleted == False,
                Question.IsHidden == False,
                db.or_(
                    db.and_(Question.RepeatCount == 0, db.cast(Question.Repeat1Date, db.Date) <= today),
                    db.and_(Question.RepeatCount == 1, db.cast(Question.Repeat2Date, db.Date) <= today),
                    db.and_(Question.RepeatCount == 2, db.cast(Question.Repeat3Date, db.Date) <= today)
                ),
                Question.QuestionId != current_id
            ).order_by(Question.QuestionId.asc())
        
        next_question = query.first()

    if next_question:
        return jsonify({'next_id': next_question.QuestionId})
    else:
        return jsonify({'next_id': None})

@app.route('/send-message', methods=['POST'])
@login_required
def send_message():
    content = request.form.get('content', '').strip().lower()
    
    if not content:
        return jsonify({'response': 'Lütfen bir mesaj girin.'}), 400
        
    if 'merhaba' in content or 'selam' in content:
        response = 'Merhaba! Sana bugün derslerinde nasıl yardımcı olabilirim?'
    elif 'pomodoro' in content or 'sayaç' in content:
        response = 'Pomodoro sayacı ile odaklanma süreni artırabilirsin. Sol menüden Sayaç sekmesine giderek bir çalışma oturumu başlatabilirsin!'
    elif 'soru' in content or 'ekle' in content:
        response = 'Yeni bir soru eklemek için sol menüden "Yeni Soru Ekle" sayfasına gidebilirsin. Eklediğin sorular tekrar aralığına göre karşına çıkacaktır.'
    elif 'hedef' in content or 'rapor' in content:
        response = 'Gelişim raporunu ve hedeflerini "Gelişim Raporu" sekmesinden takip edebilirsin. Bol şans!'
    elif 'nasılsın' in content:
        response = 'Teşekkürler, ben bir yapay zeka asistanıyım! Sana yardım etmeye hazırım. Sen nasılsın, çalışmalar nasıl gidiyor?'
    # --- SİTE / UYGULAMA BİLGİSİ ---
    elif any(word in content for word in ['site', 'uygulama', 'reviseme', 'nedir', 'amacı', 'hakkında', 'ne işe yarar']) and 'bana' not in content:
        response = '<b>Akademi Pro (ReviseMe):</b> Öğrencilerin çalışma verimliliğini en üst düzeye çıkarmak için tasarlanmış modern bir dijital asistan ve tekrar sistemidir. <br><br><b>Neler yapabilirsin?</b><br>1. Spaced Repetition (Aralıklı Tekrar) algoritması ile unutmaya yüz tuttuğun soruları sana tam zamanında hatırlatır.<br>2. Pomodoro sayacı ile odaklanarak çalışabilirsin.<br>3. Gelişim Raporu sayesinde hangi derste ne kadar ilerlediğini takip edebilirsin.<br>Kısacası, sınav yolculuğundaki en zeki çalışma arkadaşındır!'
    # --- KONU ANLATIMI (DİNAMİK VİKİPEDİ) ---
    else:
        # Mesajdan gereksiz kelimeleri temizleyip arama yapalım
        clean_query = content.replace("bana", "").replace("nedir", "").replace("anlat", "").replace("hakkında", "").replace("bilgi", "").replace("ver", "").replace("konusunu", "").replace("konusu", "").replace("?", "").strip()
        
        if clean_query and len(clean_query) > 2:
            import urllib.parse
            search_url = 'https://tr.wikipedia.org/w/api.php'
            params = {'action': 'query', 'format': 'json', 'list': 'search', 'srsearch': clean_query, 'utf8': 1, 'srlimit': 1}
            headers = {'User-Agent': 'ReviseMeBot/1.0 (test@example.com)'}
            
            try:
                res = requests.get(search_url, params=params, headers=headers, timeout=5)
                data = res.json()
                if data.get('query', {}).get('search'):
                    title = data['query']['search'][0]['title']
                    title_enc = urllib.parse.quote(title)
                    summary_url = f'https://tr.wikipedia.org/api/rest_v1/page/summary/{title_enc}'
                    sum_res = requests.get(summary_url, headers=headers, timeout=5)
                    if sum_res.status_code == 200:
                        extract = sum_res.json().get('extract')
                        if extract:
                            response = f"<b>{title}:</b><br>{extract}<br><br><span style='font-size: 10px; color: #888;'>(Kaynak: Vikipedi)</span>"
                        else:
                            response = 'Maalesef bu konu hakkında detaylı bir özet bulamadım.'
                    else:
                        response = 'Bu konu hakkında bilgi çekerken bir sorun oluştu.'
                else:
                    response = f'"{clean_query}" hakkında veri tabanında (Vikipedi) bir sonuç bulamadım. Başka bir terimle sormayı dener misin?'
            except Exception as e:
                response = 'Bilgi bankasına bağlanırken bir hata oluştu. Lütfen daha sonra tekrar dene.'
        else:
            response = 'EduAI şu anda temel sorulara yanıt verebiliyor. "Mitoz bölünmeyi anlat", "Logaritma nedir?" gibi konuları sorabilir veya uygulamanın kullanımı hakkında bilgi alabilirsin.'
        
    return jsonify({'ai_response': response})

    # MSSQL'de rastgele sıralama için NEWID() kullanılır. (Eğer hata verirse func.random() ile değiştirilebilir)
    try:
        questions = Question.query.filter_by(UserId=current_user.UserId, IsHidden=False).order_by(db.func.NEWID()).limit(10).all()
    except:
        questions = Question.query.filter_by(UserId=current_user.UserId, IsHidden=False).limit(10).all()
        
    video_data = []
    default_videos = [
        "https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
        "https://storage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
        "https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4",
        "https://storage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
        "https://storage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4"
    ]
    
    for i, q in enumerate(questions):
        cat = Category.query.get(q.CategoryId)
        cat_name = cat.Name if cat else "Genel"
        diff = q.difficulty if q.difficulty else "Orta"
        title = q.topic if q.topic else f"Soru #{q.QuestionId}"
        content_text = q.content if q.content else "Soru detaylarına ulaşmak için sisteme göz atın."
        
        video_data.append({
            'id': q.QuestionId,
            'title': title,
            'content': content_text,
            'category': cat_name,
            'difficulty': diff,
            'videoUrl': default_videos[i % len(default_videos)],
            'likes': f"{random.randint(10, 99)}.{random.randint(1,9)}K",
            'bookmarks': f"{random.randint(1, 9)}.{random.randint(1,9)}K",
            'imagePath': url_for('static', filename=q.ImagePath) if q.ImagePath else None
        })
        
    # Eğer hiç soru yoksa boş kalmaması için örnek data ekleyelim
    if not video_data:
        video_data = [
            {
                'id': 1,
                'videoUrl': "https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
                'title': "Türev Alma Kuralları: Çarpım Kuralı",
                'content': "Henüz sisteme bir soru eklemedin! Örnek içerik görüntülüyorsun.",
                'category': "Matematik",
                'difficulty': "Orta",
                'likes': "12.4K",
                'bookmarks': "3.2K",
                'imagePath': None
            }
        ]
        
    return render_template('shorts_feed.html', video_data=video_data)


# ─────────────────────────────────────────────
#  SORU ÇÖZ  –  /api/solve-image  (POST)
# ─────────────────────────────────────────────

def _compress_image(pil_img, max_dim=1280, quality=85):
    """Görsel boyutunu sınırla ve JPEG olarak sıkıştır."""
    w, h = pil_img.size
    if max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        pil_img = pil_img.resize((int(w * ratio), int(h * ratio)), PIL.Image.LANCZOS)
    # RGB'ye dönüştür (PNG/RGBA gibi kanallar için)
    if pil_img.mode not in ("RGB", "L"):
        pil_img = pil_img.convert("RGB")
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return PIL.Image.open(buf)


@app.route('/soru-coz')
@login_required
def soru_coz():
    return render_template('soru_coz.html', show_sidebar=True, section='sorucoz')


@app.route('/api/solve-image', methods=['POST'])
@login_required
def solve_image():
    import json as _json
    import re as _re
    from google import genai as new_genai
    from google.genai import types as genai_types

    file = request.files.get('image')
    if not file or not file.filename:
        return jsonify({"error": "Lütfen bir görsel yükleyin."}), 400

    # Desteklenen formatları kontrol et
    allowed_ext = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_ext:
        return jsonify({"error": f"Desteklenmeyen dosya formatı: .{ext}. PNG, JPG, WEBP kullanabilirsiniz."}), 400

    try:
        pil_img = PIL.Image.open(file.stream)
    except Exception:
        return jsonify({"error": "Görsel okunamadı. Lütfen geçerli bir resim dosyası yükleyin."}), 400

    # Büyükse sıkıştır, ardından bytes'a çevir
    try:
        pil_img = _compress_image(pil_img)
        img_buf = io.BytesIO()
        pil_img.save(img_buf, format="JPEG")
        img_bytes = img_buf.getvalue()
    except Exception as e:
        return jsonify({"error": f"Görsel işlenirken hata oluştu: {str(e)}"}), 500

    prompt = (
        "Bu görseldeki soruyu tespit et. "
        "Soruyu metne dök, konusunu ve dersini belirle, zorluk seviyesini tahmin et, adım adım detaylı çözümünü yap. "
        "Ders (subject) için Trkçe ders adı kullan: Matematik, Fizik, Kimya, Biyoloji, Tarih, Coğrafya, Türk Dili ve Edebiyatı, Felsefe, Din, Yabancı Dil. "
        "Zorluk (difficulty) için: kolay, orta veya zor. "
        "Yanıtı SADECE şu JSON formatında döndür, başka hiçbir metin ekleme:\n"
        '{"detected_text": "...", "subject": "Matematik", "topic": "...", "difficulty": "orta", '
        '"solution_steps": ["Adım 1...", "Adım 2..."], "final_answer": "..."}'
    )

    # Yeni google.genai SDK ile gönder (v1 API — görsel destekli)
    try:
        client = new_genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
            ]
        )
        raw = response.text.strip()
    except Exception as e:
        err_str = str(e)
        if "404" in err_str or "not found" in err_str.lower():
            return jsonify({"error": "Seçilen AI modeli desteklenmiyor. Lütfen model ayarlarını kontrol edin."}), 502
        if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
            return jsonify({"error": "API istek limiti aşıldı. Lütfen birkaç saniye bekleyip tekrar deneyin."}), 429
        return jsonify({"error": f"Gemini API hatası: {err_str}"}), 502

    # JSON'u temizle ve ayrıştır
    json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
    if not json_match:
        return jsonify({"error": "Yapay zeka yanıtı işlenemedi. Lütfen tekrar deneyin.", "raw": raw}), 500

    try:
        result = _json.loads(json_match.group(0))
    except _json.JSONDecodeError as e:
        return jsonify({"error": f"JSON ayrıştırma hatası: {str(e)}", "raw": raw}), 500

    # Zorunlu alanlar kontrolü
    for field in ("detected_text", "subject", "topic", "difficulty", "solution_steps", "final_answer"):
        if field not in result:
            if field == "solution_steps":
                result[field] = []
            elif field == "subject":
                result[field] = "Genel"
            elif field == "difficulty":
                result[field] = "orta"
            else:
                result[field] = ""

    return jsonify(result)


@app.route('/api/save-solved-question', methods=['POST'])
@login_required
def save_solved_question():
    """Soru Çöz sayfasından analiz edilen soruyu soru havuzuna kaydeder."""
    import json as _json

    # --- Form verilerini al ---
    detected_text = request.form.get('detected_text', '').strip()
    subject_name  = request.form.get('subject', 'Genel').strip()
    topic         = request.form.get('topic', '').strip()
    difficulty    = request.form.get('difficulty', 'orta').strip()
    solution_steps_raw = request.form.get('solution_steps', '[]')
    final_answer  = request.form.get('final_answer', '').strip()
    file          = request.files.get('image')

    if not detected_text:
        return jsonify({"error": "Soru metni boş olamaz."}), 400

    # --- Kategori eşleştir ---
    category = Category.query.filter(
        db.func.lower(Category.Name).contains(subject_name.lower())
    ).first()
    # Tam eşleşme yoksa keyword bazında dene
    if not category:
        keyword_map = {
            "matematik": "Matematik", "fizik": "Fizik", "kimya": "Kimya",
            "biyoloji": "Biyoloji", "tarih": "Tarih", "coğrafya": "Coğrafya",
            "edebiyat": "Türk Dili ve Edebiyatı", "felsefe": "Felsefe",
            "din": "Din", "dil": "Yabancı Dil", "ingilizce": "Yabancı Dil"
        }
        subject_lower = subject_name.lower()
        for kw, cat_name in keyword_map.items():
            if kw in subject_lower:
                category = Category.query.filter_by(Name=cat_name).first()
                if category:
                    break
    if not category:
        category = Category.query.first()  # Fallback: ilk kategori
    if not category:
        return jsonify({"error": "Kategori bulunamadı. Lütfen önce kategori oluşturun."}), 500

    # --- Görseli kaydet ---
    image_path = None
    if file and file.filename:
        try:
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
            unique_name = f"{uuid.uuid4().hex}_solved.{ext}"
            save_dir = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(save_dir, exist_ok=True)
            full_path = os.path.join(save_dir, unique_name)
            file.save(full_path)
            image_path = f"uploads/{unique_name}"
        except Exception as e:
            print(f"Image save error: {e}")

    # --- Açıklama oluştur (JSON formatında — görüntüleme için zengin) ---
    try:
        steps = _json.loads(solution_steps_raw)
    except Exception:
        steps = []
    explanation_data = {
        "detected_text": detected_text, # Metni burada saklıyoruz
        "subject": subject_name,
        "topic": topic,
        "steps": steps,
        "final_answer": final_answer
    }
    explanation = _json.dumps(explanation_data, ensure_ascii=False)

    # --- Tekrar tarihleri (kullanıcı ayarına göre) ---
    now = datetime.now()
    user_settings = UserSettings.query.filter_by(UserId=current_user.UserId).first()
    interval = user_settings.RepeatInterval if user_settings and user_settings.RepeatInterval else 1
    repeat1_date = now
    repeat2_date = now + timedelta(days=interval)
    repeat3_date = now + timedelta(days=interval * 2)

    # --- Question kaydı ---
    new_q = Question(
        UserId=current_user.UserId,
        content="", # Metni ana başlıktan kaldırıyoruz
        CategoryId=category.CategoryId,
        topic=topic,
        difficulty=difficulty,
        PhotoPath=None,
        IsCompleted=False,
        IsViewed=False,
        IsRepeated=False,
        RepeatCount=0,
        Repeat1Date=repeat1_date,
        Repeat2Date=repeat2_date,
        Repeat3Date=repeat3_date,
        Explanation=explanation,
        ImagePath=image_path,
        IsHidden=False
    )
    try:
        db.session.add(new_q)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Veritabanı hatası: {str(e)}"}), 500

    return jsonify({
        "success": True,
        "question_id": new_q.QuestionId,
        "category": category.Name,
        "repeat1": repeat1_date.strftime('%d.%m.%Y %H:%M'),
        "repeat2": repeat2_date.strftime('%d.%m.%Y'),
        "repeat3": repeat3_date.strftime('%d.%m.%Y'),
        "message": f"✅ Soru '{category.Name}' havuzuna eklendi! İlk tekrar: {repeat1_date.strftime('%d.%m.%Y %H:%M')}"
    })


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)

