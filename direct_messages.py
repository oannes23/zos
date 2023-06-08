import discord
import yaml
import concurrent.futures
import asyncio
import bot_utils
from collections import defaultdict
from langchain.memory import ConversationSummaryBufferMemory
from langchain.chat_models import ChatOpenAI
from langchain.chains import ConversationChain

class DirectMemory:
    def __init__(self):
        # Read keys from YAML file
        keys = bot_utils.load_yaml("keys.yml")
        self.openai_api_key = keys["openai_api_key"]
        self.memory_llm = ChatOpenAI(openai_api_key=self.openai_api_key, model="gpt-3.5-turbo-0301", temperature=0.1)
        self.talk_llm = ChatOpenAI(openai_api_key=self.openai_api_key, model="gpt-3.5-turbo-0301", temperature=0.3)
        self.conversations = {}

    async def chat(self, message):
        conversation = self.conversations.get(message.author.name)

        if not conversation:
            memory_buffer = ConversationSummaryBufferMemory(llm=self.memory_llm, 
                max_token_limit=3000, 
                human_prefix=message.author.name,
                ai_prefix="Zos")
            self.conversations[message.author.name] = ConversationChain(llm=self.talk_llm, memory=memory_buffer, verbose=False)
        
        print(f"{message.author.name} to Zos in DM: {message.content}")
        response = self.conversations[message.author.name].predict(input=f"{message.content}")
        print(f"Zos to {message.author.name} in DM: {response}")
        print(f"Summary {message.author.name} in DM: {self.conversations[message.author.name].memory.moving_summary_buffer}")
        await message.channel.send(f"{response}")
