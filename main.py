import os
import time
import requests
from datetime import datetime, timezone
from notion_client import Client as NotionClient
from slack_sdk import WebClient as SlackClient

# Config
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DUB_API_KEY = "dub_Yu8qto7pB2VKlt7vyE7RRDEg"

notion = NotionClient(auth=NOTION_TOKEN)
slack = SlackClient(token=SLACK_TOKEN)

def get_channel_ids():
    channels = slack.conversations_list(types="public_channel").get("channels", [])
    return [c["id"] for c in channels]

def user_posted_today(user_id, channel_ids):
    today = datetime.now(timezone.utc).date()
    for cid in channel_ids:
        time.sleep(1.5)
        try:
            msgs = slack.conversations_history(channel=cid, limit=100)["messages"]
            for msg in msgs:
                if msg.get("user") == user_id:
                    ts = datetime.fromtimestamp(float(msg["ts"]), tz=timezone.utc).date()
                    if ts == today:
                        print(f"✅ Found message from {user_id} in channel {cid}")
                        return True
        except Exception as e:
            print(f"Slack error in channel {cid}: {e}")
    return False

def get_clicks(slug):
    try:
        url = f"https://api.dub.co/analytics?event=clicks&groupBy=count&timezone=UTC&domain=friend.boardy.ai&key={slug}&interval=all"
        res = requests.get(url, headers={"Authorization": f"Bearer {DUB_API_KEY}"})
        return res.json().get("totalCount", 0)
    except Exception as e:
        print(f"Dub error for {slug}: {e}")
        return 0

def update_notion(page_id, streak, last_active, clicks):
    notion.pages.update(
        page_id=page_id,
        properties={
            "Streak Count": {"number": streak},
            "Last Active": {"date": {"start": last_active.isoformat()}},
            "Dub Clicks": {"number": clicks}
        }
    )

def main():
    pages = notion.databases.query(database_id=NOTION_DB_ID)["results"]
    channel_ids = get_channel_ids()

    for page in pages:
        props = page["properties"]
        user_id = props["Slack ID"]["rich_text"][0]["text"]["content"]
        streak = props["Streak Count"].get("number", 0)
        last_str = props["Last Active"]["date"]["start"]
        last_active = datetime.fromisoformat(last_str).date() if last_str else None
        dub_url = props["Dub Link"].get("url", "")
        slug = dub_url.split("/")[-1]

        today = datetime.now().date()
        posted = user_posted_today(user_id, channel_ids)

        new_streak = streak + 1 if posted and last_active != today else (0 if not posted else streak)
        clicks = get_clicks(slug)

        update_notion(page["id"], new_streak, today, clicks)
        print(f"🔁 Updated {user_id} → Streak: {new_streak}, Clicks: {clicks}")

if __name__ == "__main__":
    main()
