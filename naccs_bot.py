from discord.ext.commands import Bot
from discord.utils import get
from discord import ChannelType, Embed
import requests
import os
import pymysql
import json

BOT_PREFIX = (".")

# FACEIT Endpoints
FACEIT_DATA_V4      = "https://open.faceit.com/data/v4/"
FACEIT_QUEUE_API   = "https://api.faceit.com/queue/v1/player/"

# FACEIT Hub IDs
POWER_PUG_HUB       = "9512ae3b-7322-4821-9eca-6e0db1819b03"
GENERAL_HUB         = "a67c2ead-9968-4e8b-957b-fb8bc244b302"

# FACEIT Queue IDs
POWER_QUEUE_ID      = ''
GENERAL_QUEUE_ID    = '5d42347e5dca6f00071eaa09'

# Discord Channel IDs
POWER_PUG_CHANNEL   = 610367175487913984
GENERAL_CHANNEL     = 615733303424843798
POWER_PUG_CATEGORY  = 583601230073298954
GENERAL_CATEGORY    = 546131185797955600
POWER_PUG_LOBBY     = 583601364010270763
GENERAL_LOBBY       = 542495905484505108

# Secrets
DISCORD_TOKEN       = os.environ.get('DISCORD_TOKEN')
FACEIT_KEY          = os.environ.get('FACEIT_KEY')
FACEIT_BOT_KEY      = os.environ.get('FACEIT_BOT_KEY')
headers             = {"Authorization": "Bearer " + str(FACEIT_KEY)}

# Discord Bot
client = Bot(command_prefix=BOT_PREFIX)

# Mapping of FACEIT Match ID -> List(Discord Voice Channels)
channels = {}

DB_HOST     = os.environ.get('DB_HOST')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_DB       = os.environ.get('DB_DB')
DB_USER     = os.environ.get('DB_USER')

