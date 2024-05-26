import time
import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import requests

def load_config():
    try:
        with open("config.json", "r") as config_file:
            return json.load(config_file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading config: {e}")
        exit(1)

config = load_config()
api_key = config["api_key"]
bot_token = config["bot_token"]
CHANNEL_ID = int(config["channel_id"])
REQUIRED_ROLE_ID = int(config["required_role_id"])
DATABASE_FILE = "player_data.json"

# Global Variables
player_data = {}

# Region
API_REGIONS = {
    "account": "europe",    # Account v4
    "league": "euw1",       # League v4
    "match": "europe",      # Match v5
    "summoner": "euw1",     # Summoner v4
    "mastery": "euw1"       # Mastery v4
}

# Rank Values
TIER_VALUES = {
    "IRON": 0,
    "BRONZE": 1,
    "SILVER": 2,
    "GOLD": 3,
    "PLATINUM": 4,
    "EMERALD": 5,
    "DIAMOND": 6,
    "MASTER": 7,
    "GRANDMASTER": 8,
    "CHALLENGER": 9
}

DIVISION_VALUES = {
    "IV": 0,
    "III": 1,
    "II": 2,
    "I": 3
}

# Loading and saving
async def load_player_data():
    global player_data
    try:
        with open(DATABASE_FILE, "r") as f:
            loaded_data = json.load(f)

            # Convert loaded data to dictionary with integer keys
            player_data = {int(k): v for k, v in loaded_data.items()}  
            
    except FileNotFoundError:
        player_data = {}
        await save_player_data()

async def save_player_data():
    with open(DATABASE_FILE, "w") as f:
        json.dump(player_data, f, indent=4)

# Getters
async def get_puuid(riot_id):
    region = API_REGIONS["account"]
    try:
        gameName, tagLine = riot_id.split('#')
    except ValueError:
        return None
    url = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}?api_key={api_key}"

    try:
        response = get_with_retry(url)  
    except requests.exceptions.RequestException as e:
        print(f"Error fetching PUUID after retries: {e}")
        return None  # Return None on error after retries

    if response.status_code == 200: 
        data = response.json()
        puuid = data.get('puuid')
        if puuid:
            return puuid
        else:
            print("Error fetching PUUID: Valid response but PUUID not found.")
    elif response.status_code == 404:
        return None  # Account not found
    else:
        print(f"Error fetching PUUID: {response.status_code} - {response.text}")
        return None

async def get_league_entries(summoner_id):
    region = API_REGIONS["league"]
    url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}?api_key={api_key}"

    try:
        response = get_with_retry(url)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching league entries after retries: {e}")  # Log after retry failures
        return None 

    if response.status_code == 200:
        entries = response.json()

        # Check if the response is a list
        if not isinstance(entries, list):
            print(f"Error fetching league entries: Unexpected response format - {response.text}")
            return None

        ranks = {}
        for entry in entries:
            if entry['queueType'] == 'RANKED_SOLO_5x5':
                ranks['solo_duo'] = {
                    "tier": entry['tier'],
                    "rank": entry['rank'],
                    "leaguePoints": entry['leaguePoints']
                }
            elif entry['queueType'] == 'RANKED_FLEX_SR':
                ranks['flex'] = {
                    "tier": entry['tier'],
                    "rank": entry['rank'],
                    "leaguePoints": entry['leaguePoints']
                }
        return ranks
    elif response.status_code == 404:
        return None  # Summoner not found
    else:
        print(f"Error fetching league entries: {response.status_code} - {response.text}")
        return None

async def get_last_match_id(puuid):
    region = API_REGIONS["match"]
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=1&api_key={api_key}"

    try:
        response = get_with_retry(url)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching last match ID after retries: {e}")  # Log error after retries
        return None  # Return None on error after retries

    if response.status_code == 200:
        match_ids = response.json()

        # Data validation
        if isinstance(match_ids, list) and match_ids:  # Check if response is a list and not empty
            return match_ids[0]
        else:
            print("Error fetching last match ID: Unexpected response format -", match_ids)
            return None

    elif response.status_code == 404:
        return None  # No matches found (new account or no recent matches)
    else:
        print(f"Error fetching last match ID: {response.status_code} - {response.text}")
        return None

