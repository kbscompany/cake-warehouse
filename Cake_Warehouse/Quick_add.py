import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3
import io
import os
from io import BytesIO
import zipfile
import matplotlib.pyplot as plt
import hashlib
from config import DB_PATH
def quick_add_cake():
    st.header('Quick Add Cake from Excel Paste')
    cake_name = st.text_input('Cake Name')
    paste_data = st.text_area('Paste Ingredients/Sub-Recipes and Quantities (e.g., Chocolate Base	1.2)', height=300)

    if st.button('Save Quick Cake'):
        if not cake_name or not paste_data.strip():
            st.error('Please provide a name and paste data.')
            return

        rows = paste_data.strip().split('\n')
        parsed_rows = []
        for row in rows:
            row = row.strip()
            if '\t' in row:
                parts = row.split('\t')
            else:
                parts = row.rsplit(' ', 1)
            if len(parts) != 2:
                st.error(f"Invalid row format: {row}")
                return
            try:
                name = parts[0].strip()
                quantity = float(parts[1].strip())
                parsed_rows.append((name, quantity))
            except ValueError:
                st.error(f"Invalid quantity in row: {row}")
                return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute('INSERT INTO cakes (name) VALUES (?)', (cake_name,))
            cake_id = c.lastrowid
            for name, qty in parsed_rows:
                c.execute('SELECT id FROM ingredients WHERE name = ?', (name,))
                ing = c.fetchone()
                if ing:
                    c.execute('INSERT INTO cake_ingredients (cake_id, ingredient_or_subrecipe_id, is_subrecipe, quantity) VALUES (?, ?, 0, ?)', (cake_id, ing[0], qty))
                else:
                    c.execute('SELECT id FROM sub_recipes WHERE name = ?', (name,))
                    sub = c.fetchone()
                    if sub:
                        c.execute('INSERT INTO cake_ingredients (cake_id, ingredient_or_subrecipe_id, is_subrecipe, quantity) VALUES (?, ?, 1, ?)', (cake_id, sub[0], qty))
                    else:
                        st.error(f'Item "{name}" not found as Ingredient or Sub-Recipe.')
                        conn.rollback()
                        conn.close()
                        return
            conn.commit()
            st.success(f'Cake {cake_name} saved successfully!')
            st.balloons()
        except sqlite3.IntegrityError:
            st.error('Cake already exists.')
        conn.close()

def quick_add_sub_recipe():
    st.header('Quick Add Sub-Recipe from Excel Paste')
    sub_recipe_name = st.text_input('Sub-Recipe Name')
    paste_data = st.text_area('Paste Ingredients/Sub-Recipes and Quantities (e.g., Egg\t110.47)', height=300)

    if st.button('Save Quick Sub-Recipe'):
        if not sub_recipe_name or not paste_data.strip():
            st.error('Please provide a name and paste data.')
            return

        rows = paste_data.strip().split('\n')
        parsed_rows = []
        for row in rows:
            row = row.strip()
            if '\t' in row:
                parts = row.split('\t')
            else:
                parts = row.rsplit(' ', 1)
            if len(parts) != 2:
                st.error(f"Invalid row format: {row}")
                return
            try:
                name = parts[0].strip()
                quantity = float(parts[1].strip())
                parsed_rows.append((name, quantity))
            except ValueError:
                st.error(f"Invalid quantity in row: {row}")
                return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute('CREATE TABLE IF NOT EXISTS sub_recipe_nested (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_sub_recipe_id INTEGER, sub_recipe_id INTEGER, quantity REAL, FOREIGN KEY (parent_sub_recipe_id) REFERENCES sub_recipes(id), FOREIGN KEY (sub_recipe_id) REFERENCES sub_recipes(id))')
            c.execute('INSERT INTO sub_recipes (name) VALUES (?)', (sub_recipe_name,))
            sub_recipe_id = c.lastrowid

            for item_name, qty in parsed_rows:
                c.execute('SELECT id FROM ingredients WHERE name = ?', (item_name,))
                row = c.fetchone()
                if row:
                    c.execute('INSERT INTO sub_recipe_ingredients (sub_recipe_id, ingredient_id, quantity) VALUES (?, ?, ?)', (sub_recipe_id, row[0], qty))
                else:
                    c.execute('SELECT id FROM sub_recipes WHERE name = ?', (item_name,))
                    row = c.fetchone()
                    if row:
                        c.execute('INSERT INTO sub_recipe_nested (parent_sub_recipe_id, sub_recipe_id, quantity) VALUES (?, ?, ?)', (sub_recipe_id, row[0], qty))
                    else:
                        st.error(f'Item "{item_name}" not found as Ingredient or Sub-Recipe.')
                        conn.rollback()
                        conn.close()
                        return

            conn.commit()
            st.success(f'Sub-Recipe {sub_recipe_name} saved!')
            st.balloons()
        except sqlite3.IntegrityError:
            st.error('Sub-recipe already exists.')
        conn.close()