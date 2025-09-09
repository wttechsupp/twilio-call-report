import re
import streamlit as st
from twilio.rest import Client
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# -----------------------
# CONFIG (from Streamlit secrets)
# -----------------------
try:
    USERNAME = st.secrets["APP_USER"]
    PASSWORD = st.secrets["APP_PASS"]
    TWILIO_SID = st.secrets["TWILIO_SID"]
    TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
except Exception as e:
    st.error("Missing secrets. Please set APP_USER, APP_PASS, TWILIO_SID, TWILIO_AUTH_TOKEN in Streamlit Secrets.")
    st.stop()

client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

# -----------------------
# NAME MAP
#   - Put your Twilio line numbers (for SMS) and/or caller IDs here.
#   - We’ll normalize E.164-looking numbers; we also keep exact raw keys (e.g., 'client:agent1').
# -----------------------
NAME_MAP = {
    "+13613332093": "Warren Kadd",
    "+12109341811": "Swapnil B",
    "+14693789446": "Roshan Y",
    # "client:agent1": "Agent 1",
}

def normalize_number(val):
    """Return E.164-ish phone number if found; else None."""
    if not val:
        return None
    s = str(val)
    m = re.search(r'(\+?\d{5,15})', s)
    if m:
        num = m.group(1)
        return num if num.startswith("+") else "+" + num
    return None

# Build lookup that works with either raw IDs or normalized numbers
NAME_LOOKUP = {}
for k, v in NAME_MAP.items():
    NAME_LOOKUP[str(k)] = v
    nk = normalize_number(k)
    if nk:
        NAME_LOOKUP[nk] = v

def name_for(key):
    return NAME_LOOKUP.get(key, "Unknown")

# -----------------------
# TIME RANGE (IST 5PM–5AM)
# -----------------------
IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)

# yesterday 17:00 → today 05:00 by default
start_ist = (now_ist.replace(hour=17, minute=0, second=0, microsecond=0) - timedelta(days=1))
end_ist = start_ist + timedelta(hours=12)

# if it's before 05:00 now, cap end at "now" so we don't query future
if now_ist < end_ist:
    end_ist = now_ist

# Twilio wants UTC
start_utc = start_ist.astimezone(timezone.utc)
end_utc = end_ist.astimezone(timezone.utc)

# -----------------------
# STREAMLIT UI
# -----------------------
st.title("📊 Twilio Daily Report")
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == USERNAME and password == PASSWORD:
            st.session_state["logged_in"] = True
            st.success("✅ Login successful")
            st.experimental_rerun()
        else:
            st.error("❌ Invalid credentials")
    st.stop()

st.markdown(f"**Window (IST):** {start_ist.strftime('%d-%b-%Y %I:%M %p')} → {end_ist.strftime('%d-%b-%Y %I:%M %p')}")
st.markdown(f"**Window (UTC):** {start_utc.isoformat()} → {end_utc.isoformat()}")

show_raw = st.checkbox("Show raw samples (calls/messages) — use for debugging", value=False)

if st.button("Get Report"):
    # Separate aggregates
    sms_data = defaultdict(lambda: {"sms": 0})
    
    try:
        calls = list(client.calls.list(start_time_after=start_utc, start_time_before=end_utc, limit=1000))
        messages = list(client.messages.list(date_sent_after=start_utc, date_sent_before=end_utc, limit=5000))
    except Exception as e:
        st.error(f"Error fetching from Twilio: {e}")
        st.stop()

    st.write(f"Calls fetched: {len(calls)} — Messages fetched: {len(messages)}")

    # ========== DEBUG SAMPLES ==========
    if show_raw:
        st.subheader("Sample SMS (first 10)")
        for m in messages[:10]:
            st.json({
                "sid": getattr(m, "sid", None),
                "from": getattr(m, "from_", None),
                "to": getattr(m, "to", None),
                "direction": getattr(m, "direction", None),
                "status": getattr(m, "status", None),
                "date_sent": getattr(m, "date_sent", None),
            })
        st.subheader("Sample Calls (first 10)")
        for c in calls[:10]:
            st.json({
                "sid": getattr(c, "sid", None),
                "from": getattr(c, "from_", None),
                "to": getattr(c, "to", None),
                "direction": getattr(c, "direction", None),
                "status": getattr(c, "status", None),
                "start_time": getattr(c, "start_time", None),
                "duration": getattr(c, "duration", None),
            })

    # ========== SMS SECTION (TOP) ==========
    st.header("✉️ SMS (grouped by our Twilio number)")
    # keep your original SMS grouping: attribute to OUR number (outbound->from_, inbound->to)
    def our_number_from_message(m):
        d = (getattr(m, "direction", "") or "").lower()
        if d.startswith("outbound"):
            return getattr(m, "from_", None)
        elif d.startswith("inbound"):
            return getattr(m, "to", None)
        return getattr(m, "from_", None) or getattr(m, "to", None)

    for m in messages:
        raw_our = our_number_from_message(m)
        key = normalize_number(raw_our) or (str(raw_our) if raw_our else None)
        if not key:
            continue
        sms_data[key]["sms"] += 1

    sms_rows = []
    for key, stats in sms_data.items():
        sms_rows.append({
            "Name": name_for(key),
            "Our Number": key,
            "SMS": stats["sms"],
        })

    if sms_rows:
        sms_rows = sorted(sms_rows, key=lambda r: r["SMS"], reverse=True)
        st.dataframe(sms_rows, hide_index=True, use_container_width=True)
    else:
        st.info("No SMS found in this time window.")

    st.markdown("---")

    # ========== CALLS SECTION (BOTTOM) ==========
    st.subheader("📞 Outbound Call Report")
    
    outbound_calls_data = defaultdict(lambda: {"calls": 0, "duration": 0})
    
    # Loop through all fetched calls
    for c in calls:
        # Only process completed calls
        if getattr(c, "status", "").lower() != "completed":
            continue

        direction = getattr(c, "direction", "")
        
        # We ONLY care about outbound calls for this report
        if 'outbound' in direction or 'originating' in direction:
            agent_number = getattr(c, "from_", None)
            
            key = normalize_number(agent_number)
            if not key:
                continue # Skip if the agent number is not valid

            # Add the call and its duration to our data
            outbound_calls_data[key]["calls"] += 1
            try:
                d = int(getattr(c, "duration", 0) or 0)
            except (ValueError, TypeError):
                d = 0
            outbound_calls_data[key]["duration"] += d

    # Build and display the report table
    report_rows = []
    for number, stats in outbound_calls_data.items():
        report_rows.append({
            "Agent Number": number,
            "Name": name_for(number), # Using the name_for helper function
            "Total Calls": stats["calls"],
            "Total Minutes": round(stats["duration"] / 60, 1),
        })

    if report_rows:
        # Sort by the number of calls (most first)
        report_rows = sorted(report_rows, key=lambda r: r["Total Calls"], reverse=True)
        st.dataframe(report_rows, hide_index=True, use_container_width=True)
    else:
        st.info("No completed outbound calls were found in this time window.")
