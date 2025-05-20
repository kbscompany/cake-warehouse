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

DB_PATH = 'bakery.db'
def add_ingredient():
    st.header('Add New Ingredient')
    name = st.text_input('Ingredient Name')
    price = st.number_input('Price per Unit', min_value=0.0, step=0.00001, format="%.5f")

    unit = st.text_input('Unit (e.g., gram, liter, piece)')

    if st.button('Add Ingredient'):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute('INSERT INTO ingredients (name, price_per_unit, unit) VALUES (?, ?, ?)', (name, price, unit))
            conn.commit()
            st.success(f'Ingredient {name} added successfully!')
        except sqlite3.IntegrityError:
            st.error('Ingredient already exists.')
        conn.close()

def add_sub_recipe():
    st.header('Add New Sub-Recipe')
    sub_recipe_name = st.text_input('Sub-Recipe Name')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, name FROM ingredients')
    ingredients = c.fetchall()
    c.execute('SELECT id, name FROM sub_recipes')
    sub_recipes = c.fetchall()
    conn.close()

    options = [f"{i[1]} (Ingredient ID:{i[0]})" for i in ingredients] + [
        f"{s[1]} (Sub-Recipe ID:{s[0]})" for s in sub_recipes if sub_recipe_name not in s[1]
    ]

    if options:
        selected_items = st.multiselect('Select Ingredients or Sub-Recipes for Sub-Recipe', options=options)
        quantities = {}

        for item in selected_items:
            if "Ingredient ID:" in item:
                item_id = int(item.split('(Ingredient ID:')[1].replace(')', ''))
                key = f"ingredient_{item_id}"
                item_type = 'ingredient'
            else:
                item_id = int(item.split('(Sub-Recipe ID:')[1].replace(')', ''))
                key = f"subrecipe_{item_id}"
                item_type = 'subrecipe'

            qty = st.number_input(
                f"Quantity for {item.split(' (')[0]}",
                min_value=0.0,
                step=0.001,
                format="%.3f",
                key=key
            )
            quantities[(item_id, item_type)] = qty

        if st.button('Save Sub-Recipe'):
            if sub_recipe_name and quantities:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                try:
                    c.execute('''
                        CREATE TABLE IF NOT EXISTS sub_recipe_nested (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            parent_sub_recipe_id INTEGER,
                            sub_recipe_id INTEGER,
                            quantity REAL,
                            FOREIGN KEY (parent_sub_recipe_id) REFERENCES sub_recipes(id),
                            FOREIGN KEY (sub_recipe_id) REFERENCES sub_recipes(id)
                        )
                    ''')
                    c.execute('INSERT INTO sub_recipes (name) VALUES (?)', (sub_recipe_name,))
                    sub_recipe_id = c.lastrowid

                    for (item_id, item_type), qty in quantities.items():
                        if item_type == 'ingredient':
                            c.execute('''
                                INSERT INTO sub_recipe_ingredients (sub_recipe_id, ingredient_id, quantity)
                                VALUES (?, ?, ?)
                            ''', (sub_recipe_id, item_id, qty))
                        elif item_type == 'subrecipe':
                            c.execute('''
                                INSERT INTO sub_recipe_nested (parent_sub_recipe_id, sub_recipe_id, quantity)
                                VALUES (?, ?, ?)
                            ''', (sub_recipe_id, item_id, qty))

                    conn.commit()
                    st.success(f'Sub-Recipe "{sub_recipe_name}" added successfully!')
                except sqlite3.IntegrityError:
                    st.error('Sub-Recipe already exists.')
                conn.close()
            else:
                st.error('Please provide a Sub-Recipe name and select items.')
    else:
        st.warning('No ingredients or sub-recipes available.')

