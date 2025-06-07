# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

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
