from dotenv import load_dotenv; load_dotenv()
import pyodbc

conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=MSI\\SQLK;'
    'DATABASE=ReviseMe;'
    'Trusted_Connection=yes'
)
cursor = conn.cursor()

# Kolon var mi kontrol et
cursor.execute("""
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_NAME='Questions' AND COLUMN_NAME='FailedAttempts'
""")
exists = cursor.fetchone()[0]

if not exists:
    cursor.execute("ALTER TABLE Questions ADD FailedAttempts INT DEFAULT 0 NOT NULL")
    conn.commit()
    print("FailedAttempts column ADDED successfully!")
else:
    print("Column already exists.")

conn.close()
