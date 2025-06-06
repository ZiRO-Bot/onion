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

async def restart():
    global task
    if task:
        _ = task.cancel()
    task = client.loop.create_task(dispatch())

async def publish_release(data: ReleaseData) -> None:
    channel = client.get_partial_messageable(publish_channel_id)
    embed = discord.Embed()
    embed.title = data.title
    embed.description = f"Episode {data.episode} just released!"
    if data.thumbnail_url:
        embed.set_thumbnail(url=data.thumbnail_url)
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

    release: ReleaseData | None = await get_release(days)
    if release is not None:
        have_data.set()
        return release

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
    query = """
    query($weekStart: Int, $weekEnd: Int) {
      Page {
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
    variables = {
        "weekStart": start.timestamp(),
        "weekEnd": end.timestamp(),
    }
    earliest_airing_at: int | None = None
    async with aiohttp.ClientSession() as session:
        async with session.post("https://graphql.anilist.co/", json={ "query": query, "variables": variables }) as resp:
            data = await resp.json()
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
                    if not earliest_airing_at:
                        earliest_airing_at = current_airing_at
                    elif current_airing_at < earliest_airing_at:
                        earliest_airing_at = current_airing_at
    if earliest_airing_at is None:
        return

    have_data.set()
    if current_release and earliest_airing_at < int(current_release.publish_at.timestamp()):
        # This is unlikely to happened, but just in case...
        print("Found earlier release, restarting...")
        await restart()

async def schedules(interaction: discord.Interaction):
    rows = await bot.database.fetchall(f"SELECT * FROM releases WHERE published == 0 ORDER BY publish_at")
    data = [row["title"] for row in rows]
    await interaction.response.send_message(data, ephemeral=True)

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

    tree.add_command(command("schedules", callback=schedules))
    tree.add_command(command("fetch-schedules", callback=fetch_schedules))
