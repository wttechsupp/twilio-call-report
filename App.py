import re
import streamlit as st
from twilio.rest import Client
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# -----------------------
# CONFIG
# -----------------------
st.set_page_config(
    page_title="Twilio Activity Report",
    page_icon="📊",
    layout="wide",
)

IST = timezone(timedelta(hours=5, minutes=30))

try:
    USERNAME = st.secrets["APP_USER"]
    PASSWORD = st.secrets["APP_PASS"]
    TWILIO_SID = st.secrets["TWILIO_SID"]
    TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
except Exception:
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
    "+19156663789": "Swapnil G",
    "+12103611235": "Bilal K",
    "+12108796990": "Prathemesh D",
    "+12819407775": "Moin",
    "+13613224111": "Piyush Yadav",
    "+13464845656": "Jay Gupta",
    "+14698741361": "Anmol Deshpande",
    # TODO: Add Sanket Sir once correct number is confirmed
}

MIN_MESSAGES_FOR_CAMPAIGN = 10

# -----------------------
# Helpers
# -----------------------
def normalize_number(val):
    """Clean a phone value down to +<digits> format."""
    if not val:
        return None
    s = re.sub(r"[^0-9+]", "", str(val).strip())
    m = re.search(r'(\+?\d{5,15})$', s)
    if m:
        num = m.group(1)
        return num if num.startswith("+") else "+" + num
    return None


def extract_template(body):
    """
    Detect bulk campaign messages.
    Format: 'Hi/Hello Name, <template body>'
    Splits on the first comma — if the remainder is >30 chars,
    it's likely a campaign template.
    """
    if not body:
        return None
    parts = body.split(',', 1)
    if len(parts) > 1:
        template = parts[1].strip()
        if len(template) > 30:
            return template
    return None


NORMALIZED_NAME_MAP = {
    normalize_number(k): v
    for k, v in NAME_MAP.items()
    if normalize_number(k)
}


def our_number_from_message(m):
    """Figure out which of OUR numbers was involved in a message."""
    direction = (getattr(m, "direction", "") or "").lower()
    if direction.startswith("outbound"):
        return normalize_number(getattr(m, "from_", None))
    elif direction.startswith("inbound"):
        return normalize_number(getattr(m, "to", None))
    return normalize_number(getattr(m, "from_", None) or getattr(m, "to", None))


def fmt_duration(seconds):
    """Format seconds into 'Xh Ym' or 'Ym' or '0m'."""
    minutes = round(seconds / 60)
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60}m"
    return f"{minutes}m"


