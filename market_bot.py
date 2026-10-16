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
    "- Ads are STRICTLY posted to the Marketplace channel.\n"
    "- To ensure fairness and prevent spam, <b>ALL Ads have a strict 2-minute global queue</b> regardless of your subscription tier.\n\n"
    "<u>Advertisement Requirements</u>\n"
    "- <b>Requirements:</b> Your ad MUST contain at least a photo, a link, a phone number, or a Telegram username (@). Ads without these will be rejected.\n"
    "- <b>Strict Penalty:</b> Posting a regular confession inside this Ad bot will result in an immediate 1-WEEK timeout across all networks.\n\n"
    "<u>Mature Content 🔞</u>\n"
    "- Promoting explicit content will result in an instant and permanent ban. No appeals.\n\n"
    "<u>Deletion & Queue Management</u>\n"
    "- To delete a LIVE post, forward the message to the bot from the marketplace channel.\n"
    "- Sending the word \"delete\" directly to the bot will result in a timeout.\n"
    "- To cancel your PENDING posts that are still in the queue, click 'Clear My Queue' in the menu.\n\n"
    "<u>Timeouts & Moderation</u>\n"
    "- Timed punishments are imposed for rule-breaking. Users can instantly lift their own timeout by purchasing a 'Clear Timeout' pass for 200 Stars in our Store bot."
)

TNC_TEXT = (
    "👋 Welcome to Tapah Marketplace Bot!\n\n"
    "<b>NOTICE: This bot is STRICTLY for Advertisements and Marketplace items!</b>\n"
    "If you want to post a Confession, you must use our main bot.\n\n"
    "By tapping below, you acknowledge and agree to fully abide by the Marketplace rules, and you understand that posting a confession here will result in a 1-week timeout."
)

user_delete_cooldowns: Dict[int, datetime.datetime] = {}
user_link_cooldowns: Dict[int, datetime.datetime] = {}
user_photo_cooldowns: Dict[int, datetime.datetime] = {} 
pending_submissions: Dict[int, Dict[str, Any]] = {}
action_states: Dict[int, str] = {}
AWAITING_HELP_MESSAGE = 0

def load_banned_words() -> Set[str]:
    words = set()
    try:
        if os.path.exists("banned_words.txt"):
            with open("banned_words.txt", "r", encoding="utf-8") as f: words = {line.strip().lower() for line in f if line.strip()}
    except: pass
    return words

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

