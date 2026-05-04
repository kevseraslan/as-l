import pyodbc
import urllib

# MSSQL bağlantı parametreleri
driver = "ODBC Driver 17 for SQL Server"
server = "MSI\\SQLK"
database = "ReviseMe"

connection_string = f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;TrustServerCertificate=yes;"

try:
    conn = pyodbc.connect(connection_string)
    cursor = conn.cursor()
    
    print("Veritabanına bağlanıldı. Sütun ekleniyor...")
    
    # SecurityAnswer sütununu ekle
    cursor.execute("ALTER TABLE Users ADD SecurityAnswer NVARCHAR(200);")
    
    conn.commit()
    print("SecurityAnswer sütunu başarıyla eklendi!")
    
except Exception as e:
    print(f"Hata oluştu: {str(e)}")
    if "already exists" in str(e).lower() or "42S21" in str(e):
        print("Sütun zaten mevcut görünüyor.")
finally:
    if 'conn' in locals():
        conn.close()
