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
# -----------------------
NAME_MAP = {
    "+13613332093": "Warren Kadd",
    "+12109341811": "Swapnil B",
    "+14693789446": "Roshan Y",
    "+12108796990": "Sanket Sir",
    "+12109343993": "Swapnil G",
    "+12103611235": "Bilal K",
}

MIN_MESSAGES_FOR_CAMPAIGN = 10

# -----------------------
# Helpers
# -----------------------
def normalize_number(val):
    if not val:
        return None
    s = str(val).strip()
    # Keep only + and digits
    s = re.sub(r"[^0-9+]", "", s)
    # Extract last 15 digits optionally with +
    m = re.search(r'(\+?\d{5,15})$', s)
    if m:
        num = m.group(1)
        return num if num.startswith("+") else "+" + num
    return None

def extract_template(body):
    if not body:
        return None
    parts = body.split(',', 1)
    if len(parts) > 1:
        template = parts[1].strip()
        if len(template) > 30:
            return template
    return None

NORMALIZED_NAME_MAP = {normalize_number(k): v for k, v in NAME_MAP.items() if normalize_number(k)}

def our_number_from_message(m):
    direction = (getattr(m, "direction", "") or "").lower()
    if direction.startswith("outbound"):
        return normalize_number(getattr(m, "from_", None))
    elif direction.startswith("inbound"):
        return normalize_number(getattr(m, "to", None))
    # Fallback
    return normalize_number(getattr(m, "from_", None) or getattr(m, "to", None))

# ---------------------------------
# Main Report Function
# ---------------------------------
def run_report(start_utc, end_utc, show_raw):
    """
    Fetches Twilio data and displays a report with separate inbound/outbound stats.
    """
    start_ist_display = start_utc.astimezone(IST)
    end_ist_display = end_utc.astimezone(IST)

    st.markdown(f"**Report Window (IST):** {start_ist_display.strftime('%d-%b-%Y %I:%M %p')} → {end_ist_display.strftime('%d-%b-%Y %I:%M %p')}")

    with st.spinner('Fetching data from Twilio...'):
        report_data = defaultdict(lambda: {
            "inbound_calls": 0, "inbound_duration": 0,
            "outbound_calls": 0, "outbound_duration": 0,
            "sms": 0,
            "campaigns": defaultdict(int), "other_sms": []
        })
        try:
            fetch_limit = 20000 if (end_utc - start_utc).days > 2 else 5000
            calls = list(client.calls.list(start_time_after=start_utc, start_time_before=end_utc, limit=fetch_limit))
            messages = list(client.messages.list(date_sent_after=start_utc, date_sent_before=end_utc, limit=fetch_limit))
        except Exception as e:
            st.error(f"Error fetching from Twilio: {e}")
            st.stop()

    st.success(f"Fetched {len(calls)} calls and {len(messages)} messages.")

    if show_raw:
        with st.expander("Show Raw Data Samples"):
            st.subheader("Sample Messages (first 10)")
            for m in messages[:10]:
                st.json({
                    "sid": getattr(m, 'sid', None),
                    "from": getattr(m, 'from_', None),
                    "to": getattr(m, 'to', None),
                    "direction": getattr(m, 'direction', None),
                    "status": getattr(m, 'status', None),
                    "body": getattr(m, 'body', None)
                })
            st.subheader("Sample Calls (first 10)")
            for c in calls[:10]:
                st.json({
                    "sid": getattr(c, 'sid', None),
                    "from": getattr(c, 'from_', None),
                    "to": getattr(c, 'to', None),
                    "direction": getattr(c, 'direction', None),
                    "status": getattr(c, 'status', None),
                    "duration": getattr(c, 'duration', None),
                    "parent_call_sid": getattr(c, 'parent_call_sid', None),
                    "start_time": str(getattr(c, 'start_time', None)),
                    "end_time": str(getattr(c, 'end_time', None))
                })

    # --- FIXED CALL PROCESSING: Use Twilio's direction field ---
    completed_calls = 0
    for c in calls:
        # Skip child calls (e.g., conference legs)
        if getattr(c, 'parent_call_sid', None) is not None:
            continue

        status = (getattr(c, "status", "") or "").lower()
        if status != "completed":
            continue

        completed_calls += 1
        duration = int(getattr(c, "duration", 0) or 0)
        from_num = normalize_number(getattr(c, 'from_', None))
        to_num = normalize_number(getattr(c, 'to', None))
        direction = (getattr(c, "direction", "") or "").lower()

        if show_raw:
            st.write(f"DEBUG CALL: from={from_num} to={to_num} dir={direction} dur={duration} status={status}")

        if 'outbound' in direction:
            # For outbound calls, our number must be the 'from'
            if from_num in NORMALIZED_NAME_MAP:
                report_data[from_num]["outbound_calls"] += 1
                report_data[from_num]["outbound_duration"] += duration
        elif 'inbound' in direction:
            # For inbound calls, our number must be the 'to'
            if to_num in NORMALIZED_NAME_MAP:
                report_data[to_num]["inbound_calls"] += 1
                report_data[to_num]["inbound_duration"] += duration
        else:
            # Fallback if direction is missing/unknown
            if from_num in NORMALIZED_NAME_MAP:
                report_data[from_num]["outbound_calls"] += 1
                report_data[from_num]["outbound_duration"] += duration
            elif to_num in NORMALIZED_NAME_MAP:
                report_data[to_num]["inbound_calls"] += 1
                report_data[to_num]["inbound_duration"] += duration

    if show_raw:
        st.info(f"DEBUG: Completed calls counted: {completed_calls}")

    # --- SMS PROCESSING (kept as-is with slight hardening) ---
    for m in messages:
        num = our_number_from_message(m)
        if not num or num not in NORMALIZED_NAME_MAP:
            continue

        report_data[num]["sms"] += 1
        direction = (getattr(m, "direction", "") or "").lower()
        body = getattr(m, 'body', '') or ''
        is_campaign = False

        if 'outbound' in direction and (template := extract_template(body)):
            report_data[num]["campaigns"][template] += 1
            is_campaign = True

        if not is_campaign:
            contact = getattr(m, 'to', None) if 'outbound' in direction else getattr(m, 'from_', None)
            contact = normalize_number(contact)
            report_data[num]["other_sms"].append({
                "direction": "outbound" if 'outbound' in direction else "inbound",
                "contact": contact,
                "body": body
            })

    # Build and display report
    rows = []
    for num, stats in report_data.items():
        rows.append({
            "Name": NORMALIZED_NAME_MAP.get(num, "Unknown"),
            "Number": num,
            "Inbound Calls": stats["inbound_calls"],
            "Inbound Mins": round(stats["inbound_duration"] / 60, 1),
            "Outbound Calls": stats["outbound_calls"],
            "Outbound Mins": round(stats["outbound_duration"] / 60, 1),
            "SMS": stats["sms"],
            "Total Activity": stats["inbound_calls"] + stats["outbound_calls"] + stats["sms"],
        })
    if not rows:
        st.info("No activity found for the specified users in this time window.")
        return

    rows = sorted(rows, key=lambda r: r["Total Activity"], reverse=True)
    st.subheader("📊 Summary Report")
    st.dataframe(rows, hide_index=True)
    st.caption("Displaying report only for users defined in NAME_MAP.")

    st.divider()
    st.subheader("📢 Bulk SMS Campaign Details")
    found_campaigns = any(
        report_data[row['Number']]['campaigns']
        for row in rows
        if any(c >= MIN_MESSAGES_FOR_CAMPAIGN for c in report_data[row['Number']]['campaigns'].values())
    )
    if not found_campaigns:
        st.info(f"No bulk campaigns with {MIN_MESSAGES_FOR_CAMPAIGN} or more messages were detected.")
    else:
        for row in rows:
            user_campaigns = {k: v for k, v in report_data[row['Number']]['campaigns'].items() if v >= MIN_MESSAGES_FOR_CAMPAIGN}
            if user_campaigns:
                st.markdown(f"**Campaigns for {row['Name']} ({row['Number']})**")
                sorted_campaigns = sorted(user_campaigns.items(), key=lambda i: i[1], reverse=True)
                for idx, (template, count) in enumerate(sorted_campaigns):
                    with st.expander(f"**{count} Msgs:** `{template[:80].strip()}...`"):
                        st.text_area("Full Template", template, height=150, disabled=True, key=f"camp_{row['Number']}_{idx}")

    st.divider()
    st.subheader("📬 Other SMS (Replies & Individual Messages)")
    found_other = any(report_data[row['Number']]['other_sms'] for row in rows)
    if not found_other:
        st.info("No individual or reply SMS were detected.")
    else:
        for row in rows:
            other_msgs = report_data[row['Number']]['other_sms']
            if other_msgs:
                with st.expander(f"**{row['Name']}** has **{len(other_msgs)}** other messages"):
                    for msg in other_msgs:
                        contact = msg['contact'] or 'Unknown'
                        st.markdown(f"{'▶️ **To**' if msg['direction'] == 'outbound' else '◀️ **From**'} `{contact}`: _{msg['body']}_")

