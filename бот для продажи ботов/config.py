import os
from hashids import Hashids
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
FEEDBACK_CHANNEL_ID = int(os.getenv("FEEDBACK_CHANNEL_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")
HASHIDS_SALT = os.getenv("HASHIDS_SALT", "default_salt")
BOT_USERNAME = os.getenv("BOT_USERNAME", "MyBot")

hashids = Hashids(salt=HASHIDS_SALT, min_length=6)
