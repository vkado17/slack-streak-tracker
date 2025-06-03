import os
import time
import datetime
import requests
from urllib.parse import urlparse
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from notion_client import Client as NotionClient

# --- Load secrets from environment ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")
SLACK_TOKEN = os.getenv("SLACK_TOKEN")
DUB_API_KEY = os.getenv("DUB_API_KEY")
DUB_DOMAIN = "friend.boardy.ai"

# --- Initialize clients ---
slack_client = WebClient(token=SLACK_TOKEN)
notion = NotionClient(auth=NOTION_TOKEN)

# --- Time range for "today" in UTC ---
now = datetime.datetime.utcnow()
start_of_day = datetime.datetime.combine(now.date(), datetime.time.min)
end_of_day = datetime.datetime.combine(now.date(), datetime.time.max)
start_ts = start_of_day.timestamp()
end_ts = end_of_day.timestamp()

# --- Get all Notion rows ---
def get_notion_users():
    results = []
    start_cursor = None
    while True:
        response = notion.databases.query(
            **{
                "database_id": NOTION_DB_ID,
                "start_cursor": start_cursor,
                "page_size": 100,
            }
        )
        results.extend(response["results"])
        if not response.get("has_more"):
            break
        start_cursor = response.get("next_cursor")
    return results

# --- Get Slack channel IDs ---
def get_channel_ids():
    try:
        response = slack_client.conversations_list(types="public_channel,private_channel")
        return [channel["id"] for channel in response["channels"]]
    except SlackApiError as e:
        print("Error fetching channels:", e)
        return []

# --- Check if user posted today, with rate-limit handling ---
def did_user_post_today(user_id, channel_ids):
    print(f"Checking if user {user_id} posted today...")
    for channel_id in channel_ids:
        try:
            response = slack_client.conversations_history(
                channel=channel_id,
                oldest=start_ts,
                latest=end_ts,
                limit=200
            )
            for message in response["messages"]:
                if message.get("user") == user_id:
                    print(f"✅ Found message from {user_id} in channel {channel_id}")
                    return True
        except SlackApiError as e:
            print(f"Slack error in channel {channel_id}: {e}")
        time.sleep(1.1)  # Wait 1.1s to stay under rate limit
    print(f"❌ No message from {user_id} found today.")
    return False

# --- Slack email → user ID ---
def get_user_id_by_email(email):
    try:
        response = slack_client.users_lookupByEmail(email=email)
        return response["user"]["id"]
    except SlackApiError as e:
        print(f"Slack API error for {email}: {e}")
        return None

# --- Extract Dub slug ---
def extract_slug(dub_url):
    try:
        parsed = urlparse(dub_url)
        return parsed.path.strip("/").split("/")[0]
    except:
        return None

# --- Get click count from Dub ---
def get_dub_clicks(dub_url):
    slug = extract_slug(dub_url)
    print(f"Extracted slug: {slug}")

    if not slug:
        return 0

    headers = {
        "Authorization": f"Bearer {DUB_API_KEY}"
    }
    params = {"domain": DUB_DOMAIN}

    try:
        response = requests.get(f"https://api.dub.co/links/{slug}", headers=headers, params=params)
        print(f"Dub API status: {response.status_code}")
        print(f"Response body: {response.text}")
        if response.status_code == 200:
            return response.json().get("clicks", 0)
    except Exception as e:
        print("Error fetching from Dub:", e)

    return 0

# --- Update row in Notion ---
def update_notion_page(page_id, streak, last_active, clicks):
    print(f"🔁 Updating Notion page: {page_id}")
    print(f"→ Streak: {streak}, Last Active: {last_active}, Clicks: {clicks}")
    try:
        notion.pages.update(
            page_id=page_id,
            properties={
                "Streak Count": {"number": streak},
                "Last Active Date": {"date": {"start": last_active}},
                "Dub Clicks": {"number": clicks},
            }
        )
    except Exception as e:
        print(f"Error updating Notion page {page_id}:", e)

# --- Main loop ---
def main():
    users = get_notion_users()
    channel_ids = get_channel_ids()

    print(f"📡 Found {len(channel_ids)} Slack channels to scan.")
    print(f"🧾 Found {len(users)} users in Notion DB.")

    for user in users:
        props = user["properties"]
        email = None
        if "rich_text" in props["Email"] and props["Email"]["rich_text"]:
            email = props["Email"]["rich_text"][0]["plain_text"]

        dub_url = props.get("Dub Link", {}).get("url")
        last_streak = props["Streak Count"]["number"] or 0

        if not email:
            print("⛔️ No email for user row, skipping.")
            continue

        user_id = get_user_id_by_email(email)
        if not user_id:
            print(f"⛔️ Could not resolve Slack user for {email}")
            continue

        active_today = did_user_post_today(user_id, channel_ids)
        new_streak = last_streak + 1 if active_today else 0
        click_count = get_dub_clicks(dub_url) if dub_url else 0

        update_notion_page(
            page_id=user["id"],
            streak=new_streak,
            last_active=now.date().isoformat(),
            clicks=click_count
        )

if __name__ == "__main__":
    main()
