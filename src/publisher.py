# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

import logging
import aiohttp
import asyncio
import bot
import datetime
import discord
import os
from bot import client, database_required, tree
from dataclasses import dataclass
from discord.utils import utcnow
from discord.ext import tasks


@dataclass
class ReleaseData:
    id: int
    title: str
    episode: int
    thumbnail_url: str | None
    publish_at: datetime.datetime
    published: bool


publish_channel_id = int(os.environ.get("DISCORD_PUBLISH_CHANNEL") or "0")
current_release: ReleaseData | None = None
task: asyncio.Task[None] | None = None
have_data = asyncio.Event()

async def restart() -> None:
    global task
    log = logging.getLogger()

    if task:
        _ = task.cancel()
    log.info(f"{'Restart' if task else 'Start'}ing release publisher...")
    task = client.loop.create_task(dispatch())

def create_embed(data: ReleaseData) -> discord.Embed:
    embed = discord.Embed()
    embed.title = data.title
    if data.thumbnail_url:
        embed.set_thumbnail(url=data.thumbnail_url)
    return embed

async def publish_release(data: ReleaseData) -> None:
    channel = client.get_partial_messageable(publish_channel_id)
    embed = create_embed(data)
    embed.description = f"Episode {data.episode} just released!"
    await channel.send(embeds=[embed])
    await bot.database.execute("UPDATE OR IGNORE releases SET published = 1 WHERE id = ?", (data.id,))

async def dispatch() -> None:
    global current_release
    try:
        while not client.is_closed():
            release = current_release = await wait(days=7)
            if not release:
                await restart()
                break
            now = utcnow()

            if release.publish_at >= now:
                sleep_time = (release.publish_at - now).total_seconds()
                await asyncio.sleep(sleep_time)

            await publish_release(release)
    except asyncio.CancelledError:
        raise
    except (OSError, discord.ConnectionClosed):
        await restart()

async def get_release(days: int) -> ReleaseData | None:
    # TODO: Get data from either the database
    row = await bot.database.fetchone(f"SELECT * FROM releases WHERE publish_at < {int((utcnow() + datetime.timedelta(days=days)).timestamp())} AND published == 0 ORDER BY publish_at")
    return ReleaseData(
        row["id"],
        row["title"],
        row["episode"],
        row["thumbnail_url"],
        datetime.datetime.fromtimestamp(row["publish_at"], tz=datetime.timezone.utc),
        row["published"] == 1,
    ) if row else None

async def wait(days: int) -> ReleaseData | None:
    global current_release
    log = logging.getLogger()

    log.info("Getting earliest release")
    release: ReleaseData | None = await get_release(days)
    if release is not None:
        have_data.set()
        return release

    log.info("Waiting for new release...")
    have_data.clear()
    current_release = None
    _ = await have_data.wait()
    return await get_release(days)

@tasks.loop(
    time = [datetime.time(hour=0, tzinfo=datetime.timezone.utc)]
)
@database_required
async def get_latest_schedule():
    """
    Get schedule data from AniChart
    """
    log = logging.getLogger()

    query = """
    query($page: Int, $weekStart: Int, $weekEnd: Int) {
      Page(page: $page) {
        airingSchedules(notYetAired: true, airingAt_greater: $weekStart, airingAt_lesser: $weekEnd, sort: TIME) {
          id
          media {
            title {
              romaji
            }
            coverImage {
              large
            }
          }
          episode
          airingAt
        }
        pageInfo {
          hasNextPage
        }
      }
    }
    """
    dt = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start = dt - datetime.timedelta(days=dt.weekday())
    end = (start + datetime.timedelta(days=6)).replace(hour=23, minute=59, second=59)
    earliest_airing_at: int | None = None
    async with aiohttp.ClientSession() as session:
        page = 1
        should_continue = True
        while should_continue:
            log.info(f"Fetching new releases... (Page {page})")

            variables = {
                "weekStart": start.timestamp(),
                "weekEnd": end.timestamp(),
                "page": page,
            }
            async with session.post("https://graphql.anilist.co/", json={ "query": query, "variables": variables }) as resp:
                data = await resp.json()

                try:
                    should_continue = data["data"]["Page"]["pageInfo"]["hasNextPage"]
                except:
                    should_continue = False
                page += 1

                schedules = data["data"]["Page"]["airingSchedules"]
                async with bot.database.transaction():
                    for i in schedules:
                        current_airing_at: int = i["airingAt"]
                        await bot.database.execute(
                            "INSERT OR IGNORE INTO releases (id, title, episode, thumbnail_url, publish_at, published) VALUES (?, ?, ?, ?, ?, 0)",
                            (
                                i["id"],
                                i["media"]["title"]["romaji"],
                                i["episode"],
                                i["media"]["coverImage"]["large"],
                                current_airing_at,
                            ),
                        )
                        if not earliest_airing_at or current_airing_at < earliest_airing_at:
                            earliest_airing_at = current_airing_at
    if earliest_airing_at is None:
        return

    have_data.set()
    if current_release and earliest_airing_at < int(current_release.publish_at.timestamp()):
        # This is unlikely to happened, but just in case...
        log.info("Found earlier release, restarting...")
        await restart()

#region Views
class ScheduleView(discord.ui.View):
    def __init__(self, releases: list[ReleaseData], timeout=900):
        super().__init__(timeout=timeout)
        self.releases = releases
        self.current_index = 0

        # Disable buttons if only one image
        if len(releases) <= 1:
            self.previous_button.disabled = True
            self.next_button.disabled = True
    
    def render(self):
        data = self.releases[self.current_index]

        embed = create_embed(data)
        embed.description = f"Episode {data.episode} release at <t:{int(data.publish_at.timestamp())}> (<t:{int(data.publish_at.timestamp())}:R>)"
        embed.set_footer(text=f"Page {self.current_index + 1}/{len(self.releases)}")

        return embed
    
    @discord.ui.button(label='◀', style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0:
            self.current_index -= 1
        else:
            self.current_index = len(self.releases) - 1  # Loop to last imag

        embed = self.render()
        return await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label='▶', style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.releases) - 1:
            self.current_index += 1
        else:
            self.current_index = 0  # Loop to first image

        embed = self.render()
        return await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label='❌', style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable all buttons and edit message
        for item in self.children:
            item.disabled = True

        embed = self.render()
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()
#endregion

#region Commands
async def schedules(interaction: discord.Interaction):
    rows = await bot.database.fetchall(f"SELECT * FROM releases WHERE published == 0 ORDER BY publish_at")
    data = [
        ReleaseData(
            row["id"],
            row["title"],
            row["episode"],
            row["thumbnail_url"],
            datetime.datetime.fromtimestamp(row["publish_at"], tz=datetime.timezone.utc),
            row["published"] == 1,
        ) for row in rows
    ]

    view = ScheduleView(data)
    embed = view.render()
    await interaction.response.send_message(embeds=[embed], view=view)

async def fetch_schedules(interaction: discord.Interaction):
    await get_latest_schedule()
    await interaction.response.send_message("Fetching...", ephemeral=True)

async def register_commands():
    def command(name: str, callback, description: str = "..."):
        return discord.app_commands.Command(
            name = name,
            description = description,
            callback = callback,
        )

    tree.add_command(command("schedules", description="Get current anime release schedule", callback=schedules))
    tree.add_command(command("fetch-schedules", description="Fetch anime release schedule from AniList", callback=fetch_schedules))
#endregion