async def get_summoner_id(puuid):
    region = API_REGIONS["summoner"]
    url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}?api_key={api_key}"

    try:
        response = get_with_retry(url)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching summoner ID after retries: {e}")
        return None  # Return None on error after retries

    if response.status_code == 200:
        data = response.json()

        # Data validation
        summoner_id = data.get('id')
        if summoner_id:
            return summoner_id
        else:
            print("Error fetching summoner ID: Valid response but ID not found.")
            return None
    elif response.status_code == 404:
        return None  # Summoner not found
    else:
        print(f"Error fetching summoner ID: {response.status_code} - {response.text}")
        return None

async def get_latest_version():
    url = "https://ddragon.leagueoflegends.com/api/versions.json"

    try:
        response = get_with_retry(url)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching latest version after retries: {e}")
        return None

    if response.status_code == 200:
        versions = response.json()
        
        # Data Validation 
        if isinstance(versions, list) and versions:  # Check if response is a list and not empty
            return versions[0]
        else:
            print("Error fetching latest version: Unexpected response format -", versions)
            return None

    # We don't expect a 404 for this endpoint, so treat any other status code as an error
    else:  
        print(f"Error fetching latest version: {response.status_code} - {response.text}")
        return None

async def get_champion_id(champion_name):
    latest_version = await get_latest_version()
    
    # Check if latest_version was obtained successfully
    if not latest_version:
        print("Error fetching latest version, cannot get champion ID.")
        return None

    url = f"http://ddragon.leagueoflegends.com/cdn/{latest_version}/data/en_US/champion.json"

    try:
        response = get_with_retry(url)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching champion data after retries: {e}")
        return None

    if response.status_code == 200:
        champion_data = response.json().get("data")  # Use .get() to safely access the data
        
        # Data Validation
        if not isinstance(champion_data, dict):
            print(f"Error fetching champion data: Unexpected response format - {champion_data}")
            return None

        for champ_key, champ_info in champion_data.items():
            if champ_info["name"].lower() == champion_name.lower():
                return champ_info["key"]
        
        # Champion not found
        print(f"Error fetching champion ID: Champion '{champion_name}' not found.")  # Log champion not found
        return None 
    else:
        print(f"Error fetching champion data: {response.status_code} - {response.text}")
        return None

# Helper functions
async def update_streaks(user_id, riot_id, match_id):
    # Fetch Match Details
    region = API_REGIONS["match"]
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}?api_key={api_key}"

    try:
        response = get_with_retry(url)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching match details after retries: {e}")
        return

    if response.status_code == 200:
        match_data = response.json()

        # Data Validation
        if not isinstance(match_data.get("info"), dict):
            print(f"Error updating streaks: Unexpected match data format - {match_data}")
            return

        queue_id = match_data["info"]["queueId"]

        # Map Queue ID to Streak Type
        streak_type = {
            400: "quickplay/draftpick",
            430: "quickplay/draftpick",
            420: "ranked_solo_duo",
            440: "ranked_flex",
            450: "aram",
            1700: "arena",  # Updated to 1700 for Clash
            # ... (Add more as needed)
        }.get(queue_id)

        if not streak_type:
            print(f"Unsupported queue type: {queue_id}")
            return

        player_data[user_id][riot_id]["last_queue_type"] = streak_type

        # Find the participant matching the puuid
        for participant in match_data["info"]["participants"]:
            if participant["puuid"] == player_data[user_id][riot_id]["puuid"]:
                # Update Streak
                streak_data = player_data[user_id][riot_id]["streaks"][streak_type]
                if participant["win"]:
                    streak_data["wins"] += 1
                    streak_data["losses"] = 0
                else:
                    streak_data["losses"] += 1
                    streak_data["wins"] = 0

                # Mention Dasken (only if a loss)
                if user_id == 183253004005146625 and not participant["win"]:
                    channel = bot.get_channel(CHANNEL_ID)
                    user = await bot.fetch_user(183253004005146625)
                    await channel.send(
                        f"{user.mention} just lost a game in {streak_type} with Riot ID: {riot_id}"
                    )
                
                await save_player_data()
                break  # No need to continue searching
        else:  # No participant with matching PUUID found
            print(f"Error updating streaks: Participant with PUUID '{player_data[user_id][riot_id]['puuid']}' not found in match {match_id}")
    else:
        print(f"Error fetching match details: {response.status_code} - {response.text}")

