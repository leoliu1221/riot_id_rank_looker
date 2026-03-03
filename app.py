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

# --- API FETCH FUNCTION ---
def get_player_rank(riot_id):
    try:
        name, tag = riot_id.split('#')
        # 1. Get PUUID
        acc_url = f"https://{REG['route']}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={API_KEY}"
        acc_res = requests.get(acc_url)
        acc_data = acc_res.json()
        
        # Error handling for invalid Riot ID
        if 'puuid' not in acc_data:
            return "Not Found", 0, "Not Found", 0
            
        puuid = acc_data['puuid']

        # 2. Get Rank Data
        league_url = f"https://{REG['id']}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={API_KEY}"
        league_data = requests.get(league_url).json()

        # Initialize defaults
        solo_rank, solo_lp = "Unranked", 0
        flex_rank, flex_lp = "Unranked", 0

        # Loop through results to find specific queues
        for entry in league_data:
            if entry['queueType'] == 'RANKED_SOLO_5x5':
                solo_rank = f"{entry['tier']} {entry['rank']}"
                solo_lp = entry['leaguePoints']
            elif entry['queueType'] == 'RANKED_FLEX_SR':
                flex_rank = f"{entry['tier']} {entry['rank']}"
                flex_lp = entry['leaguePoints']
                
        return solo_rank, solo_lp, flex_rank, flex_lp

    except Exception as e:
        # In case of API errors or network issues
        return "Error", 0, "Error", 0

# --- MAIN UI ---
input_text = st.text_area("Enter Riot IDs (one per line)", height=200, placeholder="Faker#KR1\nDoublelift#NA1")

if st.button("Check Ranks"):
    if not API_KEY:
        st.error("Please add RIOT_API_KEY to your .env file.")
    elif input_text:
        # Split and clean the list of IDs
        ids = [i.strip() for i in input_text.split("\n") if "#" in i]
        results = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, rid in enumerate(ids):
            status_text.text(f"Processing {rid} ({i+1}/{len(ids)})...")
            
            # Unpack the 4 values from the updated get_player_rank function
            s_rank, s_lp, f_rank, f_lp = get_player_rank(rid)
            
            results.append({
                "Riot ID": rid, 
                "Solo Rank": s_rank, 
                "Solo LP": s_lp,
                "Flex Rank": f_rank, 
                "Flex LP": f_lp
            })
            
            # Progress bar and rate limit delay
            progress_bar.progress((i + 1) / len(ids))
            time.sleep(1.2) 

        status_text.success("✅ Done!")
        
        # Create DataFrame
        df = pd.DataFrame(results)
        
        # Display the interactive table
        st.subheader("Results")
        st.dataframe(df, use_container_width=True)
        
        # --- DOWNLOAD SECTION ---
        st.divider()
        csv = df.to_csv(index=False).encode('utf-8')
        
        st.download_button(
            label="📥 Download Results as CSV",
            data=csv,
            file_name="riot_ranks_bulk.csv",
            mime="text/csv",
            help="Click to download the table above as a CSV file for Excel or Google Sheets."
        )