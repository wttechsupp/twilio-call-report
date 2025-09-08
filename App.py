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
# NAME MAP (edit/add your Twilio numbers here)
# Put numbers in any format; they'll be normalized automatically.
# -----------------------
NAME_MAP = {
    "+13613332093": "Warren Kadd",
    "+12109341811": "Swapnil B",
    "+14693789446": "Roshan Y",
}

# -----------------------
# Helpers
# -----------------------
def normalize_number(val):
    """Extract a phone number in E.164-ish form from val.
    Returns None if nothing recognizable is found."""
    if not val:
        return None
    s = str(val)
    # look for + and digits or long digit sequence (5-15 digits)
    m = re.search(r'(\+?\d{5,15})', s)
    if m:
        num = m.group(1)
        return num if num.startswith("+") else "+" + num
    # fallback: strip whitespace
    s2 = re.sub(r'\s+', '', s)
    return s2 if s2 else None

# Normalize NAME_MAP keys once
NORMALIZED_NAME_MAP = {normalize_number(k): v for k, v in NAME_MAP.items() if normalize_number(k)}

# Decide which side of an interaction to use as "our number"
def our_number_from_call(c):
    """Return our Twilio number for a call record based on direction."""
    direction = (getattr(c, "direction", "") or "").lower()
    if direction.startswith("outbound"):
        return getattr(c, "from_", None)
    elif direction.startswith("inbound"):
        return getattr(c, "to", None)
    # fallback: prefer from_, else to
    return getattr(c, "from_", None) or getattr(c, "to", None)

def our_number_from_message(m):
    """Return our Twilio number for an SMS record based on direction/status."""
    direction = (getattr(m, "direction", "") or "").lower()
    if direction.startswith("outbound"):
        return getattr(m, "from_", None)
    elif direction.startswith("inbound"):
        return getattr(m, "to", None)
    # fallback: prefer from_, else to
    return getattr(m, "from_", None) or getattr(m, "to", None)

# -----------------------
# TIME RANGE (IST 5PM–5AM)
# - Default window = yesterday 17:00 IST → today 05:00 IST.
# - If now < 05:00 IST, end at now to avoid looking into the future.
# -----------------------
IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)

start_ist = (now_ist.replace(hour=17, minute=0, second=0, microsecond=0) - timedelta(days=1))
end_ist = start_ist + timedelta(hours=12)

if now_ist < end_ist:
    end_ist = now_ist

# Convert to UTC for Twilio filters
start_utc = start_ist.astimezone(timezone.utc)
end_utc = end_ist.astimezone(timezone.utc)

# -----------------------
# STREAMLIT UI
# -----------------------
st.title("📊 Twilio Daily Report")

# login flow (with immediate rerun)
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
    report_data = defaultdict(lambda: {"calls": 0, "sms": 0, "duration": 0})

    # Fetch Twilio calls/messages into lists (so we can inspect len and samples)
    try:
        # Use a larger limit to avoid truncation on busy days
        calls = list(client.calls.list(start_time_after=start_utc, start_time_before=end_utc, limit=1000))
        # Alternative if your library version prefers _gte/_lt:
        # calls = list(client.calls.list(start_time_gte=start_utc, start_time_lt=end_utc, limit=1000))

        messages = list(client.messages.list(date_sent_after=start_utc, date_sent_before=end_utc, limit=5000))
    except Exception as e:
        st.error(f"Error fetching from Twilio: {e}")
        st.stop()

    st.write(f"Calls fetched: {len(calls)} — Messages fetched: {len(messages)}")

    # Optionally show a few raw samples to verify shapes/fields
    if show_raw:
        st.subheader("Sample calls (first 10)")
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
        st.subheader("Sample messages (first 10)")
        for m in messages[:10]:
            st.json({
                "sid": getattr(m, "sid", None),
                "from": getattr(m, "from_", None),
                "to": getattr(m, "to", None),
                "direction": getattr(m, "direction", None),
                "status": getattr(m, "status", None),
                "date_sent": getattr(m, "date_sent", None),
            })

    # -----------------------
    # Process calls — count only completed calls, attribute to our Twilio number
    # -----------------------
    # for c in calls:
    #     status = (getattr(c, "status", "") or "").lower()
    #     if status != "completed":
    #         continue

    #     raw_our_number = our_number_from_call(c)
    #     num = normalize_number(raw_our_number)
    #     if not num:
    #         continue

    #     report_data[num]["calls"] += 1

    #     # accumulate duration (seconds)
    #     try:
    #         d = int(getattr(c, "duration", 0) or 0)
    #     except Exception:
    #         d = 0
    #     report_data[num]["duration"] += d
    for c in calls:
    if (getattr(c, "status", "") or "").lower() != "completed":
        continue

    raw_from = getattr(c, "from_", None)
    num = normalize_number(raw_from)
    if not num:
        continue

    report_data[num]["calls"] += 1
    try:
        d = int(getattr(c, "duration", 0) or 0)
    except Exception:
        d = 0
    report_data[num]["duration"] += d

    # -----------------------
    # Process messages — attribute to our Twilio number (outbound -> from_, inbound -> to)
    # -----------------------
    for m in messages:
        raw_our_number = our_number_from_message(m)
        num = normalize_number(raw_our_number)
        if not num:
            continue
        report_data[num]["sms"] += 1

    # -----------------------
    # Build rows for display, normalize name mapping
    # -----------------------
    rows = []
    for num, stats in report_data.items():
        name = NORMALIZED_NAME_MAP.get(num, "Unknown")
        total = stats["calls"] + stats["sms"]
        rows.append({
            "Name": name,
            "Number": num,
            "Calls": stats["calls"],
            "Call Minutes": round(stats.get("duration", 0) / 60, 1),
            "SMS": stats["sms"],
            "Total": total,
        })

    if not rows:
        st.info("No calls or SMS found in this time window.")
    else:
        # Sort by Total (desc)
        rows = sorted(rows, key=lambda r: r["Total"], reverse=True)
        st.subheader(f"📊 Daily Twilio Report ({end_ist.strftime('%d-%b-%Y')})")
        st.dataframe(rows, hide_index=True)
        st.caption("Note: Grouping is by your Twilio number (‘Number’ column). Edit NAME_MAP to label each line.")

