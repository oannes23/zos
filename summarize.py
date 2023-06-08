import yaml
import concurrent.futures
import asyncio
import requests
from bs4 import BeautifulSoup
from langchain.callbacks import get_openai_callback
from langchain.chat_models import ChatOpenAI
from langchain.chains.summarize import load_summarize_chain
from langchain.text_splitter import CharacterTextSplitter


async def get_html(ctx, url):
    try:
        response = requests.get(url)
        if response.status_code != 200:
            output = f"Failed to get page: {url}. Status code: {response.status_code}"
            print(output)
            await ctx.send(output)
            return None
        return response.text
    except requests.RequestException as e:
        output = f"An error occurred when trying to get {url}. Error: {str(e)}"
        print(output)
        await ctx.send(output)
        return None


def strip_html(text):
    soup = BeautifulSoup(text, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()
    return soup.get_text()


async def summarize_link(ctx, bot, link):
    with open("keys.yml", "r") as file:
        keys = yaml.safe_load(file)
    openai_api_key = keys["openai_api_key"]
    executor = concurrent.futures.ThreadPoolExecutor()

    print(f"Summarize Link: {link}")
    text = await get_html(ctx, link)

    if text:
        text = strip_html(text)
        text_splitter = CharacterTextSplitter(chunk_size=2000, chunk_overlap=0)
        documents = text_splitter.create_documents([text])

        llm = ChatOpenAI(openai_api_key=openai_api_key, model="gpt-3.5-turbo-0301", temperature=0.3)
        with get_openai_callback() as cb:
            loop = asyncio.get_event_loop()
            chain = await loop.run_in_executor(executor, load_summarize_chain, llm, "map_reduce")
            results = await loop.run_in_executor(executor, chain, {"input_documents": documents}, True)
            print(cb)

            message_content = results['output_text']
            await ctx.send(message_content)

        print(text)
