import os
import time
import requests
from datetime import datetime, timezone
from notion_client import Client as NotionClient
from slack_sdk import WebClient as SlackClient

# Config
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DUB_API_KEY = os.getenv("DUB_API_KEY")
USER_OAUTH_TOKEN = os.getenv("USER_OAUTH_TOKEN")  # For display name updates

notion = NotionClient(auth=NOTION_TOKEN)
slack = SlackClient(token=SLACK_BOT_TOKEN)
user_slack = SlackClient(token=USER_OAUTH_TOKEN)

def get_channel_ids():
    try:
        channels = slack.conversations_list(types="public_channel").get("channels", [])
        return [c["id"] for c in channels]
    except Exception as e:
        print(f"❌ Error fetching channels: {e}")
        return []

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
    try:
        notion.pages.update(
            page_id=page_id,
            properties={
                "Streak Count": {"number": streak},
                "Last Active Date": {"date": {"start": last_active.isoformat()}},
                "Dub Clicks": {"number": clicks}
            }
        )
    except Exception as e:
        print(f"❌ Notion update failed: {e}")

def update_display_name(user_id, streak):
    try:
        profile = user_slack.users_profile_get(user=user_id)["profile"]
        current_name = profile.get("display_name", "")
        new_name = f"{current_name.split('🔥')[0].strip()} 🔥{streak}"
        user_slack.users_profile_set(user=user_id, profile={"display_name": new_name})
        print(f"🎯 Updated display name for {user_id} → {new_name}")
    except Exception as e:
        print(f"⚠️ Failed to update display name for {user_id}: {e}")

def main():
    pages = notion.databases.query(database_id=NOTION_DB_ID)["results"]
    channel_ids = get_channel_ids()
    today = datetime.now().date()

    for page in pages:
        props = page["properties"]

        # Validate Slack ID
        slack_field = props.get("Slack ID", {}).get("rich_text", [])
        if not slack_field:
            print(f"⚠️ Skipping page {page['id']} — no Slack ID")
            continue
        user_id = slack_field[0]["text"]["content"]

        # Handle streak count
        streak = props.get("Streak Count", {}).get("number", 0)

        # Handle last active date
        last_str = props.get("Last Active Date", {}).get("date", {}).get("start")
        last_active = datetime.fromisoformat(last_str).date() if last_str else None

        # Handle Dub Link
        dub_url = props.get("Dub Link", {}).get("url", "")
        slug = dub_url.split("/")[-1] if "/" in dub_url else dub_url

        posted = user_posted_today(user_id, channel_ids)
        new_streak = streak + 1 if posted and last_active != today else (0 if not posted else streak)
        clicks = get_clicks(slug)

        update_notion(page["id"], new_streak, today, clicks)

        # Only update display name if it's your own user
        if user_id == "U08MWN65X8X":  # Replace with your actual Slack ID
            update_display_name(user_id, new_streak)

        print(f"🔁 Updated {user_id} → Streak: {new_streak}, Clicks: {clicks}")

if __name__ == "__main__":
    main()
