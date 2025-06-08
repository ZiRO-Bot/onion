# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

import asqlite
import discord
import logging
import os
import sys
from discord import app_commands


token = os.environ.get("DISCORD_TOKEN") or ""
publish_channel_id = int(os.environ.get("DISCORD_PUBLISH_CHANNEL") or "0")
bot_owner_id = int(os.environ.get("DISCORD_BOT_OWNER") or "-1")
try:
    import config
    token = getattr(config, "token", token)
    publish_channel_id = getattr(config, "publish_channel_id", publish_channel_id)
    bot_owner_id = getattr(config, "bot_owner_id", bot_owner_id)
except ImportError:
    pass

def check_config():
    log = logging.getLogger()
    if not token:
        log.exception("DISCORD_TOKEN is not set!")
        sys.exit(1)

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

def is_me():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == bot_owner_id
    return app_commands.check(predicate)