def db_connect():
    db = pymysql.connect(host=DB_HOST, user=DB_USER, 
                            password=DB_PASSWORD, db=DB_DB, charset='utf8mb4', 
                            cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    return db

"""
-------------------------------------------------------------------------------
    MySQL Query Helpers
-------------------------------------------------------------------------------
"""
#
#   Check if discord user is verified on website
#
def is_verified(discord_name):
    db = db_connect()
    try:
        with db.cursor() as cursor:
            sql = "select verified_student, faceit, discord from users_profile where discord=%s"
            cursor.execute(sql, (str(discord_name),))
            result = cursor.fetchone()
            verified_student = result.get('verified_student')
            faceit = result.get('faceit')
            discord = result.get('discord')
            print(verified_student, faceit, discord)
            
            if (verified_student and faceit and discord):
                return True
            else:
                return False
    except Exception as e:
        print("Unable to SQL for", discord_name, e)
        return False

#
#   Query discord username from faceit username
#
def get_discord_from_faceit(faceit):
    print("Finding", faceit)
    db = db_connect()
    try:
        with db.cursor() as cursor:
            sql = "select discord from users_profile where faceit=%s"
            cursor.execute(sql, (faceit,))
            return cursor.fetchone().get('discord')
    except Exception as e:
        print("Unable to SQL for", faceit, e)
        return None

"""
-------------------------------------------------------------------------------
    FACEIT API Helpers
-------------------------------------------------------------------------------
"""
#
#   Returns number of people in queue for specified channel
#
def get_queue_size(channel_id):
    if (channel_id == POWER_PUG_CHANNEL):
        endpoint = FACEIT_QUEUE_API + POWER_QUEUE_ID + "?limit=15"
    elif (channel_id == GENERAL_CHANNEL):
        endpoint = FACEIT_QUEUE_API + GENERAL_QUEUE_ID + "?limit=15"
    else:
        print("Invalid Channel ID. We shouldn't ever see this.")
        return None

    headers = {'Authorization': 'Bearer ' + str(FACEIT_BOT_KEY)}
    num = requests.get(endpoint, headers=headers)

    if (num.status_code != 200):
        print("Could not fetch queue size from", channel_id)
        print("STATUS", num.status_code)
        return None

    return len(num.json()['payload'])

#
#   Get ongoing FACEIT matches for specified channel
#
#   Returns None if unsuccessful
#
def get_ongoing_matches(channel_id):
    if (channel_id == POWER_PUG_CHANNEL):
        endpoint = FACEIT_DATA_V4 + "hubs/" + POWER_PUG_HUB + "/matches"
    elif (channel_id == GENERAL_CHANNEL):
        endpoint = FACEIT_DATA_V4 + "hubs/" + GENERAL_HUB + "/matches"
    else:
        print("Invalid Channel ID. We shouldn't ever see this.")
        return None

    matches = requests.get(endpoint, params={"type": "ongoing"}, headers=headers)

    if (matches.status_code != 200):
        print("Could not fetch matches from", channel_id)
        print("STATUS", matches.status_code)
        return None
    return matches.json()


"""
-------------------------------------------------------------------------------
    Discord API Helpers
-------------------------------------------------------------------------------
"""
#
#   Get category object by going through all categories
#
def get_category(guild, category_id):
    for category in guild.categories:
        if category.id == category_id:
            return category
    return None

# On match ready

# 1. Get match ID
# 2. Get FACEIT players in match
# 3. Get FACEIT player -> discord id mapping via db
# 4. Create 2 voice channels with appropriate roles
# 5. Create match id to voice channel mapping 
# 6. Move discord ids to appropriate voice channels
async def match_ready(message, parsed):
    print("Match ready")
    guild = message.guild

    if parsed.get("hub") == "NACCS Collegiate Queue":
        category = get_category(guild, GENERAL_CATEGORY)
    elif parsed.get("hub") == "NACCS Power Pugs":
        category = get_category(guild, POWER_PUG_CATEGORY)
    else:
        return

    match_id = parsed.get('match_id')
    channel_list = []
    for team in parsed.get('teams'):
        channel = await guild.create_voice_channel(team.get('team_name'), category=category, user_limit=5)

        for player in team.get('players'):
            discord_player = get_discord_from_faceit(player)
            if discord_player == None or discord_player == '':
                print("Could not find discord name for", player)
                continue

            member = guild.get_member_named(discord_player)
            try:
                await member.move_to(channel)
            except:
                print("Failed to move player", discord_player)

        channel_list.append(channel)

    channels[match_id] = channel_list
    return

# On match completed or canceled

# 1. Get match ID
# 2. Get appropriate channels from match ID
# 3. Move everyone to lobby
# 4. Delete channels
async def match_finished(message, parsed):
    print("Match finished")
    global channels
    
    if parsed.get('hub') == 'NACCS Collegiate Queue':
        lobby_channel = message.guild.get_channel(GENERAL_LOBBY)
    elif parsed.get('hub') == 'NACCS Power Pugs':
        lobby_channel = message.guild.get_channel(POWER_PUG_LOBBY)
    else:
        return

    match_id = parsed.get('match_id')
    to_delete = channels.get(match_id)
    if to_delete != None:
        for d in to_delete:
            members = d.members
            for member in members:
                await member.move_to(lobby_channel)
            await d.delete()
        channels.pop(match_id)
    else:
        print("Error! Couldn't find match", match_id)
    return

async def match_cancelled(message, parsed):
    print("Match cancelled")
    global channels

    if parsed.get('hub') == 'NACCS Collegiate Queue':
        lobby_channel = message.guild.get_channel(GENERAL_LOBBY)
    elif parsed.get('hub') == 'NACCS Power Pugs':
        lobby_channel = message.guild.get_channel(POWER_PUG_LOBBY)
    else:
        return

    match_id = parsed.get('match_id')
    to_delete = channels.get(match_id)
    if to_delete != None:
        for d in to_delete:
            members = d.members
            for member in members:
                await member.move_to(lobby_channel)
            await d.delete()
        channels.pop(match_id)
    else:
        print("Match was cancelled but no channel was to be deleted.")
    return

"""
-------------------------------------------------------------------------------
    Discord client commands
-------------------------------------------------------------------------------
"""
@client.command(name='pingme',
                description="Get the Ping role so you can be notified for Collegiate Hub queues",
                brief="Get the Ping role",
                pass_context=True)
async def pingme(context):
    author = context.message.author
    
    role = get(context.guild.roles, name="Ping")
    await author.add_roles(role)
    return

@client.command(name='noping',
                description="Remove yourself from the Ping role so you no longer get pinged by the Collegiate Queue",
                brief="Remove the Ping role from yourself",
                pass_context=True)
async def noping(context):
    author = context.message.author
    
    role = get(context.guild.roles, name="Ping")
    await author.remove_roles(role)
    return

@client.command(name='verify',
                description="Check discord user if they exist in NACCS user db to give Member role",
                brief="Verify user status",
                pass_context=True)
async def verify(context):
    author = context.message.author

    if is_verified(author):
        # Assign role
        member_role = get(context.guild.roles, name="Member")
        ping_role = get(context.guild.roles, name="Ping")
        await author.add_roles(member_role, ping_role)
        
        # Change nickname
        # TODO

        await author.send("You're verified! I've assigned you the Member role and the Ping role. The Ping role will subscribes you to a ping for when the Collegiate Hub gets active. If you don't want it, head over to #pingtoggle and type '.noping'. Also be sure to change your nickname with your college tag. GLHF!")
    else:
        await author.send("I couldn't verify you. Make sure that you have verified college credentials and that both your FACEIT and Discord accounts are linked! A common issue people encounter is that the Discord account they link is not the Discord account that's logged into their client. Make sure the Discord account you link is EXACTLY the one you're using right now! If you're sure that you have everything in order, contact NACCS staff.")

    await context.message.delete()

    return


@client.command(name='matches',
                description="Show current match status for ongoing pugs in our FACEIT hub.",
                brief="Show current status of pugs.",
                pass_context=True)
async def matches(context):
    channel = context.channel
    matches = get_ongoing_matches(channel.id)
    in_queue = get_queue_size(channel.id)

    await channel.send("```Currently in queue: " + str(in_queue) + '```', delete_after=30)
    

    if (len(matches['items']) == 0):
        await channel.send('There are currently no ongoing matches.', delete_after=20)
        # Delete message
        await context.message.delete()
        return

    # Check if our GET request succeeded
    if (matches == None):
        await channel.send('I had trouble fetching matches :( Notify staff and try again later.', delete_after=20)
        # Delete message
        await context.message.delete()
        return

    for item in matches['items']:
        teams = item['teams']
        faction1 = teams['faction1']
        faction2 = teams['faction2']
        
        faction1_score = ''
        faction2_score = ''
        
        if item['status'] != 'ONGOING' and item['status'] != 'READY':
            location = "Vote in progress"
            game_map = "Vote in progress"
        else:
            location = item['voting']['location']['pick'][0]
            game_map = item['voting']['map']['pick'][0]

        score = Embed(title=faction1['name'] + ' (' + faction1_score + ')' + ' vs. ' + faction2['name'] + ' (' + faction2_score + ')', 
                        description=location + ' | ' + game_map, 
                        url=str(item['faceit_url']).replace('{lang}', 'en'))
        
        if item['status'] == 'ONGOING' or item['status'] == 'READY':
            faction1_roster = ''
            faction2_roster = ''
            for i in range (5):
                faction1_roster += faction1['roster'][i]['nickname'] + '\n'
                faction2_roster += faction2['roster'][i]['nickname'] + '\n'

            score.add_field(name=faction1['name'] + ' (' + faction1_score + ')', value=faction1_roster)
            score.add_field(name=faction2['name'] + ' (' + faction2_score + ')', value=faction2_roster)
    
        await channel.send(embed=score, delete_after=30)

    # Delete message
    await context.message.delete()

    return

@client.event
async def on_message(message):
    # If a user dm's the bot, we want to ignore it.
    if message.channel.type != ChannelType.text:
        return
    
    # Catch FACEIT webhook!
    if (message.webhook_id):
        parsed = json.loads(message.content)
        print(parsed)
        if (parsed['event'] == "match_status_ready"):
            await match_ready(message, parsed)
        elif (parsed['event'] == "match_status_finished"):
            await match_finished(message, parsed)
        elif (parsed['event'] == "match_status_cancelled"):
            await match_cancelled(message, parsed)
        await message.delete()
        return
    else:
        # Don't process bot messages
        if (message.author.bot):
            return

        await client.process_commands(message)

"""
-------------------------------------------------------------------------------
    Main
-------------------------------------------------------------------------------
"""
if __name__ == '__main__':
    print("Bot Starting...")

    # Run Discord Bot
    client.run(DISCORD_TOKEN)
