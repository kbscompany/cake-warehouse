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
def view_costs():
    st.header('🎂 View Cake Costs')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, name FROM cakes')
    cakes = c.fetchall()

    if not cakes:
        st.warning('No cakes available.')
        conn.close()
        return

    selected = st.selectbox('Select Cake to View Cost', [f"{n} (ID:{i})" for i, n in cakes])
    cid = int(selected.split('(ID:')[1].replace(')', ''))

    c.execute('SELECT ingredient_or_subrecipe_id, is_subrecipe, quantity FROM cake_ingredients WHERE cake_id = ?', (cid,))
    parts = c.fetchall()

    total = 0
    direct_items = []

    for iid, is_sub, qty in parts:
        if is_sub:
            c.execute('SELECT name FROM sub_recipes WHERE id = ?', (iid,))
            sub_name = c.fetchone()[0]

            c.execute('''
                SELECT sri.ingredient_id, sri.quantity, i.name, i.price_per_unit, i.unit
                FROM sub_recipe_ingredients sri
                JOIN ingredients i ON sri.ingredient_id = i.id
                WHERE sri.sub_recipe_id = ?
            ''', (iid,))
            sub_ingredients = c.fetchall()

            sub_total_weight = sum([row[1] for row in sub_ingredients])
            sub_total = 0
            sub_rows = []

            if sub_total_weight == 0:
                st.error(f"⚠️ Sub-recipe '{sub_name}' has zero total weight. Cannot calculate proportions.")
                continue

            for sid, sub_qty, name, price, unit in sub_ingredients:
                ratio = sub_qty / sub_total_weight
                scaled_qty = ratio * qty
                scaled_cost = scaled_qty * price
                sub_total += scaled_cost
                sub_rows.append({
                    'Ingredient': name,
                    'Quantity Used': round(scaled_qty, 4),
                    'Unit': unit,
                    'Cost': round(scaled_cost, 2)
                })

            st.subheader(f"🧪 Sub-Recipe: {sub_name} × {qty} kg")
            st.dataframe(pd.DataFrame(sub_rows))
            total += sub_total

        else:
            c.execute('SELECT name, price_per_unit, unit FROM ingredients WHERE id = ?', (iid,))
            name, price, unit = c.fetchone()
            cost = price * qty
            total += cost
            direct_items.append({
                'Ingredient': name,
                'Quantity': qty,
                'Unit': unit,
                'Cost': round(cost, 2)
            })

    if direct_items:
        st.subheader("🧾 Direct Ingredients")
        st.dataframe(pd.DataFrame(direct_items))

    st.success(f"💰 Total Cost: {round(total, 2)}")
    conn.close()

def view_all_cakes():
    st.header("🎂 All Cakes Overview")

    if st.button("➕ Add New Cake"):
        st.session_state.edit_cake_id = None
        st.experimental_rerun()
        return

    search_term = st.text_input("🔍 Search Cakes by Name")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Filter by name
    if search_term:
        c.execute("SELECT id, name, percent_yield FROM cakes WHERE name LIKE ?", (f"%{search_term}%",))
    else:
        c.execute("SELECT id, name, percent_yield FROM cakes")

    cakes = c.fetchall()

    if not cakes:
        st.warning("No cakes found.")
        conn.close()
        return

    for cake_id, name, yield_percent in cakes:
        total_cost = 0

        # === Calculate Cake Cost ===
        c.execute('SELECT ingredient_or_subrecipe_id, is_subrecipe, quantity FROM cake_ingredients WHERE cake_id = ?', (cake_id,))
        parts = c.fetchall()

        for iid, is_sub, qty in parts:
            if is_sub:
                c.execute('''
                    SELECT sri.ingredient_id, sri.quantity, i.price_per_unit
                    FROM sub_recipe_ingredients sri
                    JOIN ingredients i ON sri.ingredient_id = i.id
                    WHERE sri.sub_recipe_id = ?
                ''', (iid,))
                sub_ings = c.fetchall()
                c.execute('SELECT SUM(quantity) FROM sub_recipe_ingredients WHERE sub_recipe_id = ?', (iid,))
                total_weight = c.fetchone()[0]
                if total_weight:
                    for ing_id, ing_qty, price in sub_ings:
                        if price is not None:
                            total_cost += (ing_qty / total_weight) * qty * price
                        else:
                            st.warning(f"⚠️ Missing price for ingredient ID {ing_id} in sub-recipe {iid}")
            else:
                c.execute('SELECT price_per_unit FROM ingredients WHERE id = ?', (iid,))
                result = c.fetchone()
                if result and result[0] is not None:
                    price = result[0]
                    total_cost += qty * price
                else:
                    st.warning(f"⚠️ Missing or deleted ingredient ID {iid} in cake '{name}'")

        adjusted_cost = total_cost * (1 + yield_percent / 100)

        # === Display Cake Entry ===
        cols = st.columns([5, 1, 1])
        with cols[0]:
            st.markdown(f"**{name}** – Yield: {yield_percent:.2f}% – 💰 Cost: EGP {adjusted_cost:.2f}")
        with cols[1]:
            if st.button("✏️ Edit", key=f"edit_{cake_id}"):
                st.session_state.edit_cake_id = cake_id
                conn.close()
                st.experimental_rerun()
                return
        with cols[2]:
            if st.button("🗑️ Delete", key=f"delete_{cake_id}"):
                c.execute("DELETE FROM cake_ingredients WHERE cake_id = ?", (cake_id,))
                c.execute("DELETE FROM cakes WHERE id = ?", (cake_id,))
                conn.commit()
                st.success(f"Deleted '{name}' successfully!")
                conn.close()
                st.experimental_rerun()
                return

    conn.close()