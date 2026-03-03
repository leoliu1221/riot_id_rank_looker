import streamlit as st
import requests
import time
import pandas as pd
import os
from dotenv import load_dotenv

# Load .env file automatically
load_dotenv()
API_KEY = os.getenv("RIOT_API_KEY")
if API_KEY:
    st.success("API Key loaded from .env")
else:
    API_KEY = st.secrets["RIOT_API_KEY"]
    if API_KEY:
        st.success("API Key loaded from Streamlit secrets")
    else:
        st.error("RIOT_API_KEY not found in .env or Streamlit secrets")
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

# --- API FETCH FUNCTION ---
def get_player_rank(riot_id):
    try:
        name, tag = riot_id.split('#')
        # 1. Get PUUID
        acc_url = f"https://{REG['route']}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={API_KEY}"
        acc_data = requests.get(acc_url).json()
        puuid = acc_data['puuid']

        # 3. Get Rank
        league_url = f"https://{REG['id']}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={API_KEY}"
        league_data = requests.get(league_url).json()

        for entry in league_data:
            if entry['queueType'] == 'RANKED_SOLO_5x5':
                return f"{entry['tier']} {entry['rank']}", entry['leaguePoints']
        return "Unranked", 0
    except Exception:
        return "Not Found", 0

# --- MAIN UI ---
input_text = st.text_area("Enter Riot IDs (one per line)", height=200, placeholder="Faker#KR1\nDoublelift#NA1")

if st.button("Check Ranks"):
    if not API_KEY:
        st.error("Please add RIOT_API_KEY to your .env file.")
    elif input_text:
        ids = [i.strip() for i in input_text.split("\n") if "#" in i]
        results = []
        
        progress_bar = st.progress(0)
        for i, rid in enumerate(ids):
            rank, lp = get_player_rank(rid)
            results.append({"Riot ID": rid, "Rank": rank, "LP": lp})
            progress_bar.progress((i + 1) / len(ids))
            time.sleep(1.2) # Rate limit safety
        
        df = pd.DataFrame(results)
        st.table(df)
        
        # Download Link
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download as CSV", csv, "ranks.csv", "text/csv")