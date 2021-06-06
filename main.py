import logging
import sqlite3
import yaml
import discord

DEFAULT_EMOJIS = ["\N{WHITE MEDIUM STAR}"]
DEFAULT_THRESHOLD = 3

with open("config.yaml") as conf_file:
    config = yaml.safe_load(conf_file)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

bot = discord.Client(
    intents=discord.Intents(guilds=True, guild_messages=True, guild_reactions=True)
)

database = sqlite3.connect("stars.sqlite3")


def start_bot():
    cursor = database.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS stars (
            original_id INTEGER PRIMARY KEY,
            starboard_channel INTEGER NOT NULL,
            starboard_id INTEGER NOT NULL
        )"""
    )
    database.commit()
    cursor.close()
    bot.run(config["token"])


def star_gradient_color(stars):
    p = min(stars / 13, 1)
    red = 255
    green = int((194 * p) + (253 * (1 - p)))
    blue = int((12 * p) + (247 * (1 - p)))
    return (red << 16) + (green << 8) + blue


def get_emoji_message(message, stars):
    if stars >= 25:
        emoji = "\N{SPARKLES}"
    elif stars >= 10:
        emoji = "\N{DIZZY SYMBOL}"
    elif stars >= 5:
        emoji = "\N{GLOWING STAR}"
    else:
        emoji = "\N{WHITE MEDIUM STAR}"

    content = f"{emoji} **{stars}** {message.channel.mention}"

    embed = discord.Embed(
        description=f"{message.content}\n\n[Jump to original message](https://discord.com/channels/{message.channel.guild.id}/{message.channel.id}/{message.id})"
    )

    if message.embeds:
        data = message.embeds[0]
        if data.type == "image" and data.thumbnail is not discord.Embed.Empty:
            embed.set_image(url=data.thumbnail.url)

    if message.attachments:
        file = message.attachments[0]
        if file.width is not None:
            embed.set_image(url=file.url)
        else:
            embed.add_field(
                name="Attachment",
                value=f"[{file.filename}]({file.url})",
                inline=False,
            )

    embed.set_author(
        name=message.author.display_name,
        icon_url=message.author.avatar_url_as(format="png"),
    )
    embed.timestamp = message.created_at
    embed.color = star_gradient_color(stars)
    return content, embed


def get_star_row(original_id):
    cursor = database.cursor()
    cursor.execute(
        """SELECT starboard_channel, starboard_id FROM stars WHERE original_id=?""",
        (original_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    return row


def get_starboard_id(original_channel):
    guild_config = config["guilds"][original_channel.guild.id]
    overrides = guild_config.get("starboard_overrides", {})
    default = guild_config["starboard_default"]
    return (
        overrides.get(original_channel.id)
        or overrides.get(original_channel.category_id)
        or default
    )


def get_all_starboards(guild_id):
    guild_config = config["guilds"][guild_id]
    overrides = guild_config.get("starboard_overrides", {})
    default = guild_config["starboard_default"]
    return {default, *overrides.values()}


def get_star_emojis(guild_id):
    guild_config = config["guilds"][guild_id]
    return guild_config.get("emojis", DEFAULT_EMOJIS)


async def action(payload, row):
    original_channel = bot.get_channel(payload.channel_id)
    if not isinstance(original_channel, discord.TextChannel):
        return

    guild_config = config["guilds"][original_channel.guild.id]
    if guild_config is None:
        return

    threshold = guild_config.get("threshold", DEFAULT_THRESHOLD)
    star_emojis = get_star_emojis(original_channel.guild.id)

    count = 0
    try:
        original_message = await original_channel.fetch_message(payload.message_id)
        for reaction in original_message.reactions:
            emoji = (
                reaction.emoji if isinstance(reaction.emoji, str) else reaction.emoji.id
            )
            if emoji in star_emojis:
                count += reaction.count
    except discord.errors.NotFound:
        original_message = None

    cursor = database.cursor()
    if row is not None:
        try:
            message = await bot.get_channel(row[0]).fetch_message(row[1])

            if count >= threshold:
                content, embed = get_emoji_message(original_message, count)

                await message.edit(content=content, embed=embed)
            else:
                cursor.execute(
                    """DELETE FROM stars WHERE original_id=?""",
                    (payload.message_id,),
                )
                await message.delete()
        except discord.errors.NotFound:
            cursor.execute(
                """DELETE FROM stars WHERE original_id=?""", (payload.message_id,)
            )
    elif (
        payload.channel_id not in get_all_starboards(payload.guild_id)
        and count >= threshold
    ):
        content, embed = get_emoji_message(original_message, count)
        starboard_channel = bot.get_channel(get_starboard_id(original_channel))
        message = await starboard_channel.send(content, embed=embed)

        cursor.execute(
            """INSERT INTO stars (
                original_id,
                starboard_channel,
                starboard_id
            ) VALUES (?, ?, ?)""",
            (payload.message_id, starboard_channel.id, message.id),
        )
    database.commit()
    cursor.close()


@bot.event
async def on_ready():
    log.info(f"Connected to Discord as {bot.user}")


async def handle_message_change(payload):
    row = get_star_row(payload.message_id)
    if row is None:
        return
    await action(payload, row)


@bot.event
async def on_raw_message_delete(payload):
    await handle_message_change(payload)


@bot.event
async def on_raw_message_edit(payload):
    await handle_message_change(payload)


@bot.event
async def on_raw_reaction_clear(payload):
    await handle_message_change(payload)


async def handle_reaction_remove(payload):
    if payload.emoji.name not in get_star_emojis(payload.guild_id):
        return
    row = get_star_row(payload.message_id)
    if row is None:
        return
    await action(payload, row)


@bot.event
async def on_raw_reaction_clear_emoji(payload):
    await handle_reaction_remove(payload)


@bot.event
async def on_raw_reaction_remove(payload):
    await handle_reaction_remove(payload)


@bot.event
async def on_raw_reaction_add(payload):
    if payload.emoji.name in get_star_emojis(payload.guild_id):
        await action(payload, get_star_row(payload.message_id))


if __name__ == "__main__":
    start_bot()
