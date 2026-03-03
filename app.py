import streamlit as st
import requests
import time
import pandas as pd
import os
from dotenv import load_dotenv
import sqlite3
from datetime import datetime, timedelta

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
# Load .env file automatically
load_dotenv()
API_KEY = os.getenv("RIOT_API_KEY")
if API_KEY:
    st.success("API Key loaded from .env")
else:
    try:
        API_KEY = st.secrets["RIOT_API_KEY"]
        st.success("API Key loaded from Streamlit secrets")
    except Exception as e:
        API_KEY = None
        st.error(f"RIOT_API_KEY not found in .env or Streamlit secrets: {e}")
st.set_page_config(page_title="Riot Rank Checker", page_icon="🎮")
st.title("🏆 Riot ID Bulk Rank Checker")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Settings")
    # Regional routing mapping
    region_options = {
        "North America": {"id": "na1", "route": "americas"},
        "Europe West": {"id": "euw1", "route": "europe"},
        "Korea": {"id": "kr", "route": "asia"},
        "Europe Nordic/East": {"id": "eun1", "route": "europe"},
        "Brazil": {"id": "br1", "route": "americas"},
    }
    choice = st.selectbox("Select Region", list(region_options.keys()))
    REG = region_options[choice]
    
    # Cache management
    if st.button("🔄 Clear Cached Ranks"):
        st.cache_data.clear()
        st.toast("Cache cleared!")

def get_player_rank(riot_id):
    # 1. Check SQLite first
    cached_data = get_cached_player(riot_id)
    if cached_data:
        s_rank, s_lp, f_rank, f_lp, last_updated = cached_data
        update_time = datetime.strptime(last_updated, '%Y-%m-%d %H:%M:%S')
        
        # If data is less than 24 hours old, return it immediately
        if datetime.now() - update_time < timedelta(hours=24):
            return s_rank, s_lp, f_rank, f_lp, True # True means it was a cache hit

    # 2. If not in DB or data is stale, call Riot API
    try:
        name, tag = riot_id.split('#')
        acc_url = f"https://{REG['route']}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={API_KEY}"
        acc_data = requests.get(acc_url).json()
        puuid = acc_data['puuid']

        league_url = f"https://{REG['id']}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={API_KEY}"
        league_data = requests.get(league_url).json()

        solo_rank, solo_lp = "Unranked", 0
        flex_rank, flex_lp = "Unranked", 0

        for entry in league_data:
            if entry['queueType'] == 'RANKED_SOLO_5x5':
                solo_rank, solo_lp = f"{entry['tier']} {entry['rank']}", entry['leaguePoints']
            elif entry['queueType'] == 'RANKED_FLEX_SR':
                flex_rank, flex_lp = f"{entry['tier']} {entry['rank']}", entry['leaguePoints']

        # 3. Save the new data to SQLite
        save_player(riot_id, solo_rank, solo_lp, flex_rank, flex_lp)
        return solo_rank, solo_lp, flex_rank, flex_lp, False # False means API was called
        
    except Exception:
        return "Not Found", 0, "Not Found", 0, False

# --- MAIN UI ---
input_text = st.text_area("Enter Riot IDs (one per line)", height=200, placeholder="Faker#KR1\nDoublelift#NA1")

if st.button("Check Ranks"):
    if input_text:
        ids = [i.strip() for i in input_text.split("\n") if "#" in i]
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, rid in enumerate(ids):
            status_text.text(f"Checking {rid}...")
            
            # Record start time to see if it was a "fast" cache hit
            start_time = time.time()
            
            # Call your cached function
            s_rank, s_lp, f_rank, f_lp, is_cached = get_player_rank(rid)
            
            # Calculate how long the function took
            duration = time.time() - start_time
            
            results.append({
                "Riot ID": rid, 
                "Solo Rank": s_rank, "Solo LP": s_lp,
                "Flex Rank": f_rank, "Flex LP": f_lp
            })
            
            progress_bar.progress((i + 1) / len(ids))

            # --- SMART SLEEP LOGIC ---
            # If duration < 0.1s, it was almost certainly a cache hit.
            # If it took longer, it was a real API call, so we must sleep.
            if not is_cached:
                time.sleep(0.02)

        status_text.success("✅ Done!")
        
        # Create DataFrame
        df = pd.DataFrame(results)
        
        # --- 1. DISPLAY TABLE ---
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
