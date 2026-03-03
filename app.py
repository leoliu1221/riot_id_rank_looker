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
        # 1. Input Validation: Ensure # exists
        if '#' not in riot_id:
            return "Invalid ID Format", 0, "Invalid ID Format", 0
            
        name, tag = riot_id.split('#')
        
        # 2. Get PUUID
        acc_url = f"https://{REG['route']}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={API_KEY}"
        acc_res = requests.get(acc_url)
        
        # Handle 404 (Not Found) or 403 (Invalid Key)
        if acc_res.status_code != 200:
            return "Account Not Found", 0, "N/A", 0
            
        acc_data = acc_res.json()
        puuid = acc_data.get('puuid') # Use .get() to avoid KeyError

        if not puuid:
            return "PUUID Missing", 0, "N/A", 0

        # 3. Get Rank Data
        league_url = f"https://{REG['id']}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={API_KEY}"
        league_res = requests.get(league_url)
        
        if league_res.status_code != 200:
            return "API Error", 0, "API Error", 0
            
        league_data = league_res.json()

        # Initialize defaults
        solo_rank, solo_lp = "Unranked", 0
        flex_rank, flex_lp = "Unranked", 0

        # Loop through results to find specific queues
        for entry in league_data:
            queue = entry.get('queueType')
            tier = entry.get('tier', 'Unknown')
            rank = entry.get('rank', '')
            lp = entry.get('leaguePoints', 0)

            if queue == 'RANKED_SOLO_5x5':
                solo_rank = f"{tier} {rank}".strip()
                solo_lp = lp
            elif queue == 'RANKED_FLEX_SR':
                flex_rank = f"{tier} {rank}".strip()
                flex_lp = lp
                
        return solo_rank, solo_lp, flex_rank, flex_lp

    except Exception:
        # Catch-all for network timeouts or other weirdness
        return "Not Found", 0, "Not Found", 0

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
            return rank_str.split(' ')[0]

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