from discord.ext.commands import Bot
from discord.utils import get
import requests

BOT_PREFIX = (".")

# FACEIT Data v4 Endpoint
FACEIT_DATA_V4      = "https://open.faceit.com/data/v4/"

# FACEIT Hub IDs
POWER_PUG_HUB       = "9512ae3b-7322-4821-9eca-6e0db1819b03"
GENERAL_HUB         = ""

# Discord Channel IDs
POWER_PUG_CHANNEL   = 
GENERAL_CHANNEL     = 

# Secrets
DISCORD_TOKEN       = os.environ.get('DISCORD_TOKEN')
headers             = {"Authorization": "Bearer " + os.environ.get('FACEIT_KEY')}

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
def get_ongoing_matches(discord_channel):
    if (discord_channel.id == POWER_PUG_CHANNEL):
        endpoint = FACEIT_DATA_V4 + "hubs/" + POWER_PUG_HUB + "/matches"
    else if (discord_channel.id == GENERAL_CHANNEL):
        endpoint = FACEIT_DATA_V4 + "hubs/" + GENERAL_HUB + "/matches"

    matches = requests.get(endpoint, params={"type": "ongoing"}, headers=headers)
    if (matches.status_code != 200):
        print("Could not fetch matches from", discord_channel)
        print("STATUS", matches.status_code)
        return None
    return matches.json

"""
-------------------------------------------------------------------------------
    Server to listen for FACEIT webhooks
-------------------------------------------------------------------------------
"""
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
    if channel.type == 'dm': # TODO
        return

    matches = get_ongoing_matches(channel)
    
    # Check if our GET request succeeded
    if (matches == None):
        channel.send('I had trouble fetching messages :( Notify staff and try again later.', delete_after=10)
        return

    for item in matches.items:
        # Send one message per match due to possible message character count limits
        print ('=============================================')
        print (faction1.name, 'vs.', faction2.name)
        print ()

    return


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
