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
def batch_production():
    st.header('Batch Production Calculator')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, name FROM cakes')
    cakes = c.fetchall()

    if not cakes:
        st.warning('No cakes available to calculate batch.')
        return

    uploaded_file = st.file_uploader("📤 Upload Excel with Cake Quantities", type=['xlsx'])

    cake_quantities = {}

    if uploaded_file is not None:
        df_uploaded = pd.read_excel(uploaded_file)
        if 'Cake Name' not in df_uploaded.columns or 'Quantity' not in df_uploaded.columns:
            st.error("Excel must have columns 'Cake Name' and 'Quantity'")
        else:
            cake_name_to_id = {n: i for i, n in cakes}
            for _, row in df_uploaded.iterrows():
                cake_name = row['Cake Name']
                qty = row['Quantity']
                if cake_name in cake_name_to_id:
                    cake_quantities[cake_name_to_id[cake_name]] = qty
                else:
                    st.warning(f"Cake '{cake_name}' not found in the database.")
    else:
        selected_cakes = st.multiselect('Select Cakes to Produce', [f"{n} (ID:{i})" for i, n in cakes])
        for cake in selected_cakes:
            cake_id = int(cake.split('(ID:')[1].replace(')', ''))
            qty = st.number_input(f'Quantity of {cake.split(" (ID:")[0]} (number of cakes)', min_value=0.0, step=0.00001, format="%.5f", key=f"qty_{cake_id}")
            cake_quantities[cake_id] = qty

    if cake_quantities and st.button('Calculate Batch Ingredients'):
        total_ingredients = {}
        detailed_rows = []
        subrecipe_summary = {}

        for cake_id, num_cakes in cake_quantities.items():
            c.execute('SELECT ingredient_or_subrecipe_id, is_subrecipe, quantity FROM cake_ingredients WHERE cake_id = ?', (cake_id,))
            cake_parts = c.fetchall()

            for iid, is_sub, qty in cake_parts:
                if is_sub:
                    resolved = resolve_subrecipe_ingredients_detailed(conn, iid, qty * num_cakes)
                    detailed_rows.extend(resolved)

                    # Sub-recipe summary logic
                    c.execute('SELECT name FROM sub_recipes WHERE id = ?', (iid,))
                    sr_name = c.fetchone()[0]
                    if sr_name not in subrecipe_summary:
                        subrecipe_summary[sr_name] = {'quantity': 0.0, 'unit_cost': 0.0}
                    subrecipe_summary[sr_name]['quantity'] += qty * num_cakes

                    if subrecipe_summary[sr_name]['unit_cost'] == 0:
                        unit_cost = sum(r['cost'] for r in resolve_subrecipe_ingredients_detailed(conn, iid, 1.0))
                        subrecipe_summary[sr_name]['unit_cost'] = unit_cost

                    for r in resolved:
                        name = r['ingredient']
                        if name in total_ingredients:
                            total_ingredients[name]['quantity'] += r['quantity']
                            total_ingredients[name]['cost'] += r['cost']
                        else:
                            total_ingredients[name] = {
                                'quantity': r['quantity'],
                                'cost': r['cost'],
                                'unit': r['unit']
                            }
                else:
                    c.execute('SELECT name, unit, price_per_unit FROM ingredients WHERE id = ?', (iid,))
                    ing_name, ing_unit, ing_price = c.fetchone()
                    scaled_qty = qty * num_cakes
                    cost = scaled_qty * ing_price
                    if ing_name in total_ingredients:
                        total_ingredients[ing_name]['quantity'] += scaled_qty
                        total_ingredients[ing_name]['cost'] += cost
                    else:
                        total_ingredients[ing_name] = {'quantity': scaled_qty, 'unit': ing_unit, 'cost': cost}
                    detailed_rows.append({
                        'source': 'Direct in Cake',
                        'ingredient': ing_name,
                        'unit': ing_unit,
                        'quantity': scaled_qty,
                        'cost': cost
                    })

        # 🧾 Total Ingredients Summary
        if total_ingredients:
            st.subheader('🧾 Total Ingredients Needed for Batch')
            df = pd.DataFrame([
                {'Ingredient': k, 'Quantity': round(v['quantity'], 5), 'Unit': v['unit'], 'Cost': round(v['cost'], 2)}
                for k, v in total_ingredients.items()
            ])
            st.dataframe(df)
            total_cost = sum(v['cost'] for v in total_ingredients.values())
            st.success(f'💰 Total Batch Cost: {round(total_cost, 2)}')

        # 🧪 Sub-Recipe Summary Table
        if subrecipe_summary:
            st.subheader("🧪 Sub-Recipe Usage Summary")
            sub_summary_rows = []
            for name, data in subrecipe_summary.items():
                qty = round(data['quantity'], 5)
                unit_cost = round(data['unit_cost'], 2)
                total_cost = round(qty * unit_cost, 2)
                sub_summary_rows.append({
                    'Sub-Recipe': name,
                    'Quantity Used': qty,
                    'Unit Cost': unit_cost,
                    'Total Cost': total_cost
                })
            df_subs = pd.DataFrame(sub_summary_rows)
            st.dataframe(df_subs)
        else:
            df_subs = pd.DataFrame()

        # 🔍 Full Breakdown Table
        if detailed_rows:
            st.subheader("🔍 Full Breakdown by Sub-Recipe and Ingredient")
            df_details = pd.DataFrame(detailed_rows)
            df_details = df_details.groupby(['source', 'ingredient', 'unit'], as_index=False).agg({
                'quantity': 'sum',
                'cost': 'sum'
            })
            df_details['quantity'] = df_details['quantity'].round(5)
            df_details['cost'] = df_details['cost'].round(2)
            st.dataframe(df_details)
        else:
            df_details = pd.DataFrame()

        # 📥 Export to Excel
        if not df.empty:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Batch Ingredients')
                if not df_subs.empty:
                    df_subs.to_excel(writer, index=False, sheet_name='Sub-Recipe Summary')
                if not df_details.empty:
                    df_details.to_excel(writer, index=False, sheet_name='Full Breakdown')

                worksheet = writer.sheets['Batch Ingredients']
                worksheet.write(len(df) + 2, 0, 'Total Batch Cost')
                worksheet.write(len(df) + 2, 1, round(total_cost, 2))

            buffer.seek(0)
            st.download_button(
                label='📥 Export to Excel',
                data=buffer,
                file_name='batch_production_summary.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

    conn.close()

# config.py
def resolve_subrecipe_ingredients_detailed(conn, sub_recipe_id, final_qty=None, path=""):
    def get_total_cost_and_weight(sub_id):
        cursor = conn.cursor()

        cursor.execute('''
            SELECT sri.quantity, i.price_per_unit
            FROM sub_recipe_ingredients sri
            JOIN ingredients i ON sri.ingredient_id = i.id
            WHERE sri.sub_recipe_id = ?
        ''', (sub_id,))
        direct_items = cursor.fetchall()
        direct_cost = sum(q * p for q, p in direct_items)
        direct_weight = sum(q for q, _ in direct_items)

        cursor.execute('SELECT sub_recipe_id, quantity FROM sub_recipe_nested WHERE parent_sub_recipe_id = ?', (sub_id,))
        nested_items = cursor.fetchall()
        nested_cost = 0
        nested_weight = 0

        for nested_sub_id, qty in nested_items:
            nc, nw = get_total_cost_and_weight(nested_sub_id)
            if nw > 0:
                nested_cost += (nc / nw) * qty
                nested_weight += qty

        return direct_cost + nested_cost, direct_weight + nested_weight

    def flatten_nested_subrecipe(nested_id, nested_qty, current_path, parent_qty=1.0, parent_total=1.0):
        flat_result = []
        total_cost, total_weight = get_total_cost_and_weight(nested_id)
        if total_weight == 0:
            return flat_result

        c.execute('''
            SELECT sri.ingredient_id, sri.quantity, i.name, i.unit, i.price_per_unit
            FROM sub_recipe_ingredients sri
            JOIN ingredients i ON sri.ingredient_id = i.id
            WHERE sri.sub_recipe_id = ?
        ''', (nested_id,))
        for ing_id, qty, name, unit, price in c.fetchall():
            scaled_qty = qty / total_weight * nested_qty / parent_total * parent_qty
            flat_result.append({
                'source': current_path,
                'ingredient': name,
                'unit': unit,
                'quantity': scaled_qty,
                'cost': scaled_qty * price
            })

        c.execute('SELECT sub_recipe_id, quantity FROM sub_recipe_nested WHERE parent_sub_recipe_id = ?', (nested_id,))
        for inner_id, inner_qty in c.fetchall():
            flat_result.extend(flatten_nested_subrecipe(inner_id, inner_qty, current_path, parent_qty=nested_qty, parent_total=total_weight))

        return flat_result

    c = conn.cursor()
    result = []

    # Get sub-recipe name
    c.execute('SELECT name FROM sub_recipes WHERE id = ?', (sub_recipe_id,))
    sub_name_row = c.fetchone()
    if not sub_name_row:
        return []
    sub_name = sub_name_row[0]
    current_path = f"{path} → {sub_name}" if path else sub_name

    # Total weight of sub-recipe
    total_cost, total_weight = get_total_cost_and_weight(sub_recipe_id)
    if total_weight == 0:
        return []

    if final_qty is None:
        final_qty = total_weight

    # Direct ingredients
    c.execute('''
        SELECT sri.ingredient_id, sri.quantity, i.name, i.unit, i.price_per_unit
        FROM sub_recipe_ingredients sri
        JOIN ingredients i ON sri.ingredient_id = i.id
        WHERE sri.sub_recipe_id = ?
    ''', (sub_recipe_id,))
    for ing_id, qty, name, unit, price in c.fetchall():
        proportion = qty / total_weight
        scaled_qty = proportion * final_qty
        result.append({
            'source': current_path,
            'ingredient': name,
            'unit': unit,
            'quantity': scaled_qty,
            'cost': scaled_qty * price
        })

    # Nested sub-recipes (fully flatten them)
    c.execute('SELECT sub_recipe_id, quantity FROM sub_recipe_nested WHERE parent_sub_recipe_id = ?', (sub_recipe_id,))
    for nested_id, nested_qty in c.fetchall():
        result.extend(flatten_nested_subrecipe(nested_id, nested_qty, current_path, parent_qty=final_qty, parent_total=total_weight))

    return result