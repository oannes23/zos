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
            this_message = f"In channel #{message.channel.name} the user @{message.author.name} said: {message.content}\n"

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
            "that is in progress is about. Phrase your summmary of the CONTEXT given in a neutral, factual description of " \
            "the subject of conversation in the chat you are analyzing. You want to retain as much of this info as possible. " \
            "Make it as succint as possible while retaining as much info as possible."
        elif subject.startswith("personality-"):
            perspective = "Analyze the CONTEXT I have given above. Provide a list of 3 - 5 words that best describe " \
            "the CONTEXT from the following options: Joyful, Sad, Excited, Angry, Anxious, Calm, Pessimistic, Optimistic, " \
            "Introverted, Extroverted, Empathetic, Indifferent, Confident, Insecure, Aggressive, Passive, Humorous, " \
            "Serious, Impatient, Patient. For example, you might return the following: Humorous, Confident, Optimistic. " \
            "Remember, only return 3 - 5 words off of that list that describe the CONTEXT I gave above."
        elif subject.startswith("biography-"):
            perspective = "Analyze the CONTEXT and compile a list of biographical information they've " \
            "mentioned, including their background, preferences, interests, education, beliefs, and other factual " \
            "self-descriptions. Summarize each piece of information in the most concise way possible."

        return perspective

    def get_token_size(self, subject):
        tokens = None

        if subject.startswith("channel-"):
            tokens = 200
        elif subject.startswith("personality-"):
            tokens = 100
        elif subject.startswith("biography-"):
            tokens = 2000

        return tokens


    def categorize_memories(self, messages):
        categories = set()

        for message in messages:
            categories.add(f"channel-{message.channel.name}")
            categories.add(f"personality-{message.author.name}")
            categories.add(f"biography-{message.author.name}")

        return list(categories)


    def find_emotional_words(self, input_string):
        emotional_words = ['Joyful', 'Sad', 'Excited', 'Angry', 'Anxious', 'Calm', 'Pessimistic', 
                           'Optimistic', 'Introverted', 'Extroverted', 'Empathetic', 'Indifferent', 
                           'Confident', 'Insecure', 'Aggressive', 'Passive', 'Humorous', 'Serious', 
                           'Impatient', 'Patient']

        print(f"find_emotional_words input: {input_string}")
        try:
            words_so_far = self.read_memory("emotion-words")
        except FileNotFoundError:
            words_so_far = ""
        
        self.write_memory("emotion-words", f"{words_so_far}\n{input_string}")

        # Convert the input string to lower case, then split it into words
        words_in_input = input_string.lower().split()

        # Convert emotional_words list to lowercase for case-insensitive comparison
        emotional_words = [word.lower() for word in emotional_words]

        # Check for each word in words_in_input, if it is in emotional_words
        found_words = [word for word in words_in_input if word in emotional_words]

        # Convert found words list to comma-separated string
        found_words_str = ', '.join(found_words)

        print(f"find_emotional_words output: {found_words_str}")

        return found_words_str


    async def process_memory(self, subject, perspective, information, tokens=500):
        try:
            current_memory = self.read_memory(subject)
        except FileNotFoundError:
            current_memory = "You have no current information on this topic, it's all new."

        tokens = self.get_token_size(subject) or tokens

        context = []
        context = bot_utils.add_context_instruction(context, [f"Only respond by saying UNDERSTOOD for now."])
        context = bot_utils.add_context_instruction(context, [f"The instructions I give after saying PERSPECTIVE " \
            "must be followed exactly and precisely. Only respond by saying UNDERSTOOD until then."])
        context = bot_utils.add_context_instruction(context, [f"I will now repeat several CONTEXTs for you, " \
            "each with different information. You will use this information in your PERSPECTIVE instructions."])
        context = bot_utils.add_context_instruction(context, [f"Keep your response under {tokens} tokens in size."])
        context = bot_utils.add_context_instruction(context, [f"KNOWN CONTEXT: {current_memory}"])
        context = bot_utils.add_context_instruction(context, [f"LEARNED CONTEXT: {information}"])
        context = bot_utils.add_context_instruction(context, [f"PERSPECTIVE: {perspective}"])

        new_memory = await bot_utils.gpt_call(context)

        if subject.startswith("personality-"):
            self.find_emotional_words(new_memory)

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
