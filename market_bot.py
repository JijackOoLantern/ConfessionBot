import os
import sys
import datetime
import time
import re
import asyncio
import logging
import html
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(SCRIPT_DIR, '.env'))
except ImportError:
    pass

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CommandHandler,
    ConversationHandler, CallbackQueryHandler, ContextTypes, Application
)
from telegram.error import NetworkError
from typing import Set, Dict, Any, Union
import pytz

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    TOKEN = os.environ.get('MARKET_BOT_TOKEN')
    SUB_BOT_URL = os.environ.get('SUB_BOT_URL', 'https://t.me/')
    AD_CHANNEL_ID = os.environ.get('AD_CHANNEL_ID')
    OWNER_ID_STR = os.environ.get('OWNER_ID')
    LOG_CHANNEL_ID = os.environ.get('LOG_CHANNEL_ID')
    MOD_LOG_CHANNEL_ID = os.environ.get('MOD_LOG_CHANNEL_ID') 
    
    required_vars = {'MARKET_BOT_TOKEN': TOKEN, 'AD_CHANNEL_ID': AD_CHANNEL_ID, 'OWNER_ID': OWNER_ID_STR, 'LOG_CHANNEL_ID': LOG_CHANNEL_ID, 'MOD_LOG_CHANNEL_ID': MOD_LOG_CHANNEL_ID}
    missing_vars = [name for name, val in required_vars.items() if not val]
    if missing_vars:
        print(f"CRITICAL ERROR: Missing .env variables: {', '.join(missing_vars)}")
        sys.exit(1)
        
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    print("CRITICAL ERROR: OWNER_ID must be a valid integer.")
    sys.exit(1)

TIMEZONE = pytz.timezone('Asia/Kuala_Lumpur') 
BOT_START_TIME = datetime.datetime.now()

START_HOUR = 21  
END_HOUR = 18    

LINKS_ENABLED = True
PHOTOS_ENABLED = True

PROMO_TEXT = (
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n"
    "⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️⬇️\n\n"
    "@MarketTapahBot\n\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️\n"
    "⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️⬆️"
)

TIER_CONFIG = {
    'b': {'name': 'Biasa', 'code': 'B', 'price': 'Free', 'queue': 120, 'limit': 2, 'delete': 'own'},
    'b+': {'name': 'Bos', 'code': 'B+', 'price': '50 Stars/bi-weekly', 'queue': 30, 'limit': 5, 'delete': 'own'},
    'a': {'name': 'Along', 'code': 'A', 'price': '100 Stars/bi-weekly', 'queue': 15, 'limit': 10, 'delete': 'all'},
    's': {'name': 'Sultan', 'code': 'S', 'price': '200 Stars/bi-weekly', 'queue': 0, 'limit': 15, 'delete': 'all'},
    'c+': {'name': 'Club', 'code': 'C+', 'price': '200 Stars/month', 'queue': 0, 'limit': 10, 'delete': 'own'},
    'c': {'name': 'Cepat Kaya', 'code': 'C', 'price': '100 Stars/bi-weekly', 'queue': 60, 'limit': 10, 'delete': 'own'} 
}

def format_duration(seconds: Union[int, float]) -> str:
    seconds = int(seconds)
    if seconds <= 0: return "0 seconds"
    if seconds < 60: return f"{seconds} second" + ("s" if seconds != 1 else "")
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if hours > 0: parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
    if minutes > 0: parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
    if secs > 0 and hours == 0: parts.append(f"{secs} second" + ("s" if secs > 1 else ""))
    return " ".join(parts)

