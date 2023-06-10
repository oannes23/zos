import discord
import yaml
import concurrent.futures
import asyncio
from langchain.callbacks import get_openai_callback
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.chat_models import ChatOpenAI
from langchain.chains.question_answering import load_qa_chain
from langchain.vectorstores import Chroma

class BitD:
	def __init__(self):
		# Read keys from YAML file
		with open("keys.yml", "r") as file:
			keys = yaml.safe_load(file)
		self.openai_api_key = keys["openai_api_key"]
		self.bitd_docs = Chroma(persist_directory="bitd_db", embedding_function=OpenAIEmbeddings(openai_api_key=self.openai_api_key))
		self.executor = concurrent.futures.ThreadPoolExecutor()


	async def ask_question(self, ctx, bot, question):
		print(f"BitD Question: {question}")
		llm = ChatOpenAI(openai_api_key=self.openai_api_key,model="gpt-3.5-turbo-0301",temperature=0.3)
		with get_openai_callback() as cb:
			relevant_info = self.bitd_docs.similarity_search(question)
			loop = asyncio.get_event_loop()
			chain = await loop.run_in_executor(self.executor, load_qa_chain, llm, "stuff")
				
			results = await loop.run_in_executor(self.executor, chain, {"input_documents": relevant_info, "question": question}, True)
			print(f"{cb}\n")
			# Send the message to the channel
			message_content = results['output_text']
			await ctx.send(f"{message_content}")
