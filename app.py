import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

DB_FILE = "locations.db"
ADMIN_PASSWORD = "admin123"
PH_TIMEZONE = ZoneInfo("Asia/Manila")

st.set_page_config(page_title="Simple Field Location Monitor", layout="wide")


# -----------------------------
# TIME FUNCTION - PHILIPPINES TIME
# -----------------------------
def get_ph_time():
    return datetime.now(PH_TIMEZONE).strftime("%Y-%m-%d %I:%M:%S %p")


# -----------------------------
# DATABASE SETUP
# -----------------------------
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

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS dismissed_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            dismissed_at TEXT NOT NULL
        )
        """
    )

    c.execute("PRAGMA table_info(messages)")
    message_columns = [col[1] for col in c.fetchall()]

    if "is_deleted" not in message_columns:
        c.execute("ALTER TABLE messages ADD COLUMN is_deleted INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


# -----------------------------
# LOCATION FUNCTIONS
# -----------------------------
def save_location(name, role, lat, lon, accuracy, event_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO locations (name, role, latitude, longitude, accuracy, event_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            role,
            lat,
            lon,
            accuracy,
            event_type,
            get_ph_time(),
        ),
    )
    conn.commit()
    conn.close()


def load_locations():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM locations ORDER BY id DESC", conn)
    conn.close()
    return df


def delete_user_locations(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM locations WHERE name = ?", (username,))
    conn.commit()
    conn.close()


def delete_all_location_records():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM locations")
    conn.commit()
    conn.close()


def latest_per_user(df):
    if df.empty:
        return df

    return df.sort_values("id", ascending=False).drop_duplicates(subset=["name"])


def attendance_summary(df):
    if df.empty:
        return pd.DataFrame()

    summary_rows = []
    users = df["name"].dropna().unique()

    for user in users:
        user_df = df[df["name"] == user].sort_values("id", ascending=False)
        latest_location = user_df.iloc[0]

        time_in_df = user_df[user_df["event_type"] == "Time In"]
        time_out_df = user_df[user_df["event_type"] == "Time Out"]

        latest_time_in = time_in_df.iloc[0]["created_at"] if not time_in_df.empty else ""
        latest_time_out = time_out_df.iloc[0]["created_at"] if not time_out_df.empty else ""

        summary_rows.append(
            {
                "name": user,
                "time_in": latest_time_in,
                "time_out": latest_time_out,
                "latest_event": latest_location["event_type"],
                "latitude": latest_location["latitude"],
                "longitude": latest_location["longitude"],
                "accuracy": latest_location["accuracy"],
                "last_update": latest_location["created_at"],
            }
        )

    return pd.DataFrame(summary_rows)


# -----------------------------
# MESSAGE FUNCTIONS
# -----------------------------
def save_message(sender, receiver, message):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO messages (sender, receiver, message, created_at, is_deleted)
        VALUES (?, ?, ?, ?, 0)
        """,
        (
            sender,
            receiver,
            message,
            get_ph_time(),
        ),
    )
    conn.commit()
    conn.close()


def load_messages_for_user(receiver):
    conn = sqlite3.connect(DB_FILE)

    df = pd.read_sql_query(
        """
        SELECT m.*
        FROM messages m
        WHERE 
            (m.receiver = ? OR m.receiver = 'ALL')
            AND m.is_deleted = 0
            AND m.id NOT IN (
                SELECT message_id 
                FROM dismissed_messages 
                WHERE username = ?
            )
        ORDER BY m.id DESC
        LIMIT 10
        """,
        conn,
        params=(receiver, receiver),
    )

    conn.close()
    return df


def load_all_messages():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        """
        SELECT * 
        FROM messages 
        WHERE is_deleted = 0
        ORDER BY id DESC
        """,
        conn,
    )
    conn.close()
    return df


def dismiss_message(username, message_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        """
        SELECT id FROM dismissed_messages
        WHERE username = ? AND message_id = ?
        """,
        (username, message_id),
    )

    existing = c.fetchone()

    if existing is None:
        c.execute(
            """
            INSERT INTO dismissed_messages (username, message_id, dismissed_at)
            VALUES (?, ?, ?)
            """,
            (username, message_id, get_ph_time()),
        )

    conn.commit()
    conn.close()


