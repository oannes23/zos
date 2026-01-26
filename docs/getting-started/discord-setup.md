# Discord Setup

This guide covers creating a Discord bot application and configuring the necessary permissions.

---

## Create a Discord Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**
3. Enter a name (e.g., "Zos") and click **Create**
4. Note the **Application ID** (you may need it later)

---

## Create the Bot

1. In your application, go to **Bot** in the left sidebar
2. Click **Add Bot** and confirm
3. Under **Token**, click **Copy** to copy your bot token
4. Store this token securely — you'll need it as `DISCORD_TOKEN`

### Bot Settings

Configure these settings:

| Setting | Value |
|---------|-------|
| Public Bot | Off (recommended for private instances) |
| Requires OAuth2 Code Grant | Off |
| Presence Intent | On |
| Server Members Intent | On |
| Message Content Intent | On |

**Important**: All three Privileged Gateway Intents must be enabled for Zos to observe messages.

---

## Generate Invite Link

1. Go to **OAuth2** → **URL Generator** in the left sidebar
2. Select these **Scopes**:
   - `bot`
   - `applications.commands`
3. Select these **Bot Permissions**:
   - Read Messages/View Channels
   - Send Messages
   - Read Message History
   - Add Reactions
   - Use Slash Commands

The minimum permission integer is `277025770560`.

4. Copy the generated URL
5. Open the URL in your browser and select the server to add Zos to

---

## Verify Bot Access

After adding the bot to your server:

1. The bot should appear in the server's member list (offline until you run it)
2. Ensure the bot has access to the channels you want it to observe
3. Check that the bot's role isn't blocked by channel permission overrides

---

## Multiple Servers

Zos can observe multiple servers. Repeat the invite process for each server. Server-specific configuration can be set in `config.yaml` under the `servers` key.

---

## Security Notes

- Never commit your bot token to version control
- Use environment variables for tokens
- Rotate your token if it's ever exposed
- Keep your bot private unless you need public access

---

## Next Step

[Configuration](configuration.md) — Set up config.yaml with your tokens and preferences
