import os
import time
import requests
from datetime import datetime, timezone
from notion_client import Client as NotionClient
from slack_sdk import WebClient as SlackClient
from slack_sdk.errors import SlackApiError

# Config
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DUB_API_KEY = os.getenv("DUB_API_KEY")

notion = NotionClient(auth=NOTION_TOKEN)
slack = SlackClient(token=SLACK_BOT_TOKEN)

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
        try:
            while True:
                try:
                    res = slack.conversations_history(channel=cid, limit=100)
                    break
                except SlackApiError as e:
                    if e.response.status_code == 429:
                        retry_after = int(e.response.headers.get("Retry-After", 1))
                        print(f"⏳ Rate limited, sleeping for {retry_after}s...")
                        time.sleep(retry_after)
                    else:
                        raise
            messages = res.get("messages", [])
            for msg in messages:
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
        url = (
            "https://api.dub.co/analytics?"
            f"event=clicks&groupBy=count&timezone=UTC&domain=friend.boardy.ai&key={slug}&interval=all"
        )
        res = requests.get(url, headers={"Authorization": f"Bearer {DUB_API_KEY}"})
        data = res.json()
        if res.status_code != 200:
            print(f"❌ Dub API status {res.status_code} for slug '{slug}' — {data}")
            return 0
        return data.get("totalCount") or data.get("clicks") or 0
    except Exception as e:
        print(f"❌ Exception fetching Dub clicks for '{slug}': {e}")
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

def clean_name(name):
    # Remove any previous tag like [𖦹x, 𐀪𐀪y]
    if "[" in name and "]" in name:
        return name[:name.rfind("[")].strip()
    return name.strip()

def update_display_name(user_id, streak, clicks, user_token):
    try:
        client = SlackClient(token=user_token)
        profile = client.users_profile_get(user=user_id)["profile"]
        display_name = profile.get("display_name", "")
        real_name = profile.get("real_name", "")

        # Fallback if display_name is empty or just the tag itself
        base_name = display_name.strip()
        if not base_name or base_name.startswith("[𖦹"):
            base_name = real_name.strip()

        # Remove previous suffix if exists
        if "[" in base_name:
            base_name = base_name.split("[")[0].strip()

        new_display_name = f"{base_name} [𖦹{streak}, 𐀪𐀪{clicks}]"

        client.users_profile_set(
            user=user_id,
            profile={"display_name": new_display_name}
        )
        print(f"🎯 Updated display name for {user_id} → {new_display_name}")
    except Exception as e:
        print(f"⚠️ Failed to update display name for {user_id}: {e}")


def main():
    pages = notion.databases.query(database_id=NOTION_DB_ID)["results"]
    channel_ids = get_channel_ids()
    today = datetime.now().date()

    for page in pages:
        props = page["properties"]

        slack_field = props.get("Slack ID", {}).get("rich_text", [])
        if not slack_field:
            print(f"⚠️ Skipping page {page['id']} — no Slack ID")
            continue
        user_id = slack_field[0]["text"]["content"]

        user_token_field = props.get("User Token", {}).get("rich_text", [])
        user_token = user_token_field[0]["text"]["content"] if user_token_field else None

        streak = props.get("Streak Count", {}).get("number", 0)
        last_str = props.get("Last Active Date", {}).get("date", {}).get("start")
        last_active = datetime.fromisoformat(last_str).date() if last_str else None
        dub_url = props.get("Dub Link", {}).get("url", "")
        slug = dub_url.split("/")[-1] if "/" in dub_url else dub_url

        posted = user_posted_today(user_id, channel_ids)
        print(f"Debug → posted: {posted}, last_active: {last_active}, today: {today}, current streak: {streak}")
        new_streak = streak + 1 if posted and last_active != today else (0 if not posted else streak)
        clicks = get_clicks(slug)

        update_notion(page["id"], new_streak, today, clicks)

        if user_token:
            update_display_name(user_id, new_streak, clicks, user_token)

        print(f"🔁 Updated {user_id} → Streak: {new_streak}, Clicks: {clicks}")

if __name__ == "__main__":
    main()
