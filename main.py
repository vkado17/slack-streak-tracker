import os
import time
import requests
from datetime import datetime, timedelta
from pytz import timezone as pytz_timezone
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
PDT = pytz_timezone("America/Los_Angeles")

def get_channel_ids():
    try:
        channels = slack.conversations_list(types="public_channel").get("channels", [])
        return [c["id"] for c in channels]
    except Exception as e:
        print(f"❌ Error fetching channels: {e}")
        return []

def user_posted_on(user_id, channel_ids, target_date):
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
                    ts = datetime.fromtimestamp(float(msg["ts"]), tz=PDT).date()
                    if ts == target_date:
                        print(f"✅ Found message from {user_id} in channel {cid} on {ts}")
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
        properties = {
            "Streak Count": {"number": streak},
            "Dub Clicks": {"number": clicks}
        }
        if last_active:
            properties["Last Active Date"] = {"date": {"start": last_active.isoformat()}}
        notion.pages.update(page_id=page_id, properties=properties)
    except Exception as e:
        print(f"❌ Notion update failed: {e}")

def update_display_name(user_id, streak, clicks, user_token):
    try:
        client = SlackClient(token=user_token)
        profile = client.users_profile_get(user=user_id)["profile"]
        display_name = profile.get("display_name", "")
        real_name = profile.get("real_name", "")

        base_name = display_name.strip()
        if not base_name or base_name.startswith("[𖦹"):
            base_name = real_name.strip()
        if "[" in base_name:
            base_name = base_name.split("[")[0].strip()

        new_display_name = f"{base_name} [ঌ{streak}, 𐀪𐀪{clicks}]"
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
    today = datetime.now(PDT).date()
    yesterday = today - timedelta(days=1)
    day_before_yesterday = today - timedelta(days=2)

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

        posted_yesterday = user_posted_on(user_id, channel_ids, yesterday)
        print(f"Debug → posted_yesterday: {posted_yesterday}, last_active: {last_active}, streak: {streak}")

        if posted_yesterday:
            if last_active == day_before_yesterday:
                new_streak = streak + 1
            else:
                new_streak = 1
            update_notion(page["id"], new_streak, yesterday, get_clicks(slug))
        else:
            new_streak = 0
            update_notion(page["id"], new_streak, last_active, get_clicks(slug))

        if user_token:
            update_display_name(user_id, new_streak, get_clicks(slug), user_token)

        print(f"🔁 Updated {user_id} → Streak: {new_streak}, Clicks: {get_clicks(slug)}")

if __name__ == "__main__":
    main()
