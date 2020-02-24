from discord.ext.commands import Bot, CommandNotFound
from discord.utils import get
from discord.ext.tasks import loop
from discord import ChannelType, Embed
import os
import pymysql
import json
import threading
import requests
import asyncio
import sentry_sdk
import schedule

sentry_sdk.init(dsn=os.environ.get('SENTRY_DSN', ''))

BOT_PREFIX = (".")

# FACEIT Endpoints
FACEIT_DATA_V4      = "https://open.faceit.com/data/v4/"
FACEIT_QUEUE_API   = "https://api.faceit.com/queue/v1/player/"
FACEIT_STREAMINGS_V1_ORGANIZER = "https://api.faceit.com/stream/v1/streamings?limit=40&offset=0&organizerId="

# FACEIT Organizer IDs
NACCS_MAIN          = "80831a09-3b2d-4070-8a1a-3be4d3de2bb5"

# FACEIT Hub IDs
POWER_PUG_HUB       = "30d483b9-c337-4738-8d4a-b65bf656269d"
GENERAL_HUB         = "a67c2ead-9968-4e8b-957b-fb8bc244b302"

# FACEIT Division IDs
VARSITY = '78aa12dc-6234-4abc-ab54-02eb3408039f'
JUNIOR_VARSITY = 'cb04e1b2-a0c8-4212-9eb6-54243afbfa5b'

# FACEIT Queue IDs
POWER_QUEUE_ID      = '5e33533649222000078eb060'
GENERAL_QUEUE_ID    = '5d42347e5dca6f00071eaa09'

# Discord Channel IDs
POWER_PUG_CHANNEL   = 610367175487913984
GENERAL_CHANNEL     = 615733303424843798
POWER_PUG_CATEGORY  = 583601230073298954
GENERAL_CATEGORY    = 546131185797955600
POWER_PUG_LOBBY     = 583601364010270763
GENERAL_LOBBY       = 542495905484505108
LEAGUE_STREAMS      = 653368287010357248

# Secrets
DISCORD_TOKEN       = os.environ.get('DISCORD_TOKEN')
FACEIT_KEY          = os.environ.get('FACEIT_KEY')
FACEIT_BOT_KEY      = os.environ.get('FACEIT_BOT_KEY')
headers             = {"Authorization": "Bearer " + str(FACEIT_KEY)}

# Discord Bot
client = Bot(command_prefix=BOT_PREFIX)

# Mapping of FACEIT Match ID -> List(Discord Voice Channels)
channels = {}

# Global var for get_streams()
displayed_streams = {}

DB_HOST     = os.environ.get('DB_HOST')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_DB       = os.environ.get('DB_DB')
DB_USER     = os.environ.get('DB_USER')

# Purge the stream channel if the bot is just booting up
should_preload = True

# Power Pug open status
window_open = False


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
            sql = "select verified_student, faceit, discord, college from users_profile where discord=%s"
            cursor.execute(sql, (str(discord_name),))
            result = cursor.fetchone()
            verified_student = result.get('verified_student')
            faceit = result.get('faceit')
            discord = result.get('discord')
            is_verified.university = result.get('college')
            print(verified_student, faceit, discord, is_verified.university)
            
            if (verified_student and faceit and discord):
                return True
            else:
                return False
    except Exception as e:
        print("Unable to SQL for", discord_name, e)
        return False

#
#   Build university tag for user nickname.
#
async def create_uni_tag(author, university):
    db = db_connect()
    try:
        with db.cursor() as cursor:
            sql = "SELECT abbreviation FROM league_school WHERE name =%s;"
            cursor.execute(sql, (str(university),))
            result = cursor.fetchone()
            tag = result.get('abbreviation')
            await author.send("I added your college tag to your server nickname. Feel free to change it if I made a mistake.")
    except Exception as e:
        print("SQL failed, falling back to generation", university, e)
        tag_words = university.split()
        tag_letters = [word[0] for word in tag_words]
        tag = "".join(tag_letters)
        await author.send("I added your college tag to your server nickname. Unfortunately we don't have one stored for your school so I tried my best to generate it. Feel free to change it if I made a mistake.")
    
    await author.edit(nick="[{}] {}".format(tag, author.name))

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

