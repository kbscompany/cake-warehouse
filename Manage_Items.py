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
import mysql.connector
from mysql.connector import Error
from db import get_connection
def manage_ingredients():
    st.header('Manage Ingredients')
    conn = get_connection()
    c = conn.cursor()
    search_term = st.text_input('Search Ingredients')

    if search_term:
        query = "SELECT id, name, price_per_unit, unit FROM ingredients WHERE name LIKE %s"
        c.execute(query, (f"%{search_term}%",))
    else:
        query = "SELECT id, name, price_per_unit, unit FROM ingredients"
        c.execute(query)

    rows = c.fetchall()

    if rows:
        for ing_id, name, price, unit in rows:
            st.markdown(f"**{name}**")
            new_price = st.number_input(f"Price per Unit for {name}", value=float(price), step=0.00001, format="%.5f", key=f"price_{ing_id}")
            new_unit = st.text_input(f"Unit for {name}", value=unit, key=f"unit_{ing_id}")
            if st.button(f"Update {name}", key=f"update_{ing_id}"):
                c.execute("UPDATE ingredients SET price_per_unit = %s, unit = %s WHERE id = %s", (new_price, new_unit, ing_id))
                conn.commit()
                st.success(f"Updated {name} successfully!")
            if st.button(f"Delete {name}", key=f"delete_{ing_id}"):
                c.execute("DELETE FROM ingredients WHERE id = %s", (ing_id,))
                conn.commit()
                st.success(f"Deleted {name} successfully!")
    else:
        st.info("No ingredients found.")
    conn.close()

# View Costs (weight-adjusted sub-recipes)

import mysql.connector  # make sure this import is present

def manage_sub_recipes():
    st.header('Manage Sub-Recipes')
    conn = get_connection()
    c = conn.cursor()

    c.execute('SELECT id, name FROM sub_recipes')
    sub_recipes = c.fetchall()

    if sub_recipes:
        selected = st.selectbox('Select Sub-Recipe to Manage', [f"{s[1]} (ID:{s[0]})" for s in sub_recipes])
        sub_id = int(selected.split('(ID:')[1].replace(')', ''))

        c.execute('SELECT name FROM sub_recipes WHERE id = %s', (sub_id,))
        row = c.fetchone()
        if not row:
            st.error("Sub-recipe not found.")
            return

        st.write(f"**Sub-Recipe Name:** {row[0]}")

        c.execute('''
            SELECT sri.id, sri.quantity, i.name, i.unit, i.price_per_unit, i.id as ing_id
            FROM sub_recipe_ingredients sri
            JOIN ingredients i ON sri.ingredient_id = i.id
            WHERE sri.sub_recipe_id = %s
        ''', (sub_id,))
        ingredients = c.fetchall()

        st.subheader('Current Ingredients')
        total_cost = 0
        cost_breakdown = []

        for row_id, qty, name, unit, price, ing_id in ingredients:
            qty = float(qty)
            price = float(price)
            new_qty = st.number_input(f"{name} Quantity", min_value=0.0, step=0.1, format="%.2f", value=qty, key=f"qty_{ing_id}")
            item_cost = new_qty * price
            total_cost += item_cost
            cost_breakdown.append({"Ingredient": name, "Quantity": new_qty, "Unit": unit, "Cost": round(item_cost, 2)})
            st.markdown(f"<span style='color:green'>Estimated Cost for {name}: {item_cost:,.2f}</span>", unsafe_allow_html=True)

            if st.button(f"Update {name}", key=f"update_{row_id}_sub"):
                c.execute('UPDATE sub_recipe_ingredients SET quantity = %s WHERE id = %s', (new_qty, row_id))
                conn.commit()
                st.success(f"Updated {name} quantity!")

            if st.button(f"Delete {name}", key=f"delete_{row_id}_sub"):
                c.execute('DELETE FROM sub_recipe_ingredients WHERE id = %s', (row_id,))
                conn.commit()
                st.success(f"Deleted {name} from Sub-Recipe!")

        st.subheader('Add New Ingredient or Sub-Recipe')
        c.execute('SELECT id, name, unit FROM ingredients')
        ingredient_list = c.fetchall()
        c.execute('SELECT id, name FROM sub_recipes WHERE id != %s', (sub_id,))
        sub_list = c.fetchall()

        options = [f"{i[1]} (Ingredient ID:{i[0]})" for i in ingredient_list] + [f"{s[1]} (Sub-Recipe ID:{s[0]})" for s in sub_list]

        selected_item = st.selectbox('Select Item', options, key='new_ing_or_sub')
        if 'Ingredient ID:' in selected_item:
            item_id = int(selected_item.split('(Ingredient ID:')[1].replace(')', ''))
            item_type = 'ingredient'
        else:
            item_id = int(selected_item.split('(Sub-Recipe ID:')[1].replace(')', ''))
            item_type = 'subrecipe'

        item_qty = st.number_input('Quantity (kg, L, etc)', min_value=0.0, step=0.00001, format="%.5f", key='qty_new_item_sub')

        if st.button('Add to Sub-Recipe'):
            try:
                if item_type == 'ingredient':
                    c.execute(
                        'INSERT INTO sub_recipe_ingredients (sub_recipe_id, ingredient_id, quantity) VALUES (%s, %s, %s)',
                        (sub_id, item_id, float(item_qty))
                    )
                else:
                    c.execute('SELECT ingredient_id, quantity FROM sub_recipe_ingredients WHERE sub_recipe_id = %s', (item_id,))
                    nested_parts = c.fetchall()
                    for ing_id, ing_qty in nested_parts:
                        flattened_qty = float(item_qty) * float(ing_qty)
                        c.execute(
                            'INSERT INTO sub_recipe_ingredients (sub_recipe_id, ingredient_id, quantity) VALUES (%s, %s, %s)',
                            (sub_id, ing_id, flattened_qty)
                        )
                conn.commit()
                st.success('Item added successfully!')
            except mysql.connector.IntegrityError:
                st.error('Item already part of this sub-recipe.')
            except mysql.connector.Error as err:
                st.error(f"MySQL Error: {err}")

        st.dataframe(pd.DataFrame(cost_breakdown))
        st.success(f"Total Estimated Sub-Recipe Cost: {total_cost:,.2f}")

        if st.button('Delete Entire Sub-Recipe'):
            c.execute('DELETE FROM sub_recipes WHERE id = %s', (sub_id,))
            c.execute('DELETE FROM sub_recipe_ingredients WHERE sub_recipe_id = %s', (sub_id,))
            conn.commit()
            st.success('Sub-Recipe deleted successfully!')

    else:
        st.warning('No sub-recipes found.')

    conn.close()