def load_moderators() -> Set[int]:
    mods = set()
    try:
        if os.path.exists("moderators.txt"):
            with open("moderators.txt", "r", encoding="utf-8") as f: mods = {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return mods

def get_user_tier(uid: int) -> str:
    if uid == OWNER_ID: return 'tier1' 
    try:
        if os.path.exists("active_subscriptions.txt"):
            with open("active_subscriptions.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        user_str, tier, expiry_str = line.strip().split(',')
                        if int(user_str) == uid and float(expiry_str) > time.time(): return tier
    except: pass
    return 'basic'

def load_agreed_users() -> Set[int]:
    users = set()
    try:
        if os.path.exists("agreed_users_market.txt"):
            with open("agreed_users_market.txt", "r", encoding="utf-8") as f: users = {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return users

def save_agreed_user(uid):
    users = load_agreed_users()
    if uid not in users:
        with open("agreed_users_market.txt", "a", encoding="utf-8") as f: f.write(f"{uid}\n")

def load_known_users() -> Set[int]:
    ids = set()
    try:
        if os.path.exists("users_market.txt"):
            with open("users_market.txt", "r", encoding="utf-8") as f: ids = {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return ids

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
                    t = j.get('tier', 'basic')
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
def is_owner_or_mod(uid: int) -> bool: return uid == OWNER_ID or uid in load_moderators()

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
    now = datetime.datetime.now(TIMEZONE)
    if START_HOUR <= now.hour or now.hour < END_HOUR: return True
    return False

def get_seconds_until_active() -> float:
    now = datetime.datetime.now(TIMEZONE)
    target = now.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    if now.hour >= START_HOUR: target += datetime.timedelta(days=1)
    return (target - now).total_seconds()

def check_for_banned_words(text: str) -> bool:
    if not text: return False
    text_lower = text.lower()
    for word in load_banned_words():
        if re.match(r'^\w+$', word):
            pattern = r'(?<!\w)' + re.escape(word) + r'(?!\w)'
            if re.search(pattern, text_lower): return True
        else:
            if word in text_lower: return True
    return False

def contains_link_text(text: str) -> bool:
    if not text: return False
    text_lower = text.lower()
    return "http://" in text_lower or "https://" in text_lower or "www." in text_lower

def create_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    raw_username = job_info.get('username')
    display_username = f"@{html.escape(raw_username)}" if raw_username else "Not available"
    safe_name = html.escape(str(job_info['user_name']))
    safe_uid = html.escape(str(job_info['user_id']))
    log_message = f"<b>🛒 New {content_type} Advertisement Log 🛒</b>\n\n<b>User ID:</b> <code>{safe_uid}</code>\n<b>Name:</b> {safe_name}\n<b>Username:</b> {display_username}\n\n"
    content_to_log = text_content or job_info.get('caption')
    if content_to_log: log_message += f"<b>Content:</b>\n{html.escape(content_to_log)}"
    return log_message

def create_mod_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    safe_uid = html.escape(str(job_info['user_id']))
    log_message = f"<b>🛒 New {content_type} Advertisement Log (Moderator) 🛒</b>\n\n<b>User ID:</b> <code>{safe_uid}</code>\n\n"
    content_to_log = text_content or job_info.get('caption')
    if content_to_log: log_message += f"<b>Content:</b>\n{html.escape(content_to_log)}"
    log_message += f"\n\n<i>Mod Tip: If this is a confession in the Ad channel, timeout for 1 week using:</i>\n<code>/timeout {safe_uid} 10080 Posted confession in Ad channel</code>\n"
    return log_message

def get_tnc_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("📖 Read Guide", callback_data='tc_guide')], [InlineKeyboardButton("✅ I Agree", callback_data='tc_agree')]])

def get_main_menu(user_id: int):
    keyboard = []
    if is_owner(user_id):
        role_title = "👑 Owner Panel"
        keyboard = [
            [InlineKeyboardButton("📊 Stats", callback_data='menu_stats'), InlineKeyboardButton("📈 Insights", callback_data='menu_insights')],
            [InlineKeyboardButton("⏰ Active Time", callback_data='menu_active_time')],
            [InlineKeyboardButton("📜 T&C Stats", callback_data='menu_tnc_stats'), InlineKeyboardButton("🤬 Banned Words", callback_data='menu_manage_words')],
            [InlineKeyboardButton("👮‍♂️ Manage Mods", callback_data='menu_manage_mods'), InlineKeyboardButton("🚫 Manage Bans", callback_data='menu_manage_bans')],
            [InlineKeyboardButton("⏳ Manage Timeouts", callback_data='menu_manage_timeouts'), InlineKeyboardButton("🔗 Toggle Links", callback_data='menu_toggle_links')],
            [InlineKeyboardButton("📸 Toggle Photos", callback_data='menu_toggle_photos'), InlineKeyboardButton("🎁 Gift Sub", callback_data='trig_gift')],
            [InlineKeyboardButton("❌ Revoke Sub", callback_data='trig_revoke')],
            [InlineKeyboardButton("🛒 Subscriptions", url=SUB_BOT_URL), InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide')],
            [InlineKeyboardButton("👤 My Status", callback_data='menu_my_status')],
            [InlineKeyboardButton("🗑️ Clear My Queue", callback_data='menu_clear'), InlineKeyboardButton("🗑️ Clear All Queues", callback_data='menu_clear_global')],
            [InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
    elif is_owner_or_mod(user_id):
        role_title = "👮‍♂️ Moderator Panel"
        keyboard = [
            [InlineKeyboardButton("📈 Insights", callback_data='menu_insights'), InlineKeyboardButton("⏳ Manage Timeouts", callback_data='menu_manage_timeouts')],
            [InlineKeyboardButton("🤬 Banned Words", callback_data='menu_manage_words'), InlineKeyboardButton("🛒 Subscriptions", url=SUB_BOT_URL)],
            [InlineKeyboardButton("👤 My Status", callback_data='menu_my_status'), InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide')],
            [InlineKeyboardButton("🗑 Clear My Queue", callback_data='menu_clear'), InlineKeyboardButton("🗑️ Clear All Queues", callback_data='menu_clear_global')],
            [InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
    else:
        role_title = "User"
        keyboard = [
            [InlineKeyboardButton("🛒 Subscriptions", url=SUB_BOT_URL), InlineKeyboardButton("📈 View Queue", callback_data='menu_insights')],
            [InlineKeyboardButton("👤 My Status", callback_data='menu_my_status'), InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide')],
            [InlineKeyboardButton("🗑️ Clear My Queue", callback_data='menu_clear'), InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
    return role_title, InlineKeyboardMarkup(keyboard)

async def execute_post_text(bot, job_info):
    try:
        msg = await bot.send_message(chat_id=job_info['chat_id'], text=job_info['text'], read_timeout=20)
        append_post_history(msg.message_id, job_info['user_id'])
        await bot.send_message(chat_id=LOG_CHANNEL_ID, text=create_log_message(job_info, "Text", job_info['text']), parse_mode='HTML', read_timeout=20)
        await bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=create_mod_log_message(job_info, "Text", job_info['text']), parse_mode='HTML', read_timeout=20)
    except: pass

async def execute_post_photo(bot, job_info):
    try:
        msg = await bot.send_photo(chat_id=job_info['chat_id'], photo=job_info['photo'], caption=job_info['caption'], read_timeout=30)
        append_post_history(msg.message_id, job_info['user_id'])
        await bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=job_info['photo'], caption=job_info['caption'])
        await bot.send_message(chat_id=LOG_CHANNEL_ID, text=create_log_message(job_info, "Photo"), parse_mode='HTML', read_timeout=30)
        await bot.send_photo(chat_id=MOD_LOG_CHANNEL_ID, photo=job_info['photo'], caption=job_info['caption'])
        await bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=create_mod_log_message(job_info, "Photo"), parse_mode='HTML', read_timeout=30)
    except: pass

async def persistent_queue_worker(context: ContextTypes.DEFAULT_TYPE):
    pq = load_persistent_queue()
    if not pq: return
    now_ts = datetime.datetime.now(TIMEZONE).timestamp()
    jobs_to_run = []
    remaining_jobs = []
    for job in pq:
        if now_ts >= job['scheduled_time']: jobs_to_run.append(job)
        else: remaining_jobs.append(job)
    if jobs_to_run:
        save_persistent_queue(remaining_jobs) 
        for job in jobs_to_run:
            if job['type'] == 'text': await execute_post_text(context.bot, job)
            else: await execute_post_photo(context.bot, job)

async def _schedule_post_direct(user, context: ContextTypes.DEFAULT_TYPE, submission: Dict[str, Any], target_chat_id: str):
    user_id = user.id
    is_privileged = is_owner_or_mod(user_id)
    if await is_user_restricted(user_id, context=context): return

    post_type = submission['type']
    text_to_check = submission['text']

    if post_type == 'photo' and not PHOTOS_ENABLED and not is_privileged:
        await context.bot.send_message(user_id, "❌ Photo posts are currently disabled.")
        return

    if check_for_banned_words(text_to_check) and not is_privileged:
        await context.bot.send_message(user_id, "❌ Your message contains words that are not allowed.")
        return

    if contains_link_text(text_to_check) and not LINKS_ENABLED and not is_privileged:
        await context.bot.send_message(user_id, "❌ Link sharing is currently disabled.")
        return

    now_tz = datetime.datetime.now(TIMEZONE)
    base_delay = get_seconds_until_active() if not is_bot_active() and not is_privileged else 0

    tier_times = load_tier_times()
    ad_last = tier_times.get('ad_global', now_tz)
    if ad_last < now_tz: ad_last = now_tz
    queue_start = max(now_tz, ad_last, now_tz + datetime.timedelta(seconds=base_delay))
    queue_duration = 120 
    scheduled_time = queue_start + datetime.timedelta(seconds=queue_duration)
    tier_times['ad_global'] = scheduled_time
    save_tier_times(tier_times)
    final_delay = (scheduled_time - now_tz).total_seconds()
    
    new_job = {
        'job_id': f"{time.time()}_{user.id}",
        'scheduled_time': scheduled_time.timestamp(),
        'chat_id': target_chat_id,
        'user_id': user.id,
        'user_name': user.first_name,
        'username': user.username,
        'is_immune': False,
        'category': 'Advertisement',
        'type': post_type,
        'tier': 'ad',
        'text': text_to_check if post_type == 'text' else None,
        'photo': submission['photo'] if post_type == 'photo' else None,
        'caption': text_to_check if post_type == 'photo' else None
    }
    
    pq = load_persistent_queue()
    queue_count = len(pq)
    pq.append(new_job)
    save_persistent_queue(pq)

    if base_delay == 0 and final_delay > 0:
        est_time_str = scheduled_time.strftime('%I:%M %p')
        await context.bot.send_message(
            user_id,
            f"🕒 <b>Advertisement Queued!</b>\n"
            f"Wait Time: <b>{format_duration(final_delay)} ({queue_count} queuing)</b>\n"
            f"Estimated Post Time: <b>{est_time_str}</b>\n\n"
            f"💡 <i>All ads follow a strict 2-minute global queue.</i>",
            parse_mode='HTML'
        )
    else:
        est_time_str = scheduled_time.strftime('%I:%M %p')
        await context.bot.send_message(user_id, f"🌙 Bot is currently in sleep mode. Your Ad is queued for {est_time_str} ({queue_count} queuing).")

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user = update.message.from_user
    user_id = user.id
    if user_id not in load_agreed_users() and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return
    if await is_user_restricted(user.id, update): return
    
    target_chat = None
    msg_id = None
    if hasattr(update.message, 'forward_origin') and update.message.forward_origin:
        origin = update.message.forward_origin
        if getattr(origin, 'type', '') == 'channel':
            target_chat = str(origin.chat.id)
            msg_id = getattr(origin, 'message_id', None)
    elif update.message.forward_from_chat:
        target_chat = str(update.message.forward_from_chat.id)
        msg_id = update.message.forward_from_message_id
        
    if not target_chat or not msg_id: return

    if target_chat == str(AD_CHANNEL_ID) or f"@{AD_CHANNEL_ID.lstrip('@')}" == target_chat:
        is_privileged = is_owner_or_mod(user_id)
        post_record = query_post_history(msg_id)
        
        if post_record['user_id'] is None:
            await update.message.reply_text("❌ <b>Action Rejected</b>\nThis message cannot be deleted by the bot because it was either posted manually by an Admin or it is too old.", parse_mode='HTML')
            return

        if post_record['user_id'] != user.id and not is_privileged:
            await update.message.reply_text("❌ Access Denied. Your authorship signatures do not match.")
            return

        try:
            await context.bot.delete_message(chat_id=AD_CHANNEL_ID, message_id=msg_id)
            await update.message.reply_text("🗑 Message successfully deleted from channel.")
            
            content = update.message.text or update.message.caption or "[Media with no caption]"
            raw_username = user.username
            display_username = f"@{html.escape(raw_username)}" if raw_username else "Not available"
            safe_user = html.escape(str(user.first_name))
            safe_uid = html.escape(str(user_id))
            safe_content = html.escape(content)
            
            owner_log_txt = f"🗑 <b>DELETION LOG</b>\n*By:* {safe_user} (<code>{safe_uid}</code>)\n*Username:* {display_username}\n*Msg ID:* <code>{msg_id}</code>\n*Original Content:*\n{safe_content}"
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=owner_log_txt, parse_mode='HTML')

            mod_log_txt = f"🗑 <b>DELETION LOG (Moderator View)</b>\n*By User ID:* <code>{safe_uid}</code>\n*Msg ID:* <code>{msg_id}</code>\n*Original Content:*\n{safe_content}"
            await context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=mod_log_txt, parse_mode='HTML')
        except Exception as e: await update.message.reply_text(f"❌ Could not delete: {e}")

async def add_mod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update.message.from_user.id): return False
    try:
        target = int(context.args[0])
        mods = load_moderators()
        mods.add(target)
        with open("moderators.txt", "w", encoding="utf-8") as f:
            for m in mods: f.write(f"{m}\n")
        await update.message.reply_text(f"👮‍♂️ User <code>{target}</code> is now a Moderator.", parse_mode='HTML')
        await log_admin_action(context, "Add Moderator", update.message.from_user, target, "Promoted to moderator")
        return True
    except: return False

async def remove_mod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update.message.from_user.id): return False
    try:
        target = int(context.args[0])
        mods = load_moderators()
        mods.discard(target)
        with open("moderators.txt", "w", encoding="utf-8") as f:
            for m in mods: f.write(f"{m}\n")
        await update.message.reply_text(f"✅ User <code>{target}</code> is no longer a Moderator.", parse_mode='HTML')
        await log_admin_action(context, "Remove Moderator", update.message.from_user, target, "Demoted from moderator")
        return True
    except: return False

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update.message.from_user.id): return False
    try:
        start_h = int(context.args[0])
        end_h = int(context.args[1])
        global START_HOUR, END_HOUR
        START_HOUR, END_HOUR = start_h, end_h
        save_time_settings()
        await update.message.reply_text(f"✅ Active time updated!\nStart: {format_time(START_HOUR)}\nEnd/Sleep: {format_time(END_HOUR)}")
        return True
    except: return False

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not is_owner(update.message.from_user.id): return
    msg_text = " ".join(context.args)
    if not msg_text: return
    users = load_known_users()
    await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    sent, failed = 0, 0
    for uid in list(users):
        try:
            await context.bot.send_message(chat_id=uid, text=msg_text)
            sent += 1
            await asyncio.sleep(0.05)
        except: failed += 1
    await update.message.reply_text(f"✅ Finished.\nSuccess: {sent}\nFailed: {failed}")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.message.from_user
    if not is_owner(user.id): return False
    try:
        target = int(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason provided."
        banned = load_banned_users()
        banned[target] = reason
        with open("banned_users.txt", "w", encoding="utf-8") as f:
            for u, r in banned.items(): f.write(f"{u},{r}\n")
            
        pq = load_persistent_queue()
        original_len = len(pq)
        pq = [j for j in pq if j['user_id'] != target]
        pq = recalculate_queues(pq)
        save_persistent_queue(pq)
        cleared_count = original_len - len(pq)
            
        await update.message.reply_text(f"🚫 User <code>{target}</code> banned.\n<b>Reason:</b> {html.escape(reason)}\n🗑 <b>Cleared {cleared_count} pending ads.</b>", parse_mode='HTML')
        await log_admin_action(context, "Ban", user, target, f"{reason} (Cleared {cleared_count} ads)")
        return True
    except: return False

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.message.from_user
    if not is_owner(user.id): return False
    try:
        target = int(context.args[0])
        banned = load_banned_users()
        if target in banned:
            del banned[target]
            with open("banned_users.txt", "w", encoding="utf-8") as f:
                for u, r in banned.items(): f.write(f"{u},{r}\n")
            await update.message.reply_text(f"✅ User <code>{target}</code> unbanned.", parse_mode='HTML')
            await log_admin_action(context, "Unban", user, target, "Ban lifted")
            return True
        else: return False
    except: return False

async def timeout_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.message.from_user
    if not is_owner_or_mod(user.id): return False
    try:
        target_id = int(context.args[0])
        minutes = int(context.args[1])
        reason = " ".join(context.args[2:]) if len(context.args) > 2 else "No reason provided."
        expiry_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        
        timeouts = load_timeouts()
        timeouts[target_id] = {'expiry': expiry_time.timestamp(), 'reason': reason}
        save_timeouts_to_disk(timeouts)
        
        pq = load_persistent_queue()
        original_len = len(pq)
        pq = [j for j in pq if j['user_id'] != target_id]
        pq = recalculate_queues(pq)
        save_persistent_queue(pq)
        cleared_count = original_len - len(pq)
        
        duration_str = format_duration(minutes * 60)
        await update.message.reply_text(f"⏳ User <code>{target_id}</code> timed out for {duration_str}.\n🗑 <b>Cleared {cleared_count} pending ads.</b>", parse_mode='HTML')
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📢 <b>Timeout Notice</b>\nYou have been timed out for {duration_str}.\n<b>Reason:</b> {html.escape(reason)}\n\n💡 <i>Tip: You can instantly lift this timeout by purchasing a 'Clear Timeout' pass for 200 Stars in our store: {SUB_BOT_URL}</i>",
                parse_mode='HTML'
            )
        except: pass
        await log_admin_action(context, "Timeout", user, target_id, f"{reason} (Cleared {cleared_count} ads)", duration_str)
        return True
    except: return False

async def remove_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.message.from_user
    if not is_owner_or_mod(user.id): return False
    try:
        target_id = int(context.args[0])
        timeouts = load_timeouts()
        if target_id in timeouts:
            del timeouts[target_id]
            save_timeouts_to_disk(timeouts)
            await update.message.reply_text(f"✅ Timeout removed for <code>{target_id}</code>.", parse_mode='HTML')
            await log_admin_action(context, "Remove Timeout", user, target_id, "Timeout lifted early")
            return True
        else: return False
    except: return False

async def add_banned_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update.message.from_user.id): return False
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        words = load_banned_words()
        words.add(word)
        with open("banned_words.txt", "w", encoding="utf-8") as f:
            for w in words: f.write(f"{w}\n")
        await update.message.reply_text(f"🚫 Banned word added: <code>{html.escape(word)}</code>", parse_mode='HTML')
        return True
    except: return False

async def remove_banned_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update.message.from_user.id): return False
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        words = load_banned_words()
        words.discard(word)
        with open("banned_words.txt", "w", encoding="utf-8") as f:
            for w in words: f.write(f"{w}\n")
        await update.message.reply_text(f"✅ Banned word removed: <code>{html.escape(word)}</code>", parse_mode='HTML')
        return True
    except: return False

