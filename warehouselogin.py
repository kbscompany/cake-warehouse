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



def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user_and_role_tables():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    c.execute("INSERT OR IGNORE INTO roles (name) VALUES ('admin'), ('staff'), ('viewer')")
    conn.commit()
    conn.close()

def login_page():
    st.title("🔐 Login to KB's Cake Studio")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    login = st.button("Login")

    if login:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, role FROM users WHERE username = ? AND password = ?", (username, hash_password(password)))
        result = c.fetchone()
        conn.close()
        if result:
            st.session_state.user = {'id': result[0], 'username': username, 'role': result[1]}
            st.success(f"Welcome back, {username}!")
            st.experimental_rerun()
        else:
            st.error("Invalid username or password")

def manage_users_page():
    st.header("👥 Manage Users & Roles")
    st.subheader("➕ Add New User")
    new_user = st.text_input("New Username")
    new_pass = st.text_input("New Password", type="password")
    role = st.selectbox("Assign Role", ["admin", "staff", "viewer"])
    if st.button("Create User"):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (new_user, hash_password(new_pass), role))
            conn.commit()
            st.success(f"User '{new_user}' created successfully.")
        except sqlite3.IntegrityError:
            st.error("Username already exists.")
        conn.close()
    st.divider()
    st.subheader("📝 Existing Users")
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT id, username, role FROM users", conn)
    st.dataframe(df)
    conn.close()


# ---------- USER AUTH + DB SETUP ----------



# ----------------------
# Database Setup
# ----------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, price_per_unit REAL, unit TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sub_recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sub_recipe_ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, sub_recipe_id INTEGER, ingredient_id INTEGER, quantity REAL, FOREIGN KEY(sub_recipe_id) REFERENCES sub_recipes(id), FOREIGN KEY(ingredient_id) REFERENCES ingredients(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS cakes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cake_ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, cake_id INTEGER, ingredient_or_subrecipe_id INTEGER, is_subrecipe BOOLEAN, quantity REAL, FOREIGN KEY(cake_id) REFERENCES cakes(id))''')
    c.execute('''
            CREATE TABLE IF NOT EXISTS sub_recipe_nested (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_sub_recipe_id INTEGER,
                sub_recipe_id INTEGER,
                quantity REAL,
                FOREIGN KEY(parent_sub_recipe_id) REFERENCES sub_recipes(id),
                FOREIGN KEY(sub_recipe_id) REFERENCES sub_recipes(id)
            )
        ''')
    # 1. Ingredient Stock
    c.execute('''
        CREATE TABLE IF NOT EXISTS warehouse (
            ingredient_id INTEGER PRIMARY KEY,
            quantity REAL DEFAULT 0,
            last_updated TEXT,
            FOREIGN KEY(ingredient_id) REFERENCES ingredients(id)
        )
    ''')

    # 2. Stock Movement Log
    c.execute('''
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER,
            change REAL,
            reason TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(ingredient_id) REFERENCES ingredients(id)
        )
    ''')

    def ensure_extended_warehouse_schema():
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Create category table
        c.execute('''
            CREATE TABLE IF NOT EXISTS inventory_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        ''')

        # Ensure category_id exists in warehouse
        c.execute("PRAGMA table_info(warehouse)")
        cols = [row[1] for row in c.fetchall()]
        if "category_id" not in cols:
            c.execute("ALTER TABLE warehouse ADD COLUMN category_id INTEGER REFERENCES inventory_categories(id)")
        if "par_level" not in cols:
            c.execute("ALTER TABLE warehouse ADD COLUMN par_level REAL DEFAULT 0")
        conn.commit()
        conn.close()

    conn.commit()
    conn.close()

# ----------------------
# Add Ingredient
# ----------------------
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
        st.warning("Source and target warehouse must be different.")
        return

    source_id = warehouse_dict[source]
    target_id = warehouse_dict[target]

    # Select ingredients to transfer
    c.execute('''
        SELECT i.id, i.name, i.unit, ws.quantity
        FROM ingredients i
        JOIN warehouse_stock ws ON i.id = ws.ingredient_id
        WHERE ws.warehouse_id = ?
        ORDER BY i.name
    ''', (source_id,))
    ingredients = c.fetchall()

    st.subheader("📦 Select Items to Transfer")
    selected_items = []
    for ing_id, name, unit, qty in ingredients:
        col1, col2 = st.columns([6, 2])
        transfer_qty = col1.number_input(
            f"{name} ({unit}) - Available: {qty}",
            min_value=0.0, max_value=qty, step=0.1, key=f"transfer_{ing_id}"
        )
        if transfer_qty > 0:
            selected_items.append((ing_id, transfer_qty))

    if st.button("➕ Create Transfer Order"):
        if not selected_items:
            st.warning("You must select at least one ingredient with quantity.")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Insert order
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
            st.success(f"✅ Transfer Order #{order_id} created.")

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