def manage_cakes():
    st.header('Manage Cakes')
    conn = get_connection()
    c = conn.cursor()

    c.execute('SELECT id, name FROM cakes')
    cakes = c.fetchall()

    if cakes:
        selected = st.selectbox('Select Cake to Manage', [f"{c[1]} (ID:{c[0]})" for c in cakes])
        cake_id = int(selected.split('(ID:')[1].replace(')', ''))

        c.execute('SELECT name, percent_yield FROM cakes WHERE id = %s', (cake_id,))
        cake_row = c.fetchone()
        if not cake_row:
            st.error("Cake not found.")
        else:
            current_name, current_yield = cake_row
            current_yield = float(current_yield or 0)

            new_name = st.text_input('Edit Cake Name', value=current_name)
            if st.button('Update Cake Name'):
                try:
                    c.execute('UPDATE cakes SET name = %s WHERE id = %s', (new_name, cake_id))
                    conn.commit()
                    st.success('Cake name updated successfully!')
                    st.rerun()
                    return
                except Exception as e:
                    st.error(f'Failed to update cake name. Error: {e}')

            new_yield = st.number_input('Edit Percent Yield (%)', value=current_yield, min_value=0.0, step=0.01, format='%.2f')
            if st.button('Update Yield Only'):
                try:
                    c.execute('UPDATE cakes SET percent_yield = %s WHERE id = %s', (new_yield, cake_id))
                    conn.commit()
                    st.success('Percent yield updated successfully!')
                    st.rerun()
                    return
                except Exception as e:
                    st.error(f'Failed to update yield. Error: {e}')

            # Load Ingredients
            c.execute('''
                SELECT ci.id,
                       ci.is_subrecipe,
                       ci.quantity,
                       COALESCE(i.name, sr.name),
                       CASE WHEN ci.is_subrecipe THEN 'Sub-Recipe' ELSE 'Ingredient' END,
                       ci.ingredient_or_subrecipe_id
                FROM cake_ingredients ci
                         LEFT JOIN ingredients i ON ci.ingredient_or_subrecipe_id = i.id AND ci.is_subrecipe = 0
                         LEFT JOIN sub_recipes sr ON ci.ingredient_or_subrecipe_id = sr.id AND ci.is_subrecipe = 1
                WHERE ci.cake_id = %s
            ''', (cake_id,))
            ingredients = c.fetchall()

            st.subheader('Current Ingredients/Sub-Recipes')
            cost_breakdown = []
            total_cost = 0

            for item_id, is_subrecipe, qty, item_name, item_type, ref_id in ingredients:
                qty = float(qty)
                new_qty = st.number_input(f"{item_name} ({item_type})", value=qty, step=0.00001, format="%.5f", key=f"{item_id}_qty_cake")

                item_cost = 0
                if is_subrecipe:
                    c.execute('''
                        SELECT SUM(sri.quantity * i.price_per_unit)
                        FROM sub_recipe_ingredients sri
                        JOIN ingredients i ON sri.ingredient_id = i.id
                        WHERE sri.sub_recipe_id = %s
                    ''', (ref_id,))
                    result = c.fetchone()
                    sub_recipe_total_cost = float(result[0]) if result and result[0] is not None else 0

                    c.execute('SELECT SUM(quantity) FROM sub_recipe_ingredients WHERE sub_recipe_id = %s', (ref_id,))
                    weight_result = c.fetchone()
                    total_weight = float(weight_result[0]) if weight_result and weight_result[0] else 0

                    if total_weight:
                        item_cost = (new_qty / total_weight) * sub_recipe_total_cost
                        st.caption(f"{item_name} — Sub Weight: {total_weight:.3f} kg, Used: {new_qty:.3f} kg")
                        formula_str = f"({new_qty:.3f} / {total_weight:.3f}) × {sub_recipe_total_cost:.2f} = {item_cost:.2f}"
                        st.markdown(f"<small style='color:#888;'>[Formula] {formula_str}</small>", unsafe_allow_html=True)
                else:
                    c.execute('SELECT price_per_unit FROM ingredients WHERE id = %s', (ref_id,))
                    row = c.fetchone()
                    if row and row[0] is not None:
                        item_cost = new_qty * float(row[0])
                    else:
                        item_cost = 0
                        st.warning(f"⚠️ Missing price for ingredient '{item_name}'")

                st.markdown(
                    f"<span style='color:green'>Estimated Cost for {item_name}: {round(item_cost, 2)}</span>",
                    unsafe_allow_html=True)
                cost_breakdown.append(
                    {"Item": item_name, "Type": item_type, "Quantity": new_qty, "Cost": round(item_cost, 2)})
                total_cost += item_cost

                if st.button(f"Update {item_name}", key=f"update_{item_id}_cake"):
                    c.execute('UPDATE cake_ingredients SET quantity = %s WHERE id = %s', (new_qty, item_id))
                    conn.commit()
                    st.success(f"Updated {item_name} quantity!")
                    st.rerun()
                    return

                if st.button(f"Delete {item_name}", key=f"delete_{item_id}_cake"):
                    c.execute('DELETE FROM cake_ingredients WHERE id = %s', (item_id,))
                    conn.commit()
                    st.success(f"Deleted {item_name} from Cake!")
                    st.rerun()
                    return

            # Add new item
            st.subheader('Add New Ingredient or Sub-Recipe')
            c.execute('SELECT id, name FROM ingredients')
            ingredients_list = c.fetchall()
            c.execute('SELECT id, name FROM sub_recipes')
            sub_recipes_list = c.fetchall()

            options = [f"{i[1]} (Ingredient ID:{i[0]})" for i in ingredients_list] + \
                      [f"{s[1]} (Sub-Recipe ID:{s[0]})" for s in sub_recipes_list]

            selected_item = st.selectbox('Select Item', options, key='new_ingredient_or_sub')
            if 'Ingredient ID:' in selected_item:
                item_id = int(selected_item.split('Ingredient ID:')[1].replace(')', ''))
                is_sub = 0
            else:
                item_id = int(selected_item.split('Sub-Recipe ID:')[1].replace(')', ''))
                is_sub = 1

            item_qty = st.number_input('Quantity (kg, L, etc)', min_value=0.0, step=0.00001, format="%.5f", key='item_qty')
            if st.button('Add to Cake'):
                try:
                    c.execute('''
                        INSERT INTO cake_ingredients (cake_id, ingredient_or_subrecipe_id, is_subrecipe, quantity)
                        VALUES (%s, %s, %s, %s)
                    ''', (cake_id, item_id, is_sub, item_qty))
                    conn.commit()
                    st.success('Added to cake successfully!')
                    st.rerun()
                    return
                except mysql.connector.IntegrityError:
                    st.error('Item already part of this cake.')

            st.subheader('🧾 Cost Breakdown')
            st.dataframe(pd.DataFrame(cost_breakdown))
            st.success(f"Total Estimated Cake Cost (Before Yield): {round(total_cost, 2)}")

            adjusted_cost = total_cost * (1 + (new_yield or 0) / 100)
            st.info(f"Estimated Cost After {new_yield:.2f}% Yield: {round(adjusted_cost, 2)}")

            cake_weight = st.number_input('Enter Total Cake Weight (kg)', min_value=0.001, step=0.001, format='%.3f')
            if cake_weight:
                cost_per_kg = adjusted_cost / cake_weight
                st.success(f"Cost per kg: {round(cost_per_kg, 2)}")

            if st.button('Delete Entire Cake'):
                c.execute('DELETE FROM cakes WHERE id = %s', (cake_id,))
                c.execute('DELETE FROM cake_ingredients WHERE cake_id = %s', (cake_id,))
                conn.commit()
                st.success('Cake deleted successfully!')
                st.rerun()
                return
    else:
        st.warning('No cakes found.')

    conn.close()
