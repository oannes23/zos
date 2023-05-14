import random
import discord
import bot_utils

chattiness_level = 50

def set_chattiness_level(value):
    global chattiness_level
    chattiness_level = value
    print(f"Chattiness set to: {chattiness}")

async def craft_message(memory, channel):
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
        ["Do not enclose your responses in quotes, or put your name at the beginning like " \
            "you are speaking in a chat room, just give the plain text of your response."])

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
            "Your response length should be roughly around the length of the average " \
            "message in your MESSAGES." \
            "When I tell you SYNTHESIZE, generate the chat message the character you " \
            "are playing would respond with, keeping in mind everything else I've said. " \
            "Only return plain text, no quotes or Zos: prepended to your message."])

    personal_context = memory.read_memory("self")
    context = bot_utils.add_context_instruction(context, [f"PERSPECTIVE: {personal_context}"])

    channel_context = memory.read_memory(f"channel-{channel}")
    context = bot_utils.add_context_instruction(context, [f"CHANNEL CONTEXT: {channel_context}"])

    short_term_memory = memory.get_short_term_memory()
    recent_messages = bot_utils.extract_information(f"channel-{channel}", short_term_memory)
    context = bot_utils.add_context_instruction(context, [f"MESSAGES: {recent_messages}"])

    for each_user in bot_utils.get_unique_users(short_term_memory):
        person_context = memory.read_memory(f"person-{each_user}")
        context = bot_utils.add_context_instruction(context, [f"{each_user.capitalize()} CONTEXT: {person_context}"])

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

    for msg in short_term_memories:
        # Get the channel associated with the memory
        channel_name = msg.channel.name

        # Get the channel probability, default to 1 if not found
        channel_probability = channel_probabilities.get(channel_name, 1)

        # Triple the channel probability if "Zos" is mentioned
        if 'Zos' in msg.content.lower():
            channel_probability *= 3

        # Calculate the probability of sending the message based on chattiness and channel_probability
        if random.randint(1, 1000) > chattiness_level * channel_probability:
            print(f"Message not sent to channel '{channel_name}' based on chattiness probability of {channel_probability}.")
            continue

        # Get the channel object based on the channel name
        channel = discord.utils.get(bot.get_all_channels(), name=channel_name)

        # Check if the channel is found
        if channel is None:
            print(f"Channel '{channel_name}' not found.")
            continue

        # Prepare the message
        message_content = await craft_message(memory, channel)

        # Send the message to the channel
        await channel.send(message_content)
