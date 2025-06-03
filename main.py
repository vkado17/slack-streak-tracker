import os
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

# --- Initialize clients ---
slack_client = WebClient(token=SLACK_TOKEN)
notion = NotionClient(auth=NOTION_TOKEN)

# --- Time range for "today" in UTC ---
now = datetime.datetime.utcnow()
start_of_day = datetime.datetime.combine(now.date(), datetime.time.min)
end_of_day = datetime.datetime.combine(now.date(), datetime.time.max)
start_ts = start_of_day.timestamp()
end_ts = end_of_day.timestamp()

# --- Helper: Get all rows in the Notion DB ---
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

# --- Helper: Get all public Slack channel IDs ---
def get_channel_ids():
    try:
        response = slack_client.conversations_list(types="public_channel")
        return [channel["id"] for channel in response["channels"]]
    except SlackApiError as e:
        print("Error fetching channels:", e)
        return []

# --- Helper: Did user post today? ---
def did_user_post_today(user_id, channel_ids):
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
                    return True
        except SlackApiError:
            continue
    return False

# --- Helper: Get Slack user ID from email ---
def get_user_id_by_email(email):
    try:
        response = slack_client.users_lookupByEmail(email=email)
        return response["user"]["id"]
    except SlackApiError:
        return None

# --- Helper: Extract slug from Dub link URL ---
def extract_slug(dub_url):
    try:
        parsed = urlparse(dub_url)
        return parsed.path.strip("/").split("/")[0]  # e.g., 'Nihal'
    except:
        return None

# --- Helper: Get click count from Dub.co ---
def get_dub_clicks(dub_url):
    slug = extract_slug(dub_url)
    print(f"Extracted slug: {slug}")

    if not slug:
        return 0

    headers = {
        "Authorization": f"Bearer {DUB_API_KEY}"
    }

    try:
        response = requests.get(f"https://api.dub.co/links/{slug}", headers=headers)
        print(f"Dub API status: {response.status_code}")
        print(f"Response body: {response.text}")

        if response.status_code == 200:
            return response.json().get("clicks", 0)
    except Exception as e:
        print("Error fetching from Dub:", e)

    return 0


# --- Helper: Update Notion page with new values ---
def update_notion_page(page_id, streak, last_active, clicks):
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

# --- MAIN ---
def main():
    users = get_notion_users()
    channel_ids = get_channel_ids()

    for user in users:
        props = user["properties"]
        email = None
        if "rich_text" in props["Email"] and props["Email"]["rich_text"]:
            email = props["Email"]["rich_text"][0]["plain_text"]

        dub_url = props.get("Dub Link", {}).get("url")
        last_streak = props["Streak Count"]["number"] or 0

        if not email:
            continue

        user_id = get_user_id_by_email(email)
        if not user_id:
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
