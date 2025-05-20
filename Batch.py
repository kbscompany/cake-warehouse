import streamlit as st
import pandas as pd
import io
import mysql.connector
from db import get_connection  # Make sure this returns a valid MySQL connection object
from utils.batch_helpers import resolve_subrecipe_ingredients_detailed

def batch_production():
    st.header('Batch Production Calculator')
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT id, name FROM cakes')
    cakes = c.fetchall()

    if not cakes:
        st.warning('No cakes available to calculate batch.')
        return

    uploaded_file = st.file_uploader("\U0001F4C4 Upload Excel with Cake Quantities", type=['xlsx'])
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
        from utils.batch_helpers import resolve_subrecipe_ingredients_detailed  # Put helper in a separate file

        total_ingredients = {}
        detailed_rows = []
        subrecipe_summary = {}

        for cake_id, num_cakes in cake_quantities.items():
            c.execute('SELECT ingredient_or_subrecipe_id, is_subrecipe, quantity FROM cake_ingredients WHERE cake_id = %s', (cake_id,))
            cake_parts = c.fetchall()

            for iid, is_sub, qty in cake_parts:
                if is_sub:
                    resolved = resolve_subrecipe_ingredients_detailed(conn, iid, qty * num_cakes)
                    detailed_rows.extend(resolved)

                    c.execute('SELECT name FROM sub_recipes WHERE id = %s', (iid,))
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
                    c.execute('SELECT name, unit, price_per_unit FROM ingredients WHERE id = %s', (iid,))
                    ing_name, ing_unit, ing_price = c.fetchone()
                    scaled_qty = qty * num_cakes
                    cost = scaled_qty * float(ing_price)

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

        if total_ingredients:
            st.subheader('🧾 Total Ingredients Needed for Batch')
            df = pd.DataFrame([
                {'Ingredient': k, 'Quantity': round(v['quantity'], 5), 'Unit': v['unit'], 'Cost': round(v['cost'], 2)}
                for k, v in total_ingredients.items()
            ])
            st.dataframe(df)
            total_cost = sum(v['cost'] for v in total_ingredients.values())
            st.success(f'💰 Total Batch Cost: {round(total_cost, 2)}')

        if subrecipe_summary:
            st.subheader("🧪 Sub-Recipe Usage Summary")
            df_subs = pd.DataFrame([{
                'Sub-Recipe': k,
                'Quantity Used': round(v['quantity'], 5),
                'Unit Cost': round(v['unit_cost'], 2),
                'Total Cost': round(v['quantity'] * v['unit_cost'], 2)
            } for k, v in subrecipe_summary.items()])
            st.dataframe(df_subs)
        else:
            df_subs = pd.DataFrame()

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
