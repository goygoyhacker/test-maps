import sqlite3
from datetime import datetime

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

DB_FILE = "locations.db"
ADMIN_PASSWORD = "admin123"  # change this before sharing your app

st.set_page_config(page_title="Simple Field Location Monitor", layout="wide")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy REAL,
            event_type TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def save_location(name, role, lat, lon, accuracy, event_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO locations (name, role, latitude, longitude, accuracy, event_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (name, role, lat, lon, accuracy, event_type, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()


def load_locations():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM locations ORDER BY created_at DESC", conn)
    conn.close()
    return df


def latest_per_user(df):
    if df.empty:
        return df
    return df.sort_values("created_at", ascending=False).drop_duplicates(subset=["name"])


def make_map(df):
    if df.empty:
        return folium.Map(location=[8.4542, 124.6319], zoom_start=12)  # Cagayan de Oro default

    center_lat = df["latitude"].mean()
    center_lon = df["longitude"].mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=16)

    for _, row in df.iterrows():
        popup = (
            f"<b>{row['name']}</b><br>"
            f"Event: {row.get('event_type', '')}<br>"
            f"Time: {row['created_at']}<br>"
            f"Accuracy: {row.get('accuracy', 'N/A')} meters"
        )
        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            popup=popup,
            tooltip=f"{row['name']} - {row['created_at']}",
        ).add_to(m)

        if pd.notna(row.get("accuracy")):
            folium.Circle(
                location=[row["latitude"], row["longitude"]],
                radius=float(row["accuracy"]),
                fill=True,
            ).add_to(m)

    return m


init_db()

st.title("📍 Simple Field Location Monitor")
st.caption("Prototype only: user shares location manually, admin views latest location on a map.")

mode = st.sidebar.radio("Choose screen", ["User End", "Admin End"])

if mode == "User End":
    st.header("User End / Field Worker")
    st.info("Open this on your phone. The browser will ask permission before sharing your location.")

    name = st.text_input("Your name", placeholder="Example: Josh")
    event_type = st.selectbox("Action", ["Location Update", "Time In", "Time Out"])

    st.write("Press the location button below, allow location permission, then save it.")
    location = get_geolocation()

    if location:
        if "error" in location:
            st.error(f"Location error: {location['error'].get('message', 'Unknown error')}")
        else:
            coords = location.get("coords", {})
            lat = coords.get("latitude")
            lon = coords.get("longitude")
            accuracy = coords.get("accuracy")

            st.success("Location detected.")
            st.write(f"Latitude: `{lat}`")
            st.write(f"Longitude: `{lon}`")
            st.write(f"Accuracy: `{accuracy}` meters")

            preview_map = folium.Map(location=[lat, lon], zoom_start=17)
            folium.Marker([lat, lon], popup="You are here").add_to(preview_map)
            st_folium(preview_map, height=350, width=None)

            if st.button("Save / Send my location"):
                if not name.strip():
                    st.warning("Please enter your name first.")
                else:
                    save_location(name.strip(), "user", lat, lon, accuracy, event_type)
                    st.success("Your location was saved. The admin can now see it.")
    else:
        st.warning("No location yet. Click the geolocation button and allow permission.")

elif mode == "Admin End":
    st.header("Admin End / Supervisor")
    password = st.text_input("Admin password", type="password")

    if password != ADMIN_PASSWORD:
        st.warning("Enter the admin password to view locations. Default is admin123.")
    else:
        df = load_locations()
        latest_df = latest_per_user(df)

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Records", len(df))
        col2.metric("Tracked Users", latest_df["name"].nunique() if not latest_df.empty else 0)
        col3.metric("Latest Updates", len(latest_df))

        st.subheader("Latest location per user")
        st_folium(make_map(latest_df), height=500, width=None)

        st.subheader("Latest table")
        if latest_df.empty:
            st.info("No user locations yet.")
        else:
            st.dataframe(
                latest_df[["name", "event_type", "latitude", "longitude", "accuracy", "created_at"]],
                use_container_width=True,
            )

        st.subheader("All location records")
        st.dataframe(df, use_container_width=True)

        if st.button("Refresh admin map"):
            st.rerun()
