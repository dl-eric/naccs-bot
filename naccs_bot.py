from discord.ext.commands import Bot
from discord.utils import get
from discord import ChannelType, Embed
import requests
import os

BOT_PREFIX = (".")

# FACEIT Data v4 Endpoint
FACEIT_DATA_V4      = "https://open.faceit.com/data/v4/"

# FACEIT Hub IDs
POWER_PUG_HUB       = "9512ae3b-7322-4821-9eca-6e0db1819b03"
GENERAL_HUB         = "a67c2ead-9968-4e8b-957b-fb8bc244b302"

# Discord Channel IDs
POWER_PUG_CHANNEL   = 610367175487913984
GENERAL_CHANNEL     = 0

# Secrets
DISCORD_TOKEN       = os.environ.get('DISCORD_TOKEN')
FACEIT_KEY          = os.environ.get('FACEIT_KEY')
headers             = {"Authorization": "Bearer " + str(FACEIT_KEY)}

# Discord Bot
client = Bot(command_prefix=BOT_PREFIX)


"""
-------------------------------------------------------------------------------
    FACEIT API Helpers
-------------------------------------------------------------------------------
"""
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
    Discord client commands
-------------------------------------------------------------------------------
"""
@client.command(name='verify',
                description="Check discord user if they exist in NACCS user db to give Member role",
                brief="Verify user status",
                pass_context=True)
async def verify(context):
    author = context.message.author

    # 1. Get all unverified users
    # 2. Check discords of all unverified users to author
    # 3a. If in db, assign Member role
    # 3b. Else, send dm to user
    # 4. Delete message

    return


@client.command(name='matches',
                description="Show current match status for ongoing pugs in our FACEIT hub.",
                brief="Show current status of pugs.",
                pass_context=True)
async def matches(context):
    channel = context.channel

    # If a user dm's the bot, we want to ignore it.
    if channel.type != ChannelType.text:
        return

    # Delete message
    await context.message.delete()

    matches = get_ongoing_matches(channel.id)

    if (len(matches['items']) == 0):
        await channel.send('There are currently no ongoing matches.', delete_after=20)
        return

    # Check if our GET request succeeded
    if (matches == None):
        await channel.send('I had trouble fetching matches :( Notify staff and try again later.', delete_after=20)
        return

    for item in matches['items']:
        teams = item['teams']
        results = item['results']
        faction1 = teams['faction1']
        faction2 = teams['faction2']
        faction1_score = str(results['score']['faction1'])
        faction2_score = str(results['score']['faction2'])
        location = item['voting']['location']['pick'][0]
        game_map = item['voting']['map']['pick'][0]

        score = Embed(title=faction1['name'] + ' (' + faction1_score + ')' + ' vs. ' + faction2['name'] + ' (' + faction2_score + ')', 
                        description=location + ' | ' + game_map, 
                        url=item['faceit_url'])
        
        faction1_roster = ''
        faction2_roster = ''
        for i in range (5):
            faction1_roster += faction1['roster'][i]['nickname'] + '\n'
            faction2_roster += faction2['roster'][i]['nickname'] + '\n'

        score.add_field(name=faction1['name'] + ' (' + faction1_score + ')', value=faction1_roster)
        score.add_field(name=faction2['name'] + ' (' + faction2_score + ')', value=faction2_roster)
    
        await channel.send(embed=score, delete_after=20)

    return

# On match ready

# 1. Get match ID
# 2. Get match via match ID
# 3. Get FACEIT players in match
# 4. Get FACEIT player -> discord id mapping via db
# 5. Create 2 voice channels with appropriate roles
# 6. Create match id to voice channel mapping 
# 7. Move discord ids to appropriate voice channels

# On match completed or canceled

# 1. Move all players to lobby
# 2. Delete channel

@client.event
async def on_message(message):
    # Catch FACEIT webhook!
    if (message.webhook_id):
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

    # Start listening for FACEIT webhook
