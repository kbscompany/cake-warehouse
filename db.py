import mysql.connector
from dotenv import load_dotenv
import os
import streamlit as st

# Load environment variables from .env file
load_dotenv()


def get_connection():
    try:
        # Default values if environment variables are not set
        host = os.getenv("DB_HOST", "localhost")
        port = int(os.getenv("DB_PORT", "3306"))
        user = os.getenv("DB_USER", "root")
        password = os.getenv("DB_PASSWORD", "")
        database = os.getenv("DB_NAME", "bakery_db")
        
        # Create connection
        return mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )
    except mysql.connector.Error as err:
        st.error(f"❌ DB Connection failed: {err}")
        return None