def delete_message(message_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE messages SET is_deleted = 1 WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()


def delete_all_messages():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE messages SET is_deleted = 1")
    conn.commit()
    conn.close()


# -----------------------------
# MAP FUNCTION
# -----------------------------
def make_map(df):
    if df.empty:
        return folium.Map(location=[8.4542, 124.6319], zoom_start=12)

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


# Start database
init_db()


# -----------------------------
# APP UI
# -----------------------------
st.title("📍 Simple Field Location Monitor")
st.caption("Prototype only: user shares location with permission, admin views latest location on a map.")

mode = st.sidebar.radio("Choose screen", ["User End", "Admin End"])


# =====================================================
# USER END
# =====================================================
if mode == "User End":
    st.header("User End / Field Worker")

    st.info(
        "Step 1: Enter your name. Step 2: Choose Time In or Time Out. "
        "Step 3: Press the big location button below and allow location permission."
    )

    name = st.text_input("Your name", placeholder="Example: Josh")
    event_type = st.selectbox("Action", ["Location Update", "Time In", "Time Out"])

    # -----------------------------
    # USER RECEIVES ADMIN MESSAGES
    # -----------------------------
    st.subheader("Messages from Admin")

    @st.fragment(run_every="5s")
    def show_admin_messages(username):
        if not username.strip():
            st.info("Enter your name to receive admin messages.")
            return

        messages_df = load_messages_for_user(username.strip())

        if messages_df.empty:
            st.info("No new messages.")
        else:
            latest = messages_df.iloc[0]
            message_id = int(latest["id"])

            st.warning(f"📩 Admin message: {latest['message']}")
            st.caption(f"Sent: {latest['created_at']}")

            if st.button("Dismiss message", key=f"dismiss_{message_id}"):
                dismiss_message(username.strip(), message_id)
                st.success("Message dismissed.")
                st.rerun()

            with st.expander("View other unread messages"):
                for _, row in messages_df.iterrows():
                    row_message_id = int(row["id"])

                    st.write(f"**{row['created_at']}**")
                    st.write(row["message"])

                    if st.button(
                        f"Dismiss this message #{row_message_id}",
                        key=f"dismiss_old_{row_message_id}",
                    ):
                        dismiss_message(username.strip(), row_message_id)
                        st.success("Message dismissed.")
                        st.rerun()

                    st.divider()

    show_admin_messages(name)

    # -----------------------------
    # USER SENDS LOCATION
    # -----------------------------
    st.subheader("Send My Location")

    st.markdown(
        """
        ### Press this button first:
        """
    )

    if "request_location" not in st.session_state:
        st.session_state.request_location = False

    if st.button("📍 ALLOW / GET MY CURRENT LOCATION", use_container_width=True):
        st.session_state.request_location = True

    if not st.session_state.request_location:
        st.warning("Location permission has not been requested yet. Press the big button above.")
    else:
        st.info("If your browser asks for permission, choose Allow.")

        location = get_geolocation()

        if location:
            if "error" in location:
                st.error(
                    f"Location error: {location['error'].get('message', 'Unknown error')}"
                )

                st.warning(
                    "If you previously tapped Block or Don't Allow, the browser may not show the popup again. "
                    "In that case, you need to reset location permission for this website once."
                )

            else:
                coords = location.get("coords", {})
                lat = coords.get("latitude")
                lon = coords.get("longitude")
                accuracy = coords.get("accuracy")

                if lat is not None and lon is not None:
                    st.success("Location detected.")
                    st.write(f"Latitude: `{lat}`")
                    st.write(f"Longitude: `{lon}`")
                    st.write(f"Accuracy: `{accuracy}` meters")

                    preview_map = folium.Map(location=[lat, lon], zoom_start=17)
                    folium.Marker([lat, lon], popup="You are here").add_to(preview_map)
                    st_folium(preview_map, height=350, width=None)

                    if st.button("Save / Send my location", use_container_width=True):
                        if not name.strip():
                            st.warning("Please enter your name first.")
                        else:
                            save_location(
                                name.strip(),
                                "user",
                                lat,
                                lon,
                                accuracy,
                                event_type,
                            )
                            st.success("Your location was saved. The admin can now see it.")
                else:
                    st.warning("Location was detected but latitude/longitude is missing.")
        else:
            st.warning("Waiting for location permission. If nothing appears, check browser permission.")

    # -----------------------------
    # MANUAL LOCATION FALLBACK
    # -----------------------------
    with st.expander("Manual location fallback"):
        st.write(
            "Use this only if GPS permission does not work. You can copy coordinates from Google Maps."
        )

        manual_lat = st.number_input("Latitude", format="%.8f")
        manual_lon = st.number_input("Longitude", format="%.8f")

        if st.button("Save manual location"):
            if not name.strip():
                st.warning("Please enter your name first.")
            elif manual_lat == 0 or manual_lon == 0:
                st.warning("Please enter valid latitude and longitude.")
            else:
                save_location(
                    name.strip(),
                    "user",
                    manual_lat,
                    manual_lon,
                    None,
                    event_type,
                )
                st.success("Manual location saved. Admin can now see it.")


# =====================================================
# ADMIN END
# =====================================================
elif mode == "Admin End":
    st.header("Admin End / Supervisor")

    password = st.text_input("Admin password", type="password")

    if password != ADMIN_PASSWORD:
        st.warning("Enter the admin password to view locations. Default is admin123.")
    else:
        st.success("Admin access granted.")

        df = load_locations()
        latest_df = latest_per_user(df)
        attendance_df = attendance_summary(df)

        # -----------------------------
        # ADMIN SENDS MESSAGE
        # -----------------------------
        st.subheader("Send Message to User")

        users = sorted(df["name"].dropna().unique().tolist()) if not df.empty else []
        receiver_options = ["ALL"] + users

        receiver = st.selectbox("Send to", receiver_options)
        admin_message = st.text_area("Message", placeholder="Example: Proceed to Site A.")

        if st.button("Send message"):
            if not admin_message.strip():
                st.warning("Please type a message first.")
            else:
                save_message("admin", receiver, admin_message.strip())
                st.success(f"Message sent to {receiver}.")
                st.rerun()

        st.divider()

        # -----------------------------
        # ADMIN DASHBOARD METRICS
        # -----------------------------
        col1, col2, col3 = st.columns(3)

        col1.metric("Total Location Records", len(df))
        col2.metric(
            "Tracked Users",
            latest_df["name"].nunique() if not latest_df.empty else 0,
        )
        col3.metric("Latest User Updates", len(latest_df))

        # -----------------------------
        # ADMIN MAP
        # -----------------------------
        st.subheader("Latest location per user")
        st_folium(make_map(latest_df), height=500, width=None)

        # -----------------------------
        # ATTENDANCE SUMMARY TABLE
        # -----------------------------
        st.subheader("Attendance Summary")

        if attendance_df.empty:
            st.info("No user locations yet.")
        else:
            st.dataframe(
                attendance_df[
                    [
                        "name",
                        "time_in",
                        "time_out",
                        "latest_event",
                        "latitude",
                        "longitude",
                        "accuracy",
                        "last_update",
                    ]
                ],
                use_container_width=True,
            )

        # -----------------------------
        # DELETE USER LOCATION RECORDS
        # -----------------------------
        st.subheader("Delete User from Location Table")

        if df.empty:
            st.info("No users to delete yet.")
        else:
            delete_user = st.selectbox(
                "Select user to delete",
                sorted(df["name"].dropna().unique().tolist()),
            )

            confirm_delete_user = st.checkbox(
                f"I confirm that I want to delete all location records for {delete_user}"
            )

            if st.button("Delete selected user location records"):
                if confirm_delete_user:
                    delete_user_locations(delete_user)
                    st.success(f"Deleted all location records for {delete_user}.")
                    st.rerun()
                else:
                    st.warning("Please check the confirmation box first.")

            confirm_delete_all_users = st.checkbox(
                "I confirm that I want to delete ALL location records"
            )

            if st.button("Delete ALL location records"):
                if confirm_delete_all_users:
                    delete_all_location_records()
                    st.success("All location records deleted.")
                    st.rerun()
                else:
                    st.warning("Please check the confirmation box first.")

        # -----------------------------
        # MESSAGE MANAGEMENT
        # -----------------------------
        st.subheader("Manage Sent Messages")

        messages_df = load_all_messages()

        if messages_df.empty:
            st.info("No active messages.")
        else:
            st.dataframe(
                messages_df[["id", "receiver", "message", "created_at"]],
                use_container_width=True,
            )

            message_ids = messages_df["id"].tolist()
            selected_message_id = st.selectbox(
                "Select message ID to delete",
                message_ids,
            )

            if st.button("Delete selected message"):
                delete_message(int(selected_message_id))
                st.success(f"Message #{selected_message_id} deleted.")
                st.rerun()

            confirm_delete_all_messages = st.checkbox(
                "I confirm that I want to delete ALL sent messages"
            )

            if st.button("Delete ALL sent messages"):
                if confirm_delete_all_messages:
                    delete_all_messages()
                    st.success("All messages deleted.")
                    st.rerun()
                else:
                    st.warning("Please check the confirmation box first.")

        # -----------------------------
        # ALL LOCATION RECORDS
        # -----------------------------
        with st.expander("View all location records"):
            if df.empty:
                st.info("No location records yet.")
            else:
                st.dataframe(df, use_container_width=True)

        if st.button("Refresh admin dashboard"):
            st.rerun()