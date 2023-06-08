import discord
import os
import openai
import time
import asyncio
import talk
import summarize
import yaml
from direct_messages import DirectMemory
from memory import Memory
from bitd import BitD
from discord.ext import commands, tasks
from bot_utils import gpt_call, format_timestamp

# Read keys from YAML file
with open("keys.yml", "r") as file:
    keys = yaml.safe_load(file)

# Set up our runtime environment
discord_token = keys["discord_token"]
default_channel_id = keys["default_channel_id"]
intents = discord.Intents.all()
intents.typing = False

class MyBot(commands.Bot):
    def __init__(self, command_prefix, **options):
        super().__init__(command_prefix, **options)
        self.default_channel = None
        self.memory = Memory()
        self.bitd = BitD()
        self.dms = DirectMemory()

    async def on_ready(self):
        print(f'We have logged in as {bot.user}')
        self.default_channel = self.get_channel(int(default_channel_id))
        if self.default_channel:
            print(f'The default channel is: {self.default_channel.name}')
        else:
            print(f'Unable to retrieve default channel!')
        self.heartbeat.start()

    @tasks.loop(seconds=60)
    async def heartbeat(self):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} - Heartbeat")
        recent_messages = self.memory.get_short_term_memory()
        print(f"Recent messages: {recent_messages}")
        if recent_messages and self.default_channel:
            asyncio.create_task(self.memory.process_messages(self))
            asyncio.create_task(talk.process_messages(self, self.memory))

    async def on_message(self, message):
        formatted_timestamp = format_timestamp(message.created_at)
        if message.author.id == bot.user.id:
            return

        if isinstance(message.channel, discord.DMChannel):  # Check if the message is a Direct Message
            asyncio.create_task(self.dms.chat(message))
            return

        if message.content.startswith("!zos"):
            await self.process_commands(message)
            return

        if any(role.name == 'Bot Buddy' for role in message.author.roles):
            print(f"{formatted_timestamp} #{message.channel.name} @{message.author.name}: {message.content}")
        else:
            print(f"I am a good bot that respects the privacy of people that are not Bot Buddies")
            return
        self.memory.add_message(message)
        

bot = MyBot(command_prefix='!zos ', intents=intents)

@bot.command()
async def hello(ctx):
    await ctx.send('Hello World! This came from the !hello command')

@bot.command(name='memory')
async def get_memory(ctx, memory_name=None):
    if memory_name is None:
        # List memories
        memories = bot.memory.list_memories()
        await ctx.send(f"List of all Memories I have: {', '.join(memories)}")
    else:
        # Read a specific memory
        memory_content = bot.memory.read_memory(memory_name)
        await ctx.send(f"Memory '{memory_name}':\n {memory_content}")

@bot.command(name='bitd')
async def ask_bitd(ctx, *, question=None):
    if question is None:
        await ctx.send("Please ask a question about Blades in the Dark.")
        return
    asyncio.create_task(bot.bitd.ask_question(ctx, bot, question))

@bot.command(name='summarize')
async def summarize_link(ctx, *, link=None):
    if link is None:
        await ctx.send("Please provide a link to summarize.")
        return
    asyncio.create_task(summarize.summarize_link(ctx, bot, link))


@bot.command(name='chatty')
async def set_chattiness(ctx, value: int=None):
    if value is None:
        await ctx.send("You need to specify a value between 0 and 1000 for chattiness.")
        return
    if value < 0 or value > 1000:
        await ctx.send("The chattiness value must be between 0 and 1000.")
        return

    talk.set_chattiness_level(value)
    await ctx.send(f"Chattiness set to {value}")

bot.run(discord_token)