# ---------------------------------
# Main Report
# ---------------------------------
def run_report(start_utc, end_utc, show_raw):
    start_ist = start_utc.astimezone(IST)
    end_ist = end_utc.astimezone(IST)

    st.markdown(
        f"**Report Window (IST):** "
        f"{start_ist.strftime('%d-%b-%Y %I:%M %p')} → "
        f"{end_ist.strftime('%d-%b-%Y %I:%M %p')}"
    )

    # --- Fetch data ---
    with st.spinner("Fetching data from Twilio..."):
        report_data = defaultdict(lambda: {
            "inbound_calls": 0, "inbound_duration": 0,
            "outbound_calls": 0, "outbound_duration": 0,
            "outbound_sms": 0, "inbound_sms": 0,
            "campaigns": defaultdict(int),
            "other_sms": [],
        })
        try:
            fetch_limit = 20000 if (end_utc - start_utc).days > 2 else 5000
            calls = list(client.calls.list(
                start_time_after=start_utc, start_time_before=end_utc, limit=fetch_limit
            ))
            messages = list(client.messages.list(
                date_sent_after=start_utc, date_sent_before=end_utc, limit=fetch_limit
            ))
        except Exception as e:
            st.error(f"Error fetching from Twilio: {e}")
            st.stop()

    st.success(f"Fetched **{len(calls)}** calls and **{len(messages)}** messages.")

    # --- Raw data debug ---
    if show_raw:
        with st.expander("Raw Data Samples"):
            st.subheader("Sample Messages (first 10)")
            for m in messages[:10]:
                st.json({
                    "sid": getattr(m, 'sid', None),
                    "from": getattr(m, 'from_', None),
                    "to": getattr(m, 'to', None),
                    "direction": getattr(m, 'direction', None),
                    "status": getattr(m, 'status', None),
                    "body": getattr(m, 'body', None),
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
                    "end_time": str(getattr(c, 'end_time', None)),
                })

    # --- Process Calls ---
    completed_calls = 0
    for c in calls:
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
            st.write(f"DEBUG CALL: from={from_num} to={to_num} dir={direction} dur={duration}s")

        if 'outbound' in direction:
            if from_num in NORMALIZED_NAME_MAP:
                report_data[from_num]["outbound_calls"] += 1
                report_data[from_num]["outbound_duration"] += duration
        elif 'inbound' in direction:
            if to_num in NORMALIZED_NAME_MAP:
                report_data[to_num]["inbound_calls"] += 1
                report_data[to_num]["inbound_duration"] += duration
        else:
            if from_num in NORMALIZED_NAME_MAP:
                report_data[from_num]["outbound_calls"] += 1
                report_data[from_num]["outbound_duration"] += duration
            elif to_num in NORMALIZED_NAME_MAP:
                report_data[to_num]["inbound_calls"] += 1
                report_data[to_num]["inbound_duration"] += duration

    if show_raw:
        st.info(f"DEBUG: Completed calls counted: {completed_calls}")

    # --- Process SMS ---
    for m in messages:
        num = our_number_from_message(m)
        if not num or num not in NORMALIZED_NAME_MAP:
            continue

        direction = (getattr(m, "direction", "") or "").lower()
        if 'outbound' in direction:
            report_data[num]["outbound_sms"] += 1
        else:
            report_data[num]["inbound_sms"] += 1
        body = getattr(m, 'body', '') or ''
        is_campaign = False

        if 'outbound' in direction:
            template = extract_template(body)
            if template:
                report_data[num]["campaigns"][template] += 1
                is_campaign = True

        if not is_campaign:
            contact = getattr(m, 'to', None) if 'outbound' in direction else getattr(m, 'from_', None)
            report_data[num]["other_sms"].append({
                "direction": "outbound" if 'outbound' in direction else "inbound",
                "contact": normalize_number(contact),
                "body": body,
            })

    # --- Build rows ---
    rows = []
    for num, stats in report_data.items():
        total_calls = stats["inbound_calls"] + stats["outbound_calls"]
        rows.append({
            "Name": NORMALIZED_NAME_MAP.get(num, "Unknown"),
            "Number": num,
            "Inbound Calls": stats["inbound_calls"],
            "Inbound Duration": fmt_duration(stats["inbound_duration"]),
            "Outbound Calls": stats["outbound_calls"],
            "Outbound Duration": fmt_duration(stats["outbound_duration"]),
            "Total Calls": total_calls,
            "Outbound SMS": stats["outbound_sms"],
            "Inbound SMS": stats["inbound_sms"],
            "Total SMS": stats["outbound_sms"] + stats["inbound_sms"],
            "Total Activity": total_calls + stats["outbound_sms"] + stats["inbound_sms"],
        })

    if not rows:
        st.info("No activity found for the mapped users in this time window.")
        return

    rows = sorted(rows, key=lambda r: r["Total Activity"], reverse=True)

    # --- Summary Table ---
    st.subheader("📊 Summary Report")
    # st.dataframe(rows, hide_index=True, use_container_width=True)
    import pandas as pd
    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Name": st.column_config.TextColumn("Name", pinned=True),
        },
    )
    st.caption(f"Showing {len(rows)} users with activity out of {len(NORMALIZED_NAME_MAP)} mapped numbers.")

    # --- Campaigns ---
    st.divider()
    st.subheader("📢 Bulk SMS Campaigns")

    found_campaigns = any(
        any(c >= MIN_MESSAGES_FOR_CAMPAIGN for c in report_data[row['Number']]['campaigns'].values())
        for row in rows
    )

    if not found_campaigns:
        st.info(f"No bulk campaigns detected (threshold: {MIN_MESSAGES_FOR_CAMPAIGN}+ messages).")
    else:
        for row in rows:
            user_campaigns = {
                k: v for k, v in report_data[row['Number']]['campaigns'].items()
                if v >= MIN_MESSAGES_FOR_CAMPAIGN
            }
            if user_campaigns:
                st.markdown(f"**{row['Name']}** ({row['Number']})")
                sorted_campaigns = sorted(user_campaigns.items(), key=lambda i: i[1], reverse=True)
                for idx, (template, count) in enumerate(sorted_campaigns):
                    preview = template[:80].strip()
                    with st.expander(f"{count} messages — `{preview}...`"):
                        st.text_area(
                            "Full Template", template, height=150, disabled=True,
                            key=f"camp_{row['Number']}_{idx}",
                        )

    # --- Other SMS ---
    st.divider()
    st.subheader("📬 Other SMS (Replies & Individual)")

    found_other = any(report_data[row['Number']]['other_sms'] for row in rows)
    if not found_other:
        st.info("No individual or reply SMS detected.")
    else:
        for row in rows:
            other_msgs = report_data[row['Number']]['other_sms']
            if other_msgs:
                with st.expander(f"**{row['Name']}** — {len(other_msgs)} messages"):
                    for msg in other_msgs:
                        contact = msg['contact'] or 'Unknown'
                        arrow = "▶️ **To**" if msg['direction'] == 'outbound' else "◀️ **From**"
                        st.markdown(f"{arrow} `{contact}`: _{msg['body']}_")


