
import pandas as pd
from datetime import datetime
import sqlite3
import io
import os
from io import BytesIO
import zipfile
import matplotlib.pyplot as plt
import hashlib
import streamlit as st
import mysql.connector
from mysql.connector import Error
from db import get_connection

def add_ingredient():
    st.header('Add New Ingredient')
    name = st.text_input('Ingredient Name')
    price = st.number_input('Price per Unit', min_value=0.0, step=0.00001, format="%.5f")
    unit = st.text_input('Unit (e.g., gram, liter, piece)')

    if st.button('Add Ingredient'):
        try:
            conn = get_connection()
            c = conn.cursor()

            c.execute(
                'INSERT INTO ingredients (name, price_per_unit, unit) VALUES (%s, %s, %s)',
                (name, price, unit)
            )
            conn.commit()
            st.success(f'Ingredient "{name}" added successfully!')

        except mysql.connector.IntegrityError:
            st.error("Ingredient already exists.")
        except mysql.connector.Error as err:
            st.error(f"MySQL Error: {err}")
        finally:
            if conn.is_connected():
                c.close()
                conn.close()

def add_sub_recipe():
    st.header('Add New Sub-Recipe')
    sub_recipe_name = st.text_input('Sub-Recipe Name')

    conn = get_connection()
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

            qty = st.number_input(f"Quantity for {item.split(' (')[0]}", min_value=0.0, step=0.001, format="%.3f", key=key)
            quantities[(item_id, item_type)] = qty

        if st.button('Save Sub-Recipe'):
            if sub_recipe_name and quantities:
                try:
                    conn = get_connection()
                    c = conn.cursor()
                    c.execute('INSERT INTO sub_recipes (name) VALUES (%s)', (sub_recipe_name,))
                    sub_recipe_id = c.lastrowid

                    for (item_id, item_type), qty in quantities.items():
                        if item_type == 'ingredient':
                            c.execute('INSERT INTO sub_recipe_ingredients (sub_recipe_id, ingredient_id, quantity) VALUES (%s, %s, %s)', (sub_recipe_id, item_id, qty))
                        elif item_type == 'subrecipe':
                            c.execute('INSERT INTO sub_recipe_nested (parent_sub_recipe_id, sub_recipe_id, quantity) VALUES (%s, %s, %s)', (sub_recipe_id, item_id, qty))

                    conn.commit()
                    st.success(f'Sub-Recipe "{sub_recipe_name}" added successfully!')
                except mysql.connector.IntegrityError:
                    st.error('Sub-Recipe already exists.')
                except mysql.connector.Error as err:
                    st.error(f"MySQL Error: {err}")
                finally:
                    if conn.is_connected():
                        c.close()
                        conn.close()
            else:
                st.error('Please provide a Sub-Recipe name and select items.')
    else:
        st.warning('No ingredients or sub-recipes available.')


def add_cake():
    st.header("Add New Cake")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name FROM ingredients")
    ingredients = c.fetchall()
    c.execute("SELECT id, name FROM sub_recipes")
    sub_recipes = c.fetchall()
    conn.close()

    cake_name = st.text_input("Cake Name")
    percent_yield = st.number_input("Percent Yield (%)", min_value=0.0, step=0.01, format="%.2f")

    all_items = [f"{i[1]} (Ingredient ID:{i[0]})" for i in ingredients] + \
                [f"{s[1]} (Sub-Recipe ID:{s[0]})" for s in sub_recipes]

    selected_items = st.multiselect("Select Ingredients or Sub-Recipes", all_items)

    quantities = {}
    for item in selected_items:
        if "Ingredient ID:" in item:
            item_id = int(item.split('Ingredient ID:')[1].replace(")", ""))
            key = f"ingredient_{item_id}"
            item_type = 'ingredient'
        else:
            item_id = int(item.split('Sub-Recipe ID:')[1].replace(")", ""))
            key = f"subrecipe_{item_id}"
            item_type = 'subrecipe'

        qty = st.number_input(f"Quantity for {item.split(' (')[0]}", min_value=0.0, step=0.00001, format="%.5f", key=key)
        quantities[(item_id, item_type)] = qty

    if st.button("Save Cake"):
        if not cake_name or not quantities:
            st.error("Please enter a cake name and at least one item.")
            return
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("INSERT INTO cakes (name, percent_yield) VALUES (%s, %s)", (cake_name, percent_yield))
            cake_id = c.lastrowid

            for (item_id, item_type), qty in quantities.items():
                is_sub = 1 if item_type == 'subrecipe' else 0
                c.execute("INSERT INTO cake_ingredients (cake_id, ingredient_or_subrecipe_id, is_subrecipe, quantity) VALUES (%s, %s, %s, %s)", (cake_id, item_id, is_sub, qty))

            conn.commit()
            st.success(f"Cake '{cake_name}' saved successfully!")
        except mysql.connector.Error as err:
            st.error(f"MySQL Error: {err}")
        finally:
            if conn.is_connected():
                c.close()
                conn.close()
