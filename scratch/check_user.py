import pyodbc
import urllib

driver = "ODBC Driver 17 for SQL Server"
server = "MSI\\SQLK"
database = "ReviseMe"
connection_string = f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;TrustServerCertificate=yes;"

try:
    conn = pyodbc.connect(connection_string)
    cursor = conn.cursor()
    cursor.execute("SELECT TOP 1 UserName, Email, SecurityQuestion, SecurityAnswer FROM Users ORDER BY UserId DESC")
    row = cursor.fetchone()
    if row:
        print(f"Son Kayıtlı Kullanıcı: {row.UserName}")
        print(f"Email: {row.Email}")
        print(f"Soru: {row.SecurityQuestion}")
        print(f"Cevap: {row.SecurityAnswer}")
    else:
        print("Kullanıcı bulunamadı.")
finally:
    if 'conn' in locals():
        conn.close()
