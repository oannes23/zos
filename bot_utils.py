import openai
import asyncio
import concurrent.futures
import time
import yaml

# Read keys from YAML file
with open("keys.yml", "r") as file:
    keys = yaml.safe_load(file)

openai.api_key = keys["openai_api_key"]

def add_context_instruction(context, instructions, include_assistant=True):
    for instruction in instructions:
        context.append({"role": "user", "content": instruction})
        if include_assistant and instruction != "SYNTHESIZE":
            context.append({"role": "assistant", "content": "UNDERSTOOD"})
    return context

def extract_information(subject, messages):
    prefix, value = subject.split("-", 1)
    relevant_messages = []

    if prefix == 'interaction':
        person1_name, person2_name = value.split("-")
        for message in messages:
            if message.author.name in [person1_name, person2_name]:
                relevant_messages.append(f"@{message.author.name}: {message.content}")

    else:
        for message in messages:
            if getattr(message.author if prefix == 'person' else message.channel, 'name') == value:
                relevant_messages.append(f"@{message.author.name}: {message.content}")

    return "\n".join(relevant_messages)

def format_timestamp(timestamp):
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")

def get_unique_users(messages):
    unique_users = set()
    
    return list({message.author.name for message in messages})


def gpt3_call_sync(context):
    return openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=context
    )

async def gpt_call(context):
    loop = asyncio.get_event_loop()
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            response = await loop.run_in_executor(pool, gpt3_call_sync, context)
    except Exception as e:
        error_message = f"An error occurred while making the API call: {str(e)}"
        print(error_message)
        return error_message  # return the error message

    # Get the generated response from OpenAI
    generated_message = response.choices[0].message['content']
    token_usage = response['usage']['total_tokens']
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

    # Print the generated message, token usage, and timestamp
    print(f"------------------------------------------------------")
    print(f"Timestamp: {timestamp}   Token Usage: {token_usage}")
    print(f"Generated Message: {generated_message}")
    print(f"------------------------------------------------------\n")

    return generated_message