GUIDE_TEXT = (
    "<b>🛒 UiTM Tapah Marketplace Bot Guide 🛒</b>\n\n"
    "<u>Marketplace Queueing</u>\n"
    "- Ads are posted to the Marketplace channel.\n"
    "- <b>All Ads have a strict 2-minute global queue</b> regardless of your subscription tier to ensure fairness (unless you own a bypass tier).\n\n"
    "<u>Advertisement Requirements</u>\n"
    "- <b>Requirements:</b> Your ad MUST contain at least a photo, a link, a phone number, or a Telegram username (@). Ads without these will be rejected.\n"
    "- <b>Strict Penalty:</b> Posting a regular confession inside this Ad bot will result in an immediate 1-WEEK timeout.\n\n"
    "<u>Mature Content 🔞</u>\n"
    "- Promoting explicit content will result in an instant and permanent ban. No appeals.\n\n"
    "<u>Deletion & Queue Management</u>\n"
    "- To delete a LIVE ad, forward the message to the bot from the Marketplace channel.\n"
    "- Sending the word \"delete\" directly to the bot will result in a timeout.\n"
    "- To cancel your PENDING ads that are still in the queue, click 'Clear My Queue' in the menu."
)

TNC_TEXT = (
    "👋 Welcome to Tapah Marketplace Bot!\n\n"
    "<b>NOTICE: This bot is STRICTLY for Advertisements and Marketplace items!</b>\n"
    "If you want to post a Confession, you must use @TapahConfessionBot.\n\n"
    "By tapping below, you acknowledge and agree to abide by the Marketplace rules. Posting a confession here results in a 1-week timeout."
)

user_delete_cooldowns: Dict[int, datetime.datetime] = {}
pending_submissions: Dict[int, Dict[str, Any]] = {}
action_states: Dict[int, str] = {}
AWAITING_HELP_MESSAGE = 0

def load_banned_words() -> Set[str]:
    try:
        if os.path.exists("banned_words.txt"):
            with open("banned_words.txt", "r", encoding="utf-8") as f: return {line.strip().lower() for line in f if line.strip()}
    except: pass
    return set()

