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
