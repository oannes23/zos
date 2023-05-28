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
            perspective = "Analyze the LEARNED CONTEXT I have given above. Decide on a list of 3 - 5 words that best describe " \
            "the emotional state and conversational tone of the user that stated the LEARNED CONTEXT from the following options: " \
            "Active, Alert, Amused, Angry, Anxious, Apathetic, Caring, Casual, " \
            "Cautious, Challenging, Comical, Concerned, Confident, Confused, Considerate, Constructive, Critical, Dismissive, " \
            "Dramatic, Excited, Focused, Formal, Friendly, Frustrated, Guilty, Injured, Insecure, Inquisitive, Introverted, " \
            "Ironic, Light-hearted, Lonesome, Lucid, Mysterious, Open-minded, Pessimistic, Recovering, Relaxed, Responsible, " \
            "Retrospective, Serious, Shocked, Suspicious, Thoughtful, Time-sensitive, Transitioning, Useful.\n" \
            "Once you have done that, look at the KNOWN CONTEXT. For each word you decided describes the LEARNED CONTEXT, " \
            "if the word is not on the KNOWN CONTEXT list add it to the bottom with the number 1 next to it. " \
            "If the word is already on the KNOWN CONTEXT list add +1 to the number next to the word on the list. " \
            "Then return the KNOWN CONTEXT list, with the changes you have made above. You should only return a list " \
            "of some of the above words with numbers next to each one, on a new line. Remove anything else from your " \
            "response.\n" \
            "Follow this example.\n " \
            "Example KNOWN CONTEXT input: \n" \
            "```\n" \
            "Caring 10\n" \
            "Friendly 8\n" \
            "Amused 5\n" \
            "Active 2\n " \
            "Lucid 2\n" \
            "Relaxed 1\n" \
            "```\n" \
            "Example LEARNED CONTEXT input: \n" \
            "```\n" \
            "Example_User said: I like cats. I had a cat named Joey when I was five. It was my favorite " \
            "color, orange.\n " \
            "Example_User said: That was thirty years ago now!\n" \
            "Example_User said: By the way, I use she/her pronouns\n" \
            "Example_User said: I'm going to breakfast now\n" \
            "Example_user said: I will be back later!\n" \
            "```\n" \
            "From this you may decide the user sounds Casual, Open-minded, Friendly, Retrospective, Relaxed. \n" \
            "You would not actually return that as a response. \n" \
            "Instead you would then update the KNOWN CONTEXT as follows:\n"
            "```\n" \
            "Caring 10\n" \
            "Friendly 9\n" \
            "Amused 5\n" \
            "Active 2\n " \
            "Lucid 2\n" \
            "Relaxed 2\n" \
            "Casual 1\n" \
            "Retrospective 1\n" \
            "```\n" \
            "Notice how in the example nothing was returned that was not on the list of options given. Notice that the " \
            "options already existing on the KNOWN CONTEXT list had their number increased by 1. Notice that the ones " \
            "not already appearing on the list were added with the number 1 next to them.\n" \
            "Now, following this example, analyze the LEARNED CONTEXT and combine it with the KNOWN CONTEXT " \
            "and return the list you have updated. Order the list first by the number next to each word with the  " \
            "highest number at the top, and second in alphabetical order for any ties. " \
            "Return no other text except the list of words and numbers."
        elif subject.startswith("biography-"):
            perspective = "Analyze the LEARNED CONTEXT and compile a list of facts about the speaker they've " \
            "mentioned about themselves such as preferences, backgrounds, and beliefs. " \
            "Join this with the KNOWN CONTEXT to create a unified list of bullet points. " \
            "Be as concise in these bullet points as possible, including not using complete sentences. " \
            "If the user does not state anything about themselves, do not include information just about " \
            "anything they say. Only include information the user says about their prefernces, traits, and history. " \
            "Follow this example.\n " \
            "Example input: \n" \
            "```\n" \
            "Example_User said: I like cats. I had a cat named Joey when I was five. It was my favorite " \
            "color, orange.\n " \
            "Example_User said: That was thirty years ago now!\n" \
            "Example_User said: By the way, I use she/her pronouns\n" \
            "Example_User said: I'm going to breakfast now\n" \
            "Example_user said: I will be back later!\n" \
            "```\n" \
            "Your example output: \n" \
            "```\n" \
            "- Name is Example_User \n" \
            "- she/her pronouns \n" \
            "- likes cats \n" \
            "- had a cat named Joey \n" \
            "- favorite color orange \n" \
            "- 35 years old \n" \
            "```\n" \
            "Notice how in the example nothing about going to breakfast and being back later was included, " \
            "because that information is not about the Example_User's preferences, personal traits or history.\n" \
            "Now, following this example, analyze the LEARNED CONTEXT and combine it with the KNOWN CONTEXT " \
            "and return the list of bullet points you have learned. If anything in the LEARNED CONTEXT contradicts " \
            "anything in the KNOWN CONTEXT, update it to the LEARNED CONTEXT. If there are any redundant points, " \
            "consolidate them into a single point. If there is no new information about the user themselves, then " \
            "just return the KNOWN CONTEXT unchanged. If there is too much information to fit within the token limit, " \
            "keep prioritize information that is more general such as pronouns, name, age, and broad preferences. " \
            "Return no other text except the bullet point list."

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
