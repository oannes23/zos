import discord
import yaml
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
		self.bitd_docs = Chroma(persist_directory="chromadb", embedding_function=OpenAIEmbeddings(openai_api_key=self.openai_api_key))


	async def ask_question(self, bot, question):
		print(f"BitD Question: {question}")
		relevant_info = self.bitd_docs.similarity_search(question)

		print (f'You have {len(relevant_info)} document(s)')
		num_words = sum([len(doc.page_content.split(' ')) for doc in relevant_info])
		print (f'You have roughly {num_words} words in your docs')
		print ()
		print (f'Preview: \n{relevant_info[0].page_content.split(". ")[0]}')

		chain = load_qa_chain(llm=ChatOpenAI(openai_api_key=self.openai_api_key), chain_type="stuff")
		results = chain({"input_documents": relevant_info, "question": question}, return_only_outputs=True)
		message_content = results['output_text']

		# Send the message to the channel
		return message_content

