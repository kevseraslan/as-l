from app import app, db
from sqlalchemy import text

def add_column():
    with app.app_context():
        try:
            # Questions tablosuna created_at ekle (eğer yoksa)
            # MSSQL için:
            db.session.execute(text("ALTER TABLE Questions ADD created_at DATETIME DEFAULT GETDATE()"))
            db.session.commit()
            print("created_at sütunu başarıyla eklendi.")
        except Exception as e:
            db.session.rollback()
            # Eğer zaten varsa hata verecektir, bunu yakalayalım
            if "already an object named" in str(e) or "Column names in each table must be unique" in str(e) or "duplicate column name" in str(e).lower():
                print("Sütun zaten mevcut veya farklı bir hata: ", e)
            else:
                print("Hata oluştu: ", e)

if __name__ == "__main__":
    add_column()
