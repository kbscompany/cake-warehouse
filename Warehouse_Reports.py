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

    def stock_report():
        st.header("📊 Stock Report")

        conn = sqlite3.connect(DB_PATH)

        # Load full data
        df = pd.read_sql_query('''
                               SELECT i.name  AS ingredient,
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

def stock_report():
    st.header("📊 Stock Report")

    conn = sqlite3.connect(DB_PATH)

    # Load full data
    df = pd.read_sql_query('''
                                   SELECT i.name  AS ingredient,
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