def transfer_order_history_page():
    st.header("📦 Transfer Order History")

    conn = sqlite3.connect(DB_PATH)

    # Fetch transfer order overview
    df_orders = pd.read_sql_query('''
        SELECT 
            t.id AS order_id,
            ws.name AS source,
            wt.name AS target,
            t.status,
            t.created_at
        FROM transfer_orders t
        JOIN warehouses ws ON t.source_warehouse_id = ws.id
        JOIN warehouses wt ON t.target_warehouse_id = wt.id
        ORDER BY t.created_at DESC
    ''', conn)

    if df_orders.empty:
        st.info("No transfer orders found.")
        conn.close()
        return

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        status = st.selectbox("Filter by Status", ["All"] + sorted(df_orders["status"].unique()))
    with col2:
        source = st.selectbox("Source Warehouse", ["All"] + sorted(df_orders["source"].unique()))
    with col3:
        target = st.selectbox("Target Warehouse", ["All"] + sorted(df_orders["target"].unique()))

    date_range = st.date_input("Filter by Date Range", [])

    # Apply filters
    if status != "All":
        df_orders = df_orders[df_orders["status"] == status]
    if source != "All":
        df_orders = df_orders[df_orders["source"] == source]
    if target != "All":
        df_orders = df_orders[df_orders["target"] == target]
    if len(date_range) == 2:
        start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        df_orders['created_at'] = pd.to_datetime(df_orders['created_at'])
        df_orders = df_orders[df_orders["created_at"].between(start, end)]

    st.dataframe(df_orders, use_container_width=True)

    # Order detail viewer
    order_ids = df_orders["order_id"].tolist()
    if order_ids:
        selected_id = st.selectbox("Select Order to View Details", order_ids)
        df_items = pd.read_sql_query('''
            SELECT 
                i.name AS ingredient,
                toi.quantity AS sent,
                toi.accepted_qty,
                toi.returned_qty,
                toi.wasted_qty
            FROM transfer_order_items toi
            JOIN ingredients i ON toi.ingredient_id = i.id
            WHERE toi.transfer_order_id = ?
        ''', conn, params=(selected_id,))

        st.markdown(f"### 📦 Transfer Order #{selected_id} Details")
        st.dataframe(df_items, use_container_width=True)

        # Export to Excel
        buffer = BytesIO()
        df_items.to_excel(buffer, index=False)
        buffer.seek(0)
        st.download_button(
            label="📤 Export This Order to Excel",
            data=buffer,
            file_name=f"transfer_order_{selected_id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    conn.close()

def transfer_dashboard_page():
    st.header("📊 Transfer Dashboard Overview")

    conn = sqlite3.connect(DB_PATH)

    # Load all transfer item data with warehouse info
    df = pd.read_sql_query('''
        SELECT 
            toi.ingredient_id,
            i.name AS ingredient,
            to.status,
            to.created_at,
            ws.name AS source,
            wt.name AS target,
            toi.quantity AS sent,
            toi.accepted_qty,
            toi.returned_qty,
            toi.wasted_qty
        FROM transfer_order_items toi
        JOIN transfer_orders to ON to.id = toi.transfer_order_id
        JOIN warehouses ws ON to.source_warehouse_id = ws.id
        JOIN warehouses wt ON to.target_warehouse_id = wt.id
        JOIN ingredients i ON toi.ingredient_id = i.id
    ''', conn)

    conn.close()

    if df.empty:
        st.info("No transfers found.")
        return

    # Convert dates
    df['created_at'] = pd.to_datetime(df['created_at'])

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        ingredient_filter = st.selectbox("Filter by Ingredient", ["All"] + sorted(df["ingredient"].unique()))
    with col2:
        warehouse_filter = st.selectbox("Filter by Warehouse (Source or Target)", ["All"] + sorted(set(df["source"]).union(set(df["target"]))))

    date_range = st.date_input("Filter by Date Range", [])

    # Apply filters
    if ingredient_filter != "All":
        df = df[df["ingredient"] == ingredient_filter]
    if warehouse_filter != "All":
        df = df[(df["source"] == warehouse_filter) | (df["target"] == warehouse_filter)]
    if len(date_range) == 2:
        start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        df = df[df["created_at"].between(start, end)]

    # Summary 1: Ingredient movement
    st.subheader("📦 Total Transferred Quantity per Ingredient")
    summary_ingredient = df.groupby("ingredient")[["sent", "accepted_qty", "returned_qty", "wasted_qty"]].sum()
    st.dataframe(summary_ingredient)

    # Summary 2: Warehouse-level totals
    st.subheader("🏭 Transfer Volume per Warehouse")
    df_sent = df.groupby("source")[["sent"]].sum().rename(columns={"sent": "total_sent"})
    df_received = df.groupby("target")[["accepted_qty"]].sum().rename(columns={"accepted_qty": "total_received"})
    warehouse_summary = df_sent.join(df_received, how="outer").fillna(0)
    st.dataframe(warehouse_summary)

    # Optional: Export all summaries
    st.subheader("📤 Export Dashboard Data")
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        summary_ingredient.to_excel(writer, sheet_name="By Ingredient")
        warehouse_summary.to_excel(writer, sheet_name="By Warehouse")
    buffer.seek(0)

    st.download_button(
        label="Download Dashboard Summary",
        data=buffer,
        file_name="transfer_dashboard_summary.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
import matplotlib.pyplot as plt

def transfer_visual_dashboard_page():
    st.header("📊 Transfer Visual Dashboard")

    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql_query('''
        SELECT 
            toi.ingredient_id,
            i.name AS ingredient,
            to.created_at,
            ws.name AS source,
            wt.name AS target,
            toi.quantity AS sent,
            toi.accepted_qty
        FROM transfer_order_items toi
        JOIN transfer_orders to ON to.id = toi.transfer_order_id
        JOIN ingredients i ON toi.ingredient_id = i.id
        JOIN warehouses ws ON to.source_warehouse_id = ws.id
        JOIN warehouses wt ON to.target_warehouse_id = wt.id
        WHERE to.status = 'Received'
    ''', conn)

    conn.close()

    if df.empty:
        st.info("No received transfer data to visualize.")
        return

    df['created_at'] = pd.to_datetime(df['created_at'])

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        selected_ingredient = st.selectbox("Ingredient", ["All"] + sorted(df["ingredient"].unique()))
    with col2:
        selected_warehouse = st.selectbox("Warehouse", ["All"] + sorted(set(df["source"]).union(set(df["target"]))))
    with col3:
        date_range = st.date_input("Date Range", [])

    # Apply filters
    if selected_ingredient != "All":
        df = df[df["ingredient"] == selected_ingredient]
    if selected_warehouse != "All":
        df = df[(df["source"] == selected_warehouse) | (df["target"] == selected_warehouse)]
    if len(date_range) == 2:
        start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        df = df[df["created_at"].between(start, end)]

    if df.empty:
        st.warning("No transfer data found for selected filters.")
        return

    # Tabs layout
    tab1, tab2, tab3 = st.tabs(["Top Ingredients", "Daily Transfers", "Warehouse Movement"])

    # Chart buffers for export
    chart_buffers = {}

    # --- Tab 1: Top Ingredients ---
    with tab1:
        st.subheader("📦 Top Transferred Ingredients")
        top_ing = df.groupby("ingredient")[["sent", "accepted_qty"]].sum().sort_values("sent", ascending=False).head(10)
        fig1, ax1 = plt.subplots()
        top_ing.plot(kind="bar", ax=ax1)
        ax1.set_ylabel("Quantity")
        ax1.set_title("Top 10 Ingredients by Volume")
        st.pyplot(fig1)

        buf1 = BytesIO()
        fig1.savefig(buf1, format="png")
        buf1.seek(0)
        chart_buffers["top_ingredients.png"] = buf1

    # --- Tab 2: Daily Transfer Volume ---
    with tab2:
        st.subheader("📅 Daily Transfer Volume")
        daily = df.groupby(df["created_at"].dt.date)[["sent", "accepted_qty"]].sum()
        fig2, ax2 = plt.subplots()
        daily.plot(ax=ax2)
        ax2.set_ylabel("Quantity")
        ax2.set_title("Daily Transfer Totals")
        st.pyplot(fig2)

        buf2 = BytesIO()
        fig2.savefig(buf2, format="png")
        buf2.seek(0)
        chart_buffers["daily_volume.png"] = buf2

    # --- Tab 3: Warehouse Activity ---
    with tab3:
        st.subheader("🏭 Warehouse Sent vs Received")
        sent_agg = df.groupby("source")[["sent"]].sum().rename(columns={"sent": "Total Sent"})
        recv_agg = df.groupby("target")[["accepted_qty"]].sum().rename(columns={"accepted_qty": "Total Received"})
        warehouse_chart = sent_agg.join(recv_agg, how="outer").fillna(0)

        fig3, ax3 = plt.subplots()
        warehouse_chart.plot(kind="bar", ax=ax3)
        ax3.set_ylabel("Quantity")
        ax3.set_title("Warehouse Movement Comparison")
        st.pyplot(fig3)

        buf3 = BytesIO()
        fig3.savefig(buf3, format="png")
        buf3.seek(0)
        chart_buffers["warehouse_comparison.png"] = buf3

    # --- Download All Charts as ZIP ---
    st.subheader("📤 Export All Charts")
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zipf:
        for name, buf in chart_buffers.items():
            zipf.writestr(name, buf.read())
    zip_buffer.seek(0)

    st.download_button(
        label="Download All Charts as ZIP",
        data=zip_buffer,
        file_name="transfer_dashboard_charts.zip",
        mime="application/zip"
    )

def manage_categories():
    st.header("🗂️ Manage Inventory Categories")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Ensure the table exists
    c.execute('''
        CREATE TABLE IF NOT EXISTS inventory_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    # --- Add New Category ---
    new_cat = st.text_input("➕ Add New Category", key="new_cat_input")
    if st.button("Add Category", key="add_cat_btn"):
        try:
            c.execute("INSERT INTO inventory_categories (name) VALUES (?)", (new_cat.strip(),))
            conn.commit()
            st.success(f"Category '{new_cat}' added.")
            st.experimental_rerun()
        except sqlite3.IntegrityError:
            st.error("Category already exists or is invalid.")

    st.divider()
    st.subheader("📝 Edit or Delete Existing Categories")

    # --- Fetch Categories ---
    c.execute("SELECT id, name FROM inventory_categories ORDER BY name")
    categories = c.fetchall()

    # --- Display Each Category in Its Own Block ---
    for cat in categories:
        cat_id, name = cat
        with st.container():
            col1, col2, col3 = st.columns([6, 2, 2])  # Wider for name input


            new_name = col1.text_input(
                label="",
                value=name,
                key=f"edit_name_{cat_id}",
                label_visibility="collapsed"
            )

            if col2.button("💾 Rename", key=f"rename_btn_{cat_id}"):
                if new_name.strip() == "":
                    st.warning("Name cannot be empty.")
                elif new_name.strip() == name:
                    st.info("No changes made.")
                else:
                    try:
                        c.execute("UPDATE inventory_categories SET name = ? WHERE id = ?", (new_name.strip(), cat_id))
                        conn.commit()
                        st.success(f"Renamed '{name}' to '{new_name.strip()}'")
                        st.experimental_rerun()
                    except sqlite3.IntegrityError:
                        st.error("That name already exists.")

            if col3.button("🗑️ Delete", key=f"delete_btn_{cat_id}"):
                c.execute("SELECT COUNT(*) FROM warehouse WHERE category_id = ?", (cat_id,))
                count = c.fetchone()[0]
                if count > 0:
                    st.warning(f"Cannot delete '{name}' – it's in use.")
                else:
                    c.execute("DELETE FROM inventory_categories WHERE id = ?", (cat_id,))
                    conn.commit()
                    st.success(f"Deleted '{name}'")
                    st.experimental_rerun()

    conn.close()


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



def view_warehouse():
    st.header("📊 Warehouse Stock Overview")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Fetch categories
    c.execute("SELECT id, name FROM inventory_categories")
    category_rows = c.fetchall()
    category_dict = {cat_id: name for cat_id, name in category_rows}
    category_filter_options = ["All"] + [name for _, name in category_rows]
    selected_category = st.selectbox("📂 Filter by Category", category_filter_options)

    # Fetch stock
    c.execute('''
        SELECT i.name, w.quantity, i.unit, w.par_level, w.last_updated, w.category_id
        FROM ingredients i
        LEFT JOIN warehouse w ON i.id = w.ingredient_id
    ''')

    rows = c.fetchall()
    data = []

    for name, qty, unit, par, updated, cat_id in rows:
        qty = qty or 0
        par = par or 0
        cat_name = category_dict.get(cat_id, "Uncategorized")
        if selected_category != "All" and cat_name != selected_category:
            continue
        alert = "🔴 LOW!" if qty < par else ""
        data.append({
            "Ingredient": name,
            "Category": cat_name,
            "Stock": round(qty, 2),
            "Par Level": round(par, 2),
            "Unit": unit,
            "Last Updated": updated or "N/A",
            "Alert": alert
        })

    if data:
        df = pd.DataFrame(data)
        st.dataframe(df)

        # 📥 Export Button
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Warehouse Stock')
        buffer.seek(0)

        st.download_button(
            label='📥 Export to Excel',
            data=buffer,
            file_name='warehouse_stock_report.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    else:
        st.warning("No stock data found for selected category.")

    conn.close()

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
def stock_report():
    st.header("📊 Stock Report")

    conn = sqlite3.connect(DB_PATH)

    # Load full data
    df = pd.read_sql_query('''
        SELECT 
            i.name AS ingredient,
            i.unit,
            ic.name AS category,
            w.quantity,
            w.par_level,
            w.last_updated
        FROM warehouse w
        JOIN ingredients i ON w.ingredient_id = i.id
        LEFT JOIN inventory_categories ic ON w.category_id = ic.id
        ORDER BY i.name
    ''', conn)

    # Convert last_updated to datetime
    if not df.empty:
        df['last_updated'] = pd.to_datetime(df['last_updated'], errors='coerce')

        # Filters
        col1, col2 = st.columns(2)

        with col1:
            search = st.text_input("🔍 Search Ingredient Name").strip().lower()
        with col2:
            date_range = st.date_input("📅 Filter by Last Updated", [], help="Select start and end date")

        # Apply filters
        if search:
            df = df[df['ingredient'].str.lower().str.contains(search)]
        if len(date_range) == 2:
            start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
            df = df[df['last_updated'].between(start, end)]

        st.dataframe(df, use_container_width=True)

        # Export to Excel
        to_excel = BytesIO()
        df.to_excel(to_excel, index=False)
        to_excel.seek(0)

        st.download_button(
            label="📤 Export Report to Excel",
            data=to_excel,
            file_name="stock_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("No stock data available.")

    conn.close()


# ----------------------
def manage_ingredients():
    st.header('Manage Ingredients')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    search_term = st.text_input('Search Ingredients')
    if search_term:
        c.execute("SELECT id, name, price_per_unit, unit FROM ingredients WHERE name LIKE ?", (f"%{search_term}%",))
    else:
        c.execute("SELECT id, name, price_per_unit, unit FROM ingredients")
    rows = c.fetchall()

    if rows:
        for ing_id, name, price, unit in rows:
            st.markdown(f"**{name}**")
            new_price = st.number_input(f"Price per Unit for {name}", value=price, step=0.00001, format="%.5f", key=f"price_{ing_id}")
            new_unit = st.text_input(f"Unit for {name}", value=unit, key=f"unit_{ing_id}")
            if st.button(f"Update {name}", key=f"update_{ing_id}"):
                c.execute("UPDATE ingredients SET price_per_unit = ?, unit = ? WHERE id = ?", (new_price, new_unit, ing_id))
                conn.commit()
                st.success(f"Updated {name} successfully!")
            if st.button(f"Delete {name}", key=f"delete_{ing_id}"):
                c.execute("DELETE FROM ingredients WHERE id = ?", (ing_id,))
                conn.commit()
                st.success(f"Deleted {name} successfully!")
    else:
        st.info("No ingredients found.")
    conn.close()
# View Costs (weight-adjusted sub-recipes)
# ----------------------
def view_costs():
    st.header('View Cake Costs')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, name FROM cakes')
    cakes = c.fetchall()

    if cakes:
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
                    st.error(f"Sub-recipe '{sub_name}' has zero total weight. Cannot calculate proportionally.")
                    continue

                for sid, sub_qty, name, price, unit in sub_ingredients:
                    ratio = sub_qty / sub_total_weight
                    scaled_qty = ratio * qty  # kg of this ingredient per qty kg of sub-recipe used
                    scaled_cost = scaled_qty * price
                    sub_total += scaled_cost
                    sub_rows.append({
                        'Ingredient': name,
                        'Quantity Used': round(scaled_qty, 4),
                        'Unit': unit,
                        'Cost': round(scaled_cost, 2)
                    })

                st.subheader(f"Sub-Recipe: {sub_name} × {qty} kg")
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
            st.subheader("Direct Ingredients")
            st.dataframe(pd.DataFrame(direct_items))

        st.success(f"Total Cost: {round(total, 2)}")
        conn.close()
    else:
        st.warning('No cakes available.')
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

# ----------------------
# Add Sub-Recipe (Manual)
# ----------------------
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

    options = [f"{i[1]} (Ingredient ID:{i[0]})" for i in ingredients] + [f"{s[1]} (Sub-Recipe ID:{s[0]})" for s in sub_recipes if sub_recipe_name not in s[1]]

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
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                try:
                    c.execute('CREATE TABLE IF NOT EXISTS sub_recipe_nested (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_sub_recipe_id INTEGER, sub_recipe_id INTEGER, quantity REAL, FOREIGN KEY (parent_sub_recipe_id) REFERENCES sub_recipes(id), FOREIGN KEY (sub_recipe_id) REFERENCES sub_recipes(id))')
                    c.execute('INSERT INTO sub_recipes (name) VALUES (?)', (sub_recipe_name,))
                    sub_recipe_id = c.lastrowid

                    for (item_id, item_type), qty in quantities.items():
                        if item_type == 'ingredient':
                            c.execute('INSERT INTO sub_recipe_ingredients (sub_recipe_id, ingredient_id, quantity) VALUES (?, ?, ?)', (sub_recipe_id, item_id, qty))
                        elif item_type == 'subrecipe':
                            c.execute('INSERT INTO sub_recipe_nested (parent_sub_recipe_id, sub_recipe_id, quantity) VALUES (?, ?, ?)', (sub_recipe_id, item_id, qty))

                    conn.commit()
                    st.success(f'Sub-Recipe {sub_recipe_name} added successfully!')
                except sqlite3.IntegrityError:
                    st.error('Sub-Recipe already exists.')
                conn.close()
            else:
                st.error('Please provide a Sub-Recipe name and select items.')
    else:
        st.warning('No ingredients or sub-recipes available.')



# ----------------------
# Quick Add Sub-Recipe
# ----------------------
...
# ----------------------
# Quick Add Sub-Recipe
# ----------------------
...
# ----------------------
# Quick Add Sub-Recipe
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

def create_warehouses_table(conn):
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS warehouses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    conn.commit()
def create_warehouse_stock_table(conn):
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS warehouse_stock (
            warehouse_id INTEGER,
            ingredient_id INTEGER,
            quantity REAL DEFAULT 0,
            PRIMARY KEY (warehouse_id, ingredient_id),
            FOREIGN KEY (warehouse_id) REFERENCES warehouses(id),
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        )
    ''')
    conn.commit()
def create_transfer_orders_tables(conn):
    c = conn.cursor()

    # Main transfer_orders table
    c.execute('''
        CREATE TABLE IF NOT EXISTS transfer_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_warehouse_id INTEGER,
            target_warehouse_id INTEGER,
            status TEXT DEFAULT 'Pending',
            created_at TEXT,
            FOREIGN KEY (source_warehouse_id) REFERENCES warehouses(id),
            FOREIGN KEY (target_warehouse_id) REFERENCES warehouses(id)
        )
    ''')

    # ✅ Updated transfer_order_items table
    c.execute('''
        CREATE TABLE IF NOT EXISTS transfer_order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transfer_order_id INTEGER,
            ingredient_id INTEGER,
            quantity REAL,
            accepted_qty REAL DEFAULT 0,
            returned_qty REAL DEFAULT 0,
            wasted_qty REAL DEFAULT 0,
            FOREIGN KEY (transfer_order_id) REFERENCES transfer_orders(id),
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        )
    ''')

    conn.commit()



def manage_sub_recipes():
    st.header('Manage Sub-Recipes')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('SELECT id, name FROM sub_recipes')
    sub_recipes = c.fetchall()

    if sub_recipes:
        selected = st.selectbox('Select Sub-Recipe to Manage', [f"{s[1]} (ID:{s[0]})" for s in sub_recipes])
        sub_id = int(selected.split('(ID:')[1].replace(')', ''))

        c.execute('SELECT name FROM sub_recipes WHERE id = ?', (sub_id,))
        row = c.fetchone()
        if not row:
            st.error("Sub-recipe not found.")
            return

        st.write(f"**Sub-Recipe Name:** {row[0]}")

        c.execute('''
            SELECT sri.id, sri.quantity, i.name, i.unit, i.price_per_unit, i.id as ing_id
            FROM sub_recipe_ingredients sri
            JOIN ingredients i ON sri.ingredient_id = i.id
            WHERE sri.sub_recipe_id = ?
        ''', (sub_id,))
        ingredients = c.fetchall()

        st.subheader('Current Ingredients')
        total_cost = 0
        cost_breakdown = []

        for row_id, qty, name, unit, price, ing_id in ingredients:
            new_qty = col1.number_input("Stock Quantity", min_value=0.0, step=0.1, format="%.2f", value=float(quantity),
                                        key=f"qty_{ing_id}")
            item_cost = new_qty * price
            total_cost += item_cost
            cost_breakdown.append({"Ingredient": name, "Quantity": new_qty, "Unit": unit, "Cost": round(item_cost, 2)})
            st.markdown(f"<span style='color:green'>Estimated Cost for {name}: {item_cost:,.2f}</span>", unsafe_allow_html=True)

            if st.button(f"Update {name}", key=f"update_{row_id}_sub"):
                c.execute('UPDATE sub_recipe_ingredients SET quantity = ? WHERE id = ?', (new_qty, row_id))
                conn.commit()
                st.success(f"Updated {name} quantity!")

            if st.button(f"Delete {name}", key=f"delete_{row_id}_sub"):
                c.execute('DELETE FROM sub_recipe_ingredients WHERE id = ?', (row_id,))
                conn.commit()
                st.success(f"Deleted {name} from Sub-Recipe!")

        st.subheader('Add New Ingredient or Sub-Recipe')
        c.execute('SELECT id, name, unit FROM ingredients')
        ingredient_list = c.fetchall()
        c.execute('SELECT id, name FROM sub_recipes WHERE id != ?', (sub_id,))
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
                    c.execute('INSERT INTO sub_recipe_ingredients (sub_recipe_id, ingredient_id, quantity) VALUES (?, ?, ?)', (sub_id, item_id, item_qty))
                else:
                    c.execute('SELECT ingredient_id, quantity FROM sub_recipe_ingredients WHERE sub_recipe_id = ?', (item_id,))
                    nested_parts = c.fetchall()
                    for ing_id, ing_qty in nested_parts:
                        flattened_qty = item_qty * ing_qty
                        c.execute('INSERT INTO sub_recipe_ingredients (sub_recipe_id, ingredient_id, quantity) VALUES (?, ?, ?)', (sub_id, ing_id, flattened_qty))
                conn.commit()
                st.success('Item added successfully!')
            except sqlite3.IntegrityError:
                st.error('Item already part of this sub-recipe.')

        st.dataframe(pd.DataFrame(cost_breakdown))
        st.success(f"Total Estimated Sub-Recipe Cost: {total_cost:,.2f}")

        if st.button('Delete Entire Sub-Recipe'):
            c.execute('DELETE FROM sub_recipes WHERE id = ?', (sub_id,))
            c.execute('DELETE FROM sub_recipe_ingredients WHERE sub_recipe_id = ?', (sub_id,))
            conn.commit()
            st.success('Sub-Recipe deleted successfully!')

    else:
        st.warning('No sub-recipes found.')

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


# ----------------------
# Add Cake
# ----------------------
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

# Manage Cakes
# ----------------------
# ----------------------
# Manage Sub-Recipes (mirror of Manage Cakes)
# ----------------------



def view_costs():
    st.header('View Cake Costs')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, name FROM cakes')
    cakes = c.fetchall()

    if cakes:
        selected = st.selectbox('Select Cake to View Cost', [f"{n} (ID:{i})" for i, n in cakes])
        cid = int(selected.split('(ID:')[1].replace(')', ''))

        c.execute('SELECT ingredient_or_subrecipe_id, is_subrecipe, quantity FROM cake_ingredients WHERE cake_id = ?', (cid,))
        parts = c.fetchall()

        total = 0
        direct_items = []
        resolved_rows = []

        for iid, is_sub, qty in parts:
            if is_sub:
                sub_rows = resolve_subrecipe_ingredients_detailed(conn, iid, final_qty=qty)
                resolved_rows.extend(sub_rows)
                total += sum(r['cost'] for r in sub_rows)
                st.subheader(f"Sub-Recipe (ID {iid}) × {qty} kg")
                st.dataframe(pd.DataFrame(sub_rows))
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
            st.subheader("Direct Ingredients")
            st.dataframe(pd.DataFrame(direct_items))

        st.success(f"Total Cost: {round(total, 2)}")
        conn.close()
    else:
        st.warning('No cakes available.')




# ----------------------
# Batch Production
# ----------------------
# ----------------------
# Batch Production (Corrected)
# ----------------------

# Manage (reused from canvas)
# ----------------------
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






# ----------------------
# Manage Cakes (fixed layout with yield + ingredients)
# ----------------------
def manage_cakes():
    st.header('Manage Cakes')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Ensure percent_yield column exists
    c.execute("PRAGMA table_info(cakes)")
    columns = [row[1] for row in c.fetchall()]
    if 'percent_yield' not in columns:
        c.execute("ALTER TABLE cakes ADD COLUMN percent_yield REAL DEFAULT 0")
        conn.commit()

    c.execute('SELECT id, name FROM cakes')
    cakes = c.fetchall()

    if cakes:
        selected = st.selectbox('Select Cake to Manage', [f"{c[1]} (ID:{c[0]})" for c in cakes])
        cake_id = int(selected.split('(ID:')[1].replace(')', ''))

        c.execute('SELECT name, percent_yield FROM cakes WHERE id = ?', (cake_id,))
        cake_row = c.fetchone()
        if not cake_row:
            st.error("Cake not found.")
        else:
            current_name, current_yield = cake_row

            # Editable Cake Name
            new_name = st.text_input('Edit Cake Name', value=current_name)
            if st.button('Update Cake Name'):
                try:
                    c.execute('UPDATE cakes SET name = ? WHERE id = ?', (new_name, cake_id))
                    conn.commit()
                    st.success('Cake name updated successfully!')
                    st.rerun()
                    return
                except Exception as e:
                    st.error(f'Failed to update cake name. Error: {e}')

            # Editable Yield
            new_yield = st.number_input('Edit Percent Yield (%)', value=current_yield or 0.0, min_value=0.0, step=0.01, format='%.2f')
            if st.button('Update Yield Only'):
                try:
                    c.execute('UPDATE cakes SET percent_yield = ? WHERE id = ?', (new_yield, cake_id))
                    conn.commit()
                    st.success('Percent yield updated successfully!')
                    st.rerun()
                    return
                except:
                    st.error('Failed to update yield.')

            # Load Ingredients
            c.execute('''
                SELECT ci.id, ci.is_subrecipe, ci.quantity,
                       COALESCE(i.name, sr.name),
                       CASE WHEN ci.is_subrecipe THEN 'Sub-Recipe' ELSE 'Ingredient' END,
                       ci.ingredient_or_subrecipe_id
                FROM cake_ingredients ci
                LEFT JOIN ingredients i ON ci.ingredient_or_subrecipe_id = i.id AND ci.is_subrecipe = 0
                LEFT JOIN sub_recipes sr ON ci.ingredient_or_subrecipe_id = sr.id AND ci.is_subrecipe = 1
                WHERE ci.cake_id = ?
            ''', (cake_id,))
            ingredients = c.fetchall()

            st.subheader('Current Ingredients/Sub-Recipes')
            cost_breakdown = []
            total_cost = 0

            for item_id, is_subrecipe, qty, item_name, item_type, ref_id in ingredients:
                new_qty = st.number_input(f"{item_name} ({item_type})", value=float(qty), step=0.00001, format="%.5f", key=f"{item_id}_qty_cake")

                # Cost calculation
                if is_subrecipe:
                    c.execute('''
                        SELECT SUM(sri.quantity * i.price_per_unit)
                        FROM sub_recipe_ingredients sri
                        JOIN ingredients i ON sri.ingredient_id = i.id
                        WHERE sri.sub_recipe_id = ?
                    ''', (ref_id,))
                    result = c.fetchone()
                    sub_recipe_total_cost = result[0] if result and result[0] is not None else 0

                    c.execute('SELECT SUM(quantity) FROM sub_recipe_ingredients WHERE sub_recipe_id = ?', (ref_id,))
                    weight_result = c.fetchone()
                    total_weight = weight_result[0] if weight_result and weight_result[0] is not None else 0

                    item_cost = 0
                    if total_weight:
                        proportion = new_qty / total_weight
                        item_cost = proportion * sub_recipe_total_cost
                        st.caption(f"{item_name} — Sub Weight: {total_weight:.3f} kg, Used: {new_qty:.3f} kg")
                        formula_str = f"({new_qty:.3f} / {total_weight:.3f}) × {sub_recipe_total_cost:.2f} = {item_cost:.2f}"
                        st.markdown(f"<small style='color:#888;'>[Formula] {formula_str}</small>", unsafe_allow_html=True)
                else:
                    c.execute('SELECT price_per_unit FROM ingredients WHERE id = ?', (ref_id,))
                    row = c.fetchone()
                    if row and row[0] is not None:
                        item_cost = new_qty * row[0]
                    else:
                        item_cost = 0
                        st.warning(f"⚠️ Missing price for ingredient '{item_name}'. Assuming EGP 0.")

                st.markdown(f"<span style='color:green'>Estimated Cost for {item_name}: {round(item_cost, 2)}</span>", unsafe_allow_html=True)
                cost_breakdown.append({"Item": item_name, "Type": item_type, "Quantity": new_qty, "Cost": round(item_cost, 2)})
                total_cost += item_cost

                if st.button(f"Update {item_name}", key=f"update_{item_id}_cake"):
                    c.execute('UPDATE cake_ingredients SET quantity = ? WHERE id = ?', (new_qty, item_id))
                    conn.commit()
                    st.success(f"Updated {item_name} quantity!")
                    st.rerun()
                    return

                if st.button(f"Delete {item_name}", key=f"delete_{item_id}_cake"):
                    c.execute('DELETE FROM cake_ingredients WHERE id = ?', (item_id,))
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
                    c.execute('INSERT INTO cake_ingredients (cake_id, ingredient_or_subrecipe_id, is_subrecipe, quantity) VALUES (?, ?, ?, ?)',
                              (cake_id, item_id, is_sub, item_qty))
                    conn.commit()
                    st.success('Added to cake successfully!')
                    st.rerun()
                    return
                except sqlite3.IntegrityError:
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
                c.execute('DELETE FROM cakes WHERE id = ?', (cake_id,))
                c.execute('DELETE FROM cake_ingredients WHERE cake_id = ?', (cake_id,))
                conn.commit()
                st.success('Cake deleted successfully!')
                st.rerun()
                return
    else:
        st.warning('No cakes found.')

    conn.close()

# ----------------------
def manage_ingredients():
    st.header('Manage Ingredients')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    search_term = st.text_input('Search Ingredients')
    if search_term:
        c.execute("SELECT id, name, price_per_unit, unit FROM ingredients WHERE name LIKE ?", (f"%{search_term}%",))
    else:
        c.execute("SELECT id, name, price_per_unit, unit FROM ingredients")
    rows = c.fetchall()

    if rows:
        for ing_id, name, price, unit in rows:
            st.markdown(f"**{name}**")
            new_price = st.number_input(f"Price per Unit for {name}", value=price, step=0.00001, format="%.5f", key=f"price_{ing_id}")
            new_unit = st.text_input(f"Unit for {name}", value=unit, key=f"unit_{ing_id}")
            if st.button(f"Update {name}", key=f"update_{ing_id}"):
                c.execute("UPDATE ingredients SET price_per_unit = ?, unit = ? WHERE id = ?", (new_price, new_unit, ing_id))
                conn.commit()
                st.success(f"Updated {name} successfully!")
            if st.button(f"Delete {name}", key=f"delete_{ing_id}"):
                c.execute("DELETE FROM ingredients WHERE id = ?", (ing_id,))
                conn.commit()
                st.success(f"Deleted {name} successfully!")
    else:
        st.info("No ingredients found.")
    conn.close()
# View Costs (weight-adjusted sub-recipes)
# ----------------------
def view_costs():
    st.header('View Cake Costs')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, name FROM cakes')
    cakes = c.fetchall()

    if cakes:
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
                    st.error(f"Sub-recipe '{sub_name}' has zero total weight. Cannot calculate proportionally.")
                    continue

                for sid, sub_qty, name, price, unit in sub_ingredients:
                    ratio = sub_qty / sub_total_weight
                    scaled_qty = ratio * qty  # kg of this ingredient per qty kg of sub-recipe used
                    scaled_cost = scaled_qty * price
                    sub_total += scaled_cost
                    sub_rows.append({
                        'Ingredient': name,
                        'Quantity Used': round(scaled_qty, 4),
                        'Unit': unit,
                        'Cost': round(scaled_cost, 2)
                    })

                st.subheader(f"Sub-Recipe: {sub_name} × {qty} kg")
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
            st.subheader("Direct Ingredients")
            st.dataframe(pd.DataFrame(direct_items))

        st.success(f"Total Cost: {round(total, 2)}")
        conn.close()
    else:
        st.warning('No cakes available.')


# ----------------------
# Main App
# ----------------------
# Main App
# ----------------------
def create_transfer_order_page():
    st.header("🚚 Create Transfer Order")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Load warehouses
    c.execute("SELECT id, name FROM warehouses ORDER BY name")
    warehouses = c.fetchall()
    warehouse_dict = {name: wid for wid, name in warehouses}

    # Warehouse selection
    col1, col2 = st.columns(2)
    source = col1.selectbox("Source Warehouse", list(warehouse_dict.keys()), index=0)
    target = col2.selectbox("Target Warehouse", list(warehouse_dict.keys()), index=1)

    if source == target:
        st.warning("Source and target warehouse must be different.")
        return

    source_id = warehouse_dict[source]
    target_id = warehouse_dict[target]

    # Get ingredient list with current stock at source
    c.execute('''
        SELECT i.id, i.name, i.unit, IFNULL(ws.quantity, 0)
        FROM ingredients i
        LEFT JOIN warehouse_stock ws 
            ON i.id = ws.ingredient_id AND ws.warehouse_id = ?
        ORDER BY i.name
    ''', (source_id,))
    ingredients = c.fetchall()

    st.subheader("📦 Select Items to Transfer")

    selected_items = []
    for ing_id, name, unit, qty in ingredients:
        col1, col2 = st.columns([6, 2])
        label = f"{name} ({unit}) - Available: {qty}"
        if qty > 0:
            transfer_qty = col1.number_input(label, min_value=0.0, max_value=qty, step=0.1, key=f"transfer_{ing_id}")
        else:
            col1.markdown(f"<span style='color:#888'>{label}</span>", unsafe_allow_html=True)
            transfer_qty = 0  # No input shown if not available
        if transfer_qty > 0:
            selected_items.append((ing_id, transfer_qty))

    if st.button("➕ Create Transfer Order"):
        if not selected_items:
            st.warning("You must select at least one ingredient with quantity.")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Insert transfer order
            c.execute('''
                INSERT INTO transfer_orders (source_warehouse_id, target_warehouse_id, status, created_at)
                VALUES (?, ?, 'Pending', ?)
            ''', (source_id, target_id, now))
            order_id = c.lastrowid

            # Insert transfer items
            for ing_id, qty in selected_items:
                c.execute('''
                    INSERT INTO transfer_order_items (transfer_order_id, ingredient_id, quantity)
                    VALUES (?, ?, ?)
                ''', (order_id, ing_id, qty))

            conn.commit()
            st.success(f"✅ Transfer Order #{order_id} created successfully.")

    conn.close()



def main():
    from PIL import Image
    st.set_page_config(page_title="KB's Cake Studio", layout='wide')

    from pathlib import Path
    if 'user' not in st.session_state:
        login_page()
        st.stop()

    st.sidebar.image('logo.png', width=150)
    st.sidebar.markdown(f"👤 Logged in as: `{st.session_state.user['username']}`")

    role = st.session_state.user['role']

    menu = [
        'Quick Add Cake',
        'Add Ingredient',
        'Add Sub-Recipe',
        'Quick Add Sub-Recipe',
        'Add Cake',
        'View Costs',
        'Batch Production',
        'Manage Ingredients',
        'Manage Sub-Recipes',
        'Manage Cakes',
        'Cake Report',
        'Warehouse Overview',
        'Manage Categories',
        'Update Stock',
        'Stock Report',
        'Stock Movements',
        'Transfer Orders',
        'Receive Transfers',
        'Transfer History',
        'Transfer Dashboard',
        'Transfer Charts',
        'Kitchen Production'
    ]

    if role == 'admin':
        menu.append('Manage Users & Roles')

    choice = st.sidebar.selectbox('Navigation', menu)

    if choice == 'Manage Users & Roles':
        manage_users_page()
        return

    st.write(f"🔐 Access Level: `{role}`")
    # Implement access filtering per page if needed
    st.write("🚧 Remaining app logic goes here...")

if __name__ == '__main__':
    create_user_and_role_tables()
    main()
