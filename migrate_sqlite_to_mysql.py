import sqlite3
import mysql.connector
from db import get_connection

# Path to your SQLite file
SQLITE_PATH = "bakery.db"

# Tables to migrate (must already exist in MySQL)
TABLES = [
    "ingredients",
    "sub_recipes",
    "sub_recipe_ingredients",
    "cakes",
    "cake_ingredients",
    "sub_recipe_nested",
    "warehouse",
    "stock_movements",
    "inventory_categories"
]

def migrate_table(table):
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_cur = sqlite_conn.cursor()

    mysql_conn = get_connection()
    mysql_cur = mysql_conn.cursor()

    sqlite_cur.execute(f"SELECT * FROM {table}")
    rows = sqlite_cur.fetchall()

    # Get column count to match insert placeholders
    col_count = len(sqlite_cur.description)
    placeholders = ", ".join(["%s"] * col_count)
    column_names = ", ".join([desc[0] for desc in sqlite_cur.description])

    insert_query = f"INSERT INTO {table} ({column_names}) VALUES ({placeholders})"

    for row in rows:
        try:
            mysql_cur.execute(insert_query, row)
        except Exception as e:
            print(f"❌ Error inserting into {table}: {e}\nRow: {row}")

    mysql_conn.commit()
    mysql_conn.close()
    sqlite_conn.close()
    print(f"✅ Migrated {len(rows)} rows to '{table}'")

if __name__ == "__main__":
    for table in TABLES:
        migrate_table(table)
