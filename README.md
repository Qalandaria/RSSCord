# RSSCord

Simple Discord bot in Python that:

- fetches RSS/Atom feeds with `feedparser`
- stores configured feeds and seen entries in SQLite
- supports CRUD commands plus enable/disable toggling
- resolves YouTube channel-style URLs into YouTube's Atom feed URL
- restricts commands to a configured allowlist of Discord users

## Commands

- `!feeds`
- `!feed_add <url>`
- `!feed_update <id> <url>`
- `!feed_remove <id>`
- `!feed_toggle <id>`
- `!feed_refresh [id]`

Only users listed in `ALLOWED_USERS` in `.env` can run commands. Use a comma-separated list of usernames.

## Setup

1. Create a virtual environment.
2. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

3. Copy `.env.example` values into your environment.
4. Set `DISCORD_BOT_TOKEN`.
5. Set `ALLOWED_USERS` to a comma-separated list of Discord usernames allowed to use the bot.
6. Set `RSSCORD_CHANNEL_ID` if you want new feed items posted to a specific channel.
7. Run the bot:

```bash
python3 bot.py
```

## Notes

- Feed history is stored in `rsscord.db` by default.
- Disabled feeds stay in the database and are skipped by the background poller.
- When you add or update a feed, the bot resolves YouTube channel URLs like `https://www.youtube.com/@handle` to a feed URL shaped like `https://www.youtube.com/feeds/videos.xml?channel_id=...`.
