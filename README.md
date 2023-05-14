# zos

# Zos Discord Bot

Zos is an AI-powered Discord bot developed using Python and OpenAI's GPT model. The bot participates in discussions based on the character of Zos, who has a distinct personality and set of interests.

## Features

- Automatic response generation based on the context and perspective of the character Zos.
- Adjustable "chattiness" level to control the bot's participation frequency.
- The ability to remember context and adjust responses based on previous interactions.
- Support for individual channel probabilities to control the bot's activity across different channels.

## Installation and Setup

**Step 1**: Clone the repository.

```bash
git clone https://github.com/oannes23/zos.git
cd zos
```

**Step 2**: Install the dependencies.

```bash
pip install -r requirements.txt
```

**Step 3**: Update the `keys.yml` file with the appropriate Discord and OpenAI API keys. Also, specify the default channel ID for the bot. Be sure not to commit this file if you're using a public repository.

```yaml
discord_token: YOUR_DISCORD_TOKEN
default_channel_id: YOUR_DEFAULT_CHANNEL_ID
openai_api_key: YOUR_OPENAI_API_KEY
```

**Step 4**: Customize the `channels.yml` file to specify the probability of the bot talking in each channel.

```yaml
channel-name-1: probability
channel-name-2: probability
...
```

**Step 5**: Edit the bot's personality. This can be found in the `memories/self` file and it influences the bot's responses.

## Running the Bot

To start the bot, simply run:

```bash
python bot.py
```

## Usage

The bot will participate in the channels as per the assigned probabilities. It will generate responses based on the character of Zos, and these responses will be influenced by the bot's memory of past interactions.

The bot's chattiness level can be adjusted by calling the `set_chattiness_level` function in `talk.py`. A higher value will make the bot more talkative.

## Dependencies

The bot relies on several Python libraries including `discord.py` for interacting with the Discord API, `openai` for generating text using GPT, `PyYAML` for parsing YAML files, and others. For the full list of dependencies, refer to `requirements.txt`.

## License

This project is open-source and available under [GPL-3.0 license](LICENSE).

## Disclaimer

This bot uses the GPT model from OpenAI, which can generate any kind of text. It's recommended to use this bot responsibly and consider the ethical implications of AI-generated text.
