from app import app, db
from sqlalchemy import text

def update_db():
    with app.app_context():
        # Eklenecek sütunlar
        cols = [
            "content TEXT",
            "topic VARCHAR(100)",
            "difficulty VARCHAR(50)",
            "status VARCHAR(50)",
            "answer TEXT"
        ]
        
        for col in cols:
            try:
                db.session.execute(text(f"ALTER TABLE Questions ADD {col}"))
                db.session.commit()
                print(f"Sütun eklendi: {col}")
            except Exception as e:
                db.session.rollback()
                print(f"Hata (muhtemelen sütun zaten var): {col}")

if __name__ == "__main__":
    update_db()