# -----------------------
# STREAMLIT UI
# -----------------------
st.title("📊 Twilio Activity Report")

if not st.session_state.get("logged_in", False):
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

if "start_utc" not in st.session_state:
    st.session_state.start_utc = None
if "end_utc" not in st.session_state:
    st.session_state.end_utc = None

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)

st.header("Select a Report Timeframe")
show_raw = st.checkbox("Show raw data samples for debugging")
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

if col1.button("Yesterday's Report", use_container_width=True):
    start_ist = (now_ist.replace(hour=17, minute=0, second=0, microsecond=0) - timedelta(days=1))
    st.session_state.start_utc = start_ist.astimezone(timezone.utc)
    st.session_state.end_utc = (start_ist + timedelta(hours=12)).astimezone(timezone.utc)

if col2.button("Today's Report (Live)", use_container_width=True):
    start_ist = now_ist.replace(hour=17, minute=0, second=0, microsecond=0)
    if now_ist.hour < 17:
        start_ist -= timedelta(days=1)
    st.session_state.start_utc = start_ist.astimezone(timezone.utc)
    st.session_state.end_utc = now_ist.astimezone(timezone.utc)

if col3.button("Last 7 Days", use_container_width=True):
    st.session_state.end_utc = now_ist.astimezone(timezone.utc)
    st.session_state.start_utc = (now_ist - timedelta(days=7)).astimezone(timezone.utc)

if col4.button("Last 30 Days", use_container_width=True):
    st.session_state.end_utc = now_ist.astimezone(timezone.utc)
    st.session_state.start_utc = (now_ist - timedelta(days=30)).astimezone(timezone.utc)

if st.session_state.start_utc and st.session_state.end_utc:
    run_report(st.session_state.start_utc, st.session_state.end_utc, show_raw)
