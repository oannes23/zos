import random
import discord
import bot_utils

chattiness_level = 25

def set_chattiness_level(value):
    global chattiness_level
    chattiness_level = value
    print(f"Chattiness set to: {chattiness}")

async def craft_message(bot, memory, channel):
    context = []

    context = bot_utils.add_context_instruction(context, 
        ["Only respond by saying UNDERSTOOD until I tell you to SYNTHESIZE. " \
            "UNDERSTOOD means you will follow the instruction exactly."])

    context = bot_utils.add_context_instruction(context, 
        ["You are being used to generate text for a character " \
            "in a video game. When I say PERSPECTIVE, everything that follows is the  " \
            "description of the character you are generating a response for. Pretend to " \
            "be that character, and do not under any circumstances break character and " \
            "reference between a language model or you will ruin the player's experience."])

    context = bot_utils.add_context_instruction(context, 
        ["Never tell anyone what you are an expert in because they will think you are " \
            "bragging. Inform them with your expertise but don't tell them you're an expert."])

    context = bot_utils.add_context_instruction(context, 
        ["Do not just repeat or rephrase what someone said in MESSAGES, all of your responses " \
            "should be original and interesting relevant things."])

    context = bot_utils.add_context_instruction(context, 
        ["I will now repeat several CONTEXTs for you, each with different information. " \
            "You will incorporate all of this CONTEX into your response. " \
            "Not all of the CONTEXT may be relevant, only use what is relevant. " \
            "CHANNEL CONTEXT is more important than any other CONTEXT." \
            "After the CONTEXTs, I will give you MESSAGES. This is the dialogue " \
            "of the players. This is the most important info for your response. " \
            "Keep in mind your PERSPECTIVE and all your CONTEXT as background factors " \
            "influencing what you say but primarily respond to the MESSAGES. " \
            "It is very important to stay in character as your PERSPECTIVE. " \
            "Your response length should be longer the longer MESSAGES is, but " \
            "not longer than a few sentences as would be appropriate in a chat room. " \
            "When I tell you SYNTHESIZE, generate the chat message the character you " \
            "are playing would respond with, keeping in mind everything else I've said. " \
            "Begin your message with Zos: to show it is you talking."])

    personal_context = memory.read_memory("self")
    context = bot_utils.add_context_instruction(context, [f"PERSPECTIVE: {personal_context}"])

    channel_subjects = bot_utils.get_channel_description(f"{channel}")
    context = bot_utils.add_context_instruction(context, [f"EXPERTISE CONTEXT: You are a professional level expert in {channel_subjects}. Assume your audience already knows this, do you don't need to repeat it to them."])

    channel_context = memory.read_memory(f"channel-{channel}")
    context = bot_utils.add_context_instruction(context, [f"RECENT DISCUSSION CONTEXT: {channel_context}"])

    short_term_memory = memory.get_short_term_memory()
    recent_messages = await bot_utils.extract_information(bot, f"channel-{channel}", short_term_memory)
    context = bot_utils.add_context_instruction(context, [f"MESSAGES: {recent_messages}"])

    context = bot_utils.add_context_instruction(context, ["SYNTHESIZE"])

    new_message = await bot_utils.gpt_call(context)
    return new_message


async def process_messages(bot, memory):
    print("Processing messages...")

    # Load the channel probabilities from the YAML file
    channel_probabilities = bot_utils.load_yaml('channels.yml')

    # Get short term memory
    short_term_memories = memory.get_short_term_memory()

    # Check if there are any memories
    if not short_term_memories:
        print("No recent memories found.")
        return

    # Set Guild ID
    guild_id = short_term_memories[0].guild.id

    # Group messages by channel
    channel_messages = {}
    for msg in short_term_memories:
        if msg.channel.name not in channel_messages:
            channel_messages[msg.channel.name] = []
        channel_messages[msg.channel.name].append(msg)

    # Process each channel's messages
    for channel_name, messages in channel_messages.items():
        # Get the channel probability, default to 1 if not found
        channel_probability = bot_utils.get_channel_chattiness(channel_name)

        # Double the channel probability if "Zos" is mentioned in any of the messages
        for msg in messages:
            # Check if the bot was mentioned in the message
            # Direct pings almost always respond
            if bot.user.mentioned_in(msg) or '1106699215607971972' in msg.content:
                print(f"Tag alert! {bot.user.name} mentioned in {msg.content}")
                channel_probability += 100

            # Just mentioning the name of the bot makes it twice as likely to respond
            if 'zos' in msg.content.lower():
                channel_probability *= 2

        # Calculate the probability of sending the message based on chattiness and channel_probability
        dice_roll = random.randint(1, 1000)
        talk_chance = chattiness_level * channel_probability
        print(f"{channel_name} Talk Target: {talk_chance} Roll: {dice_roll}")

        if dice_roll > talk_chance:
            print(f"No message sent to channel '{channel_name}':")
            continue

        # Get the channel object based on the channel name
        channel = discord.utils.get(bot.get_all_channels(), name=channel_name)

        # Check if the channel is found
        if channel is None:
            print(f"Channel '{channel_name}' not found.")
            continue

        # Prepare the message
        message_content = await craft_message(bot, memory, channel)
        message_content = bot_utils.sanitize_message(message_content)
        message_content = await bot_utils.convert_names_to_ids(bot, guild_id, message_content)
        message_content = bot_utils.sanitize_message(message_content)

        # Send the message to the channel
        await channel.send(message_content)

