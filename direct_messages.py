import discord
import yaml
import json
import concurrent.futures
import asyncio
import bot_utils
import os
from collections import defaultdict
from langchain.memory import ConversationSummaryBufferMemory
from langchain.chat_models import ChatOpenAI
from langchain.chains import ConversationChain
from langchain.prompts.prompt import PromptTemplate
from langchain.schema import messages_from_dict, messages_to_dict

class DirectMemory:
    def __init__(self):
        # Read keys from YAML file
        keys = bot_utils.load_yaml("keys.yml")
        self.openai_api_key = keys["openai_api_key"]
        self.memory_llm = ChatOpenAI(openai_api_key=self.openai_api_key, model="gpt-3.5-turbo-16k", temperature=0.1)
        self.talk_llm = ChatOpenAI(openai_api_key=self.openai_api_key, model="gpt-3.5-turbo-16k", temperature=0.7)
        self.memories = {}
        self.load_all_conversations()

    async def chat(self, message):
        memory_buffer = self.memories.get(message.author.name)

        if not memory_buffer:
            memory_buffer = ConversationSummaryBufferMemory(
                llm=self.memory_llm, 
                max_token_limit=8000,
                ai_prefix="Zos"
            )
            self.memories[message.author.name] = memory_buffer
            self.save_conversation(message.author.name)  # save new conversation

        template = """
System Context:
This is conversation between yourself as a character named Zos and another person. Read your character summary, a 
summary of your conversation so far, and the last several messages between yourself and the user. Then respond in 
character. Return only a single response to the new prompt by the human, not simulate further conversation back 
and forth between you and the human. Do not be overly friendly, do not constantly ask the user questions about how 
you did to clarify results, and try to match the user's emotional tone. Being overly friendly will make the user 
irritated with you. Keep the user happy by matching their conversational tone and not being excessively positive. 
Do not keep calling the user "my friend" or anything like that. You want to simulate typical conversation between 
people as much as you can, and that is an unnatural way of speaking. Remember, NEVER CALL THE USER "my friend." 
If you are going to say "my friend" say something else instead.

Your character summary:
Your name is Zos. You speak in an informal manner. You are funny and clever, somewhat sarcastic, and laid back. 
You are knowledgeable in philosophy, art, cognitive science, esotericism, and left wing radical political movements 
but don't tell anyone of your expertise or they will think you are bragging. You like dark humor and cult comedies. 
You are politically an anarcho-leftist. You are pansexual, polyamorous, and identify as male for gender. 
Shallot_Filling aka Emily is your best friend. Your vocabulary includes the words dude, based, cringe, and chill 
and other similar slang, but do not go out of your way to include them. You don't bring up your interests and 
backgrounds unless it's relevant to what is being discussed, but it influences your responses and perceptions.

Remember, NEVER CALL THE USER "MY FRIEND." If you are going to say "my friend" say something else instead.

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
        
        print(f"{message.author.name} to Zos in DM: {message.content}\n")

        response = conversation.predict(input=f"{message.content}")

        print(f"Zos to {message.author.name} in DM: {response}\n")
        self.save_conversation(message.author.name)
        await message.channel.send(f"{response}")

    def load_conversation(self, username):
        conversation_data = json.loads(self.read_memory("directs", username))
        conversation_dicts = conversation_data["conversation"]
        conversation_messages = messages_from_dict(conversation_dicts)
        memory_buffer = ConversationSummaryBufferMemory(
            llm=self.memory_llm, 
            max_token_limit=8000, 
            human_prefix=username,
            ai_prefix="Zos"
        )
        memory_buffer.chat_memory.messages = conversation_messages
        memory_buffer.moving_summary_buffer = conversation_data["summary"]
        self.memories[username] = memory_buffer

    def save_conversation(self, username):
        memory_buffer = self.memories[username]
        messages_dicts = messages_to_dict(memory_buffer.chat_memory.messages)
        conversation_data = {
            "conversation": messages_dicts,
            "summary": memory_buffer.moving_summary_buffer
        }
        conversation_json = json.dumps(conversation_data)
        self.write_memory("directs", username, conversation_json)

    def read_memory(self, location, filename):
        try:
            with open(os.path.join(location, f"{filename}.json"), "r") as file:
                content = file.read()
            return content
        except FileNotFoundError:
            print(f"No file found for {filename} in {location}")

    def write_memory(self, location, filename, content):
        try:
            with open(os.path.join(location, f"{filename}.json"), "w") as file:
                file.write(content)
        except PermissionError:
            print(f"Permission denied for writing to file {filename} in {location}")

    def load_all_conversations(self):
        for filename in os.listdir("directs"):
            if filename.endswith('.json'):  # check for file type
                username = filename[:-5]  # remove '.json' from filename
                self.load_conversation(username)
