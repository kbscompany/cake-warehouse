import streamlit as st
st.set_page_config(page_title="KB's Cake Studio", layout='wide')  # Must be first Streamlit command
import pandas as pd
from datetime import datetime
import sqlite3
import io
import os
from io import BytesIO
import zipfile
import matplotlib.pyplot as plt
import hashlib
from Add_Items import add_cake, add_sub_recipe, add_ingredient
from Manage_Items import manage_sub_recipes, manage_cakes, manage_ingredients
from Quick_add import quick_add_cake, quick_add_sub_recipe
from Add_stock import update_stock
from view_cakes import view_costs, view_all_cakes
from Batch import batch_production
from Warehouse_functions import create_transfer_order_page, create_kitchen_batch_log_table, receive_transfer_order_page, manage_categories
from Warehouse_Reports import view_warehouse, transfer_dashboard_page, transfer_visual_dashboard_page, transfer_order_history_page, view_warehouse, stock_report

from auth_secrets import HASHED_PASSWORD





def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def check_password():
    def password_entered():
        if hash_password(st.session_state["password"]) == HASHED_PASSWORD:
            st.session_state["authenticated"] = True
            del st.session_state["password"]
        else:
            st.session_state["authenticated"] = False

    if "authenticated" not in st.session_state:
        st.title("🔐 Secure Login")
        st.text_input("Enter password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["authenticated"]:
        st.error("❌ Incorrect password")
        return False
    else:
        return True


# ---------- DATABASE SETUP ----------
DB_PATH = 'bakery.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, price_per_unit REAL, unit TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sub_recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sub_recipe_ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, sub_recipe_id INTEGER, ingredient_id INTEGER, quantity REAL, FOREIGN KEY(sub_recipe_id) REFERENCES sub_recipes(id), FOREIGN KEY(ingredient_id) REFERENCES ingredients(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS cakes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cake_ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, cake_id INTEGER, ingredient_or_subrecipe_id INTEGER, is_subrecipe BOOLEAN, quantity REAL, FOREIGN KEY(cake_id) REFERENCES cakes(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS sub_recipe_nested (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_sub_recipe_id INTEGER, sub_recipe_id INTEGER, quantity REAL, FOREIGN KEY(parent_sub_recipe_id) REFERENCES sub_recipes(id), FOREIGN KEY(sub_recipe_id) REFERENCES sub_recipes(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS warehouse (ingredient_id INTEGER PRIMARY KEY, quantity REAL DEFAULT 0, last_updated TEXT, FOREIGN KEY(ingredient_id) REFERENCES ingredients(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS stock_movements (id INTEGER PRIMARY KEY AUTOINCREMENT, ingredient_id INTEGER, change REAL, reason TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(ingredient_id) REFERENCES ingredients(id))''')

    def ensure_extended_warehouse_schema():
        # Nested to ensure full schema update
        c.execute('''CREATE TABLE IF NOT EXISTS inventory_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
        c.execute("PRAGMA table_info(warehouse)")
        cols = [row[1] for row in c.fetchall()]
        if "category_id" not in cols:
            c.execute("ALTER TABLE warehouse ADD COLUMN category_id INTEGER REFERENCES inventory_categories(id)")
        if "par_level" not in cols:
            c.execute("ALTER TABLE warehouse ADD COLUMN par_level REAL DEFAULT 0")

    ensure_extended_warehouse_schema()
    conn.commit()
    conn.close()


# ---------- MAIN APP ----------
def main():
    st.image('logo.png', width=200)
    st.title('KB’s Cake Studio')
    init_db()

    menu = [
        'Quick Add Cake',
        'Add Ingredient',
        'Add Sub-Recipe',
        'Quick Add Sub-Recipe',
        'Add Cake',
        'View Costs',
        'Batch Production',
        'Manage Ingredients',
        'Manage Sub-Recipes',
        'Manage Cakes',
        'Cake Report',
        'Warehouse Overview',
        'Manage Categories',
        'Update Stock',
        'Stock Report',
        'Stock Movements',
        'Transfer Orders',
        'Receive Transfers',
        'Transfer History',
        'Transfer Dashboard',
        'Transfer Charts',
        'Kitchen Production'
    ]

    choice = st.sidebar.selectbox('Navigation', menu)

    if "edit_cake_id" in st.session_state:
        cake_id = st.session_state.edit_cake_id
        del st.session_state.edit_cake_id
        add_cake(cake_id)
        return

    if choice == 'Quick Add Cake':
        quick_add_cake()
    elif choice == 'Add Ingredient':
        add_ingredient()
    elif choice == 'Add Sub-Recipe':
        add_sub_recipe()
    elif choice == 'Quick Add Sub-Recipe':
        quick_add_sub_recipe()
    elif choice == 'Add Cake':
        add_cake()
    elif choice == 'View Costs':
        view_costs()
    elif choice == 'Batch Production':
        batch_production()
    elif choice == 'Manage Ingredients':
        manage_ingredients()
    elif choice == 'Manage Sub-Recipes':
        manage_sub_recipes()
    elif choice == 'Manage Cakes':
        manage_cakes()
    elif choice == 'Cake Report':
        view_all_cakes()
    elif choice == 'Warehouse Overview':
        view_warehouse()
    elif choice == 'Update Stock':
        update_stock()
    elif choice == 'Stock Report':
        stock_report()
    elif choice == 'Manage Categories':
        manage_categories()
    elif choice == 'Transfer Orders':
        create_transfer_order_page()
    elif choice == 'Receive Transfers':
        receive_transfer_order_page()
    elif choice == 'Transfer History':
        transfer_order_history_page()
    elif choice == 'Transfer Dashboard':
        transfer_dashboard_page()
    elif choice == 'Transfer Charts':
        transfer_visual_dashboard_page()


# ---------- ENTRY POINT ----------
if __name__ == '__main__':
    if check_password():
        main()