async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    if await is_user_restricted(user_id, update): return
    pq = load_persistent_queue()
    original_len = len(pq)
    pq = [j for j in pq if j['user_id'] != user_id]
    pq = recalculate_queues(pq)
    save_persistent_queue(pq)
    count = original_len - len(pq)
    await update.message.reply_text(f"✅ Cleared {count} of your pending ads from the queue.")

async def clear_all_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    if not is_owner_or_mod(update.message.from_user.id): return
    save_persistent_queue([])
    save_tier_times({})
    await update.message.reply_text("✅ Master Ad Queue has been cleared.")

async def gift_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update.message.from_user.id): return False
    try:
        target_uid = int(context.args[0])
        tier_code = context.args[1].lower()
        days = int(context.args[2])
        if tier_code not in ['tier1', 'tier2', 'club']: return False
        now = time.time()
        expiry = now + (days * 86400)
        with open("active_subscriptions.txt", "a", encoding="utf-8") as f: f.write(f"{target_uid},{tier_code},{expiry}\n")
        tier_name = tier_code.title()
        await update.message.reply_text(f"🎁 Successfully gifted <b>{tier_name}</b> ({days} days) to user <code>{target_uid}</code>!", parse_mode='HTML')
        await log_admin_action(context, "Gift Subscription", update.message.from_user, target_uid, f"Gifted {tier_name}", f"{days} days")
        try: await context.bot.send_message(chat_id=target_uid, text=f"🎁 <b>You've received a gift!</b>\nThe Developer has granted you <b>{tier_name}</b> access for {days} days.", parse_mode='HTML')
        except: pass
        return True
    except: return False

