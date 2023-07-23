import openai
import asyncio
import discord
import concurrent.futures
import time
import yaml

# Read keys from YAML file
with open("keys.yml", "r") as file:
    keys = yaml.safe_load(file)

openai.api_key = keys["openai_api_key"]

def add_context_instruction(context, instructions, include_assistant=True):
    for instruction in instructions:
        context.append({"role": "user", "content": f"{instruction}"})
        if include_assistant and instruction != "SYNTHESIZE":
            context.append({"role": "assistant", "content": "Understood."})
    return context


async def convert_names_to_ids(bot, guild_id, message):
    bot_buddies = await get_bot_buddies(bot, guild_id)

    for member in bot_buddies:
        if member.name in message:
            message = message.replace(member.name, f"<@{member.id}>")
    return message


async def convert_ids_to_names(bot, guild_id, message):
    bot_buddies = await get_bot_buddies(bot, guild_id)

    for member in bot_buddies:
        if str(member.id) in message:
            message = message.replace(f"<@{member.id}>", member.name)
    return message


async def extract_information(bot, subject, messages):
    prefix, value = subject.split("-", 1)
    relevant_messages = []
    guild_id = None

    for message in messages:
        # Extract the guild ID from the message
        if guild_id is None:
            guild_id = message.guild.id

        # Get the message content and convert IDs to names
        content = await convert_ids_to_names(bot, guild_id, message.content)

        # If the prefix is 'channel', we check if the channel name matches the value
        if prefix == 'channel' and message.channel.name == value:
            relevant_messages.append(f"@{message.author.name} said: {content}")

        # If the prefix is 'personality' or 'biography', we check if the author's name matches the value
        elif prefix in ['personality', 'biography'] and message.author.name == value:
            relevant_messages.append(f"@{message.author.name} said: {content}\n")


    return "\n".join(relevant_messages)


def format_timestamp(timestamp):
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


async def get_bot_buddies(bot, guild_id):
    guild = bot.get_guild(guild_id)
    bot_buddy_role = discord.utils.get(guild.roles, name="Bot Buddy")

    if bot_buddy_role:
        return bot_buddy_role.members

    return []


def get_channel_chattiness(channel_name):
    channel_list = load_yaml('channels.yml')
    channel_info = channel_list.get(channel_name, {})
    print(f"Channel name: {channel_name} Channel Info: {channel_info}")
    return channel_info.get('chattiness', 1)


def get_channel_description(channel_name):
    channel_list = load_yaml('channels.yml')
    channel_info = channel_list.get(channel_name, {})
    print(f"Channel name: {channel_name} Channel Info: {channel_info}")
    return channel_info.get('description', '')


def get_unique_users(messages):
    unique_users = set()
    
    return list({message.author.name for message in messages})


def gpt3_call_sync(context):
    return openai.ChatCompletion.create(
        model="gpt-3.5-turbo-16k",
        messages=context
    )


async def gpt_call(context):
    loop = asyncio.get_event_loop()
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            response = await loop.run_in_executor(pool, gpt3_call_sync, context)
    except Exception as e:
        error_message = f"An error occurred while making the API call: {str(e)}"
        print(error_message)
        return error_message  # return the error message

    # Get the generated response from OpenAI
    generated_message = response.choices[0].message['content']
    token_usage = response['usage']['total_tokens']
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    return generated_message


def load_yaml(file_path):
    with open(file_path, 'r') as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)

def sanitize_message(text):
    if text.startswith("Zos: "):
        return text[5:]
    if text.startswith("<@1106699215607971972>: "):
        return text[24:]
    text = text.replace("@@", "@")
    text = text.replace("@<@", "<@")
    return text
