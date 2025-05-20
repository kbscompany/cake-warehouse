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
def update_stock():
    st.header("📦 Update Warehouse Stock")

    # CSS Styling
    st.markdown("""
        <style>
            .ingredient-card {
                background-color: #fff0f5;
                padding: 1.5rem;
                border-radius: 10px;
                border: 1px solid #f8d6e0;
                margin-bottom: 1rem;
            }
            .no-data {
                text-align: center;
                font-weight: 500;
                color: #7b4f4f;
                margin-top: 2rem;
            }
        </style>
    """, unsafe_allow_html=True)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Ensure necessary tables
    c.execute('''CREATE TABLE IF NOT EXISTS warehouse_stock (
        warehouse_id INTEGER,
        ingredient_id INTEGER,
        quantity REAL DEFAULT 0,
        PRIMARY KEY (warehouse_id, ingredient_id),
        FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS warehouses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingredient_id INTEGER,
        warehouse_id INTEGER,
        change REAL,
        reason TEXT,
        timestamp TEXT
    )''')

    # Get warehouse list and selection
    c.execute("SELECT id, name FROM warehouses ORDER BY name")
    warehouses = c.fetchall()
    warehouse_dict = {name: wid for wid, name in warehouses}

    selected_warehouse = st.selectbox("🏢 Select Warehouse to Update", list(warehouse_dict.keys()))
    warehouse_id = warehouse_dict[selected_warehouse]

    # Export stock to Excel
    c.execute('''
        SELECT i.id AS ingredient_id, i.name AS ingredient_name, IFNULL(ws.quantity, 0) AS quantity
        FROM ingredients i
        LEFT JOIN warehouse_stock ws ON i.id = ws.ingredient_id AND ws.warehouse_id = ?
        ORDER BY i.name
    ''', (warehouse_id,))
    df_export = pd.DataFrame(c.fetchall(), columns=["ingredient_id", "ingredient_name", "quantity"])

    excel_buffer = BytesIO()
    df_export.to_excel(excel_buffer, index=False)
    excel_buffer.seek(0)

    st.download_button(
        label="📤 Download Warehouse Stock Template",
        data=excel_buffer,
        file_name=f"{selected_warehouse}_stock_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Upload Excel to update stock
    st.subheader("📥 Upload Updated Stock File")
    uploaded_file = st.file_uploader("Upload Excel with updated quantities", type=["xlsx"])

    if uploaded_file:
        df_uploaded = pd.read_excel(uploaded_file)
        if not {"ingredient_id", "quantity"}.issubset(df_uploaded.columns):
            st.error("❌ Excel must include 'ingredient_id' and 'quantity' columns.")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for _, row in df_uploaded.iterrows():
                try:
                    ing_id = int(row["ingredient_id"])
                    new_qty = float(row["quantity"])

                    c.execute('SELECT quantity FROM warehouse_stock WHERE warehouse_id = ? AND ingredient_id = ?', (warehouse_id, ing_id))
                    existing = c.fetchone()
                    old_qty = existing[0] if existing else 0
                    change = new_qty - old_qty

                    c.execute('''
                        INSERT INTO warehouse_stock (warehouse_id, ingredient_id, quantity)
                        VALUES (?, ?, ?)
                        ON CONFLICT(warehouse_id, ingredient_id) DO UPDATE SET
                            quantity = excluded.quantity
                    ''', (warehouse_id, ing_id, new_qty))

                    if change != 0:
                        c.execute('''
                            INSERT INTO stock_movements (ingredient_id, warehouse_id, change, reason, timestamp)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (ing_id, warehouse_id, change, "Excel Upload", now))
                except Exception as e:
                    st.warning(f"⚠️ Failed to process row: {e}")

            conn.commit()
            st.success("✅ Excel stock update applied successfully.")

    # Manual update per ingredient
    st.divider()
    st.subheader("🔧 Manually Update Ingredients")

    c.execute('''
        SELECT i.id, i.name, i.unit, IFNULL(ws.quantity, 0)
        FROM ingredients i
        LEFT JOIN warehouse_stock ws ON i.id = ws.ingredient_id AND ws.warehouse_id = ?
        ORDER BY i.name
    ''', (warehouse_id,))
    ingredients = c.fetchall()

    search = st.text_input("🔍 Search Ingredients").lower()
    found = False

    for ing_id, name, unit, quantity in ingredients:
        if not name or (search and search not in name.lower()):
            continue

        found = True
        st.markdown("<div class='ingredient-card'>", unsafe_allow_html=True)
        st.subheader(f"{name} ({unit})")

        col1, col2 = st.columns([5, 3])
        new_qty = col1.number_input("Stock Quantity", min_value=0.0, step=0.1, format="%.2f", value=float(quantity),
                                    key=f"qty_{warehouse_id}_{ing_id}")

        reason = col2.selectbox("Reason", ["Manual Update", "Spoilage", "Restock", "Adjustment"], key=f"reason_{warehouse_id}_{ing_id}")

        st.caption(f"🕓 Current Qty: {quantity}")

        if st.button("📂 Apply Update", key=f"apply_{warehouse_id}_{ing_id}"):
            change = new_qty - quantity
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            c.execute('''
                INSERT INTO warehouse_stock (warehouse_id, ingredient_id, quantity)
                VALUES (?, ?, ?)
                ON CONFLICT(warehouse_id, ingredient_id) DO UPDATE SET
                    quantity = excluded.quantity
            ''', (warehouse_id, ing_id, new_qty))

            if change != 0:
                c.execute('''
                    INSERT INTO stock_movements (ingredient_id, warehouse_id, change, reason, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (ing_id, warehouse_id, change, reason, now))

            conn.commit()
            st.success(f"✅ Stock for {name} updated in {selected_warehouse}.")

        st.markdown("</div>", unsafe_allow_html=True)

    if not found:
        st.markdown("<div class='no-data'>🚫 No matching ingredients found.</div>", unsafe_allow_html=True)

    conn.close()
