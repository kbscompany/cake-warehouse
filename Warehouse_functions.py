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
def create_transfer_order_page():
    st.header("🚚 Create Transfer Order")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Load warehouses
    c.execute("SELECT id, name FROM warehouses ORDER BY name")
    warehouses = c.fetchall()
    warehouse_dict = {name: wid for wid, name in warehouses}

    # Select source & target warehouses
    col1, col2 = st.columns(2)
    source = col1.selectbox("Source Warehouse", list(warehouse_dict.keys()), index=0)
    target = col2.selectbox("Target Warehouse", list(warehouse_dict.keys()), index=1)

    if source == target:
        st.warning("⚠️ Source and target warehouse must be different.")
        conn.close()
        return

    source_id = warehouse_dict[source]
    target_id = warehouse_dict[target]

    # Ingredient name filter
    search_term = st.text_input("🔍 Search Ingredients").strip().lower()

    # Query ingredients with stock in source and target
    c.execute('''
        SELECT 
            i.id,
            i.name,
            i.unit,
            IFNULL(src_ws.quantity, 0),
            IFNULL(trg_ws.quantity, 0)
        FROM ingredients i
        LEFT JOIN warehouse_stock src_ws 
            ON i.id = src_ws.ingredient_id AND src_ws.warehouse_id = ?
        LEFT JOIN warehouse_stock trg_ws 
            ON i.id = trg_ws.ingredient_id AND trg_ws.warehouse_id = ?
        ORDER BY i.name
    ''', (source_id, target_id))

    ingredients = c.fetchall()

    st.subheader("📦 Select Items to Transfer")
    selected_items = []

    for ing_id, name, unit, source_qty, target_qty in ingredients:
        if search_term and search_term not in name.lower():
            continue  # Filter out unmatched names

        col1, col2, col3 = st.columns([5, 3, 2])
        label = f"{name} ({unit}) – Source: {source_qty} | Target: {target_qty}"

        if source_qty > 0:
            transfer_qty = col1.number_input(
                label, min_value=0.0, max_value=source_qty, step=0.1, key=f"transfer_{ing_id}"
            )
        else:
            col1.markdown(f"<span style='color:#999'>{label}</span>", unsafe_allow_html=True)
            transfer_qty = 0

        if transfer_qty > 0:
            selected_items.append((ing_id, transfer_qty))

    if st.button("➕ Create Transfer Order"):
        if not selected_items:
            st.warning("⚠️ You must select at least one ingredient with quantity.")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Create transfer order
            c.execute('''
                INSERT INTO transfer_orders (source_warehouse_id, target_warehouse_id, status, created_at)
                VALUES (?, ?, 'Pending', ?)
            ''', (source_id, target_id, now))
            order_id = c.lastrowid

            # Insert items
            for ing_id, qty in selected_items:
                c.execute('''
                    INSERT INTO transfer_order_items (transfer_order_id, ingredient_id, quantity)
                    VALUES (?, ?, ?)
                ''', (order_id, ing_id, qty))

            conn.commit()
            st.success(f"✅ Transfer Order #{order_id} created successfully.")

    conn.close()