async def revoke_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update.message.from_user.id): return False
    try:
        target_uid = int(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason provided"
        revoked = False
        remaining_lines = []
        if os.path.exists("active_subscriptions.txt"):
            with open("active_subscriptions.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        u_id, tier, expiry = line.strip().split(',')
                        if int(u_id) == target_uid: revoked = True
                        else: remaining_lines.append(line)
        if revoked:
            with open("active_subscriptions.txt", "w", encoding="utf-8") as f: f.writelines(remaining_lines)
            await update.message.reply_text(f"✅ Subscription for user <code>{target_uid}</code> has been REVOKED.", parse_mode='HTML')
            await log_admin_action(context, "Revoke Subscription", update.message.from_user, target_uid, reason)
            try: await context.bot.send_message(chat_id=target_uid, text=f"⚠️ <b>Subscription Revoked</b>\nYour subscription has been revoked by the Developer.\n<b>Reason:</b> {html.escape(reason)}", parse_mode='HTML')
            except: pass
            return True
        else: return False
    except: return False

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return AWAITING_HELP_MESSAGE
    user_id = update.message.from_user.id
    if user_id not in load_agreed_users() and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return ConversationHandler.END
    if await is_user_restricted(user_id, update): return ConversationHandler.END
    await update.message.reply_text("Send your query. It will be forwarded to the owner.")
    return AWAITING_HELP_MESSAGE

async def forward_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.forward_message(chat_id=OWNER_ID, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
    await update.message.reply_text("Sent to owner.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return ConversationHandler.END
    user_id = update.message.from_user.id
    if user_id in action_states:
        del action_states[user_id]
        await update.message.reply_text("✅ Action cancelled. Returned to normal mode.")
        return ConversationHandler.END
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    if user_id not in load_agreed_users() and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return
    if await is_user_restricted(user_id, update): return
    save_user(user_id)
    if user_id in action_states: del action_states[user_id]
    
    role_title, reply_markup = get_main_menu(user_id)
    greeting = f"👋 Hello! (Role: {role_title})\n\n" if role_title != "User" else "👋 Hello!\n\n"
    await update.message.reply_text(
        f"{greeting}Send any text or photo containing your Advertisement to post it anonymously to the Marketplace.\n\nClick a button below for more options:",
        reply_markup=reply_markup
    )

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    user_id = query.from_user.id

    if query.data == 'submit_ad':
        submission = pending_submissions.get(user_id)
        if not submission:
            await query.edit_message_text("❌ Session expired. Please send your message again.")
            return
        
        has_photo = submission['type'] == 'photo'
        text_content = submission['text']
        
        text_nospace = text_content.replace(' ', '').replace('-', '')
        phone_pattern = r'(\+?6?01\d{8,9})'
        has_phone = bool(re.search(phone_pattern, text_nospace))
        has_link = contains_link_text(text_content)
        has_username = '@' in text_content
        
        if not (has_photo or has_phone or has_link or has_username):
            await query.edit_message_text(
                "❌ <b>Advertisement Rejected</b>\n\nAds MUST contain at least one of the following:\n- A photo\n- A web link\n- A phone number\n- A Telegram username (@)\n\nPlease edit your message and try again.", 
                parse_mode='HTML'
            )
            del pending_submissions[user_id]
            return
            
        await query.edit_message_text(f"✅ Processing Advertisement...")
        await _schedule_post_direct(query.from_user, context, submission, AD_CHANNEL_ID)
        del pending_submissions[user_id]
        return

    elif query.data == 'submit_cancel':
        if user_id in pending_submissions: del pending_submissions[user_id]
        await query.edit_message_text("❌ Submission cancelled.")
        return

    if query.data == 'tc_agree':
        save_agreed_user(user_id)
        role_title, reply_markup = get_main_menu(user_id)
        greeting = f"👋 Hello! (Role: {role_title})\n\n" if role_title != "User" else "👋 Hello!\n\n"
        await query.edit_message_text(
            f"✅ Thank you for agreeing to the Marketplace Terms!\n\n{greeting}Send any text or photo containing your Advertisement to post it anonymously to the Marketplace.",
            reply_markup=reply_markup
        )
        return
    elif query.data == 'tc_guide':
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to T&C", callback_data='tc_back')]])
        await query.edit_message_text(text=GUIDE_TEXT, parse_mode='HTML', reply_markup=markup)
        return
    elif query.data == 'tc_back':
        await query.edit_message_text(text=TNC_TEXT, reply_markup=get_tnc_keyboard())
        return
    if query.data == 'menu_back':
        if user_id in action_states: del action_states[user_id]
        role_title, reply_markup = get_main_menu(user_id)
        greeting = f"👋 Hello! (Role: {role_title})\n\n" if role_title != "User" else "👋 Hello!\n\n"
        await query.edit_message_text(f"{greeting}Send any text or photo containing your Advertisement to post it anonymously to the Marketplace.", reply_markup=reply_markup)
    elif query.data == 'menu_guide':
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=GUIDE_TEXT, parse_mode='HTML', reply_markup=markup)
        
    elif query.data == 'menu_clear':
        pq = load_persistent_queue()
        original_len = len(pq)
        pq = [j for j in pq if j['user_id'] != user_id]
        pq = recalculate_queues(pq)
        save_persistent_queue(pq)
        count = original_len - len(pq)
        await query.edit_message_text(text=f"✅ Cleared {count} of your pending ads from the queue.")
        
    elif query.data == 'menu_clear_global':
        if not is_owner_or_mod(user_id): return
        save_persistent_queue([])
        save_tier_times({})
        await query.edit_message_text(text="✅ Master Ad Queue has been cleared.")
        
    elif query.data == 'menu_close':
        if user_id in action_states: del action_states[user_id]
        await query.edit_message_text(text="👋 Menu closed. Send a message or photo to advertise.")
        
    elif query.data == 'menu_my_status':
        tier = get_user_tier(user_id)
        txt = (
            f"👤 <b>Runtime Profile Audit</b>\n\n"
            f"🎫 <b>Owned Access Tier:</b> <code>{tier.title()}</code>\n\n"
            f"📊 <b>Active Tier Privileges:</b>\n"
            f"• Market Queue Duration: <code>2 minutes (Fixed Global)</code>\n"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_insights':
        pq = load_persistent_queue()
        ad_count = len(pq)

        tier_times = load_tier_times()
        now_tz = datetime.datetime.now(TIMEZONE)
        
        lines = ["📈 <b>Queue Insights (Current Wait Times)</b>\n"]
        
        main_counts = get_main_queue_counts()
        main_times = get_main_tier_times()
        
        lines.append("<b>-- CONFESSIONS --</b>")
        for tier_code, cfg in TIER_CONFIG.items():
            count = main_counts.get(tier_code, 0)
            if cfg['personal_queue_duration'] == 0:
                lines.append(f"• <b>{cfg['name']}:</b> Instant ({count} queuing)")
            else:
                last_scheduled = main_times.get(tier_code, now_tz)
                wait_sec = max(0, (last_scheduled - now_tz).total_seconds())
                tier_wait = wait_sec + cfg['personal_queue_duration']
                lines.append(f"• <b>{cfg['name']}:</b> {format_duration(tier_wait)} ({count} queuing)")
        
        lines.append("\n<b>-- ADVERTISEMENTS --</b>")
        ad_last_scheduled = tier_times.get('ad_global', now_tz)
        ad_wait_sec = max(0, (ad_last_scheduled - now_tz).total_seconds())
        ad_wait = ad_wait_sec + 120
        lines.append(f"• <b>Marketplace Ads:</b> {format_duration(ad_wait)} ({ad_count} queuing)")
        
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text="\n".join(lines), parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_stats':
        if not is_owner(user_id): return
        uptime_str = str(datetime.datetime.now() - BOT_START_TIME).split('.')[0] 
        msg = (
            f"📊 <b>Market Bot Statistics</b>\n\n"
            f"👥 <b>Total Users:</b> <code>{len(load_known_users())}</code>\n"
            f"✅ <b>Agreed Users (Market):</b> <code>{len(load_agreed_users())}</code>\n"
            f"🚫 <b>Banned Users:</b> <code>{len(load_banned_users())}</code>\n"
            f"👮‍♂️ <b>Moderators:</b> <code>{len(load_moderators())}</code>\n"
            f"⏳ <b>Uptime:</b> <code>{uptime_str}</code>\n\n"
            f"🌙 Active Mode: {'✅ Yes' if is_bot_active() else '❌ No (Sleep/Queue Mode)'}"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=msg, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_tnc_stats':
        if not is_owner(user_id): return
        total_users = len(load_known_users())
        agreed_users = len(load_agreed_users())
        pending_users = total_users - agreed_users
        msg = (
            f"📜 <b>Terms & Conditions Stats</b>\n\n"
            f"👥 <b>Total Users:</b> <code>{total_users}</code>\n"
            f"✅ <b>Agreed (Market):</b> <code>{agreed_users}</code>\n"
            f"⏳ <b>Pending Agreement:</b> <code>{pending_users}</code>\n\n"
            f"<i>Note: Users in the 'Pending' list cannot send ads or use the bot until they click 'I Agree' to the new rules.</i>"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=msg, parse_mode='HTML', reply_markup=markup)
        
    elif query.data == 'menu_toggle_links':
        if not is_owner(user_id): return
        global LINKS_ENABLED
        LINKS_ENABLED = not LINKS_ENABLED
        status = 'ENABLED' if LINKS_ENABLED else 'DISABLED'
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=f"🔗 Link restriction is now {'OFF' if LINKS_ENABLED else 'ON'}.", reply_markup=markup)
        await context.bot.send_message(chat_id=AD_CHANNEL_ID, text=f"📢 Notice: Link sharing has been {status} by the administrator.")

    elif query.data == 'menu_toggle_photos':
        if not is_owner(user_id): return
        global PHOTOS_ENABLED
        PHOTOS_ENABLED = not PHOTOS_ENABLED
        status = 'ENABLED' if PHOTOS_ENABLED else 'DISABLED'
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=f"📸 Photo posts are now {'ENABLED' if PHOTOS_ENABLED else 'DISABLED'}.", reply_markup=markup)
        await context.bot.send_message(chat_id=AD_CHANNEL_ID, text=f"📢 Notice: Photo confessions have been {status} by the administrator.")

    elif query.data == 'menu_active_time':
        if not is_owner(user_id): return
        txt = (
            f"⏰ <b>Active Time Panel</b>\n\n<b>Current Start Time:</b> {format_time(START_HOUR)}\n<b>Current End (Sleep) Time:</b> {format_time(END_HOUR)}\n\n"
            f"<b>How to change it:</b>\nType <code>/settime &lt;start_hour&gt; &lt;end_hour&gt;</code> using the 24-hour clock.\n\n<i>Example for 9 PM to 6 PM:</i>\n<code>/settime 21 18</code>"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_manage_mods':
        if not is_owner(user_id): return
        txt = "👮‍♂️ <b>Moderator Management</b>\nChoose an action below:"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Mod", callback_data='trig_addmod'), InlineKeyboardButton("➖ Remove Mod", callback_data='trig_rmmod')],
            [InlineKeyboardButton("◀️ Back", callback_data='menu_back')]
        ])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_manage_bans':
        if not is_owner(user_id): return
        txt = "🚫 <b>Ban Management (Owner Only)</b>\nChoose an action below:"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔨 Ban User", callback_data='trig_ban'), InlineKeyboardButton("✅ Unban User", callback_data='trig_unban')],
            [InlineKeyboardButton("◀️ Back", callback_data='menu_back')]
        ])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_manage_timeouts':
        if not is_owner_or_mod(user_id): return
        txt = "⏳ <b>Timeout Management</b>\nChoose an action below:"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱️ Timeout User", callback_data='trig_timeout'), InlineKeyboardButton("✅ Remove Timeout", callback_data='trig_rmtimeout')],
            [InlineKeyboardButton("◀️ Back", callback_data='menu_back')]
        ])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_manage_words':
        if not is_owner_or_mod(user_id): return
        txt = "🤬 <b>Banned Words Management</b>\nChoose an action below:"
        buttons = [[InlineKeyboardButton("👁️ View Words", callback_data='menu_view_words')]]
        if is_owner(user_id):
            buttons.append([InlineKeyboardButton("➕ Add Word", callback_data='trig_addword'), InlineKeyboardButton("➖ Remove Word", callback_data='trig_rmword')])
        buttons.append([InlineKeyboardButton("◀️ Back", callback_data='menu_back')])
        markup = InlineKeyboardMarkup(buttons)
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_view_words':
        current_words = load_banned_words()
        msg = ", ".join(sorted(current_words)) if current_words else "None."
        txt = f"🤬 <b>Current Banned Words:</b>\n<code>{html.escape(msg)}</code>"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_manage_words' if is_owner_or_mod(user_id) else 'menu_back')]])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data.startswith('trig_'):
        owner_only_actions = ['trig_ban', 'trig_unban', 'trig_addword', 'trig_rmword', 'trig_addmod', 'trig_rmmod', 'trig_settime', 'trig_gift', 'trig_revoke']
        if query.data in owner_only_actions and not is_owner(user_id):
            await query.edit_message_text("❌ Only the Owner/Developer can perform this action.")
            return

        action_states[user_id] = query.data
        prompts = {
            'trig_ban': "🔨 <b>Ban User</b>\nPlease send the target User ID and Reason.\n<i>Example:</i> <code>123456789 Spamming</code>",
            'trig_unban': "✅ <b>Unban User</b>\nPlease send the target User ID to unban.\n<i>Example:</i> <code>123456789</code>",
            'trig_timeout': "⏱️ <b>Timeout User</b>\nPlease send the User ID, Minutes, and Reason.\n<i>Example:</i> <code>123456789 60 Flooding chat</code>",
            'trig_rmtimeout': "✅ <b>Remove Timeout</b>\nPlease send the target User ID to remove timeout.\n<i>Example:</i> <code>123456789</code>",
            'trig_addmod': "➕ <b>Add Moderator</b>\nPlease send the User ID to promote.\n<i>Example:</i> <code>123456789</code>",
            'trig_rmmod': "➖ <b>Remove Moderator</b>\nPlease send the User ID to demote.\n<i>Example:</i> <code>123456789</code>",
            'trig_addword': "➕ <b>Add Banned Word</b>\nPlease send the word you want to ban.\n<i>Example:</i> <code>badword</code>",
            'trig_rmword': "➖ <b>Remove Banned Word</b>\nPlease send the word you want to unban.\n<i>Example:</i> <code>badword</code>",
            'trig_settime': "✏️ <b>Set Active Time</b>\nPlease send the Start and End hours (24h format).\n<i>Example for 9PM to 6PM:</i> <code>21 18</code>",
            'trig_gift': "🎁 <b>Gift Subscription</b>\nPlease send the target User ID, Tier Code, and Days.\n<i>Example:</i> <code>123456789 tier1 14</code>",
            'trig_revoke': "❌ <b>Revoke Subscription</b>\nPlease send the User ID and Reason.\n<i>Example:</i> <code>123456789 Rule violation</code>"
        }
        cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='menu_back')]])
        await query.edit_message_text(text=prompts.get(query.data, "Please provide input.") + "\n\nType /cancel to abort.", parse_mode='HTML', reply_markup=cancel_markup)

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    if user_id not in load_agreed_users() and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return

    text_stripped = update.message.text.strip()
    
    if is_owner_or_mod(user_id):
        test_text = text_stripped
        if test_text.startswith('/'): test_text = test_text[1:]
        parts = test_text.split()
        first_word = parts[0].lower() if parts else ""
        
        admin_commands = {
            'timeout': timeout_user, 'untimeout': remove_timeout, 'ban': ban_user, 'unban': unban_user,
            'addmod': add_mod, 'removemod': remove_mod, 'addban': add_banned_word, 'removeban': remove_banned_word,
            'settime': set_time, 'gift': gift_subscription, 'revoke': revoke_subscription,
            'clearqueue': clear_queue, 'clearallqueue': clear_all_queue, 'broadcast': broadcast
        }
        if first_word in admin_commands:
            context.args = parts[1:]
            if user_id in action_states: del action_states[user_id]
            await admin_commands[first_word](update, context)
            return

    if user_id in action_states:
        state = action_states[user_id]
        context.args = text_stripped.split()
        success = False
        if state == 'trig_ban': success = await ban_user(update, context)
        elif state == 'trig_unban': success = await unban_user(update, context)
        elif state == 'trig_timeout': success = await timeout_user(update, context)
        elif state == 'trig_rmtimeout': success = await remove_timeout(update, context)
        elif state == 'trig_addmod': success = await add_mod(update, context)
        elif state == 'trig_rmmod': success = await remove_mod(update, context)
        elif state == 'trig_addword': success = await add_banned_word(update, context)
        elif state == 'trig_rmword': success = await remove_banned_word(update, context)
        elif state == 'trig_settime': success = await set_time(update, context)
        elif state == 'trig_gift': success = await gift_subscription(update, context)
        elif state == 'trig_revoke': success = await revoke_subscription(update, context)
            
        if success: del action_states[user_id]
        return

    if text_stripped.lower() == 'delete':
        is_privileged = is_owner_or_mod(user_id)
        if not is_privileged:
            expiry_time = time.time() + 60
            timeouts = load_timeouts()
            timeouts[user_id] = {'expiry': expiry_time, 'reason': "Invalid deletion attempt."}
            save_timeouts_to_disk(timeouts)
            pq = load_persistent_queue()
            pq = [j for j in pq if j['user_id'] != user_id]
            pq = recalculate_queues(pq)
            save_persistent_queue(pq)
            
            await update.message.reply_text(f"⚠️ <b>Timeout Applied (1 Minute)</b>\n\nYou typed 'delete'. To delete a post, you must forward the actual message from the channel here.\n\n{GUIDE_TEXT}", parse_mode='HTML')
            try: await context.bot.send_message(chat_id=user_id, text=f"📢 <b>Timeout Notice</b>\nYou have been timed out for 1 minute.\n<b>Reason:</b> Invalid deletion attempt.\n\n💡 <i>Tip: You can instantly lift this timeout by purchasing a 'Clear Timeout' pass for 200 Stars in our store: {SUB_BOT_URL}</i>", parse_mode='HTML')
            except: pass
            await log_admin_action(context, "Timeout (Auto)", "System", user_id, "Invalid deletion attempt ('delete')", "1 minute")
            return
        else:
            await update.message.reply_text("To delete a post, you need to forward the message from the channel. Just typing 'delete' does not work.")
            return

    pending_submissions[user_id] = {'type': 'text', 'text': text_stripped, 'photo': None}
    keyboard = [[InlineKeyboardButton("🛒 Submit as Advertisement", callback_data="submit_ad")], [InlineKeyboardButton("❌ Cancel", callback_data="submit_cancel")]]
    await update.message.reply_text("Where would you like to post this?", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    if user_id not in load_agreed_users() and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return
    if user_id in action_states:
        await update.message.reply_text("❌ Action cancelled. I was expecting text for the command.")
        del action_states[user_id]
        return

    text_stripped = update.message.caption.strip() if update.message.caption else ""
    pending_submissions[user_id] = {'type': 'photo', 'text': text_stripped, 'photo': update.message.photo[-1].file_id}
    keyboard = [[InlineKeyboardButton("🛒 Submit as Advertisement", callback_data="submit_ad")], [InlineKeyboardButton("❌ Cancel", callback_data="submit_cancel")]]
    await update.message.reply_text("Where would you like to post this photo?", reply_markup=InlineKeyboardMarkup(keyboard))

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, NetworkError): return
    print(f"Update {update} caused error {context.error}")

