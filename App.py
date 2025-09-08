import streamlit as st
from twilio.rest import Client
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# -----------------------
# CONFIG
# -----------------------
USERNAME = st.secrets.get("APP_USER")
PASSWORD = st.secrets.get("APP_PASS")
TWILIO_SID = st.secrets["TWILIO_SID"]
TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]

# Twilio client
client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

# Name mapping (add more as needed)
NAME_MAP = {
    "+13613332093": "Warren Kadd",
    "+12109341811": "Swapnil B",
    "+14693789446": "Roshan Y",
}

# -----------------------
# TIME RANGE (IST 5PM–5AM)
# -----------------------
IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)

# Yesterday 5 PM IST
start_ist = (now_ist.replace(hour=17, minute=0, second=0, microsecond=0) 
             - timedelta(days=1))
# Today 5 AM IST
end_ist = start_ist + timedelta(hours=12)

# Convert to UTC for Twilio
start_utc = start_ist.astimezone(timezone.utc)
end_utc = end_ist.astimezone(timezone.utc)

# -----------------------
# STREAMLIT APP
# -----------------------
st.title("📊 Twilio Daily Report")

# --- LOGIN ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == USERNAME and password == PASSWORD:
            st.session_state["logged_in"] = True
            st.success("✅ Login successful")
        else:
            st.error("❌ Invalid credentials")
    st.stop()   # stop app until login

# --- FETCH REPORT ---
if st.button("Get Report"):
    report_data = defaultdict(lambda: {"calls": 0, "sms": 0, "duration": 0})

    # --- Fetch Calls (fixed) ---
    calls = client.calls.list(
        start_time_after=start_utc,
        start_time_before=end_utc,
        status="completed"
    )
    for c in calls:
        if c.from_:
            report_data[c.from_]["calls"] += 1
            try:
                d = int(c.duration) if c.duration else 0
            except:
                d = 0
            report_data[c.from_]["duration"] += d

    # --- Fetch SMS (unchanged) ---
    messages = client.messages.list(
        date_sent_after=start_utc,
        date_sent_before=end_utc       
    )
    for m in messages:
        if m.from_:
            report_data[m.from_]["sms"] += 1

    # Show Report
    today = now_ist.strftime("%d-%b-%Y")
    st.subheader(f"📊 Daily Twilio Report ({today})")

    if not report_data:
        st.info("No calls or SMS found in this time window.")
    else:
        for number, stats in report_data.items():
            name = NAME_MAP.get(number, "Unknown")
            st.write(
                f"{name:12} {number} → "
                f"{stats['calls']} Calls "
                f"(Total {stats['duration']} sec), "
                f"{stats['sms']} SMS"
            )