def load_banned_users() -> Dict[int, str]:
    banned = {}
    try:
        if os.path.exists("banned_users.txt"):
            with open("banned_users.txt", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or "," not in line: continue
                    parts = line.split(',', 1) 
                    if parts[0].isdigit(): banned[int(parts[0])] = parts[1] if len(parts) > 1 else "No reason provided."
    except: pass
    return banned

def load_timeouts() -> Dict[int, Dict[str, Union[float, str]]]:
    timeouts = {}
    try:
        if os.path.exists("timeouts.txt"):
            with open("timeouts.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if "," in line:
                        parts = line.strip().split(',', 2) 
                        uid = int(parts[0])
                        timestamp = float(parts[1])
                        reason = parts[2] if len(parts) > 2 else "No reason provided."
                        if float(timestamp) > time.time(): timeouts[uid] = {'expiry': timestamp, 'reason': reason}
    except: pass
    return timeouts

def save_timeouts_to_disk(timeouts_dict):
    with open("timeouts.txt", "w", encoding="utf-8") as f:
        for uid, data in timeouts_dict.items():
            if data['expiry'] > time.time(): f.write(f"{uid},{data['expiry']},{data['reason']}\n")

def load_admins() -> Set[int]:
    try:
        if os.path.exists("admins.txt"):
            with open("admins.txt", "r", encoding="utf-8") as f: return {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return set()

def load_moderators() -> Set[int]:
    try:
        if os.path.exists("moderators.txt"):
            with open("moderators.txt", "r", encoding="utf-8") as f: return {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return set()

def get_user_tier(uid: int) -> str:
    if uid == OWNER_ID: return 's' 
    try:
        if os.path.exists("active_subscriptions.txt"):
            with open("active_subscriptions.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        user_str, tier, expiry_str = line.strip().split(',')
                        if int(user_str) == uid and float(expiry_str) > time.time():
                            t = tier.lower()
                            if t == 'tier1': t = 'a'
                            elif t == 'tier2': t = 'b+'
                            elif t == 'club': t = 'c+'
                            return t if t in TIER_CONFIG else 'b'
    except: pass
    return 'b'

def load_agreed_users() -> Set[int]:
    try:
        if os.path.exists("agreed_users_market.txt"):
            with open("agreed_users_market.txt", "r", encoding="utf-8") as f: return {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return set()

def save_agreed_user(uid):
    users = load_agreed_users()
    if uid not in users:
        with open("agreed_users_market.txt", "a", encoding="utf-8") as f: f.write(f"{uid}\n")

def load_known_users() -> Set[int]:
    try:
        if os.path.exists("users_market.txt"):
            with open("users_market.txt", "r", encoding="utf-8") as f: return {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return set()

def save_user(uid):
    users = load_known_users()
    if uid not in users:
        with open("users_market.txt", "a", encoding="utf-8") as f: f.write(f"{uid}\n")

def load_persistent_queue() -> list:
    try:
        if os.path.exists("persistent_queue_market.json"):
            with open("persistent_queue_market.json", "r", encoding="utf-8") as f: return json.load(f)
    except: pass
    return []

def save_persistent_queue(queue_list: list):
    with open("persistent_queue_market.json", "w", encoding="utf-8") as f: json.dump(queue_list, f, ensure_ascii=False, indent=4)

def load_tier_times() -> Dict[str, datetime.datetime]:
    try:
        if os.path.exists("tier_times_market.json"):
            with open("tier_times_market.json", "r") as f:
                data = json.load(f)
                return {k: datetime.datetime.fromtimestamp(v, TIMEZONE) for k, v in data.items()}
    except: pass
    return {}

def save_tier_times(times_dict: Dict[str, datetime.datetime]):
    with open("tier_times_market.json", "w") as f: json.dump({k: v.timestamp() for k, v in times_dict.items()}, f)

def get_main_queue_counts():
    counts = {}
    try:
        if os.path.exists("persistent_queue_main.json"):
            with open("persistent_queue_main.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                for j in data:
                    t = j.get('tier', 'b')
                    counts[t] = counts.get(t, 0) + 1
    except: pass
    return counts

def get_main_tier_times():
    try:
        if os.path.exists("tier_times_main.json"):
            with open("tier_times_main.json", "r", encoding="utf-8") as f:
                tt = json.load(f)
                return {k: datetime.datetime.fromtimestamp(v, TIMEZONE) for k, v in tt.items()}
    except: pass
    return {}

def get_daily_usage(uid: int) -> int:
    today = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    try:
        if os.path.exists("daily_usage_shared.json"):
            with open("daily_usage_shared.json", "r") as f:
                data = json.load(f)
                if str(uid) in data and data[str(uid)]['date'] == today: return data[str(uid)]['count']
    except: pass
    return 0

def increment_daily_usage(uid: int):
    today = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    data = {}
    try:
        if os.path.exists("daily_usage_shared.json"):
            with open("daily_usage_shared.json", "r") as f: data = json.load(f)
    except: pass
    if str(uid) not in data or data[str(uid)]['date'] != today: data[str(uid)] = {'date': today, 'count': 0}
    data[str(uid)]['count'] += 1
    with open("daily_usage_shared.json", "w") as f: json.dump(data, f)

def recalculate_queues(pq_list: list) -> list:
    now_tz = datetime.datetime.now(TIMEZONE)
    now_ts = now_tz.timestamp()
    base_delay = get_seconds_until_active() if not is_bot_active() else 0
    start_ts = now_ts + base_delay
    new_tier_times = {}
    for job in pq_list:
        t = 'ad_global'
        q_dur = 120
        queue_start = max(start_ts, new_tier_times.get(t, start_ts))
        new_sched = queue_start + q_dur
        job['scheduled_time'] = new_sched
        new_tier_times[t] = new_sched
    current_tier_times = load_tier_times()
    for t_key in list(current_tier_times.keys()):
        if t_key in new_tier_times: current_tier_times[t_key] = datetime.datetime.fromtimestamp(new_tier_times[t_key], TIMEZONE)
        else: current_tier_times[t_key] = now_tz
    for t_key, sched in new_tier_times.items():
        if t_key not in current_tier_times: current_tier_times[t_key] = datetime.datetime.fromtimestamp(sched, TIMEZONE)
    save_tier_times(current_tier_times)
    return pq_list

def append_post_history(message_id: int, user_id: int):
    with open("post_history_market.txt", "a", encoding="utf-8") as f: f.write(f"{message_id},{user_id},0\n")

def query_post_history(message_id: int) -> Dict[str, Any]:
    try:
        if os.path.exists("post_history_market.txt"):
            with open("post_history_market.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        msg_id, uid, _ = line.strip().split(',')
                        if int(msg_id) == message_id: return {'user_id': int(uid)}
    except: pass
    return {'user_id': None}

def load_time_settings():
    global START_HOUR, END_HOUR
    try:
        if os.path.exists("active_time.txt"):
            with open("active_time.txt", "r", encoding="utf-8") as f:
                parts = f.read().strip().split(',')
                START_HOUR = int(parts[0])
                END_HOUR = int(parts[1])
    except: pass

def save_time_settings():
    with open("active_time.txt", "w", encoding="utf-8") as f: f.write(f"{START_HOUR},{END_HOUR}")

load_time_settings()

def is_owner(uid: int) -> bool: return uid == OWNER_ID
def is_owner_or_admin(uid: int) -> bool: return uid == OWNER_ID or uid in load_admins()
def is_owner_or_mod(uid: int) -> bool: return is_owner_or_admin(uid) or uid in load_moderators()

async def log_admin_action(context: ContextTypes.DEFAULT_TYPE, action_type: str, executor, target_id: int, reason: str, duration: str = None):
    executor_name = html.escape(str(getattr(executor, 'first_name', 'System')))
    executor_uid = getattr(executor, 'id', 'System')
    owner_log = f"🛡️ <b>ADMIN ACTION: {action_type.upper()}</b>\n\n👤 <b>Target ID:</b> <code>{target_id}</code>\n👮 <b>By:</b> {executor_name} (<code>{executor_uid}</code>)\n"
    if duration: owner_log += f"⏳ <b>Duration:</b> {duration}\n"
    owner_log += f"📝 <b>Reason:</b> {html.escape(reason)}"
    mod_log = f"🛡️ <b>MODERATION ACTION: {action_type.upper()}</b>\n\n👤 <b>Target ID:</b> <code>{target_id}</code>\n👮 <b>By:</b> <code>{executor_uid}</code>\n"
    if duration: mod_log += f"⏳ <b>Duration:</b> {duration}\n"
    mod_log += f"📝 <b>Reason:</b> {html.escape(reason)}"
    try: await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=owner_log, parse_mode='HTML')
    except: pass
    try: await context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=mod_log, parse_mode='HTML')
    except: pass

async def is_user_restricted(user_id: int, update: Update=None, context: ContextTypes.DEFAULT_TYPE=None) -> bool:
    if is_owner_or_mod(user_id): return False 
    banned = load_banned_users()
    if user_id in banned:
        msg = f"🚫 You are permanently banned.\n<b>Reason:</b> {html.escape(banned[user_id])}"
        if update: await update.message.reply_text(msg, parse_mode='HTML')
        elif context: await context.bot.send_message(user_id, msg, parse_mode='HTML')
        return True
    timeouts = load_timeouts()
    if user_id in timeouts:
        expiry = timeouts[user_id]['expiry']
        reason = timeouts[user_id]['reason']
        rem = expiry - time.time()
        if rem > 0:
            msg = f"⏳ You are in timeout. Please wait another {format_duration(rem)}.\n<b>Reason:</b> {html.escape(reason)}\n\n💡 <i>Tip: You can instantly lift this timeout by purchasing a 'Clear Timeout' pass for 200 Stars in our store: {SUB_BOT_URL}</i>"
            if update: await update.message.reply_text(msg, parse_mode='HTML')
            elif context: await context.bot.send_message(user_id, msg, parse_mode='HTML')
            return True
        else:
            del timeouts[user_id]
            save_timeouts_to_disk(timeouts)
    return False

def format_time(hour_24: int) -> str:
    am_pm = "AM" if hour_24 < 12 else "PM"
    h = hour_24 if hour_24 <= 12 else hour_24 - 12
    if h == 0: h = 12
    return f"{h:02d}:00 {am_pm}"

def is_bot_active() -> bool:
    now = datetime.datetime.now(
