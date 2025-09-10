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

MIN_MESSAGES_FOR_CAMPAIGN = 10

# -----------------------
# Helpers
# -----------------------
def normalize_number(val):
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
    if not body:
        return None
    parts = body.split(',', 1)
    if len(parts) > 1:
        template = parts[1].strip()
        if len(template) > 30:
            return template
    return None

NORMALIZED_NAME_MAP = {normalize_number(k): v for k, v in NAME_MAP.items() if normalize_number(k)}

def our_number_from_call(c):
    direction = (getattr(c, "direction", "") or "").lower()
    if direction.startswith("outbound"):
        return getattr(c, "from_", None)
    elif direction.startswith("inbound"):
        return getattr(c, "to", None)
    return getattr(c, "from_", None) or getattr(c, "to", None)

def our_number_from_message(m):
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
    # <<< CHANGE >>> Added 'other_sms' list to store non-campaign messages.
    report_data = defaultdict(lambda: {
        "calls": 0,
        "sms": 0,
        "duration": 0,
        "campaigns": defaultdict(int),
        "other_sms": []
    })

    try:
        calls = list(client.calls.list(start_time_after=start_utc, start_time_before=end_utc, limit=1000))
        messages = list(client.messages.list(date_sent_after=start_utc, date_sent_before=end_utc, limit=5000))
    except Exception as e:
        st.error(f"Error fetching from Twilio: {e}")
        st.stop()

    st.write(f"Calls fetched: {len(calls)} — Messages fetched: {len(messages)}")

    # Raw sample display logic remains here...

    # -----------------------
    # Process calls
    # -----------------------
    for c in calls:
        raw_our_number = our_number_from_call(c)
        num = normalize_number(raw_our_number)
        # <<< CHANGE >>> Only process numbers that are in our NAME_MAP
        if not num or num not in NORMALIZED_NAME_MAP:
            continue
        
        status = (getattr(c, "status", "") or "").lower()
        if status == "completed":
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
        # <<< CHANGE >>> Only process numbers that are in our NAME_MAP
        if not num or num not in NORMALIZED_NAME_MAP:
            continue
        
        report_data[num]["sms"] += 1
        
        direction = (getattr(m, "direction", "") or "").lower()
        body = getattr(m, 'body', '')
        is_campaign_sms = False

        if 'outbound' in direction:
            template = extract_template(body)
            if template:
                report_data[num]["campaigns"][template] += 1
                is_campaign_sms = True
        
        # <<< CHANGE >>> If it's not a campaign SMS, add it to the 'other_sms' list.
        if not is_campaign_sms:
            contact = getattr(m, 'to') if 'outbound' in direction else getattr(m, 'from_')
            report_data[num]["other_sms"].append({
                "direction": "outbound" if 'outbound' in direction else "inbound",
                "contact": contact,
                "body": body,
            })

    # -----------------------
    # Build rows for display
    # -----------------------
    rows = []
    # <<< CHANGE >>> The loop now implicitly filters because we only added data for numbers in NAME_MAP
    for num, stats in report_data.items():
        name = NORMALIZED_NAME_MAP.get(num, "Unknown")
        total = stats["calls"] + stats["sms"]
        rows.append({
            "Name": name, "Number": num, "Calls": stats["calls"],
            "Call Minutes": round(stats.get("duration", 0) / 60, 1),
            "SMS": stats["sms"], "Total": total,
        })

    if not rows:
        st.info("No activity found for the specified users in this time window.")
    else:
        rows = sorted(rows, key=lambda r: r["Total"], reverse=True)
        st.subheader(f"📊 Daily Twilio Report ({end_ist.strftime('%d-%b-%Y')})")
        st.dataframe(rows, hide_index=True)
        st.caption("Displaying report only for users defined in NAME_MAP.")

        # --- Display Bulk SMS Campaigns ---
        st.divider()
        st.subheader("📢 Bulk SMS Campaign Details")
        found_any_campaigns = False
        for row in rows:
            num = row["Number"]
            user_campaigns = report_data[num]["campaigns"]
            filtered_campaigns = {k: v for k, v in user_campaigns.items() if v >= MIN_MESSAGES_FOR_CAMPAIGN}
            if filtered_campaigns:
                found_any_campaigns = True
                st.markdown(f"**Campaigns for {row['Name']} ({row['Number']})**")
                sorted_campaigns = sorted(filtered_campaigns.items(), key=lambda i: i[1], reverse=True)
                for template, count in sorted_campaigns:
                    with st.expander(f"**{count} Messages Sent:** `{template[:80].strip()}...`"):
                        st.text_area("Full Template", template, height=150, disabled=True, key=f"camp_{num}_{count}")

        if not found_any_campaigns:
            st.info(f"No bulk campaigns with {MIN_MESSAGES_FOR_CAMPAIGN} or more messages were detected.")
            
        # <<< NEW SECTION >>>
        # --- Display Other SMS (non-campaign) ---
        st.divider()
        st.subheader("📬 Other SMS (Replies & Individual Messages)")
        found_other_sms = False
        for row in rows:
            num = row["Number"]
            other_messages = report_data[num]["other_sms"]
            if other_messages:
                found_other_sms = True
                with st.expander(f"**{row['Name']}** has **{len(other_messages)}** other messages"):
                    for msg in other_messages:
                        if msg['direction'] == 'inbound':
                            st.markdown(f"◀️ **From** `{msg['contact']}`: _{msg['body']}_")
                        else:
                            st.markdown(f"▶️ **To** `{msg['contact']}`: _{msg['body']}_")
        
        if not found_other_sms:
            st.info("No individual or reply SMS were detected in this period.")
