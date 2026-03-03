import streamlit as st
import requests
import time
import pandas as pd
import os
from dotenv import load_dotenv
import sqlite3
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- DATABASE SETUP ---
DB_NAME = "riot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS players
                 (riot_id TEXT PRIMARY KEY, 
                  solo_rank TEXT, solo_lp INTEGER, 
                  flex_rank TEXT, flex_lp INTEGER, 
                  last_updated DATETIME)''')
    conn.commit()
    conn.close()

init_db()

def get_cached_player(riot_id):
    # Use a fresh connection for thread safety
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT solo_rank, solo_lp, flex_rank, flex_lp, last_updated FROM players WHERE riot_id=?", (riot_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_player(riot_id, s_rank, s_lp, f_rank, f_lp):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''INSERT OR REPLACE INTO players 
                 (riot_id, solo_rank, solo_lp, flex_rank, flex_lp, last_updated) 
                 VALUES (?, ?, ?, ?, ?, ?)''', 
              (riot_id, s_rank, s_lp, f_rank, f_lp, now))
    conn.commit()
    conn.close()

# Load API Key
load_dotenv()
API_KEY = os.getenv("RIOT_API_KEY") or st.secrets.get("RIOT_API_KEY")

st.set_page_config(page_title="Riot Rank Checker", page_icon="🎮")
st.title("🚀 Parallel Riot Rank Checker")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Settings")
    region_options = {
        "North America": {"id": "na1", "route": "americas"},
        "Europe West": {"id": "euw1", "route": "europe"},
        "Korea": {"id": "kr", "route": "asia"},
        "Europe Nordic/East": {"id": "eun1", "route": "europe"},
        "Brazil": {"id": "br1", "route": "americas"},
    }
    choice = st.selectbox("Select Region", list(region_options.keys()))
    REG = region_options[choice]
    
    # Thread Control: Be careful with higher numbers on Dev Keys!
    max_workers = st.slider("Parallel Threads", 1, 10, 5, help="How many requests to send at once.")

def fetch_single_player(rid):
    """Function to be run in parallel for each Riot ID."""
    # 1. Check SQLite Cache
    cached_data = get_cached_player(rid)
    if cached_data:
        s_rank, s_lp, f_rank, f_lp, last_updated = cached_data
        update_time = datetime.strptime(last_updated, '%Y-%m-%d %H:%M:%S')
        if datetime.now() - update_time < timedelta(hours=24):
            return {"Riot ID": rid, "Solo Rank": s_rank, "Solo LP": s_lp, "Flex Rank": f_rank, "Flex LP": f_lp}

    # 2. Fetch from API
    try:
        name, tag = rid.split('#')
        # Account V1
        acc_url = f"https://{REG['route']}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={API_KEY}"
        acc_res = requests.get(acc_url)
        
        # Handle Rate Limiting (429)
        if acc_res.status_code == 429:
            return {"Riot ID": rid, "Solo Rank": "Rate Limited", "Solo LP": 0, "Flex Rank": "Rate Limited", "Flex LP": 0}
            
        puuid = acc_res.json()['puuid']

        # League V4
        league_url = f"https://{REG['id']}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={API_KEY}"
        league_data = requests.get(league_url).json()

        solo_rank, solo_lp = "Unranked", 0
        flex_rank, flex_lp = "Unranked", 0

        for entry in league_data:
            if entry['queueType'] == 'RANKED_SOLO_5x5':
                solo_rank, solo_lp = f"{entry['tier']} {entry['rank']}", entry['leaguePoints']
            elif entry['queueType'] == 'RANKED_FLEX_SR':
                flex_rank, flex_lp = f"{entry['tier']} {entry['rank']}", entry['leaguePoints']

        # Save to Cache
        save_player(rid, solo_rank, solo_lp, flex_rank, flex_lp)
        
        return {
            "Riot ID": rid, 
            "Solo Rank": solo_rank, "Solo LP": solo_lp,
            "Flex Rank": flex_rank, "Flex LP": flex_lp
        }
    except Exception:
        return {"Riot ID": rid, "Solo Rank": "Not Found", "Solo LP": 0, "Flex Rank": "Not Found", "Flex LP": 0}

# --- MAIN UI ---
input_text = st.text_area("Enter Riot IDs (one per line)", height=200, placeholder="Faker#KR1")

if st.button("Check Ranks (Parallel)"):
    if not API_KEY:
        st.error("Missing API Key.")
    elif input_text:
        ids = list(set([i.strip() for i in input_text.split("\n") if "#" in i])) # set() removes duplicates
        results = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # --- PARALLEL EXECUTION ENGINE ---
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Map the function to our list of IDs
            future_to_rid = {executor.submit(fetch_single_player, rid): rid for rid in ids}
            
            for i, future in enumerate(as_completed(future_to_rid)):
                data = future.result()
                results.append(data)
                
                # Update progress
                progress_bar.progress((i + 1) / len(ids))
                status_text.text(f"Processed {i+1}/{len(ids)}: {data['Riot ID']}")

        status_text.success(f"✅ Finished processing {len(ids)} IDs!")
        
        # Create DataFrame and Display Results
        df = pd.DataFrame(results)
        st.subheader("📋 Detailed Results")
        st.dataframe(df, use_container_width=True)

        # --- 2. SUMMARY CALCULATIONS ---
        st.divider()
        st.header("📊 Rank Distribution Summary")

        # Define the proper order for ranks to sort the charts correctly
        rank_order = [
            "CHALLENGER", "GRANDMASTER", "MASTER", 
            "DIAMOND", "EMERALD", "PLATINUM", "GOLD", 
            "SILVER", "BRONZE", "IRON", "Unranked", "Not Found"
        ]

        # Helper function to extract just the Tier (e.g., "GOLD IV" -> "GOLD")
        def get_tier(rank_str):
            if not rank_str or " " not in rank_str:
                return rank_str # Returns "Unranked" or "Error" as is
            return rank_str.split(' ')[0] # Returns "GOLD" from "GOLD IV"

        df['Solo Tier'] = df['Solo Rank'].apply(get_tier)
        df['Flex Tier'] = df['Flex Rank'].apply(get_tier)

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Solo Queue")
            solo_summary = df['Solo Tier'].value_counts().reindex(rank_order).dropna()
            if not solo_summary.empty:
                st.bar_chart(solo_summary, color="#ff4b4b")
            else:
                st.info("No Solo Queue data found.")

        with col2:
            st.subheader("Flex Queue")
            flex_summary = df['Flex Tier'].value_counts().reindex(rank_order).dropna()
            if not flex_summary.empty:
                st.bar_chart(flex_summary, color="#0072f2")
            else:
                st.info("No Flex Queue data found.")

        # --- 3. DOWNLOAD SECTION ---
        st.divider()
        # Remove the helper columns before downloading
        csv_df = df.drop(columns=['Solo Tier', 'Flex Tier'])
        csv = csv_df.to_csv(index=False).encode('utf-8')
        
        st.download_button(
            label="📥 Download Full Report (CSV)",
            data=csv,
            file_name="riot_rank_report.csv",
            mime="text/csv"
        )
