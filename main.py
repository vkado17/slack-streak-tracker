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
        try:
            while True:
                try:
                    res = slack.conversations_history(channel=cid, limit=100)
                    break  # If successful, exit retry loop
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

        if "totalCount" in data:
            return data["totalCount"]
        elif "clicks" in data:
            return data["clicks"]
        else:
            print(f"⚠️ Unexpected Dub format for slug '{slug}' — {data}")
            return 0

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

def update_display_name(user_token, user_id, streak, clicks):
    try:
        client = SlackClient(token=user_token)
        profile = client.users_profile_get(user=user_id)["profile"]
        current_name = profile.get("display_name", "")
        base_name = current_name.split("[")[0].strip()

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

        if user_id == "U08MWN65X8X":  # Replace with your actual Slack ID
            update_display_name(user_id, new_streak)

        print(f"🔁 Updated {user_id} → Streak: {new_streak}, Clicks: {clicks}")

if __name__ == "__main__":
    main()