#
#   Get ongoing FACEIT streams for all of NACCS on FACEIT
#
# 
async def preload_streams():
    channel = client.get_channel(LEAGUE_STREAMS)

    await channel.purge()
    await channel.send("This channel automatically shows streams from players currently using a NACCS service on FACEIT. I update every 5 minutes.")

#
#   Open the Power Pugs queue
#
def open_powerpugs():
    print("Opening Powerpugs")
    pass


#
#   Close the Power Pugs queue
#
def close_powerpugs():
    print("Closing Powerpugs")
    pass

@loop(seconds=1)
async def powerpugs_timer():
    schedule.run_pending()


@loop(minutes=5)
async def get_streams():
    global displayed_streams

    active_streams = {}
    response_naccs = requests.get(FACEIT_STREAMINGS_V1_ORGANIZER + NACCS_MAIN)
    naccs_data = response_naccs.json()

    stream_responses = {0: naccs_data} # Scalability, for multiple APIs. (Since we are only using one now)

    for division in stream_responses:
        streams_json = stream_responses[division]

        count = 0
        for x in streams_json: 
            if isinstance(streams_json[x], list): 
                count += len(streams_json[x]) 
        for x in range(count):
            response_passed = True # Getting data ready for tests to verify json integrity
            # Check the json for missing key.
            expected_keys = ['payload', x, 'stream', 'viewers']
            _streams_json = streams_json
            for item in expected_keys:
                try:
                    _streams_json = _streams_json[item]
                except KeyError:
                    response_passed = False

            if (response_passed == False):
                print("FACEIT API returned incomplete response.")
            else:
                response_nick = (streams_json["payload"][x]["userNickname"])
                response_image = (streams_json["payload"][x]["stream"]["channelLogo"])
                response_comp_name = (streams_json["payload"][x]["competitionName"])
                response_channel_url = (streams_json["payload"][x]["stream"]["channelUrl"])
                response_faction_name = (streams_json["payload"][x]["factionNickname"])
                response_viewers = (streams_json["payload"][x]["stream"]["viewers"])
                active_streams[response_nick] = response_nick

                channel = client.get_channel(LEAGUE_STREAMS)
                embed = Embed(title=response_nick, url=response_channel_url, description=response_comp_name, color=0x5e7aac)
                embed.set_thumbnail(url=response_image)
                embed.set_author(name="A NACCS Stream is Live!", icon_url="https://naccs-s3.s3.us-east-2.amazonaws.com/static/assets/headerlogo_small.png")
                embed.add_field(name="Team", value=response_faction_name, inline=True)
                embed.add_field(name="Viewers", value=response_viewers, inline=True)

                if response_nick in displayed_streams:
                    msg = await channel.fetch_message(displayed_streams[response_nick])
                    await msg.edit(embed=embed)
                    continue
                else:
                    embed_active = await channel.send(embed=embed)
                    displayed_streams[response_nick] = embed_active.id


    #Check to see if streams have ended, if so, remove the messages
    stream_over = { k : displayed_streams[k] for k in set(displayed_streams) - set(active_streams) }
    if stream_over:
        for key in stream_over:
            channel = client.get_channel(LEAGUE_STREAMS)
            msg = await channel.fetch_message(displayed_streams[key])
            await msg.delete()
            del displayed_streams[key]
            stream_over = {}

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
    match_id = parsed.get('match_id')

    if match_id in channels:
        # For some reason the webhook was reporting duplicate matches so this is here
        # to protect against that
        print("Match with ID", match_id, "already handled!")
        return

    if parsed.get("hub") == "NACCS Collegiate Queue":
        category = get_category(guild, GENERAL_CATEGORY)
    elif parsed.get("hub") == "NACCS Power Pugs":
        category = get_category(guild, POWER_PUG_CATEGORY)
    else:
        return

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
@client.command(name='autowindowon',
                description="Turn on Power Pugs Queue Window",
                brief="Turn on Power Pugs Queue Window",
                pass_context=True)
