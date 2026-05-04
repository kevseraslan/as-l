import pyodbc
driver = "ODBC Driver 17 for SQL Server"
server = "MSI\\SQLK"
database = "ReviseMe"
connection_string = f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;TrustServerCertificate=yes;"

try:
    conn = pyodbc.connect(connection_string)
    cursor = conn.cursor()
    cursor.execute("SELECT Name FROM Categories")
    rows = cursor.fetchall()
    print("Kategoriler:")
    for row in rows:
        print(f"'{row.Name}'")
finally:
    if 'conn' in locals():
        conn.close()
