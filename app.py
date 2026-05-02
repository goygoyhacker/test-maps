import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Draw
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
            site_name TEXT,
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
            created_at TEXT NOT NULL,
            is_deleted INTEGER DEFAULT 0
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

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS geofences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name TEXT NOT NULL,
            polygon_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS user_geofence_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            site_id INTEGER NOT NULL,
            is_inside INTEGER NOT NULL,
            last_event TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    # Fix old database if columns do not exist yet
    c.execute("PRAGMA table_info(locations)")
    location_columns = [col[1] for col in c.fetchall()]
    if "site_name" not in location_columns:
        c.execute("ALTER TABLE locations ADD COLUMN site_name TEXT")

    c.execute("PRAGMA table_info(messages)")
    message_columns = [col[1] for col in c.fetchall()]
    if "is_deleted" not in message_columns:
        c.execute("ALTER TABLE messages ADD COLUMN is_deleted INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


# -----------------------------
# LOCATION FUNCTIONS
# -----------------------------
def save_location(name, role, lat, lon, accuracy, event_type, site_name=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO locations 
        (name, role, latitude, longitude, accuracy, event_type, site_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            role,
            lat,
            lon,
            accuracy,
            event_type,
            site_name,
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
    c.execute("DELETE FROM user_geofence_states")
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
                "site_name": latest_location.get("site_name", ""),
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
# GEOFENCE FUNCTIONS
# -----------------------------
def save_geofence(site_name, polygon_coordinates):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO geofences (site_name, polygon_json, created_at)
        VALUES (?, ?, ?)
        """,
        (site_name, json.dumps(polygon_coordinates), get_ph_time()),
    )
    conn.commit()
    conn.close()


def load_geofences():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM geofences ORDER BY id DESC", conn)
    conn.close()
    return df


def delete_geofence(site_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM geofences WHERE id = ?", (site_id,))
    c.execute("DELETE FROM user_geofence_states WHERE site_id = ?", (site_id,))
    conn.commit()
    conn.close()


def get_geofence_by_id(site_id):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        "SELECT * FROM geofences WHERE id = ?",
        conn,
        params=(site_id,),
    )
    conn.close()

    if df.empty:
        return None

    return df.iloc[0]


def point_inside_polygon(lat, lon, polygon_coordinates):
    """
    polygon_coordinates is GeoJSON format:
    [
        [
            [longitude, latitude],
            [longitude, latitude],
            ...
        ]
    ]
    """

    if not polygon_coordinates:
        return False

    polygon = polygon_coordinates[0]

    x = lon
    y = lat
    inside = False

    j = len(polygon) - 1

    for i in range(len(polygon)):
        xi = polygon[i][0]
        yi = polygon[i][1]
        xj = polygon[j][0]
        yj = polygon[j][1]

        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) + 0.0000000001) + xi
        )

        if intersect:
            inside = not inside

        j = i

    return inside


def get_user_geofence_state(username, site_id):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        """
        SELECT *
        FROM user_geofence_states
        WHERE username = ? AND site_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        conn,
        params=(username, site_id),
    )
    conn.close()

    if df.empty:
        return None

    return df.iloc[0]


def save_user_geofence_state(username, site_id, is_inside, last_event):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        """
        DELETE FROM user_geofence_states
        WHERE username = ? AND site_id = ?
        """,
        (username, site_id),
    )

    c.execute(
        """
        INSERT INTO user_geofence_states 
        (username, site_id, is_inside, last_event, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            username,
            site_id,
            1 if is_inside else 0,
            last_event,
            get_ph_time(),
        ),
    )

    conn.commit()
    conn.close()


def check_geofence_and_auto_attendance(username, site_id, lat, lon, accuracy):
    site = get_geofence_by_id(site_id)

    if site is None:
        return "No geofence site found."

    site_name = site["site_name"]
    polygon_coordinates = json.loads(site["polygon_json"])

    is_inside_now = point_inside_polygon(lat, lon, polygon_coordinates)
    previous_state = get_user_geofence_state(username, site_id)

    if previous_state is None:
        if is_inside_now:
            save_location(username, "user", lat, lon, accuracy, "Time In", site_name)
            save_user_geofence_state(username, site_id, True, "Time In")
            return f"Inside {site_name}. Automatic Time In recorded."
        else:
            save_location(username, "user", lat, lon, accuracy, "Location Update", site_name)
            save_user_geofence_state(username, site_id, False, "Outside")
            return f"Outside {site_name}. No Time In yet."

    was_inside = bool(previous_state["is_inside"])

    if not was_inside and is_inside_now:
        save_location(username, "user", lat, lon, accuracy, "Time In", site_name)
        save_user_geofence_state(username, site_id, True, "Time In")
        return f"You entered {site_name}. Automatic Time In recorded."

    if was_inside and not is_inside_now:
        save_location(username, "user", lat, lon, accuracy, "Time Out", site_name)
        save_user_geofence_state(username, site_id, False, "Time Out")
        return f"You left {site_name}. Automatic Time Out recorded."

    if is_inside_now:
        save_location(username, "user", lat, lon, accuracy, "Location Update", site_name)
        save_user_geofence_state(username, site_id, True, "Inside")
        return f"Still inside {site_name}. Location updated."

    save_location(username, "user", lat, lon, accuracy, "Location Update", site_name)
    save_user_geofence_state(username, site_id, False, "Outside")
    return f"Still outside {site_name}. Location updated."


# -----------------------------
# MAP FUNCTIONS
# -----------------------------
def add_geofence_polygons_to_map(m, geofences_df):
    if geofences_df.empty:
        return m

    for _, row in geofences_df.iterrows():
        polygon_coordinates = json.loads(row["polygon_json"])

        # Convert GeoJSON lon,lat to Folium lat,lon
        folium_polygon = []
        for point in polygon_coordinates[0]:
            lon = point[0]
            lat = point[1]
            folium_polygon.append([lat, lon])

        folium.Polygon(
            locations=folium_polygon,
            popup=f"Geofence: {row['site_name']}",
            tooltip=row["site_name"],
            fill=True,
        ).add_to(m)

    return m


def make_map(df, geofences_df=None):
    if df.empty:
        m = folium.Map(location=[8.4542, 124.6319], zoom_start=12)
        if geofences_df is not None:
            m = add_geofence_polygons_to_map(m, geofences_df)
        return m

    center_lat = df["latitude"].mean()
    center_lon = df["longitude"].mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=16)

    if geofences_df is not None:
        m = add_geofence_polygons_to_map(m, geofences_df)

    for _, row in df.iterrows():
        popup = (
            f"<b>{row['name']}</b><br>"
            f"Site: {row.get('site_name', '')}<br>"
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


def make_draw_map(existing_geofences_df):
    m = folium.Map(location=[8.4542, 124.6319], zoom_start=14)

    m = add_geofence_polygons_to_map(m, existing_geofences_df)

    draw = Draw(
        export=False,
        draw_options={
            "polyline": False,
            "rectangle": False,
            "circle": False,
            "circlemarker": False,
            "marker": False,
            "polygon": True,
        },
        edit_options={"edit": False},
    )

    draw.add_to(m)

    return m


# Start database
init_db()


# -----------------------------
# APP UI
# -----------------------------
st.title("📍 Simple Field Location Monitor with Polygon Geofencing")
st.caption(
    "Prototype only: admin draws a polygon geofence, user shares location with permission, "
    "and the system automatically records Time In or Time Out while the page is open."
)

mode = st.sidebar.radio("Choose screen", ["User End", "Admin End"])


# =====================================================
# USER END
# =====================================================
if mode == "User End":
    st.header("User End / Field Worker")

    st.info(
        "Enter your name, choose your assigned geofence site, then press Start Geofence Monitoring."
    )

    name = st.text_input("Your name", placeholder="Example: Josh")

    geofences_df = load_geofences()

    if geofences_df.empty:
        st.error("No geofence site has been created yet. Ask the admin to draw and save a geofence first.")
        selected_site_id = None
    else:
        site_options = {
            f"{row['site_name']} (ID {row['id']})": int(row["id"])
            for _, row in geofences_df.iterrows()
        }

        selected_site_label = st.selectbox("Assigned Geofence Site", list(site_options.keys()))
        selected_site_id = site_options[selected_site_label]

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
    # AUTOMATIC GEOFENCE MONITORING
    # -----------------------------
    st.subheader("Automatic Geofence Time In / Time Out")

    if "monitoring_started" not in st.session_state:
        st.session_state.monitoring_started = False

    if st.button("📍 Start Geofence Monitoring", use_container_width=True):
        if not name.strip():
            st.warning("Please enter your name first.")
        elif selected_site_id is None:
            st.warning("No geofence site selected.")
        else:
            st.session_state.monitoring_started = True
            st.success("Geofence monitoring started. Allow location permission if asked.")

    if st.button("Stop Geofence Monitoring", use_container_width=True):
        st.session_state.monitoring_started = False
        st.info("Geofence monitoring stopped.")

    @st.fragment(run_every="10s")
    def geofence_monitor(username, site_id):
        if not st.session_state.get("monitoring_started", False):
            st.warning("Monitoring is not running yet.")
            return

        if not username.strip():
            st.warning("Please enter your name first.")
            return

        if site_id is None:
            st.warning("No geofence site selected.")
            return

        st.info("Checking your current location...")

        location = get_geolocation()

        if location:
            if "error" in location:
                st.error(
                    f"Location error: {location['error'].get('message', 'Unknown error')}"
                )
                st.warning(
                    "If permission was blocked before, the browser may not show the popup again. "
                    "You may need to reset location permission once."
                )
                return

            coords = location.get("coords", {})
            lat = coords.get("latitude")
            lon = coords.get("longitude")
            accuracy = coords.get("accuracy")

            if lat is None or lon is None:
                st.warning("Location was detected but latitude/longitude is missing.")
                return

            result_message = check_geofence_and_auto_attendance(
                username.strip(),
                site_id,
                lat,
                lon,
                accuracy,
            )

            st.success(result_message)

            st.write(f"Latitude: `{lat}`")
            st.write(f"Longitude: `{lon}`")
            st.write(f"Accuracy: `{accuracy}` meters")

            site = get_geofence_by_id(site_id)
            site_df = pd.DataFrame([site]) if site is not None else pd.DataFrame()

            user_map_df = pd.DataFrame(
                [
                    {
                        "name": username,
                        "latitude": lat,
                        "longitude": lon,
                        "accuracy": accuracy,
                        "event_type": "Current Location",
                        "site_name": site["site_name"] if site is not None else "",
                        "created_at": get_ph_time(),
                    }
                ]
            )

            st_folium(make_map(user_map_df, site_df), height=400, width=None)

        else:
            st.warning("Waiting for location permission. If nothing appears, tap Start Geofence Monitoring again.")

    geofence_monitor(name, selected_site_id)

    # -----------------------------
    # MANUAL LOCATION FALLBACK
    # -----------------------------
    with st.expander("Manual location fallback"):
        st.write(
            "Use this only if GPS permission does not work. You can copy coordinates from Google Maps."
        )

        manual_lat = st.number_input("Latitude", format="%.8f")
        manual_lon = st.number_input("Longitude", format="%.8f")

        if st.button("Check manual location against geofence"):
            if not name.strip():
                st.warning("Please enter your name first.")
            elif selected_site_id is None:
                st.warning("No geofence site selected.")
            elif manual_lat == 0 or manual_lon == 0:
                st.warning("Please enter valid latitude and longitude.")
            else:
                result_message = check_geofence_and_auto_attendance(
                    name.strip(),
                    selected_site_id,
                    manual_lat,
                    manual_lon,
                    None,
                )
                st.success(result_message)


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
        geofences_df = load_geofences()

        # -----------------------------
        # ADMIN DRAWS POLYGON GEOFENCE
        # -----------------------------
        st.subheader("Draw Polygon Geofence")

        st.info(
            "Use the polygon drawing tool on the left side of the map. "
            "Draw the boundary of the work area, then type a site name and click Save Drawn Geofence."
        )

        site_name = st.text_input("New Geofence Site Name", placeholder="Example: NIA Site A")

        draw_map = make_draw_map(geofences_df)

        draw_result = st_folium(
            draw_map,
            height=500,
            width=None,
            returned_objects=["last_active_drawing", "all_drawings"],
            key="draw_geofence_map",
        )

        if st.button("Save Drawn Geofence"):
            if not site_name.strip():
                st.warning("Please enter a site name first.")
            else:
                drawing = None

                if draw_result:
                    drawing = draw_result.get("last_active_drawing")

                if not drawing:
                    st.warning("Please draw a polygon on the map first.")
                else:
                    geometry = drawing.get("geometry", {})
                    geometry_type = geometry.get("type")

                    if geometry_type != "Polygon":
                        st.warning("Please draw a polygon only.")
                    else:
                        polygon_coordinates = geometry.get("coordinates")

                        if not polygon_coordinates:
                            st.warning("Polygon data is missing.")
                        else:
                            save_geofence(site_name.strip(), polygon_coordinates)
                            st.success(f"Geofence saved for {site_name}.")
                            st.rerun()

        # -----------------------------
        # VIEW AND DELETE GEOFENCES
        # -----------------------------
        st.subheader("Saved Geofences")

        if geofences_df.empty:
            st.info("No geofences saved yet.")
        else:
            st.dataframe(
                geofences_df[["id", "site_name", "created_at"]],
                use_container_width=True,
            )

            geofence_ids = geofences_df["id"].tolist()
            selected_geofence_id = st.selectbox("Select geofence ID to delete", geofence_ids)

            if st.button("Delete selected geofence"):
                delete_geofence(int(selected_geofence_id))
                st.success(f"Geofence #{selected_geofence_id} deleted.")
                st.rerun()

        st.divider()

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
        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Total Location Records", len(df))
        col2.metric(
            "Tracked Users",
            latest_df["name"].nunique() if not latest_df.empty else 0,
        )
        col3.metric("Latest User Updates", len(latest_df))
        col4.metric("Saved Geofences", len(geofences_df))

        # -----------------------------
        # ADMIN MAP
        # -----------------------------
        st.subheader("Latest Location Per User with Geofences")
        st_folium(make_map(latest_df, geofences_df), height=500, width=None)

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
                        "site_name",
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