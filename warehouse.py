import streamlit as st
st.set_page_config(page_title="KB's Cake Studio", layout='wide')

import pandas as pd
from datetime import datetime
import io
from io import BytesIO
import zipfile
import matplotlib.pyplot as plt
import hashlib
import socket
import os
from dotenv import load_dotenv

from Add_Items import add_cake, add_sub_recipe, add_ingredient
from Manage_Items import manage_sub_recipes, manage_cakes, manage_ingredients
from Quick_add import quick_add_cake, quick_add_sub_recipe
from Add_stock import update_stock
from view_cakes import view_costs, view_all_cakes
from Batch import batch_production
from Warehouse_functions import create_transfer_order_page, create_kitchen_batch_log_table, receive_transfer_order_page, manage_categories
from Warehouse_Reports import view_warehouse, transfer_dashboard_page, transfer_visual_dashboard_page, transfer_order_history_page, stock_report

import sys
sys.path.append('/home/ec2-user/.config/cake_warehouse')
from auth_secrets import HASHED_PASSWORD
from db import get_connection

load_dotenv()

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

def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS ingredients (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) UNIQUE,
        price_per_unit DECIMAL(10,2),
        unit VARCHAR(50)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sub_recipes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) UNIQUE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sub_recipe_ingredients (
        id INT AUTO_INCREMENT PRIMARY KEY,
        sub_recipe_id INT,
        ingredient_id INT,
        quantity DECIMAL(10,2),
        FOREIGN KEY(sub_recipe_id) REFERENCES sub_recipes(id),
        FOREIGN KEY(ingredient_id) REFERENCES ingredients(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS cakes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) UNIQUE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS cake_ingredients (
        id INT AUTO_INCREMENT PRIMARY KEY,
        cake_id INT,
        ingredient_or_subrecipe_id INT,
        is_subrecipe BOOLEAN,
        quantity DECIMAL(10,2),
        FOREIGN KEY(cake_id) REFERENCES cakes(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sub_recipe_nested (
        id INT AUTO_INCREMENT PRIMARY KEY,
        parent_sub_recipe_id INT,
        sub_recipe_id INT,
        quantity DECIMAL(10,2),
        FOREIGN KEY(parent_sub_recipe_id) REFERENCES sub_recipes(id),
        FOREIGN KEY(sub_recipe_id) REFERENCES sub_recipes(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS warehouse (
        ingredient_id INT PRIMARY KEY,
        quantity DECIMAL(10,2) DEFAULT 0,
        last_updated DATETIME,
        category_id INT,
        par_level DECIMAL(10,2),
        FOREIGN KEY(ingredient_id) REFERENCES ingredients(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS stock_movements (
        id INT AUTO_INCREMENT PRIMARY KEY,
        ingredient_id INT,
        `change` DECIMAL(10,2),
        reason TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(ingredient_id) REFERENCES ingredients(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS inventory_categories (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) UNIQUE
    )''')

    conn.commit()
    conn.close()

def main():
    st.image('logo.png', width=200)
    st.title('KB’s Cake Studio')

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DATABASE();")
        db = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM ingredients;")
        count = cursor.fetchone()[0]

        st.success(f"✅ Connected to MySQL DB: `{db}` on host `{os.getenv('MYSQL_HOST')}`")
        st.info(f"Ingredients count: {count}")
        st.text(f"Server: {socket.gethostname()}")
    except Exception as e:
        st.error(f"❌ MySQL connection failed: {e}")

    init_db()

    menu = [
        'Quick Add Cake', 'Add Ingredient', 'Add Sub-Recipe', 'Quick Add Sub-Recipe', 'Add Cake',
        'View Costs', 'Batch Production', 'Manage Ingredients', 'Manage Sub-Recipes', 'Manage Cakes',
        'Cake Report', 'Warehouse Overview', 'Manage Categories', 'Update Stock', 'Stock Report',
        'Stock Movements', 'Transfer Orders', 'Receive Transfers', 'Transfer History',
        'Transfer Dashboard', 'Transfer Charts', 'Kitchen Production'
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

if __name__ == '__main__':
    if check_password():
        main()
