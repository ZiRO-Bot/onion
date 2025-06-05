import asyncio
import os
import asqlite
import discord
import sys
import bot
from bot import bot_owner_id, client, tree, database_required
from src import publisher


token = os.environ.get("DISCORD_TOKEN")
try:
    import config
    token = token or config.token
except ImportError:
    print("Unable to load config")


@client.event
async def on_message(message: discord.Message) -> None:
    if (message.author.id != bot_owner_id):
        return

    if (message.content.startswith("!sync")):
        synced = await tree.sync()
        _ = await message.reply(f"{len(synced)} command(s) has been sync")

@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user}")

@database_required
async def migrate_db_if_needed() -> None:
    current_version = (await bot.database.fetchone("SELECT user_version FROM pragma_user_version"))["user_version"]
    migration_version = 0
    to_execute: list[str] = []
    for f in os.listdir("migrations"):
        if not f.lower().endswith(".sql"):
            continue

        try:
            migration_version = int(f.rstrip(".sql"))
        except:
            print(f"Migration failed, unable to get version from {f}")
            return

        if migration_version <= current_version:
            continue

        to_execute.append(f)

    if migration_version > current_version:
        print(f"Migrating database from {current_version} to {migration_version}")
        for f in to_execute:
            await bot.database.executescript(open(f"migrations/{f}").read())

    await bot.database.execute(f"PRAGMA user_version = {migration_version}")

async def start_bot() -> None:
    if not token:
        print("DISCORD_TOKEN is not set!")
        sys.exit(1)
    bot.database = await asqlite.connect("data/data.db")
    await migrate_db_if_needed()
    await client.login(token)
    await publisher.restart()
    publisher.get_latest_schedule.start()
    await client.connect()

def main() -> None:
    asyncio.run(start_bot())


if __name__ == "__main__":
    main()
