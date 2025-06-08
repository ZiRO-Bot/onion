# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

import contextlib
import logging
from typing import override
import asqlite
import asyncio
import bot
import discord
import os
import re
from bot import bot_owner_id, client, tree, database_required
from src import publisher
from logging.handlers import RotatingFileHandler


@tree.command()
@bot.is_me()
async def sync(interaction: discord.Interaction):
    """Sync the commands
    """
    synced = await tree.sync()
    await interaction.response.send_message(f"{len(synced)} command(s) has been sync")

@client.event
async def on_message(message: discord.Message) -> None:
    if (message.author.id != bot_owner_id):
        return

    bot_user = client.user
    if not bot_user:
        return
    pattern = f"<@(!?){bot_user.id}> sync"
    if re.fullmatch(pattern, message.content):
        synced = await tree.sync()
        await message.reply(f"{len(synced)} command(s) has been sync")

@client.event
async def on_ready() -> None:
    log = logging.getLogger()
    log.info(f"Logged in as {client.user}")

class RemoveNoise(logging.Filter):
    def __init__(self):
        super().__init__(name='discord.state')

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelname == 'WARNING' and 'referencing an unknown' in record.msg:
            return False
        return True

@contextlib.contextmanager
def setup_logging():
    log = logging.getLogger()

    try:
        discord.utils.setup_logging()
        # __enter__
        max_bytes = 32 * 1024 * 1024  # 32 MiB
        logging.getLogger('discord').setLevel(logging.INFO)
        logging.getLogger('discord.http').setLevel(logging.WARNING)
        logging.getLogger('discord.state').addFilter(RemoveNoise())

        log.setLevel(logging.INFO)
        handler = RotatingFileHandler(filename='data/onion.log', encoding='utf-8', mode='w', maxBytes=max_bytes, backupCount=5)
        dt_fmt = '%Y-%m-%d %H:%M:%S'
        fmt = logging.Formatter('[{asctime}] [{levelname:<7}] {name}: {message}', dt_fmt, style='{')
        handler.setFormatter(fmt)
        log.addHandler(handler)

        yield
    finally:
        # __exit__
        handlers = log.handlers[:]
        for hdlr in handlers:
            hdlr.close()
            log.removeHandler(hdlr)

@database_required
async def migrate_db_if_needed() -> None:
    log = logging.getLogger()

    current_version = (await bot.database.fetchone("SELECT user_version FROM pragma_user_version"))["user_version"]
    migration_version = 0
    to_execute: list[str] = []
    for f in os.listdir("migrations"):
        if not f.lower().endswith(".sql"):
            continue

        try:
            migration_version = int(f.rstrip(".sql"))
        except:
            log.exception(f"Migration failed, unable to get version from {f}")
            return

        if migration_version <= current_version:
            continue

        to_execute.append(f)

    if migration_version > current_version:
        log.info(f"Migrating database from {current_version} to {migration_version}")
        for f in to_execute:
            await bot.database.executescript(open(f"migrations/{f}").read())

    await bot.database.execute(f"PRAGMA user_version = {migration_version}")

async def start_bot() -> None:
    bot.check_config()

    await publisher.register_commands()

    bot.database = await asqlite.connect("data/data.db")
    await migrate_db_if_needed()
    await client.login(bot.token)
    await publisher.restart()
    publisher.get_latest_schedule.start()
    await client.connect()

def main() -> None:
    with setup_logging():
        asyncio.run(start_bot())


if __name__ == "__main__":
    main()