def create_kitchen_batch_log_table(conn):
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS kitchen_batch_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT,               -- 'cake' or 'sub_recipe'
            item_id INTEGER,
            quantity REAL,
            produced_at TEXT,
            produced_by TEXT
        )
    ''')
    conn.commit()
def receive_transfer_order_page():
    st.header("📥 Receive Transfer Orders")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get kitchen warehouse ID
    c.execute("SELECT id FROM warehouses WHERE name = 'Kitchen'")
    kitchen_row = c.fetchone()
    if not kitchen_row:
        st.error("Kitchen warehouse not found.")
        conn.close()
        return
    kitchen_id = kitchen_row[0]

    # Fetch pending transfer orders targeted to kitchen
    c.execute('''
        SELECT t.id, w1.name AS source_name, t.created_at
        FROM transfer_orders t
        JOIN warehouses w1 ON t.source_warehouse_id = w1.id
        WHERE t.target_warehouse_id = ? AND t.status = 'Pending'
        ORDER BY t.created_at DESC
    ''', (kitchen_id,))
    orders = c.fetchall()

    if not orders:
        st.info("No pending transfer orders to receive.")
        conn.close()
        return

    # Dropdown to select a transfer order
    selected = st.selectbox(
        "Select Transfer Order",
        [f"Order #{o[0]} from {o[1]} at {o[2]}" for o in orders]
    )
    selected_order_id = int(selected.split('#')[1].split(' ')[0])

    # Fetch items in selected order
    c.execute('''
        SELECT toi.ingredient_id, i.name, i.unit, toi.quantity
        FROM transfer_order_items toi
        JOIN ingredients i ON toi.ingredient_id = i.id
        WHERE toi.transfer_order_id = ?
    ''', (selected_order_id,))
    items = c.fetchall()

    st.subheader("🔍 Review and Confirm Receipt")

    updated_items = []

    for ing_id, name, unit, qty in items:
        st.markdown(f"**{name} ({unit})** — Ordered: {qty}")
        col1, col2, col3 = st.columns(3)
        accepted = col1.number_input(
            "Accepted Qty",
            min_value=0.0,
            max_value=qty,
            step=0.1,
            value=qty,  # ✅ Pre-fill with full quantity
            key=f"acc_{ing_id}"
        )

        returned = col2.number_input("Returned Qty", min_value=0.0, max_value=qty - accepted, step=0.1, key=f"ret_{ing_id}")
        wasted = col3.number_input("Wasted Qty", min_value=0.0, max_value=qty - accepted - returned, step=0.1, key=f"was_{ing_id}")

        if accepted + returned + wasted > qty:
            st.error(f"❌ Total for {name} exceeds sent quantity.")
        else:
            updated_items.append((ing_id, qty, accepted, returned, wasted))

    # Handle Confirm
    if st.button("✅ Confirm Receipt"):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for ing_id, sent, accepted, returned, wasted in updated_items:
            # Deduct full qty from source warehouse
            c.execute('''
                UPDATE warehouse_stock
                SET quantity = quantity - ?
                WHERE warehouse_id = (
                    SELECT source_warehouse_id FROM transfer_orders WHERE id = ?
                ) AND ingredient_id = ?
            ''', (sent, selected_order_id, ing_id))

            # Add accepted qty to kitchen warehouse
            c.execute('''
                INSERT INTO warehouse_stock (warehouse_id, ingredient_id, quantity)
                VALUES (?, ?, ?)
                ON CONFLICT(warehouse_id, ingredient_id) DO UPDATE SET
                    quantity = quantity + excluded.quantity
            ''', (kitchen_id, ing_id, accepted))

            # Log accepted/returned/wasted amounts
            c.execute('''
                UPDATE transfer_order_items
                SET accepted_qty = ?, returned_qty = ?, wasted_qty = ?
                WHERE transfer_order_id = ? AND ingredient_id = ?
            ''', (accepted, returned, wasted, selected_order_id, ing_id))

        # Mark order as received
        c.execute("UPDATE transfer_orders SET status = 'Received' WHERE id = ?", (selected_order_id,))
        conn.commit()
        st.success("✅ Transfer order successfully received.")

    conn.close()

def manage_categories():
    st.header("🗂️ Manage Inventory Categories")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Add new category
    new_cat = st.text_input("Add New Category")
    if st.button("➕ Add Category"):
        try:
            c.execute("INSERT INTO inventory_categories (name) VALUES (?)", (new_cat.strip(),))
            conn.commit()
            st.success(f"Category '{new_cat}' added.")
        except sqlite3.IntegrityError:
            st.error("Category already exists or is invalid.")

    st.divider()

    # List and delete existing categories
    c.execute("SELECT id, name FROM inventory_categories ORDER BY name")
    categories = c.fetchall()

    for cat_id, name in categories:
        col1, col2 = st.columns([5, 1])
        col1.markdown(f"**{name}**")
        if col2.button("🗑️ Delete", key=f"del_{cat_id}"):
            c.execute("SELECT COUNT(*) FROM warehouse WHERE category_id = ?", (cat_id,))
            count = c.fetchone()[0]
            if count > 0:
                st.warning(f"Category '{name}' is in use and cannot be deleted.")
            else:
                c.execute("DELETE FROM inventory_categories WHERE id = ?", (cat_id,))
                conn.commit()
                st.success(f"Category '{name}' deleted.")

    conn.close()