@tasks.loop(minutes=1)  
async def check_for_updates():
    channel = bot.get_channel(CHANNEL_ID)
    for discord_id, riot_id_data in player_data.items():
        user = await bot.fetch_user(discord_id)
        for riot_id, data in riot_id_data.items():
            last_match_id = data["last_match_id"]

            # Fetch Recent Match IDs
            new_match_id = await get_last_match_id(data["puuid"])
            if new_match_id and new_match_id != last_match_id:
                # New Match Found
                data["last_match_id"] = new_match_id
                await update_streaks(discord_id, riot_id, new_match_id)

            # Check for Rank Changes
            new_league_entries = await get_league_entries(data["summoner_id"])
            if new_league_entries:
                for queue_type, entry in new_league_entries.items():
                    old_entry = data["league_entries"].get(queue_type)  # Get existing entry if it exists

                    # If the queue type doesn't exist yet, treat it as a new entry
                    if old_entry is None:
                        data["league_entries"][queue_type] = entry
                        await channel.send(
                            f"{user.mention} has a new rank in {queue_type}: {entry['tier']} {entry['rank']} with Riot ID: {riot_id}"
                        )
                    else:
                        # If the queue type exists, check for rank changes
                        if old_entry != entry:
                            old_tier_value = TIER_VALUES.get(old_entry["tier"], -1)
                            new_tier_value = TIER_VALUES.get(entry["tier"], -1)
                            old_division_value = DIVISION_VALUES.get(old_entry["rank"], -1)
                            new_division_value = DIVISION_VALUES.get(entry["rank"], -1)

                            if new_tier_value != old_tier_value or new_division_value != old_division_value:
                                overall_change = new_tier_value * 4 + new_division_value - (old_tier_value * 4 + old_division_value)
                                change = "promoted" if overall_change > 0 else "demoted"
                                await channel.send(
                                    f"{user.mention} has been **{change}** to **{entry['tier']} {entry['rank']}** in {queue_type} with Riot ID: {riot_id}"
                                )
                    data["league_entries"][queue_type] = entry # Make sure to always update league entries regardless of tier change
    await save_player_data()

def get_with_retry(url, max_retries=3, retry_delay=2):
    """Generic function to make API calls with retry logic."""
    for attempt in range(max_retries):
        response = requests.get(url)

        if response.status_code == 200:
            return response  # Return the successful response
        
        # Handle rate limiting, server errors, and internal server errors
        elif response.status_code in (429, 500, 503):  
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 1))
            else:
                retry_after = retry_delay  # Default retry delay for 500 and 503

            print(f"Rate limited/Server error (500/503) on attempt {attempt + 1}. Retrying after {retry_after} seconds...")
            time.sleep(retry_after)

        else:
            response.raise_for_status()  # Raise an exception for other errors

    # If we've reached max retries, raise an exception with the last response
    response.raise_for_status()

# Bot logic
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=None, intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    await load_player_data()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)
    update_checker.start()


@bot.tree.command(name="register", description="Register a League of Legends account.")
async def register(interaction: discord.Interaction, riot_id: str, user: discord.Member = None):
    if not user:
        user = interaction.user

    if REQUIRED_ROLE_ID:
        role = discord.utils.get(interaction.guild.roles, id=REQUIRED_ROLE_ID)
        if role not in user.roles:
            await interaction.response.send_message(f"{user.mention}, you need the '{role.name}' role to register.")
            return

    # --- Check if Riot ID is already registered ---
    if user.id in player_data and riot_id in player_data[user.id]:
        await interaction.response.send_message(f"{user.mention}, you are already registered with Riot ID: {riot_id}")
        return
    
    puuid = await get_puuid(riot_id)
    if not puuid:
        await interaction.response.send_message(f"{user.mention}, invalid Riot ID format or account not found.")
        return

    summoner_id = await get_summoner_id(puuid)
    if not summoner_id:
        await interaction.response.send_message(f"{user.mention}, error fetching summoner ID.")
        return
   
    league_entries = await get_league_entries(summoner_id)
    last_match_id = await get_last_match_id(puuid)

    if user.id not in player_data:
        player_data[user.id] = {}

    player_data[user.id][riot_id] = {
        "puuid": puuid,
        "summoner_id": summoner_id,
        "league_entries": league_entries,
        "last_match_id": last_match_id,
        "streaks": {
            "quickplay/draftpick": {"wins": 0, "losses": 0},
            "ranked_solo_duo": {"wins": 0, "losses": 0},
            "ranked_flex": {"wins": 0, "losses": 0},
            "aram": {"wins": 0, "losses": 0},
            "arena": {"wins": 0, "losses": 0}
        },
        "last_queue_type": None
    }

    if last_match_id:
        await update_streaks(user.id, riot_id, last_match_id)

    await save_player_data()
    await interaction.response.send_message(f"{user.mention}, you have been registered with Riot ID: {riot_id}")