def add_cake(cake_id=None):
    st.header("Add New Cake" if not cake_id else "Edit Cake")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    cake_name = ""
    percent_yield = 0.0
    existing_ingredients = []

    if cake_id:
        c.execute("SELECT name, percent_yield FROM cakes WHERE id = ?", (cake_id,))
        row = c.fetchone()
        if row:
            cake_name, percent_yield = row
            c.execute('SELECT ingredient_or_subrecipe_id, is_subrecipe, quantity FROM cake_ingredients WHERE cake_id = ?', (cake_id,))
            existing_ingredients = c.fetchall()
        else:
            st.error("Cake not found.")
            conn.close()
            return

    c.execute("SELECT id, name FROM ingredients")
    ingredient_options = c.fetchall()
    c.execute("SELECT id, name FROM sub_recipes")
    sub_recipe_options = c.fetchall()
    c.execute("SELECT id, name FROM cakes WHERE id != ?", (cake_id if cake_id else -1,))
    cake_options = c.fetchall()
    conn.close()

    cake_name = st.text_input("Cake Name", value=cake_name)
    percent_yield = st.number_input("Percent Yield (%)", min_value=0.0, step=0.01, format="%.2f", value=percent_yield)

    all_items = [f"{i[1]} (Ingredient ID:{i[0]})" for i in ingredient_options] + \
                [f"{s[1]} (Sub-Recipe ID:{s[0]})" for s in sub_recipe_options] + \
                [f"{c[1]} (Cake ID:{c[0]})" for c in cake_options]

    selected_items = st.multiselect("Select Ingredients, Sub-Recipes, or Other Cakes", all_items)

    quantities = {}
    for item in selected_items:
        if "Ingredient ID:" in item:
            item_id = int(item.split('Ingredient ID:')[1].replace(")", ""))
            key = f"ingredient_{item_id}"
            item_type = 'ingredient'
        elif "Sub-Recipe ID:" in item:
            item_id = int(item.split('Sub-Recipe ID:')[1].replace(")", ""))
            key = f"subrecipe_{item_id}"
            item_type = 'subrecipe'
        else:
            item_id = int(item.split('Cake ID:')[1].replace(")", ""))
            key = f"cake_{item_id}"
            item_type = 'cake'

        default_qty = 0.0
        for eid, is_sub, qty in existing_ingredients:
            if eid == item_id and ((is_sub and item_type == 'subrecipe') or (not is_sub and item_type == 'ingredient')):
                default_qty = qty
                break

        qty = st.number_input(f"Quantity for {item.split(' (')[0]}", min_value=0.0, step=0.00001, format="%.5f", key=key, value=default_qty)
        quantities[(item_id, item_type)] = qty

    # === Cost Estimation (same as your original logic) ===
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total_cost = 0
    for (item_id, item_type), qty in quantities.items():
        if item_type == 'ingredient':
            c.execute('SELECT price_per_unit FROM ingredients WHERE id = ?', (item_id,))
            price = c.fetchone()[0]
            total_cost += qty * price
        elif item_type == 'subrecipe':
            c.execute('SELECT sri.ingredient_id, sri.quantity, i.price_per_unit FROM sub_recipe_ingredients sri JOIN ingredients i ON sri.ingredient_id = i.id WHERE sri.sub_recipe_id = ?', (item_id,))
            sub_ings = c.fetchall()
            c.execute('SELECT SUM(quantity) FROM sub_recipe_ingredients WHERE sub_recipe_id = ?', (item_id,))
            total_weight = c.fetchone()[0]
            if total_weight:
                for ing_id, ing_qty, price in sub_ings:
                    total_cost += (ing_qty / total_weight) * qty * price
        elif item_type == 'cake':
            c.execute('SELECT ingredient_or_subrecipe_id, is_subrecipe, quantity FROM cake_ingredients WHERE cake_id = ?', (item_id,))
            parts = c.fetchall()
            for iid, is_sub, quantity in parts:
                if is_sub:
                    c.execute('SELECT sri.ingredient_id, sri.quantity, i.price_per_unit FROM sub_recipe_ingredients sri JOIN ingredients i ON sri.ingredient_id = i.id WHERE sri.sub_recipe_id = ?', (iid,))
                    sub_ings = c.fetchall()
                    c.execute('SELECT SUM(quantity) FROM sub_recipe_ingredients WHERE sub_recipe_id = ?', (iid,))
                    total_weight = c.fetchone()[0]
                    if total_weight:
                        for ing_id, ing_qty, price in sub_ings:
                            total_cost += (ing_qty / total_weight) * quantity * qty * price
                else:
                    c.execute('SELECT price_per_unit FROM ingredients WHERE id = ?', (iid,))
                    price = c.fetchone()[0]
                    total_cost += quantity * qty * price
    conn.close()

    adjusted_cost = total_cost * (1 + percent_yield / 100)
    st.success(f"Estimated Cake Cost with {percent_yield:.2f}% Yield: {round(adjusted_cost, 2)}")

    # === Save ===
    if st.button("Save Cake"):
        if not cake_name or not quantities:
            st.error("Please enter a cake name and at least one item.")
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            if not cake_id:
                c.execute("INSERT INTO cakes (name, percent_yield) VALUES (?, ?)", (cake_name, percent_yield))
                cake_id = c.lastrowid
            else:
                c.execute("UPDATE cakes SET name = ?, percent_yield = ? WHERE id = ?", (cake_name, percent_yield, cake_id))
                c.execute("DELETE FROM cake_ingredients WHERE cake_id = ?", (cake_id,))

            for (item_id, item_type), qty in quantities.items():
                if item_type == 'ingredient':
                    c.execute("INSERT INTO cake_ingredients (cake_id, ingredient_or_subrecipe_id, is_subrecipe, quantity) VALUES (?, ?, 0, ?)", (cake_id, item_id, qty))
                elif item_type == 'subrecipe':
                    c.execute("INSERT INTO cake_ingredients (cake_id, ingredient_or_subrecipe_id, is_subrecipe, quantity) VALUES (?, ?, 1, ?)", (cake_id, item_id, qty))
                elif item_type == 'cake':
                    c.execute('SELECT ingredient_or_subrecipe_id, is_subrecipe, quantity FROM cake_ingredients WHERE cake_id = ?', (item_id,))
                    parts = c.fetchall()
                    for iid, is_sub, part_qty in parts:
                        c.execute("INSERT INTO cake_ingredients (cake_id, ingredient_or_subrecipe_id, is_subrecipe, quantity) VALUES (?, ?, ?, ?)", (cake_id, iid, is_sub, qty * part_qty))
            conn.commit()
            st.success(f"Cake '{cake_name}' saved successfully!")
        except sqlite3.IntegrityError:
            st.error("Cake already exists.")
        conn.close()

        def add_sub_recipe():
            st.header('Add New Sub-Recipe')
            sub_recipe_name = st.text_input('Sub-Recipe Name')

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('SELECT id, name FROM ingredients')
            ingredients = c.fetchall()
            c.execute('SELECT id, name FROM sub_recipes')
            sub_recipes = c.fetchall()
            conn.close()

            options = [f"{i[1]} (Ingredient ID:{i[0]})" for i in ingredients] + [f"{s[1]} (Sub-Recipe ID:{s[0]})" for s
                                                                                 in sub_recipes if
                                                                                 sub_recipe_name not in s[1]]

            if options:
                selected_items = st.multiselect('Select Ingredients or Sub-Recipes for Sub-Recipe', options=options)
                quantities = {}

                for item in selected_items:
                    if "Ingredient ID:" in item:
                        item_id = int(item.split('(Ingredient ID:')[1].replace(')', ''))
                        key = f"ingredient_{item_id}"
                        item_type = 'ingredient'
                    else:
                        item_id = int(item.split('(Sub-Recipe ID:')[1].replace(')', ''))
                        key = f"subrecipe_{item_id}"
                        item_type = 'subrecipe'

                    qty = st.number_input(f"Quantity for {item.split(' (')[0]}", min_value=0.0, step=0.001,
                                          format="%.3f", key=key)
                    quantities[(item_id, item_type)] = qty

                if st.button('Save Sub-Recipe'):
                    if sub_recipe_name and quantities:
                        conn = sqlite3.connect(DB_PATH)
                        c = conn.cursor()
                        try:
                            c.execute(
                                'CREATE TABLE IF NOT EXISTS sub_recipe_nested (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_sub_recipe_id INTEGER, sub_recipe_id INTEGER, quantity REAL, FOREIGN KEY (parent_sub_recipe_id) REFERENCES sub_recipes(id), FOREIGN KEY (sub_recipe_id) REFERENCES sub_recipes(id))')
                            c.execute('INSERT INTO sub_recipes (name) VALUES (?)', (sub_recipe_name,))
                            sub_recipe_id = c.lastrowid

                            for (item_id, item_type), qty in quantities.items():
                                if item_type == 'ingredient':
                                    c.execute(
                                        'INSERT INTO sub_recipe_ingredients (sub_recipe_id, ingredient_id, quantity) VALUES (?, ?, ?)',
                                        (sub_recipe_id, item_id, qty))
                                elif item_type == 'subrecipe':
                                    c.execute(
                                        'INSERT INTO sub_recipe_nested (parent_sub_recipe_id, sub_recipe_id, quantity) VALUES (?, ?, ?)',
                                        (sub_recipe_id, item_id, qty))

                            conn.commit()
                            st.success(f'Sub-Recipe {sub_recipe_name} added successfully!')
                        except sqlite3.IntegrityError:
                            st.error('Sub-Recipe already exists.')
                        conn.close()
                    else:
                        st.error('Please provide a Sub-Recipe name and select items.')
            else:
                st.warning('No ingredients or sub-recipes available.')

                def add_ingredient():
                    st.header('Add New Ingredient')
                    name = st.text_input('Ingredient Name')
                    price = st.number_input('Price per Unit', min_value=0.0, step=0.00001, format="%.5f")

                    unit = st.text_input('Unit (e.g., gram, liter, piece)')

                    if st.button('Add Ingredient'):
                        conn = sqlite3.connect(DB_PATH)
                        c = conn.cursor()
                        try:
                            c.execute('INSERT INTO ingredients (name, price_per_unit, unit) VALUES (?, ?, ?)',
                                      (name, price, unit))
                            conn.commit()
                            st.success(f'Ingredient {name} added successfully!')
                        except sqlite3.IntegrityError:
                            st.error('Ingredient already exists.')
                        conn.close()