async def post_init(application: Application):
    now_str = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
    try: await application.bot.send_message(chat_id=OWNER_ID, text=f"✅ Market Bot is up! Dedicated Market Mode Active. Started at {now_str}")
    except: pass

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).read_timeout(30).connect_timeout(30).build()
    
    application.job_queue.run_repeating(persistent_queue_worker, interval=5, first=5)
    application.add_error_handler(error_handler)
    
    for cmd, func in [("start", start), ("cancel", cancel), ("settime", set_time), ("broadcast", broadcast), ("ban", ban_user), ("unban", unban_user), ("addmod", add_mod), ("removemod", remove_mod), ("timeout", timeout_user), ("untimeout", remove_timeout), ("addban", add_banned_word), ("removeban", remove_banned_word), ("revoke", revoke_subscription), ("gift", gift_subscription), ("clearqueue", clear_queue), ("clearallqueue", clear_all_queue)]:
        application.add_handler(CommandHandler(cmd, func))

    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('help', help_command)],
        states={AWAITING_HELP_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, forward_help)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    ))

    application.add_handler(CallbackQueryHandler(menu_button_handler, pattern='^(menu_|trig_|toggle_|tc_|submit_)'))
    application.add_handler(MessageHandler(filters.FORWARDED, handle_delete))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, handle_photo_input))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text_input))

    print("--- Market Bot is Online ---")
    application.run_polling()

if __name__ == '__main__':
    main()
