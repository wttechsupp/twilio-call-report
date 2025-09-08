import re
import streamlit as st
from twilio.rest import Client
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter

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
# NAME MAP (edit/add numbers here)
# You can also map Twilio Client IDs like "client:agent1"
# -----------------------
NAME_MAP = {
    "+13613332093": "Warren Kadd",
    "+12109341811": "Swapnil B",
    "+14693789446": "Roshan Y",
    # "client:agent1": "Agent 1",
}

# -----------------------
# Helpers
# -----------------------
def normalize_number(val):
    """Extract something that looks like a phone number in E.164-ish form.
    Returns None if no digit sequence found (e.g., 'client:alice')."""
    if not val:
        return None
    s = str(val)
    m = re.search(r'(\+?\d{5,15})', s)
    if m:
        num = m.group(1)
        return num if num.startswith("+") else "+" + num
    return None

# Build a flexible lookup map:
# - exact key (as provided)
# - normalized E.164 key (if possible)
NORMALIZED_NAME_MAP = {}
for k, v in NAME_MAP.items():
    NORMALIZED_NAME_MAP[str(k)] = v
    nk = normalize_number(k)
    if nk:
        NORMALIZED_NAME_MAP[nk] = v

def name_for(key):
    """Resolve a display name for a key which may be E.164 or raw (e.g., 'client:xyz')."""
    return NORMALIZED_NAME_MAP.get(key, "Unknown")

def our_number_from_message(m):
    """Return our Twilio number for an SMS record based on direction/status."""
    direction = (getattr(m, "direction", "") or "").lower()
    if direction.startswith("outbound"):
        return getattr(m, "from_", None)
    elif direction.startswith("inbound"):
        return getattr(m, "to", None)
    return getattr(m, "from_", None) or getattr(m, "to", None)

# -----------------------
# TIME RANGE (IST 5PM–5AM) — dynamic end
# -----------------------
IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)

start_ist = (now_ist.replace(hour=17, minute=0, second=0, microsecond=0) - timedelta(days=1))
end_ist = start_ist + timedelta(hours=12)

if now_ist < end_ist:
    end_ist = now_ist

# Convert to UTC for Twilio
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

    # Fetch Twilio calls/messages
    try:
        calls = list(client.calls.list(start_time_after=start_utc, start_time_before=end_utc, limit=1000))
        messages = list(client.messages.list(date_sent_after=start_utc, date_sent_before=end_utc, limit=5000))
    except Exception as e:
        st.error(f"Error fetching from Twilio: {e}")
        st.stop()

    st.write(f"Calls fetched: {len(calls)} — Messages fetched: {len(messages)}")

    # Optional raw samples
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
    # Calls: Status == Completed, group by From, collect Duration
    # -----------------------
    status_counter = Counter()
    for c in calls:
        status_val = (getattr(c, "status", "") or "").lower()
        status_counter[status_val] += 1
        if status_val != "completed":
            continue

        raw_from = getattr(c, "from_", None)
        # Prefer normalized E.164; if not a phone number (e.g., 'client:xyz'), fall back to raw
        num_key = normalize_number(raw_from) or (str(raw_from) if raw_from else None)
        if not num_key:
            continue

        report_data[num_key]["calls"] += 1
        try:
            d = int(getattr(c, "duration", 0) or 0)
        except Exception:
            d = 0
        report_data[num_key]["duration"] += d

    # Quick status histogram to help diagnose filters
    with st.expander("Call status breakdown (debug)"):
        st.write(dict(status_counter))

    # -----------------------
    # SMS: keep existing logic (attribute to our Twilio number)
    # -----------------------
    for m in messages:
        raw_our_number = our_number_from_message(m)
        num = normalize_number(raw_our_number) or (str(raw_our_number) if raw_our_number else None)
        if not num:
            continue
        report_data[num]["sms"] += 1

    # -----------------------
    # Build rows
    # -----------------------
    rows = []
    for key, stats in report_data.items():
        name = name_for(key)
        total = stats["calls"] + stats["sms"]
        rows.append({
            "Name": name,
            "Number / ID": key,
            "Calls (Completed)": stats["calls"],
            "Call Minutes": round(stats.get("duration", 0) / 60, 1),
            "SMS": stats["sms"],
            "Total": total,
        })

    if not rows:
        st.info("No calls or SMS found in this time window. Enable 'Show raw samples' or check the status breakdown above to validate filters.")
    else:
        rows = sorted(rows, key=lambda r: r["Total"], reverse=True)
        st.subheader(f"📊 Daily Twilio Report ({end_ist.strftime('%d-%b-%Y')})")
        st.dataframe(rows, hide_index=True)
        st.caption("Calls grouped by **From** (caller). Non-phone IDs (e.g., client:something) are preserved.")
