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
# -----------------------
NAME_MAP = {
    "+13613332093": "Warren Kadd",
    "+12109341811": "Swapnil B",
    "+14693789446": "Roshan Y",
}

# Define the minimum number of identical messages to be considered a "campaign"
MIN_MESSAGES_FOR_CAMPAIGN = 10

# -----------------------
# Helpers
# -----------------------
def normalize_number(val):
    """Extract a phone number in E.164-ish form from val."""
    if not val:
        return None
    s = str(val)
    m = re.search(r'(\+?\d{5,15})', s)
    if m:
        num = m.group(1)
        return num if num.startswith("+") else "+" + num
    s2 = re.sub(r'\s+', '', s)
    return s2 if s2 else None

def extract_template(body):
    """
    Identifies a message template for bulk SMS.
    Returns the template string if found, otherwise None.
    Example: "Hi John, We have a position..." -> "We have a position..."
    """
    if not body:
        return None
    
    parts = body.split(',', 1)
    
    if len(parts) > 1:
        template = parts[1].strip()
        if len(template) > 30:
            return template
            
    return None

# Normalize NAME_MAP keys once
NORMALIZED_NAME_MAP = {normalize_number(k): v for k, v in NAME_MAP.items() if normalize_number(k)}

def our_number_from_call(c):
    """Return our Twilio number for a call record based on direction."""
    direction = (getattr(c, "direction", "") or "").lower()
    if direction.startswith("outbound"):
        return getattr(c, "from_", None)
    elif direction.startswith("inbound"):
        return getattr(c, "to", None)
    return getattr(c, "from_", None) or getattr(c, "to", None)

def our_number_from_message(m):
    """Return our Twilio number for an SMS record based on direction/status."""
    direction = (getattr(m, "direction", "") or "").lower()
    if direction.startswith("outbound"):
        return getattr(m, "from_", None)
    elif direction.startswith("inbound"):
        return getattr(m, "to", None)
    return getattr(m, "from_", None) or getattr(m, "to", None)

# -----------------------
# TIME RANGE (IST 5PM–5AM)
# -----------------------
IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)

start_ist = (now_ist.replace(hour=17, minute=0, second=0, microsecond=0) - timedelta(days=1))
end_ist = start_ist + timedelta(hours=12)

if now_ist < end_ist:
    end_ist = now_ist

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
            st.rerun()
        else:
            st.error("❌ Invalid credentials")
    st.stop()

st.markdown(f"**Window (IST):** {start_ist.strftime('%d-%b-%Y %I:%M %p')} → {end_ist.strftime('%d-%b-%Y %I:%M %p')}")
st.markdown(f"**Window (UTC):** {start_utc.isoformat()} → {end_utc.isoformat()}")

show_raw = st.checkbox("Show raw samples (calls/messages) — use for debugging", value=False)

if st.button("Get Report"):
    report_data = defaultdict(lambda: {
        "calls": 0, 
        "sms": 0, 
        "duration": 0, 
        "campaigns": defaultdict(int)
    })

    try:
        calls = list(client.calls.list(start_time_after=start_utc, start_time_before=end_utc, limit=1000))
        messages = list(client.messages.list(date_sent_after=start_utc, date_sent_before=end_utc, limit=5000))
    except Exception as e:
        st.error(f"Error fetching from Twilio: {e}")
        st.stop()

    st.write(f"Calls fetched: {len(calls)} — Messages fetched: {len(messages)}")

    # ========== DEBUG SAMPLES (RESTORED) ==========
    if show_raw:
        st.subheader("Sample Messages (first 10)")
        for m in messages[:10]:
            st.json({
                "sid": getattr(m, "sid", None),
                "from": getattr(m, "from_", None),
                "to": getattr(m, "to", None),
                "direction": getattr(m, "direction", None),
                "status": getattr(m, "status", None),
                "date_sent": getattr(m, "date_sent", None),
                "body": getattr(m, "body", None) # Added body for easier debugging
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
    # ===============================================

    # -----------------------
    # Process calls
    # -----------------------
    for c in calls:
        status = (getattr(c, "status", "") or "").lower()
        if status != "completed":
            continue

        raw_our_number = our_number_from_call(c)
        num = normalize_number(raw_our_number)
        if not num:
            continue

        report_data[num]["calls"] += 1
        try:
            d = int(getattr(c, "duration", 0) or 0)
        except Exception:
            d = 0
        report_data[num]["duration"] += d

    # -----------------------
    # Process messages
    # -----------------------
    for m in messages:
        raw_our_number = our_number_from_message(m)
        num = normalize_number(raw_our_number)
        if not num:
            continue
        
        report_data[num]["sms"] += 1
        
        direction = (getattr(m, "direction", "") or "").lower()
        if 'outbound' in direction:
            body = getattr(m, 'body', None)
            template = extract_template(body)
            if template:
                report_data[num]["campaigns"][template] += 1

    # -----------------------
    # Build rows for display
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
        rows = sorted(rows, key=lambda r: r["Total"], reverse=True)
        st.subheader(f"📊 Daily Twilio Report ({end_ist.strftime('%d-%b-%Y')})")
        st.dataframe(rows, hide_index=True)
        st.caption("Note: Grouping is by your Twilio number (‘Number’ column). Edit NAME_MAP to label each line.")

        # Display the detected bulk SMS campaigns
        st.divider()
        st.subheader("📊 Bulk SMS Campaign Details")

        found_any_campaigns = False
        for row in rows:
            num = row["Number"]
            user_campaigns = report_data[num]["campaigns"]
            
            filtered_campaigns = {
                template: count 
                for template, count in user_campaigns.items() 
                if count >= MIN_MESSAGES_FOR_CAMPAIGN
            }

            if filtered_campaigns:
                found_any_campaigns = True
                st.markdown(f"**Campaigns for {row['Name']} ({row['Number']})**")
                
                sorted_campaigns = sorted(filtered_campaigns.items(), key=lambda item: item[1], reverse=True)

                for template, count in sorted_campaigns:
                    with st.expander(f"**{count} Messages Sent:** `{template[:80].strip()}...`"):
                        st.text_area("Full Template", template, height=150, disabled=True)

        if not found_any_campaigns:
            st.info(f"No bulk SMS campaigns with {MIN_MESSAGES_FOR_CAMPAIGN} or more messages were detected.")