# -----------------------
# UI
# -----------------------
st.title("📊 Twilio Activity Report")

# --- Auth ---
if not st.session_state.get("logged_in", False):
    with st.container():
        st.subheader("Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login", type="primary"):
            if username == USERNAME and password == PASSWORD:
                st.session_state["logged_in"] = True
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.stop()

# --- Logged in ---
with st.sidebar:
    st.markdown(f"Logged in")
    if st.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state.pop("start_utc", None)
        st.session_state.pop("end_utc", None)
        st.rerun()

now_ist = datetime.now(IST)

st.header("Select a Report Timeframe")
show_raw = st.checkbox("Show raw data samples for debugging")
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("Yesterday's Report", use_container_width=True):
        # Yesterday 5:00 PM IST → Today 5:00 AM IST (12-hour overnight window)
        start_ist = (now_ist - timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
        st.session_state["start_utc"] = start_ist.astimezone(timezone.utc)
        st.session_state["end_utc"] = (start_ist + timedelta(hours=12)).astimezone(timezone.utc)

with col2:
    if st.button("Today's Report (Live)", use_container_width=True):
        # Today 5:00 PM IST → now (or yesterday 5 PM if before 5 PM)
        start_ist = now_ist.replace(hour=17, minute=0, second=0, microsecond=0)
        if now_ist.hour < 17:
            start_ist -= timedelta(days=1)
        st.session_state["start_utc"] = start_ist.astimezone(timezone.utc)
        st.session_state["end_utc"] = now_ist.astimezone(timezone.utc)

with col3:
    if st.button("Last 7 Days", use_container_width=True):
        st.session_state["start_utc"] = (now_ist - timedelta(days=7)).astimezone(timezone.utc)
        st.session_state["end_utc"] = now_ist.astimezone(timezone.utc)

with col4:
    if st.button("Last 30 Days", use_container_width=True):
        st.session_state["start_utc"] = (now_ist - timedelta(days=30)).astimezone(timezone.utc)
        st.session_state["end_utc"] = now_ist.astimezone(timezone.utc)

if st.session_state.get("start_utc") and st.session_state.get("end_utc"):
    run_report(st.session_state["start_utc"], st.session_state["end_utc"], show_raw)
