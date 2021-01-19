import logging
import sqlite3
import yaml
import discord

STAR_EMOJI = ['\N{WHITE MEDIUM STAR}']
STARBOARD_THRESHOLD_DEFAULT = 3

class Stars(discord.Client):
  def __init__(self):
    super().__init__(
      intents=discord.Intents(
        guilds=True,
        messages=True,
        reactions=True
      )
    )

    self.log = logging.getLogger('bot')
    logging.basicConfig(level=logging.INFO)

    with open('config.yml') as conf_file:
      self.config = yaml.safe_load(conf_file)

    self.database = sqlite3.connect("stars.sqlite")
    self.database.row_factory = sqlite3.Row
    cursor = self.database.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS stars
                     (original_id INTEGER,
                      starboard_channel INTEGER,
                      starboard_id INTEGER,
                      guild_id INTEGER,
                      author INTEGER,
                      message_content TEXT)""")
    self.database.commit()
    cursor.close()

  @staticmethod
  def star_emoji(stars):
    if 5 > stars >= 0:
      return '\N{WHITE MEDIUM STAR}'
    elif 10 > stars >= 5:
      return '\N{GLOWING STAR}'
    elif 25 > stars >= 10:
      return '\N{DIZZY SYMBOL}'
    else:
      return '\N{SPARKLES}'

  @staticmethod
  def star_gradient_colour(stars):
    p = stars / 13
    if p > 1.0:
      p = 1.0

    red = 255
    green = int((194 * p) + (253 * (1 - p)))
    blue = int((12 * p) + (247 * (1 - p)))
    return (red << 16) + (green << 8) + blue

  def get_emoji_message(self, message, stars):
    emoji = self.star_emoji(stars)

    if stars > 1:
      content = f'{emoji} **{stars}** {message.channel.mention}'
    else:
      content = f'{emoji} {message.channel.mention}'

    embed = discord.Embed(description=f'{message.content}\n\n[Jump to original message](https://discord.com/channels/{message.channel.guild.id}/{message.channel.id}/{message.id})')
    if message.embeds:
      data = message.embeds[0]
      if data.type == 'image':
        embed.set_image(url=data.url)

    if message.attachments:
      file = message.attachments[0]
      if file.width is not None:
        embed.set_image(url=file.url)
      else:
        embed.add_field(
          name='Attachment',
          value=f'[{file.filename}]({file.url})', inline=False)

    embed.set_author(name=message.author.display_name,
             icon_url=message.author.avatar_url_as(format='png'))
    embed.timestamp = message.created_at
    embed.colour = self.star_gradient_colour(stars)
    return content, embed

  def start_bot(self):
    self.run(self.config['token'])

  async def on_ready(self):
    self.log.info(f'Connected to Discord as {self.user}')

  async def on_raw_message_delete(self, payload):
    cursor = self.database.cursor()
    cursor.execute("""SELECT * FROM stars
                      WHERE original_id=?""", (payload.message_id,))
    row = cursor.fetchone()

    if row is not None:
      try:
        message = await self.get_channel(row['starboard_channel']).fetch_message(row['starboard_id'])

        await message.delete()
      except discord.errors.NotFound:
        pass

      cursor.execute("""DELETE FROM stars
                        WHERE original_id=?""", (payload.message_id,))
      self.database.commit()
    cursor.close()

  async def on_raw_reaction_add(self, payload):
    if payload.emoji.name in STAR_EMOJI:
      await self.action(payload)

  async def on_raw_reaction_clear(self, payload):
    await self.action(payload)

  async def on_raw_reaction_remove(self, payload):
    if payload.emoji.name in STAR_EMOJI:
      await self.action(payload)

  def get_starboard_id(self, original_channel):
    guild_config = self.config['guilds'][original_channel.guild.id]
    category_maps = guild_config['category_starboards']
    default = guild_config['default_starboard']
    return category_maps.get(original_channel.category_id, default)

  def get_all_starboards(self, guild_id):
    guild_config = self.config['guilds'][guild_id]
    category_maps = guild_config['category_starboards']
    default = guild_config['default_starboard']
    return [default, *category_maps.values()]

  async def action(self, payload):
    original_channel = self.get_channel(payload.channel_id)
    if not isinstance(original_channel, discord.TextChannel) or original_channel.guild.id not in self.config['guilds']:
      return

    guild_config = self.config['guilds'][original_channel.guild.id]
    threshold = guild_config.get('threshold', STARBOARD_THRESHOLD_DEFAULT)

    original_message = await original_channel.fetch_message(payload.message_id)

    count = 0
    for i in original_message.reactions:
      if i.emoji in STAR_EMOJI:
        count = i.count
        break

    starboard_channel = self.get_channel(self.get_starboard_id(original_channel))

    cursor = self.database.cursor()
    cursor.execute("""SELECT * FROM stars
                      WHERE original_id=?""", (payload.message_id,))
    row = cursor.fetchone()

    if row:
      try:
        message = await starboard_channel.fetch_message(row['starboard_id'])

        if count >= threshold:
          content, embed = self.get_emoji_message(original_message, count)

          await message.edit(content=content, embed=embed)
        else:
          await message.delete()
          cursor.execute("""DELETE FROM stars
                            WHERE original_id=?""", (payload.message_id,))
      except discord.errors.NotFound:
        cursor.execute("""DELETE FROM stars
                          WHERE original_id=?""", (payload.message_id,))
    elif payload.channel_id not in self.get_all_starboards(payload.guild_id) and count >= threshold:
      content, embed = self.get_emoji_message(original_message, count)
      message = await starboard_channel.send(content, embed=embed)

      cursor.execute("""INSERT INTO stars
                       (original_id,
                        starboard_channel,
                        starboard_id,
                        guild_id,
                        author,
                        message_content)
                        VALUES (?, ?, ?, ?, ?, ?)""",
        (payload.message_id,
        starboard_channel.id,
        message.id,
        starboard_channel.guild.id,
        original_message.author.id,
        original_message.content))
      self.database.commit()
      cursor.close()

if __name__ == '__main__':
  Stars().start_bot()
