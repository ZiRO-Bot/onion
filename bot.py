import asqlite
import discord
from discord import app_commands


bot_owner_id = 186713080841895936
database: asqlite.Connection | None = None
# I don't think I need any intent for this bot, so let's keep it default
client = discord.Client(intents=discord.Intents.default())
tree = app_commands.CommandTree(client)

def database_required(func):
    async def wrapper():
        if not database:
            raise RuntimeError("Database is not yet initialized!")
        await func()
    return wrapper
