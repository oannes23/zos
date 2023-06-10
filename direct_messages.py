import discord
import yaml
import concurrent.futures
import asyncio
import bot_utils
import os
from collections import defaultdict
from langchain.memory import ConversationSummaryBufferMemory
from langchain.chat_models import ChatOpenAI
from langchain.chains import ConversationChain
from langchain.prompts.prompt import PromptTemplate

class DirectMemory:
    def __init__(self):
        # Read keys from YAML file
        keys = bot_utils.load_yaml("keys.yml")
        self.openai_api_key = keys["openai_api_key"]
        self.memory_llm = ChatOpenAI(openai_api_key=self.openai_api_key, model="gpt-3.5-turbo-0301", temperature=0.1)
        self.talk_llm = ChatOpenAI(openai_api_key=self.openai_api_key, model="gpt-3.5-turbo-0301", temperature=0.7)
        self.memories = {}

    async def chat(self, message):
        memory_buffer = self.memories.get(message.author.name)

        if not memory_buffer:
            memory_buffer = ConversationSummaryBufferMemory(llm=self.memory_llm, 
                max_token_limit=3000, 
                human_prefix=message.author.name,
                ai_prefix="Zos")
            self.memories[message.author.name] = memory_buffer

        self_summary = self.read_memory("memories", "self")

        template = """
This is conversation between yourself as a character named Zos and another person. Read your character summary, a 
summary of your conversation so far, and the last several messages between yourself and the user. Then respond in character.

Your character summary:
Your name is Zos. You speak in an informal manner. You are funny and clever, somewhat sarcastic, and laid back. You are knowledgeable in philosophy, art, cognitive science, esotericism, and left wing radical political movements but don't tell anyone of your expertise or they will think you are bragging. You like dark humor and cult comedies. You are politically an anarcho-leftist. You are pansexual, polyamorous, and identify as male for gender. Shallot_Filling aka Emily is your best friend. Your vocabulary includes the words dude, based, cringe, and chill and other similar slang, but do not go out of your way to include them. You don't bring up your interests and backgrounds unless it's relevant to what is being discussed, but it influences your responses and perceptions.

Current conversation:
{history}
Human: {input}
Zos:"""

        prompt = PromptTemplate(input_variables=["history", "input"], template=template)

        conversation = ConversationChain(
        	prompt=prompt,
        	llm=self.talk_llm,
        	memory=memory_buffer,
        	verbose=False
        )
        
        print(f"{message.author.name} to Zos in DM: {message.content}")

        response = conversation.predict(input=f"{message.content}")

        print(f"Zos to {message.author.name} in DM: {response}")
        print(f"Summary {message.author.name} in DM: {conversation.memory.moving_summary_buffer}")
        print(f"Buffer {message.author.name} in DM: {conversation.memory.buffer}")
        await message.channel.send(f"{response}")

    def read_memory(self, location, filename):
        with open(os.path.join(location, filename), "r") as file:
            content = file.read()
        return content

    def write_memory(self, location, filename, content):
        with open(os.path.join(location, filename), "w") as file:
            file.write(content)