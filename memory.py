import os
import bot_utils
from itertools import combinations
from collections import defaultdict

class Memory:
    def __init__(self):
        self.short_term_memory = []
        self.memories_dir = 'memories'

    def add_message(self, message):
        self.short_term_memory.append(message)

    def get_short_term_memory(self):
        return self.short_term_memory

    async def process_messages(self, bot):
        self.memory_subjects = self.categorize_memories(self.short_term_memory)

        for message in self.short_term_memory:
            formatted_timestamp = bot_utils.format_timestamp(message.created_at)
            print(f"{formatted_timestamp} #{message.channel.name} @{message.author.name}: {message.content}")
            this_message = f"#{message.channel.name} @{message.author.name}: {message.content}\n"

        for subject in self.memory_subjects:
            print(f"Processing subject: {subject}")
            perspective = self.set_perspective(subject)
            information = await bot_utils.extract_information(bot, subject, self.short_term_memory)
            await self.process_memory(subject, perspective, information)

        self.short_term_memory.clear()

    def set_perspective(self, subject):
        perspective = None

        if subject.startswith("channel-"):
            perspective = "Pretend you are a reader attempting to figure out what the current conversation " \
            "that is in progress is about. Phrase your SYNTHESIZE in a neutral, factual description of " \
            "the subject of conversation in the chat you are analyzing."
        elif subject.startswith("person-"):
            perspective = "Pretend you are an empathic, insightful person paying close attention to what this " \
            "person is saying and trying to build a profile on them. Keep in mind their word choice, vocabulary, " \
            "volunteering of biographical details, and perceived emotional state. DO NOT WRITE A RESPONSE TO THEM. " \
            "Instead, first write a one sentence summary of the speaker's name (starts with an @), " \
            "and infer their personality, and social and mental traits. Then add a biographical section after " \
            "that summarizes and incorporates anything you have learned about them that they said in their messages."

        return perspective

    def categorize_memories(self, messages):
        categories = set()
        channel_users = defaultdict(set)

        for message in messages:
            categories.add(f"channel-{message.channel.name}")
            # categories.add(f"person-{message.author.name}")

            # Add the author to the set of users for the channel
            # channel_users[message.channel.name].add(message.author.name)

        # Add interactions for each pair of users in each channel
        # categories.update(
        #    f"interaction-{'-'.join(sorted([user1, user2]))}"
        #    for users in channel_users.values()
        #    for user1, user2 in combinations(users, 2)
        # )


        return list(categories)


    async def process_memory(self, subject, perspective, information, tokens=500):
        try:
            current_memory = self.read_memory(subject)
        except FileNotFoundError:
            current_memory = "You have no current information on this topic, it's all new."

        context = [
            {"role": "user", "content": "Only respond by saying UNDERSTOOD until I tell you to SYNTHESIZE"},
            {"role": "assistant", "content": "UNDERSTOOD"},
            {"role": "user", "content": "The instructions I give after saying PERSPECTIVE " \
                "must be followed exactly and precisely."},
            {"role": "assistant", "content": "UNDERSTOOD"},
            {"role": "user", "content": "I will now repeat several CONTEXTs for you, each with different information. " \
                "You want to retain as much of this info as possible. " \
                "Be less focused on details to retain more breadth of knowledge. " \
                "LEARNED CONTEXT is usually more important than KNOWN CONTEXT " \
                "You will summarize this info in a factual, neutral tone when I tell you to SYNTHESIZE. " \
                "Make it as succint as possible while retaining as much info as possible. " \
                f"Keep this under {tokens} tokens in size."},
            {"role": "assistant", "content": "UNDERSTOOD"}
        ]

        context = bot_utils.add_context_instruction(context, [f"PERSPECTIVE: {perspective}"])
        context = bot_utils.add_context_instruction(context, [f"KNOWN CONTEXT: {current_memory}"])
        context = bot_utils.add_context_instruction(context, [f"LEARNED CONTEXT: {information}"])
        context = bot_utils.add_context_instruction(context, ["SYNTHESIZE"])

        new_memory = await bot_utils.gpt_call(context)

        if "An error occurred" not in new_memory:
            self.write_memory(subject, new_memory)

    def read_memory(self, filename):
        with open(os.path.join("memories", filename), "r") as file:
            content = file.read()
        return content

    def write_memory(self, filename, content):
        with open(os.path.join("memories", filename), "w") as file:
            file.write(content)

    def list_memories(self):
        """Lists all memory files in the 'memories' directory."""
        try:
            memories = [f for f in os.listdir(self.memories_dir) if os.path.isfile(os.path.join(self.memories_dir, f))]
            return memories
        except FileNotFoundError:
            print(f"'{self.memories_dir}' directory not found.")
            return []
        except Exception as e:
            print(f"An error occurred while listing memory files: {str(e)}")
            return []
