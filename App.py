import pandas as pd
import streamlit as st
from twilio.rest import Client
import io

st.set_page_config(page_title="📞 Twilio Call Report", layout="wide")

st.title("📞 Twilio Call Report Generator")

# --- OPTION A: Upload CSV ---
st.subheader("Upload Twilio Call Log CSV")
uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

# --- OPTION B: Fetch from Twilio API ---
st.subheader("Or Fetch Directly from Twilio API")
sid = st.text_input("Twilio Account SID", type="password")
token = st.text_input("Twilio Auth Token", type="password")
fetch_button = st.button("Fetch from Twilio API")

df = None

# Load CSV
if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)

# Fetch from API
elif fetch_button and sid and token:
    client = Client(sid, token)
    calls = client.calls.list(limit=500)  # fetch last 500 calls
    data = []
    for call in calls:
        data.append({
            "From": call.from_,
            "To": call.to,
            "Status": call.status,
            "Duration": int(call.duration or 0),
            "Price": float(call.price or 0)
        })
    df = pd.DataFrame(data)

# Process Data
if df is not None and not df.empty:
    st.success("✅ Data loaded successfully!")

    # Remove Failed for duration & price
    df_filtered = df[df["Status"] != "failed"]

    report = (
        df_filtered.groupby("From")
        .agg(
            call_count=("From", "count"),
            total_duration_sec=("Duration", "sum"),
            total_price=("Price", "sum"),
        )
        .reset_index()
    )

    report["total_duration_hours"] = (report["total_duration_sec"] / 3600).round(2)

    statuses = (
        df.groupby("From")["Status"]
        .unique()
        .apply(lambda x: ", ".join(x))
        .reset_index()
        .rename(columns={"Status": "statuses"})
    )

    report = report.merge(statuses, on="From", how="left")

    report = report[["From", "call_count", "total_duration_hours", "total_price", "statuses"]]

    # Name mapping
    name_map = {
        "+13613332093": "Warren Kadd",
        "+12109341811": "Sam Bailey"
    }
    report.insert(0, "Name", report["From"].map(name_map).fillna(""))

    report = report.sort_values(by="call_count", ascending=False).reset_index(drop=True)

    st.subheader("📊 Report")
    st.dataframe(report)

    # Download CSV
    csv = report.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download Report (CSV)", csv, "twilio_report.csv", "text/csv")
