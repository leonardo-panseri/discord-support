import asyncio
import logging
from threading import Timer

import discord
from configobj import ConfigObj

logging.basicConfig(level=logging.INFO)
prefix = "?"


class SupportClient(discord.Client):
    messages = dict()
    users = dict()
    channels = dict()
    cooldown = list()

    def __init__(self, **options):
        self.cfg = ConfigObj('config.ini', list_values=False, encoding='utf8')

        super().__init__(**options)

    async def on_ready(self):
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,
                                                             name="Scrivimi un messaggio privato per aprire un ticket"))

    async def on_message(self, message: discord.Message):
        if not message.author.bot and isinstance(message.channel, discord.DMChannel):
            if message.author.id in self.cooldown:
                embed_cfg = self.cfg['CooldownEmbed']
                cd_embed = discord.Embed(colour=getattr(discord.Colour, embed_cfg['colour'])(),
                                         title=embed_cfg['title'], description=embed_cfg['description'])
                await message.channel.send(embed=cd_embed)
                return

            if message.author.id in self.users:
                if self.users[message.author.id] is None:
                    embed_cfg = self.cfg['IncompleteEmbed']
                    incomplete_embed = discord.Embed(colour=getattr(discord.Colour, embed_cfg['colour'])(),
                                                     title=embed_cfg['title'], description=embed_cfg['description'])
                    await message.channel.send(embed=incomplete_embed)
                else:
                    try:
                        ticket_channel = await self.fetch_channel(self.users[message.author.id])
                    except discord.NotFound:
                        self.channels.__delitem__(self.users[message.author.id])
                        self.users.__delitem__(message.author.id)
                        logging.warning("Support channel deletion was not handled correctly")
                        return

                    embed_cfg = self.cfg['LimitEmbed']
                    limit_embed = discord.Embed(colour=getattr(discord.Colour, embed_cfg['colour'])(),
                                                title=embed_cfg['title'], description=embed_cfg['description'].
                                                format(ticket=ticket_channel.mention))
                    await message.channel.send(embed=limit_embed)
            else:
                self.users[message.author.id] = None

                embed_cfg = self.cfg['ConfirmEmbed']
                confirm_embed = discord.Embed(colour=getattr(discord.Colour, embed_cfg['colour'])(),
                                              title=embed_cfg['title'], description=embed_cfg['description'])
                confirm_msg = await message.channel.send(embed=confirm_embed)
                self.messages[confirm_msg.id] = message.content
                await self.add_reactions(confirm_msg)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.user.id:
            return

        channel = await self.fetch_channel(payload.channel_id)

        if isinstance(channel, discord.DMChannel) and payload.message_id in self.messages:
            user = channel.recipient
            msg = await channel.fetch_message(payload.message_id)
            if payload.emoji.name == '❌':
                await self.remove_reactions(msg)
                self.messages.__delitem__(payload.message_id)
                self.users.__delitem__(user.id)

                delete_embed_cfg = self.cfg['DeleteEmbed']
                delete_embed = discord.Embed(colour=getattr(discord.Colour, delete_embed_cfg['colour'])(),
                                             title=delete_embed_cfg['title'],
                                             description=delete_embed_cfg['description'])
                await msg.edit(embed=delete_embed)
            elif payload.emoji.name == '✅':
                self.cooldown.append(user.id)
                timer = Timer(60, lambda member_id: self.cooldown.remove(member_id), [user.id])
                timer.start()
                await self.remove_reactions(msg)
                content = self.messages[payload.message_id]
                self.messages.__delitem__(payload.message_id)

                guild: discord.Guild = self.get_guild(int(self.cfg['guild_id']))
                category: discord.CategoryChannel = guild.get_channel(int(self.cfg['category_id']))
                member = await guild.fetch_member(payload.user_id)

                overwrites = category.overwrites
                overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                private_channel: discord.TextChannel = await category.create_text_channel(
                    self.cfg['channel_title'].format(username=user.name),
                    overwrites=overwrites)

                await private_channel.send(self.cfg['tag'].format(user=user.mention))
                content_embed_cfg = self.cfg['SupportEmbed']
                content_embed = discord.Embed(colour=getattr(discord.Colour, content_embed_cfg['colour'])(),
                                              title=content_embed_cfg['title'].format(username=user.name),
                                              description=content_embed_cfg['description'].
                                              format(content=content).replace('\\n', '\n'))
                ticket = await private_channel.send(embed=content_embed)
                await ticket.add_reaction('❌')

                self.channels[private_channel.id] = user.id
                self.users[user.id] = private_channel.id

                embed_cfg = self.cfg['ConfirmEmbed']
                confirmed_embed = discord.Embed(colour=getattr(discord.Colour, embed_cfg['confirmed_colour'])(),
                                                title=embed_cfg['confirmed_title'],
                                                description=embed_cfg['confirmed_description'].
                                                format(channel=private_channel.mention))
                await msg.edit(embed=confirmed_embed)
        elif isinstance(channel, discord.TextChannel) and channel.category is not None \
                and channel.category.id == int(self.cfg['category_id']):
            member: discord.Member = await channel.guild.fetch_member(payload.user_id)
            role: discord.Role = channel.guild.get_role(int(self.cfg['support_role']))
            if payload.emoji.name == '❌' and role in member.roles:
                if channel.id in self.channels:
                    await channel.delete()
                    user = await self.fetch_user(self.channels[channel.id])

                    self.channels.__delitem__(channel.id)
                    self.users.__delitem__(user.id)

                    embed_cfg = self.cfg['CloseEmbed']
                    close_embed = discord.Embed(colour=getattr(discord.Colour, embed_cfg['colour'])(),
                                                title=embed_cfg['title'],
                                                description=embed_cfg['description'])
                    await user.send(embed=close_embed)
                else:
                    await channel.delete()

    async def add_reactions(self, msg):
        tasks = [asyncio.ensure_future(msg.add_reaction('❌')), asyncio.ensure_future(msg.add_reaction('✅'))]
        await asyncio.wait(tasks)

    async def remove_reactions(self, msg):
        tasks = [asyncio.ensure_future(msg.remove_reaction('❌', self.user)),
                 asyncio.ensure_future(msg.remove_reaction('✅', self.user))]
        await asyncio.wait(tasks)


client = SupportClient()
client.run(client.cfg['Token'])