async def start_autowindow(context):
    global window_open
    if window_open:
        # Already running
        await context.channel.send('Power Pugs already opened!')
        return

    for role in context.message.author.roles:
        if role.name == 'Tech Crew':
            schedule.every().day.at("17:00").do(open_powerpugs)
            schedule.every().monday.at("22:00").do(close_powerpugs)
            schedule.every().tuesday.at("22:00").do(close_powerpugs)
            schedule.every().wednesday.at("22:00").do(close_powerpugs)
            schedule.every().thursday.at("22:00").do(close_powerpugs)
            schedule.every().friday.at("23:59").do(close_powerpugs)
            schedule.every().saturday.at("23:59").do(close_powerpugs)
            schedule.every().sunday.at("23:59").do(close_powerpugs)
            powerpugs_timer.start()
            window_open = True

            await context.channel.send('Opened Power Pugs Window!')
            return


@client.command(name='autowindowoff',
                description="Turn off Power Pugs Queue Window",
                brief="Turn off Power Pugs Queue Window",
                pass_context=True)
async def close_autowindow(context):
    global window_open
    if not window_open:
        # Already closed
        await context.channel.send('Power Pugs already closed!')
        return

    for role in context.message.author.roles:
        if role.name == 'Tech Crew':
            schedule.clear()
            powerpugs_timer.stop()
            window_open = False

            await context.channel.send('Closed Power Pugs Window!')
            return


@client.command(name='pingme',
                description="Get the Ping role so you can be notified for Collegiate Hub queues",
                brief="Get the Ping role",
                pass_context=True)
async def pingme(context):
    author = context.message.author
    
    role = get(context.guild.roles, name="Ping")
    await author.add_roles(role)
    await author.send("I've given you the Ping role! GLHF!")
    await context.message.delete(delay=2)

    return

@client.command(name='noping',
                description="Remove yourself from the Ping role so you no longer get pinged by the Collegiate Queue",
                brief="Remove the Ping role from yourself",
                pass_context=True)
async def noping(context):
    author = context.message.author
    
    role = get(context.guild.roles, name="Ping")
    await author.remove_roles(role)
    await author.send("You no longer have the Ping role.")
    await context.message.delete(delay=2)

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
        
        #Create college tag
        university = is_verified.university
        if (university != ""):
            await create_uni_tag(author, university)
        else:
            await author.send("Unable to generate college tag. Contact a NACCS Tech. For now, add your college tag to your server nickname.")

        await author.send("You're verified! I've assigned you the Member role and the Ping role. The Ping role subscribes you to a ping for when the Collegiate Hub gets active. If you don't want it, head over to #pingtoggle and type '.noping'. GLHF!")
    else:
        await author.send("I couldn't verify you. Make sure that you have verified college credentials and that both your FACEIT and Discord accounts are linked! A common issue people encounter is that the Discord account they link is not the Discord account that's logged into their client. Make sure the Discord account you link is EXACTLY the one you're using right now! If you're sure that you have everything in order, contact NACCS staff.")

    await context.message.delete(delay=2)

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
        await context.message.delete(delay=2)
        return

    # Check if our GET request succeeded
    if (matches == None):
        await channel.send('I had trouble fetching matches :( Notify staff and try again later.', delete_after=20)
        # Delete message
        await context.message.delete(delay=2)
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
    await context.message.delete(delay=2)

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
        return
    else:
        # Don't process bot messages
        if (message.author.bot):
            return

        await client.process_commands(message)

@client.event
async def on_command_error(context, error):
    if isinstance(error, CommandNotFound):
        # Wait 3 seconds before deleting because Discord glitches out if we
        # delete it immediately after user writes the message.
        await context.message.delete(delay=2)
        return

    raise error

@client.event
async def on_ready():
    global should_preload
    if should_preload:
        await preload_streams()
        should_preload = False
        
    # Call get_streams() and begin 5 minute timer
    print("Bot ready. Starting stream task...")
    await get_streams.start()

@client.event
async def on_disconnect():
    print("Bot disconnected. Stopping stream task...")
    await get_streams.stop()

"""
-------------------------------------------------------------------------------
    Main
-------------------------------------------------------------------------------
"""
if __name__ == '__main__':
    print("Bot Starting...")
    # Run Discord Bot
    client.run(DISCORD_TOKEN)