@bot.tree.command(name="unregister", description="Unregister a League of Legends account.")
async def unregister(interaction: discord.Interaction, riot_id: str, user: discord.Member = None):
    if not user:
        user = interaction.user

    user_id = user.id
    if user_id in player_data and riot_id in player_data[user_id]:
        del player_data[user_id][riot_id]  
        # Remove user if no more Riot IDs are left
        if not player_data[user_id]:
            del player_data[user_id]
        await save_player_data()
        await interaction.response.send_message(f"{user.mention}, you have been unregistered from Riot ID: {riot_id}")
    else:
        await interaction.response.send_message(f"{user.mention}, you are not registered with Riot ID: {riot_id}")

@bot.tree.command(name="mastery", description="Display champion mastery levels for a user.")
async def mastery(interaction: discord.Interaction, user: discord.Member, champion_name: str):
    user_id = user.id  # No need to convert to string
    if user_id in player_data:
        riot_ids = player_data[user_id].keys()
        region = API_REGIONS["summoner"]  # Updated to correct region
        champion_id = await get_champion_id(champion_name)

        if champion_id is None:  # Handle invalid champion name
            await interaction.response.send_message(f"Invalid champion name: {champion_name}")
            return

        mastery_info = []
        for riot_id in riot_ids:
            puuid = player_data[user_id][riot_id]["puuid"]  # Get puuid for each riot_id
            try:
                url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/by-champion/{champion_id}?api_key={api_key}"
                response = requests.get(url)
                response.raise_for_status()

                # Get the mastery directly from the response
                mastery_data = response.json()
                mastery_level = mastery_data["championLevel"]
                mastery_points = mastery_data["championPoints"]

                # Add playertag (from riot_id)
                playertag = riot_id
                mastery_info.append(f"{playertag} ({region}): Level {mastery_level}, {mastery_points} points")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    mastery_info.append(f"{riot_id} ({region}): Not found")
                else:
                    await interaction.response.send_message(f"Error fetching mastery for {riot_id}: {e}")
                    return  # Early return on unexpected errors

        if mastery_info:
            await interaction.response.send_message("\n".join(mastery_info))
        else:
            await interaction.response.send_message(f"No mastery information found for {champion_name}.")
    else:
        await interaction.response.send_message(f"User {user.mention} is not registered with the bot.")

@bot.tree.command(name="build", description="Get a link to U.GG builds for a champion.")
async def build(interaction: discord.Interaction, champion_name: str):
    champion_name = champion_name.lower()
    url = f"https://u.gg/lol/champions/{champion_name}/build?rank=diamond_plus"
    await interaction.response.send_message(f"Here's the build for {champion_name.capitalize()} on U.GG: {url}")

@bot.tree.command(name="rank", description="Display rank information for a user.")
async def rank(interaction: discord.Interaction, user: discord.Member = None):
    if not user:
        user = interaction.user

    user_id = user.id

    if user_id in player_data:
        ranks_info = []
        for riot_id, data in player_data[user_id].items():
            league_entries = data.get("league_entries")
            if league_entries:
                for queue_type, entry in league_entries.items():
                    ranks_info.append(
                        f"Riot ID: {riot_id} - {queue_type}: {entry['tier']} {entry['rank']} ({entry['leaguePoints']} LP)"
                    )

        if ranks_info:
            await interaction.response.send_message(f"Ranks for {user.mention}:\n" + "\n".join(ranks_info))
        else:
            await interaction.response.send_message(f"No rank information found for {user.mention}.")
    else:
        await interaction.response.send_message(f"User {user.mention} is not registered with the bot.")

@tasks.loop(minutes=1) 
async def update_checker():
    try:
        await check_for_updates()
    except Exception as e:
        print(f"Error in update_checker: {e}")

@update_checker.before_loop
async def before_update_checker():
    await bot.wait_until_ready()

bot.run(bot_token)
