import os
import datetime
import requests
from notion_client import Client as NotionClient
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

load_dotenv()

# ENV Variables
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DUB_API_KEY = os.getenv("DUB_API_KEY")
DUB_DOMAIN = "friend.boardy.ai"

# Notion and Slack clients
notion = NotionClient(auth=NOTION_TOKEN)
slack_client = WebClient(token=SLACK_BOT_TOKEN)

# Get today's date
today = datetime.date.today()
today_str = today.isoformat()

# Get Slack messages
def user_posted_today(user_id, channel_ids):
    for channel_id in channel_ids:
        try:
            response = slack_client.conversations_history(
                channel=channel_id,
                oldest=datetime.datetime.combine(today, datetime.time.min).timestamp(),
            )
            for msg in response["messages"]:
                if msg.get("user") == user_id:
                    print(f"✅ Found message from {user_id} in channel {channel_id}")
                    return True
        except SlackApiError as e:
            print(f"Slack error in channel {channel_id}: {e.response['error']}")
    print(f"❌ No message from {user_id} found today.")
    return False

# Get total clicks from Dub
def get_dub_clicks(slug: str) -> int:
    url = (
        f"https://api.dub.co/analytics"
        f"?event=clicks&groupBy=count&timezone=UTC"
        f"&domain={DUB_DOMAIN}&key={slug}&interval=all"
    )
    headers = {"Authorization": f"Bearer {DUB_API_KEY}"}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        return data.get("total", 0)
    else:
        print(f"❌ Dub API error: {response.status_code}, {response.text}")
        return 0

# Get all channel IDs
def get_all_channels():
    try:
        channels = []
        response = slack_client.conversations_list()
        for channel in response["channels"]:
            channels.append(channel["id"])
        print(f"📡 Found {len(channels)} Slack channels to scan.")
        return channels
    except SlackApiError as e:
        print(f"Error fetching Slack channels: {e}")
        return []

# Fetch Notion DB users
def fetch_users():
    users = []
    response = notion.databases.query(database_id=DATABASE_ID)
    for result in response["results"]:
        props = result["properties"]
        slack_id = props["Slack ID"]["rich_text"][0]["plain_text"] if props["Slack ID"]["rich_text"] else None
        slug = props["Dub Slug"]["rich_text"][0]["plain_text"] if props["Dub Slug"]["rich_text"] else None
        users.append({
            "page_id": result["id"],
            "slack_id": slack_id,
            "slug": slug,
            "streak": props["Streak"]["number"],
            "last_active": props["Last Active"]["date"]["start"] if props["Last Active"]["date"] else None,
        })
    print(f"🧾 Found {len(users)} users in Notion DB.")
    return users

# Update user in Notion
def update_user(page_id, new_streak, last_active, clicks):
    notion.pages.update(
        page_id=page_id,
        properties={
            "Streak": {"number": new_streak},
            "Last Active": {"date": {"start": last_active}},
            "Clicks": {"number": clicks}
        }
    )
    print(f"🔁 Updating Notion page: {page_id}\n→ Streak: {new_streak}, Last Active: {last_active}, Clicks: {clicks}")

# Main sync process
def main():
    channel_ids = get_all_channels()
    users = fetch_users()

    for user in users:
        if not user["slack_id"]:
            continue

        posted_today = user_posted_today(user["slack_id"], channel_ids)
        last_active_date = (
            datetime.datetime.strptime(user["last_active"], "%Y-%m-%d").date()
            if user["last_active"]
            else None
        )
        streak = user["streak"] or 0

        if posted_today:
            if last_active_date == today - datetime.timedelta(days=1):
                streak += 1
            else:
                streak = 1
            last_active = today_str
        else:
            streak = 0
            last_active = today_str

        # Dub click tracking
        slug = user["slug"]
        clicks = get_dub_clicks(slug) if slug else 0

        update_user(user["page_id"], streak, last_active, clicks)

if __name__ == "__main__":
    main()
